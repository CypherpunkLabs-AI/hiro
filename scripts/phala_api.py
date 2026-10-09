"""Bounded, authenticated reads from the pinned Phala Cloud API version."""
import json
import os
import urllib.error
import urllib.request

from hiro import require


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Phala API redirects are not permitted")


def query(path):
    request = urllib.request.Request("https://cloud-api.phala.com/api/v1/" + path,
        headers={"X-API-Key": os.environ["PHALA_CLOUD_API_KEY"], "Accept": "application/json",
                 "Content-Type": "application/json", "User-Agent": "hiro-deployment/1",
                 "X-Phala-Version": "2026-06-23"})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as error:
        with error:
            raw = error.read(8192)
        try:
            body = json.loads(raw)
            detail = body.get("detail", body.get("message", "request rejected"))
            detail = detail if isinstance(detail, str) else "request rejected"
        except (ValueError, AttributeError):
            detail = "non-JSON response from Phala API"
        detail = detail.replace(os.environ["PHALA_CLOUD_API_KEY"], "[redacted]")
        raise ValueError(f"Phala GET {path}: HTTP {error.code}: {detail[:500]}") from None
    require(len(raw) <= 4 * 1024 * 1024, "Phala response exceeds limit")
    return json.loads(raw)
