"""Thin GitHub REST helper used by the orchestrator to discover open branches.

Stdlib-only (urllib) so the resolver package needs no third-party dependency and
stays trivially importable inside CI. Kept separate from ``feature_groups`` so
the resolution logic remains pure and unit-testable.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .feature_groups import Branch

API = "https://api.github.com"


def _get(path: str, token: str | None) -> list | dict:
    req = urllib.request.Request(f"{API}{path}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (trusted host)
        return json.loads(resp.read().decode())


def _label_overrides(owner_repo: str, token: str | None) -> dict[str, str]:
    """Map head branch -> explicit group from `feature-group:<key>` PR labels."""
    overrides: dict[str, str] = {}
    try:
        pulls = _get(f"/repos/{owner_repo}/pulls?state=open&per_page=100", token)
    except urllib.error.HTTPError:
        return overrides
    for pr in pulls if isinstance(pulls, list) else []:
        head = pr.get("head", {}).get("ref")
        for label in pr.get("labels", []):
            name = label.get("name", "")
            if name.startswith("feature-group:") and head:
                overrides[head] = name.split(":", 1)[1].strip()
    return overrides


def list_open_branches(
    owner_repo: str,
    role: str,
    *,
    token: str | None = None,
    main_branch: str = "main",
) -> list[Branch]:
    """Return non-main branches of ``owner_repo`` as resolver ``Branch`` objects."""
    token = token or os.environ.get("GITHUB_TOKEN")
    overrides = _label_overrides(owner_repo, token)
    branches: list[Branch] = []
    page = 1
    while True:
        rows = _get(f"/repos/{owner_repo}/branches?per_page=100&page={page}", token)
        if not isinstance(rows, list) or not rows:
            break
        for row in rows:
            name = row.get("name", "")
            if not name or name == main_branch:
                continue
            branches.append(Branch(repo=role, name=name, group=overrides.get(name)))
        if len(rows) < 100:
            break
        page += 1
    return branches
