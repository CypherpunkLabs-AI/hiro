# Trust configuration

These files are reviewed release inputs, not signed trust roots or live evidence.
Empty lists and null identities deliberately authorize no deployment.

| File | Owner and purpose |
| --- | --- |
| `platforms.json` | Reviewed TDX/dstack platform measurements, TCB constraints and accepted machine PPID hashes. |
| `kms.json` | Approved KMS root public key, CA key hash, app ID, composition hash and platform profile. |
| `publishers.json` | Release/policy service identifiers and exact GitHub publisher identities to provision in the SDK. |
| `policy.json` | Minimum release sequence, approved/revoked release hashes and policy lifetime. |
| `runtime.json` | Direct HTTPS endpoints for signed releases/policy, the Phala KMS node and PCCS. |
| `verifier.json` | Generated public bootstrap trust, matching the proxy and SDK `TrustConfig` format. |
| `sigstore-roots.json` | Exact reviewed root bytes pinned by `verifier.json`. |

Platform and KMS entries must follow `PlatformProfile` and `KmsApproval` in
`cypherpunk-client/crates/verifier/src/model.rs`. Do not infer trusted values from an
unauthenticated target quote. Phala/dstack's reviewed platform and KMS information
provides the basis for approval; Hiro's client policy determines acceptance.

Publisher entries require the repository name, numeric GitHub owner/repository IDs,
workflow path and exact signing workflow commit. The source commit and signing
workflow commit are distinct. Choose and pin the signing workflow before configuring
clients; changes to that pinned identity require a trust update. The policy workflow signs and publishes policies. Release signing still requires
integration, and publisher identities are not yet populated.

Release hashes are lowercase SHA-256 of the exact `release.json` bytes. A signed
artifact wrapper uses `artifact` and `bundle` string fields. Preserve the artifact
bytes after signing. Policy snapshots use a positive sequence and bounded lifetime;
this repository caps the generated lifetime at seven days. Revocations override
approvals in the verifier.

Use a Sigstore bundle profile actually supported by the client verifier. Successful
GitHub image-provenance verification is a separate check and does not demonstrate
that the SDK accepts a release-signing bundle. Establish that compatibility before
publishing trusted releases. Never place private signing keys or credentials here.

`scripts/prepare-trust` generates the final two files from pinned root bytes,
explicit signer revisions, checkpoint origins and GitHub's numeric repository
identities. The renderer checks their consistency with `publishers.json` and embeds
them into Compose configs. These files are public release inputs and should be
reviewed and committed, not treated as application secrets.

The worker requests `/prpc/KMS.GetMeta?json` from `kms_url` and decodes the
bootstrap envelope with upstream `dstack-attest`. It supplies `quote`, `event_log`,
`ca_public_key`, `root_public_key` and downloaded `collateral` to the verifier.
The KMS composition hash and app ID must match independently approved policy
after RTMR3 replay; the KMS composition preimage is not required. Hiro's workload
still requires its full composition for container inventory verification.

GitHub Actions obtains account access from `PHALA_CLOUD_API_KEY`.
The deployment workflow runs `scripts/discover-phala` with the official CLI to retrieve the account's public
KMS keys, node URLs and selected production OS identity. `--check-trust` rejects
keys or URLs inconsistent with the committed configuration. Its public metadata
artifact does not replace signed platform/KMS approvals.
