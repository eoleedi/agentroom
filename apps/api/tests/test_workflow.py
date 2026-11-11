"""API acceptance tests for the two-client design review and its audit trail."""

import asyncio
from copy import deepcopy
import json
from time import monotonic, sleep

import httpx
import pytest
from fastapi.testclient import TestClient

from app import agents, geometry
from app.main import create_app
from app.store import DomainError, ROLES

PROJECT = "/api/projects/oak-residence"


@pytest.fixture
def api(tmp_path):
    with TestClient(create_app(db_path=tmp_path / "agentroom.sqlite3", mode="demo")) as client:
        yield client


def data(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def state(api, project=PROJECT):
    return data(api.get(project))["state"]


def wait_for(read, matches, timeout=4):
    deadline = monotonic() + timeout
    result = read()
    while not matches(result) and monotonic() < deadline:
        sleep(0.02)
        result = read()
    assert matches(result), result
    return result


def decision(api, proposal, role, action="approve", expected=None, note=""):
    return api.post(f"{PROJECT}/proposals/{proposal['id']}/decision", json={
        "role": role, "action": action, "note": note,
        "expected_version": proposal["version"] if expected is None else expected,
    })


def test_two_client_tradeoff_revises_only_island_and_all_roles_publish(api):
    initial = state(api)
    assert initial["phase"] == "negotiation"
    assert initial["approved_plan_version"] is None
    assert set(initial["confirmed_clients"]) == {"client_a", "client_b"}

    estimate = data(api.get(f"{PROJECT}/budgets/latest"))
    assert estimate["body"]["estimated_total"] == 1_620_000
    assert estimate["body"]["remaining"] == -120_000
    first_plan = data(api.get(f"{PROJECT}/artifacts/plan"))["body"]
    tradeoff = initial["negotiation"]
    assert tradeoff["required"] == ["client_a", "client_b"]
    assert tradeoff["savings"] == 140_000
    assert tradeoff["projected_total"] == 1_480_000

    checkpoint = data(api.get(f"{PROJECT}/events"))["next_seq"]
    data(decision(api, tradeoff, "budget"), 403)
    data(decision(api, tradeoff, "client_a", expected=tradeoff["version"] + 1), 409)
    data(decision(api, tradeoff, "client_a"))
    data(decision(api, tradeoff, "client_a"))
    assert state(api)["phase"] == "negotiation"
    assert state(api)["plan_version"] == 1

    data(decision(api, tradeoff, "client_b"))
    revised = wait_for(lambda: state(api), lambda room: room["phase"] == "review")
    assert revised["plan_version"] == 2
    assert revised["approved_plan_version"] is None

    new_plan = data(api.get(f"{PROJECT}/artifacts/plan?version=2"))
    assert new_plan["versions"] == [2, 1]
    assert new_plan["body"]["units"] == "mm"
    first_objects = {item["id"]: item for item in first_plan["objects"]}
    new_objects = {item["id"]: item for item in new_plan["body"]["objects"]}
    assert first_objects.keys() == new_objects.keys()
    assert {key for key in first_objects if first_objects[key] != new_objects[key]} == {"island_01"}
    assert first_objects["island_01"]["width_mm"] == 1800
    assert new_objects["island_01"]["width_mm"] == 1500
    assert new_objects["table_01"]["seats"] == 6

    estimate = data(api.get(f"{PROJECT}/budgets/latest"))
    assert not estimate["stale"]
    assert estimate["body"]["estimated_total"] == 1_480_000
    assert estimate["body"]["remaining"] == 20_000
    assert estimate["body"]["source_plan_version"] == 2
    assert {"artifact_id": "bom", "version": 2} in estimate["inputs"]
    assert {"artifact_id": "price", "version": 1} in estimate["inputs"]
    diff = "\n".join(data(api.get(f"{PROJECT}/artifacts/plan/diff?from=1&to=2"))["lines"])
    assert '-      "width_mm": 1800' in diff
    assert '+      "width_mm": 1500' in diff

    events = data(api.get(f"{PROJECT}/events", params={"after_seq": checkpoint}))["events"]
    assert all(event["seq"] > checkpoint for event in events)
    assert len({event["event_id"] for event in events}) == len(events)
    stale = next(event for event in events if event["type"] == "room.state" and event["payload"]["budget_stale"])
    assert stale["payload"]["estimate_version"] == 1
    assert stale["payload"]["plan_version"] == 2
    patch = next(event["payload"] for event in events if event["type"] == "canvas.patch.applied")
    assert patch["base_version"] == 1
    assert patch["operations"][0]["object_id"] == "island_01"
    assert patch["operations"][0]["changes"]["width_mm"] == 1500
    assert len(patch["operations"]) == 1
    assert sum(event["type"] == "approval.resolved" for event in events) == 2

    review = revised["review"]
    assert set(review["required"]) == set(ROLES)
    for role in ROLES[:-1]:
        data(decision(api, review, role))
    assert state(api)["phase"] == "review"
    data(api.get(f"{PROJECT}/artifacts/proposal"), 404)
    data(decision(api, review, ROLES[-1]))
    published = state(api)
    assert published["phase"] == "approved"
    assert published["approved_plan_version"] == 2
    deliverable = data(api.get(f"{PROJECT}/artifacts/proposal"))
    assert "NT$1,480,000" in deliverable["body"]
    assert deliverable["status"] == "approved"

    prior = data(api.get(PROJECT, params={"at": checkpoint}))["state"]
    assert prior == initial
    replay_plan = data(api.get(f"{PROJECT}/artifacts/plan", params={"at": checkpoint}))
    assert replay_plan["body"] == first_plan
    assert replay_plan["versions"] == [1]


def test_declined_tradeoff_keeps_original_plan_and_note_private(api):
    proposal = state(api)["negotiation"]
    note = "This approval comment belongs only to client B."
    data(decision(api, proposal, "client_b", action="reject", note=note))
    rejected = state(api)
    assert rejected["phase"] == "changes_requested"
    assert rejected["plan_version"] == 1
    assert rejected["approved_plan_version"] is None
    data(decision(api, proposal, "client_a"), 409)
    assert data(api.get(f"{PROJECT}/artifacts/plan"))["versions"] == [1]
    assert data(api.get(f"{PROJECT}/budgets/latest"))["body"]["estimated_total"] == 1_620_000
    events = data(api.get(f"{PROJECT}/events"))["events"]
    assert note not in json.dumps([event for event in events if event["visibility"] == "shared"])
    private_note = next(event for event in events if event["type"] == "approval.note")
    assert private_note["visibility"] == "client_b"
    assert private_note["payload"]["content"] == note


def test_chat_idempotency_and_separate_channels(api):
    project_id = data(api.post("/api/projects", json={"name": "Fresh room"}), 201)["id"]
    project = f"/api/projects/{project_id}"
    text = "Private preference: I want the large oak island."
    payload = {"content": text, "request_id": "request-001"}
    url = f"{project}/agents/client_a/messages"
    first = data(api.post(url, json=payload), 202)
    assert data(api.post(url, json=payload), 202) == first
    data(api.post(url, json={**payload, "content": "Different preference."}), 409)
    wait_for(lambda: data(api.get(f"{project}/runs/{first['run_id']}")), lambda run: run["status"] == "completed")

    private = data(api.get(f"{project}/messages?channel=client_a"))
    assert len(private) == 2
    assert all(event["visibility"] == "client_a" for event in private)
    assert private[0]["payload"]["content"] == text
    assert data(api.get(f"{project}/messages?channel=client_b")) == []
    assert data(api.get(f"{project}/messages?channel=shared")) == []
    info = data(api.get(project))
    draft_seq = info["drafts"]["client_a"]["seq"]
    assert info["state"]["brief_version"] == 0
    data(api.post(f"{project}/briefs/client_a/decision", json={"action": "approve", "expected_seq": draft_seq + 1}), 409)
    data(api.post(f"{project}/briefs/client_a/decision", json={"action": "approve", "expected_seq": draft_seq}))
    assert state(api, project)["confirmed_clients"] == ["client_a"]
    assert state(api, project)["phase"] == "requirements"
    data(api.get(f"{project}/artifacts/plan"), 404)


def test_geometry_rejects_crowding_boundary_and_missing_measurement(api):
    candidates = data(api.get(f"{PROJECT}/artifacts/candidate"))["body"]
    invalid, valid = candidates[0], candidates[-1]
    assert invalid["validation"]["status"] == "failed"
    aisle = next(check for check in invalid["validation"]["checks"] if check["rule_id"] == "aisle_clearance")
    assert (aisle["measured_mm"], aisle["required_mm"]) == (450, 900)
    assert valid["validation"]["status"] == "passed"

    plan = deepcopy(valid["plan"])
    item = next(obj for obj in plan["objects"] if obj["id"] == "island_01")
    item["center_mm"] = [100, 3800]
    issues = geometry.validate(plan)
    assert issues["status"] == "failed"
    assert {"room_boundary", "door_swing"}.issubset({issue["rule_id"] for issue in issues["checks"]})
    plan["space"]["measurement_status"] = "unknown"
    assert geometry.validate(plan)["status"] == "needs_measurement"

    verified = data(api.post(f"{PROJECT}/plans/{geometry.PLAN_ID}/validate"))
    assert verified["status"] == "passed"
    assert all(clearance["measured_mm"] >= clearance["required_mm"] for clearance in verified["clearances"])


def test_stale_workspace_write_rolls_back_and_private_acl_filters_rows(api):
    store = api.app.state.store
    with store.connect(write=True) as db:
        assert store.write(db, "oak-residence", "test-run", "style", {"label": "Natural oak"}, 2) == 3
    with pytest.raises(DomainError, match="version changed") as error:
        with store.connect(write=True) as db:
            store.write(db, "oak-residence", "stale-run", "style", {"label": "Stale"}, 2)
    assert error.value.status == 409
    with store.connect() as db:
        visible = store.events(db, "oak-residence", "client_a")
        assert not any(event["run_id"] == "stale-run" for event in visible)
        assert not any(event["visibility"] in {"client_b", "budget"} for event in visible)
        assert store.artifact(db, "oak-residence", "style", "client_a")["body"] == {"label": "Natural oak"}
        with pytest.raises(DomainError, match="Artifact not found"):
            store.artifact(db, "oak-residence", "price", "client_a")


def test_gmi_transport_reuses_exact_model_and_server_key_for_three_agents(monkeypatch):
    captured = []

    def handler(request):
        payload = json.loads(request.content)
        captured.append((request, payload))
        return httpx.Response(200, json={"choices": [{"message": {
            "content": '<think>hidden reasoning</think>\n```json\n{"reply": "A verified response."}\n```',
            "reasoning_content": "also hidden",
        }}]})

    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(agents.httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs))

    async def invoke():
        gmi = agents.GMI("test-server-key")
        return await asyncio.gather(*(
            gmi.structured(role, "Respond to the user.", {"thread": []}, agents.ChatReply)
            for role in ("requirement", "design", "budget")
        ))

    replies = asyncio.run(invoke())
    assert all(reply.reply == "A verified response." for reply in replies)
    assert len(captured) == 3
    assert {str(request.url) for request, _ in captured} == {"https://api.gmi-serving.com/v1/chat/completions"}
    assert {request.headers["authorization"] for request, _ in captured} == {"Bearer test-server-key"}
    assert {payload["model"] for _, payload in captured} == {"Qwen/Qwen3.8-27B"}
    assert len({payload["messages"][0]["content"] for _, payload in captured}) == 3


