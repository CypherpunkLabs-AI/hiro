#!/usr/bin/env python3
"""Renew an authenticated policy and optionally approve one verified signed release."""
import json
import os
from pathlib import Path
import subprocess
import sys

from hiro import ROOT, matches, read, require, write
from publish_common import digest, existing, identity, valid_release, verify_bundle


def authenticate(value, label, repository, publisher, ref, commit=None):
    directory = ROOT / "dist/verification"
    directory.mkdir(parents=True, exist_ok=True)
    artifact = directory / f"{label}.json"
    bundle = directory / f"{label}.sigstore.json"
    artifact.write_text(value["artifact"])
    bundle.write_text(value["bundle"])
    verify_bundle(artifact, bundle, repository, publisher, ref, commit)
    return json.loads(value["artifact"])


def main():
    repository, config, publisher = identity("policy")
    require(os.environ["GITHUB_REF"] == config["policy_ref"], "unexpected policy branch")
    previous, _ = existing(repository, "policy.json")
    source = read("trust/policy.json")
    approved = set(source["approved_releases"])
    revoked = set(source["revoked_releases"])
    sequence = 1
    if previous:
        old = authenticate(previous, "previous-policy", repository, publisher, config["policy_ref"])
        require(old["policy_id"] == config["policy_id"] and type(old["sequence"]) is int and old["sequence"] > 0,
                "invalid prior policy")
        sequence = old["sequence"] + 1
        approved.update(old["approved_releases"])
        revoked.update(old["revoked_releases"])
        source["minimum_release_sequence"] = max(source["minimum_release_sequence"], old["minimum_release_sequence"])
    requested = os.environ.get("APPROVE_RELEASE", "").strip()
    if requested:
        require(matches(requested, r"[0-9a-f]{64}") and requested not in revoked, "invalid/revoked requested release")
        approved.add(requested)
    # A renewal cannot add an unsigned digest, revive a revoked release, or
    # extend the lifetime of its release. Rotation must publish a fresh release.
    releases = {}
    for sha in sorted(approved - revoked):
        value, _ = existing(repository, f"release-digests/{sha}.json")
        require(value is not None and digest(value["artifact"]) == sha, "release digest is not published")
        candidate = json.loads(value["artifact"])
        require(matches(candidate["tag"], r"[A-Za-z0-9][A-Za-z0-9._-]*")
                and matches(candidate["source_commit"], r"[0-9a-f]{40}"), "invalid release source identity")
        release = authenticate(value, sha, repository, config["release_publisher"],
                               "refs/tags/" + candidate["tag"], candidate["source_commit"])
        require(release["service"] == config["service"], "release service differs")
        releases[sha] = release
    if requested:
        replacement = releases[requested]
        approved -= {sha for sha, release in releases.items() if sha != requested
                     and release["app_id"] == replacement["app_id"]
                     and release["compose_sha256"] == replacement["compose_sha256"]}
    for sha in approved - revoked:
        valid_release(releases[sha])
        require(releases[sha]["sequence"] >= source["minimum_release_sequence"], "release below sequence floor")
    source["approved_releases"] = sorted(approved - revoked)
    source["revoked_releases"] = sorted(revoked)
    write("trust/policy.json", source)
    subprocess.run([sys.executable, str(Path(__file__).with_name("hiro.py")), "prepare-policy",
                    "--sequence", str(sequence)], check=True)


if __name__ == "__main__":
    main()
