"""Command-line entrypoint for the resolver, used by GitHub Actions.

Two modes:

  # From an explicit list of branches (used in tests / dry-runs):
  python -m resolver.cli --branches '[{"repo":"a","name":"feature/x"}]'

  # From live GitHub state (used by the orchestrator workflow):
  python -m resolver.cli --from-github \
      --repo-a owner/preview-service-a --repo-b owner/preview-service-b

Emits JSON to stdout:
  {"envs": [...], "slugs": [...], "matrix": {"include": [...]}}

and, when $GITHUB_OUTPUT is set, writes `matrix=...` and `slugs=...` so a
downstream matrix job can fan out one `cdk deploy` per environment.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .feature_groups import Branch, PreviewEnv, resolve, slugify


def _parse_branches(raw: str) -> list[Branch]:
    data = json.loads(raw)
    return [
        Branch(repo=b["repo"], name=b["name"], group=b.get("group")) for b in data
    ]


def _matrix_include(envs: list[PreviewEnv]) -> list[dict]:
    """Flatten envs into a GitHub Actions matrix `include` list."""
    include = []
    for env in envs:
        entry = {
            "slug": env.slug,
            "group": env.group,
            "combined": env.is_combined,
        }
        for role, svc in env.services.items():
            entry[f"{role}_branch"] = svc.branch
            entry[f"{role}_is_feature"] = svc.is_feature
            # Image tag convention: service CI tags each build with the
            # slugified branch name, so the orchestrator can pull it by tag.
            entry[f"{role}_tag"] = slugify(svc.branch)
        include.append(entry)
    return include


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve ephemeral preview envs.")
    parser.add_argument("--branches", help="Inline JSON list of branches.")
    parser.add_argument("--branches-file", help="Path to JSON list, or '-' for stdin.")
    parser.add_argument("--from-github", action="store_true")
    parser.add_argument("--repo-a", help="owner/name of service A repo.")
    parser.add_argument("--repo-b", help="owner/name of service B repo.")
    parser.add_argument("--main", default="main")
    args = parser.parse_args(argv)

    branches: list[Branch] = []
    if args.from_github:
        from .github import list_open_branches  # local import: needs network

        if not (args.repo_a and args.repo_b):
            parser.error("--from-github requires --repo-a and --repo-b")
        branches += list_open_branches(args.repo_a, "a", main_branch=args.main)
        branches += list_open_branches(args.repo_b, "b", main_branch=args.main)
    elif args.branches:
        branches = _parse_branches(args.branches)
    elif args.branches_file:
        raw = sys.stdin.read() if args.branches_file == "-" else open(args.branches_file).read()
        branches = _parse_branches(raw)
    else:
        parser.error("provide --branches, --branches-file, or --from-github")

    envs = resolve(branches, main_branch=args.main)
    matrix = {"include": _matrix_include(envs)}
    slugs = [e.slug for e in envs]
    payload = {"envs": [e.to_dict() for e in envs], "slugs": slugs, "matrix": matrix}

    print(json.dumps(payload, indent=2))

    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as fh:
            fh.write(f"matrix={json.dumps(matrix)}\n")
            fh.write(f"slugs={json.dumps(slugs)}\n")
            fh.write(f"count={len(envs)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
