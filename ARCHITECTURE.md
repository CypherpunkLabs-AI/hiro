# GCP TDX release boundary

The proxy image runtime contract is `hiro.gcp-tdx.v1`, defined in `hiro-proxy/docs/GCP_TDX.md` at the signed image's source revision. The guest OS and launcher are independently measured and must be approved by the client. Confidential Space is not used.

The launcher verifies the release signature against its approved publisher policy and rejects stale/revoked releases according to that policy. It checks `compose_sha256` and `image_lock_sha256`, launches only the pinned containers and enforces all measured mounts and runtime settings. It provides the read-only exact `release.json` and raw `ccel.bin` in `/run/hiro/attestation`.

Before launching the proxy, extend an initially zero RTMR3 exactly once with `SHA384(b"hiro.release.v1\0" + release_bytes)`. The register is then `SHA384(zero_48_bytes + event_digest)`. `dist/rtmr3.txt` records the expected value. The proxy rejects quotes with a different release measurement. The launcher provisions `/sys/kernel/config/tsm/report/hiro-proxy` with provider `tdx_guest`, grants UID 65532 access to its report attributes, and mounts only this entry into the unprivileged proxy.

A quote proves measurements, not their acceptability. The client independently validates Intel DCAP and current TCB policy, the approved OS/boot chain and CCEL, signed release approval and freshness, RTMR3, its fresh challenge, and the key bound to the Oak handshake. The proxy's local keys are generated in protected guest memory on each process start; no local KMS is involved. Remote Phala inference still has its own independent attestation and TLS key verification.

Public security settings are embedded from `runtime-policy.json`; secret credentials remain runtime inputs. The supplied policy and credentials are public dummy values. Complete the hardened guest/launcher and client integration against this contract before claiming a working private GCP deployment.
