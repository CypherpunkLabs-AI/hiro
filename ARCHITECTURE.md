# Architecture

## Repository responsibilities

`hiro` assembles independently built service images into one Phala/dstack CVM
application. Each service repository runs its own tests, builds its image and
publishes provenance. `images.lock.json` selects digest-addressed outputs and
records source and build identities. Compose rendering must never resolve mutable
tags or build application code locally.

Phala supplies the CVM operating system and dstack runtime. This repository owns
the application composition. A separate container image per service remains
compatible with measuring the whole application composition; there is no combined
Hiro OS image build in this repository.

## Runtime boundaries

```text
Browser/native client SDK
  | verifies release, policy, TDX evidence and session-key binding
  | Oak/Noise encrypted traffic over WSS
Phala gateway / TLS ingress
  |
Phala/dstack CVM
  +-- hiro-proxy :8080
  |     +-- Oak session termination and authenticated API dispatch
  |     +-- dstack socket: key derivation and runtime quote access
  |     +-- mounted supporting evidence: release, policy, collateral, KMS
  |     +-- attested Phala inference upstream
  +-- future document/search services on private Compose networks

External dependencies: PostgreSQL, authentication issuer, usage queue,
Phala inference API, approved release/policy distribution.
```

Only the proxy publishes a port. It has outbound connectivity for current external
dependencies and joins the internal service network. Later workers should expose
only the interfaces the proxy needs. Container separation inside one CVM is
operational isolation, not an independent hardware trust boundary. The dstack
socket is an authority-bearing API even when its filesystem mount is read-only.

The stack retains the SDK/proxy's existing Oak transport. The deployment repository
does not implement cryptography or replace dstack evidence verification. TLS
termination at a gateway does not authenticate an Oak session; the SDK must verify
the enclave evidence and handshake binding before sending private application data.

## Release lifecycle

1. Service CI publishes an image by digest with verifiable build provenance.
2. A reviewed change records its immutable identity in `images.lock.json`.
3. Central CI verifies image provenance and renders Compose without expanding secrets.
4. Phala prepares the full application composition for the selected dstack OS and
   configuration. Preserve the exact `app-compose.json` bytes and selected app ID.
5. Release preparation hashes those bytes and records container digests, platform
   and KMS profile IDs. The release publisher signs that manifest using the identity
   pinned by the client. A separately signed policy approves its exact digest.
6. Provision the CVM with the exact approved composition and confidential settings.
   A subsequent change to composition requires a new measurement and approval.
7. Runtime evidence production supplies current collateral, KMS evidence and signed
   metadata. The proxy obtains fresh quote/session binding evidence via dstack.
8. A real SDK connection verifies the complete chain and exchanges encrypted traffic
   before the deployment is accepted for private users.

Steps 1–3 and unsigned manifest preparation have tooling here. Signing, publication,
Phala provisioning, deployment wiring for the proxy's implemented evidence worker,
and live SDK acceptance still require integration. Preparation workflow success is not a production-release gate.

## Trust ownership

Client bootstrap trust contains the authorized publisher identities and cryptographic
roots. A repository URL is a distribution location, not an independently trusted root.
Policy snapshots authorize platform/KMS profiles and release digests with bounded
expiry and monotonically increasing sequence numbers. These decisions must not be
learned automatically from the server being verified.

Hardware/platform approval and application approval are separate. dstack provides
hardware evidence and key derivation; Hiro selects accepted measurements, publishers,
release policy and the keys bound to its sessions. Upstream inference approval is
also distinct from the proxy's own identity.

Release manifests and policy snapshots are signed artifacts; quotes and collateral
are runtime evidence. CI provenance is useful for establishing how an image was
built, but does not attest that a particular VM is presently executing that image.

## Secrets and operations

Credentials never enter committed Compose, image locks, trust files or public
artifacts. The `.env.example` file lists names only. Runtime supporting evidence is
mounted read-only and needs atomic refresh before expiry. Configure logging to avoid
request content, credentials and decrypted inference data.

Rollback selects a previously approved release without decreasing persisted client
policy floors. Revoked releases stay rejected. Platform updates, signer rotation,
KMS changes and service additions all require reviewed trust/release changes.
