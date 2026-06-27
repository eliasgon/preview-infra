"""One ephemeral preview environment.

Drops a ``PreviewEnvironment`` onto the shared baseline. It imports the baseline's
VPC, ALB listener, ECS cluster and security group by reading their IDs from SSM
(published by the baseline) and reconstructing them from attributes. That keeps
the stacks fully decoupled: no CloudFormation exports, so any environment can be
deployed or destroyed on its own without touching the baseline or its siblings.

Deleting the stack tears the whole environment down, Aurora replica included.
"""

from __future__ import annotations

from aws_cdk import CfnOutput, Stack, Tags
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_ssm as ssm
from constructs import Construct

from . import config as cfg
from .config import AppConfig
from .constructs.environment import PreviewEnvironment


class EphemeralEnvStack(Stack):
    def __init__(
        self, scope: Construct, construct_id: str, *, config: AppConfig, **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        assert config.slug, "EphemeralEnvStack requires a --context slug"
        env_name = config.group or config.slug

        # Import the shared baseline resources by their published IDs.
        vpc = ec2.Vpc.from_lookup(
            self, "Vpc", vpc_id=ssm.StringParameter.value_from_lookup(self, cfg.SSM_VPC_ID)
        )
        alb_security_group = ec2.SecurityGroup.from_security_group_id(
            self, "AlbSg", ssm.StringParameter.value_from_lookup(self, cfg.SSM_ALB_SG_ID)
        )
        listener = elbv2.ApplicationListener.from_application_listener_attributes(
            self,
            "Listener",
            listener_arn=ssm.StringParameter.value_from_lookup(self, cfg.SSM_LISTENER_ARN),
            security_group=alb_security_group,
        )
        cluster = ecs.Cluster.from_cluster_attributes(
            self,
            "Cluster",
            cluster_name=ssm.StringParameter.value_from_lookup(self, cfg.SSM_CLUSTER_NAME),
            vpc=vpc,
            security_groups=[],
        )
        repo_a = ecr.Repository.from_repository_name(self, "RepoA", cfg.REPO_A_NAME)
        repo_b = ecr.Repository.from_repository_name(self, "RepoB", cfg.REPO_B_NAME)

        environment = PreviewEnvironment(
            self,
            "Env",
            config=config,
            vpc=vpc,
            cluster=cluster,
            listener=listener,
            alb_security_group=alb_security_group,
            repo_a=repo_a,
            repo_b=repo_b,
            slug=config.slug,
            env_name=env_name,
            a_branch=config.a_branch,
            b_branch=config.b_branch,
        )

        # Tags make every environment's resources discoverable (e.g. by the
        # reaper that cleans up orphaned environments).
        Tags.of(self).add("preview:managed-by", "preview-infra")
        Tags.of(self).add("preview:slug", config.slug)
        Tags.of(self).add("preview:group", env_name)

        alb_dns = ssm.StringParameter.value_from_lookup(self, cfg.SSM_ALB_DNS)
        CfnOutput(
            self,
            "ServiceAUrl",
            value=f"curl -H 'Host: {environment.service_a.hostname}' http://{alb_dns}/info",
        )
        CfnOutput(
            self,
            "ServiceBUrl",
            value=f"curl -H 'Host: {environment.service_b.hostname}' http://{alb_dns}/info",
        )
        CfnOutput(self, "ServiceAHost", value=environment.service_a.hostname)
        CfnOutput(self, "ServiceBHost", value=environment.service_b.hostname)
