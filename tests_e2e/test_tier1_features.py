"""Tier 1 Feature Coverage Suite (F1–F13: 78 Happy-Path Requirement Tests).

Coverage Matrix (6 distinct, opaque-box requirement tests per feature = 78 total):
- F01 (`test_t1_f01_01` .. `test_t1_f01_06`): Explicit End-to-End Workshop Chain Graph (`workshop_chain.json`)
- F02 (`test_t1_f02_01` .. `test_t1_f02_06`): `36 × 18 × 3.6 m` Cutaway Shell & Flush Inbound/Outbound Dock Framing
- F03 (`test_t1_f03_01` .. `test_t1_f03_06`): Physical Workshop Line Continuity, Floor Zones, and Clear Walkways
- F04 (`test_t1_f04_01` .. `test_t1_f04_06`): GLB / Mesh / Placement Hygiene & Zero Unintended Overlaps
- F05 (`test_t1_f05_01` .. `test_t1_f05_06`): Worker Rig & 17 Operational Animations (`warehouse_worker.glb`)
- F06 (`test_t1_f06_01` .. `test_t1_f06_06`): Humanoid Robot Rig & 14 Operational Animations (`humanoid_robot.glb`)
- F07 (`test_t1_f07_01` .. `test_t1_f07_06`): Spatial-Biomechanical Hand-Prop-Worktop Alignment
- F08 (`test_t1_f08_01` .. `test_t1_f08_06`): Continuous Parcel & Character Flow Between Stages
- F09 (`test_t1_f09_01` .. `test_t1_f09_06`): Full-Sequence Operation Playback & Live Scene Sync
- F10 (`test_t1_f10_01` .. `test_t1_f10_06`): Multi-Worker Spatial Separation & Full-Hall Routing
- F11 (`test_t1_f11_01` .. `test_t1_f11_06`): Manifests, Checksums, Studio Asset Staging & Build Parity
- F12 (`test_t1_f12_01` .. `test_t1_f12_06`): High-Resolution Render Verification Suite
- F13 (`test_t1_f13_01` .. `test_t1_f13_06`): Python Benchmark Engine & HTTP Bridge Integration
"""

from __future__ import annotations

from collections import deque
import math
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request

import pytest

from tests_e2e.conftest import REQUIRED_9_V1_RUN_IDS, is_stage3_pack_station
from tests_e2e.helpers import normalize_zone_bounds, validate_render_quality
from tests_e2e.helpers.chain_validator import (
    EXPECTED_STAGE_IDS,
    FLOW_STAGE_IDS,
    REQUIRED_STAGE_KEYS,
    TERMINAL_STAGE_IDS,
)

ALL_15_GLBS: tuple[str, ...] = (
    "warehouse_environment.glb",
    "modules/carton_closed.glb",
    "modules/carton_open.glb",
    "modules/humanoid_robot.glb",
    "modules/inspection_portal.glb",
    "modules/packing_bench_1800.glb",
    "modules/pallet_1200x800.glb",
    "modules/roller_conveyor_1800.glb",
    "modules/shelving_1800.glb",
    "modules/supply_trolley.glb",
    "modules/tote_600x400.glb",
    "modules/visual_layout.glb",
    "modules/visual_support.glb",
    "modules/warehouse_worker.glb",
    "modules/workbench_1800.glb",
)

STUDIO_SCENE_PLAYER_ASSETS: tuple[str, ...] = (
    "warehouse_environment.glb",
    "modules/visual_layout.glb",
    "modules/visual_support.glb",
    "modules/warehouse_worker.glb",
    "modules/humanoid_robot.glb",
    "visual_bindings.json",
    "anchors.json",
)

WORKER_17_CLIPS: tuple[str, ...] = (
    "Idle",
    "Walk",
    "CarryIdle",
    "Reach",
    "PickUp",
    "PlaceDown",
    "CarryWalk",
    "Prepare",
    "Pick",
    "Pack",
    "Inspect",
    "Assist",
    "Break",
    "Prepare_Oversize",
    "Pick_Oversize",
    "Pack_Oversize",
    "Inspect_Oversize",
)

ROBOT_14_CLIPS: tuple[str, ...] = (
    "Idle",
    "Walk",
    "CarryIdle",
    "Reach",
    "PickUp",
    "PlaceDown",
    "CarryWalk",
    "RobotPack",
    "Jammed",
    "Service",
    "Offline",
    "RobotPack_Oversize",
    "Jammed_Oversize",
    "Service_Oversize",
)

EXPECTED_14_SUPPORT_TEMPLATES: tuple[str, ...] = (
    "VIS_manual_bench",
    "VIS_order_regular",
    "VIS_order_fragile",
    "VIS_order_oversize",
    "VIS_order_tray",
    "VIS_empty_slot",
    "VIS_reserved_slot",
    "VIS_status_jammed",
    "VIS_status_service",
    "VIS_status_break",
    "VIS_status_offline",
    "VIS_outcome_good",
    "VIS_outcome_escaped",
    "VIS_outcome_scrap",
)

FLOOR_STANDING_BLENDER_EQUIPMENT: tuple[str, ...] = (
    *[f"CONVEYOR_{i:02d}" for i in range(1, 11)],
    "VIS_STAGE_1_TABLE",
    "BENCH_PICK",
    "BENCH_PACK",
    "BENCH_REWORK",
    "BENCH_SCRAP",
    "VIS_ROBOT_PACK_TABLE",
    "VIS_STAGE_4_TABLE",
    "VIS_QUEUE_Q2_FRAME",
    "VIS_QUEUE_Q3_FRAME",
    "VIS_QUEUE_Q4_FRAME",
    "QUEUE_R_ROLLER_SECTION",
    "Q1_PAIRED_PALLET_DECK",
    "DISPATCH_PALLET_00",
    "DISPATCH_PALLET_01",
    "RACK_01",
    "RACK_02",
    "RACK_03",
    "SUPPLY_TROLLEY",
    "SCRAP_BIN",
    "ROBOT_PLC_CABINET",
    "PALLET_JACK",
    "BREAK_BENCH",
    "WATER_COOLER",
)

EXPECTED_ASSIST_YAW_RAD = math.atan2(0.70, -0.44)  # ≈ +2.131959739083249 rad toward [3.5, -2.39]


def _wrap_angle_rad(delta: float) -> float:
    return math.atan2(math.sin(delta), math.cos(delta))


def _num(mapping: Any, key: str, default: float) -> float:
    if not isinstance(mapping, dict):
        return float(default)
    val = mapping.get(key)
    return float(default if val is None else val)


