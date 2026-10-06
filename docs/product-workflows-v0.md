# Workflow execution v0

Every active agent version publishes an immutable `agent.execute` workflow
version. A workflow manager can create an ordered workflow from one to ten
current agent versions, rename it, describe it, archive it, or reactivate it. The API
can list and inspect workflow definitions and published versions:

```http
GET /api/v0/workflows
GET /api/v0/workflows/{workflow_id}
GET /api/v0/workflows/{workflow_id}/versions
GET /api/v0/workflows/{workflow_id}/versions/{workflow_version_id}
GET /api/v0/workflows/{workflow_id}/runs
```

Version history is returned newest first in pages of 50 by default (maximum
100). Follow `next_before_version` with the `before_version` query parameter to
fetch older versions. Historical detail is scoped to its workflow and retains
the exact ordered agent-version IDs, step conditions, dependencies, and parallel
groups used by a run.

Create from one agent with `agent_id` or from an ordered sequence with
`agent_ids`:

```http
POST /api/v0/workflows
Content-Type: application/json
{"name": "Release risk review", "agent_ids": ["planner-id", "reviewer-id"]}
```

Update its metadata or status with `PATCH /api/v0/workflows/{workflow_id}`.
Replace its ordered agent sequence with `PUT
/api/v0/workflows/{workflow_id}/steps` and a body such as
`{"agent_ids": ["planner-id", "reviewer-id"]}`. Step replacement publishes a
new immutable workflow version. Newly attached agents receive an immutable
version with explicit access to the workflow, and other workflows referencing
those agents are advanced to the new agent version in the same database unit of
work. Existing run records and queued workflow jobs retain the workflow version
they accepted, even if the workflow is edited before the worker starts.
A bounded group of adjacent steps can be configured to run concurrently:

```json
{
  "agent_ids": ["intake-id", "review-id", "risk-id", "summary-id"],
  "parallel_groups": [{"agent_ids": ["review-id", "risk-id"]}],
  "step_dependencies": [
    {"target_agent_id": "review-id", "depends_on_agent_ids": ["intake-id"]},
    {"target_agent_id": "risk-id", "depends_on_agent_ids": ["intake-id"]},
    {
      "target_agent_id": "summary-id",
      "depends_on_agent_ids": ["review-id", "risk-id"],
      "join_policy": "all"
    }
  ]
}
```

Parallel groups contain two to five adjacent agents after the first workflow
step. Group members cannot depend on each other's output. In graph mode, each
step receives artifacts from its declared dependencies; in sequence mode it
receives artifacts from all earlier successful steps. Up to five groups may be
published in one version.
Run it with:

```http
POST /api/v0/workflows/{workflow_id}/runs
Content-Type: application/json
Idempotency-Key: optional-client-key
{"task": "Summarize the latest release risks"}
```

Workflow creation requires `workflows.manage`. Its body can also include an
optional `description`. The new workflow starts active and pins the selected
agents' immutable versions in the supplied order. Updating an agent publishes a
new agent version and advances every linked workflow while preserving other
steps, in one database unit of work. Workflow metadata or status changes do not
rewrite its immutable version.

The synchronous response includes one workflow run, ordered `agent_runs`, tool
invocations, one artifact per step, the final agent run and artifact, an audit
event, and replay state. The run is bound to the exact workflow version.
Archived workflows, unsupported handlers, stale agent-version bindings, and
missing declared capabilities are rejected before execution. Each step receives
the original task and prior step artifacts as untrusted reference data. A
conversation thread can be supplied when it is bound to the first agent.

List runs for one workflow with `GET /api/v0/workflows/{workflow_id}/runs`.
The endpoint returns up to 50 runs by default (maximum 100), newest first, with
their agent runs, tool invocations, and artifacts. Its `items` and `next_cursor`
fields provide keyset pagination; pass the cursor back as `cursor` to fetch the
next page. It is scoped to the current organization and workspace and requires
`workflows.run`.

The caller needs both `workflows.run` and `agents.run`, because this v0 handler
dispatches an agent. Idempotency keys follow the run API's per-principal scope.
The durable execution-job API also accepts a workflow ID and dispatches it
through the PostgreSQL-backed worker. Queueing is unavailable in memory-only
mode.

The v0 runtime supports up to ten ordered agents using the fixed
`agent.execute` and `agent.sequence` handlers. A step after the first may have
one condition against an earlier agent's structured output. Conditions use a
JSON Pointer and `exists`, `equals`, or `not_equals`; a nonmatching condition
skips that step and records an audit event. Multiple mutually exclusive steps
can use conditions on the same router output, with later unconditional steps
joining the selected path. The source agent must declare an output schema so
its result is validated JSON. Conditions are published with the immutable
workflow version and survive later agent version updates.

