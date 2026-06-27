"""Typed view over CDK context / environment.

Every knob is overridable with `--context key=value` so the same app synthesizes
the baseline, the `main` environment and any ephemeral environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import aws_cdk as cdk
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_ecs as ecs

# Where the sibling service repos live relative to this CDK app, so that local
# `cdk deploy` can build images directly from source (asset mode).
DEFAULT_SERVICE_A_PATH = "../preview-service-a"
DEFAULT_SERVICE_B_PATH = "../preview-service-b"

# Fixed ECR repository names, shared by baseline and every ephemeral stack.
REPO_A_NAME = "preview-service-a"
REPO_B_NAME = "preview-service-b"

# The baseline publishes the IDs of its shared resources to these SSM parameters;
# ephemeral stacks read them back so they never depend on CloudFormation exports.
SSM_VPC_ID = "/preview/baseline/vpc-id"
SSM_LISTENER_ARN = "/preview/baseline/listener-arn"
SSM_ALB_SG_ID = "/preview/baseline/alb-sg-id"
SSM_CLUSTER_NAME = "/preview/baseline/cluster-name"
SSM_ALB_DNS = "/preview/baseline/alb-dns"


@dataclass
class AppConfig:
    account: str | None
    region: str | None

    # Identity of the environment being synthesized. slug is None for a pure
    # baseline synth; set it to also synth one ephemeral environment.
    slug: str | None
    group: str | None
    a_branch: str
    b_branch: str

    # Routing
    base_domain: str

    # Compute / image strategy
    cpu_arch: str  # "ARM64" (fast on Apple Silicon) or "X86_64"
    image_mode: str  # "asset" (build from source) or "ecr" (prebuilt tag)
    a_image_tag: str
    b_image_tag: str
    service_a_path: str
    service_b_path: str

    # Database
    db_min_acu: float
    db_max_acu: float

    # Networking / misc
    nat_gateways: int
    seed_count: int

    @staticmethod
    def from_context(app: cdk.App) -> AppConfig:
        def ctx(key: str, default=None):
            value = app.node.try_get_context(key)
            return default if value is None else value

        return AppConfig(
            account=ctx("account") or os.environ.get("CDK_DEFAULT_ACCOUNT"),
            region=ctx("region") or os.environ.get("CDK_DEFAULT_REGION"),
            slug=ctx("slug"),
            group=ctx("group"),
            a_branch=ctx("a_branch", "main"),
            b_branch=ctx("b_branch", "main"),
            base_domain=ctx("base_domain", "preview.local"),
            cpu_arch=str(ctx("cpu_arch", "ARM64")).upper(),
            image_mode=str(ctx("image_mode", "asset")).lower(),
            a_image_tag=ctx("a_image", "latest"),
            b_image_tag=ctx("b_image", "latest"),
            service_a_path=ctx("service_a_path", DEFAULT_SERVICE_A_PATH),
            service_b_path=ctx("service_b_path", DEFAULT_SERVICE_B_PATH),
            db_min_acu=float(ctx("db_min_acu", 0.5)),
            db_max_acu=float(ctx("db_max_acu", 2)),
            nat_gateways=int(ctx("nat_gateways", 1)),
            seed_count=int(ctx("seed_count", 5)),
        )

    # --- derived CDK enums --------------------------------------------------
    @property
    def cdk_env(self) -> cdk.Environment | None:
        if self.account and self.region:
            return cdk.Environment(account=self.account, region=self.region)
        return None

    @property
    def cpu_architecture(self) -> ecs.CpuArchitecture:
        return (
            ecs.CpuArchitecture.ARM64
            if self.cpu_arch == "ARM64"
            else ecs.CpuArchitecture.X86_64
        )

    @property
    def asset_platform(self) -> ecr_assets.Platform:
        return (
            ecr_assets.Platform.LINUX_ARM64
            if self.cpu_arch == "ARM64"
            else ecr_assets.Platform.LINUX_AMD64
        )
