# Weaves Product Strategy and Delivery Plan

**Status:** Research-backed planning draft
**Research reviewed:** 2026-10-05
**Product direction:** Horizontal, multi-tenant SaaS for organization-specific AI agents

## 1. Executive summary

Weaves should help organizations turn their own tools, data, and operating
context into useful AI agents and workflows. An organization connects systems,
defines what each agent is allowed to know and do, and gives employees
approved ways to use those agents. Weaves supplies the shared runtime,
connectors, context handling, execution controls, and operational visibility.

The product is horizontal: an agent can support any bounded use case that
benefits from an organization's context and systems. Examples include customer
support, sales operations, finance, people operations, IT, engineering,
compliance, and internal knowledge work. The launch plan should prove reusable
platform capabilities through a small number of customer-selected workflows;
it should not commit the product to one department.

The competitive research suggests that agent creation alone is becoming a
standard feature. Leading products combine agents with connected tools,
knowledge, workflow triggers, access controls, and operations. Weaves should
compete as the customer-facing SaaS that makes those pieces work together
across an organization's existing systems, with a clear view of what an agent
can access, what it did, and how well it completed the task.

## 2. Product thesis

### Product promise

> Connect the systems your organization already uses, then create and operate
> agents that can use the right context and take approved actions for your
> teams.

An agent in Weaves is a governed, versioned product object. It combines:

- A purpose, instructions, and expected output.
- An allowed model profile.
- Approved context sources and tool capabilities.
- A workflow or interaction surface.
- Limits for autonomy, cost, time, and data access.
- An observable run history, with artifacts and audit facts.

Weaves sells useful task completion and the controls that make it dependable.
It should not be presented only as a prompt editor, model router, connector
catalog, or generic AI control plane.

### Product boundaries

Weaves owns the cross-customer platform capabilities: tenant isolation,
identity, connector and capability management, agent and workflow lifecycle,
runtime, policy enforcement, observability, and the managed service.

Each organization owns its agent purposes, tool connections, access rules,
context, workflow configuration, and model-provider choices. Weaves may offer
starter agents and workflow templates, but customer-specific operating logic
must not be baked into a single Weaves-owned vertical.

### Working target customer

**Hypothesis to validate:** organizations with several business systems and
recurring coordination work, but without the capacity or appetite to build and
maintain an internal agent platform. Likely first buyers include operations,
IT, or AI/platform leaders; likely users are the teams doing the repeatable
work.

This is a discovery hypothesis, not a proven ideal customer profile. Research
should determine whether the buyer is a central platform team or a business
function, which organization size has urgent demand, and who owns the budget.

## 3. Competitive research and implications

### Razorpay: Slash and Agent Studio

Razorpay positions Slash as a SaaS software-engineering agent product under
Agent Studio. Razorpay's engineering article also describes how its internal
agentic SDLC uses agents for coding, PR review, ticket-triggered work, scheduled
skills, internal-system integrations, and company knowledge search. The wider
Agent Studio offering includes customer-facing payment and post-payment
operations agents, with prebuilt agents and a no-code agent builder in beta.

**Implication for Weaves:** treat Slash as a direct product reference for
software-development workflows and Agent Studio as a broader reference for
business workflows, skills, multiple triggers, a shared tool layer, and
operational learning. Weaves should support many departments while packaging
concrete, measurable workflows for adoption.

