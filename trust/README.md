# Deployment trust and release publication

Hiro keeps Phala Cloud KMS (`--kms phala`). This trusts Phala's authorization governance. The signed Hiro policy additionally controls which measured releases the proxy accepts. It does not change the KMS's key-release policy. Onchain governance requires a separate deployment choice.

## KMS evidence

The worker connects directly to `kms_url` using only `trust/kms-ca.pem` as its TLS trust anchor. It checks the hostname, certificate lifetime and production metadata, and captures the actual peer certificate. The proxy independently checks the signed policy's CA SPKI digest and endpoint, the certificate chain, the Intel quote, the `ratls-cert` report-data binding, and approved KMS app/compose/platform measurements. Original `bootstrap_info` is neither required nor used. Historical key-generation evidence is not represented as current endpoint attestation.

The committed CA is public Phala Cloud root material. Its SHA256 SPKI digest is `3b9af543b721799280ba3f05cef2a93aee3d99e49ea8f6f5716536db87b8e7f3`, matching [Phala Trust Center's pinned CA](https://github.com/Phala-Network/trust-center/blob/b2cf9eff3226ed503ccab13e51747b26d37e3a5a/packages/verifier/src/verifiers/phalaCloudKmsVerifier.ts). This root pin alone does not approve a KMS workload. Rotate it together with reviewed signed policy approvals.

Collection requires `is_dev=false` and `allow_any_upgrade=false`. The optional `os_image_verification` field describes dstack's local reconstruction of a key requester's OS measurements; dstack calls its authorization backend separately. Phala Cloud manages that backend. A false or absent flag is not, by itself, proof that boot authorization is disabled, and the collector does not treat the flag as a compatibility requirement. Hiro verifies the KMS's own OS, hardware and code identity through `prepare-platform` and the signed policy. This does not independently verify the managed backend's key-release rules. Authentication of metadata fields relies on the authenticated connection; the independent verifier establishes the certificate and measured identity, not a signed HTTP metadata response. See [dstack's separate authorization and OS reconstruction checks](https://github.com/Dstack-TEE/dstack/blob/3c877847e71a205a1d036965b8f5d671b3740103/dstack/kms/src/main_service.rs) and [Phala's Cloud KMS governance model](https://docs.phala.com/phala-cloud/key-management/cloud-vs-onchain-kms).

## Prepare platform approvals

Build the proxy with its pinned Bazel dependencies. Its `prepare-platform` command embeds upstream `dstack-verifier` at `3c877847e71a205a1d036965b8f5d671b3740103`. It verifies quote signatures and events, OS measurements against the image identity and VM configuration, and UpToDate TCB. It supports native Intel TDX 1.0 using dstack's legacy or lite measurement format. Legacy verification reconstructs measurements from a downloaded image; lite verifies the image-bound measurement document and recomputes ACPI measurements. Lite deliberately does not populate `os_image_is_dev`. In both formats, the expected OS hash must identify an independently reviewed production build; known development-image metadata is rejected. Hiro then applies its strict DCAP policy and exports exact platform measurements and a PCK PPID pin.

Supply independently reviewed expected identities in a JSON file:

```json
{
  "id": "kms-platform-v1",
  "os_image_hash": "<reviewed 32-byte OS identity, lowercase hex>",
  "app_id": "<reviewed 20-byte KMS application ID>",
  "compose_sha256": "<reviewed 32-byte KMS composition digest>",
  "allow_smt": false,
  "allow_dynamic_platform": false,
  "allow_cached_keys": false,
  "kms": {
    "id": "phala-kms-v1",
    "endpoint": "https://kms.dstack-pha-prod10.phala.network",
    "root_public_key": "<reviewed compressed secp256k1 public key>",
    "ca_public_key_sha256": "3b9af543b721799280ba3f05cef2a93aee3d99e49ea8f6f5716536db87b8e7f3"
  }
}
```

Choose hardware feature allowances deliberately. Do not derive the expected OS/code identities from the same unverified evidence being checked. Review the KMS composition against the intended upstream release and configuration. A hash match establishes identity, not the safety of arbitrary code.

```sh
mkdir -p dist
../hiro-proxy/bazel-bin/hiro-proxy collect-kms \
  https://kms.dstack-pha-prod10.phala.network trust/kms-ca.pem dist/kms-evidence.json
scripts/prepare-platform --verifier ../hiro-proxy/bazel-bin/hiro-proxy \
  --evidence dist/kms-evidence.json --expected reviewed-kms.json
```

For a workload profile, omit `kms` from the expected document. Supply an evidence JSON containing `quote` (hex), `event_log` (JSON string), and `vm_config` (JSON string), obtained from its Phala attestation. Use the reviewed workload app/compose identities. The command checks these identities and installs the platform entry. A changed machine or measurement needs a new reviewed profile; existing IDs cannot silently change meaning. `HIRO_OS_IMAGE_CACHE` selects the local image cache directory.

Discovery (`scripts/discover-phala`) supplies public candidate keys, endpoints and OS identities. `--check-trust` compares those candidates against committed approvals and the mounted CA. Discovery does not authorize measurements.

The installed `phala-cloud-prod10-20261009` approval was checked against the authenticated [Phala discovery artifact from run 37974575747](https://github.com/CypherpunkLabs-AI/hiro/actions/runs/37974575747). Its endpoint, root public key and CA SPKI digest all match that catalog. The pinned production OS is dstack 0.6.0 (`8409e2a24ea8325f3ea45d7c50622c952a8a4a961ffc139f5d9a81c4e47bd744`). The accompanying expected identities are in `phala-kms.expected.json`; the live endpoint's certificate, Intel quote, events and OS measurements passed the pinned dstack verifier and strict UpToDate Intel TCB appraisal. This approval accepts Phala Cloud's published service and authenticated KMS code identity; it does not claim an independently reproduced KMS source build. SMT, dynamic platform and cached keys are explicitly allowed for this hardware, with its exact PCK PPID digest retained.

## Bootstrap signing trust

The public Sigstore roots are now committed, with SHA256 `6494e21ea73fa7ee769f85f57d5a3e6a08725eae1e38c755fc3517c9e6bc0b66`. They were retrieved from [Sigstore's root-signing repository](https://github.com/sigstore/root-signing/blob/main/targets/trusted_root.json) and compared with the identical decoded trust root shipped in the pinned `attestation-verify` dependency. The default Rekor v1 checkpoint origin was checked against an actual checkpoint signature using that root's log key. Root or checkpoint-origin rotation requires updating these explicit pins.

First publish reviewed revisions containing the reusable `.github/workflows/release.yml` and `policy.yml` and their scripts. Then dispatch **Prepare deployment signing trust** on main. It generates an artifact containing the public verifier configuration and `publish-release.yml` / `publish-policy.yml` callers pinned to that exact published revision. Download the artifact into this repository and commit the generated files. The workload subject defaults to `hiro`; bootstrap trust lasts 90 days.

The same preparation can run locally with GitHub CLI authentication:

```sh
scripts/prepare-trust --signer-commit FULL_PUBLISHED_SIGNER_COMMIT
```

The command resolves the repository's numeric identities and fills evidence URLs. `--policy-commit` and `--release-commit` can pin separate revisions; `--subject`, `--not-after`, `--roots`, `--roots-sha256` and `--checkpoint-origin` override the defaults explicitly. This generates signing trust; it does not grant KMS or platform approvals.

The reusable signer obtains its actual `job_workflow_sha` from GitHub's authenticated OIDC endpoint before checking out signing tools. This prevents caller inputs from selecting different code while claiming the trusted signer revision. Source/configuration and signer/tool checkouts are separate. Public repositories and GitHub-hosted runners are required by the current verification profile.

A signer pin cannot refer to the commit that embeds that same pin. Pin the earlier reusable signer revision; the generated caller and release source may be newer commits. A signer rotation changes bootstrap trust and therefore the measured stack.

## Provision, publish, authorize

1. Run `scripts/deployment-status --bootstrap`. Configure the actual application environment, reviewed KMS/platform approvals and runtime trust. A first CVM can boot with only the KMS platform configured and no approved release; sessions remain unavailable until valid evidence is published.
2. Provision through the deployment workflow. It retains the exact `app-compose.json`, image lock, application ID and workload platform evidence as `hiro-deployment-RUN-ATTEMPT`. Save the provisioned `cvm_id` in `phala.toml` before another main-branch push, so deployment updates that CVM. If the workload platform was not yet known, independently verify the captured quote against the intended OS, app and composition identities, commit its profile and run deployment again against that CVM using the same proxy image run.
3. Set `trust/release.json` with the approved `platform_id` and `kms_id`. Push a `v*` tag at the exact source commit used by a successful deployment. **Publish measured release** finds that successful deployment and uses the caller's monotonically increasing run number for the initial sequence. Manual dispatch can select the deployment run, a higher sequence and profile IDs explicitly. The immutable signer rejects absent or unapproved profile IDs and verifies the run identity, OCI provenance and exact rendered composition before signing.
4. The release is published as `evidence:releases/COMPOSE_SHA256.json`; an immutable copy is stored at `evidence:release-digests/RELEASE_SHA256.json`. Each wrapper retains the exact artifact and Sigstore bundle bytes. Publication uses GitHub content SHA preconditions and shared workflow concurrency.
5. Commit the release digest shown in the release job summary to `trust/policy.json` under `approved_releases`, or dispatch **Publish and renew trust policy** on main with that digest. Main-branch policy changes automatically run the pinned signer. It independently verifies that signed release before approving it. Sessions become available only when the worker and proxy verify all evidence.

Policy renewal runs every six hours, increments the authenticated prior sequence, preserves revocations and minimum release floors, and verifies approved releases. It cannot renew an expired release. Release lifetime is at most seven days: republish from the same tag with a higher sequence and approve the new digest before expiry. Trust-root validity and service keyset validity also remain explicit operational limits. Protect release tags and the policy source branch according to the application's authorization policy.

Validation: `python3 -m unittest discover -s tests -v`, `scripts/validate`, and `actionlint`. Proxy verification tests run through the pinned Bazel CI targets. No workflow publishes unsigned configuration as trusted evidence.
