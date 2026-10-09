from pathlib import Path
import os
import runpy
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
deploy = runpy.run_path(str(SCRIPTS / 'deploy'))
verify_cli_version = deploy['verify_cli_version']


class DeployTests(unittest.TestCase):
    def test_cli_creation_does_not_inherit_a_name_as_an_existing_cvm_selector(self):
        def invoke(command, **kwargs):
            config = Path(kwargs['cwd'], 'phala.toml').read_text()
            self.assertEqual(config, 'gateway_port = 8080\n')
            return SimpleNamespace(returncode=0)
        with patch('subprocess.run', side_effect=invoke):
            deploy['invoke_deployment'](['phala', 'deploy'], {'name': 'hiro-cvm', 'gateway_port': 8080})

    def test_existing_name_lookup_uses_the_authenticated_inventory(self):
        function = deploy['existing_cvm']
        instance = {'name': 'hiro-cvm', 'vm_uuid': 'existing-id'}
        with patch.dict(function.__globals__, query=lambda path: {'items': [instance], 'pages': 1}):
            self.assertEqual(function('hiro-cvm'), 'existing-id')
        with patch.dict(function.__globals__, query=lambda path: {'items': [], 'pages': 0}):
            self.assertIsNone(function('hiro-cvm'))
        with patch.dict(function.__globals__, query=lambda path: {'items': [instance, instance], 'pages': 1}):
            with self.assertRaisesRegex(ValueError, 'multiple CVMs'):
                function('hiro-cvm')
        def error(path):
            raise ValueError('HTTP 403')
        with patch.dict(function.__globals__, query=error):
            with self.assertRaisesRegex(ValueError, 'HTTP 403'):
                function('hiro-cvm')

    def test_cli_diagnostics_redact_application_and_control_plane_credentials(self):
        result = SimpleNamespace(stderr='failed private-password token-control token-application', stdout='')
        with patch.dict(os.environ, PHALA_CLOUD_API_KEY='token-control'):
            value = deploy['cli_diagnostic'](result, 'DATABASE_URL=postgres://user:private-password@host/db\nPHALA_API_KEY="token-application"')
        for secret in ('private-password', 'token-control', 'token-application'):
            self.assertNotIn(secret, value)

    def test_official_cli_build_version_preserves_exact_package_pin(self):
        for value in ('1.1.22', 'v1.1.22', 'v1.1.22+abc1234\n'):
            verify_cli_version(value, '1.1.22')
        for value in ('v1.1.23+abc1234', 'v1.1.222', 'v1.1.22-rc.1', 'v1.1.22+abc1234-dirty'):
            with self.assertRaisesRegex(ValueError, 'differs'):
                verify_cli_version(value, '1.1.22')


if __name__ == '__main__':
    unittest.main()
