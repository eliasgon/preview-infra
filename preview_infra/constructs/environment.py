"""A complete, isolated environment: one shared Aurora cluster + both services.

This single construct backs every environment: the long-lived main environment
in the baseline stack, and each ephemeral preview. The only differences are the
slug, the env name and which branch's image each service runs.
"""

from __future__ import annotations

import hashlib

from aws_cdk import RemovalPolicy
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_logs as logs
from constructs import Construct

from ..config import AppConfig
from .database import ServerlessDatabase
from .service import PreviewService


def _priority_base(slug: str) -> int:
    """Deterministic, collision-resistant ALB rule priority window for a slug.

    Each environment claims two adjacent priorities (one per service). Using a
    hash keeps priorities stable across redeploys so updates are in-place.
    """
    digest = int(hashlib.sha1(slug.encode()).hexdigest(), 16)
    return (digest % 24000) * 2 + 100


class PreviewEnvironment(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: AppConfig,
        vpc: ec2.IVpc,
        cluster: ecs.ICluster,
        listener: elbv2.IApplicationListener,
        alb_security_group: ec2.ISecurityGroup,
        repo_a: ecr.IRepository,
        repo_b: ecr.IRepository,
        slug: str,
        env_name: str,
        a_branch: str,
        b_branch: str,
    ) -> None:
        super().__init__(scope, construct_id)

        self.repo_a = repo_a
        self.repo_b = repo_b
        self.slug = slug

        # --- shared database (with its required read replica) ---------------
        database = ServerlessDatabase(
            self,
            "Db",
            vpc=vpc,
            min_acu=config.db_min_acu,
            max_acu=config.db_max_acu,
        )

        # --- networking: one app SG shared by both services ----------------
        app_sg = ec2.SecurityGroup(
            self,
            "AppSg",
            vpc=vpc,
            description=f"App tasks for env {slug}",
            allow_all_outbound=True,
        )
        app_sg.add_ingress_rule(
            alb_security_group,
            ec2.Port.tcp(PreviewService.CONTAINER_PORT),
            "ALB to app",
        )
        database.allow_from(app_sg)

        log_group = logs.LogGroup(
            self,
            "Logs",
            log_group_name=f"/preview/{slug}",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )

        base_priority = _priority_base(slug)

        self.service_a = PreviewService(
            self,
            "ServiceA",
            vpc=vpc,
            cluster=cluster,
            listener=listener,
            app_security_group=app_sg,
            image=self._image(config, "a"),
            environment=self._service_env(
                config, "service-a", env_name, a_branch, config.a_image_tag, database
            ),
            db_secret=database.secret,
            hostname=f"{slug}-a.{config.base_domain}",
            priority=base_priority,
            cpu_architecture=config.cpu_architecture,
            log_group=log_group,
            log_prefix="service-a",
        )

        self.service_b = PreviewService(
            self,
            "ServiceB",
            vpc=vpc,
            cluster=cluster,
            listener=listener,
            app_security_group=app_sg,
            image=self._image(config, "b"),
            environment=self._service_env(
                config, "service-b", env_name, b_branch, config.b_image_tag, database
            ),
            db_secret=database.secret,
            hostname=f"{slug}-b.{config.base_domain}",
            priority=base_priority + 1,
            cpu_architecture=config.cpu_architecture,
            log_group=log_group,
            log_prefix="service-b",
        )

    # ------------------------------------------------------------------ utils
    def _image(self, config: AppConfig, role: str) -> ecs.ContainerImage:
        if config.image_mode == "ecr":
            repo = self.repo_a if role == "a" else self.repo_b
            tag = config.a_image_tag if role == "a" else config.b_image_tag
            return ecs.ContainerImage.from_ecr_repository(repo, tag)
        # asset mode - build straight from the sibling source repo (fast on the
        # deployer's machine; CI uses ecr mode with prebuilt tags instead).
        path = config.service_a_path if role == "a" else config.service_b_path
        return ecs.ContainerImage.from_asset(path, platform=config.asset_platform)

    def _service_env(
        self,
        config: AppConfig,
        service_name: str,
        env_name: str,
        branch: str,
        image_tag: str,
        database: ServerlessDatabase,
    ) -> dict[str, str]:
        return {
            "SERVICE_NAME": service_name,
            "ENV_NAME": env_name,
            "GIT_BRANCH": branch,
            "GIT_SHA": image_tag if config.image_mode == "ecr" else "asset",
            "ROOT_PATH": "",
            "DB_WRITER_HOST": database.writer_host,
            "DB_READER_HOST": database.reader_host,
            "DB_PORT": str(ServerlessDatabase.PORT),
            "DB_NAME": ServerlessDatabase.DATABASE_NAME,
            "DB_USER": ServerlessDatabase.DATABASE_USER,
            # Seed on startup so every environment is functional end-to-end the
            # moment it comes up.
            "SEED_ON_STARTUP": "true",
            "SEED_COUNT": str(config.seed_count),
        }
