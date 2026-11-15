"""Pure-Python validator for 4_Horses_Environment_v02/workshop_chain.json (F1)."""

from __future__ import annotations

from collections import deque
import copy
from typing import Any

EXPECTED_STAGE_IDS = frozenset(
    {
        "S0_INBOUND",
        "S1_PREP",
        "S2_PICK",
        "S3A_PACK_MANUAL",
        "S3B_PACK_ROBOT",
        "S3C_ROBOT_ASSIST",
        "S4_QC",
        "S5A_GOOD",
        "S5B_ESCAPED",
        "S5C_REWORK_R",
        "S5D_SCRAP",
        "S5E_BREAK",
    }
)

TERMINAL_STAGE_IDS = frozenset({"S5A_GOOD", "S5B_ESCAPED", "S5D_SCRAP"})
FLOW_STAGE_IDS = EXPECTED_STAGE_IDS - {"S5E_BREAK"}

REQUIRED_STAGE_KEYS = (
    "id",
    "name",
    "zone_id",
    "zone_bounds_gltf",
    "equipment_nodes",
    "work_anchor",
    "order_anchor",
    "character_roles",
    "operation_clips",
    "transfer_clips",
    "conveyor_segments",
    "upstream_ids",
    "downstream_ids",
)


def normalize_zone_bounds(raw: Any) -> tuple[float, float, float, float] | None:
    """Normalize supported zone_bounds_gltf shapes into (min_x, max_x, min_z, max_z)."""
    try:
        if isinstance(raw, dict):
            if "min" in raw and "max" in raw:
                lo, hi = raw["min"], raw["max"]
                if len(lo) >= 3 and len(hi) >= 3:
                    return (float(lo[0]), float(hi[0]), float(lo[2]), float(hi[2]))
                if len(lo) == 2 and len(hi) == 2:
                    return (float(lo[0]), float(hi[0]), float(lo[1]), float(hi[1]))
            if all(k in raw for k in ("min_x", "max_x", "min_z", "max_z")):
                return (
                    float(raw["min_x"]),
                    float(raw["max_x"]),
                    float(raw["min_z"]),
                    float(raw["max_z"]),
                )
            if all(k in raw for k in ("minX", "maxX", "minZ", "maxZ")):
                return (
                    float(raw["minX"]),
                    float(raw["maxX"]),
                    float(raw["minZ"]),
                    float(raw["maxZ"]),
                )
        elif isinstance(raw, (list, tuple)):
            if len(raw) == 2 and isinstance(raw[0], (list, tuple)) and isinstance(raw[1], (list, tuple)):
                lo, hi = raw[0], raw[1]
                if len(lo) >= 3 and len(hi) >= 3:
                    return (float(lo[0]), float(hi[0]), float(lo[2]), float(hi[2]))
                if len(lo) == 2 and len(hi) == 2:
                    return (float(lo[0]), float(hi[0]), float(lo[1]), float(hi[1]))
            if len(raw) == 4 and all(isinstance(v, (int, float)) for v in raw):
                return (float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))
    except (TypeError, ValueError):
        return None
    return None


