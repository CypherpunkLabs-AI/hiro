# Trust configuration

These files are reviewed release inputs, not signed trust roots or live evidence.
Empty lists and null identities deliberately authorize no deployment.

| File | Owner and purpose |
| --- | --- |
| `platforms.json` | Reviewed TDX/dstack platform measurements, TCB constraints and accepted machine PPID hashes. |
| `kms.json` | Approved KMS root public key, CA key hash, app ID, composition hash and platform profile. |
| `publishers.json` | Release/policy service identifiers and exact GitHub publisher identities to provision in the SDK. |
| `policy.json` | Minimum release sequence, approved/revoked release hashes and policy lifetime. |

Platform and KMS entries must follow `PlatformProfile` and `KmsApproval` in
`cypherpunk-client/crates/verifier/src/model.rs`. Do not infer trusted values from an
unauthenticated target quote. Phala/dstack's reviewed platform and KMS information
provides the basis for approval; Hiro's client policy determines acceptance.

Publisher entries require the repository name, numeric GitHub owner/repository IDs,
workflow path and exact signing workflow commit. The source commit and signing
workflow commit are distinct. Choose and pin the signing workflow before configuring
clients; changes to that pinned identity require a trust update. The current workflows
only prepare artifacts and are not yet configured publishers.

Release hashes are lowercase SHA-256 of the exact `release.json` bytes. A signed
artifact wrapper uses `artifact` and `bundle` string fields. Preserve the artifact
bytes after signing. Policy snapshots use a positive sequence and bounded lifetime;
this repository caps the generated lifetime at seven days. Revocations override
approvals in the verifier.

Use a Sigstore bundle profile actually supported by the client verifier. Successful
GitHub image-provenance verification is a separate check and does not demonstrate
that the SDK accepts a release-signing bundle. Establish that compatibility before
publishing trusted releases. Never place private signing keys or credentials here.
