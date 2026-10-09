#!/usr/bin/env python3
"""Publish an authenticated policy with a monotonically increasing sequence."""
import json
import os
import time
from pathlib import Path

from hiro import require
from publish_common import existing, identity, publish, verify_bundle, wrapper


def main():
    repository, config, signer = identity("policy")
    require(os.environ["GITHUB_REF"] == config["policy_ref"], "unexpected policy source branch")
    artifact, bundle = verify_bundle("dist/policy.json", os.environ["POLICY_BUNDLE"], repository,
                                     signer, config["policy_ref"], os.environ["GITHUB_SHA"])
    policy = json.loads(artifact)
    require(policy["policy_id"] == config["policy_id"] and type(policy["sequence"]) is int
            and policy["sequence"] > 0 and policy["issued_at"] <= int(time.time()) < policy["expires_at"],
            "invalid policy identity, sequence or validity")
    previous, sha = existing(repository, "policy.json")
    if previous:
        old = json.loads(previous["artifact"])
        require(old["policy_id"] == policy["policy_id"] and policy["sequence"] > old["sequence"],
                "policy sequence must increase")
    content = wrapper(artifact, bundle)
    Path("dist/signed-policy.json").write_text(content)
    publish(repository, "policy.json", content, sha, f"Publish signed policy {policy['sequence']}")


if __name__ == "__main__":
    main()
