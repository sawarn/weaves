# Platform Phase 0: Product Architecture Reset

## Status

The product direction and first platform foundation are implemented through
P5. P1 contracts, the P2 local runtime, P3 model gateway, P4 plugin gateway,
and P5 local product API are available for v0 evaluation. The current API is
uses a demo organization and local development identity. P6 dashboard is
implemented. The product runtime now supports PostgreSQL persistence in Compose
as well as its in-memory mode. Authentication, request-derived tenant scope,
and real connector rollout remain future work.

## Product Direction

Weave is an enterprise agent platform.

An organization connects its internal tools and data sources. Users in that
organization create configurable agents with personas, instructions, model
profiles, permissions, and allowed tools. Those agents use approved
organization context to solve user problems across dashboard, chat, API, and
workflow surfaces.

The incident-analysis implementation in this repository is no longer the
product center. It is reference material only. We may reuse contract patterns,
tool dispatch ideas, observability clients, Slack/GitHub integration code, and
verification discipline, but new product architecture must not be shaped around
incidents.

## Phase 0 Outcome

Phase 0 should leave the repository with a clear product and system blueprint:

- product thesis
- target user flows
- platform primitives
- runtime architecture
- package boundaries
- first small implementation slice
- explicit non-goals

Phase 0 is complete when the next implementation phase can begin without
arguing about whether the system is incident-first or platform-first.

## Core Product Promise

Weave lets an enterprise answer this question:

> Which AI agents should be allowed to use which company context, through which
> tools, under which policy, with which model, and with what audit trail?

The product must make this configurable by organization administrators without
requiring every customer to maintain custom infrastructure or bespoke
integration code.

## Deployment And Ownership Strategy

Weaves should be designed as one core platform that can support multiple
deployment modes later.

The launch path should be managed-first: we operate the application, runtime,
upgrades, monitoring, secrets infrastructure, and default model gateway for
customers who do not want to maintain their own systems. This is the fastest
path to onboarding and a better fit for companies without dedicated platform or
DevOps teams.

The architecture must still keep customer-hosted deployment possible for future
enterprise customers with strict security, data residency, compliance, or
internal AI-platform requirements. In that mode, the customer can host Weaves in
their own environment, connect their own model providers, use their own secrets
backend, and operate the runtime themselves under a license/support model.

This is a product architecture decision, not a packaging phase. Phase 0 records
the constraint; implementation and pricing come later.

### Managed Weaves

In managed mode, we operate the product for the customer.

Responsibilities owned by us:

- application hosting
- runtime operations
- upgrades
- monitoring and alerting
- default secrets infrastructure
- default storage infrastructure
- model gateway defaults
- product support

Responsibilities owned by the customer:

- approving tool connections
- supplying or approving credentials
- configuring agents, roles, and policies
- choosing whether to use our model defaults or their own providers

This mode should support subscription pricing later.

### Customer-Hosted Weaves

In customer-hosted mode, the customer operates the product in their own
environment.

Responsibilities owned by us:

- software license
- release artifacts
- documentation
- support contract
- upgrade guidance

Responsibilities owned by the customer:

- infrastructure
- deployment
- operations
- storage
- secrets backend
- network controls
- model provider credentials
- internal tool connectivity

This mode should support enterprise license and support pricing later.

### Architecture Rule

The core product must not assume that Weaves owns every dependency.

The following should remain configurable behind interfaces:

- model providers
- secrets backend
- storage backend
- plugin credentials
- audit export
- runtime environment metadata
- outbound network policy

Weaves is the enterprise AI control layer. It may provide default model access
in managed mode, but the product should not depend on us being the AI model
provider.

## Primary Users

### Organization Admin

Configures the organization, users, workspaces, model providers, plugin
installations, policies, and default controls.

### Workspace Admin

Manages agents, workflows, plugin access, and approvals for a team or business
unit.

### Agent Creator

Creates or edits agents by defining persona, instructions, model profile,
allowed tools, memory scope, and output expectations.

### Agent User

Runs agents from the dashboard, Slack, API, or configured workflows.

### Auditor Or Security Reviewer

Reviews who accessed what, which tool calls ran, which model was used, what was
approved, and what artifacts were produced.

## Target Product Flows

### 1. Organization Onboarding

1. Create organization.
2. Create default workspace.
3. Invite users or connect identity provider.
4. Assign initial roles.
5. Configure at least one model provider and model profile.
6. Install first plugin.
7. Create or publish first agent.
8. Run the agent from dashboard or chat.

### 2. Plugin Installation

1. Admin selects plugin type, such as GitHub, Slack, Jira, Google Drive,
   Datadog, Grafana, database, or MCP.