def test_live_mode_completes_workflow_with_one_env_key_and_scoped_model_context(monkeypatch, tmp_path):
    messages = {
        "client_a": "A private initial note about a large island.",
        "client_b": "A private initial note about circulation.",
        "design": "A private designer question about dimensions.",
        "budget": "A private budget question about pricing.",
    }
    captured = []

    def handler(request):
        payload = json.loads(request.content)
        system, context = (message["content"] for message in payload["messages"])
        schema = json.loads(system.rsplit("Schema: ", 1)[1])["title"]
        context = json.loads(context)
        captured.append((request.headers["authorization"], payload["model"], schema, context))
        if schema == "ChatReply":
            latest = context["latest_user_message"]
            output = {"reply": "I reviewed your private request."}
            if latest in (messages["client_a"], messages["client_b"]):
                large = latest == messages["client_a"]
                output["proposed_brief"] = {
                    "style": "Warm Japandi",
                    "island": "large" if large else "compact",
                    "priority": "prep_space" if large else "open_circulation",
                }
        elif schema == "Reconciliation":
            output = {"summary": "Compare both island sizes while retaining six seats.",
                      "style": "Warm Japandi", "priority": "balanced"}
        elif schema == "Layout":
            output = context["reference_placement"]
        else:
            assert schema == "Commentary"
            output = {"summary": "The catalog option retains the dining seats."}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(output)}}]})

    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(agents.httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs))
    monkeypatch.setenv("GMI_API_KEY", "one-key-for-all-model-calls")
    monkeypatch.setenv("GMI_MODEL", agents.MODEL)
    with TestClient(create_app(db_path=tmp_path / "live.sqlite3", mode="live")) as api:
        assert data(api.get("/api/health"))["gmi_configured"]
        assert data(api.get("/api/health"))["mode"] == "live"
        assert state(api)["phase"] == "requirements"
        for role in ROLES:
            run_id = data(api.post(f"{PROJECT}/agents/{role}/messages", json={
                "content": messages[role], "request_id": f"live-{role}",
            }), 202)["run_id"]
            wait_for(lambda: data(api.get(f"{PROJECT}/runs/{run_id}")), lambda run: run["status"] == "completed")
            if role in ("client_a", "client_b"):
                draft = data(api.get(PROJECT))["drafts"][role]
                data(api.post(f"{PROJECT}/briefs/{role}/decision", json={
                    "action": "approve", "expected_seq": draft["seq"],
                }))
        phase = wait_for(lambda: state(api), lambda room: room["phase"] == "negotiation")
        assert data(api.get(f"{PROJECT}/budgets/latest"))["body"]["estimated_total"] == 1_620_000
        for role in ("client_a", "client_b"):
            data(decision(api, phase["negotiation"], role))
        reviewed = wait_for(lambda: state(api), lambda room: room["phase"] == "review")
        assert reviewed["plan_version"] == 2
        assert data(api.get(f"{PROJECT}/budgets/latest"))["body"]["estimated_total"] == 1_480_000
        for role in ("client_a", "budget", "design"):
            run_id = data(api.post(f"{PROJECT}/agents/{role}/messages", json={
                "content": f"Explain the approved trade-off and current source versions for {role}.",
                "request_id": f"followup-{role}",
            }), 202)["run_id"]
            wait_for(lambda: data(api.get(f"{PROJECT}/runs/{run_id}")), lambda run: run["status"] == "completed")
        for role in ROLES:
            data(decision(api, reviewed["review"], role))
        assert state(api)["phase"] == "approved"
        public_messages = json.dumps(data(api.get(f"{PROJECT}/messages?channel=shared")))
        assert not any(message in public_messages for message in messages.values())

    assert {authorization for authorization, *_ in captured} == {"Bearer one-key-for-all-model-calls"}
    assert {model for _, model, *_ in captured} == {"Qwen/Qwen3.8-27B"}
    assert {schema for *_, schema, _ in captured} == {"ChatReply", "Reconciliation", "Layout", "Commentary"}
    for _, _, schema, context in captured:
        serialized = json.dumps(context)
        if schema == "ChatReply":
            private_texts = {message for message in messages.values() if message in serialized}
            if context["latest_user_message"] in messages.values():
                assert private_texts == {context["latest_user_message"]}
            else:
                assert len(private_texts) == 1
                assert context['approved_brief']['seating'] == 6
                assert context['negotiation']['status'] == 'approved'
                assert context['estimate']['estimated_total'] == 1_480_000
                if context['latest_user_message'].endswith('design.'):
                    assert context['previous_plan']['plan_version'] == 1
                    assert context['plan_changes'][0]['object_id'] == 'island_01'
                    assert context['validation']['status'] == 'passed'
                if context['latest_user_message'].endswith('budget.'):
                    assert context['previous_estimate']['estimated_total'] == 1_620_000
                    assert context['compact_option_estimate']['estimated_total'] == 1_480_000
        else:
            assert not any(message in serialized for message in messages.values())


