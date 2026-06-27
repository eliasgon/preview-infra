"""One ephemeral preview environment.

A thin wrapper that drops a ``PreviewEnvironment`` onto the shared baseline. One
of these is deployed per feature group (the resolver decides how many and with
which branches). Deleting the stack tears the whole environment down - services,
target groups, listener rules and the Aurora cluster (replica included).
"""

from __future__ import annotations

from aws_cdk import CfnOutput, Stack, Tags
from constructs import Construct

from .baseline_stack import BaselineStack
from .config import AppConfig
from .constructs.environment import PreviewEnvironment


class EphemeralEnvStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: AppConfig,
        baseline: BaselineStack,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        assert config.slug, "EphemeralEnvStack requires a --context slug"
        env_name = config.group or config.slug

        environment = PreviewEnvironment(
            self,
            "Env",
            config=config,
            vpc=baseline.vpc,
            cluster=baseline.cluster,
            listener=baseline.listener,
            alb_security_group=baseline.alb_security_group,
            repo_a=baseline.repo_a,
            repo_b=baseline.repo_b,
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

        alb_dns = baseline.alb.load_balancer_dns_name
        CfnOutput(
            self,
            "ServiceAUrl",
            value=(
                f"curl -H 'Host: {environment.service_a.hostname}' "
                f"http://{alb_dns}/info"
            ),
        )
        CfnOutput(
            self,
            "ServiceBUrl",
            value=(
                f"curl -H 'Host: {environment.service_b.hostname}' "
                f"http://{alb_dns}/info"
            ),
        )
        CfnOutput(self, "ServiceAHost", value=environment.service_a.hostname)
        CfnOutput(self, "ServiceBHost", value=environment.service_b.hostname)
