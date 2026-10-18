"""Integration test using one disposable tmpfs-only Docker container, never Kubernetes."""
import importlib.util
from pathlib import Path
import subprocess
import time
import unittest
import uuid


class PostgresBootstrapTests(unittest.TestCase):
    def test_new_database_and_nonrotating_repeat(self):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('readiness', root / 'scripts/validate-readiness.py')
        readiness = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(readiness)
        _, index = readiness.render('pre')
        scripts = index[('ConfigMap', 'scaffoldops-pre', 'postgres-init-scripts')]['data']
        name = 'readiness-postgres-' + uuid.uuid4().hex[:12]

        def docker(*args, data=None):
            return subprocess.check_output(['docker', *args], input=data, stderr=subprocess.PIPE)

        def sql(statement):
            return docker('exec', '-i', name, 'psql', '-U', 'postgres', '-d', 'postgres',
                          '-v', 'ON_ERROR_STOP=1', '-At', data=statement.encode()).strip()

        docker('run', '--detach', '--rm', '--name', name, '--tmpfs', '/var/lib/postgresql/data',
               '-e', 'POSTGRES_PASSWORD=disposable-test-only', 'postgres:16')
        try:
            for _ in range(60):
                try:
                    if sql('SELECT 1') == b'1':
                        break
                except subprocess.CalledProcessError:
                    pass
                time.sleep(1)
            else:
                self.fail('Disposable PostgreSQL did not become ready')
            sql("CREATE DATABASE keycloakdb; ")
            docker('exec', name, 'psql', '-U', 'postgres', '-d', 'keycloakdb', '-c',
                   'CREATE TABLE legacy_marker (value integer); INSERT INTO legacy_marker VALUES (42)')
            env = ['-e', 'POSTGRES_USER=postgres', '-e', 'POSTGRES_DB=postgres', '-e',
                   'POSTGRES_PASSWORD=disposable-test-only']
            for key in sorted(readiness.POSTGRES_KEYS - {'POSTGRES_USER', 'POSTGRES_DB', 'POSTGRES_PASSWORD'}):
                env += ['-e', key + "=test'quoted-password"]
            for filename in sorted(scripts):
                docker('exec', '-i', *env, name, 'bash', '-s', data=scripts[filename].encode())
            self.assertEqual(sql("SELECT count(*) FROM pg_database WHERE datname IN "
                                 "('keycloakdb','keycloakpredb','generatorapidb','generatorworkerdb','deploymentworkerdb')"), b'5')
            before = sql("SELECT rolpassword FROM pg_authid WHERE rolname='keycloakuser'")
            changed = ['-e', 'POSTGRES_KEYCLOAK_PASSWORD=must-not-rotate']
            for filename in sorted(scripts):
                docker('exec', '-i', *env, *changed, name, 'bash', '-s', data=scripts[filename].encode())
            self.assertEqual(before, sql("SELECT rolpassword FROM pg_authid WHERE rolname='keycloakuser'"))
            marker = docker('exec', name, 'psql', '-U', 'postgres', '-d', 'keycloakdb', '-Atc',
                            'SELECT value FROM legacy_marker').strip()
            self.assertEqual(marker, b'42')
        finally:
            docker('rm', '--force', name)


if __name__ == '__main__':
    unittest.main()