def prepare_review(api):
    proposal = state(api)["negotiation"]
    for role in ("client_a", "client_b"):
        data(decision(api, proposal, role))
    return wait_for(lambda: state(api), lambda room: room["phase"] == "review")


def placement_patch(api, **changes):
    plan = data(api.get(f"{PROJECT}/artifacts/plan"))
    return {
        "base_version": plan["version"], "expected_state_hash": f"sha256:{plan['sha']}",
        "idempotency_key": "designer-edit-001", "reason": "Align the compact island with the kitchen run.",
        "operations": [{"op": "update", "object_id": "island_01", "changes": changes or {"center_mm": [2800, 2100]}}],
    }


def test_designer_patch_validates_recosts_and_supersedes_existing_approvals(api):
    reviewed = prepare_review(api)
    data(decision(api, reviewed["review"], "client_a"))
    payload = placement_patch(api)
    url = f"{PROJECT}/plans/{geometry.PLAN_ID}/patches"
    result = data(api.post(url, json=payload), 202)
    assert result["plan_version"] == 3
    assert data(api.post(url, json=payload), 202) == result
    data(api.post(url, json={**payload, "reason": "Another change"}), 409)
    data(api.post(url, json={**payload, "idempotency_key": "stale-edit-001"}), 409)
    final = wait_for(lambda: state(api), lambda room: room["phase"] == "review")
    assert final["plan_version"] == 3
    assert final["review"]["id"] != reviewed["review"]["id"]
    assert final["review"]["decisions"] == {}
    data(decision(api, reviewed["review"], "design"), 404)
    plan = data(api.get(f"{PROJECT}/artifacts/plan"))
    assert plan["versions"] == [3, 2, 1]
    assert next(obj for obj in plan["body"]["objects"] if obj["id"] == "island_01")["center_mm"] == [2800, 2100]
    estimate = data(api.get(f"{PROJECT}/budgets/latest"))
    assert estimate["body"]["source_plan_version"] == 3
    assert estimate["body"]["estimated_total"] == 1_480_000
    assert not estimate["stale"]
    events = data(api.get(f"{PROJECT}/events"))["events"]
    stale = next(event for event in events if event["run_id"] == result["run_id"] and event["type"] == "room.state")
    assert stale["payload"]["budget_stale"]
    assert stale["payload"]["review"]["status"] == "superseded"
    assert data(api.get(PROJECT, params={"at": stale["seq"]}))["state"]["budget_stale"]
    for role in ROLES:
        data(decision(api, final["review"], role))
    data(api.post(url, json={**placement_patch(api, center_mm=[2850, 2100]), "idempotency_key": "approved-edit-001"}), 409)
    assert data(api.get(f"{PROJECT}/artifacts/plan"))["versions"] == [3, 2, 1]