To declare a dependency graph, add a `step_dependencies` entry for each step
that depends on earlier work. The first agent is always a root; any later step
without an entry is an additional root and receives no upstream artifacts.
Dependency sources must appear earlier in `agent_ids`, which makes that list a
topological order and rejects cycles. A target runs when all declared
dependencies succeeded (`join_policy: "all"`) or at least one succeeded
(`"any"`). Unsatisfied steps are skipped and audited. A condition source must
also be a declared dependency. Graph-mode steps receive only the artifacts of
successful declared dependencies, so unrelated branches do not flow into the
step context.

For example, after creating a workflow, publish a review-only step:

```http
PUT /api/v0/workflows/{workflow_id}/steps
Content-Type: application/json
{"agent_ids":["router-id","reviewer-id","escalation-id","summary-id"],"step_conditions":[{"source_agent_id":"router-id","target_agent_id":"reviewer-id","json_pointer":"/route","operator":"equals","expected_value":"review"},{"source_agent_id":"router-id","target_agent_id":"escalation-id","json_pointer":"/route","operator":"equals","expected_value":"escalate"}],"step_dependencies":[{"target_agent_id":"reviewer-id","depends_on_agent_ids":["router-id"]},{"target_agent_id":"escalation-id","depends_on_agent_ids":["router-id"]},{"target_agent_id":"summary-id","depends_on_agent_ids":["reviewer-id","escalation-id"],"join_policy":"any"}]}
```

These conditions select one route, and the `any` join policy lets a later
summary step rejoin the selected route. Bounded parallel groups run independent
ready steps concurrently and return results in workflow order. Multiple roots
can collect independent context before a downstream join. The v0 executor uses
a fixed topological step list and does not support cycles or loops,
user-authored handlers, custom input/output mappings, automatic workflow
retries, or production-grade tenant isolation.

The built-in `engineering-assistant` agent template is available through the
product API. Template creation requires the caller to select installed
capability IDs; the template recommends workspace knowledge, GitHub, Slack,
and Jira search, but does not grant connector access on its own.

## Webhook event triggers

An organization workflow administrator can create a webhook trigger for an
active published workflow with
`POST /api/v0/workflows/{workflow_id}/triggers`. Creation returns the trigger
secret once; the record stores only its SHA-256 digest. List triggers with
`GET /api/v0/workflow-triggers`, disable or re-enable one with
`PATCH /api/v0/workflow-triggers/{trigger_id}`, and rotate its secret with
`PUT /api/v0/workflow-triggers/{trigger_id}/secret`. Trigger metadata never
includes the secret digest in API responses.

Send a JSON object to the returned webhook URL with `X-Workflow-Trigger-Secret`
and a stable `X-Event-ID` header. The endpoint validates the secret, bounds the
body to 8 KiB, rejects credential-shaped payload fields, and queues a workflow
execution job. Replaying the same event ID and payload returns the original
job; reusing the ID with a different payload returns `409`. The job records
the trigger and event IDs, and its task labels the event JSON as untrusted
input. The workflow runs under the trigger creator's current permissions, so
revoked access prevents subsequent events from being queued. Delivery
acceptance is serialized with disablement and secret rotation across API
instances: an event accepted first can remain queued, while later events are
rejected after the administrative change completes.

Triggers require PostgreSQL because they dispatch into the separate durable
worker queue. Deployments must expose the endpoint over HTTPS and should apply
ingress rate limits. Provider-specific signature validation, delivery retry
policies, and production ingress controls remain future work.

## Recurring interval schedules

A workflow administrator can create a recurring schedule for an active,
published workflow with
`POST /api/v0/workflows/{workflow_id}/schedules`. The schedule includes a name,
task instructions, and an interval from 60 seconds to one year. Its first
occurrence is due after one full interval. List schedules with
`GET /api/v0/workflow-schedules`; pause or resume one with
`PATCH /api/v0/workflow-schedules/{schedule_id}` and a `status` of `disabled`
or `active`.

The PostgreSQL-backed worker checks for due schedules every five seconds by
default (`WEAVES_SCHEDULE_POLL_SECONDS` configures a 0.5–60 second interval).
Each occurrence queues a normal durable workflow execution job with schedule
and occurrence metadata. Multiple worker processes serialize dispatch for a
schedule, and the job uses an occurrence-derived idempotency key. If the worker
was offline across several intervals, it queues one occurrence and advances to
one interval after dispatch time instead of creating a catch-up burst. The
schedule creator's current workflow and agent permissions are checked when a
job is queued. If access or workflow configuration is no longer valid, the
schedule enters `error`; an administrator can resume it, which starts a fresh
interval.

Schedules require PostgreSQL and the separate product worker. They currently
support fixed intervals only: calendar and timezone-aware cron rules, per-run
misfire policies, and schedule-level retry policies remain future work.
