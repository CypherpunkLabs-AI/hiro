#!/usr/bin/env python3
"""Verify the pinned tag signer and publish a release indexed by measured composition."""
import json
import os
from pathlib import Path

from hiro import matches, require
from publish_common import digest, existing, identity, publish, valid_release, verify_bundle, wrapper


def main():
    repository, config, signer = identity("release")
    ref = os.environ["GITHUB_REF"]
    require(ref.startswith("refs/tags/"), "release must originate from a tag")
    artifact, bundle = verify_bundle("dist/release.json", os.environ["RELEASE_BUNDLE"],
                                     repository, signer, ref, os.environ["GITHUB_SHA"])
    release = json.loads(artifact)
    valid_release(release)
    require(release["service"] == config["service"] and ref == "refs/tags/" + release["tag"]
            and release["source_commit"] == os.environ["GITHUB_SHA"], "release identity mismatch")
    require(matches(release["compose_sha256"], r"[0-9a-f]{64}"), "invalid composition hash")
    path = f"releases/{release['compose_sha256']}.json"
    previous, sha = existing(repository, path)
    if previous:
        old = json.loads(previous["artifact"])
        require(old["app_id"] == release["app_id"] and old["compose_sha256"] == release["compose_sha256"]
                and release["sequence"] > old["sequence"], "release sequence must increase without changing identity")
    content = wrapper(artifact, bundle)
    Path("dist/signed-release.json").write_text(content)
    # Immutable digest-addressed copy supports policy approval and verification.
    immutable = f"release-digests/{digest(artifact)}.json"
    old, old_sha = existing(repository, immutable)
    require(old is None or old == json.loads(content), "conflicting release digest")
    if old is None:
        publish(repository, immutable, content, old_sha, f"Archive signed release {release['sequence']}")
    publish(repository, path, content, sha, f"Publish signed release {release['sequence']}")
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
        summary.write(f"Approve this release digest with publish-policy: `{digest(artifact)}`\n")


if __name__ == "__main__":
    main()