2. Weave validates required configuration.
3. Credentials are stored behind an opaque secret reference.
4. Plugin exposes capabilities with input/output schemas and risk metadata.
5. Admin enables capabilities for a workspace.
6. Agents can use only explicitly allowed capabilities.

### 3. Agent Creation

1. User chooses name, description, and persona.
2. User writes instructions.
3. User selects a model profile.
4. User selects allowed plugin capabilities and context scope.
5. User chooses approval and budget policies.
6. Weave saves a draft agent definition.
7. Publishing creates an immutable agent version.
8. Runs always reference the exact version used.

### 4. Agent Run

1. User asks a question or triggers a workflow.
2. Surface resolves organization, workspace, principal, and selected agent.
3. Runtime checks permission.
4. Context builder retrieves approved context from plugins.
5. Agent runtime calls the configured model.
6. Tool calls go through the plugin gateway.
7. Risky actions request approval before execution.
8. Runtime stores artifacts, usage, tool invocations, and audit events.
9. Result is returned to the original surface.

## Platform Primitives

Phase 0 defines these as the foundation for the product:

- `Organization`: customer account boundary.
- `Workspace`: internal boundary for teams, data access, agents, workflows, and
  plugin installations.
- `User`: human account.
- `Principal`: actor used for auth and audit; can be user, service account,
  system, or external app.
- `Role` and `Permission`: product authorization language.
- `ModelProvider`: configured model backend with credentials hidden behind a
  secret reference.
- `ModelProfile`: selectable model configuration exposed to agent creators.
- `AgentDefinition`: stable agent identity and lifecycle.
- `AgentVersion`: immutable executable agent configuration.
- `PluginDescriptor`: connector type and capability manifest.
- `PluginInstallation`: configured connector instance for a workspace.
- `Capability`: one context, action, or delivery operation exposed by a plugin.
- `WorkflowDefinition`: repeatable business process using agents and plugins.
- `WorkflowRun`: durable execution unit.
- `AgentRun`: one invocation of one agent version.
- `ToolInvocation`: durable record of one capability call.
- `Artifact`: durable output or context snapshot.
- `ApprovalRequest`: policy gate for sensitive or write actions.
- `AuditEvent`: append-only product fact.

## Target Runtime Architecture

```text
Surface
  -> Request Router
  -> Authorization And Policy
  -> Workflow Runtime
  -> Agent Runtime
  -> Context Builder
  -> Plugin Gateway
  -> Model Gateway
  -> Artifact Store
  -> Delivery Router
  -> Audit Logger
```

### Surface

Dashboard, Slack, API, webhooks, and scheduled triggers normalize user input
into platform requests. They do not contain agent or workflow business logic.

### Request Router

Resolves the requested agent or workflow. Early versions should prefer explicit
selection and configured defaults over broad natural-language routing.

### Authorization And Policy

Answers whether the principal may run the agent, whether the agent may use the
capability, whether the model is allowed, whether budget remains, and whether
an action needs approval.

### Workflow Runtime

Owns durable workflow state, retries, cancellation, artifacts, approvals, and
delivery. Workflows are product-level orchestration, not hard-coded incident
jobs.

### Agent Runtime

Executes an immutable agent version using its persona, instructions, model
profile, allowed capabilities, context policy, and output contract.

### Context Builder

Fetches, filters, summarizes, cites, and snapshots organization context from
approved plugin capabilities.

### Plugin Gateway

The only path from agents to external systems. It validates schemas, enforces
policy, applies rate limits, handles secrets, records tool invocations, and
normalizes results.

### Model Gateway

The only path from agents to model providers. It resolves model profiles,
applies provider credentials, enforces model policy and budgets, records usage,
and supports fallback.

### Artifact Store

Stores run outputs, context snapshots, structured results, summaries, and
references to large encrypted payloads.

### Delivery Router

Sends results back to dashboard, Slack, API callbacks, or future surfaces.

### Audit Logger

Records append-only events for configuration changes, runs, tool calls,
approvals, model usage, and external actions.

## Clean Package Direction

The target codebase should be organized around platform boundaries:

```text
src/weave/product/
  contracts/
  services/
  repositories/

src/weave/identity/
src/weave/policy/
src/weave/models/
src/weave/agents/
src/weave/plugins/
src/weave/workflows/
src/weave/runs/
src/weave/artifacts/
src/weave/audit/

src/weave/surfaces/
  api/
  dashboard/
  slack/
  webhooks/
```

Current incident-specific modules can remain until replaced, but new platform
work should not import from them. Any reused logic must move through explicit
adapters or new platform modules.

## First MVP Definition

The first usable product should prove this loop:

