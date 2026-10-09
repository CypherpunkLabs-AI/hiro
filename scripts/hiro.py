#!/usr/bin/env python3
"""Local release preparation. No network, credentials, signing or deployment."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import subprocess
import time
import tomllib
from urllib.parse import urlsplit

import yaml

ROOT = Path(os.environ.get("HIRO_ROOT", Path(__file__).resolve().parents[1])).resolve()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads((ROOT / path).read_text())


def write(path, data):
    path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def matches(value, pattern):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def kms_ca_digest():
    path = ROOT / "trust/kms-ca.pem"
    require(path.is_file() and 0 < path.stat().st_size <= 16384, "configure bounded public trust/kms-ca.pem")
    pem = path.read_bytes()
    require(pem.count(b"-----BEGIN CERTIFICATE-----") == 1 and b"PRIVATE KEY" not in pem,
            "KMS CA must contain exactly one public certificate")
    public = subprocess.run(["openssl", "x509", "-in", str(path), "-noout", "-pubkey"],
                            capture_output=True, check=True).stdout
    der = subprocess.run(["openssl", "pkey", "-pubin", "-outform", "DER"], input=public,
                         capture_output=True, check=True).stdout
    return hashlib.sha256(der).hexdigest()


def validate(strict=False):
    lock = read("images.lock.json")
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    require(lock.get("schema") == 1, "unsupported image lock schema")
    selected = {service.get("x-hiro-image", name)
                for name, service in compose["services"].items()}
    require(set(lock["services"]) == selected,
            "Every Compose image must reference exactly one locked artifact")
    for name, service in compose["services"].items():
        require("build" not in service, f"{name}: build images in the service repository")
        require(not service.get("privileged", False), f"{name}: privileged mode forbidden")
    for name, entry in lock["services"].items():
        require(matches(entry["image"], r"[a-z0-9.-]+(?::[0-9]+)?/[a-z0-9._/-]+"),
                f"{name}: expected registry/repository without a tag")
        require(matches(entry["source_repository"], r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"),
                f"{name}: invalid source repository")
        fields = {
            "digest": r"sha256:[0-9a-f]{64}",
            "source_commit": r"[0-9a-f]{40}",
            "source_ref": r"refs/(heads|tags)/[^\s]+",
            "build_workflow": r"\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml",
            "workflow_commit": r"[0-9a-f]{40}",
        }
        for field, pattern in fields.items():
            value = entry.get(field)
            require((value is None and not strict) or matches(value, pattern),
                    f"{name}.{field}: configure a valid immutable build reference")
    phala = tomllib.loads((ROOT / "phala.toml").read_text())
    require(len(phala["name"]) >= 5, "Phala CVM name requires at least five characters")
    for filename, key in (("platforms", "platforms"), ("kms", "kms")):
        doc = read(f"trust/{filename}.json")
        require(doc.get("schema") == 1 and isinstance(doc[key], list),
                f"invalid trust/{filename}.json")
        ids = [entry["id"] for entry in doc[key]]
        require(len(ids) == len(set(ids)), f"duplicate {filename} IDs")
    platforms = {profile["id"] for profile in read("trust/platforms.json")["platforms"]}
    for kms in read("trust/kms.json")["kms"]:
        require(matches(kms["root_public_key"], r"0[23][0-9a-f]{64}"), "invalid approved KMS root")
        for field, length in (("ca_public_key_sha256", 64), ("compose_sha256", 64), ("app_id", 40)):
            require(matches(kms[field], rf"[0-9a-f]{{{length}}}"), f"invalid KMS {field}")
        url = urlsplit(kms["endpoint"])
        require(url.scheme == "https" and bool(url.hostname) and not url.username and not url.password
                and not url.query and not url.fragment and url.path in ("", "/"), "invalid KMS endpoint")
        require(kms["platform_id"] in platforms, "KMS references an unconfigured platform")
    policy = read("trust/policy.json")
    require(policy.get("schema") == 1, "unsupported policy schema")
    require(type(policy["minimum_release_sequence"]) is int and policy["minimum_release_sequence"] > 0,
            "minimum release sequence must be positive")
    require(type(policy["lifetime_seconds"]) is int and 0 < policy["lifetime_seconds"] <= 604800,
            "policy lifetime must be between 1 second and 7 days")
    for key in ("approved_releases", "revoked_releases"):
        require(isinstance(policy[key], list) and len(policy[key]) <= 256 and
                all(matches(d, r"[0-9a-f]{64}") for d in policy[key]), f"invalid {key}")
    publishers = read("trust/publishers.json")
    require(publishers.get("schema") == 1, "unsupported publisher schema")
    for key in ("release_publisher", "policy_publisher"):
        require((ROOT / publishers[key]["workflow"]).is_file(), f"missing {key} workflow")
    return lock, compose


def runtime_inputs():
    """Validate provisioning inputs; cryptographic appraisal stays in the verifier."""
    trust_bytes = (ROOT / "trust/verifier.json").read_bytes()
    roots_bytes = (ROOT / "trust/sigstore-roots.json").read_bytes()
    require(len(trust_bytes) <= 65536 and len(roots_bytes) <= 262144,
            "runtime trust documents exceed verifier limits")
    trust = json.loads(trust_bytes)
    json.loads(roots_bytes)
    require(trust.get("schema") == 1, "unsupported verifier trust schema")
    require(trust.get("recipient") == "oak-session-v1-ed25519", "expected Oak recipient")
    require(trust.get("trust_root_sha256") == hashlib.sha256(roots_bytes).hexdigest(),
            "Sigstore roots do not match the provisioned trust-root hash")
    now = int(time.time())
    require(trust["not_before"] <= now < trust["not_after"], "verifier trust is not currently valid")
    for field in ("minimum_policy_sequence", "minimum_release_sequence"):
        require(type(trust[field]) is int and trust[field] > 0, f"invalid {field}")
    for field, maximum in (("max_policy_age_seconds", 604800),
                           ("max_challenge_age_seconds", 120), ("max_recipient_age_seconds", 300)):
        require(type(trust[field]) is int and 0 < trust[field] <= maximum, f"invalid {field}")
    publishers = read("trust/publishers.json")
    for field in ("policy_id", "service", "policy_ref", "policy_publisher", "release_publisher"):
        require(trust.get(field) == publishers[field], f"verifier {field} differs from publishers.json")
    for field in ("policy_publisher", "release_publisher"):
        publisher = trust[field]
        require(matches(publisher["repository"], r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"),
                f"{field}: configure the publisher repository")
        require(matches(publisher["workflow_commit"], r"[0-9a-f]{40}"), f"{field}: missing workflow pin")
        require(all(type(publisher[key]) is int and publisher[key] > 0
                    for key in ("owner_id", "repository_id")), f"{field}: missing GitHub numeric identities")
    require(matches(trust["policy_ref"], r"refs/heads/[^\s]+"), "policy must be signed from a branch")
    require(isinstance(trust["workload_subject"], str) and 0 < len(trust["workload_subject"]) <= 256,
            "missing workload subject")
    require(0 < len(trust["checkpoint_origins"]) <= 16, "configure transparency-log checkpoint origins")
    for origin in trust["checkpoint_origins"]:
        require(matches(origin["log_id"], r"[0-9a-f]{64}") and bool(origin["origin"]),
                "invalid checkpoint origin")
    runtime = read("trust/runtime.json")
    require(runtime.get("schema") == 1, "unsupported runtime schema")
    for key in ("release_base_url", "policy_url", "kms_url", "pccs_url"):
        value = runtime.get(key)
        require(isinstance(value, str), f"trust/runtime.json: configure {key}")
        url = urlsplit(value)
        require(url.scheme == "https" and bool(url.hostname) and not url.username
                and not url.password and not url.fragment, f"{key}: expected credential-free HTTPS URL")
        if key == "release_base_url":
            require(value.endswith("/") and not url.query, "release_base_url needs a trailing slash and no query")
    ca = ROOT / "trust/kms-ca.pem"
    require(ca.is_file() and 0 < ca.stat().st_size <= 16384, "configure trust/kms-ca.pem")
    require(runtime.get("kms_ca_path") == "/etc/hiro-kms-ca.pem", "unexpected KMS CA mount path")
    require(urlsplit(runtime["kms_url"]).path in ("", "/"), "KMS URL must be an origin")
    ca_digest = kms_ca_digest()
    require(any(kms["endpoint"].rstrip("/") == runtime["kms_url"].rstrip("/")
                and kms["ca_public_key_sha256"] == ca_digest for kms in read("trust/kms.json")["kms"]),
            "mounted KMS CA and endpoint do not match a reviewed approval")
    return trust_bytes.decode(), roots_bytes.decode(), runtime


def rendered():
    lock, compose = validate(strict=True)
    trust_text, roots_text, runtime = runtime_inputs()
    for name, service in compose["services"].items():
        entry = lock["services"][service.pop("x-hiro-image", name)]
        service["image"] = entry["image"] + "@" + entry["digest"]
    # Escape Compose interpolation without changing mounted JSON bytes.
    compose["configs"] = {
        "verifier-trust": {"content": trust_text.replace("$", "$$")},
        "sigstore-roots": {"content": roots_text.replace("$", "$$")},
        "kms-ca": {"content": (ROOT / "trust/kms-ca.pem").read_text()},
    }
    compose["services"]["evidence-worker"]["environment"].update({
        "HIRO_" + key.upper(): value.replace("$", "$$")
        for key, value in runtime.items() if key != "schema"
    })
    proxy = lock["services"]["hiro-proxy"]
    compose["services"]["hiro-proxy"]["environment"].update({
        "HIRO_SOURCE_REPOSITORY": "https://github.com/" + proxy["source_repository"],
        "HIRO_SOURCE_COMMIT": proxy["source_commit"],
        "HIRO_IMAGE_DIGEST": proxy["digest"],
        "HIRO_ATTESTED_SUBJECT": json.loads(trust_text)["workload_subject"].replace("$", "$$"),
    })
    return compose


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("validate")
    check.add_argument("--locked", action="store_true", help="require every immutable image reference")
    check.add_argument("--runtime", action="store_true", help="also require runtime trust and worker inputs")
    render = commands.add_parser("render-compose")
    render.add_argument("--output", type=Path, default=Path("dist/compose.yaml"))
    update = commands.add_parser("lock-image")
    update.add_argument("service")
    for field in ("digest", "source-commit", "source-ref", "build-workflow", "workflow-commit"):
        update.add_argument("--" + field, required=True)
    release = commands.add_parser("prepare-release")
    release.add_argument("--app-compose", required=True, type=Path)
    release.add_argument("--app-id", required=True)
    release.add_argument("--source-commit", required=True)
    release.add_argument("--tag", required=True)
    release.add_argument("--sequence", required=True, type=int)
    release.add_argument("--platform-id", required=True)
    release.add_argument("--kms-id", required=True)
    release.add_argument("--lifetime-seconds", type=int, default=86400)
    release.add_argument("--output", type=Path, default=Path("dist/release.json"))
    policy = commands.add_parser("prepare-policy")
    policy.add_argument("--sequence", required=True, type=int)
    policy.add_argument("--output", type=Path, default=Path("dist/policy.json"))
    args = parser.parse_args()
    if args.command == "validate":
        validate(args.locked or args.runtime)
        if args.runtime:
            runtime_inputs()
        print("Configuration valid" + ("; image references locked" if args.locked else "; unset deployment values allowed"))
    elif args.command == "render-compose":
        doc = rendered()
        output = ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(yaml.safe_dump(doc, sort_keys=False))
        print(output)
    elif args.command == "lock-image":
        lock, _ = validate()
        require(args.service in lock["services"], "unknown service")
        for field, pattern in (("digest", r"sha256:[0-9a-f]{64}"),
                               ("source_commit", r"[0-9a-f]{40}"),
                               ("workflow_commit", r"[0-9a-f]{40}"),
                               ("source_ref", r"refs/(heads|tags)/[^\s]+"),
                               ("build_workflow", r"\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml")):
            value = getattr(args, field)
            require(matches(value, pattern), f"invalid {field}")
            lock["services"][args.service][field] = value
        write("images.lock.json", lock)
        print("Image lock updated. Build provenance must be verified before release.")
    elif args.command == "prepare-release":
        compose = rendered()
        require(matches(args.app_id, r"[0-9a-f]{40}"), "app ID must be 20-byte lowercase hex")
        require(matches(args.source_commit, r"[0-9a-f]{40}"), "source commit must be 40-character hex")
        require(args.sequence > 0 and 0 < args.lifetime_seconds <= 604800, "invalid sequence or lifetime")
        require(matches(args.tag, r"[A-Za-z0-9][A-Za-z0-9._-]*"), "invalid release tag")
        require(args.platform_id in {p["id"] for p in read("trust/platforms.json")["platforms"]},
                "platform ID has not been configured in trust/platforms.json")
        require(args.kms_id in {k["id"] for k in read("trust/kms.json")["kms"]},
                "KMS ID has not been configured in trust/kms.json")
        raw = args.app_compose.read_bytes()
        app = json.loads(raw)
        require(yaml.safe_load(app["docker_compose_file"]) == compose,
                "Phala app-compose does not contain the rendered Compose configuration")
        now = int(time.time())
        write(args.output, {
            "schema": 1, "service": read("trust/publishers.json")["service"],
            "sequence": args.sequence, "tag": args.tag, "source_commit": args.source_commit,
            "issued_at": now, "expires_at": now + args.lifetime_seconds,
            "app_id": args.app_id, "compose_sha256": hashlib.sha256(raw).hexdigest(),
            "platform_id": args.platform_id, "kms_id": args.kms_id,
            "recipient": "oak-session-v1-ed25519",
            "containers": {name: service["image"] for name, service in compose["services"].items()},
        })
        print(f"Unsigned release prepared: {args.output}")
    elif args.command == "prepare-policy":
        validate()
        require(args.sequence > 0, "policy sequence must be positive")
        source = read("trust/policy.json")
        now = int(time.time())
        write(args.output, {
            "schema": 1, "policy_id": read("trust/publishers.json")["policy_id"],
            "sequence": args.sequence, "issued_at": now,
            "expires_at": now + source["lifetime_seconds"],
            "minimum_release_sequence": source["minimum_release_sequence"],
            "approved_releases": source["approved_releases"],
            "revoked_releases": source["revoked_releases"],
            "platforms": read("trust/platforms.json")["platforms"],
            "kms": read("trust/kms.json")["kms"],
        })
        print(f"Unsigned policy prepared: {args.output}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, TypeError, yaml.YAMLError) as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
