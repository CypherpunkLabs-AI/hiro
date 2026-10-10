# Hiro GCP boot image

A push to `main` builds the complete Linux boot disk with the verified Hiro proxy container already embedded. GitHub Actions performs the build, boots the image under UEFI, signs the release manifests, publishes a GitHub release and registers a custom Intel TDX image in GCP. It does not create a VM.

The job imports the selected successful proxy build, verifies its metadata and OCI provenance, and pins its digest. The Ubuntu package repositories use a fixed snapshot. Build tools are pinned through `flake.lock`. The OS, container archive, Compose configuration, public policy and startup code reside on a dm-verity-protected squashfs root. A directly bootable UKI embeds the root hash. Docker state and application keys are volatile. SSH, administrative console login and metadata startup scripts are disabled.

## One-time publishing permission

Open **Google Cloud Console → Activate Cloud Shell** while signed into the account authorized to administer project `cypherpunklabs`. Run:

```sh
git clone https://github.com/CypherpunkLabs-AI/hiro.git
cd hiro
python3 scripts/setup-gcp-publisher \
  --project cypherpunklabs \
  --bucket cypherpunklabs-hiro-images
```

The setup creates a dedicated image-publishing identity, a private bucket and Google Workload Identity Federation restricted to this repository's `main` image workflow. It grants image creation and bucket access, not VM creation. This setup has been completed for `cypherpunklabs`; the workflow already contains those public identifiers. No repository variables are required for that project. To use a different project, override these values under **GitHub repository → Settings → Secrets and variables → Actions → Variables**:

- `GCP_PROJECT_ID`
- `GCP_IMAGE_BUCKET`
- `GCP_IMAGE_PUBLISHER`
- `GCP_WORKLOAD_IDENTITY_PROVIDER`

No Google service-account key or laptop login is used by the job. Federation is checked before the expensive build, and credentials are refreshed immediately before publication.

## Outputs and VM creation

The release `image-<commit>` contains `hiro-gcp.tar.gz` (Google-compatible `disk.raw` archive), `image-release.json`, the embedded `release.json`, Compose and container pins, `hiro.efi`, checksums, a Sigstore bundle and the UEFI boot-check result. Successful GCP publication adds `gcp-image.json` with the exact registered image name and ID.

In GCP select **Compute Engine → Create instance → Boot disk → Custom images**, then `hiro-<commit>` in your project. Select **Intel TDX**, a supported C3 machine and zone, and **Secure Boot disabled** for this measured UKI profile. Firmware and boot measurements must still be verified by the client. The GCP guest image features are `TDX_CAPABLE`, `UEFI_COMPATIBLE`, `GVNIC` and `VIRTIO_SCSI_MULTIQUEUE`.

The proxy terminates TLS 1.3 inside the guest. Compose maps TCP `443:8443`. Point `api.cypherpunklabs.io` directly at the VM (DNS-only if using a CDN DNS service), allow inbound TCP 443 and outbound HTTPS, and attach the configuration disk described below. An external load balancer must use TCP passthrough. The proxy obtains and renews a browser-trusted certificate through Let's Encrypt TLS-ALPN-01; no DNS API secret or port 80 is required. It rejects application connections until a valid certificate is available.

Over HTTPS, `/health` reports process availability; `/ready` requires fresh TDX evidence; `/v1/attestation?nonce=<64 lowercase hex>` supplies challenge-bound evidence. Application requests use the Oak encrypted WebSocket session at `wss://api.cypherpunklabs.io/v1/session`, not plaintext chat endpoints. TLS early data, key logging and session resumption are disabled. A real hardware quote can only be checked after deployment on TDX.

TLS certificate keys are ECDSA P-256 keys generated inside the guest, independently of the Oak/receipt keys. The launcher disables swap and mounts a dedicated `noswap` tmpfs at `/run/hiro/tls`, owned by UID/GID 65532 with mode `0700`. Its `0600` cache files preserve certificate/account state across container restarts. VM restart destroys that state and requires fresh issuance, subject to CA rate limits. Each connection's selected TLS public key is included in its attested keyset, including during renewal. `HIRO_TLS_DOMAIN` and `HIRO_ACME_ENVIRONMENT` are fixed by `runtime-policy.json`; use `staging` in a separate test image when testing public ACME issuance.

CI boots with outbound networking blocked so it cannot request production certificates. It verifies that the TLS listener starts, rejects TLS 1.2 and plaintext HTTP, and fails closed without an issued certificate. Certificate issuance and live TDX verification require deployment; they are not reported as CI successes.

## Deployment configuration disk

Before starting the VM, attach a separate disk with an ext4 filesystem labelled `hiro-config`. Its root must contain a nonempty `secrets.env` file, owned by root with mode `0600`. Attach the disk read-only. The filesystem label identifies it regardless of the device name GCP assigns.

Use `.env.example` as the file template and replace its five dummy values with the deployment credentials. Keep that file outside the repository and image build. Use one `NAME=value` per line; values are literal, including `$` and quotes, so do not add shell quoting. For a startup-only deployment, the example values can be used on the configuration disk. They cannot serve real application traffic.

At boot, `/etc/fstab` mounts the disk at `/mnt/config` with `ro,nosuid,nodev,noexec`. `hiro.service` requires that mount and a readable, nonempty `/mnt/config/secrets.env`; it fails instead of falling back to embedded credentials. Docker Compose reads that file into the proxy container's environment without mounting the configuration disk into the container. Public endpoint and trust settings from `runtime-policy.json` remain measured in the image and take precedence over entries in the secrets file. That policy still contains dummy deployment values and must be set appropriately for real application traffic.

The image build never embeds `.env.example` or deployment credentials. The existing CI boot check creates a temporary configuration disk with public dummy values and attaches it to QEMU; that disk is deleted afterward and is not published. Release metadata records the required configuration disk.

This separates deployment secrets from public release artifacts. The configuration disk is plaintext from the guest's perspective and is not protected from the disk provider by TDX. Provider-hidden secret delivery requires an attestation-bound encrypted channel or encrypted contents with an attestation-gated decryption key; this disk-loading mechanism does not implement that.

Changes to the baked configuration require a new image. The guest never fetches new application code or packages at boot. Signed release verification, revocation/expiry policy and boot/RTMR/key verification belong in the independent client verifier. See [ARCHITECTURE.md](ARCHITECTURE.md).
