# When Agents Call Agents: The Exponential Access Problem in Multi-Agent ADK Systems

*A field report from production. What we learned scaling Agent Development Kit (ADK) from twelve agents to forty-seven across four platforms — and what Google Cloud Next '26 changed.*

---

## A 47-day bug, and the question we couldn't answer

The first agent we shipped to production ran for forty-seven days before anyone noticed the bug.

It wasn't dramatic. The agent — a research assistant for the risk analytics team at an enterprise financial services customer — had been recommending document references that didn't quite exist. Hallucinated citations, written in confident prose, attached to outputs nobody reviewed line-by-line. The team only caught it when an analyst tried to look up one of those references for a regulator filing.

Forty-seven days. The fix took an hour. The conversation it triggered took six months.

The question that came out of that incident wasn't *how do we fix the agent?* It was: *Who owns this agent? What else is it doing? Would we even know if it failed differently next time?*

Nobody had a clean answer. The engineer who'd built it had moved teams. The service account ran under a shared identity. Our monitoring covered the GCP infrastructure perfectly — and said nothing about the agent's reasoning. We had twelve agents in production at that point. Nine months later we had forty-seven, across four teams and three different agent platforms.

This article is the field report. What we learned, what Google Cloud Next '26 changed, and where we landed.

![Trajectory: from one agent to forty-seven](figure-1-trajectory.svg)
*Figure 1. The fifteen-month journey. Each platform decision was right alone. The aggregate became the problem.*

---

## Why this matters now

