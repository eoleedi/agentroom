# AgentRoom Interior — Complete English Scenario Conversations

## 1. Purpose and Scenario

This document is a detailed English demo script for **The Oak Residence**, covering each participant's private conversation, the agents' shared collaboration, the island trade-off, and final approval.

**Record type:** This is a scripted walkthrough based on the implemented demo scenario, not a verbatim export of recorded live conversations. Live model wording can vary. Shared messages below describe the intended business handoffs; the application records the messages and tool events actually emitted during a run.

### Project facts

| Item | Scenario value |
| --- | --- |
| Space | Kitchen and dining area in a simulated residential project |
| Modeled room | 7,600 × 5,000 mm |
| Budget limit | NT$1,500,000 |
| Style direction | Warm Japandi |
| Dining capacity | Six seats, retained in both versions |
| Initial island | 1,800 × 900 mm custom oak island |
| Revised island | 1,500 × 900 mm modular oak island |
| Dining table | 1,800 × 900 mm six-seat dining set |
| Initial validated estimate | NT$1,620,000 — NT$120,000 over budget |
| Revised estimate | NT$1,480,000 — NT$20,000 remaining |
| Cost reduction | NT$140,000 |
| Demo aisle rule | 900 mm minimum for the modeled aisle checks |
| Dining operating envelope | 650 mm around the table under the demo ruleset |

Room dimensions, furniture, prices, and clearance rules are simulated demo inputs. Passing these modeled checks does not establish building-code compliance or construction readiness.

### Participants and private channels

| Person | Role | Assigned agent | Private channel |
| --- | --- | --- | --- |
| Alex Morgan | Client A | Requirement Agent | `client_a` |
| Maya Chen | Client B | Requirement Agent | `client_b` |
| Jordan Lee | Budget designer | Budget Agent | `budget` |
| Sam Rivera | Space designer | Design Agent | `design` |

There are **three specialized agent types**. Alex and Maya have separate private conversations with the Requirement Agent. The orchestrator routes work in the background and is not a fourth conversational agent.

## 2. How to Use This Script

- **Human message:** Text a participant can enter into their private chat.
- **Agent response:** Suggested English wording for the demo; actual model responses may differ.
- **UI action:** A button or review action, not a chat message. Conversational agreement alone does not execute an approval.
- **Shared agent message:** A public business handoff, separate from private conversation history.
- **Tool/system event:** A deterministic operation or recorded state change, not spoken dialogue.

For a from-the-beginning walkthrough, create a new project. The seeded offline demo starts at the island decision, so its initial brief collection is already complete. In Live mode, enter the initial messages and confirm both generated briefs before expecting layout generation.

In the current MVP, revision is triggered by the island trade-off approval workflow. Follow-up questions in private chats explain the project but do not independently edit a plan. Placement edits use the floor-plan editor and its validation flow.

---

## 3. Act One — Alex Defines the Main Requirements

**Channel:** Alex Morgan ↔ Requirement Agent — private.

### Turn A1 — Initial request

**Alex Morgan:**
> I want a large 1,800 mm oak island for prep, with a warm Japandi feel and a dining table for six.

**Requirement Agent:**
> I understand that you want warm oak, a calm Japandi atmosphere, a generous preparation surface, and dining for six. Before I finalize the brief, which matters more: keeping the island exactly 1,800 mm wide, or preserving six dining seats and a workable circulation route? Is the island size a firm requirement or a preference?

### Turn A2 — Priority clarification

**Alex Morgan:**
> Six dining seats are essential. A large island is my preference because I cook frequently and want room for preparation. I would consider a smaller island if we can keep the dining function and understand the trade-off first.

**Requirement Agent:**
> I will treat the six dining seats as essential and the large preparation island as your preferred starting point. I will not treat permission to consider another option as approval to apply it. Any change in island size will come back for an explicit decision.

### Turn A3 — Storage and style

**Alex Morgan:**
> Keep the palette warm and simple. I like oak, muted green, and low storage rather than tall cabinets around the dining area.

**Requirement Agent:**
> The supported direction is Warm Japandi, with warm oak and a low sideboard. Your preferred starting option is the large island, with preparation space as the main preference. Please review the structured brief before it is shared with the design workflow.

**UI action — Alex:**
> Select **Confirm** on Alex's brief card after checking the proposed fields.

