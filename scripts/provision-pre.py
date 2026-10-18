#!/usr/bin/env python3
"""Explicit runtime provisioning; never imported or executed by overlay deployment."""
import argparse
import base64
import json
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request


def kubectl(*args, data=None):
    return subprocess.check_output(['kubectl', *args], input=data, stderr=subprocess.PIPE)


def read_secret(namespace, name):
    obj = json.loads(kubectl('-n', namespace, 'get', 'secret', name, '-o', 'json'))
    return {key: base64.b64decode(value).decode() for key, value in obj['data'].items()}


def apply_secret(namespace, name, values, kind='Opaque'):
    obj = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': name, 'namespace': namespace},
           'type': kind, 'stringData': values}
    kubectl('apply', '--server-side', '--field-manager=scaffoldops-pre-provision', '-f', '-',
            data=json.dumps(obj).encode())
    print(f'{namespace}/{name}: ready')


def exists(namespace, name):
    return bool(kubectl('-n', namespace, 'get', 'secret', name, '--ignore-not-found', '-o', 'name').strip())


def provision_runtime():
    for name in ('generated-pre', 'scaffoldops-pre'):
        obj = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': name}}
        kubectl('apply', '-f', '-', data=json.dumps(obj).encode())
    if not exists('scaffoldops-pre', 'minio-credentials'):
        apply_secret('scaffoldops-pre', 'minio-credentials', {
            'MINIO_ROOT_USER': 'scaffoldops-pre', 'MINIO_ROOT_PASSWORD': secrets.token_urlsafe(32)})
    minio = read_secret('scaffoldops-pre', 'minio-credentials')
    apply_secret('scaffoldops-pre', 'generator-worker-minio', {
        'access-key': minio['MINIO_ROOT_USER'], 'secret-key': minio['MINIO_ROOT_PASSWORD']})
    for namespace in ('scaffoldops-pre', 'generated-pre'):
        if not exists(namespace, 'docker-hub-pull-secret'):
            values = read_secret('scaffoldops-dev', 'docker-hub-pull-secret')
            apply_secret(namespace, 'docker-hub-pull-secret', values, 'kubernetes.io/dockerconfigjson')
    if not exists('scaffoldops-pre', 'docker-hub-credentials'):
        apply_secret('scaffoldops-pre', 'docker-hub-credentials',
                     read_secret('scaffoldops-dev', 'docker-hub-credentials'))
    account = json.loads(kubectl('-n', 'generated-pre', 'get', 'serviceaccount', 'default', '-o', 'json'))
    pulls = account.get('imagePullSecrets', [])
    if not any(ref['name'] == 'docker-hub-pull-secret' for ref in pulls):
        pulls.append({'name': 'docker-hub-pull-secret'})
        kubectl('-n', 'generated-pre', 'patch', 'serviceaccount', 'default', '--type=merge',
                '-p', json.dumps({'imagePullSecrets': pulls}))
    print('PRE runtime secrets provisioned; credentials were not logged.')


def provision_database():
    # No passwords on argv; the container uses its existing local admin identity.
    # Never migrate, drop, alter or connect to the legacy keycloakdb database.
    sql = r"""SELECT 'CREATE DATABASE keycloakpredb OWNER keycloakuser'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'keycloakpredb')\gexec
"""
    kubectl('-n', 'scaffoldops-pre', 'exec', '-i', 'deployment/postgres', '--',
            'bash', '-ec', 'exec psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"',
            data=sql.encode())
    print('scaffoldops-pre/keycloakpredb: ready; legacy keycloakdb unchanged')


def provision_keycloak(port):
    forward = subprocess.Popen(['kubectl', '-n', 'security', 'port-forward',
                                '--address=127.0.0.1', 'svc/keycloak-pre', f'{port}:8080'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(120):
            if forward.poll() is not None:
                raise RuntimeError('PRE port-forward exited; check service availability or choose --port')
            try:
                with urllib.request.urlopen(base + '/realms/master/.well-known/openid-configuration', timeout=2):
                    break
            except (OSError, urllib.error.URLError):
                time.sleep(2)
        else:
            raise RuntimeError('Keycloak PRE did not become available')
        admin = read_secret('security', 'keycloak-pre-admin')
        form = urllib.parse.urlencode({'grant_type': 'password', 'client_id': 'admin-cli',
                                      'username': admin['KC_BOOTSTRAP_ADMIN_USERNAME'],
                                      'password': admin['KC_BOOTSTRAP_ADMIN_PASSWORD']}).encode()
        try:
            with urllib.request.urlopen(base + '/realms/master/protocol/openid-connect/token', form, timeout=15) as response:
                token = json.load(response)['access_token']
        except urllib.error.HTTPError:
            raise RuntimeError('PRE admin credentials did not authenticate; no password was changed') from None

        def api(method, path, body=None):
            request = urllib.request.Request(base + path, method=method,
                    data=json.dumps(body).encode() if body is not None else None,
                    headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = response.read()
                return json.loads(payload) if payload else None

        realm = 'scaffoldops-pre'
        if not any(item['realm'] == realm for item in api('GET', '/admin/realms')):
            api('POST', '/admin/realms', {'realm': realm, 'enabled': True, 'registrationAllowed': False})
        for client_id, secret_name in [('scaffoldops-generator-worker', 'generator-api-worker-client'),
                                       ('deployment-worker', 'deployment-worker-oauth')]:
            path = '/admin/realms/' + realm + '/clients'
            query = '?' + urllib.parse.urlencode({'clientId': client_id})
            clients = api('GET', path + query)
            if not clients:
                api('POST', path, {'clientId': client_id, 'enabled': True, 'protocol': 'openid-connect',
                    'publicClient': False, 'serviceAccountsEnabled': True,
                    'standardFlowEnabled': False, 'directAccessGrantsEnabled': False})
                clients = api('GET', path + query)
            client = clients[0]
            if client.get('publicClient') or not client.get('serviceAccountsEnabled') or not client.get('enabled'):
                client.update(publicClient=False, serviceAccountsEnabled=True, enabled=True)
                api('PUT', path + '/' + client['id'], client)
            credential = api('GET', path + '/' + client['id'] + '/client-secret')['value']
            values = {'client-secret': credential}
            token_url = 'http://keycloak-pre.security.svc.cluster.local:8080/realms/' + realm + '/protocol/openid-connect/token'
            if secret_name == 'deployment-worker-oauth':
                values['token-url'] = token_url
            apply_secret('scaffoldops-pre', secret_name, values)
            form = urllib.parse.urlencode({'grant_type': 'client_credentials', 'client_id': client_id,
                                          'client_secret': credential}).encode()
            with urllib.request.urlopen(base + '/realms/' + realm + '/protocol/openid-connect/token', form, timeout=15) as response:
                if not json.load(response).get('access_token'):
                    raise RuntimeError('Missing PRE service token')
            print(f'PRE realm client {client_id}: token issuance verified')
    finally:
        forward.terminate()
        try:
            forward.wait(timeout=10)
        except subprocess.TimeoutExpired:
            forward.kill()
            forward.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('runtime', 'database', 'keycloak', 'all'))
    parser.add_argument('--port', type=int, default=19080)
    args = parser.parse_args()
    if args.phase in ('runtime', 'all'):
        provision_runtime()
    if args.phase in ('database', 'all'):
        provision_database()
    if args.phase in ('keycloak', 'all'):
        provision_keycloak(args.port)


if __name__ == '__main__':
    main()
