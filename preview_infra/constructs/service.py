"""A single Fargate service fronted by a host-routed ALB rule.

One of these is created per microservice per environment. Routing is by Host
header (<slug>-<role>.<base-domain>), so a shared ALB can serve any number of
parallel environments with no DNS or path rewriting: you just send the right
Host header. In production a wildcard DNS record points at the ALB so the
hostnames resolve for real.
"""

from __future__ import annotations

from aws_cdk import Duration
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_logs as logs
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct


class PreviewService(Construct):
    CONTAINER_PORT = 8000

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.IVpc,
        cluster: ecs.ICluster,
        listener: elbv2.IApplicationListener,
        app_security_group: ec2.ISecurityGroup,
        image: ecs.ContainerImage,
        environment: dict[str, str],
        db_secret: secretsmanager.ISecret,
        hostname: str,
        priority: int,
        cpu_architecture: ecs.CpuArchitecture,
        log_group: logs.ILogGroup,
        log_prefix: str,
    ) -> None:
        super().__init__(scope, construct_id)

        self.hostname = hostname

        task_definition = ecs.FargateTaskDefinition(
            self,
            "Task",
            cpu=256,
            memory_limit_mib=512,
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=cpu_architecture,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
        )

        task_definition.add_container(
            "app",
            image=image,
            environment=environment,
            secrets={
                "DB_PASSWORD": ecs.Secret.from_secrets_manager(db_secret, "password"),
            },
            logging=ecs.LogDriver.aws_logs(
                stream_prefix=log_prefix, log_group=log_group
            ),
            port_mappings=[ecs.PortMapping(container_port=self.CONTAINER_PORT)],
        )

        self.service = ecs.FargateService(
            self,
            "Service",
            cluster=cluster,
            task_definition=task_definition,
            desired_count=1,
            security_groups=[app_security_group],
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            assign_public_ip=False,
            # Fast, cheap rollouts for short-lived preview environments.
            min_healthy_percent=100,
            max_healthy_percent=200,
            health_check_grace_period=Duration.seconds(120),
            # Roll back quickly if a preview build can't start, instead of
            # waiting out the (up to 3h) default failure window.
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
        )
        # Give the app room to wait out a cold Aurora cluster on first boot
        # before the target group starts counting failed health checks.

        target_group = elbv2.ApplicationTargetGroup(
            self,
            "Tg",
            vpc=vpc,
            port=self.CONTAINER_PORT,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            targets=[self.service],
            deregistration_delay=Duration.seconds(10),
            health_check=elbv2.HealthCheck(
                path="/healthz",
                healthy_http_codes="200",
                interval=Duration.seconds(15),
                timeout=Duration.seconds(5),
                healthy_threshold_count=2,
                unhealthy_threshold_count=3,
            ),
        )

        elbv2.ApplicationListenerRule(
            self,
            "Rule",
            listener=listener,
            priority=priority,
            conditions=[elbv2.ListenerCondition.host_headers([hostname])],
            action=elbv2.ListenerAction.forward([target_group]),
        )
