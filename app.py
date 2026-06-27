#!/usr/bin/env python3
"""CDK app entrypoint.

  # Baseline + main environment:
  npx cdk deploy PreviewBaseline

  # One ephemeral environment (the orchestrator passes these per feature group):
  npx cdk deploy PreviewEnv-checkout-flow \
      --context slug=checkout-flow \
      --context a_branch=feature/checkout-flow \
      --context b_branch=main \
      --exclusively
"""

import aws_cdk as cdk

from preview_infra.baseline_stack import BaselineStack
from preview_infra.config import AppConfig
from preview_infra.ephemeral_env_stack import EphemeralEnvStack

app = cdk.App()
config = AppConfig.from_context(app)

cdk.Tags.of(app).add("project", "preview-environments")

baseline = BaselineStack(app, "PreviewBaseline", config=config, env=config.cdk_env)

# When a slug is supplied, also synthesize that one ephemeral environment. The
# baseline is always present in the app so cross-stack references resolve.
if config.slug:
    EphemeralEnvStack(
        app,
        f"PreviewEnv-{config.slug}",
        config=config,
        baseline=baseline,
        env=config.cdk_env,
    )

app.synth()
