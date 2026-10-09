#!/usr/bin/env python3
"""Verify an Actions policy attestation and publish the exact signed bytes."""
import base64
import json
import os
from pathlib import Path
import subprocess
import time

from hiro import read, require


def api(path, body=None, method=None, optional=False):
    command = ["gh", "api", path]
    if body is not None:
        command += ["--method", method or "POST", "--input", "-"]
    result = subprocess.run(command, input=None if body is None else json.dumps(body),
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        if optional and "(HTTP 404)" in result.stderr:
            return None
        raise RuntimeError(f"GitHub operation failed: {path}")
    require(len(result.stdout) <= 4 * 1024 * 1024, "GitHub response exceeds limit")
    return json.loads(result.stdout)


def main():
    repository = os.environ["GITHUB_REPOSITORY"]
    ref = os.environ["GITHUB_REF"]
    publisher = read("trust/publishers.json")
    require(ref == publisher["policy_ref"], "unexpected policy source branch")
    repo = api(f"repos/{repository}")
    require(repo["private"] is False, "public policy delivery requires a public repository")
    artifact = Path("dist/policy.json").read_text()
    bundle_path = Path(os.environ["POLICY_BUNDLE"])
    bundle = bundle_path.read_text()
    require(len(artifact.encode()) <= 256 * 1024 and len(bundle.encode()) <= 2 * 1024 * 1024,
            "policy evidence exceeds limits")
    parsed = json.loads(bundle)
    require(parsed.get("mediaType") == "application/vnd.dev.sigstore.bundle.v0.3+json",
            "unsupported Sigstore bundle profile")
    entries = parsed.get("verificationMaterial", {}).get("tlogEntries", [])
    require(entries and all(e.get("inclusionPromise", {}).get("signedEntryTimestamp")
                            and e.get("inclusionProof", {}).get("checkpoint", {}).get("envelope")
                            for e in entries), "missing Rekor v1 verification material")
    subprocess.run([
        "gh", "attestation", "verify", "dist/policy.json", "--bundle", str(bundle_path),
        "--repo", repository, "--signer-workflow", repository + "/.github/workflows/policy.yml",
        "--signer-digest", os.environ["WORKFLOW_COMMIT"],
        "--source-digest", os.environ["GITHUB_SHA"], "--source-ref", ref,
        "--predicate-type", "https://slsa.dev/provenance/v1", "--deny-self-hosted-runners",
    ], check=True)
    policy = json.loads(artifact)
    require(policy["policy_id"] == publisher["policy_id"] and type(policy["sequence"]) is int
            and policy["sequence"] > 0 and policy["issued_at"] <= int(time.time()) < policy["expires_at"],
            "invalid policy identity, sequence or validity")
    branch = "evidence"
    if api(f"repos/{repository}/git/ref/heads/{branch}", optional=True) is None:
        api(f"repos/{repository}/git/refs", {"ref": f"refs/heads/{branch}", "sha": os.environ["GITHUB_SHA"]})
    existing = api(f"repos/{repository}/contents/policy.json?ref={branch}", optional=True)
    if existing:
        require(existing.get("encoding") == "base64", "unexpected content encoding")
        previous = json.loads(base64.b64decode(existing["content"]))
        old = json.loads(previous["artifact"])
        # The authenticated repository value is a publication floor, not verifier
        # authority. SDKs independently authenticate policies and enforce rollback.
        require(old["policy_id"] == policy["policy_id"] and policy["sequence"] > old["sequence"],
                "policy sequence must increase")
    wrapper = json.dumps({"artifact": artifact, "bundle": bundle}, separators=(",", ":")) + "\n"
    require(len(wrapper.encode()) <= 4 * 1024 * 1024, "policy wrapper exceeds worker limit")
    Path("dist/signed-policy.json").write_text(wrapper)
    body = {"message": f"Publish signed policy {policy['sequence']}", "branch": branch,
            "content": base64.b64encode(wrapper.encode()).decode()}
    if existing:
        body["sha"] = existing["sha"]
    api(f"repos/{repository}/contents/policy.json", body, method="PUT")
    endpoint = f"https://raw.githubusercontent.com/{repository}/{branch}/policy.json"
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
        summary.write(f"Published signed policy {policy['sequence']}: {endpoint}\n")


if __name__ == "__main__":
    main()
