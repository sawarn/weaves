# Weaves Technical Plan: Development and POC

**Status:** POC proposal
**Research reviewed:** 2026-10-05
**Scope:** Local development and one customer-facing proof of concept

The editable HLD is [weaves-hld.excalidraw](weaves-hld.excalidraw).

## 1. POC goal

Prove one complete, use-case-neutral agent path:

1. A user supplies a task.
2. Weaves resolves the organization, workspace, and user.
3. The selected agent gets approved context and a small set of tools.
4. The model reasons within those limits and returns a useful result.
5. Weaves records the run, sources, tool calls, cost, and outcome.

Pick the first actual workflow with a design partner. Keep the components reusable
so a second workflow can use the same identity, model, connector, policy, and run
interfaces.

## 2. Recommended POC architecture

Use one Python application codebase with two local processes:

- **API/control plane:** FastAPI app for identity, agents, connectors, run requests,
  approvals, and run history.
- **Worker:** same codebase, launched separately; claims pending work from a
  PostgreSQL jobs table and executes bounded agent runs.

PostgreSQL is the source of truth for configuration, job/run state, approvals,
and audit records. For POC development, a worker can poll that table. This is
simple to run locally and persists jobs across API or worker restarts.

```text
Browser / API
     |
FastAPI: resolve user + org + workspace, authorize, create run
     |
PostgreSQL: agent config + run state + pending jobs + audit
     |
Worker: context -> model gateway -> tool gateway -> result
     |                  |                 |
Local files /       One real model     Mock connector or
one selected source  + mock adapter     one selected integration
```

Keep the component boundaries in code, but run the small POC as a modular
monolith plus worker. Do not split it into independently deployed services.

## 3. POC technology stack

| Area | Development / POC choice |
|---|---|
| Backend | Python 3.12+, FastAPI, Pydantic v2 |
| Data | PostgreSQL in Docker Compose; SQLAlchemy 2.x + Alembic |
| Background work | A PostgreSQL jobs table and a worker process polling for jobs |
| UI | Small Next.js + TypeScript workspace for submitting a task and viewing its run; use API/CLI only if that is faster for the first demo |
| Model | One real provider adapter plus a mock adapter for tests and offline development |
| Integrations | Mock connector first, then one real connector selected for the POC |
| Context | Local fixture files or one selected source; add pgvector only if the POC needs semantic retrieval |
| File storage | Local filesystem in development; add object storage only if a POC workflow needs uploaded files |
| Secrets | Local ignored `.env` for developer credentials; use test credentials and a vault before any external pilot |
| API output | JSON plus SSE or simple polling for run progress |
| Observability | Structured logs, request/run IDs, duration and cost fields; defer a full telemetry stack |
| Dev environment | Docker Compose for Postgres and optional supporting services; API and worker run locally |

