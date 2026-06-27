"""Pure feature-group resolution logic.

One rule drives everything: there is one environment per feature group, and
within an environment each repo runs that group's branch if it has one, else
main. That gives:

    A has a branch, B doesn't   -> { a: <branch>, b: main }
    B has a branch, A doesn't   -> { a: main, b: <branch> }
    A and B share a group       -> { a: <a-branch>, b: <b-branch> }
    A and B in different groups -> two envs, one per group

A branch's group key is an explicit `feature-group:<key>` PR label if present,
otherwise the branch name with any workflow prefix stripped, slugified down to
its first path segment. So feature/checkout-flow and feature/checkout-flow/api
land in the same group, and two repos join a group just by sharing a branch name.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

# Branch-name prefixes that are organisational, not part of the group key.
WORKFLOW_PREFIXES = (
    "feature",
    "feat",
    "fix",
    "bugfix",
    "hotfix",
    "chore",
    "preview",
)

DEFAULT_MAIN = "main"
DEFAULT_REPOS = ("a", "b")
MAX_SLUG_LEN = 24


def slugify(value: str) -> str:
    """Lowercase, collapse non-alphanumerics to single hyphens, trim."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "env"


def normalize_group(branch_name: str) -> str:
    """Derive a feature-group key from a branch name.

    Strips a leading workflow prefix and keys off the first remaining path
    segment, so `feature/checkout-flow/api` and `feature/checkout-flow/ui`
    share group ``checkout-flow``.
    """
    parts = [p for p in branch_name.strip("/").split("/") if p]
    if parts and parts[0].lower() in WORKFLOW_PREFIXES:
        parts = parts[1:]
    base = parts[0] if parts else branch_name
    return slugify(base)


def make_slug(group: str, max_len: int = MAX_SLUG_LEN) -> str:
    """AWS/DNS/path-safe, length-bounded slug for a group.

    Truncates long keys but appends a short deterministic hash so distinct long
    keys never collide into the same environment.
    """
    slug = slugify(group)
    if len(slug) <= max_len:
        return slug
    digest = hashlib.sha1(group.encode()).hexdigest()[:6]
    return f"{slug[: max_len - 7]}-{digest}"


@dataclass(frozen=True)
class Branch:
    """A branch that is currently open in one of the service repos.

    ``repo`` is the logical role ("a" or "b"), not the GitHub repo name, so the
    resolver is decoupled from naming. ``group`` is an optional explicit
    override (e.g. from a `feature-group:<key>` PR label).
    """

    repo: str
    name: str
    group: str | None = None

    def group_key(self) -> str:
        if self.group:
            return slugify(self.group)
        return normalize_group(self.name)


@dataclass(frozen=True)
class EnvService:
    repo: str
    branch: str
    is_feature: bool  # False means pinned to main


@dataclass(frozen=True)
class PreviewEnv:
    group: str
    slug: str
    services: dict[str, EnvService] = field(default_factory=dict)

    @property
    def is_combined(self) -> bool:
        """True when more than one repo contributes a feature branch."""
        return sum(1 for s in self.services.values() if s.is_feature) > 1

    def to_dict(self) -> dict:
        return {
            "group": self.group,
            "slug": self.slug,
            "combined": self.is_combined,
            "services": {
                role: {
                    "repo": svc.repo,
                    "branch": svc.branch,
                    "is_feature": svc.is_feature,
                }
                for role, svc in self.services.items()
            },
        }


def resolve(
    branches: list[Branch],
    repos: tuple[str, ...] = DEFAULT_REPOS,
    main_branch: str = DEFAULT_MAIN,
) -> list[PreviewEnv]:
    """Resolve the set of ephemeral environments that should exist.

    Only environments containing at least one feature branch are returned; the
    all-``main`` baseline environment is owned by the BaselineStack, not here.
    """
    repo_set = set(repos)
    # repo -> {group_key: branch_name}; deterministic via sorted input.
    by_repo_group: dict[str, dict[str, str]] = {r: {} for r in repos}
    group_order: list[str] = []

    for branch in sorted(branches, key=lambda b: (b.repo, b.name)):
        if branch.repo not in repo_set:
            continue
        if branch.name == main_branch:
            continue
        key = branch.group_key()
        # One branch per repo per group; the first (sorted) wins deterministically.
        by_repo_group[branch.repo].setdefault(key, branch.name)
        if key not in group_order:
            group_order.append(key)

    envs: list[PreviewEnv] = []
    for key in sorted(group_order):
        services: dict[str, EnvService] = {}
        for role in repos:
            branch_name = by_repo_group[role].get(key, main_branch)
            services[role] = EnvService(
                repo=role,
                branch=branch_name,
                is_feature=branch_name != main_branch,
            )
        envs.append(PreviewEnv(group=key, slug=make_slug(key), services=services))
    return envs
