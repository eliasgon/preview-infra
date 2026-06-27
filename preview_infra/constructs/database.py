"""Per-environment Aurora PostgreSQL Serverless v2 cluster with a read replica.

Each environment (main and every ephemeral preview) gets its own cluster, so
data is fully isolated. The reader instance gives every environment its own read
replica; apps read from it via the cluster's reader endpoint.
"""

from __future__ import annotations

from aws_cdk import Duration, RemovalPolicy
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_rds as rds
from constructs import Construct


class ServerlessDatabase(Construct):
    DATABASE_NAME = "app"
    DATABASE_USER = "app"
    PORT = 5432

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.IVpc,
        min_acu: float,
        max_acu: float,
    ) -> None:
        super().__init__(scope, construct_id)

        self.security_group = ec2.SecurityGroup(
            self,
            "Sg",
            vpc=vpc,
            description="Aurora access - ingress added per app security group",
            allow_all_outbound=True,
        )

        self.cluster = rds.DatabaseCluster(
            self,
            "Cluster",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_16_4
            ),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
            ),
            security_groups=[self.security_group],
            serverless_v2_min_capacity=min_acu,
            serverless_v2_max_capacity=max_acu,
            writer=rds.ClusterInstance.serverless_v2("writer"),
            readers=[
                # The required per-environment read replica. scale_with_writer
                # keeps it sized to absorb the writer's load.
                rds.ClusterInstance.serverless_v2("reader", scale_with_writer=True),
            ],
            default_database_name=self.DATABASE_NAME,
            credentials=rds.Credentials.from_generated_secret(self.DATABASE_USER),
            storage_encrypted=True,
            # Ephemeral environments must tear down cleanly and cheaply.
            removal_policy=RemovalPolicy.DESTROY,
            delete_automated_backups=True,
            backup=rds.BackupProps(retention=Duration.days(1)),
        )

    def allow_from(self, peer: ec2.IConnectable) -> None:
        """Permit an app security group to reach Postgres."""
        self.cluster.connections.allow_default_port_from(peer, "App to Aurora")

    @property
    def writer_host(self) -> str:
        return self.cluster.cluster_endpoint.hostname

    @property
    def reader_host(self) -> str:
        return self.cluster.cluster_read_endpoint.hostname

    @property
    def secret(self):
        return self.cluster.secret
