from pathlib import Path
import runpy
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
verify_cli_version = runpy.run_path(str(SCRIPTS / 'deploy'))['verify_cli_version']


class DeployTests(unittest.TestCase):
    def test_official_cli_build_version_preserves_exact_package_pin(self):
        for value in ('1.1.22', 'v1.1.22', 'v1.1.22+abc1234\n'):
            verify_cli_version(value, '1.1.22')
        for value in ('v1.1.23+abc1234', 'v1.1.222', 'v1.1.22-rc.1', 'v1.1.22+abc1234-dirty'):
            with self.assertRaisesRegex(ValueError, 'differs'):
                verify_cli_version(value, '1.1.22')


if __name__ == '__main__':
    unittest.main()