def test_invalid_patch_is_atomic_and_cannot_bypass_catalog_or_fixed_geometry(api):
    url = f"{PROJECT}/plans/{geometry.PLAN_ID}/patches"
    data(api.post(url, json=placement_patch(api)), 409)  # Clients must resolve their trade-off first.
    prepare_review(api)
    before = data(api.get(f"{PROJECT}/events"))["next_seq"]
    payload = placement_patch(api, center_mm=[100, 3800])
    error = data(api.post(url, json=payload), 422)
    assert "boundary" in error["detail"] and "door" in error["detail"]
    data(api.post(url, json={**payload, "expected_state_hash": "sha256:" + "0" * 64}), 409)
    for operation in (
        {"op": "update", "object_id": "kitchen_01", "changes": {"center_mm": [1, 1]}},
        {"op": "update", "object_id": "island_01", "changes": {"width_mm": 2000}},
        {"op": "update", "object_id": "island_01", "changes": {"catalog_id": "island-large"}},
        {"op": "remove", "object_id": "table_01"},
    ):
        data(api.post(url, json={**payload, "operations": [operation]}), 422)
    assert data(api.get(f"{PROJECT}/events"))["next_seq"] == before
    assert data(api.get(f"{PROJECT}/artifacts/plan"))["versions"] == [2, 1]


