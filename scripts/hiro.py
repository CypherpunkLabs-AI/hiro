#!/usr/bin/env python3
"""Assemble the digest-pinned GCP TDX Compose release; never deploy a VM."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import yaml

ROOT = Path(os.environ.get("HIRO_ROOT", Path(__file__).resolve().parents[1])).resolve()
PROFILE = "hiro.gcp-tdx.v1"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def matches(value, pattern):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def read(path):
    return json.loads((ROOT / path).read_text())


def write(path, data):
    path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def validate(strict=False):
    lock = read("images.lock.json")
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    require(lock.get("schema") == 1, "unsupported image lock")
    require(set(lock["services"]) == {s.get("x-hiro-image", n) for n, s in compose["services"].items()},
            "Compose services must match locked images")
    for name, service in compose["services"].items():
        require("build" not in service and not service.get("privileged"), f"{name}: use a published unprivileged image")
    for name, entry in lock["services"].items():
        for key, pattern in {
            "image": r"[a-z0-9.-]+(?::[0-9]+)?/[a-z0-9._/-]+",
            "source_repository": r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",
            "digest": r"sha256:[0-9a-f]{64}", "source_commit": r"[0-9a-f]{40}",
            "workflow_commit": r"[0-9a-f]{40}",
            "source_ref": r"refs/(heads/main|tags/v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?)",
            "build_workflow": r"\.github/workflows/ci.yml",
        }.items():
            require(matches(entry.get(key), pattern), f"{name}: invalid {key}")
        if strict:
            require(entry.get("runtime_profile") == PROFILE,
                    f"{name}: import the new signed GCP TDX proxy image before assembling a release")
    return lock, compose


def rendered():
    lock, compose = validate(strict=True)
    for name, service in compose["services"].items():
        entry = lock["services"][service.pop("x-hiro-image", name)]
        service["image"] = entry["image"] + "@" + entry["digest"]
    proxy = lock["services"]["hiro-proxy"]
    policy = read("runtime-policy.json")
    allowed = {"AUTH_ISSUER", "AUTH_AUTHORIZED_PARTIES", "AUTH_JWKS_URL", "AUTH_AUDIENCE",
               "PHALA_ACI_BASE_URL", "PHALA_ACI_ACCEPTED_SUBJECTS", "PHALA_ACI_ACCEPTED_KMS_ROOT_KEYS",
               "PHALA_ACI_PCCS_URL", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_USAGE_QUEUE_ID", "INFERENCE_SYSTEM_PROMPT"}
    require(set(policy) == allowed and all(isinstance(v, str) and v for v in policy.values()),
            "runtime-policy.json must contain exactly the public security policy fields")
    env = compose["services"]["hiro-proxy"]["environment"]
    env.update({k: v.replace("$", "$$") for k, v in policy.items()})
    env.update(HIRO_SOURCE_REPOSITORY="https://github.com/" + proxy["source_repository"],
               HIRO_SOURCE_COMMIT=proxy["source_commit"], HIRO_IMAGE_DIGEST=proxy["digest"])
    return compose


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("validate")
    check.add_argument("--locked", action="store_true")
    render = commands.add_parser("render-compose")
    render.add_argument("--output", type=Path, default=Path("dist/compose.yaml"))
    release = commands.add_parser("prepare-release")
    release.add_argument("--source-commit", required=True)
    release.add_argument("--tag", required=True)
    release.add_argument("--output", type=Path, default=Path("dist/release.json"))
    args = parser.parse_args()
    if args.command == "validate":
        validate(args.locked)
        print("Release configuration valid")
        return
    compose = rendered()
    raw = yaml.safe_dump(compose, sort_keys=False).encode()
    if args.command == "render-compose":
        output = ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(raw)
        print(output)
        return
    require(matches(args.source_commit, r"[0-9a-f]{40}"), "invalid release source commit")
    require(matches(args.tag, r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?"), "invalid release tag")
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    (output.parent / "compose.yaml").write_bytes(raw)
    lock_bytes = (ROOT / "images.lock.json").read_bytes()
    (output.parent / "images.lock.json").write_bytes(lock_bytes)
    write(output, {
        "schema": 1, "profile": PROFILE, "tag": args.tag, "source_commit": args.source_commit,
        "compose_sha256": hashlib.sha256(raw).hexdigest(),
        "image_lock_sha256": hashlib.sha256(lock_bytes).hexdigest(),
        "containers": {name: service["image"] for name, service in compose["services"].items()},
    })
    event = hashlib.sha384(b"hiro.release.v1\0" + output.read_bytes()).digest()
    (output.parent / "rtmr3.txt").write_text(hashlib.sha384(bytes(48) + event).hexdigest() + "\n")
    print(output)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, TypeError, yaml.YAMLError) as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
