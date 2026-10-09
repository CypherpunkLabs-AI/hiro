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

The proxy starts on port 8080. Configure the VM firewall for the intended endpoint. `/health` reports process availability; `/ready` requires fresh TDX evidence; `/v1/attestation?nonce=<64 lowercase hex>` supplies challenge-bound evidence. Application requests use the Oak encrypted WebSocket session at `/v1/session`, not plaintext chat endpoints. A normal UEFI CI VM must return 503 for readiness and evidence. A real hardware quote can only be checked after deployment on TDX.

The image deliberately includes the public dummy credentials from `.env.example` and dummy policy from `runtime-policy.json`, as requested. It can boot and attest without a working database or inference provider. Those dummy values cannot serve real application traffic. They are not production secrets; do not put actual secrets in this public image.

Changes to the baked configuration require a new image. The guest never fetches new application code or packages at boot. Signed release verification, revocation/expiry policy and boot/RTMR/key verification belong in the independent client verifier. See [ARCHITECTURE.md](ARCHITECTURE.md).