**Result:** Alex's confirmed brief is saved. Alex's confirmation alone does not start the combined design workflow; Maya's brief is also required.

## 4. Act Two — Maya Defines Circulation Priorities

**Channel:** Maya Chen ↔ Requirement Agent — private.

### Turn M1 — Initial request

**Maya Chen:**
> Keep all six seats. I prefer a compact island with open circulation, warm oak, and low storage.

**Requirement Agent:**
> You want to retain six seats while keeping the kitchen and dining area easy to move through. Is a compact island your preferred option, rather than removing the island entirely? Which should take priority if the initial arrangement feels crowded?

### Turn M2 — Priority clarification

**Maya Chen:**
> I still want an island, but I prefer a compact one. Open circulation matters more to me than having the largest possible worktop. Please keep the six-seat table and the low storage.

**Requirement Agent:**
> I will record a compact-island preference, open circulation as your main priority, six dining seats, and a low sideboard. Your style direction is also Warm Japandi. Please confirm that this accurately represents your preferences.

**UI action — Maya:**
> Select **Confirm** on Maya's brief card after checking the proposed fields.

### Shared reconciliation

**Requirement Agent → Design Agent — shared:**
> Both clients have confirmed their briefs. They agree on Warm Japandi, six dining seats, and low storage. Alex prefers a large preparation island; Maya prefers a compact island and wider circulation. Start with the large-island baseline, validate the layout, and make any trade-off explicit before changing the agreed direction.

**Tool/system events:**
1. Save the combined approved design brief and update the style board.
2. Record `requirement.approved` and the public design handoff.
3. Design Agent reads the approved brief, measured-room fixture, and furniture catalog.

---

## 5. Act Three — Sam Reviews the Spatial Constraints

**Channel:** Sam Rivera ↔ Design Agent — private.

### Turn S1 — Validation scope

**Sam Rivera:**
> Before we review the first layout, explain which dimensions and constraints you will use. Keep the fixed kitchen run, retain the six-seat table, and use the catalog rather than inventing furniture sizes.

**Design Agent:**
> I will use the simulated 7,600 × 5,000 mm room and the supplied fixed features. The six-seat dining set is 1,800 × 900 mm. The large island is 1,800 × 900 mm; the compact option is 1,500 × 900 mm. I will check room containment, furniture overlaps, the entry-door swing, furniture operating envelopes, and the selected 900 mm demo aisle rules. The dining table has a 650 mm operating envelope. These are modeled demo checks, not a complete construction or legal review.

### Turn S2 — Localized revision requirement

**Sam Rivera:**
> If you need to revise the layout, keep stable object IDs and preserve unaffected placements. I want to see which object changed and why.

**Design Agent:**
> The plan will retain stable IDs for the kitchen, island, table, and storage. A revision will produce a new immutable plan version and a canvas patch identifying changed objects. The BOM, validation report, and estimate must reference the corresponding versions. Any revised package will require a new review.

### First candidate: deliberately invalid offline-demo placement

**Tool/system event — Geometry Validator:**
> The first offline-demo candidate places the dining table too close to the island. The island-to-table clearance is 450 mm against the demo rule of 900 mm. The candidate fails and must not be presented as a validated plan.

**Design Agent → shared collaboration:**
> The first candidate does not satisfy the modeled clearance checks. I will adjust the affected placement, rerun validation, and publish a draft only after those checks pass.

**Tool/system event — correction:**
> The offline demo moves the table to the reference placement and reruns the validator. The corrected candidate passes the modeled checks and becomes floor plan v1.

In Live mode, the model may return a passing candidate immediately or need feedback. A failed first attempt is guaranteed by the offline fixture, not by a live model call.

### Turn S3 — Inspect the published draft

**Sam Rivera:**
> Explain what is available for review now, and distinguish the draft from a fully approved design.

**Design Agent:**
> Floor plan v1 has passed the modeled geometry checks and is available as a draft with its SVG preview, validation report, and plan-linked BOM. It is not a fully approved design package. The budget still needs to be calculated, and the participants must review any resulting trade-offs before final approval.

**Design Agent → Budget Agent — shared:**
> Validated floor plan v1 is ready. Please price the matching bill of materials using the versioned demo price catalog.

---

## 6. Act Four — Jordan Explains the Budget Conflict

**Channel:** Jordan Lee ↔ Budget Agent — private.

