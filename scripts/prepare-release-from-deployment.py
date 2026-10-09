#!/usr/bin/env python3
"""Prepare a release only from a successful deployment of this exact source commit."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from hiro import ROOT, matches, read, require
from publish_common import api, identity


def main():
    repository, _, _ = identity("release")
    ref = os.environ["GITHUB_REF"]
    require(ref.startswith("refs/tags/") and matches(ref[10:], r"[A-Za-z0-9][A-Za-z0-9._-]*"), "select a release tag")
    run_id = os.environ["DEPLOYMENT_RUN"]
    require(matches(run_id, r"[1-9][0-9]*"), "invalid deployment run")
    run = api(f"repos/{repository}/actions/runs/{run_id}")
    require(run["status"] == "completed" and run["conclusion"] == "success"
            and run["head_sha"] == os.environ["GITHUB_SHA"] and run["head_branch"] == "main"
            and run["event"] in ("push", "workflow_dispatch")
            and run["path"] in (".github/workflows/validate.yml", ".github/workflows/deploy.yml")
            and run["repository"]["full_name"].lower() == repository.lower(),
            "release requires a successful deployment of the tagged source commit")
    with tempfile.TemporaryDirectory(prefix="hiro-release-") as directory:
        subprocess.run(["gh", "run", "download", run_id, "--repo", repository, "--name",
                        f"hiro-deployment-{run_id}-{run['run_attempt']}", "--dir", directory], check=True)
        captured = Path(directory)
        for name, limit in (("images.lock.json", 65536), ("deployment.json", 8192), ("app-compose.json", 262144)):
            path = captured / name
            require(path.is_file() and not path.is_symlink() and path.stat().st_size <= limit,
                    f"invalid deployment artifact: {name}")
        lock = json.loads((captured / "images.lock.json").read_bytes())
        expected = read("images.lock.json")
        require(set(lock["services"]) == set(expected["services"]), "deployment services changed")
        for name, image in lock["services"].items():
            require(image["image"] == expected["services"][name]["image"]
                    and image["source_repository"] == expected["services"][name]["source_repository"],
                    "deployment image identity changed")
        shutil.copyfile(captured / "images.lock.json", ROOT / "images.lock.json")
        subprocess.run([sys.executable, str(Path(__file__).with_name("verify-images"))], check=True)
        deployment = json.loads((captured / "deployment.json").read_bytes())
        subprocess.run([sys.executable, str(Path(__file__).with_name("hiro.py")), "prepare-release",
                        "--app-compose", str(captured / "app-compose.json"), "--app-id", deployment["app_id"],
                        "--source-commit", os.environ["GITHUB_SHA"], "--tag", ref[10:],
                        "--sequence", os.environ["RELEASE_SEQUENCE"], "--platform-id", os.environ["PLATFORM_ID"],
                        "--kms-id", os.environ["KMS_ID"], "--lifetime-seconds", os.environ["RELEASE_LIFETIME"]], check=True)
        require(read("dist/release.json")["compose_sha256"] == deployment["compose_sha256"], "deployment digest mismatch")


if __name__ == "__main__":
    main()