def validate_workshop_chain(
    chain: Any,
    bindings: dict[str, Any],
    scene_nodes: set[str],
    worker_clips: set[str],
    robot_clips: set[str],
) -> list[str]:
    """Validate workshop_chain.json against the locked R1 / PROJECT.md §2 & §3 contracts."""
    errors: list[str] = []
    if not isinstance(chain, dict):
        return ["workshop_chain root must be a JSON object"]

    if chain.get("format") != "four-horses.workshop-chain.v1":
        errors.append(f"Invalid format: {chain.get('format')!r} != 'four-horses.workshop-chain.v1'")
    if chain.get("entry_nodes") != ["S0_INBOUND"]:
        errors.append(f"Invalid entry_nodes: {chain.get('entry_nodes')!r} != ['S0_INBOUND']")
    term = chain.get("terminal_nodes")
    if not isinstance(term, list) or len(term) != 3 or set(term) != TERMINAL_STAGE_IDS:
        errors.append(f"Invalid terminal_nodes: {term!r}")
    if chain.get("auxiliary_nodes") != ["S5E_BREAK"]:
        errors.append(f"Invalid auxiliary_nodes: {chain.get('auxiliary_nodes')!r} != ['S5E_BREAK']")

    stages_raw = chain.get("stages")
    if not isinstance(stages_raw, list):
        errors.append("stages must be a list of 12 stage objects")
        return errors

    stages_by_id: dict[str, dict[str, Any]] = {}
    for idx, st in enumerate(stages_raw):
        if not isinstance(st, dict):
            errors.append(f"stages[{idx}] is not a dict")
            continue
        sid = st.get("id")
        if not isinstance(sid, str) or not sid:
            errors.append(f"stages[{idx}] missing valid string id")
            continue
        if sid in stages_by_id:
            errors.append(f"Duplicate stage id: {sid}")
            continue
        stages_by_id[sid] = st

    actual_ids = set(stages_by_id.keys())
    if actual_ids != EXPECTED_STAGE_IDS:
        missing = sorted(EXPECTED_STAGE_IDS - actual_ids)
        extra = sorted(actual_ids - EXPECTED_STAGE_IDS)
        errors.append(f"Stage ID set mismatch: missing={missing}, extra={extra}")
        if missing:
            return errors

    # Per-stage schema & bounds checks
    for sid in sorted(EXPECTED_STAGE_IDS):
        st = stages_by_id[sid]
        missing_keys = [k for k in REQUIRED_STAGE_KEYS if k not in st]
        if missing_keys:
            errors.append(f"{sid}: missing required keys {missing_keys}")
            continue

        if not isinstance(st["name"], str) or not st["name"].strip():
            errors.append(f"{sid}: name must be non-empty string")
        if not isinstance(st["zone_id"], str) or not st["zone_id"].strip():
            errors.append(f"{sid}: zone_id must be non-empty string")

        bounds = normalize_zone_bounds(st["zone_bounds_gltf"])
        if bounds is None:
            errors.append(f"{sid}: invalid zone_bounds_gltf {st['zone_bounds_gltf']!r}")
        else:
            min_x, max_x, min_z, max_z = bounds
            if not (-18.1 <= min_x < max_x <= 18.1 and -9.1 <= min_z < max_z <= 9.1):
                errors.append(
                    f"{sid}: zone_bounds_gltf {bounds} outside 36x18m hall [-18.1..18.1, -9.1..9.1]"
                )

        for list_key in (
            "equipment_nodes",
            "character_roles",
            "operation_clips",
            "transfer_clips",
            "conveyor_segments",
            "upstream_ids",
            "downstream_ids",
        ):
            if not isinstance(st[list_key], list):
                errors.append(f"{sid}: {list_key} must be a list")

        if isinstance(st["equipment_nodes"], list) and len(st["equipment_nodes"]) < 1:
            errors.append(f"{sid}: equipment_nodes must contain >= 1 node")

    if errors:
        return errors

    # Directed graph symmetry & reference validity
    up_map = {sid: list(stages_by_id[sid]["upstream_ids"]) for sid in EXPECTED_STAGE_IDS}
    down_map = {sid: list(stages_by_id[sid]["downstream_ids"]) for sid in EXPECTED_STAGE_IDS}

    for sid in sorted(EXPECTED_STAGE_IDS):
        for u in up_map[sid]:
            if u not in EXPECTED_STAGE_IDS:
                errors.append(f"{sid}: unknown upstream id {u!r}")
            elif u == sid:
                errors.append(f"{sid}: self-loop in upstream_ids")
            elif sid not in down_map[u]:
                errors.append(f"Asymmetric edge: {u} in {sid}.upstream_ids but {sid} not in {u}.downstream_ids")
        for v in down_map[sid]:
            if v not in EXPECTED_STAGE_IDS:
                errors.append(f"{sid}: unknown downstream id {v!r}")
            elif v == sid:
                errors.append(f"{sid}: self-loop in downstream_ids")
            elif sid not in up_map[v]:
                errors.append(f"Asymmetric edge: {v} in {sid}.downstream_ids but {sid} not in {v}.upstream_ids")

    # Material-flow subgraph G_flow (excluding S5E_BREAK)
    in_flow_up = [u for u in up_map["S0_INBOUND"] if u != "S5E_BREAK"]
    if in_flow_up:
        errors.append(f"S0_INBOUND must have no material-flow upstream stages, got {in_flow_up}")

    for t_id in sorted(TERMINAL_STAGE_IDS):
        t_down = [d for d in down_map[t_id] if d != "S5E_BREAK"]
        if t_down:
            errors.append(f"Terminal stage {t_id} must have no material-flow downstream stages, got {t_down}")

    # Forward BFS from S0_INBOUND in G_flow
    visited_fwd: set[str] = {"S0_INBOUND"}
    q_fwd: deque[str] = deque(["S0_INBOUND"])
    while q_fwd:
        cur = q_fwd.popleft()
        for nxt in down_map.get(cur, []):
            if nxt in FLOW_STAGE_IDS and nxt not in visited_fwd:
                visited_fwd.add(nxt)
                q_fwd.append(nxt)
    unreachable = sorted(FLOW_STAGE_IDS - visited_fwd)
    if unreachable:
        errors.append(f"Unreachable/orphan stages from S0_INBOUND: {unreachable}")

    # Backward BFS from TERMINAL_STAGE_IDS in G_flow
    visited_bwd: set[str] = set(TERMINAL_STAGE_IDS)
    q_bwd: deque[str] = deque(sorted(TERMINAL_STAGE_IDS))
    while q_bwd:
        cur = q_bwd.popleft()
        for prv in up_map.get(cur, []):
            if prv in FLOW_STAGE_IDS and prv not in visited_bwd:
                visited_bwd.add(prv)
                q_bwd.append(prv)
    dead_ends = sorted(FLOW_STAGE_IDS - visited_bwd)
    if dead_ends:
        errors.append(f"Dead-end stages unable to reach any terminal node: {dead_ends}")

    # Mandatory domain routing transitions
    if "S1_PREP" not in down_map["S0_INBOUND"]:
        errors.append("Missing mandatory transition S0_INBOUND -> S1_PREP")
    if "S2_PICK" not in down_map["S1_PREP"]:
        errors.append("Missing mandatory transition S1_PREP -> S2_PICK")
    if not {"S3A_PACK_MANUAL", "S3B_PACK_ROBOT"}.issubset(set(down_map["S2_PICK"])):
        errors.append("S2_PICK must branch to both S3A_PACK_MANUAL and S3B_PACK_ROBOT")
    if "S4_QC" not in down_map["S3A_PACK_MANUAL"]:
        errors.append("Missing mandatory transition S3A_PACK_MANUAL -> S4_QC")
    if "S4_QC" not in down_map["S3B_PACK_ROBOT"]:
        errors.append("Missing mandatory transition S3B_PACK_ROBOT -> S4_QC")
    if "S3C_ROBOT_ASSIST" not in down_map["S3B_PACK_ROBOT"]:
        errors.append("Missing mandatory jam transition S3B_PACK_ROBOT -> S3C_ROBOT_ASSIST")
    if not ({"S4_QC", "S3B_PACK_ROBOT"} & set(down_map["S3C_ROBOT_ASSIST"])):
        errors.append("S3C_ROBOT_ASSIST must transition to S4_QC or S3B_PACK_ROBOT")
    if not {"S5A_GOOD", "S5B_ESCAPED", "S5C_REWORK_R", "S5D_SCRAP"}.issubset(
        set(down_map["S4_QC"])
    ):
        errors.append("S4_QC must branch to S5A_GOOD, S5B_ESCAPED, S5C_REWORK_R, and S5D_SCRAP")
    if "S3A_PACK_MANUAL" not in down_map["S5C_REWORK_R"]:
        errors.append("S5C_REWORK_R must loop back into S3A_PACK_MANUAL")
    if "S3B_PACK_ROBOT" in down_map["S5C_REWORK_R"]:
        errors.append("Illegal rework routing: S5C_REWORK_R must NOT route attempt==1 to S3B_PACK_ROBOT")

    # Cycle discipline: acyclic after removing recovery back-edges
    allowed_back_edges = {
        ("S5C_REWORK_R", "S3A_PACK_MANUAL"),
        ("S3C_ROBOT_ASSIST", "S3B_PACK_ROBOT"),
    }
    dag_adj: dict[str, list[str]] = {u: [] for u in FLOW_STAGE_IDS}
    in_deg: dict[str, int] = {u: 0 for u in FLOW_STAGE_IDS}
    for u in FLOW_STAGE_IDS:
        for v in down_map[u]:
            if v in FLOW_STAGE_IDS and (u, v) not in allowed_back_edges:
                dag_adj[u].append(v)
                in_deg[v] += 1
    kahn_q: deque[str] = deque(sorted(u for u, d in in_deg.items() if d == 0))
    topo_count = 0
    while kahn_q:
        u = kahn_q.popleft()
        topo_count += 1
        for v in dag_adj[u]:
            in_deg[v] -= 1
            if in_deg[v] == 0:
                kahn_q.append(v)
    if topo_count != len(FLOW_STAGE_IDS):
        errors.append("Unintended cycle detected in material-flow graph outside rework/assist recovery")

    # Auxiliary S5E_BREAK connectivity
    brk_up = set(up_map["S5E_BREAK"])
    brk_down = set(down_map["S5E_BREAK"])
    req_manual_stages = {"S1_PREP", "S2_PICK", "S3A_PACK_MANUAL", "S4_QC"}
    if not brk_up or brk_up != brk_down or not req_manual_stages.issubset(brk_up):
        errors.append(
            f"S5E_BREAK must connect symmetrically to at least {sorted(req_manual_stages)}, got up={sorted(brk_up)} down={sorted(brk_down)}"
        )

    # Cross-reference GLB nodes, visual_bindings.json anchors, and character clips
    norm_scene_nodes = set(scene_nodes) | {n.replace(" ", "_") for n in scene_nodes}
    all_clips = set(worker_clips) | set(robot_clips)

    for sid in sorted(EXPECTED_STAGE_IDS):
        st = stages_by_id[sid]
        for node_name in st["equipment_nodes"]:
            if node_name not in norm_scene_nodes and node_name.replace(" ", "_") not in norm_scene_nodes:
                errors.append(f"{sid}: equipment node {node_name!r} missing from GLBs/scene")
        for seg_name in st["conveyor_segments"]:
            if seg_name not in norm_scene_nodes and seg_name.replace(" ", "_") not in norm_scene_nodes:
                errors.append(f"{sid}: conveyor segment {seg_name!r} missing from GLBs/scene")
        for anc_key in ("work_anchor", "order_anchor"):
            anc = st[anc_key]
            if anc is not None:
                if not isinstance(anc, str) or (
                    anc not in norm_scene_nodes and anc.replace(" ", "_") not in norm_scene_nodes
                ):
                    errors.append(f"{sid}: {anc_key} {anc!r} missing from GLBs/scene")

        for clip_name in list(st["operation_clips"]) + list(st["transfer_clips"]):
            if clip_name not in all_clips:
                errors.append(f"{sid}: phantom animation clip {clip_name!r} missing from worker/robot GLBs")

    # Anchor alignment with visual_bindings.json
    expected_stage_anchors = {
        "S1_PREP": ("VIS_STAGE_1_WORK", "VIS_STAGE_1_ORDER"),
        "S2_PICK": ("VIS_STAGE_2_WORK", "VIS_STAGE_2_ORDER"),
        "S3A_PACK_MANUAL": ("VIS_STAGE_3_WORK", "VIS_STAGE_3_ORDER"),
        "S3B_PACK_ROBOT": ("VIS_ROBOT_WORK", "VIS_ROBOT_ORDER"),
        "S4_QC": ("VIS_STAGE_4_WORK", "VIS_STAGE_4_ORDER"),
    }
    for sid, (exp_work, exp_order) in expected_stage_anchors.items():
        st = stages_by_id[sid]
        if st["work_anchor"] != exp_work or st["order_anchor"] != exp_order:
            errors.append(
                f"{sid}: anchors ({st['work_anchor']!r}, {st['order_anchor']!r}) != ({exp_work!r}, {exp_order!r})"
            )

    s3c_refs = set(stages_by_id["S3C_ROBOT_ASSIST"]["equipment_nodes"]) | {
        stages_by_id["S3C_ROBOT_ASSIST"]["work_anchor"],
        stages_by_id["S3C_ROBOT_ASSIST"]["order_anchor"],
    }
    if "VIS_ROBOT_ASSIST" not in s3c_refs:
        errors.append("S3C_ROBOT_ASSIST must reference VIS_ROBOT_ASSIST")

    expected_outcomes = {
        "S5A_GOOD": "VIS_OUTCOME_GOOD",
        "S5B_ESCAPED": "VIS_OUTCOME_ESCAPED",
        "S5D_SCRAP": "VIS_OUTCOME_SCRAP",
    }
    for sid, out_anc in expected_outcomes.items():
        st = stages_by_id[sid]
        refs = set(st["equipment_nodes"]) | {st["work_anchor"], st["order_anchor"]}
        if out_anc not in refs:
            errors.append(f"{sid}: must reference outcome anchor {out_anc}")

    # Stage-specific operational clip coverage
    required_worker_stage_clips = {
        "S1_PREP": {"Prepare", "Prepare_Oversize"},
        "S2_PICK": {"Pick", "Pick_Oversize"},
        "S3A_PACK_MANUAL": {"Pack", "Pack_Oversize"},
        "S4_QC": {"Inspect", "Inspect_Oversize"},
        "S5E_BREAK": {"Break"},
    }
    for sid, req_clips in required_worker_stage_clips.items():
        st_clips = set(stages_by_id[sid]["operation_clips"]) | set(stages_by_id[sid]["transfer_clips"])
        if not req_clips.issubset(st_clips):
            errors.append(f"{sid}: missing required worker clips {sorted(req_clips - st_clips)}")
        if not req_clips.issubset(worker_clips):
            errors.append(f"{sid}: required worker clips {sorted(req_clips - worker_clips)} absent from worker GLB")

    s3b_clips = set(stages_by_id["S3B_PACK_ROBOT"]["operation_clips"])
    if not {"RobotPack", "RobotPack_Oversize"}.issubset(s3b_clips):
        errors.append("S3B_PACK_ROBOT: must include RobotPack and RobotPack_Oversize")

    s3c_clips = set(stages_by_id["S3C_ROBOT_ASSIST"]["operation_clips"]) | set(
        stages_by_id["S3C_ROBOT_ASSIST"]["transfer_clips"]
    )
    if "Assist" not in s3c_clips or not ({"Jammed", "Service"} & s3c_clips):
        errors.append("S3C_ROBOT_ASSIST: must include worker Assist and robot Jammed/Service clips")

    if bindings.get("format") != "four-horses.visual-bindings.v1":
        errors.append(f"Invalid visual_bindings format: {bindings.get('format')!r}")

    return errors