### Turn J1 — Request the pricing basis

**Jordan Lee:**
> Explain the v1 estimate using the matching BOM and the stored price catalog. Show the cost basis and the difference from the NT$1,500,000 budget. Do not invent supplier prices or discounts.

**Budget Agent:**
> The deterministic v1 estimate is NT$1,620,000, which exceeds the NT$1,500,000 budget by NT$120,000. The estimate is based on the versioned BOM, catalog prices, and the project's simulated fixed-work assumptions. It is a demo estimate rather than a supplier quotation.

### Deterministic estimate detail — v1

| Cost item | Quantity | Unit price | Amount |
| --- | ---: | ---: | ---: |
| Kitchen cabinetry | 5 linear meters | NT$88,000 / linear meter | NT$440,000 |
| Custom oak island | 1 set | NT$230,000 / set | NT$230,000 |
| Six-seat dining set | 1 set | NT$150,000 / set | NT$150,000 |
| Low storage | 1 set | NT$60,000 / set | NT$60,000 |
| Catalog items subtotal | | | **NT$880,000** |
| Simulated fixed work | | | NT$740,000 |
| Demo tax and contingency | | | NT$0 |
| Estimated total | | | **NT$1,620,000** |
| Amount over project budget | | | **NT$120,000** |

### Turn J2 — Ask for a supported alternative

**Jordan Lee:**
> What catalog-backed option reduces the estimate while preserving all six dining seats? Explain the savings without assuming the clients have accepted the change.

**Budget Agent:**
> The compact modular oak island is the supported alternative. Its catalog cost is NT$90,000 instead of NT$230,000 for the custom island, a reduction of NT$140,000. Under the same assumptions, the projected total is NT$1,480,000, leaving NT$20,000 within the budget. This is a proposed substitution. The clients must approve the island trade-off, and the revised plan must still be validated and priced.

**Budget Agent → Requirement and Design Agents — shared:**
> The current estimate is NT$1,620,000, or NT$120,000 over budget. Replacing the large custom island with the compact modular option would reduce the modeled estimate by NT$140,000 and preserve the six-seat table. Please obtain the clients' explicit decision before applying this change.

**Requirement Agent → Design Agent — shared:**
> The compact-island proposal is awaiting both clients' approval. Keep the current plan unchanged until the required decisions are complete.

---

## 7. Act Five — Both Clients Review the Trade-Off

### Alex's private discussion

**Alex Morgan:**
> I am willing to reduce the island size if we keep all six dining seats. What exactly would I be giving up, and what would stay the same?

**Requirement Agent:**
> The proposed island changes from 1,800 mm to 1,500 mm wide, a reduction of 300 mm; its catalog depth remains 900 mm. The proposal retains the six-seat dining table and the warm-oak direction. The smaller worktop is the functional trade-off. The budget proposal projects a NT$140,000 reduction, subject to the revised plan and its matching estimate. Please record your decision in the approval inbox; this conversation alone does not apply the change.

**Alex Morgan:**
> That trade-off is acceptable to me. Six seats remain essential, and I am comfortable with the smaller preparation surface.

**UI action — Alex:**
> Open **Approvals → Island trade-off** and select **Approve** as Alex Morgan.

**Tool/system event:**
> Record Alex's approval. Do not revise the plan yet: Maya's decision is still pending.

### Maya's private discussion

**Maya Chen:**
> Please confirm that this proposal keeps the six-seat dining table. I support a compact island, but I do not want the dining function reduced to meet the budget.

**Requirement Agent:**
> The island trade-off explicitly preserves the six-seat table. It substitutes the 1,500 mm modular island for the 1,800 mm custom island. The revised design must still pass the modeled geometry checks. Your approval is required before the revision workflow starts.

**Maya Chen:**
> I agree with the compact island while retaining all six seats and the low storage.

**UI action — Maya:**
> Select **Approve** as Maya Chen on the same island trade-off proposal.

**Tool/system event:**
> Both required client decisions are approved. Queue the compact-island revision. Client acceptance authorizes preparation of a new draft; it is not final approval of that draft or its estimate.

---

## 8. Act Six — Revise, Validate, and Recalculate

**Requirement Agent → Design Agent — shared:**
> Both clients have approved the compact-island trade-off. Prepare the revised layout with six dining seats retained and preserve unaffected objects.

### Sam's private follow-up

