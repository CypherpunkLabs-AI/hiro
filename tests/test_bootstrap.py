import json
from pathlib import Path
import runpy
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import hiro
import signing_workflows

bootstrap = runpy.run_path(str(SCRIPTS / 'prepare-trust'))['main']


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(SCRIPTS.parent / 'trust', self.root / 'trust')
        (self.root / '.github/workflows').mkdir(parents=True)
        self.signer = 'a' * 40
        self.repository = {'full_name': 'CypherpunkLabs-AI/hiro', 'id': 1411129710,
                           'owner': {'id': 325408208}, 'private': False}

    def invoke(self, *args):
        with patch.object(hiro, 'ROOT', self.root), \
             patch.object(signing_workflows, 'ROOT', self.root), \
             patch.dict(bootstrap.__globals__, ROOT=self.root), \
             patch.object(sys, 'argv', ['prepare-trust', '--signer-commit', self.signer, *args]), \
             patch('subprocess.check_output', return_value=json.dumps(self.repository)), \
             patch('subprocess.run'):
            bootstrap()

    def test_defaults_produce_one_consistent_immutable_signer_configuration(self):
        self.invoke()
        trust = json.loads((self.root / 'trust/verifier.json').read_text())
        publishers = json.loads((self.root / 'trust/publishers.json').read_text())
        for kind in ('policy', 'release'):
            self.assertEqual(trust[kind + '_publisher'], publishers[kind + '_publisher'])
            self.assertEqual(trust[kind + '_publisher']['workflow_commit'], self.signer)
            caller = (self.root / f'.github/workflows/publish-{kind}.yml').read_text()
            self.assertIn(f'/{kind}.yml@{self.signer}', caller)
        self.assertEqual(trust['workload_subject'], 'hiro')
        self.assertEqual(trust['not_after'] - trust['not_before'], 90 * 86400)
        self.assertEqual(trust['checkpoint_origins'][0]['origin'],
                         'rekor.sigstore.dev - 1193050959916656506')

    def test_changed_root_bytes_cannot_be_blessed_by_default_pin(self):
        (self.root / 'trust/sigstore-roots.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'supplied pin'):
            self.invoke()
        self.assertFalse((self.root / 'trust/verifier.json').exists())

    def test_private_repository_does_not_generate_public_evidence_configuration(self):
        self.repository['private'] = True
        with self.assertRaisesRegex(ValueError, 'public repository'):
            self.invoke()
        self.assertFalse((self.root / 'trust/verifier.json').exists())


if __name__ == '__main__':
    unittest.main()
