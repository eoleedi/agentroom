"""Room orchestration. Only typed, approved inputs can reach shared tools."""

import asyncio
import logging
import json
from uuid import uuid4

from pydantic import ValidationError

from . import geometry as geo
from .agents import Brief, ChatReply, Commentary, GMI, ModelFailure, Reconciliation, demo_chat
from .store import AGENTS, CLIENTS, ROLES, DomainError, Store, encode

LOG = logging.getLogger(__name__)
NAMES = {"client_a": "Alex Morgan", "client_b": "Maya Chen", "budget": "Jordan Lee", "design": "Sam Rivera"}
DEMO_INPUTS = {
    "client_a": "I want a large 1,800 mm oak island for prep, with a warm Japandi feel and a dining table for six.",
    "client_b": "Keep all six seats. I prefer a compact island with open circulation, warm oak, and low storage.",
}


def ref(identifier, version):
    return {"artifact_id": identifier, "version": version}


class Workflow:
    def __init__(self, store: Store, gmi: GMI, demo: bool):
        self.store, self.gmi, self.demo = store, gmi, demo

    def snapshot(self, db, project_id, state, run_id):
        self.store.update(db, project_id, state)
        public = {key: value for key, value in state.items() if key not in ("drafts", "confirmed", "pending_brief")}
        self.store.emit(db, project_id, run_id, "room.state", "AgentRoom", public)

    def shared(self, db, project_id, run_id, role, to, content, **payload):
        self.store.emit(db, project_id, run_id, "agent.message", AGENTS[role],
                        {"recipient": to, "content": content, **payload})

    def tool(self, db, project_id, run_id, role, name, summary, **payload):
        self.store.emit(db, project_id, run_id, "agent.tool_event", AGENTS[role],
                        {"tool": name, "summary": summary, **payload})

    def initialize_project(self, project_id, name, budget):
        run_id = uuid4().hex
        with self.store.connect(write=True) as db:
            if db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
                return False
            state = {
                "phase": "requirements", "drafts": {}, "confirmed": {}, "pending_brief": {},
                "confirmed_clients": [], "brief_version": 0, "plan_version": 0, "estimate_version": 0,
                "budget_stale": False, "negotiation": None, "review": None, "approved_plan_version": None,
            }
            db.execute("INSERT INTO projects VALUES (?,?,?,?)", (project_id, name, budget, encode(state)))
            for artifact, value in (
                ("room", {**geo.ROOM, "fixed_features": geo.FEATURES}),
                ("catalog", {k: {name: value for name, value in item.items() if name != "price"} for k, item in geo.CATALOG.items()}),
                ("price", {"assumptions": geo.PRICING, "items": {key: {"price": value["price"], "unit": value["unit"]} for key, value in geo.CATALOG.items()}}),
                ("style", {"direction": "Warm Japandi", "materials": geo.MATERIALS,
                           "principles": ["Warm timber", "Quiet contrast", "Open circulation"]}),
            ):
                self.store.write(db, project_id, run_id, artifact, value, 0, status="reference")
            self.snapshot(db, project_id, state, run_id)
        return True

    def queue_chat(self, db, project_id, role, content, key):
        run_id, created = self.store.enqueue(db, project_id, key, "chat", {"role": role, "content": content})
        if created:
            self.store.emit(db, project_id, run_id, "private.message.created", NAMES[role],
                            {"role": role, "content": content, "speaker": "human"}, role)
        return run_id

    def confirm_brief(self, db, project_id, role, expected, action):
        state = self.store.project(db, project_id)["state"]
        draft = state["drafts"].get(role)
        if role not in CLIENTS:
            raise DomainError(403, "Only the client who owns this brief can decide.")
        if action == "approve" and state["pending_brief"].get(role) == expected:
            return
        if not draft or draft["seq"] != expected:
            raise DomainError(409, "This brief has changed. Review the latest version.")
        if state["phase"] != "requirements":
            raise DomainError(409, "The initial brief is locked. Review the current change request.")
        del state["drafts"][role]
        state["confirmed"].pop(role, None)
        state["pending_brief"].pop(role, None)
        run_id = uuid4().hex
        if action == "approve":
            state["confirmed"][role] = draft["brief"]
            state["pending_brief"][role] = expected
        state["confirmed_clients"] = list(state["confirmed"])
        self.store.emit(db, project_id, run_id, "approval.resolved", NAMES[role],
                        {"summary": "Client brief " + ("confirmed." if action == "approve" else "returned for changes."),
                         "role": role, "kind": "brief", "action": action}, role)
        if all(client in state["confirmed"] for client in CLIENTS):
            state["phase"] = "reconciling"
            self.store.enqueue(db, project_id, f"initial:{run_id}", "initial", {})
        self.snapshot(db, project_id, state, run_id)

    def decision(self, db, project_id, role, identifier, expected, action, note):
        state = self.store.project(db, project_id)["state"]
        proposal = next((state[key] for key in ("negotiation", "review")
                         if state[key] and state[key]["id"] == identifier), None)
        if proposal is None:
            raise DomainError(404, "Proposal not found.")
        if role not in proposal["required"]:
            raise DomainError(403, "Your role cannot decide on this proposal.")
        prior = proposal["decisions"].get(role)
        if prior and prior["action"] == action and proposal["version"] == expected:
            return
        if proposal["status"] != "pending" or proposal["version"] != expected or prior:
            raise DomainError(409, "The proposal changed. Reload to see the current status.")
        if proposal["kind"] == "final" and (state["budget_stale"] or proposal["plan_version"] != state["plan_version"]):
            raise DomainError(409, "An updated plan and estimate are required before approval.")
        run_id = uuid4().hex
        proposal["decisions"][role] = {"action": action}
        if note:
            self.store.emit(db, project_id, run_id, "approval.note", NAMES[role],
                            {"proposal_id": identifier, "content": note}, role)
        self.store.emit(db, project_id, run_id, "approval.resolved", NAMES[role],
                        {"proposal_id": identifier, "role": role, "action": action,
                         "summary": f"{NAMES[role]} {dict(approve='approved', reject='declined', request_changes='requested changes to')[action]} the {proposal['label'].lower()}."})
        if action != "approve":
            proposal["status"] = action
            state["phase"] = "changes_requested"
        elif all(participant in proposal["decisions"] for participant in proposal["required"]):
            proposal["status"] = "approved"
            if proposal["kind"] == "tradeoff":
                state["phase"] = "revising"
                self.store.enqueue(db, project_id, f"revision:{proposal['id']}", "revision", {"compact": True})
            else:
                state["phase"] = "approved"
                state["approved_plan_version"] = state["plan_version"]
                total = self.store.artifact(db, project_id, "estimate", "budget")["body"]["estimated_total"]
                md = (f"# Approved design proposal\n\n{self.store.project(db, project_id)['name']}\n\n"
                      f"- Floor plan v{state['plan_version']}\n- Estimate v{state['estimate_version']}, NT${total:,}\n"
                      f"- Approvers: {', '.join(NAMES[r] for r in ROLES)}\n- Demo ruleset: {geo.RULESET}\n")
                self.store.write(db, project_id, run_id, "proposal", md, self.store.latest(db, project_id, "proposal"),
                                 inputs=[ref("plan", state["plan_version"]), ref("estimate", state["estimate_version"])], status="approved")
        self.snapshot(db, project_id, state, run_id)

    def request_alternative(self, db, project_id, role):
        project = self.store.project(db, project_id)
        state = project["state"]
        if role != "design":
            raise DomainError(403, "Only the space designer can reopen a proposal.")
        if state["phase"] not in ("changes_requested", "failed"):
            raise DomainError(409, "An alternative can be requested after a declined or failed run.")
        if not all(client in state["confirmed"] for client in CLIENTS):
            raise DomainError(409, "Both client briefs are required.")
        failed = state["phase"] == "failed"
        state["phase"] = "revising"
        pending = db.execute(
            "SELECT * FROM jobs WHERE project_id=? AND kind!='chat' AND status IN ('failed','cancelled') ORDER BY created_at DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        if pending and failed:
            db.execute("UPDATE jobs SET status='queued', error=NULL WHERE id=?", (pending["id"],))
            run_id = pending["id"]
        else:
            run_id, _ = self.store.enqueue(db, project_id, f"alternative:{uuid4().hex}", "alternative", {})
        self.snapshot(db, project_id, state, run_id)
        return run_id

    def patch_plan(self, db, project_id, role, patch):
        if role != "design":
            raise DomainError(403, "Only the space designer can edit a plan.")
        project = self.store.project(db, project_id)
        key = f"patch:{patch.idempotency_key}"
        payload = patch.model_dump(mode="json")
        prior = db.execute("SELECT * FROM jobs WHERE project_id=? AND request_key=?", (project_id, key)).fetchone()
        if prior:
            if json.loads(prior["payload"]) != payload:
                raise DomainError(409, "This request key was already used for a different patch.")
            return {"run_id": prior["id"], "plan_version": patch.base_version + 1}
        state = project["state"]
        if state["phase"] not in ("review", "changes_requested") or state["budget_stale"]:
            raise DomainError(409, "Finish the active workflow or resolve the client trade-off before editing.")
        previous = self.store.artifact(db, project_id, "plan", role)
        if previous["version"] != patch.base_version or patch.expected_state_hash != f"sha256:{previous['sha']}":
            raise DomainError(409, "The plan changed. Reload the latest version before editing.")
        plan = geo.apply_patch(previous["body"], patch)
        operations = geo.plan_patch(previous["body"], plan)
        if not operations:
            raise DomainError(400, "The patch does not change any objects.")
        report = geo.validate(plan)
        if report["status"] != "passed":
            detail = ("The proposed layout failed spatial validation: " +
                      "; ".join(check["message"] for check in report["checks"])) if report["checks"] else (
                      "Verified room measurements are required before editing.")
            raise DomainError(422, detail)
        run_id, _ = self.store.enqueue(db, project_id, key, "patch", payload)
        self.commit_plan(db, project_id, run_id, state, previous["body"], plan, report)
        db.execute("UPDATE jobs SET stage='costing' WHERE id=?", (run_id,))
        self.tool(db, project_id, run_id, "design", "apply_canvas_patch", patch.reason.strip(),
                  artifact_id="plan", status="passed", plan_version=plan["plan_version"])
        return {"run_id": run_id, "plan_version": plan["plan_version"]}

    def commit_plan(self, db, project_id, run_id, state, previous, plan, report):
        version = plan["plan_version"]
        operations = geo.plan_patch(previous, plan)
        changed = [operation["object_id"] for operation in operations]
        self.store.write(db, project_id, run_id, "plan", plan, version-1, status="validated", object_ids=changed,
                         inputs=[ref("brief", state["brief_version"]), ref("room", 1), ref("catalog", 1)])
        for artifact, content in (("validation", report), ("preview", geo.render_svg(plan)), ("bom", geo.extract_bom(plan))):
            self.store.write(db, project_id, run_id, artifact, content, self.store.latest(db, project_id, artifact),
                             inputs=[ref("plan", version)])
        groups = [[op] for op in operations] if previous is None else [operations]
        for index, group in enumerate(groups):
            self.store.emit(db, project_id, run_id, "canvas.patch.applied", "Design Agent", {
                "plan_id": geo.PLAN_ID, "plan_version": version, "base_version": version-1,
                "operations": group, "batch_index": index, "batch_size": len(groups),
                "artifact_id": "plan", "summary": f"Applied {len(group)} object update(s) to plan v{version}.",
            })
        self.store.emit(db, project_id, run_id, "floorplan.draft.committed", "Design Agent",
                        {"artifact_id": "plan", "plan_version": version, "object_ids": changed})
        self.store.emit(db, project_id, run_id, "material_bom.updated", "Design Agent",
                        {"summary": "Published the plan-linked bill of materials.", "artifact_id": "bom", "plan_version": version})
        for key in ("review", "negotiation"):
            if state[key] and state[key]["status"] == "pending":
                state[key]["status"] = "superseded"
        state["phase"], state["plan_version"], state["budget_stale"] = "costing", version, True
        self.snapshot(db, project_id, state, run_id)
        self.shared(db, project_id, run_id, "design", "Budget Agent",
                    f"Validated floor plan v{version} is ready. Price the matching bill of materials.", artifact_id="bom")

    async def chat(self, job):
        project_id, run_id = job["project_id"], job["id"]
        role, content = job["payload"]["role"], job["payload"]["content"]
        with self.store.connect() as db:
            project = self.store.project(db, project_id)
            state = project["state"]
            design_context = {
                "room": self.store.artifact(db, project_id, "room", role)["body"],
                "catalog": self.store.artifact(db, project_id, "catalog", role)["body"],
                "rules": {"ruleset_version": geo.RULESET, "aisle_clearance_mm": geo.CLEARANCE,
                          "dining_pullout_mm": geo.SEATING_CLEARANCE, "source": "demo_project_rule",
                          "building_code_compliance": "unverified"},
            } if role == "design" else None
            rows = db.execute("SELECT payload FROM events WHERE project_id=? AND visibility=? AND type='private.message.created' ORDER BY seq DESC LIMIT 12",
                              (project_id, role)).fetchall()
            history = [{"speaker": event["speaker"], "content": event["content"]}
                       for row in reversed(rows) if (event := json.loads(row["payload"]))]
            version = state["estimate_version"]
            estimate = self.store.artifact(db, project_id, "estimate", role, version)["body"] if version else None
            plan_version = state["plan_version"]
            plan = self.store.artifact(db, project_id, "plan", role, plan_version)["body"] if plan_version else None
            previous_plan = self.store.artifact(db, project_id, "plan", role, plan_version-1)["body"] if plan_version > 1 else None
            previous_estimate = self.store.artifact(db, project_id, "estimate", role, version-1)["body"] if version > 1 else None
            approved_brief = self.store.artifact(db, project_id, "brief", role, state["brief_version"])["body"] if state["brief_version"] else None
            validation = self.store.artifact(db, project_id, "validation", role)["body"] if plan_version else None
            prior_brief = state["drafts"].get(role, {}).get("brief") or state["confirmed"].get(role)
            compact_estimate = None
            if role == "budget" and plan_version:
                prices = self.store.artifact(db, project_id, "price", role)
                compact_plan = geo.build_plan(geo.default_layout(compact=True), plan_version)
                compact_estimate = geo.calculate_estimate(geo.extract_bom(compact_plan), project["budget"],
                                                          self.store.latest(db, project_id, "bom"), prices["version"], prices["body"])
        if self.demo:
            reply = demo_chat(role, content, estimate, prior_brief)
        else:
            kind = "requirement" if role in CLIENTS else role
            instruction = (
                "Propose a structured brief only when the user's intent is clear and within the six-seat kitchen/dining scope. "
                "Ask about unclear or unsupported requests. Never silently relax a requirement."
                if kind == "requirement" else "Set proposed_brief to null. Answer from the supplied project context."
            )
            reply = await self.gmi.structured(kind, instruction, {
                "thread": history, "latest_user_message": content, "plan": plan if kind == "design" else None,
                "estimate": estimate, "previous_estimate": previous_estimate if kind == "budget" else None,
                "approved_brief": approved_brief, "own_previous_brief": prior_brief if role in CLIENTS else None,
                "workflow_phase": state["phase"], "negotiation": state["negotiation"], "review": state["review"],
                "previous_plan": previous_plan if kind == "design" else None,
                "plan_changes": geo.plan_patch(previous_plan, plan) if kind == "design" and plan else None,
                "validation": validation if kind == "design" else None,
                "compact_option_estimate": compact_estimate,
                "project_budget": project["budget"], "budget_stale": state["budget_stale"],
                "design_context": design_context,
            }, ChatReply)
        with self.store.connect(write=True) as db:
            self.store.job_status(db, run_id, "completed", "answered")
            self.store.emit(db, project_id, run_id, "agent.task.completed", AGENTS[role],
                            {"summary": "Private reply completed.", "role": role}, role)
            state = self.store.project(db, project_id)["state"]
            payload = {"role": role, "speaker": "agent", "content": reply.reply}
            seq = self.store.emit(db, project_id, run_id, "private.message.created", AGENTS[role], payload, role)
            if role in CLIENTS and reply.proposed_brief and state["phase"] == "requirements":
                draft = {"seq": seq, "brief": reply.proposed_brief.model_dump()}
                state["drafts"][role] = draft
                state["confirmed"].pop(role, None)
                state["pending_brief"].pop(role, None)
                state["confirmed_clients"] = list(state["confirmed"])
                self.store.emit(db, project_id, run_id, "approval.requested", AGENTS[role], draft, role)
                self.snapshot(db, project_id, state, run_id)

    async def reconcile(self, project_id, run_id, project):
        state = project["state"]
        approved = [state["confirmed"][client] for client in CLIENTS]
        first, second = approved
        island_conflict = {first["island"], second["island"]} == {"large", "compact"}
        style_conflict = first["style"] != second["style"]
        style = first["style"] if not style_conflict else "Warm Japandi"
        priority = first["priority"] if first["priority"] == second["priority"] else "balanced"
        summary = (
            "Alex wants more prep surface. Maya wants a wider route through the kitchen. Compare both island sizes while keeping the six-seat dining table."
            if island_conflict else "Both client briefs are confirmed. Compare catalog options with six seats and low storage retained."
        )
        if style_conflict:
            summary += " The material board blends the two style preferences through warm timber and a restrained palette."
        if not self.demo:
            result = await self.gmi.structured("requirement",
                "Summarize the tensions and a shared direction. Use only the confirmed structured briefs. Keep six seats. "
                "Human approval is still required for a change in island size.", {"confirmed_briefs": approved}, Reconciliation)
            style, priority, summary = result.style, result.priority, result.summary
        large_baseline = island_conflict or "large" in {first["island"], second["island"]}
        return {"approved_client_briefs": state["confirmed"], "style": style, "priority": priority, "seating": 6,
                "island_conflict": island_conflict, "style_conflict": style_conflict,
                "island_baseline": "large" if large_baseline else "compact", "summary": summary}

    async def propose_layout(self, compact, brief, previous, rejected=None):
        if self.demo:
            if previous:
                positions = {obj["id"]: {"catalog_id": obj["catalog_id"], "center_mm": obj["center_mm"],
                                       "rotation_deg": obj["rotation_deg"]} for obj in previous["objects"]}
                positions["island_01"]["catalog_id"] = "island-compact" if compact else "island-large"
                return geo.Layout.model_validate(positions)
            return geo.default_layout(compact, crowded=rejected is None)
        return await self.gmi.structured(
            "design",
            "Return the four placements. Keep kitchen_01 fixed. Use the supplied island variant and six-seat table. "
            "Dining requires a 650 mm pull-out envelope on all sides. Storage needs 500 mm in front. "
            "Keep 900 mm between island and table, and between kitchen and island. Preserve unaffected positions on revision. "
            "The reference placement fits demo constraints and can be used if appropriate.",
            {"room": geo.ROOM, "fixed_features": geo.FEATURES, "brief": brief, "previous_plan": previous,
             "required_island": "island-compact" if compact else "island-large",
             "reference_placement": geo.default_layout(compact).model_dump(mode="json"),
             "feedback": rejected}, geo.Layout,
        )

    async def design(self, job, project):
        project_id, run_id, kind = job["project_id"], job["id"], job["kind"]
        state = project["state"]
        previous = None
        if kind == "initial":
            brief = await self.reconcile(project_id, run_id, project)
            compact = brief["island_baseline"] == "compact"
        else:
            with self.store.connect() as db:
                brief = self.store.artifact(db, project_id, "brief", "design", state["brief_version"])["body"]
                if state["plan_version"]:
                    previous = self.store.artifact(db, project_id, "plan", "design", state["plan_version"])["body"]
            compact = kind == "revision" or bool(previous and next(obj for obj in previous["objects"] if obj["id"] == "island_01")["catalog_id"] == "island-compact")
        with self.store.connect(write=True) as db:
            self.store.require_active(db, run_id)
            state = self.store.project(db, project_id)["state"]
            if kind == "initial" and not state["brief_version"]:
                brief_version = self.store.write(db, project_id, run_id, "brief", brief, 0, status="approved")
                state["brief_version"] = brief_version
                materials = geo.MATERIALS
                palette = {
                    "Warm Japandi": ["warm-oak", "plaster", "sage", "smoked-oak"],
                    "Soft Minimalism": ["plaster", "stone", "warm-oak"],
                    "Natural Modern": ["stone", "smoked-oak", "sage", "warm-oak"],
                }[brief["style"]]
                self.store.write(db, project_id, run_id, "style",
                                 {"direction": brief["style"], "materials": {key: materials[key] for key in palette}},
                                 self.store.latest(db, project_id, "style"), inputs=[ref("brief", brief_version)])
                self.store.emit(db, project_id, run_id, "requirement.approved", "Requirement Agent",
                                {"summary": "Both clients confirmed their requirements.", "brief_version": brief_version})
                self.shared(db, project_id, run_id, "client_a", "Design Agent", brief["summary"], artifact_id="brief")
            else:
                self.shared(db, project_id, run_id, "client_a", "Design Agent",
                            "Review the agreed priorities and prepare a revised layout with the six dining seats preserved.",
                            artifact_id="brief")
            state["phase"] = "designing"
            for identifier in ("brief", "room", "catalog"):
                self.store.read_for_agent(db, project_id, run_id, identifier, "design")
            self.snapshot(db, project_id, state, run_id)
        version = state["plan_version"] + 1
        feedback = None
        candidates = []
        for attempt in range(3):
            layout = await self.propose_layout(compact, brief, previous, feedback)
            expected = "island-compact" if compact else "island-large"
            if layout.island_01.catalog_id != expected:
                feedback = {"summary": f"The authorized island catalog ID is {expected}."}
                continue
            plan = geo.build_plan(layout, version)
            report = geo.validate(plan)
            candidates.append({"attempt": attempt+1, "plan": plan, "validation": report})
            with self.store.connect(write=True) as db:
                self.store.require_active(db, run_id)
                self.tool(db, project_id, run_id, "design", "validate_geometry",
                          report["checks"][-1]["message"] if report["checks"] else f"Layout v{version} passed all modeled checks.",
                           status=report["status"], checks=report["checks"], plan_version=version)
                if report["status"] != "passed":
                    self.shared(db, project_id, run_id, "design", "Requirement Agent",
                                "The proposed placement failed the modeled spatial checks. " +
                                " ".join(check["message"] for check in report["checks"]) +
                                " I will revise the candidate before publishing a validated draft.",
                                plan_version=version)
            if report["status"] == "passed":
                break
            feedback = report
        else:
            with self.store.connect(write=True) as db:
                self.store.require_active(db, run_id)
                self.store.write(db, project_id, run_id, "candidate", candidates,
                                 self.store.latest(db, project_id, "candidate"), status="needs_review")
            raise DomainError(422, "No candidate passed the modeled spatial checks after three attempts.")
        with self.store.connect(write=True) as db:
            self.store.require_active(db, run_id)
            state = self.store.project(db, project_id)["state"]
            if state["plan_version"] + 1 != version:
                raise DomainError(409, "The floor plan advanced while the agent was working.")
            self.store.write(db, project_id, run_id, "candidate", candidates, self.store.latest(db, project_id, "candidate"),
                             inputs=[ref("brief", state["brief_version"])])
            self.shared(db, project_id, run_id, "design", "Requirement Agent",
                        f"Plan v{version} passed the modeled geometry checks. Six dining seats are retained. " +
                        ("The compact-island revision preserves unaffected placements." if kind == "revision" else
                         "The validated draft and its source artifacts are ready for costing."),
                        artifact_id="validation", plan_version=version)
            self.commit_plan(db, project_id, run_id, state, previous, plan, report)
            self.store.job_status(db, run_id, "running", "costing")

    async def cost(self, job, project):
        project_id, run_id = job["project_id"], job["id"]
        with self.store.connect(write=True) as db:
            self.store.require_active(db, run_id)
            state = self.store.project(db, project_id)["state"]
            bom = self.store.read_for_agent(db, project_id, run_id, "bom", "budget")
            prices = self.store.read_for_agent(db, project_id, run_id, "price", "budget")
            previous = self.store.artifact(db, project_id, "estimate", "budget")["body"] if state["estimate_version"] else None
        estimate = geo.calculate_estimate(bom["body"], project["budget"], bom["version"], prices["version"], prices["body"])
        alternative = None
        if estimate["remaining"] < 0:
            plan = geo.build_plan(geo.default_layout(compact=True), state["plan_version"])
            alternative = geo.calculate_estimate(geo.extract_bom(plan), project["budget"], bom["version"], prices["version"], prices["body"])
        total = estimate["estimated_total"]
        balance = estimate["remaining"]
        recommendation = (
            f"The estimate is NT${total:,}, NT${abs(balance):,} over budget. "
            f"The 1,500 mm modular oak island would bring it to NT${alternative['estimated_total']:,} and retain six seats."
            if alternative else f"The updated estimate is NT${total:,}, with NT${balance:,} remaining in the project budget."
        )
        if not self.demo:
            try:
                response = await self.gmi.structured("budget",
                    "Summarize the authoritative estimate and the island trade-off in at most two sentences. "
                    "The dashboard supplies exact figures separately. Do not include any numbers, prices, dimensions, or private details.",
                    {"estimate": estimate, "compact_option": alternative}, Commentary)
                if not any(char.isdigit() for char in response.summary):
                    recommendation += f" {response.summary}"
            except ModelFailure:
                with self.store.connect(write=True) as db:
                    self.store.require_active(db, run_id)
                    self.tool(db, project_id, run_id, "budget", "explain_estimate",
                              "GMI commentary was unavailable. The deterministic estimate is available.", status="warning")
        with self.store.connect(write=True) as db:
            self.store.require_active(db, run_id)
            state = self.store.project(db, project_id)["state"]
            if (self.store.latest(db, project_id, "bom") != bom["version"] or
                    self.store.latest(db, project_id, "price") != prices["version"]):
                raise DomainError(409, "The bill of materials or price catalog changed during costing.")
            version = self.store.write(db, project_id, run_id, "estimate", estimate, state["estimate_version"],
                                       inputs=[ref("bom", bom["version"]), ref("price", prices["version"])], status="estimated")
            self.tool(db, project_id, run_id, "budget", "calculate_estimate",
                      f"Calculated NT${total:,} from BOM v{bom['version']}.", status="passed", artifact_id="estimate")
            if previous:
                before = previous["estimated_total"]
                delta = total-before
                md = f"# Cost comparison\n\n- Previous estimate: NT${before:,}\n- Current estimate: NT${total:,}\n- Change: {delta:+,} TWD\n"
                self.store.write(db, project_id, run_id, "comparison", md, self.store.latest(db, project_id, "comparison"),
                                 inputs=[ref("estimate", version-1), ref("estimate", version)])
            self.shared(db, project_id, run_id, "budget", "Requirement & Design", recommendation, artifact_id="estimate")
            self.store.emit(db, project_id, run_id, "estimate.completed", "Budget Agent",
                            {"summary": f"Estimate v{version} is ready.", "artifact_id": "estimate", "version": version})
            state["estimate_version"], state["budget_stale"] = version, False
            large_island = any(line["catalog_id"] == "island-large" for line in bom["body"]["items"])
            if alternative and large_island and job["kind"] != "alternative":
                state["phase"] = "negotiation"
                proposal = {
                    "id": uuid4().hex, "kind": "tradeoff", "version": version, "status": "pending",
                    "required": list(CLIENTS), "decisions": {}, "plan_version": state["plan_version"],
                    "label": "Island trade-off", "summary": "Swap the 1,800 mm custom island for the 1,500 mm modular oak island. Keep the six-seat table.",
                    "savings": total-alternative["estimated_total"], "projected_total": alternative["estimated_total"],
                }
                state["negotiation"] = proposal
                self.store.write(db, project_id, run_id, "conflict", proposal, self.store.latest(db, project_id, "conflict"),
                                 inputs=[ref("estimate", version), ref("brief", state["brief_version"])])
                self.shared(db, project_id, run_id, "client_a", "Design Agent",
                            "I have asked both clients to approve the compact island and retain six seats before a revision.",
                            artifact_id="conflict")
            elif balance >= 0:
                state["phase"] = "review"
                proposal = {
                    "id": uuid4().hex, "kind": "final", "version": version, "status": "pending",
                    "required": list(ROLES), "decisions": {}, "plan_version": state["plan_version"],
                    "label": "Design package", "summary": f"Review floor plan v{state['plan_version']}, its validation report, and estimate v{version}.",
                }
                state["review"] = proposal
            else:
                state["phase"] = "changes_requested"
                proposal = None
            if proposal:
                self.store.emit(db, project_id, run_id, "approval.requested", "AgentRoom",
                                {"proposal_id": proposal["id"], "summary": proposal["summary"]})
            self.snapshot(db, project_id, state, run_id)
            self.store.job_status(db, run_id, "completed", "complete")
            self.store.emit(db, project_id, run_id, "agent.task.completed", "Budget Agent",
                            {"summary": "Layout validation and costing completed.", "plan_version": state["plan_version"]})

    async def execute(self, job):
        project_id, run_id = job["project_id"], job["id"]
        kind = job["kind"]
        try:
            with self.store.connect(write=True) as db:
                self.store.require_active(db, run_id)
                project = self.store.project(db, project_id)
                role = job["payload"].get("role", "design")
                visibility = role if kind == "chat" else "shared"
                self.store.emit(db, project_id, run_id, "agent.task.started", AGENTS[role],
                                {"summary": "Processing private request." if kind == "chat" else "Started layout and cost workflow."}, visibility)
            if kind == "chat":
                await self.chat(job)
                return
            if job["stage"] != "costing":
                await self.design(job, project)
            await self.cost(job, project)
        except (ModelFailure, DomainError, ValidationError) as error:
            if isinstance(error, DomainError) and error.status == 409:
                with self.store.connect() as db:
                    if db.execute("SELECT status FROM jobs WHERE id=?", (run_id,)).fetchone()[0] == "cancelled":
                        return
            self.fail(job, str(error) if not isinstance(error, ValidationError) else "A proposal failed schema validation.")
        except Exception:
            LOG.exception("Run %s failed", run_id)
            self.fail(job, "An unexpected server error interrupted the run.")

    def fail(self, job, message):
        project_id, run_id = job["project_id"], job["id"]
        role = job["payload"].get("role", "design")
        private = job["kind"] == "chat"
        with self.store.connect(write=True) as db:
            status = db.execute("SELECT status, stage FROM jobs WHERE id=?", (run_id,)).fetchone()
            if status["status"] != "running":
                return
            self.store.job_status(db, run_id, "failed", status["stage"], message)
            self.store.emit(db, project_id, run_id, "agent.task.failed", AGENTS[role],
                            {"summary": message, "role": role}, role if private else "shared")
            if not private:
                state = self.store.project(db, project_id)["state"]
                state["phase"] = "failed"
                self.snapshot(db, project_id, state, run_id)

    async def worker(self):
        while True:
            job = self.store.claim()
            if job is None:
                await asyncio.sleep(0.15)
                continue
            await self.execute(job)

    async def seed_demo(self, project_id):
        with self.store.connect(write=True) as db:
            for role, content in DEMO_INPUTS.items():
                self.queue_chat(db, project_id, role, content, f"seed:{role}")
        for _ in CLIENTS:
            job = self.store.claim()
            await self.execute(job)
        for role in CLIENTS:
            with self.store.connect(write=True) as db:
                draft = self.store.project(db, project_id)["state"]["drafts"][role]
                self.confirm_brief(db, project_id, role, draft["seq"], "approve")
        job = self.store.claim()
        await self.execute(job)
