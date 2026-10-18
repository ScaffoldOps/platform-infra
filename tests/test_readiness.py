import contextlib
import copy
import importlib.util
import io
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import yaml


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / 'scripts' / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


readiness = module('readiness', 'validate-readiness.py')
provision = module('provision', 'provision-pre.py')


class IsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rendered, cls.index = readiness.render('pre')

    def rejected(self, mutation, message):
        objects = copy.deepcopy(list(self.index.values()))
        mutation(objects)
        with patch.object(readiness.subprocess, 'check_output', return_value=yaml.safe_dump_all(objects)):
            with self.assertRaisesRegex(ValueError, message):
                readiness.render('pre')

    def test_all_environments(self):
        for environment in ('dev', 'local-dev', 'pre'):
            readiness.render(environment)

    def test_pre_secret_rejected(self):
        self.rejected(lambda objects: objects.append({'apiVersion': 'v1', 'kind': 'Secret',
                      'metadata': {'name': 'forbidden', 'namespace': 'scaffoldops-pre'}}), 'must not manage')

    def test_dev_workload_rejected(self):
        self.rejected(lambda objects: objects.append({'apiVersion': 'apps/v1', 'kind': 'Deployment',
                      'metadata': {'name': 'dev', 'namespace': 'scaffoldops-dev'}}), 'isolation boundary')

    def test_missing_job_rejected(self):
        self.rejected(lambda objects: objects.remove(next(obj for obj in objects
                      if obj['metadata']['name'] == 'kafka-topic-bootstrap')), 'missing resources')

    def test_legacy_database_rejected(self):
        def mutate(objects):
            deployment = next(obj for obj in objects if obj['kind'] == 'Deployment'
                              and obj['metadata']['name'] == 'keycloak-pre')
            env = deployment['spec']['template']['spec']['containers'][0]['env']
            next(item for item in env if item['name'] == 'KC_DB_URL_DATABASE')['value'] = 'keycloakdb'
        self.rejected(mutate, 'legacy keycloakdb')

    def test_preflight_missing_keys_fails_without_values(self):
        output = io.StringIO()
        result = subprocess.CompletedProcess([], 0, stdout='MINIO_ROOT_USER\n', stderr='')
        with patch.object(readiness, 'render', return_value=(self.rendered, self.index)):
            with patch.object(readiness.subprocess, 'run', return_value=result) as run:
                with contextlib.redirect_stderr(output), contextlib.redirect_stdout(output):
                    with self.assertRaisesRegex(ValueError, 'preflight failed'):
                        readiness.preflight('pre')
        self.assertIn('MINIO_ROOT_PASSWORD', output.getvalue())
        self.assertIn('go-template=', ' '.join(run.call_args.args[0]))
        self.assertNotIn('-o json', ' '.join(run.call_args.args[0]))

    def test_missing_keycloak_readiness_rejected(self):
        def mutate(objects):
            deployment = next(obj for obj in objects if obj['kind'] == 'Deployment'
                              and obj['metadata']['name'] == 'keycloak-pre')
            del deployment['spec']['template']['spec']['containers'][0]['readinessProbe']
        self.rejected(mutate, 'readinessProbe')


class ProvisioningTests(unittest.TestCase):
    def test_database_creation_never_alters_legacy_or_passwords(self):
        with patch.object(provision, 'kubectl') as kubectl, contextlib.redirect_stdout(io.StringIO()):
            provision.provision_database()
        args, kwargs = kubectl.call_args
        sql = kwargs['data'].decode()
        self.assertIn('keycloakpredb OWNER keycloakuser', sql)
        self.assertIn('WHERE NOT EXISTS', sql)
        self.assertNotIn('ALTER', sql)
        self.assertNotIn('DROP', sql)
        self.assertNotIn('PASSWORD', sql)
        self.assertEqual(args[1], 'scaffoldops-pre')

    def test_runtime_preserves_existing_credentials_and_pull_references(self):
        values = {'MINIO_ROOT_USER': 'test-user', 'MINIO_ROOT_PASSWORD': 'test-only'}
        account = b'{"imagePullSecrets":[{"name":"other"},{"name":"docker-hub-pull-secret"}]}'
        with patch.object(provision, 'exists', return_value=True):
            with patch.object(provision, 'read_secret', return_value=values) as read:
                with patch.object(provision, 'apply_secret') as apply:
                    with patch.object(provision, 'kubectl', return_value=account) as kubectl:
                        with contextlib.redirect_stdout(io.StringIO()):
                            provision.provision_runtime()
        read.assert_called_once_with('scaffoldops-pre', 'minio-credentials')
        apply.assert_called_once_with('scaffoldops-pre', 'generator-worker-minio', {
            'access-key': 'test-user', 'secret-key': 'test-only'})
        self.assertFalse(any('patch' in call.args for call in kubectl.call_args_list))


if __name__ == '__main__':
    unittest.main()
