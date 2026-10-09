# Hiro

Canonical Compose and release-configuration repository for Hiro on Phala/dstack.
Service repositories own their code, tests, Dockerfiles and image publishing.
This repository selects immutable images and holds the stack configuration and
reviewed trust inputs.

## Layout

```text
compose.yaml              Stack template; runtime secrets remain variable references
images.lock.json          Image digests and their source/build identities
phala.toml                Phala CLI project identity and gateway port
trust/                    Platform, KMS, publisher and release-policy inputs
scripts/                  Validation, image locking and artifact preparation
.github/workflows/        Configuration CI and manual preparation workflows
.env.example              Deployment and application variable names
ARCHITECTURE.md            Ownership, trust boundaries and release lifecycle
LICENSE                   GNU AGPL version 3, matching hiro-proxy
```

The initial stack contains `hiro-proxy`. Documents and search are excluded from
this first deployment. No `environments/` directory is used.

## Local preparation

Requires Python 3.11 or newer. Image provenance verification additionally requires
GitHub CLI with `gh attestation verify` and registry access.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r scripts/requirements.txt
scripts/validate
```

Null image digests and empty trust lists are deliberately unconfigured. Structural
validation accepts them; `scripts/validate --locked` and rendering reject missing
image identities. These checks validate configuration, not hardware attestation.

After the service repository publishes an image and its build provenance, record
the actual values:

```sh
scripts/lock-image hiro-proxy \
  --digest "sha256:$IMAGE_SHA256" \
  --source-commit "$SERVICE_COMMIT" \
  --source-ref "$SERVICE_REF" \
  --build-workflow .github/workflows/build.yml \
  --workflow-commit "$BUILD_WORKFLOW_COMMIT"
scripts/verify-images
scripts/render-compose
```

Use the service's actual workflow path. The lock command records values; it does
not establish their provenance. `verify-images` checks the image digest against
the repository, source commit/ref and signing workflow identity using GitHub's
verifier. CI currently requires GitHub-hosted image builds.

Rendered configuration is written to `dist/compose.yaml`. Rendering is
deterministic and does not read `.env` or interpolate credentials. Phala must
receive the rendered file rather than the root template.

## Phala configuration and first deployment

`phala.toml` sets `hiro-cvm` and port 8080. Set the selected non-development dstack
OS image, instance type, region/node and a pinned Phala CLI version in deployment
configuration. Keep the Cloud API token outside the repository. Application
variables should be supplied through Phala's confidential environment mechanism.
The CLI supports `--compose`, `--image`, `--instance-type`, `--env`,
`--no-dev-os`, `--no-public-logs` and `--no-public-sysinfo`; see the
[official deployment reference](https://docs.phala.com/phala-cloud/phala-cloud-cli/deploy).
The repository does not provision or redeploy a CVM automatically.

The current proxy requires these runtime dependencies before it can serve traffic:

- A working published proxy image, reachable PostgreSQL, authentication settings,
  cache namespace and inference configuration.
- Cloudflare usage-queue configuration and credentials, as required by the current
  proxy startup path.
- Phala inference API credentials and accepted upstream attestation identities.
- The CVM's `/var/run/dstack.sock`, exposed only to services requiring dstack access.
- `/run/hiro/evidence/evidence.json` on the CVM, mounted read-only as
  `/run/hiro/evidence.json` in the proxy. The bind mount deliberately refuses to
  create a missing host directory.

The proxy now implements an `evidence` worker command and a private Unix bootstrap
interface, with independent SDK verification and refresh. This Compose template
still needs the worker service, shared volumes, trust inputs and socket configuration
wired as described in `hiro-proxy/docs/EVIDENCE_WORKER.md`. A GitHub workflow cannot
supply a fresh runtime quote or substitute for that worker.
The service repository must also supply a buildable image before this stack boots.

## Release and policy preparation

Populate `trust/` from reviewed platform/KMS information and the actual GitHub
publisher identities. See [trust/README.md](trust/README.md).

After Phala prepares the application composition, preserve its exact JSON bytes.
The application measurement is the SHA-256 of those bytes, not the SHA-256 of
the Compose YAML. Prepare the unsigned release with:

```sh
scripts/prepare-release \
  --app-compose .local/app-compose.json \
  --app-id "$APP_ID" --source-commit "$HIRO_COMMIT" \
  --tag "$RELEASE_TAG" --sequence "$RELEASE_SEQUENCE" \
  --platform-id "$PLATFORM_ID" --kms-id "$KMS_ID"
scripts/prepare-policy --sequence "$POLICY_SEQUENCE"
```

`source-commit` here is the **hiro release repository** commit. Individual service
commits remain in the image lock. Release preparation checks that the supplied
Phala composition embeds the rendered stack and hashes the original bytes.
These scripts do not cryptographically validate supplied platform/KMS records.

The release workflow verifies image provenance and uploads the locked stack for
review. The policy workflow uploads an **unsigned** policy for review. Neither
workflow currently signs a client-trusted release or policy. Final publication
must produce the SDK's supported Sigstore bundle, verify it with the SDK, approve
the exact release digest in a signed policy, and retain the exact signed bytes.
Publisher workflow pins remain unconfigured until that signing path is established.

Before exposing private traffic, complete signing/publication and deployment wiring
for the implemented evidence worker, then verify a live Oak connection with the actual
client SDK. Configuration CI and `/health` alone do not establish that result.

## CI and changes

Pull requests and pushes to `main` run configuration validation. Preparation jobs
are manual and restricted to `main`. Actions are pinned to commits and Dependabot
proposes updates. Configure branch protection and required review in repository
settings; workflow files cannot enforce those settings themselves.

Each image update is a reviewed lock-file change. Updating a registry tag never
changes the selected stack. Rollback requires a still-approved release and policy
sequence; client rollback protection must remain enabled.