def _stage_map(v02_configs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    chain = v02_configs.get("workshop_chain")
    assert isinstance(chain, dict), (
        f"workshop_chain.json missing or invalid: {(v02_configs.get('files') or {}).get('workshop_chain')}"
    )
    stages = chain.get("stages")
    assert isinstance(stages, list), f"workshop_chain['stages'] must be a list, got {type(stages).__name__}"
    return {s["id"]: s for s in stages if isinstance(s, dict) and isinstance(s.get("id"), str)}


def _node_png_to_py_metrics(entry: dict[str, Any]) -> dict[str, Any]:
    rgb_std = entry.get("rgbStd") or (0.0, 0.0, 0.0)
    return {
        "width": int(entry.get("width") or 0),
        "height": int(entry.get("height") or 0),
        "bit_depth": int(entry.get("bitDepth") or 0),
        "color_type": int(entry.get("colorType") or 0),
        "rgb_std": tuple(float(v) for v in rgb_std),
        "unique_5bit": int(entry.get("unique5bit") or 0),
        "entropy_bits": float(entry.get("entropyBits") or 0.0),
        "third_foreground_ratio": list(entry.get("thirdForegroundRatio") or [0.0, 0.0, 0.0]),
    }


def _detailed_shifts(node_probe: dict[str, Any]) -> dict[str, dict[str, Any]]:
    replay_audit = node_probe.get("studioReplayAudit") or {}
    shifts = replay_audit.get("shifts") or {}
    return {
        rid: info
        for rid, info in shifts.items()
        if isinstance(info, dict) and info.get("detailed") is True
    }


# ==============================================================================
# F01: Explicit End-to-End Workshop Chain Graph (`workshop_chain.json`) — 6 Tests
# ==============================================================================


def test_t1_f01_01_workshop_chain_schema_and_twelve_canonical_stages(
    v02_configs: dict[str, Any],
) -> None:
    """F1.1: workshop_chain.json defines format, entry/terminal nodes, and all 12 bounded stages."""
    meta = (v02_configs.get("files") or {}).get("workshop_chain") or {}
    assert meta.get("exists") is True and meta.get("ok") is True, (
        f"4_Horses_Environment_v02/workshop_chain.json missing or unreadable: {meta}"
    )
    chain = v02_configs.get("workshop_chain")
    assert isinstance(chain, dict)
    assert chain.get("format") == "four-horses.workshop-chain.v1"
    assert chain.get("entry_nodes") == ["S0_INBOUND"]
    term_nodes = chain.get("terminal_nodes")
    assert isinstance(term_nodes, list) and set(term_nodes) == TERMINAL_STAGE_IDS

    stages = chain.get("stages")
    assert isinstance(stages, list) and len(stages) == 12, (
        f"Expected exactly 12 stages, got {len(stages) if isinstance(stages, list) else stages!r}"
    )
    by_id = _stage_map(v02_configs)
    assert set(by_id.keys()) == EXPECTED_STAGE_IDS

    for sid, stage in by_id.items():
        missing_keys = [k for k in REQUIRED_STAGE_KEYS if k not in stage]
        assert not missing_keys, f"Stage {sid} missing required keys: {missing_keys}"
        bounds = normalize_zone_bounds(stage.get("zone_bounds_gltf"))
        assert bounds is not None, f"Stage {sid} has invalid zone_bounds_gltf: {stage.get('zone_bounds_gltf')!r}"
        min_x, max_x, min_z, max_z = bounds
        assert min_x < max_x and min_z < max_z, f"Stage {sid} inverted zone_bounds_gltf: {bounds}"
        assert -18.05 <= min_x and max_x <= 18.05 and -9.05 <= min_z and max_z <= 9.05, (
            f"Stage {sid} zone_bounds_gltf escapes 36x18m hall: {bounds}"
        )


def test_t1_f01_02_workshop_chain_forward_and_backward_bfs_reachability(
    v02_configs: dict[str, Any],
) -> None:
    """F1.2: Every flow stage is forward-reachable from S0_INBOUND and reaches a terminal stage."""
    by_id = _stage_map(v02_configs)
    assert FLOW_STAGE_IDS <= set(by_id.keys())

    # Reciprocal edge symmetry across all 12 stages
    for sid, stage in by_id.items():
        for down in stage.get("downstream_ids") or []:
            assert down in by_id, f"{sid} downstream {down!r} does not exist"
            assert sid in (by_id[down].get("upstream_ids") or []), (
                f"Edge asymmetry: {sid} -> {down} missing from {down}.upstream_ids"
            )
        for up in stage.get("upstream_ids") or []:
            assert up in by_id, f"{sid} upstream {up!r} does not exist"
            assert sid in (by_id[up].get("downstream_ids") or []), (
                f"Edge asymmetry: {up} <- {sid} missing from {up}.downstream_ids"
            )

    # Forward BFS from S0_INBOUND across flow stages
    fwd_visited: set[str] = {"S0_INBOUND"}
    q_fwd: deque[str] = deque(["S0_INBOUND"])
    while q_fwd:
        cur = q_fwd.popleft()
        for nxt in by_id[cur].get("downstream_ids") or []:
            if nxt in FLOW_STAGE_IDS and nxt not in fwd_visited:
                fwd_visited.add(nxt)
                q_fwd.append(nxt)
    assert fwd_visited == FLOW_STAGE_IDS, (
        f"Orphan flow stages unreachable from S0_INBOUND: {sorted(FLOW_STAGE_IDS - fwd_visited)}"
    )

    # Backward BFS from terminal outcome stages across flow stages
    bwd_visited: set[str] = set(TERMINAL_STAGE_IDS)
    q_bwd: deque[str] = deque(TERMINAL_STAGE_IDS)
    while q_bwd:
        cur = q_bwd.popleft()
        for prev in by_id[cur].get("upstream_ids") or []:
            if prev in FLOW_STAGE_IDS and prev not in bwd_visited:
                bwd_visited.add(prev)
                q_bwd.append(prev)
    assert bwd_visited == FLOW_STAGE_IDS, (
        f"Dead-end flow stages unable to reach terminal outcomes: {sorted(FLOW_STAGE_IDS - bwd_visited)}"
    )


def test_t1_f01_03_workshop_chain_domain_routing_dag_and_break_links(
    v02_configs: dict[str, Any],
) -> None:
    """F1.3: Stage-2/3/4/5C domain transitions, forward DAG acyclicity, and S5E_BREAK symmetry hold."""
    by_id = _stage_map(v02_configs)

    assert (by_id["S0_INBOUND"].get("upstream_ids") or []) == []
    for term in TERMINAL_STAGE_IDS:
        assert (by_id[term].get("downstream_ids") or []) == [], f"Terminal {term} has non-empty downstream_ids"

    s2_down = set(by_id["S2_PICK"].get("downstream_ids") or []) - {"S5E_BREAK"}
    assert {"S3A_PACK_MANUAL", "S3B_PACK_ROBOT"} <= s2_down

    assert "S3C_ROBOT_ASSIST" in (by_id["S3B_PACK_ROBOT"].get("downstream_ids") or [])
    assert "S4_QC" in (by_id["S3A_PACK_MANUAL"].get("downstream_ids") or [])
    assert "S4_QC" in (by_id["S3B_PACK_ROBOT"].get("downstream_ids") or [])

    s4_down = set(by_id["S4_QC"].get("downstream_ids") or []) - {"S5E_BREAK"}
    assert s4_down == {"S5A_GOOD", "S5B_ESCAPED", "S5C_REWORK_R", "S5D_SCRAP"}

    rework_down = set(by_id["S5C_REWORK_R"].get("downstream_ids") or []) - {"S5E_BREAK"}
    assert rework_down == {"S3A_PACK_MANUAL"}, (
        f"Rework loop must return strictly to S3A_PACK_MANUAL (never robot), got {sorted(rework_down)}"
    )

    # Kahn topological sort on forward flow graph (excluding S5C->S3A rework loop & S3C->S3B recovery return)
    flow_nodes = sorted(FLOW_STAGE_IDS)
    indeg = {u: 0 for u in flow_nodes}
    adj: dict[str, list[str]] = {u: [] for u in flow_nodes}
    for u in flow_nodes:
        for v in by_id[u].get("downstream_ids") or []:
            if v not in FLOW_STAGE_IDS:
                continue
            if (u == "S5C_REWORK_R" and v == "S3A_PACK_MANUAL") or (
                u == "S3C_ROBOT_ASSIST" and v == "S3B_PACK_ROBOT"
            ):
                continue
            adj[u].append(v)
            indeg[v] += 1
    ready = deque([u for u, d in indeg.items() if d == 0])
    ordered: list[str] = []
    while ready:
        u = ready.popleft()
        ordered.append(u)
        for v in adj[u]:
            indeg[v] -= 1
            if indeg[v] == 0:
                ready.append(v)
    assert len(ordered) == len(flow_nodes), (
        f"Illegal cycle in forward flow DAG (visited {len(ordered)}/{len(flow_nodes)}): {ordered}"
    )

    # S5E_BREAK bidirectional links with all 4 manual stages
    manual_stages = {"S1_PREP", "S2_PICK", "S3A_PACK_MANUAL", "S4_QC"}
    break_up = set(by_id["S5E_BREAK"].get("upstream_ids") or [])
    break_down = set(by_id["S5E_BREAK"].get("downstream_ids") or [])
    assert manual_stages <= break_up and manual_stages <= break_down


def test_t1_f01_04_workshop_chain_equipment_and_conveyor_nodes_exist_in_scene(
    v02_configs: dict[str, Any],
    chain_report: dict[str, Any],
) -> None:
    """F1.4: Every equipment_nodes and conveyor_segments entry resolves in exported scene GLBs."""
    assert chain_report.get("exists") is True, f"workshop_chain.json missing: {chain_report}"
    scene_nodes = set(chain_report.get("scene_nodes") or [])
    assert len(scene_nodes) >= 100, f"Scene node inventory unexpectedly empty: {len(scene_nodes)}"

    by_id = _stage_map(v02_configs)
    missing_refs: list[str] = []
    for sid, stage in sorted(by_id.items()):
        eq_nodes = stage.get("equipment_nodes") or []
        assert len(eq_nodes) >= 1, f"Stage {sid} must declare >= 1 equipment_nodes"
        for node_name in eq_nodes:
            if node_name not in scene_nodes:
                missing_refs.append(f"{sid}.equipment_nodes:{node_name}")
        for seg_name in stage.get("conveyor_segments") or []:
            if seg_name not in scene_nodes:
                missing_refs.append(f"{sid}.conveyor_segments:{seg_name}")

    assert not missing_refs and chain_report.get("ok") is True, (
        f"workshop_chain.json references unexported scene nodes or has chain errors: "
        f"missing={missing_refs}, chain_errors={chain_report.get('errors')}"
    )


def test_t1_f01_05_workshop_chain_anchors_match_visual_bindings_and_layout_glb(
    v02_configs: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F1.5: Stage work/order anchors match visual_bindings.json, visual_layout.glb, and anchors.json."""
    vb = v02_configs.get("visual_bindings")
    cfg_vb = v02_configs.get("config_visual_bindings")
    anchors_data = v02_configs.get("anchors")
    assert isinstance(vb, dict) and isinstance(cfg_vb, dict), "visual_bindings.json missing"
    assert vb == cfg_vb, "visual_bindings.json and config/visual_bindings.json diverged"
    assert isinstance(anchors_data, (dict, list)), "anchors.json missing or invalid"

    raw_anchors = anchors_data.get("anchors", anchors_data) if isinstance(anchors_data, dict) else anchors_data
    anchor_count = len(raw_anchors) if isinstance(raw_anchors, (dict, list)) else 0
    assert anchor_count >= 28, f"Expected >= 28 exported anchors in anchors.json, got {anchor_count}"

    layout_audit = node_probe.get("layoutAudit") or {}
    assert layout_audit.get("anchorsOutOfHall") == 0, (
        f"Anchors outside 36x18m hall: {layout_audit.get('anchorsOutOfHall')}"
    )
    layout_nodes = set(layout_audit.get("nodeNames") or [])
    layout_node_count = int(layout_audit.get("nodeCount") or len(layout_nodes))
    assert layout_node_count >= 61, f"Expected >= 61 layout nodes in visual_layout.glb, got {layout_node_count}"

    by_id = _stage_map(v02_configs)
    expected_stage_anchors = {
        "S1_PREP": ("VIS_STAGE_1_WORK", "VIS_STAGE_1_ORDER"),
        "S2_PICK": ("VIS_STAGE_2_WORK", "VIS_STAGE_2_ORDER"),
        "S3A_PACK_MANUAL": ("VIS_STAGE_3_WORK", "VIS_STAGE_3_ORDER"),
        "S3B_PACK_ROBOT": ("VIS_ROBOT_WORK", "VIS_ROBOT_ORDER"),
        "S3C_ROBOT_ASSIST": ("VIS_ROBOT_ASSIST", "VIS_ROBOT_ORDER"),
        "S4_QC": ("VIS_STAGE_4_WORK", "VIS_STAGE_4_ORDER"),
    }
    for sid, (exp_work, exp_order) in expected_stage_anchors.items():
        st = by_id[sid]
        assert st.get("work_anchor") == exp_work, f"{sid}.work_anchor={st.get('work_anchor')!r} != {exp_work!r}"
        assert st.get("order_anchor") == exp_order, f"{sid}.order_anchor={st.get('order_anchor')!r} != {exp_order!r}"
        assert exp_work in layout_nodes, f"{exp_work} missing from visual_layout.glb"
        assert exp_order in layout_nodes, f"{exp_order} missing from visual_layout.glb"

    for sid, stage in by_id.items():
        for field in ("work_anchor", "order_anchor"):
            anc = stage.get(field)
            if anc is not None:
                assert anc in layout_nodes or anc in set((node_probe.get("gltfValidation") or {}).get("warehouse_environment.glb", {}).get("threeNodeNames") or []), (
                    f"{sid}.{field}={anc!r} missing from visual_layout.glb and warehouse_environment.glb"
                )


def test_t1_f01_06_workshop_chain_character_roles_and_clips_resolve_in_rigs(
    v02_configs: dict[str, Any],
    chain_report: dict[str, Any],
) -> None:
    """F1.6: Character role assignments and clip lists match worker (17) and robot (14) GLBs."""
    by_id = _stage_map(v02_configs)
    worker_clips = set(chain_report.get("worker_clips") or [])
    robot_clips = set(chain_report.get("robot_clips") or [])
    all_clips = worker_clips | robot_clips
    assert worker_clips == set(WORKER_17_CLIPS)
    assert robot_clips == set(ROBOT_14_CLIPS)

    worker_only_stages = {
        "S0_INBOUND",
        "S1_PREP",
        "S2_PICK",
        "S3A_PACK_MANUAL",
        "S4_QC",
        "S5C_REWORK_R",
        "S5D_SCRAP",
        "S5E_BREAK",
    }
    for sid in worker_only_stages:
        roles = [str(r).lower() for r in (by_id[sid].get("character_roles") or [])]
        assert any("worker" in r for r in roles) and not any("robot" in r for r in roles), (
            f"Stage {sid} must be worker-operated without robot role, got {roles}"
        )

    robot_stage_roles = [str(r).lower() for r in (by_id["S3B_PACK_ROBOT"].get("character_roles") or [])]
    assert robot_stage_roles == ["robot"], (
        f"S3B_PACK_ROBOT must assign exclusively ['robot'], got {robot_stage_roles}"
    )

    assist_roles = [str(r).lower() for r in (by_id["S3C_ROBOT_ASSIST"].get("character_roles") or [])]
    assert any("worker" in r or "helper" in r for r in assist_roles), (
        f"S3C_ROBOT_ASSIST must include human helper worker role, got {assist_roles}"
    )

    required_stage_clips = {
        "S1_PREP": ({"Prepare", "Prepare_Oversize"}, worker_clips),
        "S2_PICK": ({"Pick", "Pick_Oversize"}, worker_clips),
        "S3A_PACK_MANUAL": ({"Pack", "Pack_Oversize"}, worker_clips),
        "S3B_PACK_ROBOT": ({"RobotPack", "RobotPack_Oversize"}, robot_clips),
        "S4_QC": ({"Inspect", "Inspect_Oversize"}, worker_clips),
        "S5E_BREAK": ({"Break"}, worker_clips),
    }
    for sid, (req_set, target_rig_clips) in required_stage_clips.items():
        st_clips = set(by_id[sid].get("operation_clips") or []) | set(by_id[sid].get("transfer_clips") or [])
        assert req_set <= st_clips and req_set <= target_rig_clips, (
            f"{sid} missing required clips {sorted(req_set)}: got {sorted(st_clips)}"
        )

    s3c_clips = set(by_id["S3C_ROBOT_ASSIST"].get("operation_clips") or []) | set(
        by_id["S3C_ROBOT_ASSIST"].get("transfer_clips") or []
    )
    assert "Assist" in s3c_clips and "Assist" in worker_clips
    for sid, stage in by_id.items():
        roles = [str(r).lower() for r in (stage.get("character_roles") or [])]
        has_robot = any("robot" in r for r in roles)
        has_worker = any("worker" in r or "dispatch" in r or "arrival" in r for r in roles)
        for field in ("operation_clips", "transfer_clips"):
            raw_clips = stage.get(field) or []
            clip_list = (
                [c for sub in raw_clips.values() if isinstance(sub, list) for c in sub]
                if isinstance(raw_clips, dict)
                else list(raw_clips)
            )
            for cname in clip_list:
                assert cname in all_clips, f"{sid}.{field} phantom clip {cname!r} absent from rigs"
                if has_robot and not has_worker:
                    assert cname in robot_clips, f"{sid}.{field} {cname!r} missing from humanoid_robot.glb"
                elif has_worker and not has_robot:
                    assert cname in worker_clips, f"{sid}.{field} {cname!r} missing from warehouse_worker.glb"


# ==============================================================================
# F02: `36 × 18 × 3.6 m` Cutaway Shell & Dock Framing — 6 Tests
# ==============================================================================


def test_t1_f02_01_room_envelope_36x18x36_and_clipped_interior_cad_grid(
    v02_configs: dict[str, Any],
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F2.1: Configs, .blend, and .glb agree on 36x18x3.6m envelope, Stage-3 station, and interior CAD grid."""
    for cfg_key in ("environment_config", "config_environment"):
        cfg = v02_configs.get(cfg_key)
        assert isinstance(cfg, dict), f"{cfg_key} missing or invalid"
        room = cfg.get("room") or {}
        assert math.isclose(float(room.get("width", 0.0)), 36.0, abs_tol=1e-3)
        assert math.isclose(float(room.get("depth", 0.0)), 18.0, abs_tol=1e-3)
        assert math.isclose(float(room.get("wall_height", 0.0)), 3.6, abs_tol=1e-3)
        stations = cfg.get("stations") or []
        assert any(is_stage3_pack_station(s) for s in stations), (
            f"{cfg_key} missing Stage-3 Pack station compatible with is_stage3_pack_station: {stations}"
        )
    assert v02_configs["environment_config"] == v02_configs["config_environment"], (
        "environment_config.json and config/environment.json diverged"
    )

    assert blender_probe.get("ok") is True, f"blender_probe failed: {blender_probe.get('error')}"
    slab = (blender_probe.get("room") or {}).get("slab") or {}
    assert math.isclose(slab["min"][0], -18.0, abs_tol=0.05)
    assert math.isclose(slab["max"][0], 18.0, abs_tol=0.05)
    assert math.isclose(slab["min"][1], -9.0, abs_tol=0.05)
    assert math.isclose(slab["max"][1], 9.0, abs_tol=0.05)
    assert math.isclose(slab["max"][2], 0.0, abs_tol=0.01)

    env_slab = ((node_probe.get("environmentAudit") or {}).get("slabBox") or {})
    assert math.isclose(env_slab["span"][0], 36.0, abs_tol=0.10)
    assert math.isclose(env_slab["span"][2], 18.0, abs_tol=0.10)

    for grid_label, grid_box, z_idx in (
        ("Blender cad_grid_aabb", (blender_probe.get("spurs_and_zones") or {}).get("cad_grid_aabb"), 1),
        ("GLB cadGridAabb", (node_probe.get("environmentAudit") or {}).get("cadGridAabb"), 2),
    ):
        assert isinstance(grid_box, dict), f"{grid_label} missing"
        assert grid_box["min"][0] >= -18.02 and grid_box["max"][0] <= 18.02, (
            f"{grid_label} X bounds extend outside [-18, +18]m slab: {grid_box}"
        )
        assert grid_box["min"][z_idx] >= -9.02 and grid_box["max"][z_idx] <= 9.02, (
            f"{grid_label} depth bounds extend outside [-9, +9]m slab: {grid_box}"
        )


def test_t1_f02_02_rear_wall_columns_cutaway_side_walls_and_no_legacy_upper_walls(
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F2.2: Rear wall, structural columns, and West/East cutaway side walls reach 3.6m without upper dock walls."""
    room = blender_probe.get("room") or {}
    back_wall = room.get("back_wall_panels") or {}
    assert int(back_wall.get("count") or 0) >= 10
    assert math.isclose(back_wall["aabb"]["max"][2], 3.6, abs_tol=0.03)
    assert back_wall["aabb"]["span"][0] >= 35.8

    cols = room.get("structural_columns") or {}
    assert int(cols.get("count") or 0) >= 10
    assert math.isclose(cols["aabb"]["max"][2], 3.6, abs_tol=0.05)

    side_walls = room.get("cutaway_side_walls") or {}
    assert int(side_walls.get("west_count") or 0) >= 2
    assert int(side_walls.get("east_count") or 0) >= 2
    assert room.get("dock_upper_walls") == [], (
        f"Legacy floating DOCK_*_UPPER_WALL artifacts still present: {room.get('dock_upper_walls')}"
    )

    walls_box = ((node_probe.get("environmentAudit") or {}).get("wallsBox") or {})
    assert math.isclose(walls_box["max"][1], 3.6, abs_tol=0.05)


def test_t1_f02_03_side_wall_parapets_and_overdoor_lintels_pass_raycast_closure(
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F2.3: Horizontal raycasts verify continuous side walls, closed 2.85-3.60m lintels, and open portals."""
    pr = ((blender_probe.get("room") or {}).get("parapet_raycast") or {})
    assert pr.get("uncovered_wall_rays") == [], f"Uncovered side-wall rays in .blend: {pr.get('uncovered_wall_rays')}"
    assert pr.get("uncovered_lintel_rays") == [], f"Uncovered overdoor lintel rays in .blend: {pr.get('uncovered_lintel_rays')}"
    assert pr.get("blocked_portal_rays") == [], f"Blocked dock portal rays in .blend: {pr.get('blocked_portal_rays')}"
    assert pr.get("outside_jamb_misses") == [], f"Knife-edge jamb misses in .blend: {pr.get('outside_jamb_misses')}"
    assert pr.get("inside_portal_hits") == [], f"Knife-edge portal hits in .blend: {pr.get('inside_portal_hits')}"
    assert pr.get("inside_lintel_misses") == [], f"Knife-edge lintel misses in .blend: {pr.get('inside_lintel_misses')}"

    gl_rays = ((node_probe.get("environmentAudit") or {}).get("raycasts") or {})
    assert gl_rays.get("uncoveredWallRays") == 0
    assert gl_rays.get("uncoveredLintelRays") == 0
    assert gl_rays.get("blockedPortalRays") == 0
    assert gl_rays.get("knifeEdgeFailures") == 0


def test_t1_f02_04_inbound_and_outbound_docks_flush_on_side_walls_with_open_portals(
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F2.4: DOCK_01 (-17.85m) and DOCK_02 (+17.85m) sit flush on West/East walls with signals and raised doors."""
    docks = ((blender_probe.get("room") or {}).get("docks") or {})
    for dock_name, exp_x in (("DOCK_01", -17.85), ("DOCK_02", 17.85)):
        d = docks.get(dock_name) or {}
        assert d.get("exists") is True, f"{dock_name} missing in .blend"
        loc = d.get("location") or [0.0, 0.0, 0.0]
        assert math.isclose(loc[0], exp_x, abs_tol=0.05), f"{dock_name} X={loc[0]} != {exp_x}"
        assert math.isclose(loc[1], -5.15, abs_tol=0.08), f"{dock_name} Blender Y={loc[1]} != -5.15"
        assert d.get("signals_exist") is True, f"{dock_name} signal lights missing"
        assert d.get("leaf_exists") is True, f"{dock_name} raised sectional door leaf missing"
        leaf_aabb = d.get("leaf_aabb") or {}
        assert leaf_aabb["min"][2] >= 2.75, f"{dock_name} door leaf obstructs 2.8m portal: {leaf_aabb}"
        lintel_aabb = d.get("lintel_aabb") or {}
        assert lintel_aabb["min"][2] <= 2.90 and lintel_aabb["max"][2] >= 3.55, (
            f"{dock_name} overdoor lintel does not span [2.85, 3.60]m: {lintel_aabb}"
        )

    env_audit = node_probe.get("environmentAudit") or {}
    d1_pos = env_audit.get("dock01Pos") or [0.0, 0.0, 0.0]
    d2_pos = env_audit.get("dock02Pos") or [0.0, 0.0, 0.0]
    assert math.isclose(d1_pos[0], -17.85, abs_tol=0.05) and math.isclose(d1_pos[2], 5.15, abs_tol=0.08)
    assert math.isclose(d2_pos[0], 17.85, abs_tol=0.05) and math.isclose(d2_pos[2], 5.15, abs_tol=0.08)


def test_t1_f02_05_overhead_trusses_and_cable_tray_span_35m_hidden_by_default(
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F2.5: Unobstructed open cutaway ceiling (0 physical beam/truss/cable-tray/lamp meshes) with active lighting (02:42:13Z)."""
    ov = blender_probe.get("overhead") or {}
    assert int(ov.get("mesh_count") or 0) == 0 and ov.get("aabb") is None, (
        f"Physical 3D ceiling beam/truss/cable-tray/lamp meshes obstruct cutaway ceiling in .blend: {ov}"
    )
    assert (ov.get("forbidden_overhead_meshes") or []) == [], (
        f"Forbidden overhead ceiling clutter meshes remain in .blend: {ov.get('forbidden_overhead_meshes')}"
    )
    for child_name, ch in (ov.get("children") or {}).items():
        assert int((ch or {}).get("mesh_count") or 0) == 0, (
            f"Overhead child {child_name} still contains view-blocking meshes in .blend: {ch}"
        )
    assert int(ov.get("active_light_count") or 0) >= 2, (
        f"Blender workshop scene lost invisible active light sources (SUN/AREA): {ov}"
    )

    env_audit = node_probe.get("environmentAudit") or {}
    assert env_audit.get("overheadBox") is None, (
        f"Physical overhead geometry AABB leaked into warehouse_environment.glb: {env_audit.get('overheadBox')}"
    )
    assert (env_audit.get("forbiddenOverheadMeshes") or []) == [], (
        f"Forbidden overhead ceiling beam/lamp meshes leaked into exported GLBs: {env_audit.get('forbiddenOverheadMeshes')}"
    )
    assert (env_audit.get("layerAndAndon") or {}).get("ovHiddenByDefault") is True

    ceiling_audit = ((node_probe.get("studioReplayAudit") or {}).get("ceilingAudit") or {})
    assert (ceiling_audit.get("visibleOverheadMeshes") or []) == [], (
        f"Visible overhead ceiling clutter meshes remain in Studio scene: {ceiling_audit}"
    )
    assert int(ceiling_audit.get("activeLightCount") or 0) >= 2, (
        f"Studio Three.js lighting missing active light sources: {ceiling_audit}"
    )


def test_t1_f02_06_camera_overview_centered_and_frames_unoccluded_docks_and_corners(
    blender_probe: dict[str, Any],
) -> None:
    """F2.6: CAMERA_OVERVIEW is centered at X≈0 and frames both DOCK_01/02 and all 4 floor corners."""
    cam = blender_probe.get("camera") or {}
    assert cam.get("exists") is True and cam.get("name") == "CAMERA_OVERVIEW"
    loc = cam.get("location") or [999.0, 0.0, 0.0]
    tgt = cam.get("target_at_z085") or [999.0, 0.0, 0.0]
    assert abs(loc[0]) <= 0.25, f"CAMERA_OVERVIEW X={loc[0]} is not centered near X=0"
    assert abs(tgt[0]) <= 0.25, f"CAMERA_OVERVIEW look target X={tgt[0]} is not centered near X=0"

    for dock_name in ("DOCK_01", "DOCK_02"):
        d_cam = (cam.get("docks") or {}).get(dock_name) or {}
        assert d_cam.get("in_frustum") is True, f"{dock_name} outside CAMERA_OVERVIEW frustum: {d_cam}"
        assert d_cam.get("occluded") is False, f"{dock_name} occluded in CAMERA_OVERVIEW by {d_cam.get('hit')}"
        ndc = d_cam.get("ndc") or [0.0, 0.0, 0.0]
        assert 0.03 <= ndc[0] <= 0.97 and 0.03 <= ndc[1] <= 0.97, (
            f"{dock_name} clipped near camera frame edge: NDC={ndc}"
        )

    corners = cam.get("floor_corners") or {}
    for corner_key in ("WS", "WN", "ES", "EN"):
        cinfo = corners.get(corner_key)
        assert isinstance(cinfo, dict) and cinfo.get("in_frustum") is True, (
            f"Floor corner {corner_key} missing or outside frustum: {cinfo}"
        )
        ndc = cinfo.get("ndc")
        assert isinstance(ndc, list) and len(ndc) >= 2, f"Missing NDC for floor corner {corner_key}: {cinfo}"
        assert 0.01 <= ndc[0] <= 0.99 and 0.01 <= ndc[1] <= 0.99, (
            f"Floor corner {corner_key} clipped at CAMERA_OVERVIEW edge: NDC={ndc}"
        )


# ==============================================================================
# F03: Physical Workshop Line Continuity, Floor Zones, and Clear Walkways — 6 Tests
# ==============================================================================


def test_t1_f03_01_infeed_prep_c01_bridge_connects_stage1_to_conveyor01(
    v02_configs: dict[str, Any],
    blender_probe: dict[str, Any],
) -> None:
    """F3.1: INFEED_PREP_C01 bridges Stage-1 Prep table to CONVEYOR_01 and C01..C10 joints have <=2cm gap."""
    eq = blender_probe.get("equipment") or {}
    infeed = eq.get("INFEED_PREP_C01") or {}
    stage1_tbl = eq.get("VIS_STAGE_1_TABLE") or {}
    conv01 = eq.get("CONVEYOR_01") or {}
    assert infeed.get("exists") is True and int(infeed.get("mesh_count") or 0) >= 1
    infeed_box = infeed.get("aabb") or {}
    assert abs(infeed_box["min"][2]) <= 0.005, f"INFEED_PREP_C01 not grounded: {infeed_box}"
    assert 0.855 <= float(infeed_box["max"][2]) <= 0.915, (
        f"INFEED_PREP_C01 top {infeed_box['max'][2]} outside [0.855, 0.915]m roller+guide envelope"
    )
    assert infeed_box["min"][0] <= stage1_tbl["aabb"]["max"][0] + 0.12
    assert infeed_box["max"][0] >= conv01["aabb"]["min"][0] - 0.08

    anchors_doc = v02_configs.get("anchors") or {}
    raw_anchors = anchors_doc.get("anchors", anchors_doc) if isinstance(anchors_doc, dict) else anchors_doc
    anchor_pos: dict[str, list[float]] = {}
    if isinstance(raw_anchors, list):
        for item in raw_anchors:
            if isinstance(item, dict):
                aid = item.get("id") or item.get("name")
                pos = item.get("position_m") or item.get("position_gltf_m") or item.get("position")
                if isinstance(aid, str) and isinstance(pos, list) and len(pos) >= 3:
                    anchor_pos[aid] = [float(pos[0]), float(pos[1]), float(pos[2])]
    elif isinstance(raw_anchors, dict):
        for aid, val in raw_anchors.items():
            pos = val if isinstance(val, list) else (val.get("position_m") or val.get("position_gltf_m") if isinstance(val, dict) else None)
            if isinstance(pos, list) and len(pos) >= 3:
                anchor_pos[str(aid)] = [float(pos[0]), float(pos[1]), float(pos[2])]

    joint_gaps: list[float] = []
    for idx in range(1, 10):
        p_out = anchor_pos.get(f"ANCHOR_C{idx:02d}_OUT")
        p_in = anchor_pos.get(f"ANCHOR_C{idx + 1:02d}_IN")
        if p_out is not None and p_in is not None:
            joint_gaps.append(math.dist(p_out, p_in))
    assert len(joint_gaps) == 9, f"Expected all 9 ANCHOR_C01..C10 joint pairs in anchors.json, got {len(joint_gaps)}"
    assert max(joint_gaps) <= 0.02, f"Conveyor trunk joint gap {max(joint_gaps):.4f}m > 0.02m: {joint_gaps}"


def test_t1_f03_02_outfeed_c10_good_bridge_and_additive_spurs_grounded(
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F3.2: OUTFEED_C10_GOOD bridges CONVEYOR_10 to Good dispatch and additive spurs are cleanly grounded."""
    eq = blender_probe.get("equipment") or {}
    outfeed = eq.get("OUTFEED_C10_GOOD") or {}
    conv10 = eq.get("CONVEYOR_10") or {}
    pal0 = eq.get("DISPATCH_PALLET_00") or {}
    assert outfeed.get("exists") is True and int(outfeed.get("mesh_count") or 0) >= 1
    outfeed_box = outfeed.get("aabb") or {}
    assert abs(outfeed_box["min"][2]) <= 0.005, f"OUTFEED_C10_GOOD not grounded: {outfeed_box}"
    assert math.isclose(outfeed_box["max"][2], 0.860, abs_tol=0.05), (
        f"OUTFEED_C10_GOOD top {outfeed_box['max'][2]} not aligned near 0.860m"
    )
    assert outfeed_box["min"][0] <= conv10["aabb"]["max"][0] + 0.08
    assert outfeed_box["max"][0] >= pal0["aabb"]["min"][0] - 0.45

    present_spurs = set((node_probe.get("environmentAudit") or {}).get("additiveSpursPresent") or [])
    assert {"INFEED_PREP_C01", "OUTFEED_C10_GOOD", "STOPPER_GATE"} <= present_spurs, (
        f"Core line continuity bridges missing from warehouse_environment.glb: {present_spurs}"
    )

    add_spurs = ((blender_probe.get("spurs_and_zones") or {}).get("additive_spurs") or {})
    for spur_name, spur_info in add_spurs.items():
        if isinstance(spur_info, dict) and spur_info.get("exists") and spur_info.get("aabb"):
            min_z = spur_info["aabb"]["min"][2]
            # Floor-standing spurs rest at Z≈0; conveyor-mounted divert/stopper gates mount <= 0.90m
            if spur_name.startswith("SPUR_"):
                assert abs(min_z) <= 0.005, f"Additive spur {spur_name} floats above floor: min_z={min_z}"
            else:
                assert -0.01 <= min_z <= 0.90, f"Mounted gate/divert {spur_name} out of range: min_z={min_z}"


def test_t1_f03_03_marked_floor_transfer_lanes_connect_inbound_dispatch_and_rework(
    v02_configs: dict[str, Any],
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F3.3: Transfer-lane anchors/nodes & 5S floor zones span West inbound, East dispatch, and North rework with 0 off-walkway arrow/dash clutter (03:59:41Z)."""
    spurs_zones = blender_probe.get("spurs_and_zones") or {}
    raw_lanes = spurs_zones.get("floor_transfer_lanes") or []
    lanes = [
        ln
        for ln in raw_lanes
        if isinstance(ln, dict) and "LANE" in str(ln.get("name") or "").upper()
    ]
    assert len(lanes) >= 2, f"Expected transfer lane nodes/anchors (e.g. INBOUND_TRANSFER_LANE, DISPATCH_TRANSFER_LANE) in .blend, got {raw_lanes}"
    for ln in lanes:
        aabb = ln.get("aabb")
        if isinstance(aabb, dict) and isinstance(aabb.get("max"), list):
            assert aabb["max"][2] <= 0.020, f"Transfer lane {ln.get('name')} protrudes above 20mm decal limit: {aabb}"

    by_id = _stage_map(v02_configs)
    s0_bounds = normalize_zone_bounds((by_id.get("S0_INBOUND") or {}).get("zone_bounds_gltf"))
    s5a_bounds = normalize_zone_bounds((by_id.get("S5A_GOOD") or {}).get("zone_bounds_gltf"))
    s5c_bounds = normalize_zone_bounds((by_id.get("S5C_REWORK_R") or {}).get("zone_bounds_gltf"))
    assert s0_bounds is not None and s0_bounds[0] <= -12.5, f"S0_INBOUND does not reach West inbound staging: {s0_bounds}"
    assert s5a_bounds is not None and s5a_bounds[1] >= 9.5, f"S5A_GOOD does not reach East dispatch staging: {s5a_bounds}"
    assert s5c_bounds is not None and s5c_bounds[3] >= 5.5, f"S5C_REWORK_R does not reach North rework zone: {s5c_bounds}"

    glb_lanes = ((node_probe.get("environmentAudit") or {}).get("transferLaneNodes") or [])
    assert len(glb_lanes) >= 2, f"Expected transfer lane anchor/group nodes in warehouse_environment.glb, got {glb_lanes}"

    bl_arrows = spurs_zones.get("floor_arrows") or {}
    assert (bl_arrows.get("off_walkway_arrows") or []) == [], (
        f"Forbidden off-walkway arrows/chevrons/dashed shafts remain in .blend (03:59:41Z): {bl_arrows}"
    )


def test_t1_f03_04_stage2_pick_sku_totes_placed_at_rear_without_tray_intrusion(
    blender_probe: dict[str, Any],
) -> None:
    """F3.4: Stage-2 Pick bench holds rear SKU totes while all 5 active order tray volumes stay clear."""
    spurs_zones = blender_probe.get("spurs_and_zones") or {}
    pick_tooling = spurs_zones.get("pick_totes_tooling") or {}
    assert pick_tooling.get("root_exists") is True and int(pick_tooling.get("root_mesh_count") or 0) >= 2, (
        f"Stage-2 Pick SKU tote tooling missing: {pick_tooling}"
    )
    rear_totes = pick_tooling.get("rear_tote_meshes") or []
    assert len(rear_totes) >= 2, f"Expected >= 2 rear SKU totes on BENCH_PICK, got {rear_totes}"

    intrusions = spurs_zones.get("tray_volume_intrusions")
    assert isinstance(intrusions, dict) and len(intrusions) == 5, (
        f"Expected 5 workstation tray volume checks, got: {intrusions}"
    )
    assert all(int(v) == 0 for v in intrusions.values()), (
        f"Static geometry intrudes into active workstation order tray volumes: {intrusions}"
    )


def test_t1_f03_05_floor_zones_enclose_q1_and_plc_cabinet_without_border_overlap(
    blender_probe: dict[str, Any],
) -> None:
    """F3.5: FLOOR_ZONE_01..04, R, and ESCAPED exist; Zone 01 encloses Q1 and Zone 03 encloses PLC cabinet."""
    spurs_zones = blender_probe.get("spurs_and_zones") or {}
    fzones = spurs_zones.get("floor_zones") or {}
    for zname in (
        "FLOOR_ZONE_01",
        "FLOOR_ZONE_02",
        "FLOOR_ZONE_03",
        "FLOOR_ZONE_04",
        "FLOOR_ZONE_R",
        "OUTCOME_FLOOR_ESCAPED",
    ):
        zinfo = fzones.get(zname) or {}
        assert int(zinfo.get("mesh_count") or 0) >= 1 and zinfo.get("aabb") is not None, (
            f"Floor zone {zname} missing: {zinfo}"
        )

    fz01_box = fzones["FLOOR_ZONE_01"]["aabb"]
    assert fz01_box["min"][0] <= -13.15, f"FLOOR_ZONE_01 west edge {fz01_box['min'][0]} > -13.15m"
    q1_slots = spurs_zones.get("q1_slot_positions_blender") or []
    assert len(q1_slots) >= 4
    for pt in q1_slots:
        assert fz01_box["min"][0] - 0.05 <= pt[0] <= fz01_box["max"][0] + 0.05, (
            f"Q1 slot {pt} falls outside FLOOR_ZONE_01 X bounds {fz01_box}"
        )

    plc_box = ((blender_probe.get("equipment") or {}).get("ROBOT_PLC_CABINET") or {}).get("aabb") or {}
    fz03_box = fzones["FLOOR_ZONE_03"]["aabb"]
    assert plc_box["min"][0] >= fz03_box["min"][0] + 0.04 and plc_box["max"][0] <= fz03_box["max"][0] - 0.04
    assert plc_box["min"][1] >= fz03_box["min"][1] + 0.04 and plc_box["max"][1] <= fz03_box["max"][1] - 0.04
    border_overlaps = [
        o
        for o in (spurs_zones.get("plc_border_overlaps") or [])
        if not str((o or {}).get("strip") or "").upper().endswith("_FILL")
    ]
    assert border_overlaps == [], (
        f"ROBOT_PLC_CABINET overlaps FLOOR_ZONE_03 border stripe: {border_overlaps}"
    )


def test_t1_f03_06_south_walkway_5s_corridor_helper_zone_and_transfer_ports_unobstructed(
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F3.6: WALKWAY_GREEN_5S 2.2m prism, VIS_ROBOT_ASSIST cylinder, and conveyor transfer ports have 0 hits."""
    spurs_zones = blender_probe.get("spurs_and_zones") or {}
    ww_box = spurs_zones.get("walkway_aabb") or {}
    assert ww_box["span"][0] >= 35.0, f"WALKWAY_GREEN_5S X-span {ww_box['span'][0]} < 35.0m"
    assert ww_box["span"][1] >= 1.35, f"WALKWAY_GREEN_5S corridor width {ww_box['span'][1]} < 1.35m"
    assert ww_box["max"][2] <= 0.020, f"WALKWAY_GREEN_5S decal height {ww_box['max'][2]} > 0.020m"

    bvh = blender_probe.get("bvh") or {}
    assert bvh.get("walkway_hits") == [], f"Meshes intruding into WALKWAY_GREEN_5S: {bvh.get('walkway_hits')}"
    assert bvh.get("helper_hits") == [], f"Meshes intruding into VIS_ROBOT_ASSIST cylinder: {bvh.get('helper_hits')}"

    env_audit = node_probe.get("environmentAudit") or {}
    assert env_audit.get("walkwayPrismHits") == 0, (
        f"GLB meshes intruding into WALKWAY_GREEN_5S prism: {env_audit.get('walkwayPrismHits')}"
    )
    assert env_audit.get("transferPortHits") == 0, (
        f"Conveyor side-guard transfer ports obstructed: {env_audit.get('transferPortHits')}"
    )

    bl_arrows = spurs_zones.get("floor_arrows") or {}
    assert (bl_arrows.get("off_walkway_arrows") or []) == [], (
        f"Off-walkway floor arrows/chevrons/dashed shafts remain in .blend (03:14:54Z/03:59:41Z): {bl_arrows}"
    )
    assert (bl_arrows.get("under_table_arrows") or []) == [], f"Arrows under tables in .blend: {bl_arrows}"
    assert (bl_arrows.get("misoriented_walkway_arrows") or []) == [], (
        f"Misoriented walkway arrows in .blend: {bl_arrows}"
    )
    assert len(bl_arrows.get("walkway_arrows") or []) >= 3, f"Missing +X walkway arrows in .blend: {bl_arrows}"

    env_arrows = env_audit.get("floorArrowsAudit") or {}
    assert (env_arrows.get("offWalkwayArrows") or []) == [], (
        f"Off-walkway floor arrows/chevrons/dashed shafts remain in warehouse_environment.glb: {env_arrows}"
    )
    assert (env_arrows.get("twistedArrowMeshes") or []) == []
    assert (env_arrows.get("underTableArrows") or []) == []
    assert (env_arrows.get("misorientedWalkwayArrows") or []) == []
    assert len(env_arrows.get("walkwayArrows") or []) >= 3

    studio_arrows = (
        ((node_probe.get("studioReplayAudit") or {}).get("floorArrowsAudit"))
        or env_audit.get("studioPatchedFloorArrowsAudit")
        or {}
    )
    assert (studio_arrows.get("offWalkwayArrows") or []) == [], (
        f"Off-walkway floor arrows/chevrons/dashed shafts remain in Studio scene: {studio_arrows}"
    )
    assert (studio_arrows.get("duplicateWalkwayPairs") or []) == [], (
        f"Duplicate stacked walkway arrows in Studio: {studio_arrows}"
    )
    assert (studio_arrows.get("twistedArrowMeshes") or []) == []
    assert (studio_arrows.get("underTableArrows") or []) == []
    assert (studio_arrows.get("misorientedWalkwayArrows") or []) == []
    assert len(studio_arrows.get("walkwayArrows") or []) >= 3
    assert studio_arrows.get("hasWalkwayGreen5S") is True


# ==============================================================================
# F04: GLB / Mesh / Placement Hygiene & Zero Unintended Overlaps — 6 Tests
# ==============================================================================


def test_t1_f04_01_all_15_glbs_pass_khronos_gltf_validator_and_size_budget(
    node_probe: dict[str, Any],
) -> None:
    """F4.1: All 15 GLB assets exist, pass Khronos gltf-validator (0 errors), and stay within <12 MiB."""
    gltf_val = node_probe.get("gltfValidation") or {}
    for rel in ALL_15_GLBS:
        info = gltf_val.get(rel) or {}
        assert info.get("exists") is True, f"Missing required GLB: {rel}"
        assert int(info.get("bytes") or 0) > 512, f"GLB {rel} unexpectedly tiny: {info.get('bytes')}"
        assert info.get("numErrors") == 0, f"Khronos gltf-validator errors in {rel}: {info.get('numErrors')}"

    env_bytes = int((gltf_val.get("warehouse_environment.glb") or {}).get("bytes") or 0)
    assert env_bytes < 12 * 1024 * 1024, (
        f"warehouse_environment.glb size {env_bytes} exceeds 12 MiB ceiling"
    )


def test_t1_f04_02_robot_chamfer_top_reparented_off_conveyor_roller_06_01(
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F4.2: VIS_Bench_top_robot_chamfer sits on VIS_ROBOT_PACK_TABLE (X≈3.5m) leaving ROLLER_06_01 clear."""
    chamfer_bl = ((blender_probe.get("artifacts") or {}).get("VIS_Bench_top_robot_chamfer") or {})
    assert chamfer_bl.get("exists") is True
    assert chamfer_bl.get("parent") == "VIS_ROBOT_PACK_TABLE"
    cbox_bl = chamfer_bl.get("aabb") or {}
    assert 2.85 <= cbox_bl["min"][0] and cbox_bl["max"][0] <= 4.15
    assert math.isclose(0.5 * (cbox_bl["min"][0] + cbox_bl["max"][0]), 3.50, abs_tol=0.10)
    assert math.isclose(cbox_bl["max"][2], 0.860, abs_tol=0.004)

    chamfer_gl = ((node_probe.get("layoutAudit") or {}).get("chamfer") or {})
    assert chamfer_gl.get("exists") is True
    assert chamfer_gl.get("parent") == "VIS_ROBOT_PACK_TABLE"
    cbox_gl = chamfer_gl.get("aabb") or {}
    assert 2.85 <= cbox_gl["min"][0] and cbox_gl["max"][0] <= 4.15
    assert math.isclose(0.5 * (cbox_gl["min"][0] + cbox_gl["max"][0]), 3.50, abs_tol=0.10)
    assert math.isclose(cbox_gl["max"][1], 0.860, abs_tol=0.004)

    env_audit = node_probe.get("environmentAudit") or {}
    assert env_audit.get("chamferInEnv") is False, "VIS_Bench_top_robot_chamfer leaked into warehouse_environment.glb"
    top_hit = env_audit.get("roller0601TopHit") or {}
    assert top_hit.get("name") == "ROLLER_06_01", f"ROLLER_06_01 obstructed from above by {top_hit}"
    assert math.isclose(float(top_hit.get("y") or 0.0), 0.860, abs_tol=0.003)


def test_t1_f04_03_legacy_clutter_purged_and_pallet_jack_intact_at_inbound_dock(
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F4.3: UTILITY_CABINET, ZEBRA_*, and demo cartons are purged; grounded BENCH_REWORK, BENCH_SCRAP, and PALLET_JACK are intact."""
    arts = blender_probe.get("artifacts") or {}
    cab_entry = arts.get("UTILITY_CABINET") or {}
    assert not (cab_entry.get("exists") and int(cab_entry.get("mesh_count") or 0) > 0 and cab_entry.get("visible")), (
        f"Legacy intersecting object UTILITY_CABINET still active in .blend: {cab_entry}"
    )

    for req_bench, exp_x in (("BENCH_REWORK", 1.80), ("BENCH_SCRAP", 8.65)):
        b_entry = arts.get(req_bench) or ((blender_probe.get("equipment") or {}).get(req_bench) or {})
        assert b_entry.get("exists") is True and int(b_entry.get("mesh_count") or 0) >= 1 and b_entry.get("aabb"), (
            f"Mandatory grounded workstation {req_bench} missing in .blend: {b_entry}"
        )
        bb = b_entry["aabb"]
        assert abs(float(bb["min"][2])) <= 0.005, f"{req_bench} levitating or sunken in .blend: {bb}"
        assert 0.856 <= float(bb["max"][2]) <= 1.55, f"{req_bench} height {bb['max'][2]} outside [0.856, 1.55]m in .blend: {bb}"
        cx = 0.5 * (float(bb["min"][0]) + float(bb["max"][0]))
        cy = 0.5 * (float(bb["min"][1]) + float(bb["max"][1]))
        assert abs(cx - exp_x) <= 0.25 and abs(cy - (-6.35)) <= 0.25, (
            f"{req_bench} misplaced in .blend (expected [{exp_x}, -6.35]): center=({cx:.3f}, {cy:.3f})"
        )

    env_audit = node_probe.get("environmentAudit") or {}
    assert env_audit.get("benchReworkInEnv") is True, "Grounded BENCH_REWORK missing from warehouse_environment.glb"
    assert env_audit.get("benchScrapInEnv") is True, "Grounded BENCH_SCRAP missing from warehouse_environment.glb"
    br_gl = env_audit.get("benchReworkBox") or {}
    bs_gl = env_audit.get("benchScrapBox") or {}
    assert br_gl.get("exists") is True and abs(float(br_gl["minY"])) <= 0.005 and 0.856 <= float(br_gl["maxY"]) <= 1.55, br_gl
    assert bs_gl.get("exists") is True and abs(float(bs_gl["minY"])) <= 0.005 and 0.856 <= float(bs_gl["maxY"]) <= 1.55, bs_gl
    assert env_audit.get("utilityCabinetInEnv") is False
    assert env_audit.get("cabinetRegionTris") == 0, (
        f"Floating utility cabinet triangles remain in [-2.4,-1.0]x[2.5,3.5]: {env_audit.get('cabinetRegionTris')}"
    )
    assert env_audit.get("legacyClutterNodes") == []
    assert env_audit.get("demoCartonNodes") == []

    jack_bl = ((blender_probe.get("equipment") or {}).get("PALLET_JACK") or {})
    assert jack_bl.get("exists") is True and int(jack_bl.get("mesh_count") or 0) == 12, (
        f"PALLET_JACK must preserve all 12 native mesh parts in .blend, got {jack_bl}"
    )
    jack_gl = env_audit.get("palletJack") or {}
    assert int(jack_gl.get("meshCount") or 0) >= 4 and int(jack_gl.get("triangleCount") or 0) >= 200, (
        f"PALLET_JACK damaged or missing in warehouse_environment.glb: {jack_gl}"
    )
    assert abs(jack_gl["aabb"]["min"][1]) <= 0.005 and jack_gl["aabb"]["max"][0] <= -11.5


def test_t1_f04_04_all_floor_standing_equipment_and_bench_modules_grounded_within_2mm(
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
    _tier1_workstation_grounding_audit: dict[str, Any],
) -> None:
    """F4.4: Stationary workstations in .blend, standalone warehouse_environment.glb, and Studio rest on floor."""
    eq = blender_probe.get("equipment") or {}
    ungrounded_bl: list[str] = []
    for name in FLOOR_STANDING_BLENDER_EQUIPMENT:
        info = eq.get(name) or {}
        if not info.get("exists") or not info.get("aabb"):
            ungrounded_bl.append(f"{name}:missing")
            continue
        min_z = float(info["aabb"]["min"][2])
        if abs(min_z) > 0.005:
            ungrounded_bl.append(f"{name}:min_z={min_z:.5f}")
    assert not ungrounded_bl, f"Floor-standing assemblies floating or sunken in .blend: {ungrounded_bl}"

    gltf_val = node_probe.get("gltfValidation") or {}
    grounded_modules = (
        "modules/workbench_1800.glb",
        "modules/packing_bench_1800.glb",
        "modules/roller_conveyor_1800.glb",
        "modules/shelving_1800.glb",
        "modules/supply_trolley.glb",
        "modules/pallet_1200x800.glb",
        "modules/inspection_portal.glb",
    )
    for mod in grounded_modules:
        aabb = (gltf_val.get(mod) or {}).get("aabb") or {}
        assert abs(float(aabb["min"][1])) <= 0.005, f"Module {mod} not grounded at Y=0: {aabb}"

    bench_tpl = ((node_probe.get("supportAudit") or {}).get("templates") or {}).get("VIS_manual_bench") or {}
    assert bench_tpl.get("exists") is True
    assert abs(float(bench_tpl["localAabb"]["min"][1])) <= 0.005, (
        f"VIS_manual_bench template floats above floor: {bench_tpl}"
    )

    assert _tier1_workstation_grounding_audit.get("ok") is True, (
        f"Stationary workstation grounding probe failed: {_tier1_workstation_grounding_audit}"
    )
    required_workstations = (
        "stage1_prep",
        "stage2_pick",
        "stage3_pack",
        "stage3_robot",
        "stage4_qc",
        "bench_rework",
        "bench_scrap",
        "break_bench",
        "water_cooler",
        "shipping_podium",
    )
    standalone_env = _tier1_workstation_grounding_audit.get("standaloneEnv") or {}
    combined_studio = _tier1_workstation_grounding_audit.get("combinedStudio") or {}
    cloned_benches = _tier1_workstation_grounding_audit.get("clonedBenches") or []

    grounding_failures: list[str] = []
    for ws_key in required_workstations:
        st_info = standalone_env.get(ws_key) or {}
        if not st_info.get("exists") or st_info.get("minY") is None:
            grounding_failures.append(f"standalone_env.{ws_key}:missing_or_empty")
        elif float(st_info["minY"]) > 0.005 or float(st_info["minY"]) < -0.02:
            grounding_failures.append(f"standalone_env.{ws_key}:levitating_or_sunken(minY={st_info['minY']:.4f})")

        cb_info = combined_studio.get(ws_key) or {}
        if not cb_info.get("exists") or cb_info.get("minY") is None:
            grounding_failures.append(f"combined_studio.{ws_key}:missing_or_empty")
        elif float(cb_info["minY"]) > 0.005 or float(cb_info["minY"]) < -0.02:
            grounding_failures.append(f"combined_studio.{ws_key}:levitating_or_sunken(minY={cb_info['minY']:.4f})")

    for clone_entry in cloned_benches:
        c_min_y = float(clone_entry.get("minY", 99.0))
        if c_min_y > 0.005 or c_min_y < -0.02:
            grounding_failures.append(
                f"cloned_bench.stage{clone_entry.get('stage')}_slot{clone_entry.get('slot')}:minY={c_min_y:.4f}"
            )

    assert not grounding_failures, (
        "Stationary workstations missing or levitating above floor (minY > 0.005m) in standalone "
        f"warehouse_environment.glb or combined Studio scene: {grounding_failures}"
    )


def test_t1_f04_05_roller_plane_workstation_tops_qc_scale_and_support_templates_aligned(
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F4.5: 200 rollers, buffer rollers, 5 bench tops, QC scale, Q2-Q4 guides/labels, and 14 templates align."""
    supports = blender_probe.get("supports") or {}
    main_r = supports.get("main_rollers") or {}
    buf_r = supports.get("buffer_rollers") or {}
    assert main_r.get("count") == 200 and main_r.get("offenders") == [], f"Main roller height offenders: {main_r}"
    assert int(buf_r.get("count") or 0) >= 8 and buf_r.get("offenders") == [], f"Buffer roller offenders: {buf_r}"

    env_audit = node_probe.get("environmentAudit") or {}
    assert env_audit.get("rollerCount") == 200 and env_audit.get("rollerHeightOffenders") == 0

    wtops = supports.get("workstation_tops") or {}
    for anchor_name in (
        "VIS_STAGE_1_ORDER",
        "VIS_STAGE_2_ORDER",
        "VIS_STAGE_3_ORDER",
        "VIS_ROBOT_ORDER",
        "VIS_STAGE_4_ORDER",
    ):
        wt = wtops.get(anchor_name) or {}
        assert wt.get("exists") is True and wt.get("covers_tray_footprint") is True, (
            f"Worktop under {anchor_name} does not support full tray footprint at 0.860m: {wt}"
        )

    arts = blender_probe.get("artifacts") or {}
    qc_scale = arts.get("QC_SCALE_FLUSH") or {}
    assert qc_scale.get("exists") is True and qc_scale["aabb"]["max"][2] <= 0.863, (
        f"QC_SCALE_FLUSH protrudes above 0.860m worktop: {qc_scale}"
    )

    qracks = ((node_probe.get("layoutAudit") or {}).get("queueRacks") or {})
    for qid in ("Q2", "Q3", "Q4"):
        qr = qracks.get(qid) or {}
        assert _num(qr, "maxGuideSlotOverlapM", 99.0) <= 0.002, (
            f"Queue {qid} guide rail collides with carton slots: {qr}"
        )
        lbl_min = (qr.get("labelAabb") or {}).get("min") or [-99.0, -99.0, -99.0]
        top_max = (qr.get("topAabb") or {}).get("max") or [99.0, 99.0, 99.0]
        assert lbl_min[1] >= top_max[1] - 0.002 or lbl_min[2] >= top_max[2] - 0.002, (
            f"Queue {qid} label buried inside rack top: {qr}"
        )

    templates = ((node_probe.get("supportAudit") or {}).get("templates") or {})
    for tpl_name in EXPECTED_14_SUPPORT_TEMPLATES:
        tpl = templates.get(tpl_name) or {}
        assert tpl.get("exists") is True, f"Support template {tpl_name} missing from visual_support.glb"
        cx, cz = tpl.get("centerXZ") or [99.0, 99.0]
        assert math.hypot(cx, cz) <= 0.15, f"Support template {tpl_name} local pivot not centered: {[cx, cz]}"


def test_t1_f04_06_bvh_audit_reports_zero_unintended_collisions_and_clean_mesh_topology(
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F4.6: BVH triangle audit finds 0 unintended collisions and 0 NaN/Inf/degenerate triangles across all GLBs."""
    bvh = blender_probe.get("bvh") or {}
    assert int(bvh.get("assembly_count") or 0) >= 30
    assert bvh.get("unintended_collisions") == [], (
        f"Unintended BVH equipment collisions detected: {bvh.get('unintended_collisions')}"
    )
    assert _num(bvh, "floor_decal_max_z", 99.0) <= 0.010

    sanity = bvh.get("synthetic_sanity") or {}
    assert len(sanity.get("conveyor_box_hits") or []) >= 1 and int(sanity.get("rework_box_hit_count") or 0) >= 1

    mi = bvh.get("mesh_integrity") or {}
    assert mi.get("nan_inf_vertices") == 0 and mi.get("zero_area_triangles") == 0

    gltf_val = node_probe.get("gltfValidation") or {}
    for rel in ALL_15_GLBS:
        info = gltf_val.get(rel) or {}
        assert info.get("nanVertices") == 0, f"NaN/Inf vertices in {rel}"
        assert info.get("zeroAreaTriangles") == 0, f"Degenerate zero-area triangles in {rel}: {info.get('zeroAreaTriangles')}"


# ==============================================================================
# F05: Worker Rig & 17 Operational Animations (`warehouse_worker.glb`) — 6 Tests
# ==============================================================================


def test_t1_f05_01_worker_glb_skeleton_35_bones_prop_rig_and_skinning_weights(
    node_probe: dict[str, Any],
) -> None:
    """F5.1: warehouse_worker.glb has 35 bones (incl. 9 prop_*), valid normalized weights, and head-weighted helmet."""
    w = ((node_probe.get("characterAudit") or {}).get("worker") or {})
    assert w.get("numErrors") == 0
    assert w.get("boneCount") == 35, f"Expected 35 worker bones (26 humanoid + 9 prop_*), got {w.get('boneCount')}"
    assert w.get("missingPropBones") == [], f"Missing required prop_* bones: {w.get('missingPropBones')}"

    skin = w.get("skinning") or {}
    assert int(skin.get("totalSkinnedVerts") or 0) >= 500
    assert skin.get("unweightedVerts") == 0
    assert skin.get("outOfRangeIndices") == 0
    assert skin.get("nonNormalizedVerts") == 0
    assert skin.get("helmetHeadWeighted") is True, "Worker safety helmet must be weighted to head bone"


def test_t1_f05_02_worker_hand_sockets_and_operation_prop_metadata_clean(
    node_probe: dict[str, Any],
) -> None:
    """F5.2: ATTACH_WORKER_HAND_L/R mount to handL/R, DemoSupport is purged, and props have operation_prop=true."""
    w = ((node_probe.get("characterAudit") or {}).get("worker") or {})
    sockets = w.get("sockets") or {}
    assert sockets.get("leftExists") is True and sockets.get("leftParent") == "handL"
    assert sockets.get("rightExists") is True and sockets.get("rightParent") == "handR"
    assert w.get("demoSupportNodes") == [], f"Legacy DemoSupport nodes leaked into worker GLB: {w.get('demoSupportNodes')}"

    prop_meshes = w.get("propMeshInfos") or []
    assert len(prop_meshes) >= 6, f"Expected articulated operation prop meshes in worker GLB, got {prop_meshes}"
    for pm in prop_meshes:
        assert pm.get("operation_prop") is True, f"Worker prop mesh missing operation_prop=true: {pm}"
        assert pm.get("demo_only") is not True, f"Worker prop mesh flagged demo_only=true: {pm}"


def test_t1_f05_03_worker_17_contract_clips_30fps_cadence_and_manifest_sync(
    v02_configs: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F5.3: warehouse_worker.glb ships exact 17 clips at 30-FPS cadence synced with worker_manifest.json."""
    w = ((node_probe.get("characterAudit") or {}).get("worker") or {})
    assert set(w.get("clipNames") or []) == set(WORKER_17_CLIPS) and len(w.get("clipNames") or []) == 17

    cadence = w.get("cadence") or {}
    assert cadence.get("offGridSamplers") == [], f"Off-30FPS keyframes in worker GLB: {cadence.get('offGridSamplers')}"
    clip_cad = cadence.get("clipCadence") or {}
    metrics = w.get("clipMetrics") or {}
    for cname in WORKER_17_CLIPS:
        cc = clip_cad.get(cname) or {}
        assert cc.get("offGridCount") == 0, f"Worker clip {cname} has off-grid keyframes: {cc}"
        assert _num(cc, "durationGridErr", 99.0) <= 3e-4, f"Worker clip {cname} duration off 30-FPS grid: {cc}"
        assert int(cc.get("intervals") or 0) >= 15 and _num(cc, "duration", 0.0) > 0.5
        assert (metrics.get(cname) or {}).get("nonFiniteMatrices") == 0

    w_manifest = v02_configs.get("worker_manifest")
    assert isinstance(w_manifest, dict), "worker_manifest.json missing or invalid"
    assert w_manifest.get("bones") == 35
    raw_m_clips = w_manifest.get("clips") or []
    m_clips = [c["name"] if isinstance(c, dict) else c for c in raw_m_clips]
    assert set(m_clips) == set(WORKER_17_CLIPS)
    for c in raw_m_clips:
        if isinstance(c, dict) and "fps" in c:
            assert c["fps"] == 30, f"worker_manifest clip not 30 FPS: {c}"


def test_t1_f05_04_worker_empty_hand_clips_collapse_all_prop_bones_to_zero(
    node_probe: dict[str, Any],
) -> None:
    """F5.4: Worker Idle, Walk, Reach, Assist, and Break keep all prop_* world scales collapsed (< 1e-4)."""
    metrics = (((node_probe.get("characterAudit") or {}).get("worker") or {}).get("clipMetrics") or {})
    for empty_clip in ("Idle", "Walk", "Reach", "Assist", "Break"):
        max_scale = _num(metrics.get(empty_clip), "maxPropWorldScale", 99.0)
        assert max_scale < 1e-4, f"Worker empty-hand clip {empty_clip} leaks visible prop (scale={max_scale})"


def test_t1_f05_05_worker_active_clips_have_non_degenerate_body_motion_including_assist_and_break(
    node_probe: dict[str, Any],
) -> None:
    """F5.5: Worker locomotion, workstation, Assist (>=0.20m), and Break (>=0.15m) clips are non-degenerate."""
    metrics = (((node_probe.get("characterAudit") or {}).get("worker") or {}).get("clipMetrics") or {})
    min_deltas = {
        "Idle": 0.01,
        "CarryIdle": 0.003,
        "Walk": 0.40,
        "CarryWalk": 0.40,
        "Reach": 0.15,
        "PickUp": 0.20,
        "PlaceDown": 0.20,
        "Prepare": 0.20,
        "Prepare_Oversize": 0.20,
        "Pick": 0.25,
        "Pick_Oversize": 0.25,
        "Pack": 0.20,
        "Pack_Oversize": 0.20,
        "Inspect": 0.14,
        "Inspect_Oversize": 0.14,
        "Assist": 0.20,
        "Break": 0.15,
    }
    for cname, req_delta in min_deltas.items():
        actual = _num(metrics.get(cname), "maxBodyDeltaM", 0.0)
        assert actual >= req_delta, f"Worker clip {cname} body motion {actual:.4f}m < {req_delta:.4f}m"


def test_t1_f05_06_worker_workstation_clips_drive_articulated_carton_flap_tape_and_item_props(
    node_probe: dict[str, Any],
) -> None:
    """F5.6: Worker Prepare/Pick/Pack/Inspect articulate carton flaps, SKU item, tote, and sealing tape."""
    w = ((node_probe.get("characterAudit") or {}).get("worker") or {})
    metrics = w.get("clipMetrics") or {}
    flap_bones = ("prop_flap_front", "prop_flap_back", "prop_flap_left", "prop_flap_right")

    for prep_clip in ("Prepare", "Prepare_Oversize"):
        props = metrics[prep_clip]["props"]
        max_flap_rot = max(float(props[fb]["rotDeltaRad"]) for fb in flap_bones)
        assert max_flap_rot >= 0.35, f"{prep_clip} fails to fold carton flaps (max_rot={max_flap_rot:.3f} rad)"
        assert float(props["prop_shell"]["maxWorldScale"]) > 0.5

    for pick_clip in ("Pick", "Pick_Oversize"):
        props = metrics[pick_clip]["props"]
        assert float(props["prop_tote"]["maxWorldScale"]) > 0.5, f"{pick_clip} missing active prop_tote"
        assert float(props["prop_item"]["posDeltaM"]) >= 0.12, f"{pick_clip} fails to transfer prop_item into carton"

    for pack_clip in ("Pack", "Pack_Oversize"):
        props = metrics[pack_clip]["props"]
        max_flap_rot = max(float(props[fb]["rotDeltaRad"]) for fb in flap_bones)
        assert max_flap_rot >= 0.35, f"{pack_clip} fails to close carton flaps"
        assert (
            float(props["prop_tape"]["posDeltaM"]) >= 0.08
            or float(props["prop_closed"]["scaleDelta"]) > 0.5
        ), f"{pack_clip} missing sealing tape stroke / closed carton transition"

    for insp_clip in ("Inspect", "Inspect_Oversize"):
        props = metrics[insp_clip]["props"]
        assert float(props["prop_closed"]["maxWorldScale"]) > 0.5, f"{insp_clip} missing closed carton prop"

    adapter = w.get("adapterAudit") or {}
    assert adapter.get("ok") is True and int(adapter.get("visibleOpPropsInPack") or 0) >= 1


# ==============================================================================
# F06: Humanoid Robot Rig & 14 Operational Animations (`humanoid_robot.glb`) — 6 Tests
# ==============================================================================


def test_t1_f06_01_robot_glb_skeleton_41_bones_prop_rig_and_rigid_armor_skinning(
    node_probe: dict[str, Any],
) -> None:
    """F6.1: humanoid_robot.glb has 41 bones (32 mechanical + 9 prop_*) and 100% rigid single-bone armor skinning."""
    r = ((node_probe.get("characterAudit") or {}).get("robot") or {})
    assert r.get("numErrors") == 0
    assert r.get("boneCount") == 41, f"Expected 41 robot bones (32 mechanical + 9 prop_*), got {r.get('boneCount')}"
    assert r.get("missingPropBones") == []

    skin = r.get("skinning") or {}
    assert int(skin.get("totalSkinnedVerts") or 0) >= 500
    assert skin.get("unweightedVerts") == 0
    assert skin.get("outOfRangeIndices") == 0
    assert skin.get("nonNormalizedVerts") == 0
    assert skin.get("nonRigidArmorVerts") == 0, (
        f"Robot hard-surface armor has multi-bone rubbery skinning on {skin.get('nonRigidArmorVerts')} vertices"
    )


def test_t1_f06_02_robot_14_contract_clips_30fps_no_forbidden_clips_and_manifest_sync(
    v02_configs: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F6.2: humanoid_robot.glb ships exact 14 clips at 30-FPS, 0 Pick/Inspect leaks, synced with robot_manifest.json."""
    r = ((node_probe.get("characterAudit") or {}).get("robot") or {})
    assert set(r.get("clipNames") or []) == set(ROBOT_14_CLIPS) and len(r.get("clipNames") or []) == 14
    assert r.get("forbiddenClips") == [], f"Forbidden Pick/Inspect clips on robot rig: {r.get('forbiddenClips')}"

    cadence = r.get("cadence") or {}
    assert cadence.get("offGridSamplers") == []
    clip_cad = cadence.get("clipCadence") or {}
    metrics = r.get("clipMetrics") or {}
    for cname in ROBOT_14_CLIPS:
        cc = clip_cad.get(cname) or {}
        assert cc.get("offGridCount") == 0, f"Robot clip {cname} has off-grid keyframes: {cc}"
        assert _num(cc, "durationGridErr", 99.0) <= 3e-4, f"Robot clip {cname} duration off 30-FPS grid: {cc}"
        assert int(cc.get("intervals") or 0) >= 15 and _num(cc, "duration", 0.0) > 0.5
        assert (metrics.get(cname) or {}).get("nonFiniteMatrices") == 0

    r_manifest = v02_configs.get("robot_manifest")
    assert isinstance(r_manifest, dict), "robot_manifest.json missing or invalid"
    assert r_manifest.get("bones") == 41
    raw_m_clips = r_manifest.get("clips") or []
    m_clips = [c["name"] if isinstance(c, dict) else c for c in raw_m_clips]
    assert set(m_clips) == set(ROBOT_14_CLIPS)
    for c in raw_m_clips:
        if isinstance(c, dict) and "fps" in c:
            assert c["fps"] == 30, f"robot_manifest clip not 30 FPS: {c}"


def test_t1_f06_03_robot_hand_sockets_and_operation_prop_metadata_clean(
    node_probe: dict[str, Any],
) -> None:
    """F6.3: ATTACH_ROBOT_HAND_L/R mount to handL/R, DemoSupport is purged, and props have operation_prop=true."""
    r = ((node_probe.get("characterAudit") or {}).get("robot") or {})
    sockets = r.get("sockets") or {}
    assert sockets.get("leftExists") is True and sockets.get("leftParent") == "handL"
    assert sockets.get("rightExists") is True and sockets.get("rightParent") == "handR"
    assert r.get("demoSupportNodes") == []

    prop_meshes = r.get("propMeshInfos") or []
    assert len(prop_meshes) >= 6, f"Expected articulated operation prop meshes in robot GLB, got {prop_meshes}"
    for pm in prop_meshes:
        assert pm.get("operation_prop") is True, f"Robot prop mesh missing operation_prop=true: {pm}"
        assert pm.get("demo_only") is not True, f"Robot prop mesh flagged demo_only=true: {pm}"


def test_t1_f06_04_robot_empty_hand_and_offline_clips_collapse_all_prop_bones(
    node_probe: dict[str, Any],
) -> None:
    """F6.4: Robot Idle, Walk, Reach, and Offline keep all prop_* world scales collapsed (< 1e-4)."""
    metrics = (((node_probe.get("characterAudit") or {}).get("robot") or {}).get("clipMetrics") or {})
    for empty_clip in ("Idle", "Walk", "Reach", "Offline"):
        max_scale = _num(metrics.get(empty_clip), "maxPropWorldScale", 99.0)
        assert max_scale < 1e-4, f"Robot empty-hand/offline clip {empty_clip} leaks visible prop (scale={max_scale})"


def test_t1_f06_05_robot_pack_jammed_service_and_offline_clips_drive_distinct_motion(
    node_probe: dict[str, Any],
) -> None:
    """F6.5: RobotPack, Jammed, Service, and Offline execute distinct motion without frozen recovery phases."""
    r = ((node_probe.get("characterAudit") or {}).get("robot") or {})
    metrics = r.get("clipMetrics") or {}
    flap_bones = ("prop_flap_front", "prop_flap_back", "prop_flap_left", "prop_flap_right")

    for rpack in ("RobotPack", "RobotPack_Oversize"):
        assert float(metrics[rpack]["maxBodyDeltaM"]) >= 0.20
        props = metrics[rpack]["props"]
        max_flap_rot = max(float(props[fb]["rotDeltaRad"]) for fb in flap_bones)
        assert max_flap_rot >= 0.35, f"{rpack} fails to fold carton flaps"
        assert (
            float(props["prop_tape"]["posDeltaM"]) >= 0.08
            or float(props["prop_closed"]["scaleDelta"]) > 0.5
        ), f"{rpack} missing sealing tape / closed carton transition"

    for srv in ("Service", "Service_Oversize"):
        assert float(metrics[srv]["maxBodyDeltaM"]) >= 0.10, f"{srv} recovery motion too static"
    for jam in ("Jammed", "Jammed_Oversize"):
        assert float(metrics[jam]["maxBodyDeltaM"]) >= 0.02, f"{jam} fault posture completely frozen"
        assert float(metrics[jam]["maxPropWorldScale"]) > 0.5, f"{jam} must display jammed carton prop"
    assert float(metrics["Offline"]["maxBodyDeltaM"]) >= 0.01

    adapter = r.get("adapterAudit") or {}
    assert adapter.get("ok") is True and int(adapter.get("visibleOpPropsInPack") or 0) >= 1
    phase_diffs = adapter.get("statePhaseDiffs") or {}
    for st in ("pack", "jammed", "service"):
        assert float(phase_diffs.get(st) or 0.0) > 1e-4, (
            f"visual-integration.js froze robot state {st!r} across phase progression: {phase_diffs}"
        )


def test_t1_f06_06_worker_and_robot_share_20_core_humanoid_joint_proportions(
    node_probe: dict[str, Any],
) -> None:
    """F6.6: Worker and humanoid robot share all 20 core humanoid rest-pose joint positions within 5mm."""
    parity = ((node_probe.get("characterAudit") or {}).get("proportionParity") or {})
    assert parity.get("comparedCoreJoints") == 20
    max_diff = _num(parity, "maxCoreJointDiffM", 99.0)
    assert max_diff <= 0.005, f"Worker/robot 20-joint proportion drift {max_diff:.4f}m > 0.005m"


# ==============================================================================
# F07: Spatial-Biomechanical Hand-Prop-Worktop Alignment — 6 Tests
# ==============================================================================


def test_t1_f07_01_vis_robot_assist_yaw_and_forward_vector_face_robot_cell(
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F7.1: VIS_ROBOT_ASSIST at [2.80, 0, -1.95] faces [3.50, -2.39] (cos_sim >= 0.98, yaw ≈ +2.13196 rad)."""
    assist_bl = ((blender_probe.get("artifacts") or {}).get("VIS_ROBOT_ASSIST") or {})
    assert assist_bl.get("exists") is True
    assert _num(assist_bl, "cos_sim_to_robot_order", -1.0) >= 0.98, (
        f"Blender VIS_ROBOT_ASSIST faces away from robot order: {assist_bl}"
    )
    assert abs(_wrap_angle_rad(_num(assist_bl, "yaw_gltf_rad", 0.0) - EXPECTED_ASSIST_YAW_RAD)) <= 0.12

    static_info = ((node_probe.get("layoutAudit") or {}).get("staticAssistInfo") or {})
    assert _num(static_info, "nodeCosSim", -1.0) >= 0.98, (
        f"visual_layout.glb VIS_ROBOT_ASSIST forward cosine < 0.98: {static_info}"
    )
    if static_info.get("bindingsHelperCosSim") is not None:
        assert float(static_info["bindingsHelperCosSim"]) >= 0.98
    if static_info.get("spatialAssistCosSim") is not None:
        assert float(static_info["spatialAssistCosSim"]) >= 0.98

    shifts = _detailed_shifts(node_probe)
    all_assist_samples = [
        smp
        for sinfo in shifts.values()
        for smp in (sinfo.get("assistSamples") or [])
    ]
    assert len(all_assist_samples) >= 1, "No live robot-assist samples captured across shift replays"
    for smp in all_assist_samples:
        assert _num(smp, "distToAnchorM", 99.0) <= 0.05, f"Helper drifted from VIS_ROBOT_ASSIST: {smp}"
        assert _num(smp, "cosSim", -1.0) >= 0.98, f"Helper facing away from robot cell during assist: {smp}"
        assert _num(smp, "angleErrDeg", 180.0) <= 11.5
        assert smp.get("helperClip") == "Assist"


def test_t1_f07_02_worker_stages_1_to_4_hand_sockets_reach_carton_envelope(
    node_probe: dict[str, Any],
) -> None:
    """F7.2: Worker ATTACH_WORKER_HAND_L/R reach within 25mm of carton/flap envelopes across Stages 1–4."""
    grasp = ((node_probe.get("characterAudit") or {}).get("workstationGrasp") or {})
    worker_keys = (
        "stage1_worker_Prepare_tray0",
        "stage1_worker_Prepare_Oversize_tray0",
        "stage2_worker_Pick_tray0",
        "stage2_worker_Pick_Oversize_tray0",
        "stage3_worker_Pack_tray0",
        "stage3_worker_Pack_Oversize_tray0",
        "stage4_worker_Inspect_tray0",
        "stage4_worker_Inspect_Oversize_tray0",
    )
    for key in worker_keys:
        entry = grasp.get(key) or {}
        d_l = float(entry.get("minDistL", 99.0))
        d_r = float(entry.get("minDistR", 99.0))
        assert min(d_l, d_r) <= 0.025 and max(d_l, d_r) <= 0.080, (
            f"Worker hand-to-carton gap exceeds 25mm on {key}: {entry}"
        )


def test_t1_f07_03_robot_stage3_pack_hand_sockets_reach_carton_envelope(
    node_probe: dict[str, Any],
) -> None:
    """F7.3: Robot ATTACH_ROBOT_HAND_L/R reach within 25mm of carton/flap envelopes at VIS_ROBOT_ORDER."""
    grasp = ((node_probe.get("characterAudit") or {}).get("workstationGrasp") or {})
    for key in ("stage3_robot_RobotPack_tray0", "stage3_robot_RobotPack_Oversize_tray0"):
        entry = grasp.get(key) or {}
        d_l = float(entry.get("minDistL", 99.0))
        d_r = float(entry.get("minDistR", 99.0))
        assert d_l <= 0.025 and d_r <= 0.025, (
            f"Robot bilateral hand-to-carton gap exceeds 25mm on {key}: {entry}"
        )


def test_t1_f07_04_trayed_orders_maintain_12mm_vertical_alignment_and_grasp(
    node_probe: dict[str, Any],
) -> None:
    """F7.4: Trayed orders elevate carton base by +12mm in live replay and preserve <=25mm hand contact."""
    shifts = _detailed_shifts(node_probe)
    total_trayed = sum(int((s.get("trayAlignment") or {}).get("trayHeightChecked") or 0) for s in shifts.values())
    total_tray_err = sum(int((s.get("trayAlignment") or {}).get("trayHeightErrors") or 0) for s in shifts.values())
    total_untrayed = sum(int((s.get("trayAlignment") or {}).get("untrayedHeightChecked") or 0) for s in shifts.values())
    total_untrayed_err = sum(int((s.get("trayAlignment") or {}).get("untrayedHeightErrors") or 0) for s in shifts.values())

    assert total_trayed > 0 and total_untrayed > 0, "Expected both trayed and untrayed order samples in shifts"
    assert total_tray_err == 0, f"Trayed order +12mm vertical alignment errors: {total_tray_err}"
    assert total_untrayed_err == 0, f"Untrayed order vertical alignment errors: {total_untrayed_err}"

    grasp = ((node_probe.get("characterAudit") or {}).get("workstationGrasp") or {})
    tray12_entries = {k: v for k, v in grasp.items() if k.endswith("_tray12mm")}
    assert len(tray12_entries) == 10
    for key, entry in tray12_entries.items():
        assert min(float(entry["minDistL"]), float(entry["minDistR"])) <= 0.025, (
            f"+12mm tray offset broke hand-to-carton grasp on {key}: {entry}"
        )


def test_t1_f07_05_active_workstation_clips_never_penetrate_086m_worktop_plane(
    node_probe: dict[str, Any],
) -> None:
    """F7.5: Active workstation hand sockets and articulated props remain above the 0.860m bench plane."""
    grasp = ((node_probe.get("characterAudit") or {}).get("workstationGrasp") or {})
    tray0_entries = {k: v for k, v in grasp.items() if k.endswith("_tray0")}
    assert len(tray0_entries) == 10
    for key, entry in tray0_entries.items():
        min_sock_y = float(entry.get("minOverBenchSocketY", 0.0))
        min_prop_y = float(entry.get("minOverBenchPropY", 0.0))
        assert min_sock_y >= 0.858, f"Hand socket penetrated 0.860m bench top during {key}: y={min_sock_y:.4f}m"
        assert min_prop_y >= 0.855, f"Operation prop penetrated 0.860m bench top during {key}: y={min_prop_y:.4f}m"


def test_t1_f07_06_zero_joint_inversions_spine_order_ground_penetration_and_palm_opposition(
    node_probe: dict[str, Any],
) -> None:
    """F7.6: All 31 clips have <60 deg frame steps, valid spine Y order, floor clearance, and opposing palms."""
    char_audit = node_probe.get("characterAudit") or {}
    for kind, expected_clips, carry_pack_clips in (
        ("worker", WORKER_17_CLIPS, ("CarryIdle", "CarryWalk", "Pack", "Pack_Oversize")),
        ("robot", ROBOT_14_CLIPS, ("CarryIdle", "CarryWalk", "RobotPack", "RobotPack_Oversize")),
    ):
        metrics = ((char_audit.get(kind) or {}).get("clipMetrics") or {})
        for cname in expected_clips:
            cm = metrics.get(cname) or {}
            assert _num(cm, "maxConsecutiveStepDeg", 999.0) < 60.0, (
                f"{kind}:{cname} joint snap/inversion step >= 60 deg: {cm.get('maxConsecutiveStepDeg')}"
            )
            assert cm.get("spineOrderViolations") == 0, (
                f"{kind}:{cname} torso/head inversion: {cm.get('spineOrderViolations')}"
            )
            assert _num(cm, "minBodyBoneY", -1.0) >= -0.02, (
                f"{kind}:{cname} body bone penetrated floor: {cm.get('minBodyBoneY')}"
            )
        for cp_clip in carry_pack_clips:
            cm = metrics.get(cp_clip) or {}
            assert _num(cm, "maxPalmDot", 1.0) <= -0.75, (
                f"{kind}:{cp_clip} palms not opposing carton sidewalls (dot={cm.get('maxPalmDot')})"
            )
            assert _num(cm, "maxHandSpanX", 9.0) <= 0.68, (
                f"{kind}:{cp_clip} hands splayed unrealistically wide: {cm.get('maxHandSpanX')}"
            )


# ==============================================================================
# Module-Scoped Read-Only Subprocess Probes for F04, F11, and F13 (< 3s Total)
# ==============================================================================


@pytest.fixture(scope="module")
def _tier1_workstation_grounding_audit(
    node_probe: dict[str, Any],
) -> dict[str, Any]:
    """Read-only Three.js audit of stationary workstation grounding & map idempotency from node_probe."""
    if not node_probe.get("ok"):
        return {"ok": False, "error": node_probe.get("error")}
    env_audit = node_probe.get("environmentAudit") or {}
    wg = env_audit.get("workstationGrounding") or {}
    mi = node_probe.get("mapIdempotency") or {}
    ship = mi.get("shipped") or {}
    syn = mi.get("syntheticNative36m") or {}
    p1 = ship.get("pass1") or {}
    p2 = ship.get("pass2") or {}
    p3 = ship.get("pass3") or {}
    reapp = ship.get("afterReapply") or {}
    syn_p1 = syn.get("pass1") or {}
    syn_span_x = ((syn_p1.get("slabBox") or {}).get("span") or [None])[0]
    return {
        "ok": bool(wg.get("ok")),
        "standaloneEnv": wg.get("standaloneEnv") or {},
        "combinedStudio": wg.get("combinedStudio") or {},
        "clonedBenches": wg.get("clonedBenches") or [],
        "postMapChamferBox": p1.get("chamferBox"),
        "mapIdempotency": {
            "shipped": {
                "ok": bool(
                    ship.get("ok")
                    and (p1.get("meshCount") or 0) > 0
                    and p1.get("meshCount") == p2.get("meshCount") == p3.get("meshCount") == reapp.get("meshCount")
                ),
                "pass1Meshes": p1.get("meshCount"),
                "pass2Meshes": p2.get("meshCount"),
                "pass3Meshes": p3.get("meshCount"),
                "afterReapplyMeshes": reapp.get("meshCount"),
            },
            "syntheticNative36m": {
                "ok": bool(syn.get("ok") and syn_span_x is not None and abs(float(syn_span_x) - 36.0) <= 0.10),
                "slabSpanX": syn_span_x,
            },
        },
    }


@pytest.fixture(scope="module")
def _tier1_v02_npm_sandbox(run_v02_npm_test_sandbox) -> dict[str, Any]:
    """Run isolated v02 check_v02.mjs sandbox once for F11."""
    return run_v02_npm_test_sandbox()


@pytest.fixture(scope="module")
def _tier1_live_bridge(ephemeral_serve_3d, run_custom_replay_probe) -> dict[str, Any]:
    """Launch ephemeral serve_3d.py once for F13 HTTP header/Range & Studio openRemote checks."""
    with ephemeral_serve_3d() as srv:
        result: dict[str, Any] = {"server": dict(srv), "http_checks": {}, "remote_probe": None}
        if srv.get("ready"):
            base_url = srv["base_url"]
            index_url = srv["index_url"]
            events_url = f"{base_url}/v1-candidate-seed11/events.jsonl"

            # 1. GET /index.json
            with urllib.request.urlopen(index_url, timeout=5.0) as resp:
                get_body = resp.read()
                result["http_checks"]["get_index"] = {
                    "status": resp.status,
                    "headers": {k.lower(): v for k, v in resp.headers.items()},
                    "bytes": len(get_body),
                }

            # 2. HEAD /index.json
            head_req = urllib.request.Request(index_url, method="HEAD")
            with urllib.request.urlopen(head_req, timeout=5.0) as resp:
                head_body = resp.read()
                result["http_checks"]["head_index"] = {
                    "status": resp.status,
                    "headers": {k.lower(): v for k, v in resp.headers.items()},
                    "bytes": len(head_body),
                }

            # 3. OPTIONS /index.json
            opt_req = urllib.request.Request(index_url, method="OPTIONS")
            with urllib.request.urlopen(opt_req, timeout=5.0) as resp:
                result["http_checks"]["options_index"] = {
                    "status": resp.status,
                    "headers": {k.lower(): v for k, v in resp.headers.items()},
                }

            # 4. GET /v1-candidate-seed11/events.jsonl with Range: bytes=0-63 -> 206 Partial Content
            range_req = urllib.request.Request(events_url, headers={"Range": "bytes=0-63"})
            with urllib.request.urlopen(range_req, timeout=5.0) as resp:
                range_body = resp.read()
                result["http_checks"]["range_events"] = {
                    "status": resp.status,
                    "headers": {k.lower(): v for k, v in resp.headers.items()},
                    "bytes": len(range_body),
                }

            # 5. Studio DataMod.openRemote over live HTTP bridge
            result["remote_probe"] = run_custom_replay_probe(http_url=srv["pack_url"])
        return result


# ==============================================================================
# F08: Continuous Parcel & Character Flow Between Stages — 6 Tests
# ==============================================================================


def test_t1_f08_01_main_conveyor_trunk_shows_monotonic_west_to_east_parcel_transit(
    node_probe: dict[str, Any],
) -> None:
    """F8.1: Sub-tick replay sampling observes parcels moving monotonically West->East on CONVEYOR_01..10."""
    shifts = _detailed_shifts(node_probe)
    assert len(shifts) >= 4
    for rid in ("v1-manual-seed11", "v1-candidate-seed11", "v1-reference-seed11"):
        tr = (shifts.get(rid) or {}).get("transit") or {}
        assert int(tr.get("mainConveyorHits") or 0) > 0, (
            f"No parcels observed on main conveyor trunk during {rid}: {tr}"
        )
        assert int(tr.get("mainConveyorIncreasingXCount") or 0) > 0, (
            f"Parcels did not advance West->East along main conveyor during {rid}: {tr}"
        )


def test_t1_f08_02_infeed_outfeed_spurs_qc_portal_and_rework_loop_carry_parcels(
    node_probe: dict[str, Any],
) -> None:
    """F8.2: Parcels traverse infeed/outfeed/spurs, QC_PORTAL, and north rework loop without robot attempt==1."""
    shifts = _detailed_shifts(node_probe)
    total_bridge_spur = sum(
        int((s.get("transit") or {}).get("infeedBridgeHits") or 0)
        + int((s.get("transit") or {}).get("outfeedBridgeHits") or 0)
        + int((s.get("transit") or {}).get("spurHits") or 0)
        for s in shifts.values()
    )
    total_qc_portal = sum(int((s.get("transit") or {}).get("qcPortalHits") or 0) for s in shifts.values())
    assert total_bridge_spur > 0, f"Zero parcels observed on infeed/outfeed bridges or spurs: {shifts}"
    assert total_qc_portal > 0, "Zero parcels observed passing through QC_PORTAL"

    rework_shifts = [s for s in shifts.values() if int((s.get("rework") or {}).get("reworkStartedInRaw") or 0) > 0]
    assert len(rework_shifts) >= 1, "Expected >=1 detailed shift with rework orders"
    assert any(
        int((s.get("rework") or {}).get("reworkInQueueRObserved") or 0) > 0
        or int((s.get("rework") or {}).get("reworkBadgeObserved") or 0) > 0
        for s in rework_shifts
    ), (
        f"Rework parcels neither appeared in north Queue R nor displayed rework badge: {[s.get('rework') for s in rework_shifts]}"
    )
    assert any(
        int((s.get("rework") or {}).get("reworkBenchWorkerSamples") or 0) > 0
        and int((s.get("rework") or {}).get("reworkBenchCartonSamples") or 0) > 0
        for s in rework_shifts
    ), (
        "Stage-3 manual rework worker/carton never physically worked at BENCH_REWORK [1.80, 0, +6.35]: "
        f"{[s.get('rework') for s in rework_shifts]}"
    )

    scrap_shifts = [s for s in shifts.values() if int((s.get("scrap") or {}).get("scrapInRaw") or 0) > 0]
    assert len(scrap_shifts) >= 1, "Expected >=1 detailed shift with scrap orders"
    assert any(
        int((s.get("scrap") or {}).get("scrapCarryOrTransitObserved") or 0) > 0
        and int((s.get("scrap") or {}).get("scrapBenchOrBinVisibleAtEnd") or 0) > 0
        for s in scrap_shifts
    ), (
        "Scrap cartons vanished instead of visibly routing/stacking onto BENCH_SCRAP [8.65, 0, +6.35] / SCRAP_BIN: "
        f"{[s.get('scrap') for s in scrap_shifts]}"
    )

    for rid, s in shifts.items():
        assert int((s.get("rework") or {}).get("robotAssignedAttempt1") or 0) == 0, (
            f"Robot illegally assigned rework order (attempt==1) in {rid}: {s.get('rework')}"
        )


def test_t1_f08_03_worker_handoff_clips_and_carry_walk_fire_without_empty_hand_prop_leaks(
    node_probe: dict[str, Any],
) -> None:
    """F8.3: Workers play CarryWalk and handoff transitions in live replay with 0 empty-hand prop leaks."""
    shifts = _detailed_shifts(node_probe)
    observed_worker_union: set[str] = set()
    for rid, s in shifts.items():
        observed_worker_union.update(s.get("observedWorkerClips") or [])
        assert int(s.get("emptyHandPropLeakCount") or 0) == 0, (
            f"Empty-hand prop leak detected on {rid}: count={s.get('emptyHandPropLeakCount')}"
        )

    assert {"Idle", "Walk", "CarryWalk"} <= observed_worker_union, (
        f"Missing core locomotion clips in live shift playback: {sorted(observed_worker_union)}"
    )
    assert observed_worker_union & {"PickUp", "PlaceDown", "Reach"}, (
        f"No handoff clips (PickUp/PlaceDown/Reach) triggered during live replay: {sorted(observed_worker_union)}"
    )


def test_t1_f08_04_post_break_return_walks_smoothly_without_teleport_or_stranding(
    node_probe: dict[str, Any],
) -> None:
    """F8.4: Mandatory shift breaks walk smoothly to/from ENV_BREAK_AREA (0 11m teleports, 0 stranded workers)."""
    shifts = _detailed_shifts(node_probe)
    break_shifts = {
        rid: s for rid, s in shifts.items() if int((s.get("breaks") or {}).get("count") or 0) > 0
    }
    assert len(break_shifts) >= 3, "Expected mandatory break events across benchmark shifts"
    for rid, s in break_shifts.items():
        brk = s.get("breaks") or {}
        max_jump = _num(brk, "maxBreakStepJumpM", 99.0)
        assert max_jump <= 2.50, (
            f"Post-break teleport snap ({max_jump:.3f}m > 2.50m at dt=0.10) in {rid}: {brk.get('maxBreakJumpInfo')}"
        )
        stranded = [
            chk for chk in (brk.get("breakEndChecks") or []) if chk.get("strandedInBreakArea") is True
        ]
        assert not stranded, f"Workers stranded in break area after break end in {rid}: {stranded}"


def test_t1_f08_05_active_conveyor_rollers_spin_around_local_axis_without_center_drift(
    node_probe: dict[str, Any],
) -> None:
    """F8.5: Active rollers rotate around local axes (<2mm drift), stay still when idle, and camera presets work."""
    replay_audit = node_probe.get("studioReplayAudit") or {}
    presets = replay_audit.get("cameraPresets") or {}
    for req_preset in ("overview", "q1", "robot", "qc", "break"):
        assert (presets.get(req_preset) or {}).get("supported") is True, (
            f"Required camera preset {req_preset!r} unsupported: {presets.get(req_preset)}"
        )

    shifts = _detailed_shifts(node_probe)
    saw_spin = False
    for rid, s in shifts.items():
        assert _num(s, "stationaryRollerDelta", 99.0) < 1e-5, (
            f"Rollers spun when no orders were in transit on {rid}"
        )
        assert _num(s, "maxRollerCenterDriftM", 99.0) <= 0.002, (
            f"Spinning roller world center drifted off conveyor frame on {rid}: {s.get('maxRollerCenterDriftM')}"
        )
        if _num(s, "activeRollerMaxAngleRad", 0.0) > 0.05:
            saw_spin = True
    assert saw_spin, "Active conveyor rollers never rotated during in-transit parcel movement"


def test_t1_f08_06_replay_state_machine_matches_all_9_v1_shift_counters_and_boundaries(
    node_probe: dict[str, Any],
) -> None:
    """F8.6: Discrete replay.js state machine matches all 13 manifest counters across all 9 v1 benchmark shifts."""
    replay_audit = node_probe.get("studioReplayAudit") or {}
    assert replay_audit.get("all9RequiredV1Present") is True
    shifts = replay_audit.get("shifts") or {}
    for rid in REQUIRED_9_V1_RUN_IDS:
        s = shifts.get(rid)
        assert isinstance(s, dict), f"Missing replay inspection for {rid}"
        mismatch_count = int(s.get("counterMismatches") if s.get("counterMismatches") is not None else 99)
        assert mismatch_count == 0, (
            f"Counter parity mismatch on {rid} (count={mismatch_count}): {s.get('counterMismatchSample')}"
        )
        assert s.get("boundaryClampingOk") is True, f"Seek boundary clamping failed on {rid}"


# ==============================================================================
# F09: Full-Sequence Operation Playback & Live Scene Sync — 6 Tests
# ==============================================================================


def test_t1_f09_01_manual_stages_1_to_4_play_articulated_operation_props_live(
    node_probe: dict[str, Any],
) -> None:
    """F9.1: Live ScenePlayer advances Prepare, Pick, Pack, and Inspect operation_prop meshes across phase 0->1."""
    shifts = _detailed_shifts(node_probe)
    stage_specs = (
        ("stage1_", "Prepare"),
        ("stage2_", "Pick"),
        ("stage3_", "Pack"),
        ("stage4_", "Inspect"),
    )
    for stage_prefix, base_clip in stage_specs:
        matching_entries = [
            entry
            for s in shifts.values()
            for key, entry in (s.get("opPhaseProgression") or {}).items()
            if key.startswith(stage_prefix)
            and isinstance(entry, dict)
            and str(entry.get("clipSeen") or "").startswith(base_clip)
        ]
        assert len(matching_entries) >= 1, f"Operation clip {stage_prefix}{base_clip}* never played in live shift replays"
        best_diag = max(_num(e, "maxDiagSeen", 0.0) for e in matching_entries)
        best_delta = max(_num(e, "maxPropPhaseDelta", 0.0) for e in matching_entries)
        best_span = max(_num(e, "mixerTimeSpan", 0.0) for e in matching_entries)
        assert best_diag > 0.05, f"{stage_prefix}{base_clip} operation_prop remained hidden (maxDiagSeen={best_diag:.4f}m)"
        assert best_delta > 0.005, f"{stage_prefix}{base_clip} operation_prop frozen across job phase (delta={best_delta:.4f}m)"
        assert best_span > 0.05, f"{stage_prefix}{base_clip} AnimationMixer time did not advance (span={best_span:.4f}s)"


def test_t1_f09_02_robot_pack_jammed_service_and_andon_tower_sync_live(
    node_probe: dict[str, Any],
) -> None:
    """F9.2: Robot cell plays RobotPack, Jammed, and Service clips in sync with green/red/amber Andon states."""
    shifts = _detailed_shifts(node_probe)
    rpack_entries = [
        entry
        for s in shifts.values()
        for key, entry in (s.get("opPhaseProgression") or {}).items()
        if key.startswith("robot_")
        and isinstance(entry, dict)
        and str(entry.get("clipSeen") or "").startswith("RobotPack")
    ]
    assert len(rpack_entries) >= 1, "RobotPack never played in automated shift replays"
    assert max(_num(e, "maxDiagSeen", 0.0) for e in rpack_entries) > 0.05
    assert max(_num(e, "maxPropPhaseDelta", 0.0) for e in rpack_entries) > 0.005
    assert max(_num(e, "mixerTimeSpan", 0.0) for e in rpack_entries) > 0.05

    robot_clips_union: set[str] = set()
    andon_union: set[str] = set()
    for s in shifts.values():
        robot_clips_union.update(s.get("observedRobotClips") or [])
        andon_union.update(str(st).lower() for st in (s.get("observedAndonStates") or []))

    assert "Jammed" in robot_clips_union or "Jammed_Oversize" in robot_clips_union, (
        f"Robot Jammed clip never played during fault ticks: {sorted(robot_clips_union)}"
    )
    assert "Service" in robot_clips_union or "Service_Oversize" in robot_clips_union, (
        f"Robot Service clip never played during human assist recovery: {sorted(robot_clips_union)}"
    )
    has_green = any("green" in st or "pack" in st for st in andon_union)
    has_red = any("red" in st or "jam" in st for st in andon_union)
    has_amber = any("amber" in st or "service" in st for st in andon_union)
    assert has_green and has_red and has_amber, (
        f"Andon tower states did not cover green/red/amber (pack/jammed/service): {sorted(andon_union)}"
    )


def test_t1_f09_03_static_bench_order_placeholders_hidden_during_active_work(
    node_probe: dict[str, Any],
) -> None:
    """F9.3: Active workstation operations never show overlapping static bench ORDER_* placeholders."""
    shifts = _detailed_shifts(node_probe)
    total_samples = sum(int(s.get("activeWorkstationSamples") or 0) for s in shifts.values())
    assert total_samples >= 50, f"Insufficient active workstation samples: {total_samples}"
    for rid, s in shifts.items():
        assert int(s.get("activeBenchDuplicateCollisions") or 0) == 0, (
            f"Duplicate static carton overlapped articulated operation_prop on {rid}: "
            f"{s.get('activeBenchDuplicateCollisions')}"
        )


def test_t1_f09_04_studio_map_pipeline_preserves_native_36x18x36_envelope_and_docks(
    node_probe: dict[str, Any],
    _tier1_workstation_grounding_audit: dict[str, Any],
) -> None:
    """F9.4: Studio map-*.js pipeline preserves 36x18x3.6m envelope, ±17.85m docks, and 0.86m robot chamfer."""
    env = ((node_probe.get("studioReplayAudit") or {}).get("postMapEnvelope") or {})
    slab = env.get("slabBox") or {}
    walls = env.get("wallsBox") or {}
    d1 = env.get("dock01Pos") or [0.0, 0.0, 0.0]
    d2 = env.get("dock02Pos") or [0.0, 0.0, 0.0]
    chamfer = _tier1_workstation_grounding_audit.get("postMapChamferBox") or {}

    assert math.isclose(slab["span"][0], 36.0, abs_tol=0.10)
    assert math.isclose(slab["span"][2], 18.0, abs_tol=0.10)
    assert math.isclose(walls["max"][1], 3.6, abs_tol=0.06)
    assert math.isclose(d1[0], -17.85, abs_tol=0.08)
    assert math.isclose(d2[0], 17.85, abs_tol=0.08)
    assert isinstance(chamfer.get("min"), list) and isinstance(chamfer.get("max"), list), (
        f"VIS_Bench_top_robot_chamfer missing after Studio map-*.js pipeline: {chamfer}"
    )
    assert 2.85 <= chamfer["min"][0] and chamfer["max"][0] <= 4.15
    assert math.isclose(chamfer["max"][1], 0.860, abs_tol=0.005)


def test_t1_f09_05_map_patch_pipeline_is_idempotent_and_never_double_expands_36m_glb(
    _tier1_workstation_grounding_audit: dict[str, Any],
) -> None:
    """F9.5: Applying map-*.js 3x is idempotent and native 36m GLBs are never double-expanded to 46.29m."""
    idem = _tier1_workstation_grounding_audit.get("mapIdempotency") or {}
    shipped = idem.get("shipped") or {}
    assert shipped.get("ok") is True, f"map-*.js non-idempotent on shipped GLBs: {shipped}"
    assert (
        shipped.get("pass1Meshes")
        == shipped.get("pass2Meshes")
        == shipped.get("pass3Meshes")
        == shipped.get("afterReapplyMeshes")
    )

    synth = idem.get("syntheticNative36m") or {}
    assert synth.get("ok") is True, f"map-*.js double-expanded synthetic native 36m scene: {synth}"
    synth_span_x = _num(synth, "slabSpanX", 0.0)
    assert math.isclose(synth_span_x, 36.0, abs_tol=0.10), (
        f"Native 36m scene expanded to {synth_span_x:.2f}m instead of staying 36.0m"
    )


def test_t1_f09_06_live_overhead_layer_toggle_andon_clone_isolation_and_scrub_determinism(
    node_probe: dict[str, Any],
) -> None:
    """F9.6: ENV_OVERHEAD toggles cleanly, Andon material clones are isolated, and timeline scrub is deterministic."""
    replay_audit = node_probe.get("studioReplayAudit") or {}
    assert replay_audit.get("overheadLayerToggleOk") is True

    la = ((node_probe.get("environmentAudit") or {}).get("layerAndAndon") or {})
    assert la.get("ovHiddenByDefault") is True
    assert la.get("ovVisibleAfterToggle") is True
    assert la.get("ovHiddenAfterRevert") is True
    assert la.get("cloneIsolationOk") is True, "Andon state bled across cloned environment scenes"
    assert la.get("dockSignalUnmutated") is True, "Robot Andon mutated DOCK_01_SIGNAL_RED shared material"

    for rid, s in _detailed_shifts(node_probe).items():
        assert _num(s, "maxScrubDeterminismErrM", 99.0) < 1e-6, (
            f"Non-deterministic timeline scrubbing drift on {rid}: {s.get('maxScrubDeterminismErrM')}"
        )


# ==============================================================================
# F10: Multi-Worker Spatial Separation & Full-Hall Routing — 6 Tests
# ==============================================================================


def test_t1_f10_01_stage3_parallel_packing_benches_avoid_overlap_up_to_8_workers(
    node_probe: dict[str, Any],
) -> None:
    """F10.1: Up to 5 and 6 parallel Stage-3 manual benches have 0 overlaps with racks, queues, or robot cell."""
    layouts = ((node_probe.get("spatialAudit") or {}).get("layouts") or {})
    for key in ("stage3_5slots", "stage3_6slots"):
        lay = layouts.get(key) or {}
        assert lay.get("ok") is True and lay.get("overlaps") == [], (
            f"Parallel Stage-3 bench collision in {key}: {lay}"
        )
        assert int(lay.get("parallelBenchCount") or 0) >= 4


def test_t1_f10_02_stages_1_2_4_parallel_workstations_avoid_overlap(
    node_probe: dict[str, Any],
) -> None:
    """F10.2: Multi-slot Stages 1, 2, and 4 workstations avoid overlap and 1-slot staffing spawns 0 clones."""
    layouts = ((node_probe.get("spatialAudit") or {}).get("layouts") or {})
    for key in ("stages124_3slots", "stage4_3slots"):
        lay = layouts.get(key) or {}
        assert lay.get("ok") is True and lay.get("overlaps") == [], (
            f"Parallel workstation overlap in {key}: {lay}"
        )
    single = layouts.get("singleWorkerMin") or {}
    assert single.get("ok") is True and single.get("parallelBenchCount") == 0


def test_t1_f10_03_astar_nav_grid_routes_across_full_36x18m_hall_and_corners(
    node_probe: dict[str, Any],
) -> None:
    """F10.3: A* navigation routes cleanly across the full [-17.6..+17.6] x [-8.6..+8.6]m 36x18m hall."""
    routes = ((node_probe.get("spatialAudit") or {}).get("astarRoutes") or {})
    for rkey in (
        "dock01_to_dock02",
        "sw_to_ne_corners",
        "dock01_to_stage1",
        "boundary_176_86",
        "trivial_same_point",
    ):
        rt = routes.get(rkey) or {}
        assert rt.get("ok") is True and rt.get("inBounds") is True, (
            f"A* route {rkey} clipped or failed inside 36x18m hall: {rt}"
        )
    assert int((routes.get("dock01_to_dock02") or {}).get("pointCount") or 0) >= 2


def test_t1_f10_04_worker_walk_paths_bypass_dynamic_parallel_benches(
    node_probe: dict[str, Any],
) -> None:
    """F10.4: Dynamic parallel benches are injected into A* obstacles so worker walk paths have 0 hits."""
    layouts = ((node_probe.get("spatialAudit") or {}).get("layouts") or {})
    for key in ("stage3_5slots", "stage3_6slots", "stages124_3slots", "stage4_3slots"):
        lay = layouts.get(key) or {}
        assert lay.get("pathHits") == 0, (
            f"Worker A* walk path cut through dynamic parallel bench in {key}: pathHits={lay.get('pathHits')}"
        )


def test_t1_f10_05_eight_break_points_distinct_and_reachable_from_all_stages(
    node_probe: dict[str, Any],
) -> None:
    """F10.5: All 8 BREAK_POINTS maintain >=0.55m separation and all 32 stage->break A* paths succeed."""
    bp = ((node_probe.get("spatialAudit") or {}).get("breakPoints") or {})
    assert int(bp.get("count") or 0) >= 8
    assert float(bp.get("minPairDistM") or 0.0) >= 0.55, (
        f"Break area slots overlap (minPairDistM={bp.get('minPairDistM')})"
    )
    assert bp.get("reachableFromStagesCount") == 32, (
        f"Expected 32/32 reachable stage->break paths, got {bp.get('reachableFromStagesCount')}"
    )


def test_t1_f10_06_queue_and_outcome_stack_positions_bounded_with_overflow_badges(
    node_probe: dict[str, Any],
) -> None:
    """F10.6: queueStackPositions and outcomeStackPositions cap visible items and report exact overflow counts."""
    stacks = ((node_probe.get("spatialAudit") or {}).get("stackSummary") or {})
    assert stacks.get("Q2_12") == {"visibleCount": 12, "overflow": 0}
    assert stacks.get("Q3_10") == {"visibleCount": 10, "overflow": 0}
    assert stacks.get("Q4_8") == {"visibleCount": 8, "overflow": 0}

    q1 = stacks.get("Q1_25") or {}
    assert 18 <= int(q1.get("visibleCount") or 0) <= 20 and int(q1.get("overflow") or 0) > 0
    assert int(q1["visibleCount"]) + int(q1["overflow"]) == 25, f"Q1_25 conservation mismatch: {q1}"

    r25 = stacks.get("R_25") or {}
    assert 14 <= int(r25.get("visibleCount") or 0) <= 20 and int(r25.get("overflow") or 0) > 0
    assert int(r25["visibleCount"]) + int(r25["overflow"]) == 25, f"R_25 conservation mismatch: {r25}"

    for out_key, total_n in (("good_20", 20), ("escaped_20", 20), ("scrap_15", 15)):
        entry = stacks.get(out_key) or {}
        vis = int(entry.get("visibleCount") or 0)
        ovf = int(entry.get("overflow") or 0)
        assert vis > 0 and ovf > 0 and vis + ovf == total_n, f"Invalid outcome stack cap on {out_key}: {entry}"


# ==============================================================================
# F11: Manifests, Checksums, Studio Asset Staging & Build Parity — 6 Tests
# ==============================================================================


def test_t1_f11_01_asset_stats_v02_sha256_bytes_and_bone_counts_match_all_15_glbs(
    v02_configs: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F11.1: asset_stats_v02.json SHA-256, byte sizes, and bone/clip counts match all 15 shipped GLBs."""
    stats = v02_configs.get("asset_stats_v02")
    assert isinstance(stats, dict), "4_Horses_Environment_v02/asset_stats_v02.json missing or invalid"
    raw_files = stats.get("files")
    if isinstance(raw_files, list):
        by_file = {entry["file"]: entry for entry in raw_files if isinstance(entry, dict) and "file" in entry}
    elif isinstance(raw_files, dict):
        by_file = raw_files
    else:
        by_file = {}

    gltf_val = node_probe.get("gltfValidation") or {}
    mismatches: list[str] = []
    for rel in ALL_15_GLBS:
        rec = by_file.get(rel)
        actual = gltf_val.get(rel) or {}
        if not isinstance(rec, dict):
            mismatches.append(f"{rel}:missing_in_asset_stats")
            continue
        if rec.get("sha256") != actual.get("sha256") or rec.get("bytes") != actual.get("bytes"):
            mismatches.append(
                f"{rel}:stats=({rec.get('bytes')},{str(rec.get('sha256'))[:12]})!=actual=({actual.get('bytes')},{str(actual.get('sha256'))[:12]})"
            )
    w_rec = by_file.get("modules/warehouse_worker.glb") or {}
    r_rec = by_file.get("modules/humanoid_robot.glb") or {}
    if w_rec.get("bones") != 35:
        mismatches.append(f"warehouse_worker.bones={w_rec.get('bones')}!=35")
    if r_rec.get("bones") != 41:
        mismatches.append(f"humanoid_robot.bones={r_rec.get('bones')}!=41")

    assert not mismatches, f"asset_stats_v02.json out of sync with live GLBs: {mismatches}"


def test_t1_f11_02_asset_manifest_and_character_manifests_synced_with_glbs(
    v02_configs: dict[str, Any],
) -> None:
    """F11.2: asset_manifest.json, worker_manifest.json, and robot_manifest.json reflect 35/41-bone v2.0 rigs."""
    am = v02_configs.get("asset_manifest")
    assert isinstance(am, (list, dict)), "4_Horses_Environment_v02/asset_manifest.json missing or invalid"
    entries = am if isinstance(am, list) else (am.get("assets") or am.get("files") or list(am.values()))
    by_file = {e.get("file"): e for e in entries if isinstance(e, dict) and e.get("file")}

    missing = [rel for rel in ALL_15_GLBS if rel not in by_file]
    assert not missing, f"asset_manifest.json missing GLB entries: {missing}"

    w_entry = by_file["modules/warehouse_worker.glb"]
    r_entry = by_file["modules/humanoid_robot.glb"]
    assert w_entry.get("bones") == 35, f"asset_manifest.json warehouse_worker bones={w_entry.get('bones')} != 35"
    assert r_entry.get("bones") == 41, f"asset_manifest.json humanoid_robot bones={r_entry.get('bones')} != 41"
    assert set(w_entry.get("clips") or []) == set(WORKER_17_CLIPS)
    assert set(r_entry.get("clips") or []) == set(ROBOT_14_CLIPS)


def test_t1_f11_03_studio_asset_hashes_lock_matches_all_15_v02_glbs(
    v02_configs: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F11.3: studio/asset-hashes.json lock matches SHA-256 and byte sizes of all 15 v02 GLBs."""
    bundle = node_probe.get("studioBundleAudit") or {}
    hashes = v02_configs.get("studio_asset_hashes")
    assert bundle.get("assetHashesExists") is True and isinstance(hashes, dict), (
        "studio/asset-hashes.json missing or unreadable"
    )
    files_map = hashes.get("files") if isinstance(hashes.get("files"), dict) else hashes
    gltf_val = node_probe.get("gltfValidation") or {}

    mismatches: list[str] = []
    for rel in ALL_15_GLBS:
        rec = files_map.get(f"4_Horses_Environment_v02/{rel}") or files_map.get(rel)
        actual = gltf_val.get(rel) or {}
        if not isinstance(rec, dict):
            mismatches.append(f"{rel}:missing_entry")
        elif rec.get("sha256") != actual.get("sha256") or rec.get("bytes") != actual.get("bytes"):
            mismatches.append(
                f"{rel}:lock=({rec.get('bytes')},{str(rec.get('sha256'))[:12]})!=v02=({actual.get('bytes')},{str(actual.get('sha256'))[:12]})"
            )
    assert not mismatches, f"studio/asset-hashes.json out of sync with 4_Horses_Environment_v02 GLBs: {mismatches}"


def test_t1_f11_04_studio_public_scene_staged_assets_have_sha256_parity_and_blueprint_preset(
    node_probe: dict[str, Any],
) -> None:
    """F11.4: studio/public/scene/ stages byte-identical scene player assets and supports camera presets."""
    bundle = node_probe.get("studioBundleAudit") or {}
    pub = bundle.get("publicScene") or {}
    assert pub.get("exists") is True, "studio/public/scene/ directory missing"
    assert set(STUDIO_SCENE_PLAYER_ASSETS) <= set(pub.get("presentAssets") or []), (
        f"Missing staged assets in studio/public/scene/: {pub.get('missingAssets')}"
    )
    assert pub.get("missingAssets") == []
    assert pub.get("parityMismatches") == [], (
        f"Stale staged assets in studio/public/scene/ differ from 4_Horses_Environment_v02/: {pub.get('parityMismatches')}"
    )

    presets = ((node_probe.get("studioReplayAudit") or {}).get("cameraPresets") or {})
    assert (presets.get("blueprint") or {}).get("supported") is True, (
        f"Studio top-down 'blueprint' camera preset not yet supported: {presets.get('blueprint')}"
    )
    assert (presets.get("rework") or {}).get("supported") is True, (
        f"Studio 'rework' camera preset not yet supported: {presets.get('rework')}"
    )


def test_t1_f11_05_studio_production_dist_bundle_and_dist_scene_assets_synced(
    node_probe: dict[str, Any],
) -> None:
    """F11.5: studio/dist/ contains built index.html + JS/CSS chunks and byte-identical studio/dist/scene/."""
    dist = ((node_probe.get("studioBundleAudit") or {}).get("dist") or {})
    assert dist.get("exists") is True and dist.get("indexHtmlExists") is True, (
        f"studio/dist/ production build missing: {dist}"
    )
    assert len(dist.get("jsFiles") or []) >= 1, f"No compiled JS bundle in studio/dist/assets/: {dist}"
    assert len(dist.get("cssFiles") or []) >= 1, f"No compiled CSS bundle in studio/dist/assets/: {dist}"

    dist_scene = dist.get("scene") or {}
    assert dist_scene.get("exists") is True, "studio/dist/scene/ missing"
    assert dist_scene.get("missingAssets") == [], (
        f"studio/dist/scene/ missing player assets: {dist_scene.get('missingAssets')}"
    )
    assert dist_scene.get("parityMismatches") == [], (
        f"studio/dist/scene/ SHA-256 mismatch vs 4_Horses_Environment_v02/: {dist_scene.get('parityMismatches')}"
    )


def test_t1_f11_06_v02_package_scripts_and_sandbox_npm_test_pass(
    v02_configs: dict[str, Any],
    _tier1_v02_npm_sandbox: dict[str, Any],
) -> None:
    """F11.6: 4_Horses_Environment_v02/package.json defines test scripts and check_v02.mjs exits 0 in sandbox."""
    pkg = v02_configs.get("v02_package_json")
    assert isinstance(pkg, dict), "4_Horses_Environment_v02/package.json missing"
    scripts = pkg.get("scripts") or {}
    assert isinstance(scripts.get("test"), str) and scripts["test"].strip(), (
        f"4_Horses_Environment_v02/package.json missing 'scripts.test': {scripts}"
    )

    assert _tier1_v02_npm_sandbox.get("ok") is True and _tier1_v02_npm_sandbox.get("returncode") == 0, (
        f"check_v02.mjs failed in isolated sandbox (rc={_tier1_v02_npm_sandbox.get('returncode')}): "
        f"stderr={_tier1_v02_npm_sandbox.get('stderr')[-500:]}"
    )


# ==============================================================================
# F12: High-Resolution Render Verification Suite — 6 Tests
# ==============================================================================


def test_t1_f12_01_environment_overview_png_meets_1600x1000_entropy_and_framing_gates(
    node_probe: dict[str, Any],
) -> None:
    """F12.1: environment_overview.png is >=1600x1000 with non-blank entropy, colour std, and W/C/E framing."""
    files = ((node_probe.get("pngAudit") or {}).get("files") or {})
    ov = files.get("environment_overview.png")
    assert isinstance(ov, dict) and ov.get("exists") is True and ov.get("valid") is True, (
        f"environment_overview.png missing or corrupt: {ov}"
    )
    errs = validate_render_quality(_node_png_to_py_metrics(ov), is_overview=True)
    assert errs == [], f"environment_overview.png failed quality/framing gates: {errs}"


def test_t1_f12_02_detail_packing_conveyor_and_storage_pngs_valid_and_distinct(
    node_probe: dict[str, Any],
) -> None:
    """F12.2: detail_{packing,conveyor,storage}.png are >=1200x800, high-entropy, and mutually distinct."""
    files = ((node_probe.get("pngAudit") or {}).get("files") or {})
    detail_names = ("detail_packing.png", "detail_conveyor.png", "detail_storage.png")
    hashes: set[str] = set()
    ov_sha = (files.get("environment_overview.png") or {}).get("sha256")
    for name in detail_names:
        entry = files.get(name)
        assert isinstance(entry, dict) and entry.get("exists") is True and entry.get("valid") is True, (
            f"{name} missing or corrupt: {entry}"
        )
        errs = validate_render_quality(
            _node_png_to_py_metrics(entry),
            is_overview=False,
            min_width=1200,
            min_height=800,
        )
        assert errs == [], f"{name} failed render quality check: {errs}"
        hashes.add(str(entry.get("sha256")))
        assert entry.get("sha256") != ov_sha, f"{name} is a duplicate copy of environment_overview.png"
    assert len(hashes) == 3, "detail_*.png renders contain duplicate SHA-256 images"


def test_t1_f12_03_renders_presentation_gallery_has_at_least_8_high_res_pngs(
    node_probe: dict[str, Any],
) -> None:
    """F12.3: 4_Horses_Environment_v02/renders_presentation/ contains >=8 valid >=1200x720 presentation PNGs."""
    files = ((node_probe.get("pngAudit") or {}).get("files") or {})
    pres = {
        rel: info
        for rel, info in files.items()
        if rel.startswith("renders_presentation/") and isinstance(info, dict)
    }
    assert len(pres) >= 8, (
        f"Expected >= 8 PNGs in 4_Horses_Environment_v02/renders_presentation/, found {len(pres)}: {sorted(pres)}"
    )
    quality_failures: dict[str, list[str]] = {}
    for rel, info in sorted(pres.items()):
        if not info.get("valid"):
            quality_failures[rel] = [str(info.get("error") or "invalid PNG")]
            continue
        errs = validate_render_quality(_node_png_to_py_metrics(info), min_width=1200, min_height=720)
        if errs:
            quality_failures[rel] = errs
    assert not quality_failures, f"Presentation renders failed quality checks: {quality_failures}"


def test_t1_f12_04_blueprint_topdown_and_all_9_workshop_zone_perspectives_present(
    node_probe: dict[str, Any],
) -> None:
    """F12.4: Presentation render set includes blueprint_topdown.png and covers all 9 workshop zones."""
    files = ((node_probe.get("pngAudit") or {}).get("files") or {})
    valid_paths = [
        rel
        for rel, info in files.items()
        if isinstance(info, dict)
        and info.get("valid") is True
        and (
            rel in ("environment_overview.png", "blueprint_topdown.png", "detail_packing.png", "detail_conveyor.png", "detail_storage.png")
            or rel.startswith("renders_presentation/")
            or rel.startswith("artifacts/player-check/")
        )
    ]
    blueprint_candidates = [p for p in valid_paths if "blueprint" in p.lower() or "topdown" in p.lower()]
    assert len(blueprint_candidates) >= 1, (
        f"Missing blueprint_topdown.png / top-down orthographic render among: {sorted(valid_paths)}"
    )
    for bp in blueprint_candidates:
        errs = validate_render_quality(_node_png_to_py_metrics(files[bp]), min_width=1200, min_height=720)
        assert errs == [], f"{bp} failed render quality check: {errs}"

    lower_paths = [p.lower() for p in valid_paths]
    zone_keywords = {
        "full_hall_overview": ("overview", "hall", "master"),
        "inbound_dock01_q1": ("inbound", "dock01", "dock_01", "q1", "arrival"),
        "stage1_prep": ("prep", "stage1", "stage_1", "s1"),
        "stage2_pick": ("pick", "stage2", "stage_2", "s2", "storage"),
        "stage3_pack_robot_assist": ("pack", "robot", "assist", "stage3", "stage_3"),
        "stage4_qc": ("qc", "inspect", "quality", "stage4", "stage_4"),
        "rework_north_lane": ("rework", "queue_r", "return"),
        "outbound_dispatch_dock02": ("outbound", "dispatch", "dock02", "dock_02", "shipping", "outcome"),
        "break_area": ("break", "kpi"),
    }
    missing_zones = [
        zone
        for zone, kws in zone_keywords.items()
        if not any(any(kw in p for kw in kws) for p in lower_paths)
    ]
    assert not missing_zones, (
        f"Presentation render suite missing required workshop zone perspectives {missing_zones} (found: {sorted(valid_paths)})"
    )


def test_t1_f12_05_both_native_blender_and_live_studio_webgl2_renders_present(
    node_probe: dict[str, Any],
) -> None:
    """F12.5: Render suite includes both native Blender renders and live Studio WebGL2 captures."""
    files = ((node_probe.get("pngAudit") or {}).get("files") or {})
    blender_renders = [
        rel
        for rel, info in files.items()
        if isinstance(info, dict)
        and info.get("valid") is True
        and (rel == "environment_overview.png" or (rel.startswith("renders_presentation/") and "studio" not in rel.lower()))
    ]
    studio_renders = [
        rel
        for rel, info in files.items()
        if isinstance(info, dict)
        and info.get("valid") is True
        and (
            rel.startswith("artifacts/player-check/")
            or (
                rel.startswith("renders_presentation/")
                and any(tag in rel.lower() for tag in ("studio", "player", "webgl", "live"))
            )
        )
    ]
    assert len(blender_renders) >= 4, f"Insufficient native Blender renders: {blender_renders}"
    assert len(studio_renders) >= 2, (
        f"Missing live Studio WebGL2 presentation renders in renders_presentation/ or artifacts/player-check/: {sorted(files)}"
    )
    for rel in studio_renders:
        info = files[rel]
        assert int(info.get("width") or 0) >= 900 and int(info.get("height") or 0) >= 600
        assert float(info.get("entropyBits") or 0.0) >= 2.0


def test_t1_f12_06_all_presentation_renders_have_100_percent_unique_sha256_hashes(
    node_probe: dict[str, Any],
) -> None:
    """F12.6: Every root and renders_presentation/ PNG is a genuinely distinct view (100% unique SHA-256)."""
    files = ((node_probe.get("pngAudit") or {}).get("files") or {})
    gallery = {
        rel: info
        for rel, info in files.items()
        if isinstance(info, dict)
        and info.get("valid") is True
        and (
            rel in ("environment_overview.png", "blueprint_topdown.png", "detail_packing.png", "detail_conveyor.png", "detail_storage.png")
            or rel.startswith("renders_presentation/")
        )
    }
    assert len(gallery) >= 11, (
        f"Expected >= 11 total root + renders_presentation/ PNGs (overview + 3 details + >=8 presentation), got {len(gallery)}"
    )
    by_hash: dict[str, list[str]] = {}
    for rel, info in sorted(gallery.items()):
        by_hash.setdefault(str(info.get("sha256")), []).append(rel)
    duplicates = {sha: paths for sha, paths in by_hash.items() if len(paths) > 1}
    assert not duplicates, f"Duplicate presentation PNG files detected: {duplicates}"


# ==============================================================================
# F13: Python Benchmark Engine & HTTP Bridge Integration — 6 Tests
# ==============================================================================


def test_t1_f13_01_frozen_python_core_pytest_suite_passes_with_zero_failures(
    core_pytest_report: dict[str, Any],
) -> None:
    """F13.1: Frozen Python benchmark core passes >=90 unit/integration tests with 0 failures and 0 errors."""
    assert core_pytest_report.get("exitcode") == 0, (
        f"Core pytest exited non-zero: {core_pytest_report}"
    )
    assert int(core_pytest_report.get("passed") or 0) >= 90
    assert core_pytest_report.get("failed") == 0
    assert core_pytest_report.get("errors") == 0


def test_t1_f13_02_frozen_python_core_and_world_spec_git_clean_and_compatible(
    repo_root: Path,
    core_pytest_report: dict[str, Any],
    v02_configs: dict[str, Any],
) -> None:
    """F13.2: Frozen Python core & benchmark contracts have 0 git diff (external workspace files untouched)."""
    import subprocess
    from tests_e2e.conftest import build_e2e_env

    assert core_pytest_report.get("frozen_core_git_diff_rc") == 0, (
        f"Frozen core modified: {core_pytest_report.get('frozen_core_git_diff')}"
    )
    assert core_pytest_report.get("frozen_core_git_status") == "", (
        f"Dirty git status in src/robotization_bench or data/world_spec.json: {core_pytest_report.get('frozen_core_git_status')}"
    )

    frozen_paths = [
        "src/robotization_bench",
        "data/world_spec.json",
        "tests",
        "scripts/export_3d_pack.py",
        "scripts/serve_3d.py",
        "studio/public/demo-pack",
    ]
    diff_proc = subprocess.run(
        ["git", "diff", "--exit-code", "HEAD", "--", *frozen_paths],
        cwd=str(repo_root),
        env=build_e2e_env(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert diff_proc.returncode == 0, (
        f"Immutable benchmark contract files modified: {diff_proc.stdout[:600]}"
    )

    world = v02_configs.get("world_spec")
    assert isinstance(world, dict) and isinstance(world.get("world_id"), str) and world["world_id"]
    if "quarterly" in world:
        assert isinstance(world["quarterly"], dict), "world_spec['quarterly'] must be a dict when present"


def test_t1_f13_03_export_3d_pack_generates_valid_9_v1_shift_bundles_and_index(
    exported_pack_report: dict[str, Any],
    exported_pack_dir: Path,
) -> None:
    """F13.3: export_3d_pack exports >=9 runs including all 9 required v1 shifts passing validate_shift_bundle."""
    from robotization_bench.reporting import validate_shift_bundle

    assert exported_pack_report.get("ok") is True, f"export_pack failed: {exported_pack_report.get('error')}"
    assert int(exported_pack_report.get("total_runs") or 0) >= 9
    assert exported_pack_report.get("all_9_v1_present") is True

    idx = exported_pack_report.get("index") or {}
    assert idx.get("pack_format") == "robotization-bench.3d-pack-index.v1"

    for rid in REQUIRED_9_V1_RUN_IDS:
        bdir = exported_pack_dir / rid
        assert (bdir / "manifest.json").is_file() and (bdir / "events.jsonl").is_file()
        audit = validate_shift_bundle(bdir)
        assert int(audit.get("event_count") or 0) > 100


def test_t1_f13_04_reference_policy_satisfies_benchmark_feasibility_and_win_gates(
    exported_pack_report: dict[str, Any],
) -> None:
    """F13.4: Reference optimal policy passes valid, feasible, and win gates vs manual baseline."""
    idx = exported_pack_report.get("index") or {}
    runs = idx.get("runs") or []
    by_id = {r["id"]: r for r in runs if isinstance(r, dict) and "id" in r}

    for seed in (11, 29, 47):
        ref_run = by_id.get(f"v1-reference-seed{seed}") or {}
        man_run = by_id.get(f"v1-manual-seed{seed}") or {}
        ev = ref_run.get("evaluation") or {}
        assert ev.get("valid") is True, f"Reference policy invalid on seed {seed}: {ev}"
        assert ev.get("feasible") is True, f"Reference policy infeasible on seed {seed}: {ev}"
        assert ev.get("win") is True, f"Reference policy failed benchmark win gate on seed {seed}: {ev}"
        ref_summary = ref_run.get("summary") or {}
        man_summary = man_run.get("summary") or {}
        if "net_profit" in ref_summary and "net_profit" in man_summary:
            assert float(ref_summary["net_profit"]) > float(man_summary["net_profit"])


def test_t1_f13_05_serve_3d_http_bridge_provides_cors_nosniff_head_options_and_206_range(
    _tier1_live_bridge: dict[str, Any],
) -> None:
    """F13.5: serve_3d.py serves GET/HEAD/OPTIONS with CORS+nosniff headers and 206 Partial Content byte ranges."""
    srv = _tier1_live_bridge.get("server") or {}
    assert srv.get("ready") is True, f"serve_3d.py failed to start: {srv}"
    checks = _tier1_live_bridge.get("http_checks") or {}

    get_idx = checks.get("get_index") or {}
    assert get_idx.get("status") == 200 and int(get_idx.get("bytes") or 0) > 100
    hdrs = get_idx.get("headers") or {}
    assert hdrs.get("access-control-allow-origin") == "*"
    assert hdrs.get("x-content-type-options") == "nosniff"
    assert "no-store" in str(hdrs.get("cache-control") or "")

    head_idx = checks.get("head_index") or {}
    assert head_idx.get("status") == 200 and head_idx.get("bytes") == 0
    assert int((head_idx.get("headers") or {}).get("content-length") or 0) == get_idx["bytes"]

    opt_idx = checks.get("options_index") or {}
    assert opt_idx.get("status") in (200, 204)
    allow_methods = str((opt_idx.get("headers") or {}).get("access-control-allow-methods") or "")
    for m in ("GET", "HEAD", "OPTIONS"):
        assert m in allow_methods

    rng = checks.get("range_events") or {}
    assert rng.get("status") == 206 and rng.get("bytes") == 64
    content_range = str((rng.get("headers") or {}).get("content-range") or "")
    assert content_range.startswith("bytes 0-63/"), f"Unexpected Content-Range header: {content_range}"


def test_t1_f13_06_studio_data_open_remote_loads_all_9_v1_runs_over_live_http_bridge(
    _tier1_live_bridge: dict[str, Any],
) -> None:
    """F13.6: Studio DataMod.openRemote loads all 9 v1 runs over live serve_3d.py HTTP with valid replay parsing."""
    remote = _tier1_live_bridge.get("remote_probe") or {}
    assert remote.get("ok") is True, f"Studio openRemote HTTP probe failed: {remote}"
    assert int(remote.get("totalRunsCount") or 0) >= 9
    loaded_ids = set(remote.get("loadedRunIds") or [])
    assert set(REQUIRED_9_V1_RUN_IDS) <= loaded_ids, (
        f"Missing v1 runs over live HTTP bridge: {sorted(set(REQUIRED_9_V1_RUN_IDS) - loaded_ids)}"
    )
    sample = remote.get("sampleInspection") or {}
    metrics = sample.get("metrics") or {}
    assert metrics.get("ended") is True and int(metrics.get("actors") or 0) >= 4, (
        f"Sample replay failed to execute shift to horizon over HTTP: {sample}"
    )
    assert sample.get("boundaryClampingOk") is True