def test_versioned_price_catalog_is_the_cost_authority(api):
    reviewed = prepare_review(api)
    store = api.app.state.store
    with store.connect(write=True) as db:
        price = store.artifact(db, "oak-residence", "price", "budget")["body"]
        price["items"]["island-compact"]["price"] = 91000
        price["assumptions"]["tax_rate"] = "0.005"
        store.write(db, "oak-residence", "price-update", "price", price, 1)
    payload = placement_patch(api)
    data(api.post(f"{PROJECT}/plans/{geometry.PLAN_ID}/patches", json=payload), 202)
    wait_for(lambda: state(api), lambda room: room["phase"] == "review" and room["plan_version"] == 3)
    estimate = data(api.get(f"{PROJECT}/budgets/latest"))["body"]
    assert estimate["price_catalog_version"] == 2
    assert estimate["estimated_total"] == 1_488_405
    assert estimate["tax"] == 7405
    assert reviewed["estimate_version"] == 2


def test_cancel_during_model_call_prevents_late_plan_commit_and_retry_resumes(api, monkeypatch):
    workflow = api.app.state.workflow
    original = workflow.propose_layout

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        async def paused(*args, **kwargs):
            started.set()
            await release.wait()
            return await original(*args, **kwargs)

        monkeypatch.setattr(workflow, "propose_layout", paused)
        with workflow.store.connect(write=True) as db:
            run_id, _ = workflow.store.enqueue(db, "oak-residence", "cancel-test", "revision", {"compact": True})
        job = workflow.store.claim()
        running = asyncio.create_task(workflow.execute(job))
        await started.wait()
        data(api.post(f"{PROJECT}/runs/{run_id}/cancel"))
        checkpoint = data(api.get(f"{PROJECT}/events"))["next_seq"]
        release.set()
        await running
        assert data(api.get(f"{PROJECT}/runs/{run_id}"))["status"] == "cancelled"
        assert data(api.get(f"{PROJECT}/events"))["next_seq"] == checkpoint
        assert state(api)["plan_version"] == 1
        monkeypatch.setattr(workflow, "propose_layout", original)
        with workflow.store.connect(write=True) as db:
            assert workflow.request_alternative(db, "oak-residence", "design") == run_id
        await workflow.execute(workflow.store.claim())
        assert state(api)["phase"] == "review"
        assert state(api)["plan_version"] == 2

    asyncio.run(scenario())


