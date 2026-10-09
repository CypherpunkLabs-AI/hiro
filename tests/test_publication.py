import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import hiro
import publish_common as common
import signing_workflows


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load('release', 'publish-release.py')
prepare = load('prepare_release', 'prepare-release-from-deployment.py')
policy = load('policy', 'prepare-published-policy.py')


class PublicationTests(unittest.TestCase):
    def test_release_reads_the_uploaded_deployment_directory_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            captured = Path(directory)
            (captured / 'dist').mkdir()
            (captured / 'images.lock.json').write_text('{}')
            (captured / 'dist/deployment.json').write_text('{}')
            composition = captured / 'dist/app-compose.json'
            composition.write_text('{"measured": "exact bytes"}')
            files = prepare.deployment_files(captured)
            self.assertEqual(files['compose'].read_bytes(), b'{"measured": "exact bytes"}')
            composition.unlink()
            composition.symlink_to(captured / 'images.lock.json')
            with self.assertRaisesRegex(ValueError, 'invalid deployment artifact'):
                prepare.deployment_files(captured)

    def test_release_lifetime_is_not_extended_by_policy_renewal(self):
        with patch.object(common.time, 'time', return_value=100):
            with self.assertRaises(ValueError):
                common.valid_release({'schema': 1, 'sequence': 1, 'issued_at': 1, 'expires_at': 99})

    def test_release_requires_exact_tagged_deployment_commit(self):
        run = {'status': 'completed', 'conclusion': 'success', 'head_sha': 'b' * 40,
               'head_branch': 'main', 'event': 'push', 'path': '.github/workflows/deploy.yml',
               'repository': {'full_name': 'owner/hiro'}}
        with patch.dict(os.environ, GITHUB_REF='refs/tags/v1', GITHUB_SHA='a' * 40, DEPLOYMENT_RUN='123'), \
             patch.object(prepare, 'identity', return_value=('owner/hiro', {}, {})), \
             patch.object(prepare, 'api', return_value=run), \
             patch.object(prepare.subprocess, 'run') as command:
            with self.assertRaisesRegex(ValueError, 'tagged source commit'):
                prepare.main()
            command.assert_not_called()

    def test_release_rejects_branch_origin_before_signing_or_publication(self):
        with patch.dict(os.environ, GITHUB_REF='refs/heads/main'), \
             patch.object(release, 'identity', return_value=('owner/hiro', {}, {})), \
             patch.object(release, 'verify_bundle') as verify:
            with self.assertRaisesRegex(ValueError, 'tag'):
                release.main()
            verify.assert_not_called()

    def test_release_rejects_same_sequence_for_existing_composition(self):
        manifest = {'schema': 1, 'service': 'hiro', 'sequence': 2, 'tag': 'v1',
                    'source_commit': 'a' * 40, 'app_id': 'b' * 40, 'compose_sha256': 'c' * 64,
                    'issued_at': 90, 'expires_at': 110}
        with patch.dict(os.environ, GITHUB_REF='refs/tags/v1', GITHUB_SHA='a' * 40, RELEASE_BUNDLE='unused'), \
             patch.object(release, 'identity', return_value=('owner/hiro', {'service': 'hiro'}, {})), \
             patch.object(release, 'verify_bundle', return_value=(json.dumps(manifest), '{}')), \
             patch.object(common.time, 'time', return_value=100), \
             patch.object(release, 'existing', return_value=({'artifact': json.dumps(manifest)}, 'sha')), \
             patch.object(release, 'publish') as publish:
            with self.assertRaisesRegex(ValueError, 'sequence must increase'):
                release.main()
            publish.assert_not_called()

    def test_rekor_proof_required_before_gh_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / 'release.json'
            bundle = Path(directory) / 'bundle.json'
            artifact.write_text('{}')
            bundle.write_text(json.dumps({'mediaType': 'application/vnd.dev.sigstore.bundle.v0.3+json',
                                          'verificationMaterial': {'tlogEntries': []}}))
            with patch.object(common.subprocess, 'run') as command:
                with self.assertRaisesRegex(ValueError, 'Rekor'):
                    common.verify_bundle(artifact, bundle, 'owner/hiro', {}, 'refs/tags/v1')
                command.assert_not_called()

    def test_publisher_pins_signer_source_and_tag(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / 'release.json'
            bundle = Path(directory) / 'bundle.json'
            artifact.write_text('{"exact": "bytes"}\n')
            bundle.write_text(json.dumps({'mediaType': 'application/vnd.dev.sigstore.bundle.v0.3+json',
                'verificationMaterial': {'tlogEntries': [{'inclusionPromise': {'signedEntryTimestamp': 'x'},
                    'inclusionProof': {'checkpoint': {'envelope': 'x'}}}]}}))
            signer = {'workflow': '.github/workflows/release.yml', 'workflow_commit': 'a' * 40}
            with patch.object(common.subprocess, 'run') as command:
                result = common.verify_bundle(artifact, bundle, 'owner/hiro', signer, 'refs/tags/v1', 'b' * 40)
                args = command.call_args.args[0]
                self.assertEqual(args[args.index('--signer-digest') + 1], 'a' * 40)
                self.assertEqual(args[args.index('--source-digest') + 1], 'b' * 40)
                self.assertEqual(args[args.index('--source-ref') + 1], 'refs/tags/v1')
                self.assertEqual(result[0], artifact.read_text())

    def test_failed_signature_verification_never_produces_wrapper(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / 'release.json'
            bundle = Path(directory) / 'bundle.json'
            artifact.write_text('{}')
            bundle.write_text(json.dumps({'mediaType': 'application/vnd.dev.sigstore.bundle.v0.3+json',
                'verificationMaterial': {'tlogEntries': [{'inclusionPromise': {'signedEntryTimestamp': 'x'},
                    'inclusionProof': {'checkpoint': {'envelope': 'x'}}}]}}))
            with patch.object(common.subprocess, 'run', side_effect=RuntimeError('bad signature')):
                with self.assertRaisesRegex(RuntimeError, 'bad signature'):
                    common.verify_bundle(artifact, bundle, 'owner/hiro',
                        {'workflow': '.github/workflows/release.yml', 'workflow_commit': 'a' * 40}, 'refs/tags/v1')

    def test_policy_cannot_reapprove_revoked_release(self):
        source = {'approved_releases': [], 'revoked_releases': ['a' * 64], 'minimum_release_sequence': 1}
        config = {'policy_ref': 'refs/heads/main'}
        with patch.dict(os.environ, GITHUB_REF='refs/heads/main', APPROVE_RELEASE='a' * 64), \
             patch.object(policy, 'identity', return_value=('owner/hiro', config, {})), \
             patch.object(policy, 'existing', return_value=(None, None)), \
             patch.object(policy, 'read', return_value=source), \
             patch.object(policy, 'write') as write:
            with self.assertRaisesRegex(ValueError, 'revoked'):
                policy.main()
            write.assert_not_called()

    def test_publication_preserves_exact_signed_bytes_and_indexes_composition(self):
        manifest = {'schema': 1, 'service': 'hiro', 'sequence': 3, 'tag': 'v1',
                    'source_commit': 'a' * 40, 'app_id': 'b' * 40, 'compose_sha256': 'c' * 64,
                    'issued_at': 90, 'expires_at': 110}
        artifact = json.dumps(manifest, indent=2) + '\n'
        with tempfile.TemporaryDirectory() as directory:
            previous_cwd = Path.cwd()
            try:
                os.chdir(directory)
                Path('dist').mkdir()
                with patch.dict(os.environ, GITHUB_REF='refs/tags/v1', GITHUB_SHA='a' * 40,
                                RELEASE_BUNDLE='unused', GITHUB_STEP_SUMMARY=str(Path(directory) / 'summary')), \
                     patch.object(release, 'identity', return_value=('owner/hiro', {'service': 'hiro'}, {})), \
                     patch.object(release, 'verify_bundle', return_value=(artifact, '{"signed":true}\n')), \
                     patch.object(common.time, 'time', return_value=100), \
                     patch.object(release, 'existing', return_value=(None, None)), \
                     patch.object(release, 'publish') as publish:
                    release.main()
                paths = [call.args[1] for call in publish.call_args_list]
                self.assertEqual(paths, [f'release-digests/{common.digest(artifact)}.json', 'releases/' + 'c' * 64 + '.json'])
                saved = json.loads(Path('dist/signed-release.json').read_text())
                self.assertEqual(saved['artifact'], artifact)
                self.assertEqual(saved['bundle'], '{"signed":true}\n')
            finally:
                os.chdir(previous_cwd)

    def test_policy_renewal_preserves_authenticated_revocations_and_floor(self):
        source = {'approved_releases': [], 'revoked_releases': [], 'minimum_release_sequence': 1}
        old = {'policy_id': 'hiro', 'sequence': 7, 'approved_releases': [],
               'revoked_releases': ['a' * 64], 'minimum_release_sequence': 5}
        config = {'policy_ref': 'refs/heads/main', 'policy_id': 'hiro'}
        with patch.dict(os.environ, GITHUB_REF='refs/heads/main', APPROVE_RELEASE=''), \
             patch.object(policy, 'identity', return_value=('owner/hiro', config, {})), \
             patch.object(policy, 'existing', return_value=({'artifact': '{}'}, 'sha')), \
             patch.object(policy, 'authenticate', return_value=old), \
             patch.object(policy, 'read', return_value=source), \
             patch.object(policy, 'write') as write, \
             patch.object(policy.subprocess, 'run') as command:
            policy.main()
            written = write.call_args.args[1]
            self.assertEqual(written['revoked_releases'], ['a' * 64])
            self.assertEqual(written['minimum_release_sequence'], 5)
            self.assertEqual(command.call_args.args[0][-2:], ['--sequence', '8'])

    def test_generated_callers_pin_reusable_workflows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.github/workflows').mkdir(parents=True)
            with patch.object(signing_workflows, 'ROOT', root):
                signing_workflows.write_callers('owner/hiro', 'a' * 40, 'b' * 40)
            release_text = (root / '.github/workflows/publish-release.yml').read_text()
            self.assertIn('owner/hiro/.github/workflows/release.yml@' + 'b' * 40, release_text)
            self.assertIn("startsWith(github.ref, 'refs/tags/')", release_text)
            self.assertIn("17 */6 * * *", (root / '.github/workflows/publish-policy.yml').read_text())


if __name__ == '__main__':
    unittest.main()