Next.js App Router is a supported route for the small TypeScript UI. PostgreSQL
is sufficient for POC state; pgvector can add vector similarity search in the
same database if a chosen use case requires it. [Next.js App Router](https://nextjs.org/docs/app)
[pgvector](https://github.com/pgvector/pgvector)

## 4. Where SQS and Temporal fit

Neither is needed to develop or demonstrate the first POC.

- **SQS** is a hosted message queue. It would replace the local PostgreSQL job
  poller when Weaves needs independently scaled API and worker deployments,
  managed buffering, and dead-letter handling. SQS standard queues can redeliver
  jobs, so consumers must be idempotent. [AWS SQS](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/)
- **Temporal** is a durable workflow engine. Consider it if customer workflows
  need long waits, timers, branching, compensation, or recovery across many
  steps. It would own durable workflow progress; it is more than a queue.
  [Temporal](https://docs.temporal.io/temporal)

These are later deployment choices, not POC prerequisites. They are not a pair
that Weaves must adopt together. Revisit them only after workflow requirements
and operating needs are visible.

## 5. POC code boundaries

Keep these modules as logical boundaries inside the backend:

- `identity`: principal, organization/workspace resolution, roles.
- `agents`: agent definition, version, instructions, budgets, allowed tools.
- `models`: model profile and provider adapters behind one gateway interface.
- `connections`: connector configuration and credential references.
- `capabilities`: typed tool schemas, risk class, timeout, identity mode.
- `context`: retrieval, provenance, source references, access scope.
- `runs`: run state, job claiming, tool invocation records, output artifacts.
- `policy`: authorization checks and approval state.
- `audit`: append-only product events.
- `api` and `worker`: transport and process entry points.

Agent code calls model and tool interfaces; it does not import vendor SDKs or
connector clients directly. Workflow handlers are registered in code with
typed configuration. Do not accept customer-supplied executable code.

## 6. Minimal data model

Create only the records needed for the selected POC workflow:

- `Organization`, `Workspace`, `User`, `Principal`, basic `RoleBinding`.
- `Agent` and immutable `AgentVersion`.
- `ModelProfile` and `ConnectionInstallation` with opaque credential refs.
- `Capability` definitions and per-agent allowlists.
- `Workflow` if the POC is triggered as a repeatable process.
- `Run`, `RunStep`, `ToolInvocation`, `RunEvent`.
- `ApprovalRequest` if the POC includes a write action.
- `Artifact`, `AuditEvent`, and `Job`.

Every customer-owned record carries `org_id`; workspace-owned records also
carry `workspace_id`. Check scope in the application and repository methods.
Use PostgreSQL row-level security only as an additional safeguard; it is easy to
misconfigure and does not replace application authorization.
[PostgreSQL row security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)

## 7. POC execution flow

1. API validates the request and derives the principal from the authenticated
   session or a local development identity.
2. In one database transaction, API creates a `Run` and a pending `Job`.
3. Worker claims a job, pins the exact agent version, and enforces time,
   token, tool-call, and cost limits.
4. Context retrieval returns only allowed sources with provenance.
5. The model gateway calls the configured provider. The tool gateway validates
   capability, schema, identity, and approval before dispatch.
6. Worker persists tool calls, run events, usage, and the final artifact.
7. UI streams or polls run status and displays result, sources, and actions.

For local work, a development principal is convenient. Any POC exposed to a
customer must use a real authenticated identity; do not expose a bypass or
shared dev token.

## 8. Development and POC milestones

### D0 — Local skeleton

- Create backend package boundaries and Docker Compose for PostgreSQL.
- Add health endpoint, migrations, request IDs, and a local development
  principal.
- Exit: API, database, and worker start with one documented command.

### D1 — Mocked run

- Add minimal agent/version records, run/job records, mock model, and mock tool.
- Worker claims and completes a job; UI or API can inspect the run.
- Exit: restart API and worker during a queued job; run state remains visible.

### D2 — Real model and context

- Add one provider adapter, budget/time limits, one context source, provenance,
  and output validation.
- Keep a mock provider available for repeatable local development.
- Exit: one chosen task completes with source references, usage, and a saved
  result.

### D3 — One real integration

- Add one selected system through the tool gateway, using a test connection.
- Add a read/draft workflow first. Add a single approved write only if the
  customer POC needs it.
- Exit: connector permissions and run history are inspectable end to end.

### D4 — POC review

- Demonstrate the workflow to the design partner.
- Record task completion, user acceptance, latency, cost per successful run,
  connector friction, and failures.
- Decide whether to add another workflow, connector, or stronger orchestration.

## 9. POC acceptance criteria

- One selected workflow completes from request to visible artifact.
- Organization and workspace scope is carried through every run and tool call.
- Agent only sees the configured context and capabilities.
- Every run shows its agent version, model, sources, tool calls, cost, and result.
- Duplicate job delivery cannot repeat a side effect.
- A failed provider/connector call produces a visible failed or retrying run.
- No write capability executes without its configured approval.
- A second mocked workflow can reuse the same agent, model, tool, and run
  contracts without restructuring the backend.

## 10. Defer until after the POC

- SQS, Temporal, Kubernetes, and microservice deployment.
- Multi-region, customer-hosted packaging, advanced data residency, and
  enterprise SSO/SCIM.
- Broad connector catalogs, marketplace, visual workflow graph editor,
  agent-to-agent delegation, and long-term memory.
- Dedicated vector database or knowledge graph.
- Full production telemetry stack and complex model routing.
- Production billing, SLO commitments, and large-scale load tuning.

The next architecture review should use the POC evidence to decide which
production concerns have become real. Keep interfaces around queue, secret
storage, model providers, and object storage so replacing local implementations
does not change product contracts.

## References

- [FastAPI deployment concepts](https://fastapi.tiangolo.com/deployment/concepts/)
- [Next.js App Router](https://nextjs.org/docs/app)
- [Amazon SQS developer guide](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/)
- [PostgreSQL row security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
- [pgvector](https://github.com/pgvector/pgvector)
- [Temporal documentation](https://docs.temporal.io/temporal)