**Sam Rivera:**
> Explain the difference between v1 and v2. Did the kitchen run, dining table, or storage move?

**Design Agent:**
> In the deterministic demo revision, only `island_01` changes: its catalog option becomes the compact modular island and its width changes from 1,800 to 1,500 mm. Its center and rotation remain unchanged. The kitchen, six-seat table, and storage retain their IDs and placements. The revised plan has its own validation report, SVG preview, and BOM.

**Tool/system events:**
1. Apply the island update as a new draft version, preserving v1.
2. Validate v2 against the modeled rules.
3. Commit floor plan v2, validation report, preview, and BOM.
4. Emit the canvas patch so the view highlights `island_01`.
5. Mark the previous estimate **stale** until recalculation finishes.

**Design Agent → Budget Agent — shared:**
> Validated floor plan v2 and its matching BOM are ready. Recalculate using the versioned price catalog and explain the change from v1.

### Jordan's private follow-up

**Jordan Lee:**
> Confirm that the new estimate uses BOM v2, not the previous quantities. Explain the exact change and the remaining budget.

**Budget Agent:**
> The revised estimate references the updated BOM and source plan v2. The island cost decreases from NT$230,000 to NT$90,000, reducing the estimate by NT$140,000. The other modeled cost items and assumptions stay the same. The new total is NT$1,480,000, with NT$20,000 remaining against the NT$1,500,000 cap.

### Deterministic estimate comparison

| Item | v1 | v2 | Change |
| --- | ---: | ---: | ---: |
| Kitchen cabinetry | NT$440,000 | NT$440,000 | NT$0 |
| Island | NT$230,000 | NT$90,000 | −NT$140,000 |
| Six-seat dining set | NT$150,000 | NT$150,000 | NT$0 |
| Low storage | NT$60,000 | NT$60,000 | NT$0 |
| Simulated fixed work | NT$740,000 | NT$740,000 | NT$0 |
| Demo tax and contingency | NT$0 | NT$0 | NT$0 |
| **Estimated total** | **NT$1,620,000** | **NT$1,480,000** | **−NT$140,000** |
| **Budget balance** | **NT$120,000 over** | **NT$20,000 remaining** | |

**Budget Agent → Requirement and Design Agents — shared:**
> The updated estimate is NT$1,480,000, with NT$20,000 remaining. The estimate matches the revised BOM. Please review the v2 design package and record the required approvals.

---

## 9. Act Seven — Final Review by All Four Participants

The final package requires **Alex, Maya, Jordan, and Sam**. Each approval applies to the current versioned package. A conversational “yes” is not a substitute for the corresponding UI action.

### Alex reviews the functional compromise

**Alex Morgan → Requirement Agent — private:**
> My final priorities are six dining seats, warm oak, and a usable preparation island. I accept the smaller island as the agreed budget compromise.

**Requirement Agent:**
> Those are the priorities reflected in the revised package. Review the latest plan and estimate, then record your approval on the Design package card. The design and budget professionals must also record their decisions.

**UI action — Alex:** Approve **Design package** as Alex Morgan.

### Maya reviews circulation and dining

**Maya Chen → Requirement Agent — private:**
> The compact island matches my preference. I want to confirm the six-seat table and low storage remain in the package.

**Requirement Agent:**
> The revised package retains the six-seat table and low storage. Review the plan and its modeled clearance results, then record your decision on the Design package card.

**UI action — Maya:** Approve **Design package** as Maya Chen.

### Jordan reviews the estimate

**Jordan Lee → Budget Agent — private:**
> I have reviewed the NT$1,480,000 estimate, the matching BOM, the price-catalog version, and the simulated assumptions. Confirm that the estimate is current rather than stale.

**Budget Agent:**
> After recalculation completes, the estimate is current for the revised plan and BOM. It leaves NT$20,000 within the project budget. Record your decision after reviewing the source versions and assumptions; this remains a demo estimate, not a supplier commitment.

**UI action — Jordan:** Approve **Design package** as Jordan Lee.

### Sam reviews the geometry

**Sam Rivera → Design Agent — private:**
> I have checked the latest plan, the island-only revision, and the modeled validation report. Explain any checks that remain outside this review.

**Design Agent:**
> The validator covers the modeled boundary, overlap, door-swing, operating-envelope, and selected aisle checks. Site measurements and building-code compliance remain unverified. The package does not claim to be a complete construction drawing or professional regulatory assessment.

