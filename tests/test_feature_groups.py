"""Unit tests for the feature-group resolver.

Covers the four routing cases plus the edge cases that matter once the output
drives a real cdk deploy matrix: determinism, slug safety, linking semantics.
"""

from __future__ import annotations

from resolver.feature_groups import (
    Branch,
    make_slug,
    normalize_group,
    resolve,
)


def _by_slug(envs):
    return {e.slug: e for e in envs}


# --- the four routing cases -------------------------------------------------
def test_no_feature_branches_yields_no_envs():
    assert resolve([]) == []
    assert resolve([Branch("a", "main"), Branch("b", "main")]) == []


def test_repo_a_only():
    envs = resolve([Branch("a", "feature/checkout-flow")])
    assert len(envs) == 1
    env = envs[0]
    assert env.group == "checkout-flow"
    assert env.services["a"].branch == "feature/checkout-flow"
    assert env.services["a"].is_feature is True
    assert env.services["b"].branch == "main"
    assert env.services["b"].is_feature is False
    assert env.is_combined is False


def test_repo_b_only():
    envs = resolve([Branch("b", "feature/search")])
    assert len(envs) == 1
    env = envs[0]
    assert env.services["a"].branch == "main"
    assert env.services["b"].branch == "feature/search"
    assert env.is_combined is False


def test_both_same_group_combined():
    envs = resolve(
        [Branch("a", "feature/checkout-flow"), Branch("b", "feature/checkout-flow")]
    )
    assert len(envs) == 1
    env = envs[0]
    assert env.services["a"].is_feature is True
    assert env.services["b"].is_feature is True
    assert env.is_combined is True


def test_both_different_groups_two_envs():
    envs = resolve(
        [Branch("a", "feature/checkout-flow"), Branch("b", "feature/search")]
    )
    assert len(envs) == 2
    by_slug = _by_slug(envs)

    checkout = by_slug["checkout-flow"]
    assert checkout.services["a"].is_feature is True
    assert checkout.services["b"].branch == "main"
    assert checkout.is_combined is False

    search = by_slug["search"]
    assert search.services["a"].branch == "main"
    assert search.services["b"].is_feature is True
    assert search.is_combined is False


# --- linking semantics ------------------------------------------------------
def test_same_group_via_subpaths():
    # feature/checkout-flow and feature/checkout-flow/api share group "checkout-flow"
    envs = resolve(
        [
            Branch("a", "feature/checkout-flow"),
            Branch("b", "feature/checkout-flow/api"),
        ]
    )
    assert len(envs) == 1
    assert envs[0].is_combined is True


def test_explicit_group_override_links_differently_named_branches():
    envs = resolve(
        [
            Branch("a", "feature/wild-name", group="epic-42"),
            Branch("b", "feature/other-name", group="epic-42"),
        ]
    )
    assert len(envs) == 1
    assert envs[0].group == "epic-42"
    assert envs[0].is_combined is True


def test_plain_branch_name_links_to_prefixed():
    envs = resolve([Branch("a", "checkout-flow"), Branch("b", "feature/checkout-flow")])
    assert len(envs) == 1
    assert envs[0].is_combined is True


# --- determinism & robustness ----------------------------------------------
def test_result_is_order_independent():
    branches = [
        Branch("a", "feature/checkout-flow"),
        Branch("b", "feature/search"),
        Branch("b", "feature/checkout-flow"),
    ]
    a = [e.to_dict() for e in resolve(branches)]
    b = [e.to_dict() for e in resolve(list(reversed(branches)))]
    assert a == b


def test_unknown_repo_role_ignored():
    envs = resolve([Branch("c", "feature/x")])
    assert envs == []


def test_normalize_group_strips_prefixes():
    assert normalize_group("feature/checkout-flow") == "checkout-flow"
    assert normalize_group("fix/login-bug") == "login-bug"
    assert normalize_group("checkout-flow") == "checkout-flow"
    assert normalize_group("feature/Checkout_Flow/api") == "checkout-flow"


def test_make_slug_is_safe_and_bounded():
    long = "feature-with-an-absurdly-long-name-that-exceeds-limits"
    slug = make_slug(long)
    assert len(slug) <= 24
    assert all(c.isalnum() or c == "-" for c in slug)
    # deterministic
    assert make_slug(long) == slug
    # distinct long inputs do not collide
    assert make_slug(long + "-two") != slug


def test_to_dict_shape():
    env = resolve([Branch("a", "feature/x")])[0]
    d = env.to_dict()
    assert set(d) == {"group", "slug", "combined", "services"}
    assert set(d["services"]) == {"a", "b"}
    assert set(d["services"]["a"]) == {"repo", "branch", "is_feature"}
