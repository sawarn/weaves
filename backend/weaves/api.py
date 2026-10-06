from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from weaves.db import IS_POSTGRES, as_id, connect, initialize_database, statement


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="Weaves POC", version="0.1.0", lifespan=lifespan)
STATIC_DIR = Path(__file__).with_name("static")
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


class RunRequest(BaseModel):
    agent_id: str = "company-knowledge-assistant"
    task: str = Field(min_length=3, max_length=4000)


class AgentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(default="", max_length=240)
    instructions: str = Field(
        default="Answer the user using the connected company handbook. Be clear, concise, and cite source files.",
        min_length=10,
        max_length=4000,
    )


class AgentPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=80)
    description: Optional[str] = Field(default=None, max_length=240)
    instructions: Optional[str] = Field(default=None, min_length=10, max_length=4000)


@app.get("/health")
def health() -> dict[str, str]:
    with connect() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def ui() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/agents")
def list_agents() -> list[dict]:
    with connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT id, org_id, workspace_id, name, description, instructions, created_at FROM agents ORDER BY name"
            ).fetchall()
        ]


@app.post("/agents", status_code=201)
def create_agent(request: AgentCreate) -> dict:
    agent_id = str(uuid4())
    with connect() as conn:
        conn.execute(
            statement("""INSERT INTO agents
               (id, org_id, workspace_id, name, description, instructions)
               VALUES (%s, 'demo-org', 'demo-workspace', %s, %s, %s)"""),
            (agent_id, request.name, request.description, request.instructions),
        )
        agent = conn.execute(
            statement(
                "SELECT id, org_id, workspace_id, name, description, instructions, created_at FROM agents WHERE id = %s"
            ),
            (agent_id,),
        ).fetchone()
    return dict(agent)


@app.patch("/agents/{agent_id}")
def update_agent(agent_id: str, patch: AgentPatch) -> dict:
    updates = patch.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No changes supplied")
    with connect() as conn:
        existing = conn.execute(
            statement("SELECT id FROM agents WHERE id = %s"), (agent_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Agent not found")
        assignments = ", ".join(f"{field} = %s" for field in updates)
        conn.execute(
            statement(f"UPDATE agents SET {assignments} WHERE id = %s"),
            (*updates.values(), agent_id),
        )
        agent = conn.execute(
            statement(
                "SELECT id, org_id, workspace_id, name, description, instructions, created_at FROM agents WHERE id = %s"
            ),
            (agent_id,),
        ).fetchone()
    return dict(agent)


@app.get("/runs")
def list_runs(limit: int = 50) -> list[dict]:
    bounded_limit = max(1, min(limit, 100))
    with connect() as conn:
        runs = conn.execute(
            statement("""SELECT r.id, r.org_id, r.workspace_id, r.agent_id, a.name AS agent_name,
                       r.task, r.status, r.result, r.error, r.created_at, r.finished_at
               FROM runs r JOIN agents a ON a.id = r.agent_id
               ORDER BY r.created_at DESC LIMIT %s"""),
            (bounded_limit,),
        ).fetchall()
    output = []
    for item in runs:
        run = dict(item)
        run["id"] = str(run["id"])
        if not IS_POSTGRES and run["result"]:
            import json

            run["result"] = json.loads(run["result"])
        output.append(run)
    return output


@app.post("/runs", status_code=202)
def create_run(request: RunRequest) -> dict:
    run_id = uuid4()
    with connect() as conn:
        agent = conn.execute(
            statement(
                "SELECT id, org_id, workspace_id, instructions FROM agents WHERE id = %s"
            ),
            (request.agent_id,),
        ).fetchone()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        conn.execute(
            statement("""INSERT INTO runs
               (id, org_id, workspace_id, agent_id, requested_by, task, agent_instructions, status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 'queued')"""),
            (
                as_id(run_id),
                agent["org_id"],
                agent["workspace_id"],
                agent["id"],
                "local-developer",
                request.task,
                agent["instructions"],
            ),
        )
        conn.execute(
            statement(
                "INSERT INTO jobs (id, run_id, status) VALUES (%s, %s, 'queued')"
            ),
            (as_id(uuid4()), as_id(run_id)),
        )
    return {"run_id": str(run_id), "status": "queued", "poll": f"/runs/{run_id}"}


@app.get("/runs/{run_id}")
def get_run(run_id: UUID) -> dict:
    with connect() as conn:
        run = conn.execute(
            statement("""SELECT id, org_id, workspace_id, agent_id, requested_by, task, agent_instructions,
                      status, result, error, created_at, started_at, finished_at
               FROM runs WHERE id = %s"""),
            (as_id(run_id),),
        ).fetchone()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    run = dict(run)
    run["id"] = str(run["id"])
    if not IS_POSTGRES and run["result"]:
        import json

        run["result"] = json.loads(run["result"])
    return run
