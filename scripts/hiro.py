#!/usr/bin/env python3
"""Local release preparation. No network, credentials, signing or deployment."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import tomllib

import yaml

ROOT = Path(__file__).resolve().parents[1]


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


def validate(strict=False):
    lock = read("images.lock.json")
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    require(lock.get("schema") == 1, "unsupported image lock schema")
    require(set(lock["services"]) == set(compose["services"]),
            "Compose services and image lock must match")
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
        service = compose["services"][name]
        require("build" not in service, f"{name}: build images in the service repository")
        require(not service.get("privileged", False), f"{name}: privileged mode forbidden")
    phala = tomllib.loads((ROOT / "phala.toml").read_text())
    require(len(phala["name"]) >= 5, "Phala CVM name requires at least five characters")
    for filename, key in (("platforms", "platforms"), ("kms", "kms")):
        doc = read(f"trust/{filename}.json")
        require(doc.get("schema") == 1 and isinstance(doc[key], list),
                f"invalid trust/{filename}.json")
        ids = [entry["id"] for entry in doc[key]]
        require(len(ids) == len(set(ids)), f"duplicate {filename} IDs")
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


def rendered():
    lock, compose = validate(strict=True)
    for name, entry in lock["services"].items():
        compose["services"][name]["image"] = entry["image"] + "@" + entry["digest"]
    proxy = lock["services"]["hiro-proxy"]
    compose["services"]["hiro-proxy"]["environment"].update({
        "HIRO_SOURCE_REPOSITORY": "https://github.com/" + proxy["source_repository"],
        "HIRO_SOURCE_COMMIT": proxy["source_commit"],
        "HIRO_IMAGE_DIGEST": proxy["digest"],
    })
    return compose


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("validate")
    check.add_argument("--locked", action="store_true", help="require every immutable image reference")
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
        validate(args.locked)
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
