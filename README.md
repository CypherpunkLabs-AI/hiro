# Hiro

Deployment repository for the Hiro stack on Phala/dstack. Service repositories
publish OCI images; this repository selects their immutable digests and assembles
the measured Compose application.

## Runtime

`compose.yaml` runs three containers from the **same proxy image**:

| Service | Purpose | Mounts |
| --- | --- | --- |
| `volume-init` | One-shot directory ownership setup for UID 65532; no network | Four named volumes, no secrets or dstack |
| `hiro-proxy` | Oak sessions, API, upstream inference and fresh dstack quotes | dstack socket; private evidence socket; read-only evidence; its own verification state |
| `evidence-worker` | Retrieve and validate signed metadata, KMS evidence and collateral; refresh evidence atomically | Private evidence socket; writable evidence; its own verification state |

Only the proxy publishes port 8080 and receives application credentials. The worker
starts independently after volume initialization and retries until the proxy's
private socket is available. There is no readiness dependency cycle. Its health
check runs the image's `evidence-health` command.

Named volumes preserve separate rollback checkpoints. Do not delete them during
an ordinary update. Container isolation is within one attested CVM. The worker
cannot access the proxy's state volume or dstack key-derivation API.

## Import the image being built

Install Python 3.11+, GitHub CLI with attestation support, and authenticate `gh`.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r scripts/requirements.txt
scripts/import-proxy-image --run "$PROXY_RUN_ID"
```

`PROXY_RUN_ID` is the number in the proxy's successful GitHub Actions run URL.
The importer downloads that run's signed metadata, verifies both its signature
and the OCI image provenance, then updates `images.lock.json`. A running or failed
run is rejected. The selected repository currently matches the pushed proxy's
remote: `CypherpunkLabs-AI/hiro-gateway-test`; its registry image is
`ghcr.io/cypherpunklabs-ai/hiro-gateway-test`.

`volume-init` and `evidence-worker` reference the `hiro-proxy` lock entry using
`x-hiro-image`. Rendering removes that extension and gives all three services the
same `image@sha256:...` reference. There are no independent worker builds.

## Public trust configuration

`trust/publishers.json` defines the release/policy publisher identities.
`scripts/prepare-trust` resolves the actual GitHub numeric identities and checks
that the specified workflow files exist at the supplied revisions. It writes the
proxy/SDK trust format to `trust/verifier.json` and preserves the exact pinned
Sigstore root bytes in `trust/sigstore-roots.json`.

```sh
scripts/prepare-trust \
  --repository CypherpunkLabs-AI/hiro \
  --policy-commit "$POLICY_SIGNER_COMMIT" \
  --release-commit "$RELEASE_SIGNER_COMMIT" \
  --roots "$REVIEWED_SIGSTORE_ROOT_FILE" \
  --roots-sha256 "$REVIEWED_SIGSTORE_ROOT_SHA256" \
  --checkpoint-origin "$REKOR_LOG_ID=$REKOR_CHECKPOINT_ORIGIN" \
  --subject hiro \
  --not-after "$TRUST_EXPIRY_UNIX_SECONDS"
```

The signer commits must identify the eventual **signing** workflows; the present
release workflow prepares unsigned artifacts; the policy workflow signs and publishes policies. The root file is a
Sigstore trusted-root JSON document, with its digest and checkpoint-origin binding
selected independently of the CVM being verified. The proxy's `attestation-verify`
0.1.0 dependency bundles a public-good root and documents the supported profile:
GitHub SLSA v1, Sigstore bundle v0.3 and Rekor v1. It rejects Rekor v2 and private
repository attestation profiles. The signing pipeline must be checked against that
profile before its artifacts can be accepted; image provenance verified by `gh`
does not establish that compatibility.

Configure these **public** URLs in `trust/runtime.json`:

| Key | Exact response required |
| --- | --- |
| `release_base_url` | HTTPS directory with `<app-compose-sha256>.json`, containing signed release wrappers |
| `policy_url` | Current signed policy wrapper |
| `kms_url` | Phala KMS node base URL; the worker requests `/prpc/KMS.GetMeta?json` and decodes its bootstrap envelope using upstream dstack |
| `pccs_url` | PCCS base URL accepted by the proxy's DCAP collateral downloader |

The worker refuses redirects. Each endpoint must directly serve the requested
bytes. GitHub release download URLs redirect and cannot be used directly. Signed
wrappers have string fields `artifact` and `bundle`; preserve the exact artifact
bytes. KMS data is converted to the verifier's document by the worker; its quote,
event log and public keys must then pass the signed KMS approval checks.

Platform/KMS approvals belong in `trust/platforms.json` and `trust/kms.json`;
policy release approvals belong in `trust/policy.json`. Empty values authorize
nothing. See [trust/README.md](trust/README.md) for the verifier's formats.

```sh
scripts/deployment-status
scripts/validate --runtime
scripts/render-compose
```

The renderer checks root hashes, publisher consistency, validity bounds and URL
configuration. It embeds public trust files as Compose `configs.content` and fixes
the expected workload subject and worker URLs. This requires Docker Compose
2.23.1+ on the selected dstack OS. No local repository paths must exist on the CVM.
Rendering preserves secret variable references and never loads `.env`.

## Deploy or update

Install the selected exact CLI version with `npm install --global phala@VERSION`.
Copy `.env.example` to `.env` and set the application values. Export the Phala Cloud
control-plane token as `PHALA_CLOUD_API_KEY` in the operator shell; it must not be
included in the uploaded application environment.

```sh
scripts/deploy \
  --env .env \
  --image "$PHALA_OS_IMAGE" \
  --instance-type "$PHALA_INSTANCE_TYPE" \
  --region "$PHALA_REGION" \
  --cli-version "$PHALA_CLI_VERSION" \
  --check
