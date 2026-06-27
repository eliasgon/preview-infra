"""Baseline (shared) infrastructure.

Deployed once. Owns everything the environments share - the VPC, the
internet-facing ALB, the ECS Fargate cluster and the ECR repositories - plus the
long-lived `main` environment (both services running their `main` branch).

Ephemeral environments attach to this baseline rather than recreating a VPC/ALB
per environment, which is what keeps spin-up fast and cheap.
"""

from __future__ import annotations

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from constructs import Construct

from .config import AppConfig
from .constructs.environment import PreviewEnvironment


class BaselineStack(Stack):
    def __init__(
        self, scope: Construct, construct_id: str, *, config: AppConfig, **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- network --------------------------------------------------------
        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=config.nat_gateways,
            ip_addresses=ec2.IpAddresses.cidr("10.20.0.0/16"),
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24
                ),
                ec2.SubnetConfiguration(
                    name="app",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="data",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24,
                ),
            ],
        )

        # --- shared ALB -----------------------------------------------------
        self.alb_security_group = ec2.SecurityGroup(
            self,
            "AlbSg",
            vpc=self.vpc,
            description="Shared preview ALB",
            allow_all_outbound=True,
        )
        self.alb_security_group.add_ingress_rule(
            ec2.Peer.any_ipv4(), ec2.Port.tcp(80), "HTTP"
        )
        self.alb = elbv2.ApplicationLoadBalancer(
            self,
            "Alb",
            vpc=self.vpc,
            internet_facing=True,
            security_group=self.alb_security_group,
        )
        self.listener = self.alb.add_listener(
            "Http",
            port=80,
            open=False,
            default_action=elbv2.ListenerAction.fixed_response(
                404,
                content_type="text/plain",
                message_body="No preview environment matched this Host header.",
            ),
        )

        # --- shared compute -------------------------------------------------
        self.cluster = ecs.Cluster(self, "Cluster", vpc=self.vpc)

        # --- image registries ----------------------------------------------
        self.repo_a = ecr.Repository(
            self,
            "RepoA",
            repository_name="preview-service-a",
            image_scan_on_push=True,
            removal_policy=RemovalPolicy.DESTROY,
            empty_on_delete=True,
            lifecycle_rules=[ecr.LifecycleRule(max_image_count=20)],
        )
        self.repo_b = ecr.Repository(
            self,
            "RepoB",
            repository_name="preview-service-b",
            image_scan_on_push=True,
            removal_policy=RemovalPolicy.DESTROY,
            empty_on_delete=True,
            lifecycle_rules=[ecr.LifecycleRule(max_image_count=20)],
        )

        # --- the long-lived `main` environment ------------------------------
        PreviewEnvironment(
            self,
            "Main",
            config=config,
            vpc=self.vpc,
            cluster=self.cluster,
            listener=self.listener,
            alb_security_group=self.alb_security_group,
            repo_a=self.repo_a,
            repo_b=self.repo_b,
            slug="main",
            env_name="main",
            a_branch="main",
            b_branch="main",
        )

        CfnOutput(self, "AlbDnsName", value=self.alb.load_balancer_dns_name)
        CfnOutput(
            self,
            "MainServiceAExample",
            value=(
                f"curl -H 'Host: main-a.{config.base_domain}' "
                f"http://{self.alb.load_balancer_dns_name}/info"
            ),
        )
        CfnOutput(self, "RepoAUri", value=self.repo_a.repository_uri)
        CfnOutput(self, "RepoBUri", value=self.repo_b.repository_uri)
