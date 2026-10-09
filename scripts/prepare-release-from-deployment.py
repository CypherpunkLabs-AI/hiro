#!/usr/bin/env python3
"""Prepare a release only from a successful deployment of this exact source commit."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from hiro import ROOT, matches, read, require
from publish_common import api, identity


def deployment_files(captured):
    # upload-artifact preserves dist/ because images.lock.json is at the
    # repository root, so their least common parent is the repository itself.
    files = {"lock": captured / "images.lock.json",
             "deployment": captured / "dist/deployment.json",
             "compose": captured / "dist/app-compose.json"}
    for key, limit in (("lock", 65536), ("deployment", 8192), ("compose", 262144)):
        path = files[key]
        require(path.is_file() and not path.is_symlink() and path.stat().st_size <= limit,
                f"invalid deployment artifact: {path.relative_to(captured)}")
    return files


def find_deployment(repository, commit, requested):
    if requested:
        require(matches(requested, r"[1-9][0-9]*"), "invalid deployment run")
        return api(f"repos/{repository}/actions/runs/{requested}")
    runs = api(f"repos/{repository}/actions/runs?head_sha={commit}&branch=main&status=success&per_page=100")
    candidates = [run for run in runs["workflow_runs"]
                  if run["head_sha"] == commit and run["head_branch"] == "main"
                  and run["status"] == "completed" and run["conclusion"] == "success"
                  and run["path"] in (".github/workflows/validate.yml", ".github/workflows/deploy.yml")]
    require(candidates, "no successful deployment exists for the tagged source commit")
    return max(candidates, key=lambda run: run["id"])


def verify_deployment_lock(captured, expected):
    require(captured == expected, "deployed image lock differs from the tagged source's immutable image pins")


def main():
    repository, _, _ = identity("release")
    ref = os.environ["GITHUB_REF"]
    require(ref.startswith("refs/tags/") and matches(ref[10:], r"[A-Za-z0-9][A-Za-z0-9._-]*"), "select a release tag")
    run = find_deployment(repository, os.environ["GITHUB_SHA"], os.environ.get("DEPLOYMENT_RUN", ""))
    require(run["status"] == "completed" and run["conclusion"] == "success"
            and run["head_sha"] == os.environ["GITHUB_SHA"] and run["head_branch"] == "main"
            and run["event"] in ("push", "workflow_dispatch")
            and run["path"] in (".github/workflows/validate.yml", ".github/workflows/deploy.yml")
            and run["repository"]["full_name"].lower() == repository.lower(),
            "release requires a successful deployment of the tagged source commit")
    run_id = str(run["id"])
    defaults = read("trust/release.json") if (ROOT / "trust/release.json").is_file() else {}
    sequence = os.environ.get("RELEASE_SEQUENCE") or os.environ["GITHUB_RUN_NUMBER"]
    platform = os.environ.get("PLATFORM_ID") or defaults.get("platform_id", "")
    kms = os.environ.get("KMS_ID") or defaults.get("kms_id", "")
    lifetime = os.environ.get("RELEASE_LIFETIME") or "604800"
    with tempfile.TemporaryDirectory(prefix="hiro-release-") as directory:
        subprocess.run(["gh", "run", "download", run_id, "--repo", repository, "--name",
                        f"hiro-deployment-{run_id}-{run['run_attempt']}", "--dir", directory], check=True)
        captured = deployment_files(Path(directory))
        lock = json.loads(captured["lock"].read_bytes())
        expected = read("images.lock.json")
        verify_deployment_lock(lock, expected)
        subprocess.run([sys.executable, str(Path(__file__).with_name("verify-images"))], check=True)
        deployment = json.loads(captured["deployment"].read_bytes())
        subprocess.run([sys.executable, str(Path(__file__).with_name("hiro.py")), "prepare-release",
                        "--app-compose", str(captured["compose"]), "--app-id", deployment["app_id"],
                        "--source-commit", os.environ["GITHUB_SHA"], "--tag", ref[10:],
                        "--sequence", sequence, "--platform-id", platform,
                        "--kms-id", kms, "--lifetime-seconds", lifetime], check=True)
        require(read("dist/release.json")["compose_sha256"] == deployment["compose_sha256"], "deployment digest mismatch")


if __name__ == "__main__":
    main()