def test_multiturn_brief_preserves_preferences_and_invalidates_old_confirmation(api):
    identifier = data(api.post('/api/projects', json={"name": "Multi-turn brief review"}), 201)["id"]
    base = f"/api/projects/{identifier}"

    def chat(role, content, key):
        run = data(api.post(f"{base}/agents/{role}/messages", json={"content": content, "request_id": key}), 202)
        wait_for(lambda: data(api.get(f"{base}/runs/{run['run_id']}")), lambda item: item['status'] == 'completed')
        return data(api.get(base))["drafts"][role]

    def approve(role, draft):
        data(api.post(f"{base}/briefs/{role}/decision", json={"action": "approve", "expected_seq": draft["seq"]}))

    first = chat('client_a', 'I prefer a large 1,800 mm oak island, Warm Japandi, and six seats.', 'multi-first')
    approve('client_a', first)
    replacement = chat('client_a', 'Keep the palette warm and simple. I like oak and low storage.', 'multi-second')
    assert replacement['brief']['island'] == 'large'
    assert replacement['brief']['priority'] == 'prep_space'
    assert 'client_a' not in state(api, base)['confirmed_clients']
    second = chat('client_b', 'Keep all six seats and use a compact island for open circulation.', 'multi-third')
    approve('client_b', second)
    assert state(api, base)['phase'] == 'requirements'
    data(api.get(f"{base}/artifacts/plan"), 404)
    approve('client_a', replacement)
    wait_for(lambda: state(api, base), lambda item: item['phase'] == 'negotiation')
    assert data(api.get(f"{base}/budgets/latest"))['body']['estimated_total'] == 1_620_000


