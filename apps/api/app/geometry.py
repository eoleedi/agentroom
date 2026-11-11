"""Authoritative millimeter geometry, proposal validation, and takeoffs."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from html import escape
from math import cos, radians, sin
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from shapely import affinity
from shapely.geometry import Polygon, box

ROOM_WIDTH, ROOM_DEPTH = 7600, 5000
CLEARANCE = 900
SEATING_CLEARANCE = 650
RULESET = "agentroom-demo-v1"
ROOM = {
    "id": "kitchen-dining",
    "polygon_mm": [[0, 0], [ROOM_WIDTH, 0], [ROOM_WIDTH, ROOM_DEPTH], [0, ROOM_DEPTH]],
    "measurement_source": "Synthetic room dimensions supplied with the demo",
    "measurement_status": "assumed_for_demo",
}
DOOR = {"id": "entry_door", "type": "door", "hinge_mm": [0, 3750], "width_mm": 900, "swing_deg": 90}
FEATURES = [DOOR, {"id": "north_window", "type": "window", "start_mm": [5800, 0], "end_mm": [7050, 0]}]
CATALOG = {
    "kitchen": {"label": "Kitchen cabinetry", "kind": "kitchen", "width": 5000, "depth": 700, "height": 920, "material": "warm-oak", "unit": "linear m", "price": 88000},
    "island-large": {"label": "Custom oak island", "kind": "island", "width": 1800, "depth": 900, "height": 900, "material": "warm-oak", "unit": "set", "price": 230000},
    "island-compact": {"label": "Modular oak island", "kind": "island", "width": 1500, "depth": 900, "height": 900, "material": "warm-oak", "unit": "set", "price": 90000},
    "table-six": {"label": "Six-seat dining set", "kind": "table", "width": 1800, "depth": 900, "height": 750, "material": "smoked-oak", "unit": "set", "price": 150000, "seats": 6, "operating_mm": SEATING_CLEARANCE},
    "sideboard": {"label": "Low storage", "kind": "storage", "width": 1800, "depth": 500, "height": 800, "material": "sage", "unit": "set", "price": 60000, "operating_mm": 500},
    "chair": {"label": "Dining chair", "kind": "chair", "width": 460, "depth": 470, "height": 800, "material": "smoked-oak", "unit": "set", "price": 0, "included_in": "table-six"},
}
CATALOG = {key: {**item, "dimensions_source": "demo furniture catalog"} for key, item in CATALOG.items()}
PRICING = {
    "currency": "TWD",
    "source": "Simulated prices for the AgentRoom demo",
    "effective_date": "2026-11-11",
    "fixed_work": 740000,
    "tax_rate": "0",
    "contingency": 0,
}
MATERIALS = {
    "warm-oak": {"label": "Warm oak", "hex": "#bb946c"},
    "smoked-oak": {"label": "Smoked oak", "hex": "#85634b"},
    "sage": {"label": "Sage green", "hex": "#929c85"},
    "plaster": {"label": "Lime plaster", "hex": "#ded7c7"},
    "stone": {"label": "Soft limestone", "hex": "#eae1cd"},
}
OBJECT_CATALOG = {
    "kitchen_01": ("kitchen",), "island_01": ("island-large", "island-compact"),
    "table_01": ("table-six",), "storage_01": ("sideboard",),
}
PLAN_ID = "kitchen-dining"


class Placement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    catalog_id: Literal["kitchen", "island-large", "island-compact", "table-six", "sideboard"]
    center_mm: tuple[Annotated[int, Field(ge=0, le=20000)], Annotated[int, Field(ge=0, le=20000)]]
    rotation_deg: Literal[0, 90, 180, 270] = 0


class Layout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kitchen_01: Placement
    island_01: Placement
    table_01: Placement
    storage_01: Placement

    @model_validator(mode="after")
    def validate_catalog(self):
        for identifier, allowed in OBJECT_CATALOG.items():
            if getattr(self, identifier).catalog_id not in allowed:
                raise ValueError(f"{identifier} requires a compatible catalog item")
        if self.kitchen_01 != Placement(catalog_id="kitchen", center_mm=(3150, 350)):
            raise ValueError("Fixed kitchen cabinetry cannot move")
        return self


class PlacementChanges(BaseModel):
    model_config = ConfigDict(extra="forbid")
    center_mm: tuple[Annotated[int, Field(ge=0, le=20000)], Annotated[int, Field(ge=0, le=20000)]] | None = None
    rotation_deg: Literal[0, 90, 180, 270] | None = None

    @model_validator(mode="after")
    def has_changes(self):
        if not self.model_dump(exclude_none=True):
            raise ValueError("Provide a position or rotation")
        return self


class PlacementUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["update"]
    object_id: Literal["island_01", "table_01", "storage_01"]
    changes: PlacementChanges


class CanvasPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_version: int = Field(gt=0)
    expected_state_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    idempotency_key: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,100}$")
    operations: list[PlacementUpdate] = Field(min_length=1, max_length=3)
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_objects(self):
        ids = [op.object_id for op in self.operations]
        if len(ids) != len(set(ids)):
            raise ValueError("Each object can only be updated once per patch")
        if not self.reason.strip():
            raise ValueError("A revision reason is required")
        return self


def apply_patch(previous: dict, patch: CanvasPatch) -> dict:
    placements = {obj["id"]: {key: obj[key] for key in ("catalog_id", "center_mm", "rotation_deg")}
                  for obj in previous["objects"]}
    for operation in patch.operations:
        placements[operation.object_id].update(operation.changes.model_dump(exclude_none=True))
    plan = build_plan(Layout.model_validate(placements), previous["plan_version"] + 1, previous["space"])
    plan["fixed_features"] = previous["fixed_features"]
    return plan


def default_layout(compact: bool = False, crowded: bool = False) -> Layout:
    return Layout(
        kitchen_01=Placement(catalog_id="kitchen", center_mm=(3150, 350)),
        island_01=Placement(catalog_id="island-compact" if compact else "island-large", center_mm=(2750, 2100)),
        table_01=Placement(catalog_id="table-six", center_mm=(5000 if crowded else 5750, 2100)),
        storage_01=Placement(catalog_id="sideboard", center_mm=(5900, 4550)),
    )


def build_plan(layout: Layout, version: int, space: dict | None = None) -> dict:
    objects = []
    for identifier in OBJECT_CATALOG:
        placement = getattr(layout, identifier)
        item = CATALOG[placement.catalog_id]
        objects.append({
            "id": identifier,
            "type": item["kind"],
            "label": item["label"],
            **placement.model_dump(mode="json"),
            "width_mm": item["width"],
            "depth_mm": item["depth"],
            "height_mm": item["height"],
            "material_id": item["material"],
            "seats": item.get("seats", 0),
            "source_requirement_ids": {"island": ["island"], "table": ["dining"], "storage": ["storage"]}.get(item["kind"], []),
        })
    return {
        "schema_version": "1.0", "plan_id": PLAN_ID, "plan_version": version,
        "units": "mm", "coordinate_system": {"origin": "room_local_top_left", "x_axis": "right", "y_axis": "down", "rotation_direction": "clockwise"},
        "space": space if space is not None else ROOM, "fixed_features": FEATURES, "objects": objects,
        "approval_status": "draft",
    }


def footprint(obj: dict, padding: int = 0, front: int = 0) -> Polygon:
    w, d = obj["width_mm"] / 2, obj["depth_mm"] / 2
    polygon = box(-w-padding, -d-padding-front, w+padding, d+padding)
    rotated = affinity.rotate(polygon, obj["rotation_deg"], origin=(0, 0))
    return affinity.translate(rotated, *obj["center_mm"])


def swing_polygon(door: dict) -> Polygon:
    x, y = door["hinge_mm"]
    radius = door["width_mm"]
    return Polygon([(x, y), *[
        (x + radius * cos(radians(angle)), y + radius * sin(radians(angle)))
        for angle in range(0, door["swing_deg"] + 1)
    ]])


def validate(plan: dict) -> dict:
    checks = []
    clearances = []
    space = plan["space"]
    status = space.get("measurement_status")
    report = {"plan_version": plan["plan_version"], "ruleset_version": RULESET, "checks": checks,
              "clearances": clearances, "unverified": ["site measurements", "building-code compliance"]}
    if status not in {"assumed_for_demo", "measured", "imported_verified"} or len(space.get("polygon_mm", [])) < 3:
        return {**report, "status": "needs_measurement"}
    room = Polygon(space["polygon_mm"])
    if not room.is_valid or room.area <= 0:
        return {**report, "status": "needs_measurement"}
    door = next((item for item in plan["fixed_features"] if item["type"] == "door"), None)
    swing = swing_polygon(door) if door else None
    shapes = {obj["id"]: footprint(obj) for obj in plan["objects"]}

    def add(rule: str, ids: list[str], message: str, **measurements):
        checks.append({"rule_id": rule, "object_ids": ids, "severity": "hard", "result": "fail",
                       "required_source": RULESET, "message": message, **measurements})

    for index, obj in enumerate(plan["objects"]):
        identifier = obj["id"]
        shape = shapes[identifier]
        if not room.covers(shape):
            add("room_boundary", [identifier], f"{obj['label']} extends beyond the room boundary.")
        if swing is not None and swing.intersection(shape).area > 0.01:
            add("door_swing", [door["id"], identifier], f"{obj['label']} blocks the entry door swing.")
        for other in plan["objects"][index+1:]:
            if shape.intersection(shapes[other["id"]]).area > 0.01:
                add("physical_collision", [identifier, other["id"]], f"{obj['label']} overlaps {other['label'].lower()}.")
        envelope = CATALOG[obj["catalog_id"]].get("operating_mm", 0)
        if envelope:
            swept = footprint(obj, padding=envelope) if obj["type"] == "table" else footprint(obj, front=envelope)
            if not room.covers(swept):
                add("operating_boundary", [identifier], f"{obj['label']} needs {envelope} mm of operating space.")
            if swing is not None and swing.intersection(swept).area > 0.01:
                add("operating_door_swing", [identifier, door["id"]], f"{obj['label']} operating area overlaps the entry door swing.")
            for other_id, other_shape in shapes.items():
                if other_id != identifier and swept.intersection(other_shape).area > 0.01:
                    add("operating_clearance", [identifier, other_id],
                        f"{obj['label']} operating area is obstructed.", required_mm=envelope)
    for first, second in (("island_01", "table_01"), ("kitchen_01", "island_01")):
        if first not in shapes or second not in shapes:
            continue
        measured = int(shapes[first].distance(shapes[second]))
        clearances.append({"object_ids": [first, second], "measured_mm": measured, "required_mm": CLEARANCE})
        if measured < CLEARANCE:
            add("aisle_clearance", [first, second], f"Aisle clearance is {measured:,} mm. The project minimum is {CLEARANCE:,} mm.",
                measured_mm=measured, required_mm=CLEARANCE)
    return {**report, "status": "failed" if checks else "passed"}


def plan_patch(previous: dict | None, plan: dict) -> list[dict]:
    before = {obj["id"]: obj for obj in previous["objects"]} if previous else {}
    after = {obj["id"]: obj for obj in plan["objects"]}
    operations = [{"op": "remove", "object_id": identifier} for identifier in before.keys() - after.keys()]
    for identifier, obj in after.items():
        if identifier not in before:
            operations.append({"op": "add", "object_id": identifier, "object": obj})
        elif before[identifier] != obj:
            operations.append({"op": "update", "object_id": identifier,
                               "changes": {key: value for key, value in obj.items() if before[identifier].get(key) != value}})
    return operations


def extract_bom(plan: dict) -> dict:
    items = []
    for obj in plan["objects"]:
        item = CATALOG[obj["catalog_id"]]
        unit = item["unit"]
        quantity = obj["width_mm"] / 1000 if unit == "linear m" else 1
        items.append({"object_id": obj["id"], "catalog_id": obj["catalog_id"], "label": item["label"],
                      "material_id": obj["material_id"], "quantity": quantity, "unit": unit,
                      "pricing_rule_id": "millimeters-to-linear-meters" if unit == "linear m" else "per-set"})
    return {"source_plan_id": plan["plan_id"], "source_plan_version": plan["plan_version"], "items": items}


def calculate_estimate(bom: dict, budget_limit: int, bom_version: int, catalog_version: int, price_catalog: dict | None = None) -> dict:
    pricing = price_catalog["assumptions"] if price_catalog is not None else PRICING
    prices = price_catalog["items"] if price_catalog is not None else CATALOG
    def amount(value: Decimal) -> int:
        return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    lines = [
        {**line, "unit_price": prices[line["catalog_id"]]["price"],
         "subtotal": amount(Decimal(str(line["quantity"])) * Decimal(str(prices[line["catalog_id"]]["price"])))}
        for line in bom["items"]
    ]
    material_total = sum(line["subtotal"] for line in lines)
    subtotal = material_total + pricing["fixed_work"]
    tax = amount(Decimal(subtotal) * Decimal(pricing["tax_rate"]))
    total = subtotal + tax + pricing["contingency"]
    return {
        "currency": "TWD", "estimated_total": total, "budget_limit": budget_limit, "remaining": budget_limit-total,
        "material_total": material_total, "fixed_work": pricing["fixed_work"], "tax": tax, "contingency": pricing["contingency"],
        "source_plan_version": bom["source_plan_version"], "bom_version": bom_version, "price_catalog_version": catalog_version,
        "assumptions": pricing, "items": lines, "calculated_at": datetime.now(timezone.utc).isoformat(),
    }


def render_svg(plan: dict) -> str:
    points = " ".join(f"{x},{y}" for x, y in plan["space"]["polygon_mm"])
    objects = []
    for obj in plan["objects"]:
        x, y = obj["center_mm"]
        w, d = obj["width_mm"], obj["depth_mm"]
        color = MATERIALS[obj["material_id"]]["hex"]
        label = escape(obj["label"])
        objects.append(
            f'<g transform="translate({x} {y}) rotate({obj["rotation_deg"]})">'
            f'<rect x="{-w/2}" y="{-d/2}" width="{w}" height="{d}" fill="{color}" stroke="#534539" stroke-width="16"/>'
            f'<text text-anchor="middle" dominant-baseline="central" font-family="sans-serif" font-size="120">{label}</text></g>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-200 -200 {ROOM_WIDTH+400} {ROOM_DEPTH+400}" role="img">'
        f'<title>Kitchen and dining floor plan, version {plan["plan_version"]}</title>'
        f'<polygon points="{points}" fill="#f5f0e6" stroke="#38342e" stroke-width="60"/>'
        f'{"".join(objects)}</svg>'
    )
