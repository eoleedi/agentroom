"""HTTP gateway for AgentRoom Interior."""

import asyncio
from contextlib import asynccontextmanager, suppress
import difflib
import json
import os
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .agents import DEFAULT_BASE, MODEL, GMI
from .geometry import CanvasPatch, PLAN_ID, validate
from .store import ARTIFACTS, CLIENTS, ROLES, DomainError, Store
from .workflow import DEMO_INPUTS, NAMES, Workflow

ROOT = Path(__file__).resolve().parents[3]
Role = Literal["client_a", "client_b", "budget", "design"]
Decision = Literal["approve", "reject", "request_changes"]
NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: NonEmpty
    request_id: Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]{8,100}$")]


class BriefDecision(BaseModel):
    expected_seq: int = Field(gt=0)
    action: Literal["approve", "request_changes"]


class ProposalDecision(BaseModel):
    expected_version: int = Field(gt=0)
    action: Decision
    role: Role | None = None
    note: str = Field(default="", max_length=1000)


class ProjectInput(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=72)]
    budget: int = Field(default=1500000, ge=1, le=100000000)


def create_app(db_path=None, mode=None, provider=None, seed=True):
    load_dotenv(ROOT / ".env")
    mode = mode or os.getenv("AGENTROOM_MODE", "demo")
    if mode not in {"demo", "live"}:
        raise ValueError("AGENTROOM_MODE must be demo or live.")
    demo = mode == "demo"
    path = Path(db_path or os.getenv("AGENTROOM_DB") or ROOT / ".data" / f"agentroom-{mode}.sqlite3")
    if not path.is_absolute():
        path = ROOT / path
    store = Store(path)
    gmi = provider or GMI(os.getenv("GMI_API_KEY", ""), os.getenv("GMI_BASE_URL", DEFAULT_BASE), os.getenv("GMI_MODEL", MODEL))
    workflow = Workflow(store, gmi, demo)
    default_id = "oak-residence"

    @asynccontextmanager
    async def lifespan(_app):
        store.initialize()
        workflow.initialize_project(default_id, "The Oak Residence", 1500000, seed_demo=demo and seed)
        if demo and seed:
            await workflow.seed_demo(default_id)
        worker = asyncio.create_task(workflow.worker())
        try:
            yield
        finally:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker

    app = FastAPI(title="AgentRoom Interior", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=[os.getenv("APP_ORIGIN", "http://localhost:5173")],
                       allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])
    app.state.store, app.state.workflow = store, workflow
    api = APIRouter(prefix="/api")

    @app.exception_handler(DomainError)
    async def error_handler(_request: Request, exc: DomainError):
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})

    def auth():
        return "overview"

    Actor = Annotated[str, Depends(auth)]

    def act_as(actor, requested):
        if actor == "overview" and requested in ROLES:
            return requested
        if actor == requested or (requested is None and actor in ROLES):
            return actor
        raise DomainError(403, "This action belongs to a different participant.")

    @api.get("/health")
    def health():
        return {"mode": mode, "model": gmi.model, "gmi_configured": bool(gmi.token), "default_project_id": default_id}

    @api.post("/projects", status_code=201)
    def create_project(body: ProjectInput, actor: Actor):
        if actor not in ("overview", "design"):
            raise DomainError(403, "Only the space designer can create a project.")
        identifier = uuid4().hex[:16]
        workflow.initialize_project(identifier, body.name, body.budget)
        return {"id": identifier}

    @api.get("/projects/{project_id}")
    def project_info(project_id: str, actor: Actor, at: Annotated[int | None, Query(ge=0)] = None):
        with store.connect() as db:
            project = store.project(db, project_id)
            state = project["state"].copy()
            drafts = state.pop("drafts")
            state.pop("confirmed")
            state.pop("pending_brief")
            state.pop("demo_seed_pending", None)
            if at is not None:
                row = db.execute(
                    "SELECT payload FROM events WHERE project_id=? AND type='room.state' AND seq<=? ORDER BY seq DESC LIMIT 1",
                    (project_id, at),
                ).fetchone()
                state = json.loads(row["payload"]) if row else {"phase": "requirements", "confirmed_clients": [],
                    "plan_version": 0, "estimate_version": 0, "brief_version": 0, "budget_stale": False,
                    "negotiation": None, "review": None, "approved_plan_version": None}
                drafts = {}
            active_runs = [] if at is not None else [
                {key: row[key] for key in ("id", "kind", "status", "stage")}
                for row in db.execute("SELECT id,kind,status,stage FROM jobs WHERE project_id=? AND kind!='chat' "
                                      "AND status IN ('queued','running') ORDER BY created_at", (project_id,))]
        return {"id": project_id, "name": project["name"], "budget": project["budget"], "state": state, "actor": actor,
                "active_runs": active_runs,
                "drafts": drafts if actor == "overview" else {actor: drafts[actor]} if actor in drafts else {},
                "participants": NAMES, "suggested_messages": DEMO_INPUTS if demo else {}}

    @api.post("/projects/{project_id}/agents/{role}/messages", status_code=202)
    def send_message(project_id: str, role: Role, body: ChatInput, actor: Actor):
        role = act_as(actor, role)
        with store.connect(write=True) as db:
            store.project(db, project_id)
            active = db.execute(
                "SELECT request_key FROM jobs WHERE project_id=? AND kind='chat' AND json_extract(payload,'$.role')=? "
                "AND status IN ('queued','running')", (project_id, role),
            ).fetchone()
            key = f"chat:{role}:{body.request_id}"
            if active and active["request_key"] != key:
                raise DomainError(409, "Wait for the current reply before sending another message.")
            return {"run_id": workflow.queue_chat(db, project_id, role, body.content, key)}

    @api.get("/projects/{project_id}/messages")
    def messages(project_id: str, actor: Actor, channel: str = "shared"):
        if channel != "shared":
            act_as(actor, channel)
        with store.connect() as db:
            store.project(db, project_id)
            kind = "agent.message" if channel == "shared" else "private.message.created"
            rows = db.execute(
                "SELECT * FROM events WHERE project_id=? AND type=? AND visibility=? ORDER BY seq DESC LIMIT 100",
                (project_id, kind, channel),
            ).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in reversed(rows)]

    @api.post("/projects/{project_id}/briefs/{role}/decision")
    def brief_decision(project_id: str, role: Role, body: BriefDecision, actor: Actor):
        role = act_as(actor, role)
        with store.connect(write=True) as db:
            workflow.confirm_brief(db, project_id, role, body.expected_seq, body.action)
        return {"ok": True}

    @api.post("/projects/{project_id}/proposals/{proposal_id}/decision")
    def decision(project_id: str, proposal_id: str, body: ProposalDecision, actor: Actor):
        role = act_as(actor, body.role)
        with store.connect(write=True) as db:
            workflow.decision(db, project_id, role, proposal_id, body.expected_version, body.action, body.note)
        return {"ok": True}

    @api.get("/projects/{project_id}/events")
    async def events(project_id: str, actor: Actor, after_seq: Annotated[int, Query(ge=0)] = 0,
                     wait: Annotated[float, Query(ge=0, le=20)] = 0, request: Request = None):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + wait
        while True:
            with store.connect() as db:
                store.project(db, project_id)
                batch = store.events(db, project_id, actor, after_seq)
            if batch or loop.time() >= deadline or await request.is_disconnected():
                return {"events": batch, "next_seq": batch[-1]["seq"] if batch else after_seq}
            await asyncio.sleep(0.25)

    @api.get("/projects/{project_id}/workspace")
    def workspace(project_id: str, actor: Actor, at: Annotated[int | None, Query(ge=0)] = None):
        with store.connect() as db:
            store.project(db, project_id)
            entries = []
            for identifier in ARTIFACTS:
                try:
                    artifact = store.artifact(db, project_id, identifier, actor, at=at)
                except DomainError as exc:
                    if exc.status != 404:
                        raise
                    continue
                artifact.pop("body")
                entries.append(artifact)
        return entries

    @api.get("/projects/{project_id}/artifacts/{artifact_id}")
    def artifact(project_id: str, artifact_id: str, actor: Actor, version: Annotated[int | None, Query(gt=0)] = None,
                 at: Annotated[int | None, Query(ge=0)] = None):
        with store.connect() as db:
            return store.artifact(db, project_id, artifact_id, actor, version, at)

    @api.get("/projects/{project_id}/artifacts/{artifact_id}/diff")
    def diff(project_id: str, artifact_id: str, actor: Actor,
             from_version: Annotated[int, Query(alias="from", gt=0)], to_version: Annotated[int, Query(alias="to", gt=0)]):
        with store.connect() as db:
            first = store.artifact(db, project_id, artifact_id, actor, from_version)["body"]
            second = store.artifact(db, project_id, artifact_id, actor, to_version)["body"]
        def lines(value):
            return (value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)).splitlines()
        return {"lines": list(difflib.unified_diff(lines(first), lines(second), f"v{from_version}", f"v{to_version}", lineterm=""))}

    @api.get("/projects/{project_id}/plans/{plan_id}")
    def plan(project_id: str, plan_id: str, actor: Actor, version: Annotated[int | None, Query(gt=0)] = None):
        if plan_id != PLAN_ID:
            raise DomainError(404, "Plan not found.")
        with store.connect() as db:
            return store.artifact(db, project_id, "plan", actor, version)

    @api.post("/projects/{project_id}/plans/{plan_id}/validate")
    def validate_plan(project_id: str, plan_id: str, actor: Actor, version: Annotated[int | None, Query(gt=0)] = None):
        return validate(plan(project_id, plan_id, actor, version)["body"])

    @api.post("/projects/{project_id}/plans/{plan_id}/patches", status_code=202)
    def patch_plan(project_id: str, plan_id: str, body: CanvasPatch, actor: Actor):
        if plan_id != PLAN_ID:
            raise DomainError(404, "Plan not found.")
        role = act_as(actor, "design")
        with store.connect(write=True) as db:
            return workflow.patch_plan(db, project_id, role, body)

    @api.get("/projects/{project_id}/budgets/latest")
    def budget(project_id: str, actor: Actor):
        with store.connect() as db:
            project = store.project(db, project_id)
            estimate = store.artifact(db, project_id, "estimate", actor)
            return {**estimate, "stale": project["state"]["budget_stale"]}

    @api.post("/projects/{project_id}/runs", status_code=202)
    def alternative(project_id: str, actor: Actor):
        with store.connect(write=True) as db:
            return {"run_id": workflow.request_alternative(db, project_id, act_as(actor, "design"))}

    @api.get("/projects/{project_id}/runs/{run_id}")
    def run_status(project_id: str, run_id: str, actor: Actor):
        with store.connect() as db:
            job = db.execute("SELECT * FROM jobs WHERE project_id=? AND id=?", (project_id, run_id)).fetchone()
            if not job or (job["kind"] == "chat" and actor not in ("overview", json.loads(job["payload"])["role"])):
                raise DomainError(404, "Run not found.")
            return {key: job[key] for key in ("id", "kind", "status", "stage", "attempts", "error")}

    @api.post("/projects/{project_id}/runs/{run_id}/cancel")
    def cancel(project_id: str, run_id: str, actor: Actor):
        with store.connect(write=True) as db:
            job = db.execute("SELECT * FROM jobs WHERE project_id=? AND id=?", (project_id, run_id)).fetchone()
            if not job:
                raise DomainError(404, "Run not found.")
            private = job["kind"] == "chat"
            role = json.loads(job["payload"])["role"] if private else "design"
            act_as(actor, role)
            if job["status"] not in ("queued", "running"):
                raise DomainError(409, "Only queued or running jobs can be cancelled.")
            db.execute("UPDATE jobs SET status='cancelled' WHERE id=?", (run_id,))
            store.emit(db, project_id, run_id, "agent.task.cancelled", NAMES[role],
                       {"summary": "Run cancelled.", "role": role}, role if private else "shared")
            if not private:
                state = store.project(db, project_id)["state"]
                state["phase"] = "failed"
                workflow.snapshot(db, project_id, state, run_id)
        return {"ok": True}

    app.include_router(api)
    return app


app = create_app()
