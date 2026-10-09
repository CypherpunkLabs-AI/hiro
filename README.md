# Hiro Compose release

Assembles a signed, immutable Compose release for an Intel TDX guest on GCP. The proxy is built in `hiro-proxy` and published to GHCR. This repository no longer deploys to Phala, runs a local KMS, starts an evidence worker or uses Confidential Space.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r scripts/requirements.txt
export PATH="$PWD/.venv/bin:$PATH"
scripts/import-proxy-image --release v0.1.0
# Alternatively: scripts/import-proxy-image --run <successful-main-CI-run>
scripts/verify-images
scripts/prepare-release --source-commit "$(git rev-parse HEAD)" --tag v0.1.0
```

The importer verifies both signed metadata and OCI build provenance. It rejects the old Phala runtime profile. The existing image lock remains historical until the new proxy build is published and imported; it is deliberately not relabeled as a GCP-compatible image.

`runtime-policy.json` contains public endpoint/authentication/inference trust settings. Rendering embeds them as literals into measured Compose, so changing a policy requires a new signed release. The checked-in values are dummy settings. `.env.example` contains only dummy application credentials; they allow boot but cannot serve real application requests. Keep real credentials outside public release assets.

`prepare-release` writes `dist/compose.yaml`, `images.lock.json`, `release.json` and the expected `rtmr3.txt`. A version-tag push runs `publish-release.yml`, verifies the locked images, signs `release.json` and publishes the release assets. The signed manifest hashes the exact Compose and image lock and contains every container digest. No cloud deployment runs on a main-branch push.

The measured guest launcher verifies the release signature, enforces the Compose/digest pins, extends RTMR3 once with `SHA384("hiro.release.v1\0" || exact_release_bytes)`, and provides the Linux TSM report entry and CCEL log. See [ARCHITECTURE.md](ARCHITECTURE.md). Building a Compose release does not provision the hardened guest OS or update the client verifier.