Sources: [Razorpay on Slash](https://razorpay.com/blog/?p=26885),
[Agent Studio terms](https://razorpay.com/tnc/agent-studio/),
[Razorpay Agent Studio launch](https://razorpay.com/blog/agent-studio-ai-agents-by-razorpay/).

### Microsoft Copilot Studio

Microsoft documents a builder that combines agents, knowledge sources,
connectors, tools, workflows, publication surfaces, analytics, evaluation, and
data policies. Its connector model includes Microsoft and non-Microsoft
systems. Governance can restrict authentication and connector use at the
organization level.

**Implication for Weaves:** customers will expect a complete lifecycle, from
building and testing through publishing and monitoring. Connector access and
identity policy need to be visible product controls, rather than backend-only
configuration.

Sources: [Copilot Studio overview](https://learn.microsoft.com/en-us/microsoft-copilot-studio/),
[connectors and tools](https://learn.microsoft.com/en-us/microsoft-copilot-studio/copilot-connectors-in-copilot-studio),
[data loss prevention policies](https://learn.microsoft.com/en-us/microsoft-copilot-studio/admin-data-loss-prevention).

### Workato Agent Studio

Workato's agent product combines agents, knowledge bases, reusable skills,
workflow recipes, chat surfaces, and connections to apps and MCP servers. Its
documentation describes role-based access, audit trails, approval steps, and
verified user access that lets a skill run with an end user's identity.

**Implication for Weaves:** reusable skills and workflows can make horizontal
agents practical; permissions should be tied to authenticated identity and
connected-system permissions, not to claims inside a conversation. Approvals
should fit into real business processes.

Sources: [Workato Agent Studio](https://docs.workato.com/en/agentic/agent-studio),
[establishing user identity](https://docs.workato.com/en/agentic/agent-studio/genie-governance/establish-user-identity),
[business approvals](https://docs.workato.com/en/agentic/agent-studio/business-approvals.html).

### AWS Bedrock AgentCore

AWS presents AgentCore as modular infrastructure for agent runtime, tools,
identity, memory, policy, and observability. It is a building block for teams
creating agent applications, rather than a complete cross-functional business
agent product by itself.

**Implication for Weaves:** managed infrastructure lowers the cost of building
the runtime, but Weaves must own the user-facing layer: onboarding, organization
context, agent lifecycle, workflows, controls, and outcome visibility. Keep
runtime and model choices behind interfaces so Weaves can adopt or replace
infrastructure as requirements change.

Sources: [AgentCore overview](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html),
[AgentCore release notes](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/release-notes.html).

### Market read

Across these examples, agents are packaged with tools, knowledge, triggers,
identity, approvals, and monitoring. These capabilities are table stakes for a
serious product. A more defensible Weaves position will come from:

1. A fast path from an organization's existing systems to a useful, scoped
   agent.
2. Consistent access control across context retrieval and tool actions.
3. Workflows and skills that customers can adapt and reuse across teams.
4. Reliable evaluation and operational evidence for each workflow.
5. A managed experience that works across model providers and heterogeneous
   business systems.

The research does not establish that Weaves has a technical moat yet. The plan
should validate adoption, task success, and repeat usage before treating any
one of these as differentiation.

## 4. Product principles

1. **Start with work, then configure agents.** Users should recognize a task
   such as answering a policy question, preparing a customer response, or
   reconciling records. Agent concepts support that job.
2. **One platform, many use cases.** Department templates specialize shared
   capabilities; each department does not get a separate runtime.
3. **Context is permissioned.** Retrieval must honor source-level and
   user-level access rules. Relevant data is not automatically authorized data.
4. **Actions have declared limits.** Every capability declares inputs,
   outputs, risk, identity mode, and approval requirements.
5. **The product is model-neutral.** Model selection and credentials are
   managed through profiles and a gateway.
6. **Runs are explainable and reviewable.** A user can see sources used,
   actions attempted, approvals, outputs, and failures.
7. **Prefer bounded autonomy.** Start with read and draft operations. Increase
   autonomy only when evaluations and customer policy support it.
8. **Make the managed path excellent.** Customer-hosted operation remains an
   architectural option, not a first-release requirement.

## 5. Product model

The existing platform plan has the right core entities. Organize the product
around five connected layers:

### A. Organization and identity

Organizations, workspaces, users, service principals, roles, and policy
bindings define the customer boundary and the actor requesting work. Workspace
is mandatory for executable agents, integrations, workflows, runs, and
artifacts. Use one default workspace for simple customers.

### B. Connections and context

An administrator connects a system and chooses the authentication model:

- User-delegated access where actions or reads must respect each user's
  existing permissions.
- Workspace service identity for explicitly shared use cases, with narrow
  scopes and clear ownership.

Connectors expose typed capabilities and, where appropriate, searchable
knowledge sources. Context items retain provenance, source references,
timestamps, access scope, and deletion/retention metadata. Do not build a
universal company graph before customers demonstrate a need for cross-system
entity resolution.

### C. Agents, skills, and workflows

- An **agent** reasons over context and selects among allowed skills.
- A **skill** is a reusable bounded operation or task that can be tested and
  shared.
- A **workflow** defines a repeatable trigger and sequence of steps, including
  agent calls and approvals.
- Definitions are versioned; published runs pin exact versions.

Keep the first workflow model code-backed with typed configuration, as the
Phase 1 contract plan recommends. Add a visual graph editor only when usage
proves customers need custom orchestration beyond reusable skills and
templates.

### D. Execution and controls

The runtime resolves identity and workspace, constructs permitted context,
executes a bounded agent loop, dispatches tool calls through a gateway, and
persists run events and artifacts. Policy checks occur at execution time, not
only when an agent is saved.

Risk levels should at minimum distinguish read, draft, reversible write, and
high-impact write. Approval policy can require confirmation per action, per
workflow, or by role. The initial product should not allow a model to silently
grant itself a capability or bypass the connector's source permissions.

### E. Surfaces and operations

Start with a web workspace and one collaboration surface selected with pilot
customers (likely Slack or Microsoft Teams). Add API and event/webhook entry
points for workflows. Provide run history, source citations, approval inbox,
connection health, usage/cost controls, evaluation results, and audit export.

## 6. Initial customer discovery and use-case selection

Before committing to a vertical pack, conduct structured discovery with
prospective buyers and users. Ask for recent examples of work, systems involved,
frequency, time spent, failure cost, approval requirements, and what makes the
work safe to delegate. Request sample inputs and desired outputs where
possible.

Score candidate workflows from 1 to 5 on:

| Criterion | What to assess |
|---|---|
| Frequency | How often does the task occur? |
| Pain / value | Time saved, revenue recovered, risk reduced, or service quality improved |
| Context availability | Are needed facts available through connectable systems? |
| Repeatability | Can success and failure be described and evaluated? |
| Boundedness | Can the task start with clear limits and a safe fallback? |
| Integration reuse | Will connectors or skills also serve other use cases? |
| Buyer ownership | Is there a team willing to sponsor and measure a pilot? |

Avoid selecting a workflow solely because its demo looks impressive. Prefer a
task with a named owner, accessible data, measurable baseline, and permission
to run a real pilot.

### Initial pilot portfolio hypothesis

Use three workflow archetypes to validate the platform across different kinds
of work:

1. **Knowledge answer:** retrieve and cite authorized information from a small
   set of connected sources.
2. **Triage and preparation:** summarize an incoming request or event, gather
   context, classify it, and prepare a recommended response or record.
3. **Approved action:** execute one bounded write only after the right person
   approves it.

The specific department use cases should come from discovery. This portfolio
tests shared context, asynchronous execution, structured outputs, and human
approval without defining Weaves as a single-department product.

## 7. Minimum viable product

### Customer-visible outcome

A pilot organization can connect a few systems, publish a useful agent or
workflow, let an authorized employee run it, inspect its sources and actions,
and improve it from observed results.

### In scope

- Organization creation, one default workspace, invited users, and basic roles.
- Two authentication options for integrations: delegated OAuth where needed
  and a controlled service identity where appropriate.
- A small set of integrations selected by design partners; begin with three,
  prioritizing reuse across chosen workflows.
- Model provider profiles with at least one managed default and one customer
  provider option if early customers require it.
- Agent create, test, publish, disable, and version lifecycle.
- Reusable skills/capabilities with schemas, permissions, risk, timeouts, and
  idempotency behavior.
- Code-backed workflow handlers with typed configuration, manual and event
  triggers, retries, cancellation, and durable run state.
- Web run surface plus one collaboration integration.
- Context retrieval with citations, source ACL enforcement, and short-lived
  conversation continuity.
- Read and draft actions; one approved write path only after a pilot validates
  its safety model.
- Run timeline, tool-call record, source list, approval decision, output
  artifact, usage/cost, and error reason.
- A simple evaluation harness for representative tasks and regression cases.

### Out of scope for MVP

- A general visual workflow programming environment.
- Unbounded autonomous write access.
- A marketplace or external third-party agent ecosystem.
- Long-term cross-workspace memory by default.
- Every connector and every model provider.
- Customer-hosted deployment and complex data residency controls.
- Multi-agent swarms and agent-to-agent delegation as a default behavior.
- A universal organization knowledge graph before retrieval use cases require
  it.

## 8. Delivery roadmap and stage gates

The ranges below are planning estimates only. Re-estimate once team size,
design partners, and connector access are known.

### Stage 0 — Product validation (2–4 weeks)

**Work:** interview 10–15 prospective organizations across at least three
functions; map current workflows; identify data owners, access patterns, risk,
and value measures; select 2–3 design partners and 3 candidate workflows.

**Exit gate:** named buyer and pilot owner; workflow baseline and success metric;
systems and credentials available; customer approval to run a bounded pilot.

### Stage 1 — Product contracts and tenant boundary (2–4 weeks)

Implement the planned P1A organization, workspace, principal, role, and
permission contracts. Add only the agent, model, connection, capability,
workflow, run, artifact, approval, and audit contracts required by the selected
pilot. Keep the broader contract list as a target model, not a prerequisite to
the first end-to-end product workflow. Keep contract code independent of
runtime and infrastructure packages.

**Exit gate:** schemas are versioned; workspace and organization scopes are
explicit; forbidden cross-scope references are rejected at service boundaries;
contract package remains independent of legacy incident runtime.

### Stage 2 — One secure end-to-end workflow pilot (4–8 weeks)

Implement one customer-selected workflow all the way from request to artifact. Include
identity resolution, one model profile, two or three required connections,
context construction, one bounded agent/tool loop, durable run records, and a
user-visible result. Use mock model/tool implementations for fast development
and provider-backed integration in a controlled pilot environment.

**Exit gate:** a pilot user can complete the task repeatedly; source access is
enforced; runs can be inspected and replayed where safe; cost and latency are
measured; no unapproved write can execute.

### Stage 3 — Admin control plane (4–8 weeks)

Add organization onboarding, users/roles, integration setup and health,
model profiles, agent/skill configuration, test and publish flow, basic
workflow configuration, approval policy, and audit search. Start with APIs and
a simple dashboard rather than a comprehensive no-code studio.

**Exit gate:** an organization admin can operate the pilot without direct
database or YAML edits; changes to executable definitions create a new version.

### Stage 4 — Pilot portfolio and reliability (6–12 weeks)

Add additional workflows selected from pilots, reuse existing skills and
connectors, add scheduled/event triggers as required, strengthen evaluations,
and add one approved write action. Build usage budgets, cancellation, retry
controls, connector health, retention/deletion, and export needed by pilot
customers.

**Exit gate:** at least two workflows in different business areas use shared
platform primitives; customers return weekly; task outcome and cost targets
are met; support load is understood.

### Stage 5 — Commercial SaaS readiness

Harden tenant isolation, billing and usage metering, SSO/SCIM where demanded,
data processing and retention controls, incident response, backups, security
review, service-level objectives, and customer-facing admin documentation.
Offer customer-hosted deployment only after repeat demand and operating
economics justify it.

**Exit gate:** repeatable onboarding, clear unit economics, support ownership,
security evidence, and a stable release process.

## 9. Architecture and implementation guidance

The planned platform primitives map to a product runtime of:

```text
Surface and trigger
  -> identity and workspace resolution
  -> workflow runtime
  -> context builder
  -> bounded agent runtime
  -> capability/plugin gateway
  -> policy and approval checks
  -> artifact, run-event, and audit stores
  -> delivery and notification
```

Key design guidance:

- Keep tenant and workspace identity on every executable object and durable
  event. Enforce it at repository/service boundaries and in data access.
- Keep connector credentials in a secret store, referenced by opaque IDs.
- Separate user-delegated tool execution from shared service identities.
- Keep agent definitions declarative and versioned; execute registered,
  code-backed workflow handlers initially.
- Treat external content as untrusted input. Tool outputs and retrieved
  documents must not change authorization or expand allowed capabilities.
- Persist run events as durable facts: selected versions, context references,
  model, tool calls, approvals, output, error, usage, and timestamps.
- Make model and runtime providers replaceable through narrow interfaces.
- Keep APIs and connector contracts independent of the UI.
- Defer a central knowledge graph. Start with connector search, access-aware
  retrieval, provenance, and citations; add entity graphing only where it
  solves a measured cross-source problem.
- Offer standard templates and skills as product content, with organization
  overrides and explicit versioning.

## 10. Security, trust, and operations requirements

Security and reliability are core product behavior because agents can act
across systems.

- Strict organization isolation for database records, caches, search indexes,
  object storage, queue messages, and secrets references.
- Authenticated identities from the surface/provider; never treat identity or
  role claims in natural-language content as authorization.
- Least-privilege connector scopes and capability-level allowlists.
- Access-aware retrieval, source attribution, and citation links.
- Approval records bound to the exact action, inputs, agent version, and run.
- Idempotency for retried tool calls; explicit timeout, retry, and cancellation
  semantics.
- Redaction of secrets and sensitive payloads from logs and model traces.
- Configurable retention, deletion, and audit export.
- Egress controls for plugin/runtime traffic; isolated execution if arbitrary
  customer code is ever introduced.
- Evaluation coverage for prompt injection, cross-tenant access, unauthorized
  tools, malformed model outputs, and workflow failure/recovery.
- Clear customer-facing explanation of what data is sent to models, which
  model is selected, and which retention rules apply.

## 11. Measurement

### Product outcomes

- Time from organization signup to first successful, useful run.
- Percentage of invited pilot users who complete a workflow in a typical week.
- Workflow completion and human acceptance rates.
- Time saved or business outcome per workflow, measured against a baseline.
- Repeat usage by team and workflow; number of active workflows per customer.

### Quality and trust

- Correctness/task completion on a versioned evaluation set.
- Citation/source support for factual answers.
- Unauthorized retrieval or action incidents: target zero.
- Approval rate, rejection rate, and post-approval failure rate.
- Run failure, retry, cancellation, and escalation rates.

### Cost and service health

- Cost per successful task and per customer.
- End-to-end latency by workflow and model/provider.
- Connector error rate and rate-limit impact.
- Queue delay, run recovery, and availability against workflow SLOs.

Set numeric launch thresholds with design partners after baselines exist. Do
not select targets by intuition before observing real tasks.

## 12. Commercial model hypothesis

Test a managed SaaS subscription with a platform fee and included usage, plus
transparent usage-based overage or higher tiers. Meter successful runs, model
usage, and premium connector/runtime costs separately during pilots. Price
should align to customer value and predictable operating cost; avoid pricing
solely by seats if agents are expected to perform background work.

Validate willingness to pay with design partners before committing to public
pricing. Enterprise plans may later add SSO/SCIM, retention controls, audit
export, dedicated environments, data residency, or customer-hosted operation
when customer demand supports them.

## 13. Key risks and mitigations

| Risk | Mitigation |
|---|---|
| Horizontal scope becomes too broad | Keep the platform horizontal; choose a small pilot portfolio with named owners and measurable outcomes. |
| Connector count becomes the roadmap | Build a capability contract and prioritize integrations that serve multiple pilots; use MCP/API adapters selectively. |
| Permissions leak through retrieval or service identities | Make identity mode explicit; enforce source ACLs; test adversarial cross-user and cross-tenant cases. |
| Customers create agents that do not work reliably | Provide test runs, versioned evaluations, templates, run inspection, and safe defaults. |
| LLM/model volatility hurts quality or margin | Use a provider-neutral gateway and task-specific evaluation before model routing. |
| Customization demands turn into bespoke consulting | Keep extension points declarative; measure support effort per workflow; productize recurring patterns. |
| A no-code builder consumes effort before workflow value is proven | Use forms, reusable skills, and registered handlers first; expand visual authoring based on observed needs. |
| Memory retains data unexpectedly | Begin with scoped thread context and explicit retention; add durable memory only with user controls and deletion behavior. |
| Customer-hosted mode slows managed launch | Preserve interfaces and deployment boundaries without building customer-hosted packaging in the MVP. |

## 14. Decisions to resolve during discovery

1. Initial customer segment and buyer: central IT/platform, operations, or a
   specific business function?
2. Which two or three workflows best prove reuse across departments?
3. Which collaboration surface is essential for the first pilots?
4. Which initial systems are common to the chosen pilots, and which need
   delegated user identity?
5. Should Weaves provide managed model access, support customer keys, or both
   in the first paid version?
6. What level of customization should business users get versus developers?
7. What run data and model traces may Weaves retain by default?
8. What buying requirement would justify customer-hosted deployment?
9. What is the product name and canonical spelling: Weaves or Weave? Current
   repository naming is inconsistent.

## 15. Immediate next actions

1. Agree that the product target is a horizontal, managed-first SaaS agent
   platform for organization-specific work.
2. Complete 10–15 discovery interviews and document candidate workflows using
   the scorecard above.
3. Recruit 2–3 design partners and select a pilot portfolio with read, triage,
   and approved-action behavior.
4. Update the product contract plan to cover skills/capabilities, workflow
   triggers, approval and execution policy, context provenance/access scope,
   and evaluation metadata.
5. Implement P1A identity contracts, then build one narrow end-to-end workflow
   before expanding control-plane breadth.
6. Review pilot evidence at each stage gate and revise ICP, use cases, and
   roadmap before adding more connectors or visual authoring.

## Research sources

- [Razorpay Agent Studio launch](https://razorpay.com/blog/agent-studio-ai-agents-by-razorpay/) — examples of business-specific workflow agents and no-code customization.
- [Razorpay on Slash](https://razorpay.com/blog/?p=26885) — engineering agents, reviewers, triggers, skills, integrations, and company knowledge search.
- [Microsoft Copilot Studio documentation](https://learn.microsoft.com/en-us/microsoft-copilot-studio/) — agent building, tools, knowledge, workflows, evaluation, publication, analytics, and governance.
- [Microsoft connector documentation](https://learn.microsoft.com/en-us/microsoft-copilot-studio/copilot-connectors-in-copilot-studio) — prebuilt and custom connectors for enterprise knowledge and actions.
- [Workato Agent Studio documentation](https://docs.workato.com/en/agentic/agent-studio) — reusable skills, knowledge, integrations, user surfaces, and approvals.
- [Workato identity guidance](https://docs.workato.com/en/agentic/agent-studio/genie-governance/establish-user-identity) — trusted identity for actions and audit.
- [AWS Bedrock AgentCore guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html) — modular managed agent infrastructure and operational components.