**UI action — Sam:** Approve **Design package** as Sam Rivera.

### Publication

**Tool/system event:**
> Once all four required approvals are recorded, mark the proposal approved, set the approved-plan pointer to v2, and write the approved proposal artifact with references to the plan and estimate versions.

**Presenter narration — not an additional agent message:**
> The team reached a shared decision without losing the requirement history, design revision, or cost basis. The final package retains six seats, uses the compact island, and has a modeled estimate of NT$1,480,000. Every handoff, file version, and approval remains traceable.

---

## 10. Optional Branch — A Client Declines the Compact Island

Use this branch instead of approving the island trade-off if demonstrating human control.

**Alex Morgan → Requirement Agent — private:**
> I do not accept the smaller preparation surface. Please keep the large island for now and explain how we can review another option.

**Requirement Agent:**
> Declining the proposal will preserve the current plan. The team must review another option rather than silently applying the compact island. Record your decision in the approval inbox so the workflow has an explicit outcome.

**UI action — Alex:** Select **Decline** on the Island trade-off card.

**Tool/system event:**
> Mark the proposal declined and move the project to changes requested. Keep floor plan v1 and its NT$1,620,000 estimate. Do not apply the compact-island revision.

**Sam Rivera → Design Agent — private:**
> The compact island was declined. Keep that rejection visible and do not describe a smaller island as approved.

**Design Agent:**
> The rejected change remains in the recorded history. A further proposal must be reviewed on its own merits. The current MVP's bounded catalog does not guarantee an alternative that satisfies both the large-island preference and the budget cap.

**UI action — Sam:** Use **Approvals → Request alternative** if another proposal is needed. This starts the implemented alternative workflow; it does not guarantee budget feasibility or introduce unsupported products.

## 11. Optional Branch — Edit a Draft Placement

This branch is available after a draft reaches review or is returned for changes, before final publication.

**Sam Rivera → Design Agent — private:**
> I want to move the compact island slightly to the right. How should I submit that change while keeping the plan and estimate synchronized?

**Design Agent:**
> Select the island on the latest draft and use the placement editor. Enter the new center coordinates and a revision reason, then choose Validate & save draft. The backend checks the base version and hash, validates the proposed geometry, and publishes a new plan and BOM only if the change passes. Costing then recalculates the estimate and a fresh approval request replaces the prior review.

**UI action — Sam:**
1. Select the compact island on the latest draft.
2. Change its X coordinate from `2750` to `2800` mm, retaining Y `2100` mm and rotation `0°`.
3. Enter the reason: **Align the compact island with the kitchen run.**
4. Select **Validate & save draft**.

**Tool/system event:**
> If the candidate passes, save the next plan version, mark the old estimate stale, recalculate from the new BOM, and request fresh approvals. A position-only change does not change catalog costs under the current pricing rules. Invalid geometry or a stale version is rejected without committing a new plan.

## 12. Suggested Closing Questions for Live Interaction

These are follow-up prompts a person can type after the walkthrough. They are questions, not automatic workflow commands.

### Alex — Requirement Agent

> Which of my requirements are essential, and which are preferences?

> Explain the island trade-off in plain English without changing the plan.

### Maya — Requirement Agent

> What should I inspect in the plan before approving the dining arrangement?

> Explain the difference between agreeing to explore an option and approving the final package.

### Jordan — Budget Agent

> Explain the source versions behind the current estimate and whether it is stale.

> Which cost line changed between v1 and v2, and what assumptions stayed the same?

### Sam — Design Agent

> Explain the current island dimensions, the dining operating envelope, and the demo aisle rules.

> Which constraints are modeled by the validator, and which still need a professional site review?

## 13. Presenter Checklist

- Use a fresh project for the initial requirement conversation, or the seeded demo for the island-decision starting point.
- Confirm the actual structured brief fields before approving; live wording and extracted preferences can vary.
- Show private conversations separately from shared agent handoffs.
- Show validation and costing as tool events, not invented dialogue.
- Use approval buttons to trigger decisions and revisions.
- Compare v1 and v2 in the floor plan and workspace.
- Show the NT$140,000 reduction and the retained six-seat requirement.
- Use recorded-event replay to explain the actual run history.
- Keep the distinction between a validated draft, a current estimate, and a fully approved package visible.
