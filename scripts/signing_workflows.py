"""Render callers of immutable reusable signing workflows, avoiding self-referential commit pins."""
from hiro import ROOT


def write_callers(repository, policy_commit, release_commit):
    permissions = """permissions:
  contents: write
  id-token: write
  attestations: write
  packages: read
"""
    release = """name: Publish measured release
on:
  push:
    tags: ['v*']
  workflow_dispatch:
    inputs:
      deployment_run:
        description: Successful deployment run for this exact tag commit
        required: true
        type: string
      sequence:
        description: Monotonically increasing release sequence
        required: true
        type: string
      platform_id:
        required: true
        type: string
      kms_id:
        required: true
        type: string
      lifetime_seconds:
        required: true
        type: string
        default: '604800'
""" + permissions + f"""jobs:
  release:
    if: startsWith(github.ref, 'refs/tags/')
    uses: {repository}/.github/workflows/release.yml@{release_commit}
    with:
      signer_commit: {release_commit}
      deployment_run: ${{{{ inputs.deployment_run }}}}
      sequence: ${{{{ inputs.sequence }}}}
      platform_id: ${{{{ inputs.platform_id }}}}
      kms_id: ${{{{ inputs.kms_id }}}}
      lifetime_seconds: ${{{{ inputs.lifetime_seconds }}}}
"""
    policy = """name: Publish and renew trust policy
on:
  push:
    branches: [main]
    paths:
      - 'trust/policy.json'
      - 'trust/platforms.json'
      - 'trust/kms.json'
      - '.github/workflows/publish-policy.yml'
  workflow_dispatch:
    inputs:
      approve_release:
        description: Optional signed release SHA256 to approve
        required: false
        type: string
  schedule:
    - cron: '17 */6 * * *'
""" + permissions + f"""jobs:
  policy:
    uses: {repository}/.github/workflows/policy.yml@{policy_commit}
    with:
      signer_commit: {policy_commit}
      approve_release: ${{{{ inputs.approve_release || '' }}}}
"""
    (ROOT / ".github/workflows/publish-release.yml").write_text(release)
    (ROOT / ".github/workflows/publish-policy.yml").write_text(policy)
