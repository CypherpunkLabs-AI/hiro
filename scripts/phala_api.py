"""Bounded, authenticated reads from the pinned Phala Cloud API version."""
import json
import os
import urllib.request

from hiro import require


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Phala API redirects are not permitted")


def query(path):
    request = urllib.request.Request("https://cloud-api.phala.com/api/v1/" + path,
        headers={"X-API-Key": os.environ["PHALA_CLOUD_API_KEY"], "Accept": "application/json",
                 "X-Phala-Version": "2026-06-23"})
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
        raw = response.read(4 * 1024 * 1024 + 1)
    require(len(raw) <= 4 * 1024 * 1024, "Phala response exceeds limit")
    return json.loads(raw)