```

This verifies registry provenance, renders the self-contained stack, validates
Compose and required application values without printing them, and checks the
installed CLI version. Remove `--check` to call `phala deploy`. Add
`--cvm-id "$CVM_ID"` to update an existing CVM; omit it to create one. Optional
`--node-id` selects a particular Phala node. The command uses Phala KMS, the
explicit OS image, `--no-dev-os`, `--no-public-logs`, `--no-public-sysinfo` and
`--wait`, following the [official CLI contract](https://docs.phala.com/phala-cloud/phala-cloud-cli/deploy).

The manual `deploy.yml` workflow imports and verifies the selected successful proxy CI image before invoking the same command. An empty `proxy_run` input selects the latest successful main-branch push. It checks all remaining bootstrap inputs together before provisioning. Configure GitHub secrets
`PHALA_CLOUD_API_KEY` and `HIRO_RUNTIME_ENV` (the application env file contents),
then supply the OS image, instance, region and CLI version in the dispatch form.
Deployment runs are serialized. Runtime secrets are stored only in a temporary
mode-0600 file and removed on exit; they are not uploaded as artifacts.

The current application also requires reachable PostgreSQL with its required
schema, auth issuer configuration, the Cloudflare usage queue and Phala inference
credentials/trust settings. Deploying containers does not provision those services.

## Signed release and live acceptance

The container can start before a supporting evidence snapshot exists. Private
sessions remain unavailable until the worker supplies evidence accepted by the
proxy's verifier. This allows the CVM's actual application composition to be
obtained before publishing its corresponding release approval.

The deployment script obtains the exact `app_compose` string from `phala cvms attestation` after provisioning, verifies the embedded Compose stack, and writes `dist/app-compose.json` without reserializing it. `dist/deployment.json` records the CVM ID before that retrieval, so a retry can target the existing CVM. Both files and the selected image lock are retained in the deployment artifact. Release preparation then uses:

```sh
scripts/prepare-release \
  --app-compose dist/app-compose.json \
  --app-id "$APP_ID" --source-commit "$HIRO_COMMIT" \
  --tag "$RELEASE_TAG" --sequence "$RELEASE_SEQUENCE" \
  --platform-id "$PLATFORM_ID" --kms-id "$KMS_ID"
scripts/prepare-policy --sequence "$POLICY_SEQUENCE"
```

The application measurement hashes the original JSON bytes, not the Compose YAML.
Release preparation checks that it embeds the rendered stack and records **all**
container identities, including initialization and evidence worker containers.
The `source-commit` here is the `hiro` release repository commit.

Still required for private-traffic activation: a compatible signed release and
release publication path, actual reviewed platform/KMS approvals and the selected
Phala KMS endpoint. The policy workflow signs and publishes policies; the release
workflow still produces unsigned review artifacts. After those inputs are published, the worker verifies them and refreshes
the evidence automatically. Acceptance requires a real client SDK connection that
verifies the deployed quote and completes an encrypted Oak request; `/health` alone
is not that acceptance check.

Configuration validation runs on branch pushes and pull requests. GitHub Actions
are pinned; image updates are reviewed lock changes. There is no `environments/`
directory, and document/search services are not part of this stack yet.