def test_agent_room_tracks_real_handoffs_validation_and_recosting(api):
    prepare_review(api)
    events = data(api.get(f'{PROJECT}/events'))['events']
    shared = [event for event in events if event['visibility'] == 'shared']
    messages = [event for event in shared if event['type'] == 'agent.message']
    assert {'Requirement Agent', 'Budget Agent', 'Design Agent'} == {event['actor'] for event in messages}
    failed_check = next(event for event in shared if event['type'] == 'agent.tool_event' and event['payload'].get('status') == 'failed')
    explanation = next(event for event in messages if '450 mm' in event['payload']['content'])
    assert explanation['run_id'] == failed_check['run_id']
    assert explanation['seq'] > failed_check['seq']
    assert any('1,620,000' in event['payload']['content'] for event in messages)
    assert any('1,480,000' in event['payload']['content'] for event in messages)
    assert any('compact-island revision' in event['payload']['content'] for event in messages)
    assert all(event['payload'].get('recipient') for event in messages)
    assert not any(event['type'] == 'private.message.created' for event in shared)
    assert len({event['event_id'] for event in shared}) == len(shared)


def test_interrupted_demo_seed_resumes_after_project_creation(tmp_path):
    from app.agents import GMI
    from app.store import Store
    from app.workflow import Workflow

    path = tmp_path / 'interrupted.sqlite3'
    store = Store(path)
    store.initialize()
    workflow = Workflow(store, GMI(''), True)
    workflow.initialize_project('oak-residence', 'The Oak Residence', 1500000, seed_demo=True)
    with store.connect(write=True) as db:
        workflow.queue_chat(db, 'oak-residence', 'client_a', 'I want a large island.', 'seed:client_a')
    asyncio.run(workflow.execute(store.claim()))
    with TestClient(create_app(db_path=path, mode='demo')) as client:
        assert state(client)['phase'] == 'negotiation'
        assert state(client)['plan_version'] == 1
        assert len(data(client.get(f'{PROJECT}/messages?channel=client_a'))) == 2
    with TestClient(create_app(db_path=path, mode='demo')) as client:
        assert state(client)['plan_version'] == 1
        assert len(data(client.get(f'{PROJECT}/messages?channel=client_a'))) == 2


def test_pending_client_correction_blocks_reconciliation_before_reply(api):
    workflow = api.app.state.workflow
    store = workflow.store
    project_id = data(api.post('/api/projects', json={"name": "Pending correction"}), 201)['id']
    base = f'/api/projects/{project_id}'
    for role, text in (('client_a', 'I want a large island.'), ('client_b', 'I want a compact island.')):
        run = data(api.post(f'{base}/agents/{role}/messages', json={'content': text, 'request_id': f'pending-{role}'}), 202)
        wait_for(lambda: data(api.get(f"{base}/runs/{run['run_id']}")), lambda item: item['status'] == 'completed')
    drafts = data(api.get(base))['drafts']
    with store.connect(write=True) as db:
        workflow.confirm_brief(db, project_id, 'client_a', drafts['client_a']['seq'], 'approve')
        run_id = workflow.queue_chat(db, project_id, 'client_a', 'Actually, prioritize open circulation.', 'pending-correction')
        assert workflow.queue_chat(db, project_id, 'client_a', 'Actually, prioritize open circulation.', 'pending-correction') == run_id
        workflow.confirm_brief(db, project_id, 'client_b', drafts['client_b']['seq'], 'approve')
        current = store.project(db, project_id)['state']
        assert current['phase'] == 'requirements'
        assert current['confirmed_clients'] == ['client_b']
        assert not db.execute("SELECT 1 FROM jobs WHERE project_id=? AND kind='initial'", (project_id,)).fetchone()