def make_reference_workshop_chain() -> dict[str, Any]:
    """Build a valid canonical workshop_chain.json structure for isolated Tier 2 negative mutation tests."""
    base = {
        "format": "four-horses.workshop-chain.v1",
        "entry_nodes": ["S0_INBOUND"],
        "terminal_nodes": ["S5A_GOOD", "S5B_ESCAPED", "S5D_SCRAP"],
        "auxiliary_nodes": ["S5E_BREAK"],
        "stages": [
            {
                "id": "S0_INBOUND",
                "name": "Inbound Arrival & Q1 Staging",
                "zone_id": "ZONE_INBOUND_Q1",
                "zone_bounds_gltf": {"min": [-17.9, 0.0, -4.9], "max": [-9.2, 3.6, 6.0]},
                "equipment_nodes": ["DOCK_01", "PALLET_JACK", "Q1_PAIRED_PALLET_DECK", "VIS_QUEUE_Q1"],
                "work_anchor": None,
                "order_anchor": "VIS_QUEUE_Q1",
                "character_roles": ["system_inbound", "worker_stage_1"],
                "operation_clips": ["PickUp"],
                "transfer_clips": ["Walk", "CarryWalk"],
                "conveyor_segments": [],
                "upstream_ids": [],
                "downstream_ids": ["S1_PREP"],
            },
            {
                "id": "S1_PREP",
                "name": "Stage 1 - Carton Preparation",
                "zone_id": "FLOOR_ZONE_01",
                "zone_bounds_gltf": {"min": [-13.35, 0.0, -4.9], "max": [-8.55, 3.6, -0.65]},
                "equipment_nodes": ["VIS_STAGE_1_TABLE", "PREP_TOOLING"],
                "work_anchor": "VIS_STAGE_1_WORK",
                "order_anchor": "VIS_STAGE_1_ORDER",
                "character_roles": ["worker_stage_1"],
                "operation_clips": ["Prepare", "Prepare_Oversize"],
                "transfer_clips": ["Walk", "CarryWalk", "PlaceDown"],
                "conveyor_segments": ["CONVEYOR_01", "CONVEYOR_02"],
                "upstream_ids": ["S0_INBOUND", "S5E_BREAK"],
                "downstream_ids": ["S2_PICK", "S5E_BREAK"],
            },
            {
                "id": "S2_PICK",
                "name": "Stage 2 - Order Picking",
                "zone_id": "FLOOR_ZONE_02",
                "zone_bounds_gltf": {"min": [-8.15, 0.0, -4.9], "max": [-3.95, 3.6, -0.65]},
                "equipment_nodes": ["VIS_QUEUE_Q2_FRAME", "BENCH_PICK", "RACK_01", "RACK_02", "RACK_03"],
                "work_anchor": "VIS_STAGE_2_WORK",
                "order_anchor": "VIS_STAGE_2_ORDER",
                "character_roles": ["worker_stage_2"],
                "operation_clips": ["Pick", "Pick_Oversize"],
                "transfer_clips": ["Walk", "PickUp", "PlaceDown"],
                "conveyor_segments": ["CONVEYOR_03", "CONVEYOR_04", "CONVEYOR_05"],
                "upstream_ids": ["S1_PREP", "S5E_BREAK"],
                "downstream_ids": ["S3A_PACK_MANUAL", "S3B_PACK_ROBOT", "S5E_BREAK"],
            },
            {
                "id": "S3A_PACK_MANUAL",
                "name": "Stage 3A - Manual Packing & Rework",
                "zone_id": "FLOOR_ZONE_03",
                "zone_bounds_gltf": {"min": [-3.55, 0.0, -4.9], "max": [5.1, 3.6, -0.65]},
                "equipment_nodes": ["VIS_QUEUE_Q3_FRAME", "BENCH_PACK", "SUPPLY_TROLLEY", "QUEUE_R_ROLLER_SECTION"],
                "work_anchor": "VIS_STAGE_3_WORK",
                "order_anchor": "VIS_STAGE_3_ORDER",
                "character_roles": ["worker_stage_3"],
                "operation_clips": ["Pack", "Pack_Oversize"],
                "transfer_clips": ["Walk", "CarryWalk", "PlaceDown"],
                "conveyor_segments": ["CONVEYOR_07", "CONVEYOR_08"],
                "upstream_ids": ["S2_PICK", "S5C_REWORK_R", "S5E_BREAK"],
                "downstream_ids": ["S4_QC", "S5E_BREAK"],
            },
            {
                "id": "S3B_PACK_ROBOT",
                "name": "Stage 3B - Automated Robot Packing",
                "zone_id": "ZONE_ROBOT_CELL",
                "zone_bounds_gltf": {"min": [2.3, 0.0, -4.5], "max": [5.1, 3.6, -1.3]},
                "equipment_nodes": ["ENV_ROBOT_CELL", "VIS_ROBOT_PACK_TABLE", "ROBOT_PLC_CABINET", "ANDON_GREEN"],
                "work_anchor": "VIS_ROBOT_WORK",
                "order_anchor": "VIS_ROBOT_ORDER",
                "character_roles": ["robot"],
                "operation_clips": ["RobotPack", "RobotPack_Oversize", "Idle", "Offline"],
                "transfer_clips": [],
                "conveyor_segments": ["CONVEYOR_06", "CONVEYOR_07", "CONVEYOR_08"],
                "upstream_ids": ["S2_PICK"],
                "downstream_ids": ["S4_QC", "S3C_ROBOT_ASSIST"],
            },
            {
                "id": "S3C_ROBOT_ASSIST",
                "name": "Stage 3C - Robot Jam & Human Assist",
                "zone_id": "ZONE_ROBOT_ASSIST",
                "zone_bounds_gltf": {"min": [2.3, 0.0, -3.2], "max": [4.8, 3.6, -1.3]},
                "equipment_nodes": ["ENV_ROBOT_CELL", "ANDON_RED", "ANDON_AMBER", "VIS_ROBOT_ASSIST"],
                "work_anchor": "VIS_ROBOT_ASSIST",
                "order_anchor": "VIS_ROBOT_ORDER",
                "character_roles": ["robot", "worker_stage_3"],
                "operation_clips": ["Jammed", "Jammed_Oversize", "Service", "Service_Oversize", "Assist"],
                "transfer_clips": ["Walk"],
                "conveyor_segments": ["CONVEYOR_07", "CONVEYOR_08"],
                "upstream_ids": ["S3B_PACK_ROBOT", "S5E_BREAK"],
                "downstream_ids": ["S4_QC", "S5E_BREAK"],
            },
            {
                "id": "S4_QC",
                "name": "Stage 4 - Quality Control",
                "zone_id": "FLOOR_ZONE_04",
                "zone_bounds_gltf": {"min": [5.4, 0.0, -4.9], "max": [8.78, 3.6, -0.65]},
                "equipment_nodes": ["VIS_QUEUE_Q4_FRAME", "QC_PORTAL", "VIS_STAGE_4_TABLE"],
                "work_anchor": "VIS_STAGE_4_WORK",
                "order_anchor": "VIS_STAGE_4_ORDER",
                "character_roles": ["worker_stage_4"],
                "operation_clips": ["Inspect", "Inspect_Oversize"],
                "transfer_clips": ["Walk", "PickUp", "PlaceDown"],
                "conveyor_segments": ["CONVEYOR_09", "CONVEYOR_10"],
                "upstream_ids": ["S3A_PACK_MANUAL", "S3B_PACK_ROBOT", "S3C_ROBOT_ASSIST", "S5E_BREAK"],
                "downstream_ids": ["S5A_GOOD", "S5B_ESCAPED", "S5C_REWORK_R", "S5D_SCRAP", "S5E_BREAK"],
            },
            {
                "id": "S5A_GOOD",
                "name": "Terminal Outcome - Good Dispatch",
                "zone_id": "ZONE_DISPATCH_GOOD",
                "zone_bounds_gltf": {"min": [9.0, 0.0, -3.0], "max": [17.9, 3.6, 6.0]},
                "equipment_nodes": ["DISPATCH_PALLET_00", "VIS_OUTCOME_GOOD", "DOCK_02"],
                "work_anchor": None,
                "order_anchor": "VIS_OUTCOME_GOOD",
                "character_roles": ["system_outbound"],
                "operation_clips": [],
                "transfer_clips": ["CarryWalk", "PlaceDown"],
                "conveyor_segments": ["CONVEYOR_10"],
                "upstream_ids": ["S4_QC"],
                "downstream_ids": [],
            },
            {
                "id": "S5B_ESCAPED",
                "name": "Terminal Outcome - Escaped Defect",
                "zone_id": "ZONE_HOLD_ESCAPED",
                "zone_bounds_gltf": {"min": [9.0, 0.0, -5.2], "max": [17.9, 3.6, 6.0]},
                "equipment_nodes": ["DISPATCH_PALLET_01", "VIS_OUTCOME_ESCAPED", "DOCK_02"],
                "work_anchor": None,
                "order_anchor": "VIS_OUTCOME_ESCAPED",
                "character_roles": ["system_outbound"],
                "operation_clips": [],
                "transfer_clips": ["CarryWalk", "PlaceDown"],
                "conveyor_segments": [],
                "upstream_ids": ["S4_QC"],
                "downstream_ids": [],
            },
            {
                "id": "S5C_REWORK_R",
                "name": "Rework Return Loop",
                "zone_id": "FLOOR_ZONE_R",
                "zone_bounds_gltf": {"min": [3.2, 0.0, 6.5], "max": [5.6, 3.6, 7.9]},
                "equipment_nodes": ["QUEUE_R_ROLLER_SECTION", "VIS_QUEUE_R"],
                "work_anchor": None,
                "order_anchor": "VIS_QUEUE_R",
                "character_roles": ["worker_stage_3"],
                "operation_clips": ["PickUp"],
                "transfer_clips": ["Walk", "CarryWalk"],
                "conveyor_segments": [],
                "upstream_ids": ["S4_QC"],
                "downstream_ids": ["S3A_PACK_MANUAL"],
            },
            {
                "id": "S5D_SCRAP",
                "name": "Terminal Outcome - Scrap",
                "zone_id": "ZONE_SCRAP",
                "zone_bounds_gltf": {"min": [6.5, 0.0, 6.4], "max": [8.0, 3.6, 7.7]},
                "equipment_nodes": ["SCRAP_BIN", "VIS_OUTCOME_SCRAP"],
                "work_anchor": None,
                "order_anchor": "VIS_OUTCOME_SCRAP",
                "character_roles": ["system_qc_reject"],
                "operation_clips": [],
                "transfer_clips": ["CarryWalk", "PlaceDown"],
                "conveyor_segments": [],
                "upstream_ids": ["S4_QC"],
                "downstream_ids": [],
            },
            {
                "id": "S5E_BREAK",
                "name": "Mandatory Shift Break",
                "zone_id": "ZONE_BREAK_AREA",
                "zone_bounds_gltf": {"min": [7.0, 0.0, -8.2], "max": [11.0, 3.6, -6.0]},
                "equipment_nodes": ["ENV_BREAK_AREA", "BREAK_BENCH", "WATER_COOLER", "SQDC_KPI_BOARD"],
                "work_anchor": None,
                "order_anchor": None,
                "character_roles": ["worker_stage_1", "worker_stage_2", "worker_stage_3", "worker_stage_4"],
                "operation_clips": ["Break"],
                "transfer_clips": ["Walk"],
                "conveyor_segments": [],
                "upstream_ids": ["S1_PREP", "S2_PICK", "S3A_PACK_MANUAL", "S3C_ROBOT_ASSIST", "S4_QC"],
                "downstream_ids": ["S1_PREP", "S2_PICK", "S3A_PACK_MANUAL", "S3C_ROBOT_ASSIST", "S4_QC"],
            },
        ],
    }
    return copy.deepcopy(base)
