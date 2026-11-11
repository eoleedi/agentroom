"""SQLite workspace, immutable artifact versions, and durable room events."""

from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
import sqlite3
from uuid import uuid4

ROLES = ("client_a", "client_b", "budget", "design")
CLIENTS = ROLES[:2]
AGENTS = {"client_a": "Requirement Agent", "client_b": "Requirement Agent", "budget": "Budget Agent", "design": "Design Agent"}
ARTIFACTS = {
    "room": ("Geometry/measured_floorplan.json", "design", "shared"),
    "catalog": ("Geometry/furniture_catalog.json", "design", "shared"),
    "style": ("Requirements/style_board.json", "client_a", "shared"),
    "brief": ("Requirements/design_brief.json", "client_a", "shared"),
    "conflict": ("Requirements/change_request.json", "client_a", "shared"),
    "candidate": ("Design/layout_candidates.json", "design", "shared"),
    "plan": ("Design/floorplan.json", "design", "shared"),
    "preview": ("Design/floorplan.svg", "design", "shared"),
    "validation": ("Geometry/validation_report.json", "design", "shared"),
    "bom": ("Design/material_bom.json", "design", "shared"),
    "price": ("Budget/price_catalog.json", "budget", "budget"),
    "estimate": ("Budget/estimate.json", "budget", "shared"),
    "comparison": ("Budget/cost_comparison.md", "budget", "shared"),
    "proposal": ("Deliverables/design_proposal.md", "design", "shared"),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, name TEXT NOT NULL, budget INTEGER NOT NULL, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(
  project_id TEXT NOT NULL REFERENCES projects(id), seq INTEGER NOT NULL, event_id TEXT UNIQUE NOT NULL,
  run_id TEXT NOT NULL, actor TEXT NOT NULL, type TEXT NOT NULL, visibility TEXT NOT NULL, timestamp TEXT NOT NULL, payload TEXT NOT NULL,
  PRIMARY KEY(project_id, seq)
);
CREATE TABLE IF NOT EXISTS artifacts(
  project_id TEXT NOT NULL REFERENCES projects(id), id TEXT NOT NULL, version INTEGER NOT NULL, body TEXT NOT NULL,
  sha TEXT NOT NULL, inputs TEXT NOT NULL, run_id TEXT NOT NULL, event_seq INTEGER NOT NULL, status TEXT NOT NULL,
  PRIMARY KEY(project_id, id, version)
);
CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), request_key TEXT NOT NULL,
  kind TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
  stage TEXT NOT NULL DEFAULT 'queued', error TEXT, created_at TEXT NOT NULL,
  UNIQUE(project_id, request_key)
);
CREATE INDEX IF NOT EXISTS jobs_waiting ON jobs(status, created_at);
"""


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def now():
    return datetime.now(timezone.utc).isoformat()


class DomainError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class Store:
    def __init__(self, path):
        self.path = path

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript(SCHEMA)
            db.execute("UPDATE jobs SET status='queued' WHERE status='running'")

    @contextmanager
    def connect(self, write=False):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def project(db, project_id):
        row = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise DomainError(404, "Project not found.")
        return {**dict(row), "state": json.loads(row["state"])}

    @staticmethod
    def update(db, project_id, state):
        db.execute("UPDATE projects SET state=? WHERE id=?", (encode(state), project_id))

    @staticmethod
    def emit(db, project_id, run_id, kind, actor, payload, visibility="shared"):
        seq = db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE project_id=?", (project_id,)).fetchone()[0]
        db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)",
                   (project_id, seq, uuid4().hex, run_id, actor, kind, visibility, now(), encode(payload)))
        return seq

    @staticmethod
    def events(db, project_id, role, after=0, limit=500, through=None):
        rows = db.execute(
            """SELECT * FROM events WHERE project_id=? AND seq>? AND seq<=?
               AND (visibility='shared' OR visibility=? OR ?='overview') ORDER BY seq LIMIT ?""",
            (project_id, after, through if through is not None else 2**63-1, role, role, limit),
        )
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]

    @staticmethod
    def latest(db, project_id, artifact_id):
        return db.execute("SELECT COALESCE(MAX(version),0) FROM artifacts WHERE project_id=? AND id=?",
                          (project_id, artifact_id)).fetchone()[0]

    def write(self, db, project_id, run_id, artifact_id, body, expected, inputs=(), status="draft", object_ids=()):
        path, owner, visibility = ARTIFACTS[artifact_id]
        if expected != self.latest(db, project_id, artifact_id):
            raise DomainError(409, "Artifact version changed. Reload the workspace before retrying.")
        content = encode(body)
        if len(content.encode()) > 256_000:
            raise DomainError(422, "Artifact exceeds the workspace size limit.")
        version = expected + 1
        seq = self.emit(db, project_id, run_id, "workspace.file.written", AGENTS[owner], {
            "artifact_id": artifact_id, "path": path, "from_version": expected, "to_version": version,
            "summary": f"Wrote {path.split('/')[-1]} v{version}.", "object_ids": object_ids,
        }, visibility)
        db.execute("INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?)",
                   (project_id, artifact_id, version, content, sha256(content.encode()).hexdigest(),
                    encode(inputs), run_id, seq, status))
        return version

    @staticmethod
    def artifact(db, project_id, artifact_id, role, version=None, at=None):
        if artifact_id not in ARTIFACTS:
            raise DomainError(404, "Artifact not found.")
        path, owner, visibility = ARTIFACTS[artifact_id]
        if visibility != "shared" and role not in (visibility, "overview"):
            raise DomainError(404, "Artifact not found.")
        rows = db.execute(
            "SELECT * FROM artifacts WHERE project_id=? AND id=? AND event_seq<=? ORDER BY version DESC",
            (project_id, artifact_id, at if at is not None else 2**63-1),
        ).fetchall()
        row = next((row for row in rows if version is None or row["version"] == version), None)
        if row is None:
            raise DomainError(404, "Artifact version not found.")
        return {**dict(row), "body": json.loads(row["body"]), "inputs": json.loads(row["inputs"]),
                "path": path, "owner": AGENTS[owner], "versions": [item["version"] for item in rows]}

    def read_for_agent(self, db, project_id, run_id, identifier, role, version=None):
        data = self.artifact(db, project_id, identifier, role, version)
        self.emit(db, project_id, run_id, "workspace.file.read", AGENTS[role], {
            "artifact_id": identifier, "path": data["path"], "version": data["version"],
            "summary": f"Read {data['path'].split('/')[-1]} v{data['version']}.",
        }, ARTIFACTS[identifier][2])
        return data

    @staticmethod
    def enqueue(db, project_id, request_key, kind, payload):
        run_id = uuid4().hex
        cursor = db.execute(
            "INSERT OR IGNORE INTO jobs(id,project_id,request_key,kind,payload,status,created_at) VALUES (?,?,?,?,?,'queued',?)",
            (run_id, project_id, request_key, kind, encode(payload), now()),
        )
        if cursor.rowcount:
            return run_id, True
        row = db.execute("SELECT id, kind, payload FROM jobs WHERE project_id=? AND request_key=?",
                         (project_id, request_key)).fetchone()
        if row["kind"] != kind or row["payload"] != encode(payload):
            raise DomainError(409, "This request key was already used for a different action.")
        return row["id"], False

    def claim(self):
        with self.connect(write=True) as db:
            job = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if job is None:
                return None
            db.execute("UPDATE jobs SET status='running', attempts=attempts+1 WHERE id=?", (job["id"],))
            return {**dict(job), "payload": json.loads(job["payload"]), "attempts": job["attempts"]+1}

    @staticmethod
    def require_active(db, run_id):
        row = db.execute("SELECT status FROM jobs WHERE id=?", (run_id,)).fetchone()
        if row is None or row["status"] != "running":
            raise DomainError(409, "This run is no longer active.")

    @staticmethod
    def job_status(db, run_id, status, stage, error=None):
        cursor = db.execute(
            "UPDATE jobs SET status=?, stage=?, error=? WHERE id=? AND status='running'",
            (status, stage, error, run_id),
        )
        if not cursor.rowcount:
            raise DomainError(409, "This run is no longer active.")
