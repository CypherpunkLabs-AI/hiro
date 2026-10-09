"""Pinned-signing-workflow helpers; publish exact bytes after signature appraisal."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from hiro import read, require

BRANCH = "evidence"


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
    require(len(result.stdout.encode()) <= 4 * 1024 * 1024, "GitHub response exceeds limit")
    return json.loads(result.stdout)


def identity(kind):
    repository = os.environ["GITHUB_REPOSITORY"]
    config = read("trust/publishers.json")
    publisher = config[kind + "_publisher"]
    repo = api(f"repos/{repository}")
    require(repo["private"] is False, "public evidence requires public-good Sigstore")
    require(publisher["repository"].lower() == repository.lower()
            and publisher["repository_id"] == repo["id"]
            and publisher["owner_id"] == repo["owner"]["id"], "publisher identity mismatch")
    require(publisher["workflow_commit"] == os.environ["SIGNER_COMMIT"], "signing revision differs from trust")
    return repository, config, publisher


def verify_bundle(artifact_path, bundle_path, repository, publisher, source_ref, source_commit=None):
    artifact = Path(artifact_path).read_bytes()
    bundle = Path(bundle_path).read_bytes()
    require(len(artifact) <= 256 * 1024 and len(bundle) <= 2 * 1024 * 1024, "signed evidence exceeds limits")
    parsed = json.loads(bundle)
    require(parsed.get("mediaType") == "application/vnd.dev.sigstore.bundle.v0.3+json", "unsupported Sigstore bundle")
    entries = parsed.get("verificationMaterial", {}).get("tlogEntries", [])
    require(entries and all(e.get("inclusionPromise", {}).get("signedEntryTimestamp")
                            and e.get("inclusionProof", {}).get("checkpoint", {}).get("envelope")
                            for e in entries), "missing Rekor verification material")
    command = ["gh", "attestation", "verify", str(artifact_path), "--bundle", str(bundle_path),
               "--repo", repository, "--signer-workflow", repository + "/" + publisher["workflow"],
               "--signer-digest", publisher["workflow_commit"], "--source-ref", source_ref,
               "--predicate-type", "https://slsa.dev/provenance/v1", "--deny-self-hosted-runners"]
    if source_commit:
        command += ["--source-digest", source_commit]
    subprocess.run(command, check=True)
    return artifact.decode(), bundle.decode()


def wrapper(artifact, bundle):
    value = json.dumps({"artifact": artifact, "bundle": bundle}, separators=(",", ":")) + "\n"
    require(len(value.encode()) <= 4 * 1024 * 1024, "wrapper exceeds worker limit")
    return value


def existing(repository, path):
    value = api(f"repos/{repository}/contents/{path}?ref={BRANCH}", optional=True)
    if value is None:
        return None, None
    require(value.get("encoding") == "base64", "unexpected evidence content encoding")
    raw = base64.b64decode(value["content"], validate=False)
    require(len(raw) <= 4 * 1024 * 1024, "existing evidence exceeds limit")
    return json.loads(raw), value["sha"]


def publish(repository, path, content, previous_sha, message):
    if api(f"repos/{repository}/git/ref/heads/{BRANCH}", optional=True) is None:
        api(f"repos/{repository}/git/refs", {"ref": f"refs/heads/{BRANCH}", "sha": os.environ["GITHUB_SHA"]})
    body = {"message": message, "branch": BRANCH, "content": base64.b64encode(content.encode()).decode()}
    if previous_sha:
        body["sha"] = previous_sha
    api(f"repos/{repository}/contents/{path}", body, method="PUT")
    endpoint = f"https://raw.githubusercontent.com/{repository}/{BRANCH}/{path}"
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
        summary.write(f"{message}: {endpoint}\n")


def valid_release(release):
    require(release["schema"] == 1 and type(release["sequence"]) is int and release["sequence"] > 0,
            "invalid release sequence")
    now = int(time.time())
    require(release["issued_at"] <= now < release["expires_at"]
            and release["expires_at"] - release["issued_at"] <= 604800, "invalid release lifetime")


def digest(artifact):
    return hashlib.sha256(artifact.encode()).hexdigest()