The data behind the field experience is unambiguous. According to the [2026 Gartner CIO and Technology Executive Survey](https://www.gartner.com/en/articles/hype-cycle-for-agentic-ai), only 17% of organizations have deployed AI agents to date, yet more than 60% expect to do so within the next two years — the most aggressive adoption curve among all emerging technologies measured. Gartner's Predicts 2026 research adds the harder warning: more than 40% of agentic AI initiatives could be abandoned by 2027 if companies don't get the fundamentals right around governance and ROI.

The companies abandoning agentic AI initiatives by 2027 won't be doing so because the agents don't work. They'll be doing it because the systems became ungovernable.

A separate SailPoint and Dimensional Research survey of 353 technology professionals found that 80% of organizations had already seen AI agents take unintended actions, and 96% viewed AI agents as a growing security threat. Those numbers match what my team has been seeing.

Identity is one of the load-bearing fundamentals on Gartner's governance list. The seams across platforms are where most of the unintended actions happen.

---

## How twelve agents became forty-seven (and started crossing platforms)

The trajectory was unglamorous, the way most production stories are.

Six months in, the data team wanted an agent that could pull customer history. It made sense to put it in **Salesforce Agentforce** — that's where the CRM lived. Then the compliance team built a policy-checker on **Microsoft Copilot Studio**, because that's what their last vendor consolidation pushed them toward. Six weeks later, an enterprise notification agent went up on **AWS Bedrock AgentCore** as part of a shared services initiative.

None of these decisions were wrong individually. Each platform was the right tool for that team's job. The problem only became visible when our orchestrator agent on Vertex AI started calling all of them — and we sat down to draw the access map.

![Cross-platform agent call graph](figure-2-cross-platform-call-graph.svg)
*Figure 2. The same user request fans out across four agent platforms. Each platform sees its own slice; no single platform sees the chain.*

A user request entered through our Google Cloud-hosted coordinator. From there, it fanned out to four platforms, each with its own identity model, its own audit logs, its own policy engine. The coordinator's blast radius wasn't what we'd granted the coordinator's service account. It was the union of every transitively reachable permission — across four clouds.

The auditor's question came soon after: *who in your organization can ultimately cause a write to that customer table?*

We could answer it. Eventually. With trace IDs, log joins, and a full afternoon. That isn't governance. That's forensics.

> Governance tells you the answer before the question is asked. Forensics is what helps you answer it after the auditor walks in.

---

## What Google Cloud Next '26 unlocked

I want to start with what's good, because it's substantial.

When Google announced the **Gemini Enterprise Agent Platform** at Next '26 — the evolution of Vertex AI for agentic workloads — they shipped the agent governance primitives my team had been hand-rolling for over a year. The relief was real.

**Agent Identity** (GA) gives every agent a strongly attested cryptographic identity based on the [SPIFFE standard](https://spiffe.io). Each agent is auto-provisioned with a SPIFFE ID and an X.509 certificate that's automatically rotated every 24 hours:

```
spiffe://agents.global.org-{ORG_ID}.system.id.goog/resources/aiplatform/projects/{PROJECT_NUMBER}/locations/{LOCATION}/reasoningEngines/{AGENT_NAME}
```

Unlike service accounts, agent identities aren't shared by multiple workloads, can't be impersonated, and don't allow developers to generate long-lived keys. Inside managed Agent Runtime, agents finally have identities of their own — distinct from the service accounts they used to inherit.

The rest of the agent governance stack arrived in Preview: **Agent Registry** indexes every agent and tool centrally; **Agent Gateway** enforces policy on every agent-to-agent and agent-to-tool call with native MCP and A2A protocol support; **Agent Observability** and **Agent Anomaly Detection** deliver execution traces and LLM-as-judge anomaly scoring; **Agent Identity Auth Manager** provides a credential vault for third-party API authentication; **VPC Service Controls for Agent Identity** and **Identity-Aware Proxy for Agents** extend Zero Trust to agent traffic. Model Armor integrates inline for prompt injection and data exfiltration protection.

**Wiz AI Application Protection Platform (AI-APP)** — Wiz, [now part of Google Cloud](https://cloud.google.com/blog/products/identity-security/next26-redefining-security-for-the-ai-era-with-google-cloud-and-wiz), expands cross-platform AI security visibility into AWS AgentCore, Microsoft Copilot Studio, Salesforce Agentforce, and Databricks alongside Gemini Enterprise. Wiz AI-BOM auto-inventories AI frameworks across the environment, surfacing shadow AI tooling.

Layered on top is the **Agent Skills** open standard, with Google's official catalog at [`github.com/google/skills`](https://github.com/google/skills) providing curated, agent-first documentation that loads on demand through progressive disclosure.

Agent Identity is GA. Most of the agent governance primitives are in Preview. The direction is unmistakable: Google is building a serious native governance stack for agents, and with the Wiz integration, that stack now reaches across other major agent platforms for security posture and threat detection.

If your entire agentic estate lives inside Gemini Enterprise Agent Platform — and you can rely on Wiz for cross-platform security visibility — much of the runtime governance and security problem is solved.

But identity *lifecycle* — who owns the agent, when does it expire, has it been certified, can the auditor see the chain of approval — is a different layer. And that's where things get interesting.

---

## The architecture, in code

The system that grew on us looks unremarkable in code. Four agents on Google, three more on other platforms, the orchestrator gluing them together. In ADK with stable Gemini 3 models:

```python
# coordinator_agent.py
from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool

from research_agent import research_agent
from data_agent import data_agent
from reporter_agent import reporter_agent

coordinator_agent = LlmAgent(
    name="coordinator",
    model="gemini-3-pro",
    instruction="""
    You orchestrate a research workflow.
    1. Use the research agent for public sources.
    2. Use the data agent for internal metrics.
    3. Use the reporter agent to compose and deliver findings.
    """,
    tools=[
        AgentTool(agent=research_agent),
        AgentTool(agent=data_agent),
        AgentTool(agent=reporter_agent),
    ],
)
```

The `data_agent` references the official BigQuery skill from Google's skills catalog through its instruction:

```python
# data_agent.py
from google.adk.agents import LlmAgent
from tools.bigquery_tool import bigquery_query

# The agent's instruction references the BigQuery agent skill
# from Google's official skills catalog (github.com/google/skills).
# Progressive disclosure means the relevant guidance is loaded on demand.
data_agent = LlmAgent(
    name="data_agent",
    model="gemini-3-flash",
    instruction="""
    Run BigQuery queries against the analytics dataset.
    Follow the BigQuery agent skill conventions documented at
    github.com/google/skills/tree/main/bigquery for query patterns,
    cost optimization, and result interpretation.
    """,
    tools=[bigquery_query],
)
```

In the post-Next '26 world, each of these agents gets registered in Agent Registry, gets its SPIFFE-anchored Agent Identity, and inter-agent calls flow through Agent Gateway. With Wiz AI-APP, the security posture extends across other agent platforms in the chain. Real progress.

The complications start where lifecycle governance begins.

---

## Two layers, two scopes

It's worth being precise about what Google's stack — including Wiz — covers, and what remains identity governance territory. The two are complementary, not competing.

![Two layers, two scopes](figure-3-two-layers-two-scopes.svg)
*Figure 3. Layer 1 (runtime governance and cross-platform security) is well-served natively. Layer 2 (identity lifecycle governance) is where partner IGA fits.*

**Layer 1: Runtime governance and cross-platform security.** Agent Identity, Agent Gateway, Agent Observability, Model Armor, and Wiz AI-APP cover this layer. They answer: who is this agent (cryptographically)? What is it allowed to do at runtime? Is its behavior anomalous? Are there shadow AI tools in our environment? What's the security posture of agents across our cloud and SaaS surface?

For Layer 1, the Google Cloud + Wiz combination is now a strong native answer.

**Layer 2: Identity lifecycle governance.** Different questions: who is the human owner of this agent in the org chart? When the owner is offboarded by HR, who inherits ownership? Has this agent been certified by its owner in the last 90 days? Does the audit evidence packet meet SOX, BACEN, LGPD, HIPAA documentation requirements? Has access been revoked when scheduled?

Layer 2 is the domain enterprise Identity Governance and Administration (IGA) platforms have served for human identities for two decades. Google's stack doesn't try to be an IGA — it points to its open partner ecosystem. The reasons are good: IGA is a deeply specialized category with twenty-plus years of regulatory tooling, and replicating that natively isn't where Google's roadmap focuses.

For my team, the gap between Layer 1 and Layer 2 was where we lived for over a year before finding the right architectural shape.

---

## The bridge: making agent identities portable

The cross-platform identity lifecycle problem requires every agent's identity to be exposed in a portable format an upstream IGA can aggregate. Two patterns matter, depending on where the agent runs.

**Pattern A: self-hosted agents (ADK on Cloud Run, Cloud Run + custom runtime, GKE).** Expose a well-known endpoint that returns the agent's metadata envelope:

```python
# identity.py
from datetime import datetime
from typing import Literal
from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr

# Endpoint is protected by IAP for Agents in production.
# Identity Aware Proxy enforces caller authorization before the route runs.
router = APIRouter(dependencies=[Depends(verify_iap_jwt)])


class AgentIdentity(BaseModel):
    agent_id: str
    name: str
    version: str
    platform: str
    spiffe_id: str | None
    owner_email: EmailStr
    fallback_owner_email: EmailStr
    business_unit: str
    created_at: datetime
    last_reviewed_at: datetime | None
    model: str
    tools: list[str]
    inbound_callers: list[str]
    outbound_callees: list[str]
    classification: Literal[
        "low-risk", "medium-risk", "high-risk-data-access", "regulated"
    ]
    data_scopes: list[str]
    business_context: str
    decommission_after: datetime | None


@router.get("/.well-known/agent-identity", response_model=AgentIdentity)
async def get_identity() -> AgentIdentity:
    return AgentIdentity(
        agent_id="data-agent-prod-001",
        name="data_agent",
        version="2.4.1",
        platform="gemini-enterprise",
        spiffe_id=(
            "spiffe://agents.global.org-123456789.system.id.goog/"
            "resources/aiplatform/projects/847291/"
            "locations/us-central1/reasoningEngines/data-agent-prod-001"
        ),
        owner_email="risk-analytics-lead@example.com",
        fallback_owner_email="ai-platform-ops@example.com",
        business_unit="Risk & Analytics",
        created_at=datetime(2026, 3, 15, 14, 32),
        last_reviewed_at=datetime(2026, 4, 28),
        model="gemini-3-pro",
        tools=["bigquery_query", "spanner_read"],
        inbound_callers=["coordinator"],
        outbound_callees=[],
        classification="high-risk-data-access",
        data_scopes=[
            "bigquery:analytics.customer_metrics",
            "spanner:risk-db.exposure_v3",
        ],
        business_context=(
            "Provides aggregated risk metrics to the research orchestrator "
            "for internal analyst workflows."
        ),
        decommission_after=datetime(2026, 9, 30),
    )
```

**Pattern B: SaaS-hosted agents (Agentforce, Copilot Studio, Bedrock AgentCore).** You can't deploy a custom FastAPI route on a SaaS platform. The metadata flows through the platform's own admin API, ingested by the IGA's native connector for that platform.

![The bridge architecture](figure-4-bridge-architecture.svg)
*Figure 4. Native cryptographic identities from each platform are wrapped in a common metadata envelope, exposed at a well-known endpoint or pulled via platform APIs, and aggregated into a single IGA control plane.*

This pattern wraps Google's Agent Identity in a portable envelope. The native SPIFFE ID is preserved, but augmented with ownership, classification, lifecycle metadata, and business context that Agent Registry doesn't store and was never designed to store.

---

## Where SailPoint Agent Identity Security fit our picture

When my team scoped what an IGA layer needed to do for us, the requirements were specific: aggregate agents from every platform we used, sync agent ownership to our existing HR-driven JML pipeline, run quarterly certification campaigns auditors would actually accept, and produce a single Identity Graph that crossed clouds.

We evaluated several options and landed on **SailPoint Agent Identity Security**.

**Connector breadth.** SailPoint's documented connector catalog covers Bedrock AgentCore, Microsoft Copilot Studio, Salesforce Agentforce, ServiceNow AI Platform, Snowflake Cortex AI, Databricks Agent Bricks, and Vertex AI / Gemini Enterprise Agent Platform. Every platform in our estate had a native integration path. The Web Services SaaS connector covered the long tail — exactly where our portable `/.well-known/agent-identity` endpoint plugged in.

**Identity Graph.** SailPoint's Identity Graph turns the cross-platform call chain — human → coordinator (Google) → customer_history_agent (Agentforce) → BigQuery — into a single query. That answers the auditor's question as a data structure instead of a four-hour investigation.

**IGA fundamentals.** SailPoint has been running joiner-mover-leaver, certification campaigns, and separation of duties for two decades. Treating the agent as a first-class identity inside the same machinery that governed our human identities — instead of building parallel governance for AI — was the natural shape. Our agents joined the same control plane as our employees, with the same lifecycle events, review cadences, and audit evidence format.

For us, SailPoint Agent Identity Security and Google's Gemini Enterprise Agent Platform turned out to be complementary, not competing. Google governed the runtime. Wiz AI-APP extended security posture across platforms. SailPoint governed the lifecycle. Each did the part it was built for.

---

## What changed for our team

Six months after the IGA layer went in, the picture looked different.

When an engineer left the company, our HR system fired the offboarding event. SailPoint reassigned every agent they owned to the documented fallback owner automatically and triggered a review. Orphan agents stopped existing as a category.

When the next quarterly audit came around and the auditor asked the cross-platform question, we answered in twenty seconds with a graph query across the IGA's Identity Graph. The previous answer had taken an afternoon.

When the platform team wanted to add a new shared agent, the certification cadence and ownership pattern were already in place. The new agent joined the same governance plane as everything else from day one. Within Google Cloud, Agent Identity, Agent Registry, and Agent Gateway handled the runtime governance. Wiz AI-APP handled cross-platform security posture. Above them, SailPoint handled the human-organization lifecycle.

The agents kept doing useful work. The systems were still hard. What we'd escaped was the moment where complexity meets unaccountability.

---

## Where you might be in this journey

![Decision matrix](figure-5-decision-matrix.svg)
*Figure 5. Native governance is enough for narrow scope. Most enterprise environments hit at least three of the right-hand criteria.*

**Native Google Cloud governance + Wiz AI-APP for cross-platform security is enough when:**

- Your audit obligations are satisfied by raw audit logs and security posture findings
- Your engineering team owns agent ownership and lifecycle manually, and turnover is low
- You're not in a regulated industry with periodic certification requirements
- You don't have an existing IGA platform that already governs human identities

**You'll want a partner IGA layer like SailPoint Agent Identity Security on top when any of these are true:**

- Multi-platform agent deployment requiring identity lifecycle governance
- Regulated industry: BACEN, LGPD, SOX, GDPR, HIPAA, PCI-DSS
- External audit examines agent decisions or data access with documented certification expectations
- Headcount turnover is normal (it always is)
- 10+ agents in production, or visible runway to 50+
- Existing IGA platform already governs human identities — agents should join the same control plane

The threshold matters less than the trajectory. If you're going to scale agentic AI in production, the cross-platform identity lifecycle layer is the part that ages worst when you skip it. Bolting it on at fifty agents across four platforms is genuinely difficult. Designing for it at five agents on one platform is almost free.

---

## Closing

The 47-day bug that started this story was, eventually, just a code change. The harder fix was the system around it: an agent without a documented owner, in production without a review cadence, on a platform that didn't have HR-side accountability built in. That class of incident — the one that wastes an afternoon on forensic reconstruction and surfaces a structural gap behind a tactical bug — is what the new governance stack is built to make rare.

Google Cloud Next '26 took an enormous bite out of that gap. Agent Identity at GA, the rest of the agent governance stack maturing through Preview, and Wiz AI-APP extending cross-platform security visibility — together these mean the runtime governance question has a real answer for the first time. For teams running multi-platform with regulated audit obligations, the identity lifecycle layer is where the open partner ecosystem comes in. Our team integrated SailPoint Agent Identity Security; other Google Cloud customers will reasonably choose differently. The architectural shape is what matters: native runtime identity inside each platform, Wiz security visibility across platforms, and a partner IGA layer above all of them, anchored in the HR system that already governs human identities.

Service accounts wearing trench coats was a 2024 problem. In 2026, the question is whether your agents have identities the org chart can recognize. The Gartner data is clear about why: 60% of organizations expect to deploy AI agents within two years, and more than 40% of those initiatives are at risk of being abandoned by 2027 if governance fundamentals aren't in place. Worth catching that before the auditor does.

---

*If you're shipping multi-agent systems on ADK or Gemini Enterprise Agent Platform and want to compare notes on cross-platform identity architecture, my DMs are open.*

*Djalma is Head of Google Cloud Practice at GFT Technologies. Google Cloud Partner All-Star 2024, Distinguished Engineer 2025. He spends his days shipping ADK agents in regulated environments.*