1. Create one organization and default workspace.
2. Register one model provider and model profile.
3. Install one plugin, initially mock or local.
4. Create one custom agent.
5. Run the agent from an API or minimal dashboard.
6. Build context through the plugin gateway.
7. Produce an artifact.
8. Record audit events and usage.

This MVP does not need billing, customer-hosted packaging, SSO, a visual
workflow builder, marketplace plugins, long-term memory, or autonomous writes.

## Small Implementation Phases

### P1A: Identity Contracts

Add strict contracts for organization, workspace, user, principal, role,
permission, and role binding.

### P1B: Agent And Model Contracts

Add model provider, model profile, agent definition, and immutable agent version
contracts.

### P1C: Plugin And Capability Contracts

Add plugin descriptor, plugin installation, capability, and credential-reference
contracts.

### P1D: Run, Artifact, Approval, And Audit Contracts

Add durable execution facts without adding runtime behavior.

### P2: Local Platform Runtime

Status: implemented in `backend/weaves/product/runtime` as a deterministic,
in-memory local runtime. It bootstraps scoped example configuration and
executes one mock agent path through identity and role authorization, context
retrieval, a typed tool invocation, an artifact, and an audit event. Contract
and architecture tests cover this path. Persistent repositories and API
integration are separate follow-on work.

The implementation covers the org, workspace, principal, role, model profile,
mock plugin installation, agent/version, workflow/version, run, artifact, and
audit event records.

### P3: Model Gateway

Status: implemented in `backend/weaves/product/runtime/model_gateway.py` with
provider-neutral request/response contracts, a deterministic mock adapter, and
an OpenAI-compatible HTTP adapter. The local runtime routes calls through this
gateway and records resolved provider/model and token usage. Adapter tests use
an in-process HTTP transport; they do not call a real provider.

The model profile binding selects an active provider and allowlisted model
before dispatching to its registered adapter.

### P4: Plugin Gateway

Status: implemented in `backend/weaves/product/runtime/plugin_gateway.py`.
The local runtime dispatches the mock `knowledge.search` capability through
the gateway. It checks agent and workspace scope, installation status and
capability grants, validates input and output schemas, bounds payload sizes,
and records success or failure as a tool invocation and run audit trail. Only
context-read capabilities are enabled in this v0; there is no real connector
adapter yet.

### P5: Product API

Status: implemented in `backend/weaves/product/api/app.py` under `/api/v0`.
Routes expose the local organization/workspace, model profiles, plugin
capabilities and installations, agent create/update/read, workflow listing,
synchronous run creation and inspection, artifacts, and audit events. The
development identity is fixed, and all records live in memory, so this is a
local evaluation API rather than a multi-user service.

### P6: First Dashboard

Status: implemented in `backend/weaves/product/api/static/`. The platform API
serves a responsive local dashboard at `/` with overview metrics, agent
creation and version updates, a run lab with prompt examples and execution
trace, run and workflow inspection, connection and model-profile views,
OpenAI model catalog discovery, and artifact/audit inspection. Discovered
models become selectable agent profiles. This is a local evaluation UI; it
does not add authentication or durable state.

### P7: First Real Workflow

Add one complete workflow that uses the platform primitives. The recommended
first workflow is an engineering assistant over GitHub, Slack, and Jira, because
it exercises multiple data sources without making incident analysis the center.

## Phase 0 Decisions

Approved:

- Workspaces are mandatory internally.
- The new platform uses `org_id`, `workspace_id`, `agent_id`,
  `plugin_installation_id`, and `run_id` as first-class terms.
- `User` and `Principal` are separate concepts.
- The incident-analysis implementation is reference material, not the
  architecture anchor.
- The product should launch managed-first while keeping the core architecture
  deployment-mode agnostic.
- Weaves is the AI control layer; model providers are configurable behind model
  profiles and the model gateway.

Open but not blocking P1A:

- Which real connector follows the mock plugin.
- Whether the first UI is dashboard-first or API-first.
- Which identity provider is supported first.
- Which model providers are enabled first.
- Default retention classes.
- Exact deployment packaging.
- Pricing.

## Non-Goals For Phase 0

- Deleting the current incident code.
- Refactoring runtime modules.
- Adding database migrations.
- Designing pricing or deployment tiers.
- Building the dashboard.
- Connecting real customer tools.
- Supporting autonomous production writes.
- Implementing SSO.
- Implementing long-term memory.

## Completion Criteria

Phase 0 is complete when:

- the README describes Weave as an enterprise agent platform
- the core product plan is platform-first
- phase 1 contract planning no longer depends on incident compatibility
- the first implementation slice is P1A only
- no runtime behavior has changed
