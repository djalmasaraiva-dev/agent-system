"""Deploy the coordinator agent to Vertex AI Agent Engine (managed runtime).

Run from the project root:

    uv run python deployment/agent_engine_deploy.py \
        --project acme-financials --location us-central1 \
        --staging-bucket gs://acme-financials-agent-staging \
        --display-name agent-system-coordinator

This is the alternative deployment target to Cloud Run. Agent Engine gives you:
  * Managed scaling and session persistence (VertexAiSessionService).
  * Native Agent Identity (SPIFFE) auto-provisioned per reasoning engine.
  * Built-in Agent Observability traces.
"""

from __future__ import annotations

import argparse
import sys

import vertexai
from vertexai import agent_engines

from app.agent_engine_app import build_adk_app


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", default="acme-financials")
    p.add_argument("--location", default="us-central1")
    p.add_argument(
        "--staging-bucket",
        required=True,
        help="GCS bucket (gs://...) used to stage the wheel for Agent Engine.",
    )
    p.add_argument("--display-name", default="agent-system-coordinator")
    p.add_argument(
        "--description",
        default=(
            "Multi-agent ADK coordinator (research + data + reporter). "
            "Deployed via Vertex AI Agent Engine."
        ),
    )
    p.add_argument(
        "--update",
        metavar="RESOURCE_NAME",
        help="If set, update an existing Agent Engine resource instead of creating.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    vertexai.init(
        project=args.project,
        location=args.location,
        staging_bucket=args.staging_bucket,
    )

    adk_app = build_adk_app()

    requirements = [
        "google-adk>=1.0.0",
        "google-cloud-aiplatform[adk,agent-engines]>=1.95.0",
        "google-cloud-bigquery>=3.25.0",
        "google-auth>=2.35.0",
        "pydantic>=2.9.0",
        "pydantic-settings>=2.6.0",
    ]

    if args.update:
        print(f"==> Updating Agent Engine resource: {args.update}")
        remote = agent_engines.update(
            resource_name=args.update,
            agent_engine=adk_app,
            requirements=requirements,
            display_name=args.display_name,
            description=args.description,
        )
    else:
        print("==> Creating new Agent Engine resource")
        remote = agent_engines.create(
            agent_engine=adk_app,
            requirements=requirements,
            extra_packages=["./app"],
            display_name=args.display_name,
            description=args.description,
        )

    print("\n✅ Deployed.")
    print(f"   resource_name = {remote.resource_name}")
    print(f"   region        = {args.location}")
    print(f"   project       = {args.project}")
    print(
        "\nInvoke with:\n"
        "   from vertexai import agent_engines\n"
        f"   remote = agent_engines.get('{remote.resource_name}')\n"
        "   for ev in remote.stream_query(user_id='djalma', message='...'): print(ev)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
