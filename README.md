# AgentRoom Interior

AgentRoom Interior is a local collaboration workspace for a residential kitchen and dining project. Two clients share their preferences with the Requirement Agent in separate conversations. The Design Agent proposes layouts, and the Budget Agent explains estimates calculated from the layout’s bill of materials. Participants review the same plan, files, and decisions.

For the full English walkthrough, including each participant's private conversation, public agent handoffs, and approval actions, see [AgentRoom_Demo_Conversation_EN.md](AgentRoom_Demo_Conversation_EN.md). This is a scenario script, not a verbatim live transcript.

## Start locally

Install [uv](https://docs.astral.sh/uv/), Python 3.11 or later, and Node.js 22.12 or later. Run these commands from the project root.

1. Create a local configuration if you do not already have one.

   ```sh
   test -f .env || cp .env.example .env
   ```

2. Start the API in one terminal.

   ```sh
   cd apps/api
   uv sync
   uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

3. Start the web app in another terminal.

   ```sh
   cd apps/web
   npm install
   npm run dev -- --host 127.0.0.1
   ```

4. Open [AgentRoom](http://127.0.0.1:5173). The web app proxies `/api` requests to port 8000. The API schema is available at [FastAPI Docs](http://127.0.0.1:8000/docs).

Demo and live projects use separate SQLite databases under `.data/` by default. Set `AGENTROOM_DB` to use another local database. Run one API process per database.

## Offline demo

Set `AGENTROOM_MODE=demo` in the root `.env`. Demo mode uses deterministic fixtures and requires no API key. On first startup, it seeds **The Oak Residence** at the island decision.

1. Open the overview. Alex prefers a large prep island. Maya prefers wider circulation. Both confirmed briefs keep six dining seats.
2. Inspect the geometry check in the agent room. The first candidate has a 450 mm aisle against the demo’s 900 mm target. The corrected layout becomes plan v1, estimated at NT$1,620,000 against a NT$1,500,000 project budget.
3. Open **Approvals**. Approve the compact island as both Alex and Maya. This runs the revision, validation, BOM, and costing workflow. Plan v2 keeps six seats and replaces the 1,800 mm custom island with a 1,500 mm modular model. The estimate becomes NT$1,480,000.
4. Switch plan versions or open the workspace to compare artifacts and inspect the cost delta. Review the design package as both clients and both designers to publish the approved proposal.
5. Open the timeline and replay the saved events. Replay reads the recorded state and does not call a model.

### Edit a draft floor plan

After the compact-island revision reaches **Ready for review**, select the island, dining table, or storage on the latest floor plan. The placement editor below the canvas accepts center coordinates in millimeters, a quarter-turn rotation, and a revision reason. For example, change the compact island's X coordinate from `2750` to `2800` and select **Validate & save draft**.

The API checks the base version and SHA-256, validates room boundaries, door swing, operating envelopes, and demo aisle clearances, then atomically publishes a new plan, SVG, validation report, and BOM. Invalid placements leave the workspace untouched. A successful edit marks the previous estimate stale, queues costing from the versioned price catalog, and creates a fresh approval request. Previous approvals are not carried into the revised package. Catalog dimensions and the fixed kitchen run remain controlled by the existing brief/catalog workflow.

Editing is available for drafts in review or returned for changes. Complete the client island trade-off first. Published packages and historical/replay views are read-only. During a design workflow, **Cancel run** stops further commits; **Approvals → Request alternative** resumes a cancelled or failed run from its saved stage, including costing when the plan was already committed.

The controlled endpoint is `POST /api/projects/{id}/plans/kitchen-dining/patches`. It requires `base_version`, `expected_state_hash` (`sha256:` plus the artifact hash), `idempotency_key`, `reason`, and one to three `update` operations for movable objects. Each operation accepts `center_mm` and/or `rotation_deg`. Reusing a key with the same payload returns the original run; changing the payload under that key returns `409`.

The price catalog, measured floor plan, and spatial rules are demo inputs. Estimated prices and modeled clearances are for the walkthrough.

## Live GMI Cloud

Edit the same root `.env` and restart the API.

```dotenv
AGENTROOM_MODE=live
GMI_API_KEY=your_gmi_cloud_api_key
GMI_MODEL=Qwen/Qwen3.8-27B
GMI_BASE_URL=https://api.gmi-serving.com/v1
```

All three agents use the same server-side `GMI_API_KEY` and the Qwen 3.8 27B model. Each agent has its own prompt and schema. The browser receives no provider key, and participants need no separate tokens. Obtain the key from [GMI Cloud](https://console.gmicloud.ai/).

Start by sending a preference message from each client card. Review and confirm each structured brief. Once both are confirmed, the agents reconcile priorities, propose a layout, validate the geometry, and price the resulting BOM. The approval inbox shows the next action. Budget and design conversations accept follow-up questions at any stage. Live projects start with the synthetic room and catalog so that the model has known dimensions and product choices. Model output can vary. A layout enters review only after validation and costing.

Before both briefs are confirmed, the canvas shows the room outline with an **Awaiting briefs** label. This is a reference, not a generated furniture layout. The confirmation counter and **Open requirement chats** button show the next step. After confirmation, the agents generate and validate the furniture layout; approved geometry then appears on the canvas. A failed run offers retry under **Approvals**.

The **Agent room** displays persisted public handoffs from Requirement, Design, and Budget, with event sequence numbers and run identifiers. Switch to **Messages** for discussion or **Tools** for validation, task status, and file reads/writes. Private participant messages remain in their individual cards. Live follow-up questions receive the applicable shared proposals and versioned design/budget facts; they do not perform an approval or change the plan by themselves.

This MVP uses a trusted local participant overview. Individual conversations are stored separately from shared agent handoffs and omitted from the shared activity feed. Anyone with access to the local overview can act as any participant. Keep the development server bound to localhost. Live mode sends the active thread and its scoped context to GMI Cloud for inference.

## How the workspace works

| Component | Implementation |
| --- | --- |
| Dashboard | React, TypeScript, and Vite. SVG floor plans use canonical geometry in millimeters, with version-checked placement editing. |
| API and jobs | FastAPI, Pydantic, and a SQLite-backed single-worker queue. The workflow records stages and supports retrying a failed design run. |
| Agent model | GMI Cloud chat completions with validated structured responses in live mode. Deterministic responses in demo mode. |
| Spatial checks | Shapely checks room containment, physical overlaps, door swing, furniture operation zones, and selected aisle clearances. |
| Costing | A catalog-backed BOM and deterministic arithmetic use the persisted price-catalog version to produce a TWD estimate. An estimate becomes stale when its plan changes. |
| Shared workspace | Immutable artifact versions, dependency references, hashes, text diffs, and read/write events. |
| Replay | Sequence-numbered events and historical state support play, pause, and inspection without model calls. |

The hackathon MVP covers a single kitchen and dining layout with a bounded furniture catalog. Production identity management, measured-room import, general pathfinding, a 3D pipeline, construction review, and research benchmarks are outside this implementation.

## Verification

```sh
cd apps/api
uv run pytest
```

```sh
cd apps/web
npm run build
```

Check the API mode and configured model without disclosing the key.

```sh
curl http://127.0.0.1:8000/api/health
```
