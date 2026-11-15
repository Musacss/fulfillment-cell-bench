"""Tier 2 Boundary Value Analysis (BVA), Corner & Negative-Input E2E Tests (F1–F13).

Coverage Map (78 Tests Total = 6 Genuine BVA / Negative / Corner Tests × 13 Core Features):
- F1  (test_t2_f01_01..06): Authoritative workshop_chain.json graph/schema/cross-ref negative mutations & queue BVA
- F2  (test_t2_f02_01..06): 36×18×3.6m hall knife-edge dock/lintel rays, 3.60m cap, 0 overhead beams/lamps, CAD clip, camera & anchors BVA
- F3  (test_t2_f03_01..06): Oversize queue spacing, Q1/Zone-01 margin, transfer port rays, tray volume, assist cylinder & decal ceiling BVA
- F4  (test_t2_f04_01..06): Corrupt GLB rejection, ±2mm floor/0.860m roller contacts, rack guide clearance, 0 NaN/degenerate tris & synthetic BVH sanity
- F5  (test_t2_f05_01..06): Adversarial worker GLB skinning/DemoSupport/phantom-prop/frozen-Assist/off-grid cadence rejections & adapter negatives
- F6  (test_t2_f06_01..06): Adversarial robot GLB leaked clips/blended armor/frozen recovery/static flaps & not_purchased/disabled/Andon BVA
- F7  (test_t2_f07_01..06): VIS_ROBOT_ASSIST yaw cosine BVA, <2.5cm grasp across 20 combos, >=0.858m non-penetration, 180° pole-flip & +12mm tray BVA
- F8  (test_t2_f08_01..06): Replay t=0/horizon/+50 clamping, NaN/Inf seek rejection, idle post-break walk, scrub determinism, roller drift & rework BVA
- F9  (test_t2_f09_01..06): Empty-hand zero prop leak, active bench zero duplicate order, _Oversize clips, native-36m map no-double-scale & pool negatives
- F10 (test_t2_f10_01..06): 1-worker vs 8-worker parallel bench extremes, ±17.6/±8.6 wall-boundary & trivial A*, NaN/trap & invalid slot rejections, stack caps
- F11 (test_t2_f11_01..06): prepare-assets 1-byte tamper rejection, exact 14 module GLBs, dual-copy JSON parity, asset-hashes/scene parity & v02 sandbox check
- F12 (test_t2_f12_01..06): Corrupt PNG magic/CRC32/IDAT/IEND/filter rejections, solid/low-entropy gates, exact resolution BVA, East-clipping & hash uniqueness
- F13 (test_t2_f13_01..06): serve_3d 400/403/404/405/416/206 security & range BVA, export_3d_pack safe-dir/seeds, ReplayError/DataError & Python Plan BVA
"""

from __future__ import annotations

import copy
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
from typing import Any, Iterator
import zlib

import pytest

from tests_e2e.conftest import (
    REQUIRED_9_V1_RUN_IDS,
    build_e2e_env,
    is_stage3_pack_station,
)
from tests_e2e.helpers.chain_validator import (
    make_reference_workshop_chain,
    normalize_zone_bounds,
    validate_workshop_chain,
)
from tests_e2e.helpers.png_validator import (
    PNG_SIG,
    inspect_png_bytes,
    make_synthetic_png,
    validate_render_quality,
)

ALL_15_GLB_RELS = (
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

CANONICAL_WORKER_CLIPS = frozenset(
    {
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
    }
)

CANONICAL_ROBOT_CLIPS = frozenset(
    {
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
    }
)

_COMPONENT_BYTES = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
_TYPE_ARITY = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}


def _stage_by_id(chain: dict[str, Any], stage_id: str) -> dict[str, Any]:
    return next(st for st in chain["stages"] if st["id"] == stage_id)


def _parse_glb_binary(raw: bytes) -> tuple[dict[str, Any], bytearray]:
    magic, version, total_len = struct.unpack_from("<III", raw, 0)
    assert magic == 0x46546C67 and version == 2 and total_len <= len(raw)
    json_len, json_type = struct.unpack_from("<II", raw, 12)
    assert json_type == 0x4E4F534A
    doc = json.loads(raw[20 : 20 + json_len].decode("utf-8"))
    bin_pos = 20 + json_len
    if bin_pos + 8 <= len(raw):
        bin_len, bin_type = struct.unpack_from("<II", raw, bin_pos)
        assert bin_type == 0x004E4942
        bin_buf = bytearray(raw[bin_pos + 8 : bin_pos + 8 + bin_len])
    else:
        bin_buf = bytearray()
    return doc, bin_buf


def _serialize_glb_binary(doc: dict[str, Any], bin_buf: bytearray) -> bytes:
    bin_out = bytearray(bin_buf)
    while len(bin_out) % 4 != 0:
        bin_out.append(0)
    if doc.get("buffers"):
        doc["buffers"][0]["byteLength"] = len(bin_out)
    else:
        doc["buffers"] = [{"byteLength": len(bin_out)}]
    json_bytes = bytearray(json.dumps(doc, separators=(",", ":")).encode("utf-8"))
    while len(json_bytes) % 4 != 0:
        json_bytes.append(0x20)
    total_len = 12 + 8 + len(json_bytes) + 8 + len(bin_out)
    return (
        struct.pack("<III", 0x46546C67, 2, total_len)
        + struct.pack("<II", len(json_bytes), 0x4E4F534A)
        + bytes(json_bytes)
        + struct.pack("<II", len(bin_out), 0x004E4942)
        + bytes(bin_out)
    )


def _read_accessor_contiguous(doc: dict[str, Any], bin_buf: bytearray, acc_idx: int) -> tuple[dict[str, Any], bytearray]:
    acc = doc["accessors"][acc_idx]
    bv = doc["bufferViews"][acc["bufferView"]]
    elem_bytes = _COMPONENT_BYTES[acc["componentType"]] * _TYPE_ARITY[acc["type"]]
    stride = bv.get("byteStride") or elem_bytes
    base_off = (bv.get("byteOffset") or 0) + (acc.get("byteOffset") or 0)
    out = bytearray(acc["count"] * elem_bytes)
    for i in range(acc["count"]):
        src = base_off + i * stride
        out[i * elem_bytes : (i + 1) * elem_bytes] = bin_buf[src : src + elem_bytes]
    return acc, out


def _append_accessor(
    doc: dict[str, Any],
    bin_buf: bytearray,
    payload: bytes | bytearray,
    *,
    component_type: int,
    count: int,
    acc_type: str,
    min_vals: list[float | int] | None = None,
    max_vals: list[float | int] | None = None,
) -> int:
    while len(bin_buf) % 4 != 0:
        bin_buf.append(0)
    offset = len(bin_buf)
    bin_buf.extend(payload)
    bvs = doc.setdefault("bufferViews", [])
    bv_idx = len(bvs)
    bvs.append({"buffer": 0, "byteOffset": offset, "byteLength": len(payload)})
    accs = doc.setdefault("accessors", [])
    acc_idx = len(accs)
    entry: dict[str, Any] = {
        "bufferView": bv_idx,
        "byteOffset": 0,
        "componentType": component_type,
        "count": count,
        "type": acc_type,
    }
    if min_vals is not None:
        entry["min"] = min_vals
    if max_vals is not None:
        entry["max"] = max_vals
    accs.append(entry)
    return acc_idx


def _freeze_sampler_output(doc: dict[str, Any], bin_buf: bytearray, sampler: dict[str, Any]) -> None:
    acc, raw_out = _read_accessor_contiguous(doc, bin_buf, sampler["output"])
    elem_bytes = _COMPONENT_BYTES[acc["componentType"]] * _TYPE_ARITY[acc["type"]]
    if acc["count"] <= 0 or len(raw_out) < elem_bytes:
        return
    first_frame = bytes(raw_out[:elem_bytes])
    frozen_payload = first_frame * acc["count"]
    sampler["output"] = _append_accessor(
        doc,
        bin_buf,
        frozen_payload,
        component_type=acc["componentType"],
        count=acc["count"],
        acc_type=acc["type"],
    )


def _build_adversarial_worker_glb(src_bytes: bytes) -> bytes:
    """Create a mutated worker GLB testing F5 skinning, DemoSupport, prop scale, Assist & 30-FPS cadence."""
    doc, bin_buf = _parse_glb_binary(src_bytes)
    nodes = doc.setdefault("nodes", [])
    prop_re = re.compile(r"_(OpenCarton|DemoCarton|Carton|Flap_|Product|PickingTote|SealingTape)|^prop_", re.I)

    # 1. Zero vertex 0 skinWeight & inject out-of-range bone index 99 on vertex 1 of first body SkinnedMesh
    skinned_node = next(
        (n for n in nodes if "skin" in n and "mesh" in n and not prop_re.search(n.get("name", ""))),
        next((n for n in nodes if "skin" in n and "mesh" in n), None),
    )
    assert skinned_node is not None, "Worker GLB lacks skinned mesh node"
    prim = doc["meshes"][skinned_node["mesh"]]["primitives"][0]
    w_acc, w_raw = _read_accessor_contiguous(doc, bin_buf, prim["attributes"]["WEIGHTS_0"])
    j_acc, j_raw = _read_accessor_contiguous(doc, bin_buf, prim["attributes"]["JOINTS_0"])
    assert w_acc["componentType"] == 5126 and w_acc["count"] >= 2
    struct.pack_into("<ffff", w_raw, 0, 0.0, 0.0, 0.0, 0.0)
    struct.pack_into("<ffff", w_raw, 16, 1.0, 0.0, 0.0, 0.0)
    j_fmt = "<BBBB" if j_acc["componentType"] == 5121 else "<HHHH"
    j_stride = 4 if j_acc["componentType"] == 5121 else 8
    struct.pack_into(j_fmt, j_raw, j_stride, 99, 0, 0, 0)
    prim["attributes"]["WEIGHTS_0"] = _append_accessor(
        doc, bin_buf, w_raw, component_type=5126, count=w_acc["count"], acc_type="VEC4"
    )
    prim["attributes"]["JOINTS_0"] = _append_accessor(
        doc, bin_buf, j_raw, component_type=j_acc["componentType"], count=j_acc["count"], acc_type="VEC4"
    )

    # 2. Inject forbidden WORKER_DemoSupport node & flip one prop mesh to demo_only=True / operation_prop=False
    demo_idx = len(nodes)
    nodes.append({"name": "WORKER_DemoSupport", "extras": {"handling_prop": "support"}})
    doc["scenes"][0].setdefault("nodes", []).append(demo_idx)

    prop_mesh_node = next((n for n in reversed(nodes) if "mesh" in n and prop_re.search(n.get("name", ""))), None)
    if prop_mesh_node is not None:
        prop_mesh_node["extras"] = {"operation_prop": False, "demo_only": True, "handling_prop": "tampered"}
    else:
        pos_acc = _append_accessor(
            doc,
            bin_buf,
            struct.pack("<9f", 0.0, 0.0, 0.0, 0.1, 0.0, 0.0, 0.0, 0.1, 0.0),
            component_type=5126,
            count=3,
            acc_type="VEC3",
            min_vals=[0.0, 0.0, 0.0],
            max_vals=[0.1, 0.1, 0.0],
        )
        m_idx = len(doc.setdefault("meshes", []))
        doc["meshes"].append({"name": "WORKER_TamperedCartonMesh", "primitives": [{"attributes": {"POSITION": pos_acc}}]})
        n_idx = len(nodes)
        nodes.append(
            {
                "name": "WORKER_TamperedCarton",
                "mesh": m_idx,
                "extras": {"operation_prop": False, "demo_only": True, "handling_prop": "tampered"},
            }
        )
        doc["scenes"][0]["nodes"].append(n_idx)

    # 3. Force non-zero (1,1,1) prop scale in Idle
    prop_node_indices = [idx for idx, n in enumerate(nodes) if (n.get("name") or "").startswith("prop_")]
    idle_anim = next((a for a in doc.get("animations", []) if a.get("name") == "Idle"), None)
    if idle_anim is not None and prop_node_indices:
        patched_idle_scale = 0
        for ch in idle_anim.get("channels", []):
            tgt = ch.get("target") or {}
            if tgt.get("path") == "scale" and tgt.get("node") in prop_node_indices:
                smp = idle_anim["samplers"][ch["sampler"]]
                out_acc, _ = _read_accessor_contiguous(doc, bin_buf, smp["output"])
                ones = struct.pack("<fff", 1.0, 1.0, 1.0) * out_acc["count"]
                smp["output"] = _append_accessor(
                    doc,
                    bin_buf,
                    ones,
                    component_type=5126,
                    count=out_acc["count"],
                    acc_type="VEC3",
                    min_vals=[1.0, 1.0, 1.0],
                    max_vals=[1.0, 1.0, 1.0],
                )
                patched_idle_scale += 1
        if patched_idle_scale == 0 and idle_anim.get("samplers"):
            in_acc_idx = idle_anim["samplers"][0]["input"]
            in_acc = doc["accessors"][in_acc_idx]
            ones = struct.pack("<fff", 1.0, 1.0, 1.0) * in_acc["count"]
            out_idx = _append_accessor(
                doc,
                bin_buf,
                ones,
                component_type=5126,
                count=in_acc["count"],
                acc_type="VEC3",
                min_vals=[1.0, 1.0, 1.0],
                max_vals=[1.0, 1.0, 1.0],
            )
            for p_node in prop_node_indices:
                s_idx = len(idle_anim["samplers"])
                idle_anim["samplers"].append({"input": in_acc_idx, "interpolation": "LINEAR", "output": out_idx})
                idle_anim.setdefault("channels", []).append(
                    {"sampler": s_idx, "target": {"node": p_node, "path": "scale"}}
                )

    # 4. Freeze Assist to 0.0m skeletal excursion
    assist_anim = next((a for a in doc.get("animations", []) if a.get("name") == "Assist"), None)
    if assist_anim is not None:
        for smp in assist_anim.get("samplers", []):
            _freeze_sampler_output(doc, bin_buf, smp)

    # 5. Perturb 1 keyframe timestamp in Walk by +0.009s off the 30-FPS grid
    walk_anim = next((a for a in doc.get("animations", []) if a.get("name") == "Walk"), None)
    if walk_anim is not None:
        smp0 = next(
            (s for s in walk_anim.get("samplers", []) if doc["accessors"][s["input"]]["count"] >= 3),
            None,
        )
        if smp0 is not None:
            t_acc, t_raw = _read_accessor_contiguous(doc, bin_buf, smp0["input"])
            times = list(struct.unpack(f"<{t_acc['count']}f", t_raw))
            times[1] = float(times[1] + 0.009)
            new_t_raw = struct.pack(f"<{len(times)}f", *times)
            smp0["input"] = _append_accessor(
                doc,
                bin_buf,
                new_t_raw,
                component_type=5126,
                count=len(times),
                acc_type="SCALAR",
                min_vals=[min(times)],
                max_vals=[max(times)],
            )

    return _serialize_glb_binary(doc, bin_buf)


def _build_adversarial_robot_glb(src_bytes: bytes) -> bytes:
    """Create a mutated robot GLB testing F6 forbidden clips, blended armor, frozen Service/Jammed & F7 180° flip."""
    doc, bin_buf = _parse_glb_binary(src_bytes)
    nodes = doc.setdefault("nodes", [])
    prop_re = re.compile(r"_(OpenCarton|DemoCarton|Carton|Flap_|Product|PickingTote|SealingTape)|^prop_", re.I)

    # 1. InjectROBOT_DemoSupport & blended 2-bone non-rigid weight on ROBOT_Body armor
    demo_idx = len(nodes)
    nodes.append({"name": "ROBOT_DemoSupport", "extras": {"handling_prop": "support"}})
    doc["scenes"][0].setdefault("nodes", []).append(demo_idx)

    armor_node = next(
        (n for n in nodes if "skin" in n and "mesh" in n and not prop_re.search(n.get("name", ""))),
        None,
    )
    assert armor_node is not None, "Robot GLB lacks body armor SkinnedMesh"
    skin_joints = doc["skins"][armor_node["skin"]]["joints"]
    body_joint_slots = [
        slot
        for slot, n_idx in enumerate(skin_joints)
        if not (nodes[n_idx].get("name") or "").startswith("prop_")
    ]
    assert len(body_joint_slots) >= 2
    j_a, j_b = body_joint_slots[1], body_joint_slots[2]

    prim = doc["meshes"][armor_node["mesh"]]["primitives"][0]
    w_acc, w_raw = _read_accessor_contiguous(doc, bin_buf, prim["attributes"]["WEIGHTS_0"])
    j_acc, j_raw = _read_accessor_contiguous(doc, bin_buf, prim["attributes"]["JOINTS_0"])
    struct.pack_into("<ffff", w_raw, 0, 0.5, 0.5, 0.0, 0.0)
    j_fmt = "<BBBB" if j_acc["componentType"] == 5121 else "<HHHH"
    struct.pack_into(j_fmt, j_raw, 0, j_a, j_b, 0, 0)
    prim["attributes"]["WEIGHTS_0"] = _append_accessor(
        doc, bin_buf, w_raw, component_type=5126, count=w_acc["count"], acc_type="VEC4"
    )
    prim["attributes"]["JOINTS_0"] = _append_accessor(
        doc, bin_buf, j_raw, component_type=j_acc["componentType"], count=j_acc["count"], acc_type="VEC4"
    )

    # 2. Append forbidden non-Stage-3 clips Pick & Inspect_Oversize (cloned before mutating Idle)
    anims = doc.setdefault("animations", [])
    idle_orig = next((a for a in anims if a.get("name") == "Idle"), anims[0])
    for leaked_name in ("Pick", "Inspect_Oversize"):
        leaked = copy.deepcopy(idle_orig)
        leaked["name"] = leaked_name
        anims.append(leaked)

    # 3. Freeze Service & Jammed completely + freeze prop_flap_left & prop_tape in RobotPack
    for freeze_name in ("Service", "Jammed"):
        anim = next((a for a in anims if a.get("name") == freeze_name), None)
        if anim is not None:
            for smp in anim.get("samplers", []):
                _freeze_sampler_output(doc, bin_buf, smp)

    rpack_anim = next((a for a in anims if a.get("name") == "RobotPack"), None)
    if rpack_anim is not None:
        frozen_prop_targets = {
            idx
            for idx, n in enumerate(nodes)
            if (n.get("name") or "") in ("prop_flap_left", "prop_tape", "prop_box")
        }
        for ch in rpack_anim.get("channels", []):
            if (ch.get("target") or {}).get("node") in frozen_prop_targets:
                _freeze_sampler_output(doc, bin_buf, rpack_anim["samplers"][ch["sampler"]])

    # 4. Inject a single-frame 180° orthogonal quaternion pole flip on a body bone in Idle (F7_04)
    body_node_set = {
        n_idx for n_idx in skin_joints if not (nodes[n_idx].get("name") or "").startswith("prop_")
    }
    rot_ch = next(
        (
            ch
            for ch in idle_orig.get("channels", [])
            if (ch.get("target") or {}).get("path") == "rotation"
            and (ch.get("target") or {}).get("node") in body_node_set
            and doc["accessors"][idle_orig["samplers"][ch["sampler"]]["output"]]["count"] >= 3
        ),
        None,
    )
    if rot_ch is not None:
        smp_rot = idle_orig["samplers"][rot_ch["sampler"]]
        q_acc, q_raw = _read_accessor_contiguous(doc, bin_buf, smp_rot["output"])
        qx, qy, qz, qw = struct.unpack_from("<ffff", q_raw, 0)
        q_norm = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw) or 1.0
        qx, qy, qz, qw = qx / q_norm, qy / q_norm, qz / q_norm, qw / q_norm
        # Orthogonal unit quaternion: q0 · (-qw, qz, -qy, qx) == 0 => exact 180.0° step!
        struct.pack_into("<ffff", q_raw, 16, -qw, qz, -qy, qx)
        smp_rot["output"] = _append_accessor(
            doc, bin_buf, q_raw, component_type=5126, count=q_acc["count"], acc_type="VEC4"
        )

    return _serialize_glb_binary(doc, bin_buf)


@pytest.fixture(scope="module")
def reference_chain_env() -> dict[str, Any]:
    """Deterministic baseline scene/clip universe matching make_reference_workshop_chain()."""
    ref_chain = make_reference_workshop_chain()
    scene_nodes: set[str] = set()
    for st in ref_chain["stages"]:
        scene_nodes.update(st["equipment_nodes"])
        scene_nodes.update(st["conveyor_segments"])
        if st["work_anchor"]:
            scene_nodes.add(st["work_anchor"])
        if st["order_anchor"]:
            scene_nodes.add(st["order_anchor"])
    bindings = {"format": "four-horses.visual-bindings.v1"}
    baseline_errors = validate_workshop_chain(
        ref_chain,
        bindings,
        scene_nodes,
        set(CANONICAL_WORKER_CLIPS),
        set(CANONICAL_ROBOT_CLIPS),
    )
    assert baseline_errors == [], f"Reference workshop chain must be clean: {baseline_errors}"
    return {
        "bindings": bindings,
        "scene_nodes": scene_nodes,
        "worker_clips": set(CANONICAL_WORKER_CLIPS),
        "robot_clips": set(CANONICAL_ROBOT_CLIPS),
    }


@pytest.fixture(scope="module")
def corrupt_glb_probes(session_tmp_dir: Path, v02_dir: Path, run_custom_glb_probe) -> dict[str, Any]:
    """Run gltf-validator on 2 synthetic corrupt GLBs in session_tmp_dir (2 of 4 custom GLB calls)."""
    out_dir = session_tmp_dir / "t2_corrupt_glbs"
    out_dir.mkdir(parents=True, exist_ok=True)

    bad_magic_path = out_dir / "bad_magic.glb"
    bad_magic_path.write_bytes(b"BAD!" + struct.pack("<II", 2, 32) + b"\x00" * 20)

    src_glb = (v02_dir / "modules" / "carton_closed.glb").read_bytes()
    trunc_bin_path = out_dir / "truncated_bin.glb"
    # Keep header totalLength & BIN chunk length intact, but chop the final 64 bytes of the BIN payload
    trunc_bin_path.write_bytes(src_glb[:-64])

    return {
        "bad_magic": run_custom_glb_probe(bad_magic_path, mode="validate-glb"),
        "truncated_bin": run_custom_glb_probe(trunc_bin_path, mode="validate-glb"),
    }


@pytest.fixture(scope="module")
def adversarial_worker_glb_probe(session_tmp_dir: Path, v02_dir: Path, run_custom_glb_probe) -> dict[str, Any]:
    """Run probe-custom-glb once on a binary-patched worker GLB in session_tmp_dir (3 of 4 custom GLB calls)."""
    out_dir = session_tmp_dir / "t2_mutated_glbs"
    out_dir.mkdir(parents=True, exist_ok=True)
    src = (v02_dir / "modules" / "warehouse_worker.glb").read_bytes()
    mut_path = out_dir / "t2_mutated_worker.glb"
    mut_path.write_bytes(_build_adversarial_worker_glb(src))
    return run_custom_glb_probe(mut_path, mode="probe-custom-glb", kind="worker")


@pytest.fixture(scope="module")
def adversarial_robot_glb_probe(session_tmp_dir: Path, v02_dir: Path, run_custom_glb_probe) -> dict[str, Any]:
    """Run probe-custom-glb once on a binary-patched robot GLB in session_tmp_dir (4 of 4 custom GLB calls)."""
    out_dir = session_tmp_dir / "t2_mutated_glbs"
    out_dir.mkdir(parents=True, exist_ok=True)
    src = (v02_dir / "modules" / "humanoid_robot.glb").read_bytes()
    mut_path = out_dir / "t2_mutated_robot.glb"
    mut_path.write_bytes(_build_adversarial_robot_glb(src))
    return run_custom_glb_probe(mut_path, mode="probe-custom-glb", kind="robot")


@pytest.fixture(scope="module")
def live_serve_3d_pack(
    repo_root: Path,
    exported_pack_dir: Path,
    session_tmp_dir: Path,
    ephemeral_serve_3d,
) -> Iterator[dict[str, Any]]:
    """Single module-scoped serve_3d.py instance over a temp pack copy containing a test symlink."""
    serve_pack = session_tmp_dir / "t2_serve_pack"
    if serve_pack.exists():
        shutil.rmtree(serve_pack)
    shutil.copytree(exported_pack_dir, serve_pack)
    symlink_target = repo_root / "pyproject.toml"
    (serve_pack / "evil_symlink.json").symlink_to(symlink_target)
    with ephemeral_serve_3d(pack_dir=serve_pack) as srv:
        yield {**srv, "serve_pack": serve_pack}


_FORBIDDEN_OVERHEAD_RE = re.compile(
    r"OVERHEAD_TRUSS|OVERHEAD_CABLE_TRAY|HIGHBAY|ENV_LIGHTING_RIG|CEILING_BEAM|HANGING_LAMP",
    re.I,
)


def _find_forbidden_overhead_clutter_in_glb(raw_glb: bytes) -> dict[str, list[str]]:
    """Inspect GLB scene hierarchy for forbidden overhead beam/truss/cable-tray/lamp meshes."""
    doc, _ = _parse_glb_binary(raw_glb)
    nodes = doc.get("nodes") or []
    parent_of: dict[int, int] = {}
    for idx, node in enumerate(nodes):
        for ch in node.get("children") or []:
            parent_of[int(ch)] = idx

    forbidden_mesh_nodes: list[str] = []
    env_overhead_mesh_nodes: list[str] = []
    for idx, node in enumerate(nodes):
        if "mesh" not in node:
            continue
        chain_names: list[str] = []
        cur: int | None = idx
        seen: set[int] = set()
        while cur is not None and cur not in seen and 0 <= cur < len(nodes):
            seen.add(cur)
            chain_names.append(str(nodes[cur].get("name") or f"node_{cur}"))
            cur = parent_of.get(cur)
        label = "/".join(reversed(chain_names))
        if any(_FORBIDDEN_OVERHEAD_RE.search(nm) for nm in chain_names):
            forbidden_mesh_nodes.append(label)
        if any(nm == "ENV_OVERHEAD" for nm in chain_names):
            env_overhead_mesh_nodes.append(label)
    return {
        "forbidden_mesh_nodes": sorted(set(forbidden_mesh_nodes)),
        "env_overhead_mesh_nodes": sorted(set(env_overhead_mesh_nodes)),
    }


@pytest.fixture(scope="module")
def direct_studio_bva_probe(
    repo_root: Path,
    v02_dir: Path,
    exported_pack_dir: Path,
    session_tmp_dir: Path,
) -> dict[str, Any]:
    """Direct headless Node v24 BVA probe exercising studio/src/{data,replay,scene,map-*}.js in session_tmp_dir."""
    src_dir = str(repo_root / "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    from robotization_bench import contracts, economics, engine, reporting, scenarios, validation

    rework_bundle_dir = session_tmp_dir / "t2_saturated_rework_bundle"
    if rework_bundle_dir.exists():
        shutil.rmtree(rework_bundle_dir)
    world = contracts.load_world()
    day11 = scenarios.generate(world, 11)
    # Bare-carton robot bypass + 2 QC workers + single manual Stage-3 worker => saturates Stage 3 so Queue R fills
    sat_plan = validation.parse_plan(
        {
            "schema_version": 1,
            "robot": True,
            "trays": False,
            "route": "bypass",
            "workers": [[1], [1], [2], [2], [3], [4], [4]],
        },
        world,
    )
    sat_raw = engine.simulate(world, sat_plan, day11, trace=True)
    sat_econ = economics.calculate(world, sat_plan, sat_raw)
    reporting.export_shift_bundle(world, sat_plan, day11, sat_raw, sat_econ, rework_bundle_dir)

    probe_dir = session_tmp_dir / "t2_direct_studio_probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    mjs_path = probe_dir / "run_direct_studio_bva.mjs"
    out_path = probe_dir / "direct_studio_bva.json"

    studio_nm = (repo_root / "studio" / "node_modules").as_posix()
    v02_nm = (v02_dir / "node_modules").as_posix()
    studio_src = (repo_root / "studio" / "src").as_posix()

    mjs_code = f"""
import fs from 'node:fs/promises';
import fsSync from 'node:fs';
import path from 'node:path';
import {{ pathToFileURL }} from 'node:url';

const studioNmDir = {json.dumps(str(studio_nm))};
const v02NmDir = {json.dumps(str(v02_nm))};
const studioSrcDir = {json.dumps(str(studio_src))};
const toFileHref = (base, rel) => pathToFileURL(fsSync.realpathSync(path.join(base, rel))).href;

const THREE = await import(toFileHref(studioNmDir, 'three/build/three.module.js'));
const {{ GLTFLoader }} = await import(toFileHref(studioNmDir, 'three/examples/jsm/loaders/GLTFLoader.js'));
const THREE_V02 = await import(toFileHref(v02NmDir, 'three/build/three.module.js'));
const DataMod = await import(toFileHref(studioSrcDir, 'data.js'));
const {{ createReplay, COUNTER_KEYS }} = await import(toFileHref(studioSrcDir, 'replay.js'));
const {{ createScenePlayer }} = await import(toFileHref(studioSrcDir, 'scene.js'));
const MapGeomMod = await import(toFileHref(studioSrcDir, 'map-geometry.js'));
const MapLayoutMod = await import(toFileHref(studioSrcDir, 'map-layout.js'));
const MapFloorMod = await import(toFileHref(studioSrcDir, 'map-floor.js'));

const v02Dir = {json.dumps(str(v02_dir))};
const packDir = {json.dumps(str(exported_pack_dir))};
const reworkBundleDir = {json.dumps(str(rework_bundle_dir))};
const outFile = {json.dumps(str(out_path))};
const required9 = {json.dumps(list(REQUIRED_9_V1_RUN_IDS))};

let capturedScene = null;
const routePrefix = 'http://local.t2probe/__v02__/';

globalThis.window = globalThis;
globalThis.self = globalThis;
globalThis.devicePixelRatio = 1;
globalThis.requestAnimationFrame ??= () => 0;
globalThis.cancelAnimationFrame ??= () => {{}};
globalThis.ResizeObserver ??= class {{ observe() {{}} unobserve() {{}} disconnect() {{}} }};
globalThis.ProgressEvent ??= class ProgressEvent extends Event {{
  constructor(type, init = {{}}) {{ super(type); this.lengthComputable = Boolean(init.lengthComputable); this.loaded = init.loaded ?? 0; this.total = init.total ?? 0; }}
}};

const glConsts = {{
  POINTS: 0, LINES: 1, LINE_LOOP: 2, LINE_STRIP: 3, TRIANGLES: 4, TRIANGLE_STRIP: 5, TRIANGLE_FAN: 6,
  VERSION: 0x1F02, SHADING_LANGUAGE_VERSION: 0x8B8C, VENDOR: 0x1F00, RENDERER: 0x1F01,
  MAX_TEXTURE_SIZE: 0x0D33, MAX_CUBE_MAP_TEXTURE_SIZE: 0x851C, MAX_RENDERBUFFER_SIZE: 0x84E8,
  MAX_VIEWPORT_DIMS: 0x0D3A, COMPILE_STATUS: 0x8B81, LINK_STATUS: 0x8B82, FRAMEBUFFER_COMPLETE: 0x8CD5,
}};
const gl2 = new Proxy({{}}, {{
  get(_t, prop) {{
    if (prop in glConsts) return glConsts[prop];
    if (prop === 'getParameter') return (p) => {{
      if (p === 0x1F02) return 'WebGL 2.0';
      if (p === 0x8B8C) return 'WebGL GLSL ES 3.00';
      if (p === 0x1F00 || p === 0x1F01) return 'HeadlessStub';
      if (p === 0x0D3A) return new Int32Array([8192, 8192]);
      if ([0x0D33, 0x851C, 0x84E8].includes(p)) return 8192;
      return 32;
    }};
    if (prop === 'getExtension') return (n) => (n === 'EXT_color_buffer_float' ? {{}} : null);
    if (prop === 'getSupportedExtensions') return () => ['EXT_color_buffer_float'];
    if (prop === 'getShaderPrecisionFormat') return () => ({{ rangeMin: 127, rangeMax: 127, precision: 23 }});
    if (prop === 'getShaderParameter') return () => true;
    if (prop === 'getProgramParameter') return (_pr, p) => (p === 0x8B82 || p === 0x8B83 ? true : 0);
    if (prop === 'getActiveUniform' || prop === 'getActiveAttrib') return () => ({{ name: '', size: 1, type: 0x1406 }});
    if (prop === 'getUniformIndices' || prop === 'getActiveUniforms') return (_pr, arr) => (arr ?? []).map(() => 0);
    if (prop === 'checkFramebufferStatus') return () => 0x8CD5;
    if (prop === 'getContextAttributes') return () => ({{ alpha: false, antialias: true, depth: true, stencil: true }});
    if (['createTexture','createBuffer','createFramebuffer','createRenderbuffer','createProgram','createShader','createVertexArray','getUniformLocation'].includes(prop)) return () => ({{}});
    if (prop === 'getProgramInfoLog' || prop === 'getShaderInfoLog') return () => '';
    if (typeof prop === 'string' && /^[A-Z0-9_]+$/.test(prop)) return 0;
    return () => {{}};
  }},
}});
const ctx2d = new Proxy({{}}, {{ get(_t, p) {{ return p === 'measureText' ? () => ({{ width: 50 }}) : () => {{}}; }} }});
const makeCanvas = (w = 1280, h = 720) => {{
  const c = {{
    width: w, height: h, style: {{}}, ownerDocument: null,
    addEventListener() {{}}, removeEventListener() {{}}, setPointerCapture() {{}}, releasePointerCapture() {{}},
    getRootNode() {{ return globalThis.document; }},
    getBoundingClientRect() {{ return {{ left: 0, top: 0, width: w, height: h, right: w, bottom: h }}; }},
    getContext(t) {{ return t === '2d' ? ctx2d : (t === 'webgl2' || t === 'webgl') ? gl2 : null; }},
  }};
  c.ownerDocument = globalThis.document;
  return c;
}};
globalThis.document = {{
  documentElement: {{ style: {{}} }},
  addEventListener() {{}}, removeEventListener() {{}},
  createElement(tag) {{ return tag === 'canvas' ? makeCanvas(512, 112) : {{ style: {{}}, addEventListener() {{}}, removeEventListener() {{}} }}; }},
  createElementNS(_ns, tag) {{ return this.createElement(tag); }},
}};
const nativeFetch = globalThis.fetch.bind(globalThis);
globalThis.fetch = async (input, init) => {{
  const u = typeof input === 'string' ? input : input?.url ?? String(input);
  if (u.startsWith(routePrefix)) {{
    const rel = decodeURIComponent(u.slice(routePrefix.length));
    const full = path.join(v02Dir, rel);
    try {{
      const buf = await fs.readFile(full);
      return new Response(buf, {{ status: 200, headers: {{ 'content-type': full.endsWith('.json') ? 'application/json' : 'model/gltf-binary' }} }});
    }} catch {{
      return new Response('Not Found', {{ status: 404 }});
    }}
  }}
  return nativeFetch(input, init);
}};
for (const T of new Set([THREE, THREE_V02])) {{
  const origAdd = T.Object3D.prototype.add;
  T.Object3D.prototype.add = function (...objs) {{
    if (this?.isScene) {{
      capturedScene = this;
    }}
    return origAdd.apply(this, objs);
  }};
}}

function boxToDict(box) {{
  if (!box || box.isEmpty()) return null;
  return {{
    min: [box.min.x, box.min.y, box.min.z],
    max: [box.max.x, box.max.y, box.max.z],
    span: [box.max.x - box.min.x, box.max.y - box.min.y, box.max.z - box.min.z],
  }};
}}

async function parseGlb(filePath) {{
  const buf = await fs.readFile(filePath);
  const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
  return new Promise((res, rej) => new GLTFLoader().parse(ab, '', res, rej));
}}

function measureMap(envRoot, layRoot) {{
  envRoot.updateMatrixWorld(true);
  layRoot.updateMatrixWorld(true);
  const slab = MapLayoutMod.findFloorSlab(envRoot);
  const walls = envRoot.getObjectByName('ENV_WALLS_AND_DOCKS');
  const d1 = envRoot.getObjectByName('DOCK_01');
  const d2 = envRoot.getObjectByName('DOCK_02');
  let meshCount = 0;
  let patchGroups = 0;
  for (const r of [envRoot, layRoot]) {{
    r.traverse((o) => {{
      if (o.isMesh) meshCount++;
      if (
        o.name === 'MAP_LAYOUT_EXPANSION' ||
        o.name === 'MAP_EXPANDED_GRID' ||
        o.name === 'MAP_FLOOR_FIXES' ||
        o.name === 'MAP_FLOOR_PATCHES' ||
        o.name === 'MAP_GEOMETRY_FIXES' ||
        o.name === 'MAP_ROBOT_REINFORCEMENT_FEET' ||
        o.name === 'MAP_ROBOT_TABLE_UNDERFRAME' ||
        o.name === 'MAP_WATER_COOLER_PLINTH'
      ) {{
        patchGroups++;
      }}
    }});
  }}
  return {{
    slabBox: slab ? boxToDict(new THREE.Box3().setFromObject(slab, true)) : null,
    wallsBox: walls ? boxToDict(new THREE.Box3().setFromObject(walls, true)) : null,
    dock01Pos: d1 ? d1.getWorldPosition(new THREE.Vector3()).toArray() : null,
    dock02Pos: d2 ? d2.getWorldPosition(new THREE.Vector3()).toArray() : null,
    meshCount,
    patchGroups,
  }};
}}

function runMapTrial(envTemplate, layTemplate) {{
  const env1 = envTemplate.clone(true);
  const lay1 = layTemplate.clone(true);
  for (const root of [env1, lay1]) {{
    root.traverse((o) => {{ if (o.isMesh && o.geometry) o.geometry = o.geometry.clone(); }});
  }}
  const h1a = MapGeomMod.applyMapGeometryFixes(env1, lay1);
  const h1b = MapLayoutMod.applyMapLayoutExpansion(env1);
  const h1c = MapFloorMod.applyMapFloorFixes(env1, lay1);
  const pass1 = measureMap(env1, lay1);

  MapGeomMod.applyMapGeometryFixes(env1, lay1);
  MapLayoutMod.applyMapLayoutExpansion(env1);
  MapFloorMod.applyMapFloorFixes(env1, lay1);
  const pass2 = measureMap(env1, lay1);

  MapGeomMod.applyMapGeometryFixes(env1, lay1);
  MapLayoutMod.applyMapLayoutExpansion(env1);
  MapFloorMod.applyMapFloorFixes(env1, lay1);
  const pass3 = measureMap(env1, lay1);

  h1c?.dispose?.();
  h1b?.dispose?.();
  h1a?.dispose?.();
  const afterDispose = measureMap(env1, lay1);

  MapGeomMod.applyMapGeometryFixes(env1, lay1);
  MapLayoutMod.applyMapLayoutExpansion(env1);
  MapFloorMod.applyMapFloorFixes(env1, lay1);
  const afterReapply = measureMap(env1, lay1);

  return {{ ok: true, pass1, pass2, pass3, afterDispose, afterReapply }};
}}

async function captureAsyncThrow(fn) {{
  try {{ await fn(); return {{ threw: false, name: null, message: null }}; }}
  catch (e) {{ return {{ threw: true, name: e?.name ?? null, message: String(e?.message ?? e) }}; }}
}}
function captureSyncThrow(fn) {{
  try {{ fn(); return {{ threw: false, name: null, message: null }}; }}
  catch (e) {{ return {{ threw: true, name: e?.name ?? null, message: String(e?.message ?? e) }}; }}
}}

const baseManRaw = await fs.readFile(path.join(packDir, 'v1-candidate-seed11', 'manifest.json'), 'utf8');
const baseMan = JSON.parse(baseManRaw);
const baseEvTxt = await fs.readFile(path.join(packDir, 'v1-candidate-seed11', 'events.jsonl'), 'utf8');

const dataNegatives = {{
  badEventsFile: await captureAsyncThrow(async () => {{
    const badMan = {{ ...structuredClone(baseMan), events_file: '../secret.jsonl' }};
    const handle = await DataMod.openLocal([
      {{ name: 'manifest.json', text: async () => JSON.stringify(badMan) }},
      {{ name: 'events.jsonl', text: async () => baseEvTxt }},
    ]);
    await handle.loadRun('local-shift');
  }}),
  badQuarter0Weeks: captureSyncThrow(() =>
    DataMod.validateQuarter({{ replay_pack_format: 'robotization-bench.quarter-pack.v1', weeks: [] }}, 'quarter_manifest.json')
  ),
  badQuarter13Weeks: captureSyncThrow(() =>
    DataMod.validateQuarter({{
      replay_pack_format: 'robotization-bench.quarter-pack.v1',
      weeks: Array.from({{ length: 13 }}, (_, i) => ({{ week: i }})),
    }}, 'quarter_manifest.json')
  ),
  badRemoteScheme: await captureAsyncThrow(() => DataMod.openRemote('ftp://invalid.local/index.json')),
  emptyLocalFiles: await captureAsyncThrow(() => DataMod.openLocal([])),
}};

const [envGltf, layGltf] = await Promise.all([
  parseGlb(path.join(v02Dir, 'warehouse_environment.glb')),
  parseGlb(path.join(v02Dir, 'modules', 'visual_layout.glb')),
]);
const shipped = runMapTrial(envGltf.scene, layGltf.scene);

const synEnv = new THREE.Group();
synEnv.name = 'Scene';
const floorGrp = new THREE.Group();
floorGrp.name = 'ENV_FLOOR_AND_GRID';
const slabMesh = new THREE.Mesh(new THREE.BoxGeometry(36, 0.2, 18), new THREE.MeshStandardMaterial());
slabMesh.position.set(0, -0.1, 0);
slabMesh.name = 'Raised_concrete_slab';
floorGrp.add(slabMesh);
const walkMesh = new THREE.Mesh(new THREE.PlaneGeometry(35.4, 1.5), new THREE.MeshStandardMaterial());
walkMesh.rotation.x = -Math.PI / 2;
walkMesh.position.set(0, 0.002, 5.15);
walkMesh.name = 'WALKWAY_GREEN_5S';
floorGrp.add(walkMesh);
synEnv.add(floorGrp);

const wallsGrp = new THREE.Group();
wallsGrp.name = 'ENV_WALLS_AND_DOCKS';
const backWall = new THREE.Mesh(new THREE.BoxGeometry(36, 3.6, 0.16), new THREE.MeshStandardMaterial());
backWall.position.set(0, 1.8, -9.0);
backWall.name = 'Back_wall_panel';
wallsGrp.add(backWall);
const d1 = new THREE.Group(); d1.name = 'DOCK_01'; d1.position.set(-17.85, 0, 5.15);
d1.add(new THREE.Mesh(new THREE.BoxGeometry(0.3, 3.0, 3.0), new THREE.MeshStandardMaterial()));
const d2 = new THREE.Group(); d2.name = 'DOCK_02'; d2.position.set(17.85, 0, 5.15);
d2.add(new THREE.Mesh(new THREE.BoxGeometry(0.3, 3.0, 3.0), new THREE.MeshStandardMaterial()));
wallsGrp.add(d1, d2);
synEnv.add(wallsGrp);
const syntheticNative36m = runMapTrial(synEnv, layGltf.scene);

const shiftCounterParity = {{}};
for (const runId of required9) {{
  const m = JSON.parse(await fs.readFile(path.join(packDir, runId, 'manifest.json'), 'utf8'));
  const eTxt = await fs.readFile(path.join(packDir, runId, 'events.jsonl'), 'utf8');
  const rep = createReplay(m, eTxt, {{ runId }});
  const st0 = rep.seekTo(0);
  const stHigh = rep.seekTo((rep.horizonTicks + 999) * rep.tickSeconds);
  let mismatches = 0;
  for (const k of COUNTER_KEYS) {{
    if (JSON.stringify(stHigh.counters[k]) !== JSON.stringify(m.raw[k])) mismatches++;
  }}
  shiftCounterParity[runId] = {{
    boundaryClampingOk: st0.tick === 0 && !st0.ended && Math.abs(stHigh.tickFloat - rep.horizonTicks) < 1e-6 && stHigh.ended === true,
    counterMismatches: mismatches,
  }};
}}

const player = await createScenePlayer(makeCanvas(1280, 720), {{ assetBase: routePrefix }});
capturedScene = player.scene ?? capturedScene;

const visibleOverheadClutterMeshes = [];
let activeLightCount = 0;
const overheadRe = /OVERHEAD_TRUSS|OVERHEAD_CABLE_TRAY|HIGHBAY|ENV_LIGHTING_RIG|CEILING_BEAM|HANGING_LAMP/i;
if (capturedScene) {{
  capturedScene.updateMatrixWorld(true);
  capturedScene.traverse((o) => {{
    if (o.isLight && o.visible && (o.intensity ?? 0) > 0) activeLightCount++;
    if (!o.isMesh) return;
    let effVis = true;
    let underOverhead = false;
    let forbiddenName = false;
    for (let cur = o; cur; cur = cur.parent) {{
      if (cur.visible === false) effVis = false;
      if (cur.name === 'ENV_OVERHEAD') underOverhead = true;
      if (overheadRe.test(cur.name ?? '')) forbiddenName = true;
    }}
    if (effVis && (underOverhead || forbiddenName)) {{
      visibleOverheadClutterMeshes.push(o.name || 'unnamed_mesh');
    }}
  }});
}}

async function measureStationaryQueueTrayAlignment(runId) {{
  const m = JSON.parse(await fs.readFile(path.join(packDir, runId, 'manifest.json'), 'utf8'));
  const eTxt = await fs.readFile(path.join(packDir, runId, 'events.jsonl'), 'utf8');
  const rep = createReplay(m, eTxt, {{ runId }});
  await player.setReplay(rep);
  const dyn = capturedScene?.getObjectByName('REPLAY_DYNAMIC');
  let trayHeightChecked = 0, trayHeightErrors = 0, untrayedHeightChecked = 0, untrayedHeightErrors = 0;

  for (let t = 4; t <= Math.min(rep.horizonTicks, 96); t += 2) {{
    const st = rep.seekTo(t * rep.tickSeconds);
    player.render(st, {{ playing: false, speed: 1, deltaSeconds: 0 }});
    capturedScene?.updateMatrixWorld(true);
    const transitIds = new Set((st.flow?.transits || []).map((tr) => tr.orderId));
    const stationaryIds = new Set([
      ...(st.queues.Q2 || []),
      ...(st.queues.Q3 || []),
      ...(st.queues.Q4 || []),
      ...(st.queues.R || []),
    ].filter((id) => !transitIds.has(id)));

    if (!capturedScene || stationaryIds.size === 0) continue;
    const orderNodes = [];
    capturedScene.traverse((o) => {{
      if (!o.visible) return;
      const mOrd = /^ORDER_(\\d+)$/.exec(o.name || '');
      const sel = o.userData?.selectionEntity;
      const ordId = sel?.type === 'order' ? Number(sel.id) : (mOrd ? Number(mOrd[1]) : NaN);
      if (Number.isFinite(ordId) && stationaryIds.has(ordId)) orderNodes.push(o);
    }});
    for (const oNode of orderNodes) {{
      let trayObj = null;
      const cartonMeshes = [];
      oNode.traverse((ch) => {{
        if (ch.name?.includes('VIS_order_tray') && ch.visible) trayObj = ch;
        if (ch.isMesh && ch.visible && !ch.name?.includes('tray') && !ch.name?.includes('rework_badge')) {{
          let inTray = false;
          for (let p = ch; p && p !== oNode; p = p.parent) if (p.name?.includes('VIS_order_tray')) inTray = true;
          if (!inTray) cartonMeshes.push(ch);
        }}
      }});
      if (cartonMeshes.length === 0) continue;
      const cb = new THREE.Box3();
      for (const cm of cartonMeshes) cb.expandByObject(cm);
      if (m.plan.trays) {{
        if (trayObj) {{
          const tb = new THREE.Box3().setFromObject(trayObj, true);
          trayHeightChecked++;
          if (Math.abs(tb.min.y - 0.860) > 0.004 || Math.abs(cb.min.y - tb.min.y - 0.012) > 0.004) {{
            trayHeightErrors++;
          }}
        }}
      }} else {{
        untrayedHeightChecked++;
        if (Math.abs(cb.min.y - 0.860) > 0.004) untrayedHeightErrors++;
      }}
      if (trayHeightChecked + untrayedHeightChecked >= 50) break;
    }}
    if (trayHeightChecked + untrayedHeightChecked >= 50) break;
  }}
  return {{ trayHeightChecked, trayHeightErrors, untrayedHeightChecked, untrayedHeightErrors }};
}}

const trayAlignment = {{
  'v1-candidate-seed11': await measureStationaryQueueTrayAlignment('v1-candidate-seed11'),
  'v1-candidate-seed29': await measureStationaryQueueTrayAlignment('v1-candidate-seed29'),
  'v1-manual-seed11': await measureStationaryQueueTrayAlignment('v1-manual-seed11'),
}};

const satMan = JSON.parse(await fs.readFile(path.join(reworkBundleDir, 'manifest.json'), 'utf8'));
const satEvTxt = await fs.readFile(path.join(reworkBundleDir, 'events.jsonl'), 'utf8');
const satRep = createReplay(satMan, satEvTxt, {{ runId: 't2-saturated-rework' }});
await player.setReplay(satRep);
const dyn = capturedScene?.getObjectByName('REPLAY_DYNAMIC');
let reworkQueueRObserved = 0;
let reworkBadgeVisibleCount = 0;
let robotAssignedAttempt1 = 0;
for (const ev of satRep.events) {{
  if (ev.kind === 'start' && (ev.attempt ?? 0) >= 1 && ev.resource === 'robot') robotAssignedAttempt1++;
  if (ev.kind === 'enqueue' && ev.stage === 3 && ev.attempt === 1) {{
    const st = satRep.seekTo(Math.min(satRep.horizonTicks, ev.tick + 0.5) * satRep.tickSeconds);
    player.render(st, {{ playing: false, speed: 1, deltaSeconds: 0 }});
    capturedScene?.updateMatrixWorld(true);
    const transitIds = new Set((st.flow?.transits || []).map((tr) => tr.orderId));
    const rIds = new Set((st.queues.R || []).filter((id) => !transitIds.has(id)));
    if (capturedScene && rIds.size > 0) {{
      capturedScene.traverse((oNode) => {{
        if (!oNode.visible) return;
        const mOrd = /^ORDER_(\\d+)$/.exec(oNode.name || '');
        const sel = oNode.userData?.selectionEntity;
        const ordId = sel?.type === 'order' ? Number(sel.id) : (mOrd ? Number(mOrd[1]) : NaN);
        if (!Number.isFinite(ordId) || !rIds.has(ordId)) return;
        const wp = oNode.getWorldPosition(new THREE.Vector3());
        if (wp.x >= 2.9 && wp.x <= 5.8 && wp.z >= 6.4 && wp.z <= 8.2 && wp.y >= 0.856 && wp.y <= 0.876) {{
          reworkQueueRObserved++;
        }}
      }});
    }}
  }} else if (ev.kind === 'start' && ev.stage === 3 && ev.attempt === 1) {{
    const mid = Math.min(satRep.horizonTicks, ev.tick + ((ev.end_tick ?? ev.tick + 2) - ev.tick) * 0.5);
    const st = satRep.seekTo(mid * satRep.tickSeconds);
    player.render(st, {{ playing: true, speed: 1, deltaSeconds: 0.1 * satRep.tickSeconds }});
    if (player.metrics?.reworkNorth === true) reworkBadgeVisibleCount++;
    if (dyn) {{
      dyn.traverse((o) => {{
        if (o.isSprite && o.visible && Math.abs(o.position.y - 1.75) < 0.1) reworkBadgeVisibleCount++;
      }});
    }}
  }}
}}
player.dispose();

await fs.writeFile(outFile, JSON.stringify({{
  ok: true,
  dataNegatives,
  mapIdempotency: {{ shipped, syntheticNative36m }},
  shiftCounterParity,
  ceilingAudit: {{ visibleOverheadClutterMeshes, activeLightCount }},
  trayAlignment,
  saturatedReworkBva: {{
    reworkStartedInRaw: satMan.raw.rework_started,
    reworkQueueRObserved,
    reworkBadgeVisibleCount,
    robotAssignedAttempt1,
  }},
}}, null, 2));
""".strip()

    mjs_path.write_text(mjs_code, encoding="utf-8")
    env = build_e2e_env(repo_root)
    proc = subprocess.run(
        [env["NODE_BIN"], str(mjs_path)],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0 or not out_path.exists():
        return {
            "ok": False,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-2000:],
            "stderr": proc.stderr[-2000:],
        }
    return json.loads(out_path.read_text(encoding="utf-8"))


# ==============================================================================
# FEATURE F1: Authoritative Workshop Chain Spec (workshop_chain.json) — 6 Tests
# ==============================================================================


def test_t2_f01_01_rejects_isolated_orphan_stage_and_severed_entry(
    reference_chain_env: dict[str, Any],
) -> None:
    """F1 BVA/Negative: Severing S0_INBOUND -> S1_PREP or isolating S2_PICK fails forward reachability."""
    chain_severed = make_reference_workshop_chain()
    _stage_by_id(chain_severed, "S0_INBOUND")["downstream_ids"] = []
    _stage_by_id(chain_severed, "S1_PREP")["upstream_ids"] = ["S5E_BREAK"]
    errs_severed = validate_workshop_chain(
        chain_severed,
        reference_chain_env["bindings"],
        reference_chain_env["scene_nodes"],
        reference_chain_env["worker_clips"],
        reference_chain_env["robot_clips"],
    )
    assert any("Unreachable/orphan stages" in e for e in errs_severed), errs_severed
    assert any("S0_INBOUND -> S1_PREP" in e for e in errs_severed), errs_severed

    chain_orphan = make_reference_workshop_chain()
    _stage_by_id(chain_orphan, "S1_PREP")["downstream_ids"] = ["S5E_BREAK"]
    _stage_by_id(chain_orphan, "S2_PICK")["upstream_ids"] = ["S5E_BREAK"]
    errs_orphan = validate_workshop_chain(
        chain_orphan,
        reference_chain_env["bindings"],
        reference_chain_env["scene_nodes"],
        reference_chain_env["worker_clips"],
        reference_chain_env["robot_clips"],
    )
    assert any("Unreachable/orphan stages" in e and "S2_PICK" in e for e in errs_orphan), errs_orphan


def test_t2_f01_02_rejects_dead_end_non_terminal_and_polluted_terminal_stages(
    reference_chain_env: dict[str, Any],
) -> None:
    """F1 BVA/Negative: Non-terminal dead-end S3A_PACK_MANUAL or terminal with downstream flow fails."""
    chain_dead = make_reference_workshop_chain()
    _stage_by_id(chain_dead, "S3A_PACK_MANUAL")["downstream_ids"] = ["S5E_BREAK"]
    _stage_by_id(chain_dead, "S4_QC")["upstream_ids"] = [
        u for u in _stage_by_id(chain_dead, "S4_QC")["upstream_ids"] if u != "S3A_PACK_MANUAL"
    ]
    errs_dead = validate_workshop_chain(
        chain_dead,
        reference_chain_env["bindings"],
        reference_chain_env["scene_nodes"],
        reference_chain_env["worker_clips"],
        reference_chain_env["robot_clips"],
    )
    assert any("Dead-end stages" in e and "S3A_PACK_MANUAL" in e for e in errs_dead), errs_dead

    chain_term = make_reference_workshop_chain()
    chain_term["terminal_nodes"] = ["S5A_GOOD", "S5B_ESCAPED"]
    errs_term = validate_workshop_chain(
        chain_term,
        reference_chain_env["bindings"],
        reference_chain_env["scene_nodes"],
        reference_chain_env["worker_clips"],
        reference_chain_env["robot_clips"],
    )
    assert any("Invalid terminal_nodes" in e for e in errs_term), errs_term


def test_t2_f01_03_rejects_illegal_rework_to_robot_asymmetry_and_unintended_cycle(
    reference_chain_env: dict[str, Any],
) -> None:
    """F1 BVA/Negative: S5C_REWORK_R -> S3B_PACK_ROBOT, asymmetric edges, and S4_QC -> S2_PICK cycle fail."""
    chain_rework = make_reference_workshop_chain()
    _stage_by_id(chain_rework, "S5C_REWORK_R")["downstream_ids"].append("S3B_PACK_ROBOT")
    _stage_by_id(chain_rework, "S3B_PACK_ROBOT")["upstream_ids"].append("S5C_REWORK_R")
    errs_rework = validate_workshop_chain(
        chain_rework,
        reference_chain_env["bindings"],
        reference_chain_env["scene_nodes"],
        reference_chain_env["worker_clips"],
        reference_chain_env["robot_clips"],
    )
    assert any("Illegal rework routing" in e for e in errs_rework), errs_rework

    chain_asym = make_reference_workshop_chain()
    _stage_by_id(chain_asym, "S2_PICK")["downstream_ids"].append("S4_QC")
    errs_asym = validate_workshop_chain(
        chain_asym,
        reference_chain_env["bindings"],
        reference_chain_env["scene_nodes"],
        reference_chain_env["worker_clips"],
        reference_chain_env["robot_clips"],
    )
    assert any("Asymmetric edge" in e for e in errs_asym), errs_asym

    chain_cycle = make_reference_workshop_chain()
    _stage_by_id(chain_cycle, "S4_QC")["downstream_ids"].append("S2_PICK")
    _stage_by_id(chain_cycle, "S2_PICK")["upstream_ids"].append("S4_QC")
    errs_cycle = validate_workshop_chain(
        chain_cycle,
        reference_chain_env["bindings"],
        reference_chain_env["scene_nodes"],
        reference_chain_env["worker_clips"],
        reference_chain_env["robot_clips"],
    )
    assert any("Unintended cycle" in e for e in errs_cycle), errs_cycle


def test_t2_f01_04_rejects_phantom_glb_node_conveyor_anchor_and_phantom_clip(
    reference_chain_env: dict[str, Any],
) -> None:
    """F1 Negative: Missing GLB equipment/conveyor/anchor nodes and phantom clips are caught."""
    chain_bad = make_reference_workshop_chain()
    _stage_by_id(chain_bad, "S2_PICK")["equipment_nodes"].append("PHANTOM_RACK_99")
    _stage_by_id(chain_bad, "S1_PREP")["conveyor_segments"].append("CONVEYOR_99")
    _stage_by_id(chain_bad, "S3A_PACK_MANUAL")["operation_clips"].append("TeleportPack")
    _stage_by_id(chain_bad, "S4_QC")["work_anchor"] = "VIS_STAGE_99_WORK"

    errs = validate_workshop_chain(
        chain_bad,
        reference_chain_env["bindings"],
        reference_chain_env["scene_nodes"],
        reference_chain_env["worker_clips"],
        reference_chain_env["robot_clips"],
    )
    assert any("PHANTOM_RACK_99" in e for e in errs), errs
    assert any("CONVEYOR_99" in e for e in errs), errs
    assert any("TeleportPack" in e for e in errs), errs
    assert any("VIS_STAGE_99_WORK" in e for e in errs), errs


def test_t2_f01_05_rejects_out_of_hall_zone_bounds_and_verify_live_chain_bounds(
    reference_chain_env: dict[str, Any],
    v02_configs: dict[str, Any],
    chain_report: dict[str, Any],
) -> None:
    """F1 BVA: Out-of-hall [-19.5..+18] / inverted zone_bounds_gltf fail; live workshop_chain stays in hall."""
    chain_oob = make_reference_workshop_chain()
    _stage_by_id(chain_oob, "S0_INBOUND")["zone_bounds_gltf"] = {"min": [-19.5, 0.0, -4.9], "max": [-9.2, 3.6, 6.0]}
    _stage_by_id(chain_oob, "S4_QC")["zone_bounds_gltf"] = {"min": [8.5, 0.0, -1.0], "max": [5.4, 3.6, -4.9]}
    errs = validate_workshop_chain(
        chain_oob,
        reference_chain_env["bindings"],
        reference_chain_env["scene_nodes"],
        reference_chain_env["worker_clips"],
        reference_chain_env["robot_clips"],
    )
    assert any("S0_INBOUND" in e and "outside 36x18m hall" in e for e in errs), errs
    assert any("S4_QC" in e and "outside 36x18m hall" in e for e in errs), errs

    assert chain_report["exists"] and v02_configs["workshop_chain"] is not None, chain_report["errors"]
    assert chain_report["ok"], f"Live workshop_chain.json validation failed: {chain_report['errors']}"
    for st in v02_configs["workshop_chain"]["stages"]:
        b = normalize_zone_bounds(st["zone_bounds_gltf"])
        assert b is not None, f"{st['id']} has unparseable zone_bounds_gltf: {st['zone_bounds_gltf']!r}"
        min_x, max_x, min_z, max_z = b
        assert -18.05 <= min_x < max_x <= 18.05, f"{st['id']} X bounds {b} escape [-18, +18]"
        assert -9.05 <= min_z < max_z <= 9.05, f"{st['id']} Z bounds {b} escape [-9, +9]"


def test_t2_f01_06_queue_slot_overflow_bva_and_invalid_binding_calls(
    node_probe: dict[str, Any],
) -> None:
    """F1 BVA/Negative: queueSlotPositions handles 0, Q2=17 (>12), R=101 and rejects Q99/-1/stage 99."""
    assert node_probe.get("ok"), node_probe.get("error")
    q_neg = node_probe["negativeChecks"]["queues"]
    assert q_neg["q1_0"] == 0
    assert q_neg["q2_17"] == 17
    assert q_neg["r_101"] == 101
    assert q_neg["badQueue"]["threw"] is True
    assert q_neg["negQueueCount"]["threw"] is True
    assert q_neg["badStageWork"]["threw"] is True


# ==============================================================================
# FEATURE F2: Clean 36×18×3.6m Hall, Closed Walls, Docks, Zero Overhead Beams/Lamps & CAD — 6 Tests
# ==============================================================================


def test_t2_f02_01_side_wall_portal_knife_edge_jamb_and_lintel_rays(
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F2 BVA: Knife-edge rays 5cm outside dock jambs hit wall; portal interior passes; lintel hits."""
    assert blender_probe.get("ok"), blender_probe.get("error")
    assert node_probe.get("ok"), node_probe.get("error")

    b_ray = blender_probe["room"]["parapet_raycast"]
    assert b_ray["uncovered_wall_rays"] == []
    assert b_ray["uncovered_lintel_rays"] == []
    assert b_ray["blocked_portal_rays"] == []
    assert b_ray["outside_jamb_misses"] == []
    assert b_ray["inside_portal_hits"] == []
    assert b_ray["inside_lintel_misses"] == []

    g_ray = node_probe["environmentAudit"]["raycasts"]
    assert g_ray["uncoveredWallRays"] == 0
    assert g_ray["uncoveredLintelRays"] == 0
    assert g_ray["blockedPortalRays"] == 0
    assert g_ray["knifeEdgeFailures"] == 0


def test_t2_f02_02_wall_lintel_strict_360m_ceiling_cap_and_zero_overhead_meshes_bva(
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F2 BVA (02:42:13Z Ceiling Rule): Walls & lintels cap at 3.60m ±5mm; 0 physical overhead truss/lamp meshes."""
    assert blender_probe.get("ok"), blender_probe.get("error")
    assert node_probe.get("ok"), node_probe.get("error")

    room = blender_probe["room"]
    assert room["dock_upper_walls"] == []
    walls_bb = room["walls_aabb"]
    assert walls_bb is not None and 3.595 <= walls_bb["max"][2] <= 3.605, walls_bb
    for panel in room["cutaway_side_walls"]["panels"]:
        assert -0.004 <= panel["min"][2] <= 0.004, panel
        assert 3.595 <= panel["max"][2] <= 3.605, panel
    for dock_name in ("DOCK_01", "DOCK_02"):
        lintel = room["docks"][dock_name]["lintel_aabb"]
        assert lintel is not None and 3.595 <= lintel["max"][2] <= 3.605, (dock_name, lintel)

    env_walls = node_probe["environmentAudit"]["wallsBox"]
    assert env_walls is not None and 3.595 <= env_walls["max"][1] <= 3.605, env_walls

    # Superseding 02:42:13Z user requirement: 0 physical ceiling beam/truss/cable-tray/lamp meshes
    ov = blender_probe["overhead"]
    assert ov["mesh_count"] == 0 and ov["aabb"] is None, (
        f"Physical overhead beam/lamp meshes remain in warehouse_environment.blend: {ov}"
    )
    for legacy_name in ("OVERHEAD_TRUSS_01", "OVERHEAD_TRUSS_02", "OVERHEAD_TRUSS_03", "OVERHEAD_CABLE_TRAY"):
        ch = ov["children"][legacy_name]
        assert ch["mesh_count"] == 0 and ch["aabb"] is None, (legacy_name, ch)

    env_ov = node_probe["environmentAudit"]["overheadBox"]
    assert env_ov is None, f"Physical overhead meshes remain in warehouse_environment.glb: {env_ov}"


def test_t2_f02_03_zero_overhead_beams_lamps_adversarial_rejection_and_slab_perimeter_bva(
    v02_dir: Path,
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
    direct_studio_bva_probe: dict[str, Any],
) -> None:
    """F2 Negative + Live BVA: Injected ceiling truss/lamp meshes flagged; live GLBs & Studio have 0 + active lights & 36×18m slab."""
    assert blender_probe.get("ok"), blender_probe.get("error")
    assert node_probe.get("ok"), node_probe.get("error")
    assert direct_studio_bva_probe.get("ok"), direct_studio_bva_probe

    # 1. Adversarial negative check: inject synthetic OVERHEAD_TRUSS_01 & HIGHBAY_LAMP_01 meshes into an in-memory GLB
    sample_raw = (v02_dir / "modules" / "carton_closed.glb").read_bytes()
    adv_doc, adv_bin = _parse_glb_binary(sample_raw)
    assert adv_doc.get("meshes"), "Expected >= 1 mesh in sample GLB"
    adv_nodes = adv_doc.setdefault("nodes", [])
    truss_idx = len(adv_nodes)
    adv_nodes.append({"name": "OVERHEAD_TRUSS_01", "mesh": 0, "translation": [0.0, 3.4, 0.0]})
    lamp_idx = len(adv_nodes)
    adv_nodes.append({"name": "HIGHBAY_LAMP_01", "mesh": 0, "translation": [0.0, 3.2, 0.0]})
    ov_idx = len(adv_nodes)
    adv_nodes.append({"name": "ENV_OVERHEAD", "children": [truss_idx, lamp_idx]})
    adv_doc["scenes"][0].setdefault("nodes", []).append(ov_idx)
    adv_findings = _find_forbidden_overhead_clutter_in_glb(_serialize_glb_binary(adv_doc, adv_bin))
    assert len(adv_findings["forbidden_mesh_nodes"]) >= 2, adv_findings
    assert len(adv_findings["env_overhead_mesh_nodes"]) >= 2, adv_findings

    # 2. Live GLB & Studio unobstructed ceiling verification (0 beam/truss/cable-tray/lamp meshes; active lights kept)
    for rel in ("warehouse_environment.glb", "modules/visual_layout.glb", "modules/visual_support.glb"):
        live_findings = _find_forbidden_overhead_clutter_in_glb((v02_dir / rel).read_bytes())
        assert live_findings["forbidden_mesh_nodes"] == [], (rel, live_findings)
        assert live_findings["env_overhead_mesh_nodes"] == [], (rel, live_findings)

    ca = direct_studio_bva_probe["ceilingAudit"]
    assert ca["visibleOverheadClutterMeshes"] == [], ca
    assert ca["activeLightCount"] >= 2, f"Expected active invisible Three.js lights in Studio scene, got {ca}"

    # 3. Exact 36.0 × 18.0 × 0.20m concrete floor slab perimeter BVA
    slab_b = blender_probe["room"]["slab"]
    slab_g = node_probe["environmentAudit"]["slabBox"]
    assert slab_b is not None and slab_g is not None
    assert abs(slab_b["min"][0] - (-18.0)) <= 0.02 and abs(slab_b["max"][0] - 18.0) <= 0.02
    assert abs(slab_b["min"][1] - (-9.0)) <= 0.02 and abs(slab_b["max"][1] - 9.0) <= 0.02
    assert abs(slab_b["min"][2] - (-0.20)) <= 0.01 and abs(slab_b["max"][2] - 0.0) <= 0.003
    assert abs(slab_g["span"][0] - 36.0) <= 0.04 and abs(slab_g["span"][2] - 18.0) <= 0.04


def test_t2_f02_04_cad_grid_strictly_clipped_inside_hall_walls_zero_bleed(
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F2 BVA: Interior CAD grid meshes stay strictly inside [-17.90..+17.90] × [-8.90..+8.90] walls."""
    assert blender_probe.get("ok"), blender_probe.get("error")
    assert node_probe.get("ok"), node_probe.get("error")

    grid_b = blender_probe["spurs_and_zones"]["cad_grid_aabb"]
    grid_g = node_probe["environmentAudit"]["cadGridAabb"]
    assert grid_b is not None, "CAD grid meshes missing in warehouse_environment.blend"
    assert grid_g is not None, "CAD grid meshes missing in warehouse_environment.glb"

    assert -17.90 <= grid_b["min"][0] <= -16.90 and 16.90 <= grid_b["max"][0] <= 17.90, grid_b
    assert -8.90 <= grid_b["min"][1] <= -7.90 and 7.90 <= grid_b["max"][1] <= 8.90, grid_b
    assert -17.90 <= grid_g["min"][0] <= -16.90 and 16.90 <= grid_g["max"][0] <= 17.90, grid_g
    assert -8.90 <= grid_g["min"][2] <= -7.90 and 7.90 <= grid_g["max"][2] <= 8.90, grid_g


def test_t2_f02_05_overview_camera_dock_symmetry_and_all_four_hall_corners_in_frustum(
    blender_probe: dict[str, Any],
) -> None:
    """F2 BVA: CAMERA_OVERVIEW centers X≈0, frames DOCK_01/02 symmetrically & keeps WS/WN/ES/EN in frustum."""
    assert blender_probe.get("ok"), blender_probe.get("error")
    cam = blender_probe["camera"]
    assert cam["exists"] is True
    assert abs(cam["location"][0]) <= 1.0 and abs(cam["target_at_z085"][0]) <= 1.0, cam

    d1 = cam["docks"]["DOCK_01"]
    d2 = cam["docks"]["DOCK_02"]
    assert d1["in_frustum"] and not d1["occluded"], d1
    assert d2["in_frustum"] and not d2["occluded"], d2
    assert abs((d1["ndc"][0] + d2["ndc"][0]) - 1.0) <= 0.08, (d1["ndc"], d2["ndc"])

    for corner_key in ("WS", "WN", "ES", "EN"):
        c_info = cam["floor_corners"][corner_key]
        assert c_info["in_frustum"] is True, f"Hall corner {corner_key} clipped out of CAMERA_OVERVIEW: {c_info}"


def test_t2_f02_06_env_overhead_empty_layer_compat_andon_isolation_and_conveyor_joint_zero_gap(
    node_probe: dict[str, Any],
) -> None:
    """F2 BVA/Negative: Empty ENV_OVERHEAD layer compat, Andon clone isolation, bad layer throw & 9 joints < 1e-4m."""
    assert node_probe.get("ok"), node_probe.get("error")
    env_aud = node_probe["environmentAudit"]
    la = env_aud["layerAndAndon"]
    if "ENV_OVERHEAD" in env_aud["presentLayers"]:
        assert la["ovHiddenByDefault"] is True
        assert la["ovVisibleAfterToggle"] is True
        assert la["ovHiddenAfterRevert"] is True
    assert env_aud["overheadBox"] is None, f"ENV_OVERHEAD must contain 0 meshes: {env_aud['overheadBox']}"
    assert la["cloneIsolationOk"] is True
    assert la["dockSignalUnmutated"] is True
    assert node_probe["negativeChecks"]["envAndMap"]["badEnvLayer"]["threw"] is True

    lay = node_probe["layoutAudit"]
    assert lay["conveyorJointCount"] == 9
    assert lay["maxConveyorJointGapM"] < 1e-4, lay["maxConveyorJointGapM"]
    assert lay["anchorsOutOfHall"] == 0


# ==============================================================================
# FEATURE F3: Spurs, Peripheral Bays, Floor Lanes, Zone Borders & Walkways — 6 Tests
# ==============================================================================


def test_t2_f03_01_oversize_queue_slot_spacing_and_q1_zone01_containment_margin(
    v02_configs: dict[str, Any],
    blender_probe: dict[str, Any],
) -> None:
    """F3 BVA: Queue slot spacing fits 0.48×0.34m oversize + 4cm margin; Q1 & deck fit inside FLOOR_ZONE_01."""
    assert blender_probe.get("ok"), blender_probe.get("error")
    bindings = v02_configs["visual_bindings"]
    assert isinstance(bindings, dict) and "queues" in bindings

    for q_name in ("Q1", "Q2", "Q3", "Q4", "R"):
        q_cfg = bindings["queues"][q_name]
        sp = (
            q_cfg.get("spacing")
            or q_cfg.get("slot_spacing_m")
            or q_cfg.get("spacing_gltf_m")
            or q_cfg.get("spacing_m")
        )
        assert isinstance(sp, list) and len(sp) >= 2, (q_name, q_cfg)
        dx = abs(float(sp[0]))
        dz = abs(float(sp[-1]))
        assert dx >= 0.52 and dz >= 0.38, f"{q_name} spacing {(dx, dz)} too tight for oversize tray"

    sz = blender_probe["spurs_and_zones"]
    z01 = sz["floor_zones"]["FLOOR_ZONE_01"]["aabb"]
    q1_deck = blender_probe["equipment"]["Q1_PAIRED_PALLET_DECK"]["aabb"]
    q1_slots = sz["q1_slot_positions_blender"]
    assert z01 is not None and q1_deck is not None and len(q1_slots) == 6
    assert z01["min"][0] <= -13.15, f"FLOOR_ZONE_01 not widened West: {z01}"
    assert z01["min"][0] - (-17.85) >= 4.30, f"Insufficient West apron to DOCK_01: {z01['min'][0]}"
    assert q1_deck["min"][0] >= z01["min"][0] + 0.05 and q1_deck["max"][0] <= z01["max"][0] - 0.05
    for sp_b in q1_slots:
        assert sp_b[0] - 0.27 >= z01["min"][0] + 0.05 and sp_b[0] + 0.27 <= z01["max"][0] - 0.05, sp_b


def test_t2_f03_02_conveyor_transfer_port_raycasts_and_infeed_outfeed_bridge_gaps(
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F3 BVA: Q2/Q3/Q4 transfer ports have 0 obstructions; INFEED_PREP_C01 & OUTFEED_C10_GOOD bridge <= 0.35m."""
    assert blender_probe.get("ok"), blender_probe.get("error")
    assert node_probe.get("ok"), node_probe.get("error")
    assert node_probe["environmentAudit"]["transferPortHits"] == 0

    eq = blender_probe["equipment"]
    infeed = eq["INFEED_PREP_C01"]
    outfeed = eq["OUTFEED_C10_GOOD"]
    c01 = eq["CONVEYOR_01"]["aabb"]
    c10 = eq["CONVEYOR_10"]["aabb"]
    t1 = eq["VIS_STAGE_1_TABLE"]["aabb"]
    p_good = eq["DISPATCH_PALLET_00"]["aabb"]

    assert infeed["exists"] and infeed["mesh_count"] >= 1 and infeed["aabb"] is not None
    assert outfeed["exists"] and outfeed["mesh_count"] >= 1 and outfeed["aabb"] is not None
    assert c01 is not None and c10 is not None and t1 is not None and p_good is not None

    in_bb = infeed["aabb"]
    out_bb = outfeed["aabb"]
    assert abs(in_bb["min"][2]) <= 0.003 and 0.858 <= in_bb["max"][2] <= 1.05, in_bb
    assert abs(out_bb["min"][2]) <= 0.003 and 0.858 <= out_bb["max"][2] <= 1.05, out_bb
    assert in_bb["min"][0] <= t1["max"][0] + 0.35 and in_bb["max"][0] >= c01["min"][0] - 0.35
    assert out_bb["min"][0] <= c10["max"][0] + 0.35 and out_bb["max"][0] >= p_good["min"][0] - 0.35


def test_t2_f03_03_active_order_tray_volumes_zero_static_tooling_intrusions(
    blender_probe: dict[str, Any],
) -> None:
    """F3 BVA: All 5 workstation 0.54×0.40×0.32m tray volumes [0.865..1.18m] have 0 tooling triangle hits."""
    assert blender_probe.get("ok"), blender_probe.get("error")
    intrusions = blender_probe["spurs_and_zones"]["tray_volume_intrusions"]
    expected_anchors = (
        "VIS_STAGE_1_ORDER",
        "VIS_STAGE_2_ORDER",
        "VIS_STAGE_3_ORDER",
        "VIS_STAGE_4_ORDER",
        "VIS_ROBOT_ORDER",
    )
    for anc in expected_anchors:
        assert anc in intrusions, f"Missing tray intrusion check for {anc}"
        assert intrusions[anc] == 0, f"Static tooling intrudes into {anc} tray volume: {intrusions[anc]} hits"


def test_t2_f03_04_robot_assist_standing_cylinder_clearance_near_chamfered_table(
    blender_probe: dict[str, Any],
) -> None:
    """F3 BVA: 0.55m-diameter × 1.80m helper cylinder at VIS_ROBOT_ASSIST has 0 static BVH hits."""
    assert blender_probe.get("ok"), blender_probe.get("error")
    assert blender_probe["artifacts"]["VIS_ROBOT_ASSIST"]["exists"] is True
    assert blender_probe["bvh"]["helper_hits"] == [], (
        f"VIS_ROBOT_ASSIST helper cylinder hits static equipment: {blender_probe['bvh']['helper_hits']}"
    )


def test_t2_f03_05_floor_zone_gaps_plc_containment_and_stage3_pack_station_contract(
    blender_probe: dict[str, Any],
    v02_configs: dict[str, Any],
) -> None:
    """F3 BVA: Zones 01..04 keep >0.12m outer border X-gap, PLC has 0 border overlaps, ESCAPED clears QC >0.15m."""
    assert blender_probe.get("ok"), blender_probe.get("error")
    sz = blender_probe["spurs_and_zones"]
    fz = sz["floor_zones"]
    for a_id, b_id in (
        ("FLOOR_ZONE_01", "FLOOR_ZONE_02"),
        ("FLOOR_ZONE_02", "FLOOR_ZONE_03"),
        ("FLOOR_ZONE_03", "FLOOR_ZONE_04"),
    ):
        bb_a = fz[a_id]["aabb"]
        bb_b = fz[b_id]["aabb"]
        assert bb_a is not None and bb_b is not None, (a_id, b_id)
        gap = bb_b["min"][0] - bb_a["max"][0]
        assert gap > 0.12, f"Zone border outer X-gap between {a_id} and {b_id} is {gap:.3f}m <= 0.12m"

    esc_bb = fz["OUTCOME_FLOOR_ESCAPED"]["aabb"]
    z04_bb = fz["FLOOR_ZONE_04"]["aabb"]
    assert esc_bb is not None and z04_bb is not None
    assert esc_bb["min"][0] - z04_bb["max"][0] >= 0.05, (z04_bb, esc_bb)

    assert sz["plc_border_overlaps"] == [], sz["plc_border_overlaps"]
    plc_bb = blender_probe["equipment"]["ROBOT_PLC_CABINET"]["aabb"]
    z03_bb = fz["FLOOR_ZONE_03"]["aabb"]
    assert plc_bb is not None and z03_bb is not None
    assert z03_bb["min"][0] + 0.02 < plc_bb["min"][0] < plc_bb["max"][0] < z03_bb["max"][0] - 0.02

    for cfg_key in ("environment_config", "config_environment"):
        matched = v02_configs["stage3_pack_station"][cfg_key]
        assert matched is not None and is_stage3_pack_station(matched), f"Missing Stage-3 station in {cfg_key}"


def test_t2_f03_06_floor_decal_height_ceiling_and_walkway_0025m_to_220m_prism_bva(
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F3 BVA: Floor decals <=0.010m, green-walkway-only arrows (03:14:54Z), 0 walkway prism hits, 0 ceiling obstructions."""
    assert blender_probe.get("ok"), blender_probe.get("error")
    assert node_probe.get("ok"), node_probe.get("error")

    decal_max_z = blender_probe["bvh"]["floor_decal_max_z"]
    assert 0.0002 <= decal_max_z <= 0.010, f"Floor decal max_z={decal_max_z:.5f}m out of [0.0002, 0.010]m"
    assert blender_probe["bvh"]["walkway_hits"] == [], blender_probe["bvh"]["walkway_hits"]
    assert node_probe["environmentAudit"]["walkwayPrismHits"] == 0
    ov = blender_probe["overhead"]
    assert ov["mesh_count"] == 0 and ov["aabb"] is None, f"Overhead meshes obstruct ceiling above walkway: {ov}"

    bl_arrows = blender_probe["spurs_and_zones"]["floor_arrows"]
    assert bl_arrows["off_walkway_arrows"] == [], f"Off-walkway floor arrows remain in .blend (03:14:54Z): {bl_arrows}"
    assert bl_arrows["under_table_arrows"] == [], f"Arrows under tables in .blend: {bl_arrows}"
    assert bl_arrows["misoriented_walkway_arrows"] == [], f"Misoriented walkway arrows in .blend: {bl_arrows}"
    assert len(bl_arrows["walkway_arrows"]) >= 3, f"Missing green-walkway arrows in .blend: {bl_arrows}"

    env_arrows = node_probe["environmentAudit"]["floorArrowsAudit"]
    assert env_arrows["offWalkwayArrows"] == [], f"Off-walkway floor arrows remain in warehouse_environment.glb: {env_arrows}"
    assert env_arrows["underTableArrows"] == [], f"Arrows under tables in .glb: {env_arrows}"
    assert env_arrows["twistedArrowMeshes"] == [], f"Twisted arrow quads in .glb: {env_arrows}"
    assert env_arrows["misorientedWalkwayArrows"] == [], f"Misoriented walkway arrows in .glb: {env_arrows}"
    assert len(env_arrows["walkwayArrows"]) >= 3, f"Missing WALKWAY_DIRECTION_ARROW_* in .glb: {env_arrows}"

    studio_arrows = (
        node_probe["studioReplayAudit"].get("floorArrowsAudit")
        or node_probe["environmentAudit"]["studioPatchedFloorArrowsAudit"]
    )
    assert studio_arrows["offWalkwayArrows"] == [], f"Off-walkway floor arrows remain in Studio scene: {studio_arrows}"
    assert studio_arrows["duplicateWalkwayPairs"] == [], f"Duplicate stacked walkway arrows in Studio: {studio_arrows}"
    assert studio_arrows["twistedArrowMeshes"] == [], f"Twisted arrow quads in Studio: {studio_arrows}"
    assert studio_arrows["underTableArrows"] == [], f"Arrows under tables in Studio: {studio_arrows}"
    assert studio_arrows["misorientedWalkwayArrows"] == [], f"Misoriented walkway arrows in Studio: {studio_arrows}"
    assert len(studio_arrows["walkwayArrows"]) >= 3, f"Missing green-walkway arrows in Studio: {studio_arrows}"
    assert studio_arrows["hasWalkwayGreen5S"] is True


# ==============================================================================
# FEATURE F4: Clean GLB Exports, ±2mm Contacts & Zero BVH Collisions — 6 Tests
# ==============================================================================


def test_t2_f04_01_gltf_validator_rejects_corrupt_magic_and_truncated_bin_in_tmp_path(
    corrupt_glb_probes: dict[str, Any],
) -> None:
    """F4 Negative: gltf-validator cleanly rejects bad-magic and truncated-BIN GLBs without crashing."""
    bad_magic = corrupt_glb_probes["bad_magic"]
    trunc_bin = corrupt_glb_probes["truncated_bin"]
    assert bad_magic["ok"] is True and bad_magic["numErrors"] > 0, bad_magic
    assert trunc_bin["ok"] is True and trunc_bin["numErrors"] > 0, trunc_bin


def test_t2_f04_02_strict_2mm_floor_contact_tolerance_across_all_floor_standing_roots(
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F4 BVA: All floor-standing equipment roots (incl. WATER_COOLER & PALLET_JACK) touch z=0.000 ± 0.002m."""
    assert blender_probe.get("ok"), blender_probe.get("error")
    assert node_probe.get("ok"), node_probe.get("error")

    floor_roots = (
        *[f"CONVEYOR_{i:02d}" for i in range(1, 11)],
        "BENCH_PICK",
        "BENCH_PACK",
        "BENCH_REWORK",
        "BENCH_SCRAP",
        "RACK_01",
        "RACK_02",
        "RACK_03",
        "SUPPLY_TROLLEY",
        "QC_PORTAL",
        "Q1_PAIRED_PALLET_DECK",
        "QUEUE_R_ROLLER_SECTION",
        "SCRAP_BIN",
        "DISPATCH_PALLET_00",
        "DISPATCH_PALLET_01",
        "PALLET_JACK",
        "PREP_TOOLING",
        "ROBOT_PLC_CABINET",
        "BREAK_BENCH",
        "WATER_COOLER",
        "VIS_STAGE_1_TABLE",
        "VIS_STAGE_4_TABLE",
        "VIS_ROBOT_PACK_TABLE",
        "VIS_QUEUE_Q2_FRAME",
        "VIS_QUEUE_Q3_FRAME",
        "VIS_QUEUE_Q4_FRAME",
    )
    eq = blender_probe["equipment"]
    offenders = []
    for name in floor_roots:
        info = eq.get(name)
        if not info or not info["exists"] or info["aabb"] is None:
            offenders.append((name, "missing_or_empty"))
            continue
        min_z = info["aabb"]["min"][2]
        if not (-0.002 <= min_z <= 0.002):
            offenders.append((name, round(min_z, 5)))
    assert offenders == [], f"Equipment roots violating 0.000 ± 0.002m floor contact: {offenders}"
    assert eq["PALLET_JACK"]["mesh_count"] == 12

    jack_g = node_probe["environmentAudit"]["palletJack"]
    assert jack_g["meshCount"] >= 4 and jack_g["triangleCount"] >= 200, jack_g
    assert jack_g["aabb"] is not None and abs(jack_g["aabb"]["min"][1]) <= 0.002, jack_g


def test_t2_f04_03_strict_2mm_0860m_roller_worktop_and_0150m_pallet_height_tolerances(
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F4 BVA: 200 main rollers, buffer rollers, QC_SCALE_FLUSH & chamfer top sit at 0.860 ± 0.002m."""
    assert blender_probe.get("ok"), blender_probe.get("error")
    assert node_probe.get("ok"), node_probe.get("error")

    sup = blender_probe["supports"]
    assert sup["main_rollers"]["count"] == 200 and sup["main_rollers"]["offenders"] == []
    assert sup["buffer_rollers"]["count"] >= 24 and sup["buffer_rollers"]["max_abs_err_from_086"] <= 0.002
    assert sup["buffer_rollers"]["offenders"] == []
    for ord_anc, top_info in sup["workstation_tops"].items():
        assert top_info["covers_tray_footprint"] is True, (ord_anc, top_info)

    qc_scale = blender_probe["artifacts"]["QC_SCALE_FLUSH"]
    assert qc_scale["exists"] and qc_scale["aabb"] is not None
    assert abs(qc_scale["aabb"]["max"][2] - 0.860) <= 0.002, qc_scale

    chamfer_l = node_probe["layoutAudit"]["chamfer"]
    assert chamfer_l["exists"] and chamfer_l["parent"] == "VIS_ROBOT_PACK_TABLE"
    assert abs(chamfer_l["aabb"]["max"][1] - 0.860) <= 0.002, chamfer_l
    assert node_probe["environmentAudit"]["chamferInEnv"] is False
    assert node_probe["environmentAudit"]["rollerCount"] == 200
    assert node_probe["environmentAudit"]["rollerHeightOffenders"] == 0

    for p_name in ("DISPATCH_PALLET_00", "DISPATCH_PALLET_01", "Q1_PAIRED_PALLET_DECK"):
        p_bb = blender_probe["equipment"][p_name]["aabb"]
        assert p_bb is not None and abs(p_bb["max"][2] - 0.150) <= 0.002, (p_name, p_bb)


def test_t2_f04_04_queue_rack_labels_below_084m_and_guide_rails_clear_of_slots(
    node_probe: dict[str, Any],
) -> None:
    """F4 BVA: VIS_QUEUE_Q2..Q4 labels stay < 0.84m and guide rails overlap preview slots by <= 1mm."""
    assert node_probe.get("ok"), node_probe.get("error")
    racks = node_probe["layoutAudit"]["queueRacks"]
    for q_id in ("Q2", "Q3", "Q4"):
        r_info = racks[q_id]
        assert r_info["topAabb"] is not None and abs(r_info["topAabb"]["max"][1] - 0.860) <= 0.002, (q_id, r_info)
        assert r_info["labelAabb"] is not None and r_info["labelAabb"]["max"][1] < 0.840, (q_id, r_info)
        assert r_info["maxGuideSlotOverlapM"] <= 0.001, (q_id, r_info)


def test_t2_f04_05_zero_nan_zero_area_triangles_module_dimensions_and_support_pivots(
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F4 BVA: 0 NaN/zero-area triangles across .blend & 15 GLBs; module AABBs & 14 support pivots exact."""
    assert blender_probe.get("ok"), blender_probe.get("error")
    assert node_probe.get("ok"), node_probe.get("error")

    mi = blender_probe["bvh"]["mesh_integrity"]
    assert mi["nan_inf_vertices"] == 0 and mi["zero_area_triangles"] == 0, mi

    gv = node_probe["gltfValidation"]
    for rel in ALL_15_GLB_RELS:
        info = gv.get(rel) or {}
        assert info.get("exists") is True and info.get("numErrors") == 0, (rel, info)
        assert info.get("nanVertices") == 0 and info.get("zeroAreaTriangles") == 0, (rel, info)

    assert 100_000 < gv["warehouse_environment.glb"]["bytes"] < 12 * 1024 * 1024
    assert node_probe["environmentAudit"]["demoCartonNodes"] == []
    assert node_probe["environmentAudit"]["legacyClutterNodes"] == []
    assert node_probe["environmentAudit"]["benchReworkInEnv"] is True, "Grounded BENCH_REWORK missing from warehouse_environment.glb"
    assert node_probe["environmentAudit"]["benchScrapInEnv"] is True, "Grounded BENCH_SCRAP missing from warehouse_environment.glb"
    br_box = node_probe["environmentAudit"]["benchReworkBox"]
    bs_box = node_probe["environmentAudit"]["benchScrapBox"]
    assert br_box["exists"] and abs(br_box["minY"]) <= 0.005 and 0.856 <= br_box["maxY"] <= 1.55, br_box
    assert abs(br_box["center"][0] - 1.80) <= 0.25 and abs(br_box["center"][2] - 6.35) <= 0.25, br_box
    assert bs_box["exists"] and abs(bs_box["minY"]) <= 0.005 and 0.856 <= bs_box["maxY"] <= 1.55, bs_box
    assert abs(bs_box["center"][0] - 8.65) <= 0.25 and abs(bs_box["center"][2] - 6.35) <= 0.25, bs_box
    assert node_probe["environmentAudit"]["utilityCabinetInEnv"] is False
    assert node_probe["environmentAudit"]["cabinetRegionTris"] == 0

    tote_span = gv["modules/tote_600x400.glb"]["aabb"]["span"]
    pallet_span = gv["modules/pallet_1200x800.glb"]["aabb"]["span"]
    assert abs(tote_span[0] - 0.60) <= 0.005 and abs(tote_span[1] - 0.22) <= 0.005 and abs(tote_span[2] - 0.40) <= 0.005
    assert abs(pallet_span[0] - 1.20) <= 0.005 and abs(pallet_span[1] - 0.15) <= 0.005 and abs(pallet_span[2] - 0.80) <= 0.005

    templates = node_probe["supportAudit"]["templates"]
    surface_templates = (
        "VIS_manual_bench",
        "VIS_order_regular",
        "VIS_order_fragile",
        "VIS_order_oversize",
        "VIS_order_tray",
        "VIS_empty_slot",
        "VIS_reserved_slot",
    )
    for t_name in surface_templates:
        t_info = templates[t_name]
        assert t_info["exists"] is True, t_name
        assert abs(t_info["localAabb"]["min"][1]) <= 0.001, (t_name, t_info["localAabb"])
        if t_name != "VIS_manual_bench":
            cx, cz = t_info["centerXZ"]
            assert abs(cx) <= 0.006 and abs(cz) <= 0.006, (t_name, cx, cz)


def test_t2_f04_06_bvh_synthetic_interpenetration_sanity_vs_clean_scene(
    blender_probe: dict[str, Any],
) -> None:
    """F4 BVA/Sanity: BVH catches synthetic conveyor & rework bench interpenetrations while live scene has 0."""
    assert blender_probe.get("ok"), blender_probe.get("error")
    bvh = blender_probe["bvh"]
    assert set(bvh["synthetic_sanity"]["conveyor_box_hits"]) == {"CONVEYOR_05", "CONVEYOR_06"}
    assert bvh["synthetic_sanity"]["rework_box_hit_count"] > 0

    # Per PROJECT.md §Interface Contracts 1 (line 105), grounded env workstation tables co-locate with
    # VIS_* layout anchors and mounted tooling (deduplicated at runtime by map-geometry.js).
    allowed_co_station_pairs = {
        frozenset({"STAGE1_PREP_TABLE", "VIS_STAGE_1_TABLE"}),
        frozenset({"STAGE1_PREP_TABLE", "PREP_TOOLING"}),
        frozenset({"STAGE1_PREP_TABLE", "INFEED_PREP_C01"}),
        frozenset({"ROBOT_PACK_TABLE", "VIS_ROBOT_PACK_TABLE"}),
        frozenset({"ROBOT_PACK_TABLE", "ROBOT_TABLE_REINFORCEMENT"}),
        frozenset({"ROBOT_PACK_TABLE", "SPUR_ROBOT"}),
        frozenset({"STAGE4_QC_TABLE", "VIS_STAGE_4_TABLE"}),
        frozenset({"STAGE4_QC_TABLE", "QC_TABLE_TOOLING"}),
        frozenset({"STAGE4_QC_TABLE", "SPUR_QC"}),
    }
    unexpected = [
        hit
        for hit in bvh["unintended_collisions"]
        if frozenset({hit["a"], hit["b"]}) not in allowed_co_station_pairs
    ]
    assert unexpected == [], unexpected


# ==============================================================================
# FEATURE F5: 30-FPS Articulated Worker Rig & 17 Clips (warehouse_worker.glb) — 6 Tests
# ==============================================================================


def test_t2_f05_01_adversarial_worker_glb_catches_unweighted_vertex_and_bad_joint_vs_live_clean(
    adversarial_worker_glb_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F5 Negative + Live BVA: Mutated worker GLB flags unweightedVerts & outOfRangeIndices; live has 0."""
    assert adversarial_worker_glb_probe.get("ok"), adversarial_worker_glb_probe
    mut_skin = adversarial_worker_glb_probe["skinning"]
    assert mut_skin["unweightedVerts"] >= 1, mut_skin
    assert mut_skin["outOfRangeIndices"] >= 1, mut_skin

    assert node_probe.get("ok"), node_probe.get("error")
    live_w = node_probe["characterAudit"]["worker"]
    assert live_w["boneCount"] == 35 and live_w["missingPropBones"] == [], live_w
    assert live_w["skinning"]["unweightedVerts"] == 0, live_w["skinning"]
    assert live_w["skinning"]["outOfRangeIndices"] == 0, live_w["skinning"]
    assert live_w["skinning"]["nonNormalizedVerts"] == 0, live_w["skinning"]
    assert live_w["skinning"]["helmetHeadWeighted"] is True, live_w["skinning"]


def test_t2_f05_02_adversarial_worker_glb_catches_demosupport_and_demo_only_prop_vs_live_clean(
    adversarial_worker_glb_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F5 Negative + Live BVA: Mutated worker GLB flags WORKER_DemoSupport & demo_only; live has 0."""
    assert adversarial_worker_glb_probe.get("ok"), adversarial_worker_glb_probe
    assert "WORKER_DemoSupport" in adversarial_worker_glb_probe["demoSupportNodes"]
    assert any(
        p["demo_only"] is True or p["operation_prop"] is False
        for p in adversarial_worker_glb_probe["propMeshInfos"]
    ), adversarial_worker_glb_probe["propMeshInfos"]

    assert node_probe.get("ok"), node_probe.get("error")
    live_w = node_probe["characterAudit"]["worker"]
    assert live_w["demoSupportNodes"] == [], live_w["demoSupportNodes"]
    assert len(live_w["propMeshInfos"]) >= 7, live_w["propMeshInfos"]
    assert all(p["operation_prop"] is True and p["demo_only"] is False for p in live_w["propMeshInfos"]), (
        live_w["propMeshInfos"]
    )
    assert live_w["sockets"]["leftExists"] and live_w["sockets"]["rightExists"], live_w["sockets"]


def test_t2_f05_03_adversarial_worker_glb_catches_phantom_idle_prop_scale_vs_live_zero_scale(
    adversarial_worker_glb_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F5 Negative + Live BVA: Mutated Idle prop scale >= 1.7; live Idle/Walk/Reach/Assist/Break < 1e-4."""
    assert adversarial_worker_glb_probe.get("ok"), adversarial_worker_glb_probe
    assert adversarial_worker_glb_probe["clipMetrics"]["Idle"]["maxPropWorldScale"] > 1.0

    assert node_probe.get("ok"), node_probe.get("error")
    live_cm = node_probe["characterAudit"]["worker"]["clipMetrics"]
    for clip_name in ("Idle", "Walk", "Reach", "Assist", "Break"):
        assert clip_name in live_cm, f"Missing worker clip {clip_name}"
        assert live_cm[clip_name]["maxPropWorldScale"] < 1e-4, (
            f"Worker {clip_name} leaks visible prop scale: {live_cm[clip_name]['maxPropWorldScale']}"
        )


def test_t2_f05_04_adversarial_worker_glb_catches_frozen_assist_vs_live_bva_motion_thresholds(
    adversarial_worker_glb_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F5 Negative + Live BVA: Mutated Assist has 0.0m delta; live clips meet Assist >= 0.20m & Break >= 0.15m."""
    assert adversarial_worker_glb_probe.get("ok"), adversarial_worker_glb_probe
    assert adversarial_worker_glb_probe["clipMetrics"]["Assist"]["maxBodyDeltaM"] < 1e-5

    assert node_probe.get("ok"), node_probe.get("error")
    live_w = node_probe["characterAudit"]["worker"]
    assert set(live_w["clipNames"]) == CANONICAL_WORKER_CLIPS
    cm = live_w["clipMetrics"]
    min_thresholds = {
        "Assist": 0.20,
        "Break": 0.15,
        "Prepare": 0.20,
        "Prepare_Oversize": 0.20,
        "Pick": 0.25,
        "Pick_Oversize": 0.25,
        "Pack": 0.20,
        "Pack_Oversize": 0.20,
        "Inspect": 0.14,
        "Inspect_Oversize": 0.14,
        "Walk": 0.40,
        "CarryWalk": 0.40,
        "PickUp": 0.30,
        "PlaceDown": 0.30,
        "Reach": 0.20,
        "Idle": 0.002,
        "CarryIdle": 0.002,
    }
    for clip_name, min_m in min_thresholds.items():
        actual = cm[clip_name]["maxBodyDeltaM"]
        assert actual >= min_m, f"Worker {clip_name} maxBodyDeltaM={actual:.4f}m < {min_m}m"

    ad = live_w["adapterAudit"]
    assert ad["ok"] is True and ad["visibleOpPropsInPack"] >= 1, ad
    for st in ("assist", "break", "pack"):
        assert ad["statePhaseDiffs"][st] > 0.01, f"Worker state {st!r} frozen across phases: {ad}"


def test_t2_f05_05_adversarial_worker_glb_catches_off_grid_timestamp_vs_live_30fps_cadence(
    adversarial_worker_glb_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F5 Negative + Live BVA: +9ms perturbed timestamp is flagged; live 17 clips have 0 off-grid keys."""
    assert adversarial_worker_glb_probe.get("ok"), adversarial_worker_glb_probe
    mut_cad = adversarial_worker_glb_probe["cadence"]
    assert len(mut_cad["offGridSamplers"]) >= 1, mut_cad
    assert any(s["clip"] == "Walk" for s in mut_cad["offGridSamplers"]), mut_cad

    assert node_probe.get("ok"), node_probe.get("error")
    live_cad = node_probe["characterAudit"]["worker"]["cadence"]
    assert live_cad["offGridSamplers"] == [], live_cad["offGridSamplers"]
    for clip_name in CANONICAL_WORKER_CLIPS:
        cc = live_cad["clipCadence"][clip_name]
        assert cc["duration"] >= 1.0 and cc["durationGridErr"] < 3e-4 and cc["offGridCount"] == 0, (clip_name, cc)


def test_t2_f05_06_worker_visual_adapter_rejects_invalid_inputs_and_isolates_clones(
    node_probe: dict[str, Any],
) -> None:
    """F5 Negative: createActorVisual(worker) rejects teleport/pallet/NaN/cycles=-1 & keeps clones independent."""
    assert node_probe.get("ok"), node_probe.get("error")
    wa = node_probe["negativeChecks"]["workerAdapter"]
    assert wa["workerClonesIndependent"] is True
    assert wa["badWorkerState"]["threw"] is True
    assert wa["badWorkerOrderKind"]["threw"] is True
    assert wa["badWorkerPhase"]["threw"] is True
    assert wa["badWorkerCycles"]["threw"] is True


# ==============================================================================
# FEATURE F6: 30-FPS Articulated Robot Rig & Exact 14 Clips (humanoid_robot.glb) — 6 Tests
# ==============================================================================


def test_t2_f06_01_adversarial_robot_glb_catches_leaked_pick_inspect_vs_live_exact_14_clips(
    adversarial_robot_glb_probe: dict[str, Any],
    node_probe: dict[str, Any],
    v02_configs: dict[str, Any],
) -> None:
    """F6 Negative + Live BVA: Mutated robot GLB flags Pick & Inspect_Oversize; live has exact 14 clips."""
    assert adversarial_robot_glb_probe.get("ok"), adversarial_robot_glb_probe
    assert set(adversarial_robot_glb_probe["forbiddenClips"]) >= {"Pick", "Inspect_Oversize"}

    assert node_probe.get("ok"), node_probe.get("error")
    live_r = node_probe["characterAudit"]["robot"]
    assert live_r["forbiddenClips"] == [], live_r["forbiddenClips"]
    assert len(live_r["clipNames"]) == 14 and set(live_r["clipNames"]) == CANONICAL_ROBOT_CLIPS, live_r["clipNames"]

    r_man = v02_configs["robot_manifest"]
    assert isinstance(r_man, dict), "robot_manifest.json missing or invalid"
    man_clips = r_man.get("clips") or r_man.get("animations") or []
    man_names = [c["name"] if isinstance(c, dict) else str(c) for c in man_clips]
    assert len(man_names) == 14 and set(man_names) == CANONICAL_ROBOT_CLIPS, man_names


def test_t2_f06_02_adversarial_robot_glb_catches_blended_armor_and_demosupport_vs_live_rigid_41_bones(
    adversarial_robot_glb_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F6 Negative + Live BVA: Mutated robot GLB flags nonRigidArmorVerts & DemoSupport; live has 41 bones & 0."""
    assert adversarial_robot_glb_probe.get("ok"), adversarial_robot_glb_probe
    assert adversarial_robot_glb_probe["skinning"]["nonRigidArmorVerts"] >= 1, adversarial_robot_glb_probe["skinning"]
    assert "ROBOT_DemoSupport" in adversarial_robot_glb_probe["demoSupportNodes"]

    assert node_probe.get("ok"), node_probe.get("error")
    live_r = node_probe["characterAudit"]["robot"]
    assert live_r["numErrors"] == 0
    assert live_r["boneCount"] == 41 and live_r["missingPropBones"] == [], live_r
    assert live_r["demoSupportNodes"] == [], live_r["demoSupportNodes"]
    assert live_r["skinning"]["unweightedVerts"] == 0, live_r["skinning"]
    assert live_r["skinning"]["outOfRangeIndices"] == 0, live_r["skinning"]
    assert live_r["skinning"]["nonRigidArmorVerts"] == 0, live_r["skinning"]
    assert live_r["sockets"]["leftExists"] and live_r["sockets"]["rightExists"], live_r["sockets"]


def test_t2_f06_03_adversarial_robot_glb_catches_frozen_service_jammed_vs_live_active_recovery(
    adversarial_robot_glb_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F6 Negative + Live BVA: Frozen Service/Jammed caught; live Service* >=0.10m, Jammed* >=0.02m, Offline >=0.01m."""
    assert adversarial_robot_glb_probe.get("ok"), adversarial_robot_glb_probe
    assert adversarial_robot_glb_probe["clipMetrics"]["Service"]["maxBodyDeltaM"] < 1e-5
    assert adversarial_robot_glb_probe["clipMetrics"]["Jammed"]["maxBodyDeltaM"] < 1e-5

    assert node_probe.get("ok"), node_probe.get("error")
    live_r = node_probe["characterAudit"]["robot"]
    cm = live_r["clipMetrics"]
    robot_thresholds = {
        "RobotPack": 0.20,
        "RobotPack_Oversize": 0.20,
        "Service": 0.10,
        "Service_Oversize": 0.10,
        "Jammed": 0.02,
        "Jammed_Oversize": 0.02,
        "Offline": 0.01,
        "Walk": 0.40,
        "CarryWalk": 0.40,
        "PickUp": 0.30,
        "PlaceDown": 0.30,
        "Reach": 0.20,
    }
    for clip_name, min_m in robot_thresholds.items():
        actual = cm[clip_name]["maxBodyDeltaM"]
        assert actual >= min_m, f"Robot {clip_name} maxBodyDeltaM={actual:.4f}m < {min_m}m"

    ad = live_r["adapterAudit"]
    assert ad["ok"] is True and ad["visibleOpPropsInPack"] >= 1, ad
    for st in ("pack", "jammed", "service", "disabled"):
        assert ad["statePhaseDiffs"][st] > 0.005, f"Robot adapter froze state {st!r}: {ad}"


def test_t2_f06_04_robot_empty_hand_zero_prop_scale_and_robotpack_flap_tape_choreography_bva(
    adversarial_robot_glb_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F6 Negative + Live BVA: Static flap/tape in mutated RobotPack caught; live flaps fold & empty clips <1e-4."""
    assert adversarial_robot_glb_probe.get("ok"), adversarial_robot_glb_probe
    mut_rp = adversarial_robot_glb_probe["clipMetrics"]["RobotPack"]["props"]
    if "prop_flap_left" in mut_rp:
        assert mut_rp["prop_flap_left"]["rotDeltaRad"] < 1e-4, mut_rp["prop_flap_left"]

    assert node_probe.get("ok"), node_probe.get("error")
    cm = node_probe["characterAudit"]["robot"]["clipMetrics"]
    for empty_clip in ("Idle", "Walk", "Reach", "Offline"):
        assert cm[empty_clip]["maxPropWorldScale"] < 1e-4, (empty_clip, cm[empty_clip]["maxPropWorldScale"])

    for pack_clip in ("RobotPack", "RobotPack_Oversize"):
        props = cm[pack_clip]["props"]
        for flap in ("prop_flap_front", "prop_flap_back", "prop_flap_left", "prop_flap_right"):
            assert props[flap]["rotDeltaRad"] > 0.15, (pack_clip, flap, props[flap])
        assert props["prop_tape"]["posDeltaM"] > 0.015 and props["prop_tape"]["scaleDelta"] > 0.05, (
            pack_clip,
            props["prop_tape"],
        )


def test_t2_f06_05_robot_not_purchased_hidden_and_disabled_shows_offline_marker_bva(
    node_probe: dict[str, Any],
) -> None:
    """F6 BVA: state='not_purchased' hides robot (clip=null); state='disabled' plays Offline + status marker."""
    assert node_probe.get("ok"), node_probe.get("error")
    ra = node_probe["negativeChecks"]["robotAdapter"]
    assert ra["notPurchasedHidden"] is True
    assert ra["disabledShowsOffline"] is True


def test_t2_f06_06_robot_rejects_worker_only_state_bad_andon_and_core_joint_parity_bva(
    node_probe: dict[str, Any],
) -> None:
    """F6 Negative + BVA: robot.sample('prepare') & bad Andon state throw; 20 core joints match worker < 5mm."""
    assert node_probe.get("ok"), node_probe.get("error")
    assert node_probe["negativeChecks"]["robotAdapter"]["badRobotWorkerState"]["threw"] is True
    assert node_probe["negativeChecks"]["envAndMap"]["badAndonState"]["threw"] is True

    parity = node_probe["characterAudit"]["proportionParity"]
    assert parity["comparedCoreJoints"] == 20, parity
    assert parity["maxCoreJointDiffM"] < 0.005, parity



# ==============================================================================
# FEATURE F7: Scene-Anchored Grasp, VIS_ROBOT_ASSIST Yaw & +12mm Tray Alignment — 6 Tests
# ==============================================================================


def test_t2_f07_01_assist_yaw_cosine_bva_rejects_inverted_yaws_and_verifies_live_alignment(
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F7 BVA/Negative: Yaw π/-2.48/+2.569/0 fail dot >= 0.98; VIS_ROBOT_ASSIST & live helper face robot cell."""
    assert blender_probe.get("ok"), blender_probe.get("error")
    assert node_probe.get("ok"), node_probe.get("error")

    yaw_bva = node_probe["negativeChecks"]["assistYawBva"]
    assert yaw_bva["exactAtan2"]["cos"] > 0.9999 and yaw_bva["exactAtan2"]["deg"] < 0.5
    assert yaw_bva["wrongPi"]["cos"] < 0.60 and yaw_bva["wrongPi"]["deg"] > 50.0
    assert yaw_bva["wrongNeg248"]["cos"] < 0.0 and yaw_bva["wrongNeg248"]["deg"] > 90.0
    assert yaw_bva["wrongPos2569"]["cos"] < 0.94 and yaw_bva["wrongPos2569"]["deg"] > 20.0
    assert yaw_bva["wrongZero"]["cos"] < -0.40 and yaw_bva["wrongZero"]["deg"] > 110.0

    b_assist = blender_probe["artifacts"]["VIS_ROBOT_ASSIST"]
    assert b_assist["exists"] is True
    assert b_assist["cos_sim_to_robot_order"] is not None and b_assist["cos_sim_to_robot_order"] >= 0.98, b_assist

    s_assist = node_probe["layoutAudit"]["staticAssistInfo"]
    assert s_assist is not None
    assert abs(s_assist["expectedYawRad"] - 2.131959739083249) < 1e-6
    assert s_assist["nodeCosSim"] >= 0.98, s_assist
    assert s_assist["bindingsHelperCosSim"] is not None and s_assist["bindingsHelperCosSim"] >= 0.98, s_assist
    if s_assist["spatialAssistCosSim"] is not None:
        assert s_assist["spatialAssistCosSim"] >= 0.98, s_assist

    shifts = node_probe["studioReplayAudit"]["shifts"]
    live_samples = [
        smp
        for sh in shifts.values()
        if isinstance(sh, dict) and sh.get("detailed")
        for smp in (sh.get("assistSamples") or [])
    ]
    assist_active = [smp for smp in live_samples if smp.get("helperClip") == "Assist"]
    assert len(assist_active) >= 2, f"Expected live Assist-pose samples in detailed shift replays, got {live_samples}"
    for smp in assist_active:
        assert smp["distToAnchorM"] <= 0.08, smp
        assert smp["cosSim"] >= 0.9659 and smp["angleErrDeg"] <= 15.0, smp


def test_t2_f07_02_workstation_bilateral_grasp_contact_under_25mm_across_all_20_combinations(
    node_probe: dict[str, Any],
) -> None:
    """F7 BVA: All 20 (stage, regular/oversize clip, tray=0/+12mm) grasp checks achieve L & R contact < 0.025m."""
    assert node_probe.get("ok"), node_probe.get("error")
    grasp = node_probe["characterAudit"]["workstationGrasp"]
    assert len(grasp) == 20, f"Expected 20 workstation grasp combinations, got {len(grasp)}: {sorted(grasp)}"

    offenders = []
    for combo_key, metrics in sorted(grasp.items()):
        if metrics["minDistL"] >= 0.025 or metrics["minDistR"] >= 0.025:
            offenders.append((combo_key, round(metrics["minDistL"], 4), round(metrics["minDistR"], 4)))
    assert offenders == [], f"Workstation grasp contact >= 0.025m (2.5cm): {offenders}"


def test_t2_f07_03_worktop_non_penetration_0858m_floor_across_active_clips(
    node_probe: dict[str, Any],
) -> None:
    """F7 BVA: Hand sockets & active operation_prop bones stay >= 0.858m (<= 2mm tolerance below 0.860m top)."""
    assert node_probe.get("ok"), node_probe.get("error")
    grasp = node_probe["characterAudit"]["workstationGrasp"]
    tray0_keys = [k for k in sorted(grasp) if k.endswith("_tray0")]
    assert len(tray0_keys) == 10, tray0_keys

    penetrations = []
    for key in tray0_keys:
        m = grasp[key]
        if m["minOverBenchSocketY"] < 0.858 or m["minOverBenchPropY"] < 0.858:
            penetrations.append((key, round(m["minOverBenchSocketY"], 4), round(m["minOverBenchPropY"], 4)))
    assert penetrations == [], f"Hand socket or prop penetrates below 0.858m bench top: {penetrations}"


def test_t2_f07_04_adversarial_180deg_pole_flip_rejection_vs_live_smooth_31_clips(
    adversarial_robot_glb_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F7 Negative + Live BVA: Injected 180° step caught (>170°); all 31 live clips stay < 60° & upright."""
    assert adversarial_robot_glb_probe.get("ok"), adversarial_robot_glb_probe
    assert adversarial_robot_glb_probe["clipMetrics"]["Idle"]["maxConsecutiveStepDeg"] > 170.0

    assert node_probe.get("ok"), node_probe.get("error")
    for actor_key, expected_clips in (
        ("worker", CANONICAL_WORKER_CLIPS),
        ("robot", CANONICAL_ROBOT_CLIPS),
    ):
        cm = node_probe["characterAudit"][actor_key]["clipMetrics"]
        for clip_name in expected_clips:
            m = cm[clip_name]
            assert m["nonFiniteMatrices"] == 0, (actor_key, clip_name, m)
            assert m["spineOrderViolations"] == 0, (actor_key, clip_name, m)
            assert m["maxConsecutiveStepDeg"] < 60.0, (actor_key, clip_name, m["maxConsecutiveStepDeg"])
            assert m["minBodyBoneY"] >= -0.02, (actor_key, clip_name, m["minBodyBoneY"])


def test_t2_f07_05_oversize_vs_regular_bilateral_hand_span_delta_and_inward_palm_normals(
    node_probe: dict[str, Any],
) -> None:
    """F7 BVA: _Oversize clips widen bilateral hand X-span vs regular clips; carry/inspect palms oppose."""
    assert node_probe.get("ok"), node_probe.get("error")
    w_cm = node_probe["characterAudit"]["worker"]["clipMetrics"]
    r_cm = node_probe["characterAudit"]["robot"]["clipMetrics"]

    for base_clip, ov_clip in (
        ("Prepare", "Prepare_Oversize"),
        ("Pick", "Pick_Oversize"),
        ("Pack", "Pack_Oversize"),
        ("Inspect", "Inspect_Oversize"),
    ):
        delta = w_cm[ov_clip]["maxHandSpanX"] - w_cm[base_clip]["maxHandSpanX"]
        assert 0.04 <= delta <= 0.24, (
            f"Worker {ov_clip} vs {base_clip} hand-span delta={delta:.4f}m out of [0.04, 0.24]m"
        )

    r_delta = r_cm["RobotPack_Oversize"]["maxHandSpanX"] - r_cm["RobotPack"]["maxHandSpanX"]
    assert 0.04 <= r_delta <= 0.24, f"RobotPack_Oversize vs RobotPack span delta={r_delta:.4f}m"

    for carry_clip in ("CarryIdle", "CarryWalk", "Inspect", "Inspect_Oversize"):
        assert w_cm[carry_clip]["maxPalmDot"] < 0.25, (carry_clip, w_cm[carry_clip]["maxPalmDot"])
    for r_carry in ("CarryIdle", "CarryWalk"):
        assert r_cm[r_carry]["maxPalmDot"] < 0.25, (r_carry, r_cm[r_carry]["maxPalmDot"])


def test_t2_f07_06_live_replay_12mm_trayed_vs_untrayed_support_height_alignment_bva(
    direct_studio_bva_probe: dict[str, Any],
) -> None:
    """F7 BVA: Stationary trayed queue orders place tray at 0.860m & carton at +0.012m; untrayed sits at 0.860m ± 4mm."""
    assert direct_studio_bva_probe.get("ok"), direct_studio_bva_probe
    ta = direct_studio_bva_probe["trayAlignment"]

    cand11_ta = ta["v1-candidate-seed11"]
    cand29_ta = ta["v1-candidate-seed29"]
    man11_ta = ta["v1-manual-seed11"]

    assert cand11_ta["trayHeightChecked"] > 0 and cand11_ta["trayHeightErrors"] == 0, cand11_ta
    assert cand29_ta["trayHeightChecked"] > 0 and cand29_ta["trayHeightErrors"] == 0, cand29_ta
    assert man11_ta["untrayedHeightChecked"] > 0 and man11_ta["untrayedHeightErrors"] == 0, man11_ta


# ==============================================================================
# FEATURE F8: Sub-Tick Motion, Conveyor/Spur Transit, Rollers & Smooth Post-Break — 6 Tests
# ==============================================================================


def test_t2_f08_01_seek_boundary_clamping_t0_and_past_horizon_across_all_9_v1_shifts(
    node_probe: dict[str, Any],
    direct_studio_bva_probe: dict[str, Any],
) -> None:
    """F8 BVA: seekTo(0) & seekTo((horizon+999)*ts) clamp cleanly with 0 final counter mismatches on all 9 runs."""
    assert node_probe.get("ok"), node_probe.get("error")
    assert direct_studio_bva_probe.get("ok"), direct_studio_bva_probe
    sra = node_probe["studioReplayAudit"]
    assert sra["ok"] is True, sra.get("error")
    assert sra["all9RequiredV1Present"] is True, sra["v1RunIds"]

    parity = direct_studio_bva_probe["shiftCounterParity"]
    for run_id in REQUIRED_9_V1_RUN_IDS:
        sh = parity[run_id]
        assert sh["boundaryClampingOk"] is True, (run_id, sh)
        assert sh["counterMismatches"] == 0, (run_id, sh)


def test_t2_f08_02_seek_rejects_nan_and_infinity_with_replay_error(
    node_probe: dict[str, Any],
) -> None:
    """F8 Negative: replay.seekTo(NaN) and replay.seekTo(+Infinity) throw ReplayError cleanly."""
    assert node_probe.get("ok"), node_probe.get("error")
    rn = node_probe["negativeChecks"]["replayNegatives"]
    assert rn["seekNan"]["threw"] is True and rn["seekNan"]["name"] == "ReplayError", rn["seekNan"]
    assert rn["seekInf"]["threw"] is True and rn["seekInf"]["name"] == "ReplayError", rn["seekInf"]


def test_t2_f08_03_post_break_idle_worker_smooth_return_walk_zero_teleport_and_zero_stranding(
    node_probe: dict[str, Any],
) -> None:
    """F8 BVA: At dt=0.10 ticks across break windows, max step <= 2.50m & 0 workers strand in break area."""
    assert node_probe.get("ok"), node_probe.get("error")
    shifts = node_probe["studioReplayAudit"]["shifts"]

    idle_gap_samples = 0
    for run_id in ("v1-manual-seed11", "v1-candidate-seed11", "v1-candidate-seed29", "v1-reference-seed11", "stress-seed137"):
        if run_id not in shifts:
            continue
        brk = shifts[run_id]["breaks"]
        assert brk["count"] >= 4, (run_id, brk)
        assert brk["maxBreakStepJumpM"] <= 2.50, (
            f"{run_id} worker teleported {brk['maxBreakStepJumpM']:.3f}m in 0.10 ticks: {brk['maxBreakJumpInfo']}"
        )
        for chk in brk["breakEndChecks"]:
            if chk["idleGapTicks"] >= 3:
                idle_gap_samples += 1
            assert chk["strandedInBreakArea"] is False, f"{run_id} worker stranded in break area: {chk}"
    assert idle_gap_samples >= 1, "Expected >= 1 post-break worker with >= 3 idle ticks to exercise idle-return BVA"


def test_t2_f08_04_non_monotonic_random_timeline_scrubbing_determinism_bva(
    node_probe: dict[str, Any],
) -> None:
    """F8 BVA: Non-monotonic scrubbing [720.35 -> 12.10 -> 480.25 -> 12.10 -> 720.35] reproduces poses < 1e-4m."""
    assert node_probe.get("ok"), node_probe.get("error")
    shifts = node_probe["studioReplayAudit"]["shifts"]
    for run_id in ("v1-manual-seed11", "v1-candidate-seed11", "v1-candidate-seed29", "v1-reference-seed11", "stress-seed137"):
        if run_id not in shifts:
            continue
        err = shifts[run_id]["maxScrubDeterminismErrM"]
        assert err < 1e-4, f"{run_id} non-monotonic seek scrubbing drifted by {err}"


def test_t2_f08_05_roller_stationary_when_paused_vs_spinning_zero_drift_and_conveyor_monotonicity(
    node_probe: dict[str, Any],
) -> None:
    """F8 BVA: Paused roller delta < 1e-6; playing rollers spin (>0.05 rad) with <2mm drift & +X parcel flow."""
    assert node_probe.get("ok"), node_probe.get("error")
    shifts = node_probe["studioReplayAudit"]["shifts"]
    for run_id in ("v1-manual-seed11", "v1-candidate-seed11", "v1-candidate-seed29", "v1-reference-seed11", "stress-seed137"):
        if run_id not in shifts:
            continue
        sh = shifts[run_id]
        assert sh["stationaryRollerDelta"] < 1e-6, (run_id, sh["stationaryRollerDelta"])
        assert sh["activeRollerMaxAngleRad"] > 0.05, (run_id, sh["activeRollerMaxAngleRad"])
        assert sh["maxRollerCenterDriftM"] < 0.002, (run_id, sh["maxRollerCenterDriftM"])
        tr = sh["transit"]
        assert tr["mainConveyorHits"] > 0 and tr["mainConveyorIncreasingXCount"] > 0, (run_id, tr)
        assert tr["spurHits"] > 0 and tr["qcPortalHits"] > 0, (run_id, tr)


def test_t2_f08_06_rework_attempt_1_never_routed_to_robot_and_populates_north_queue_r(
    node_probe: dict[str, Any],
    direct_studio_bva_probe: dict[str, Any],
) -> None:
    """F8 BVA: attempt >= 1 rework orders never route to robot (robotAssignedAttempt1 == 0) and visit Queue R."""
    assert node_probe.get("ok"), node_probe.get("error")
    assert direct_studio_bva_probe.get("ok"), direct_studio_bva_probe
    shifts = node_probe["studioReplayAudit"]["shifts"]
    saw_rework_shift = False
    saw_scrap_shift = False
    for run_id in ("v1-manual-seed11", "v1-candidate-seed11", "v1-candidate-seed29", "v1-reference-seed11", "stress-seed137"):
        if run_id not in shifts:
            continue
        rw = shifts[run_id]["rework"]
        assert rw["robotAssignedAttempt1"] == 0, f"{run_id} illegally assigned rework attempt>=1 to robot: {rw}"
        if rw["reworkStartedInRaw"] > 0:
            saw_rework_shift = True
            assert rw["reworkInQueueRObserved"] >= 1 or rw["reworkBadgeObserved"] >= 1, (
                f"{run_id} rework neither queued in R nor displayed Stage-3 rework badge: {rw}"
            )
            assert rw.get("reworkBenchWorkerSamples", 0) >= 1 and rw.get("reworkBenchCartonSamples", 0) >= 1, (
                f"{run_id} Stage-3 rework worker/carton never interacted with BENCH_REWORK [1.80, 0, +6.35]: {rw}"
            )
        sc = shifts[run_id].get("scrap") or {}
        if sc.get("scrapInRaw", 0) > 0:
            saw_scrap_shift = True
            assert sc.get("scrapCarryOrTransitObserved", 0) >= 1 and sc.get("scrapBenchOrBinVisibleAtEnd", 0) >= 1, (
                f"{run_id} scrap order vanished instead of routing onto BENCH_SCRAP / SCRAP_BIN: {sc}"
            )
    assert saw_rework_shift is True
    assert saw_scrap_shift is True, "Expected >=1 detailed shift with scrap orders"

    sat = direct_studio_bva_probe["saturatedReworkBva"]
    assert sat["reworkStartedInRaw"] >= 1, sat
    assert sat["robotAssignedAttempt1"] == 0, sat
    assert sat["reworkQueueRObserved"] >= 1, f"Saturated Stage-3 shift never rendered rework order in North Queue R: {sat}"
    assert sat["reworkBadgeVisibleCount"] >= 1, sat


# ==============================================================================
# FEATURE F9: Single-Carton Ownership, Active Props & Map Pipeline Idempotency — 6 Tests
# ==============================================================================


def test_t2_f09_01_zero_empty_hand_prop_leak_and_zero_active_bench_static_duplicate_cartons(
    node_probe: dict[str, Any],
) -> None:
    """F9 BVA: Empty-hand clips have 0 active prop leaks; active benches have 0 duplicate static ORDER_* boxes."""
    assert node_probe.get("ok"), node_probe.get("error")
    shifts = node_probe["studioReplayAudit"]["shifts"]
    for run_id in ("v1-manual-seed11", "v1-candidate-seed11", "v1-candidate-seed29", "v1-reference-seed11", "stress-seed137"):
        if run_id not in shifts:
            continue
        sh = shifts[run_id]
        assert sh["activeWorkstationSamples"] > 0, (run_id, sh["activeWorkstationSamples"])
        assert sh["emptyHandPropLeakCount"] == 0, (run_id, sh["emptyHandPropLeakCount"])
        assert sh["activeBenchDuplicateCollisions"] == 0, (run_id, sh["activeBenchDuplicateCollisions"])


def test_t2_f09_02_oversize_clip_selection_and_mid_operation_prop_phase_progression_bva(
    node_probe: dict[str, Any],
) -> None:
    """F9 BVA: Oversize orders select *_Oversize clips and operation_prop bones advance across [0.35, 0.62, 0.88]."""
    assert node_probe.get("ok"), node_probe.get("error")
    shifts = node_probe["studioReplayAudit"]["shifts"]

    all_w_clips: set[str] = set()
    all_r_clips: set[str] = set()
    oversize_entries = []
    for run_id in ("v1-manual-seed11", "v1-candidate-seed11", "v1-candidate-seed29", "v1-reference-seed11", "stress-seed137"):
        if run_id not in shifts:
            continue
        sh = shifts[run_id]
        all_w_clips.update(sh["observedWorkerClips"])
        all_r_clips.update(sh["observedRobotClips"])
        for key, prog in sh["opPhaseProgression"].items():
            assert prog["maxDiagSeen"] > 0.05, (run_id, key, prog)
            assert prog["mixerTimeSpan"] > 0.05 or prog["maxPropPhaseDelta"] > 0.005, (run_id, key, prog)
            if key.endswith("_oversize"):
                oversize_entries.append((run_id, key, prog))

    assert any(c.endswith("_Oversize") for c in all_w_clips), all_w_clips
    assert any(c.endswith("_Oversize") for c in all_r_clips), all_r_clips
    assert len(oversize_entries) >= 2, oversize_entries
    for run_id, key, prog in oversize_entries:
        assert str(prog["clipSeen"]).endswith("_Oversize"), (run_id, key, prog)


def test_t2_f09_03_map_pipeline_synthetic_native_36m_scene_never_double_scales_to_46m(
    node_probe: dict[str, Any],
    direct_studio_bva_probe: dict[str, Any],
) -> None:
    """F9 BVA: Native 36×18×3.6m scene stays 36.0m × 18.0m × 3.60m (docks ±17.85m), NEVER 46.29m / 6.0m / ±21.85m."""
    assert node_probe.get("ok"), node_probe.get("error")
    assert direct_studio_bva_probe.get("ok"), direct_studio_bva_probe
    syn = direct_studio_bva_probe["mapIdempotency"]["syntheticNative36m"]
    assert syn["ok"] is True, syn.get("error")

    p1 = syn["pass1"]
    assert abs(p1["slabBox"]["span"][0] - 36.0) <= 0.10, p1["slabBox"]
    assert abs(p1["slabBox"]["span"][2] - 18.0) <= 0.10, p1["slabBox"]
    assert abs(p1["wallsBox"]["max"][1] - 3.60) <= 0.05, p1["wallsBox"]
    assert abs(p1["dock01Pos"][0] - (-17.85)) <= 0.15, p1["dock01Pos"]
    assert abs(p1["dock02Pos"][0] - 17.85) <= 0.15, p1["dock02Pos"]

    post_env = node_probe["studioReplayAudit"]["postMapEnvelope"]
    assert post_env is not None
    assert abs(post_env["slabBox"]["span"][0] - 36.0) <= 0.10, post_env["slabBox"]
    assert abs(post_env["wallsBox"]["max"][1] - 3.60) <= 0.05, post_env["wallsBox"]


def test_t2_f09_04_map_pipeline_triple_pass_idempotency_and_dispose_reapply_roundtrip(
    direct_studio_bva_probe: dict[str, Any],
) -> None:
    """F9 BVA: 3x applyMap* passes keep identical meshCount & bounds; dispose() cleans patchGroups & reapplies."""
    assert direct_studio_bva_probe.get("ok"), direct_studio_bva_probe
    shipped = direct_studio_bva_probe["mapIdempotency"]["shipped"]
    assert shipped["ok"] is True, shipped.get("error")

    p1, p2, p3 = shipped["pass1"], shipped["pass2"], shipped["pass3"]
    assert p1["meshCount"] == p2["meshCount"] == p3["meshCount"], (p1["meshCount"], p2["meshCount"], p3["meshCount"])
    assert p1["patchGroups"] == p2["patchGroups"] == p3["patchGroups"]
    for axis in range(3):
        assert abs(p1["slabBox"]["span"][axis] - p3["slabBox"]["span"][axis]) < 1e-5

    assert shipped["afterDispose"]["patchGroups"] == 0, shipped["afterDispose"]
    assert shipped["afterReapply"]["meshCount"] == p1["meshCount"], shipped["afterReapply"]


def test_t2_f09_05_map_pipeline_null_root_and_invalid_camera_preset_rejections(
    node_probe: dict[str, Any],
) -> None:
    """F9 Negative: applyMapGeometryFixes(null, {}) & setCameraPreset('nonexistent_preset') throw cleanly."""
    assert node_probe.get("ok"), node_probe.get("error")
    assert node_probe["negativeChecks"]["envAndMap"]["badMapRoot"]["threw"] is True

    sra = node_probe["studioReplayAudit"]
    assert sra["badCameraPreset"]["threw"] is True, sra["badCameraPreset"]
    presets = sra["cameraPresets"]
    assert presets["overview"]["supported"] is True
    assert presets["q1"]["supported"] is True or presets["q1/pick"]["supported"] is True
    assert presets["robot"]["supported"] is True
    assert presets["qc"]["supported"] is True
    assert presets["break"]["supported"] is True
    assert presets["blueprint"]["supported"] is True, f"Studio 'blueprint' camera preset missing: {presets.get('blueprint')}"
    assert presets["rework"]["supported"] is True, f"Studio 'rework' camera preset missing: {presets.get('rework')}"


def test_t2_f09_06_order_visual_pool_rejects_invalid_kind_and_mid_run_kind_mutation(
    node_probe: dict[str, Any],
) -> None:
    """F9 Negative: createOrderVisualPool rejects kind='invalid' and mutating an order's kind mid-run."""
    assert node_probe.get("ok"), node_probe.get("error")
    op = node_probe["negativeChecks"]["orderPool"]
    assert op["badOrderKind"]["threw"] is True, op["badOrderKind"]
    assert op["kindMutation"]["threw"] is True, op["kindMutation"]


# ==============================================================================
# FEATURE F10: Dynamic Parallel Benches, 36×18m A* Obstacles & Stack Caps — 6 Tests
# ==============================================================================


def test_t2_f10_01_min_1_worker_vs_max_8_worker_parallel_bench_layouts_zero_overlap_bva(
    node_probe: dict[str, Any],
) -> None:
    """F10 BVA: 1-worker spawns 0 parallel benches; 8-worker Stage-3 (5 & 6 slots) & Stages 1/2/4 have 0 overlaps."""
    assert node_probe.get("ok"), node_probe.get("error")
    layouts = node_probe["spatialAudit"]["layouts"]

    single = layouts["singleWorkerMin"]
    assert single["ok"] is True and single["parallelBenchCount"] == 0 and single["pathHits"] == 0, single

    assert layouts["stage3_5slots"]["ok"] is True and layouts["stage3_5slots"]["parallelBenchCount"] == 4
    assert layouts["stage3_6slots"]["ok"] is True and layouts["stage3_6slots"]["parallelBenchCount"] >= 5
    assert layouts["stages124_3slots"]["ok"] is True and layouts["stages124_3slots"]["parallelBenchCount"] >= 6
    assert layouts["stage4_3slots"]["ok"] is True and layouts["stage4_3slots"]["parallelBenchCount"] == 2

    for name, res in layouts.items():
        assert res["ok"] is True, (name, res)
        assert res["overlaps"] == [], f"Parallel bench overlap in {name}: {res['overlaps']}"
        assert res["pathHits"] == 0, f"Walk path intersects obstacle in {name}: {res['pathHits']} hits"


def test_t2_f10_02_full_36x18m_hall_wall_boundary_astar_routes_not_clipped_at_legacy_14m(
    node_probe: dict[str, Any],
) -> None:
    """F10 BVA: A* routes across [-17.6..+17.6] × [-8.6..+8.6] & DOCK_01->DOCK_02 succeed inside hall bounds."""
    assert node_probe.get("ok"), node_probe.get("error")
    routes = node_probe["spatialAudit"]["astarRoutes"]
    for key in ("dock01_to_dock02", "sw_to_ne_corners", "dock01_to_stage1", "boundary_176_86"):
        r = routes[key]
        assert r["ok"] is True, f"A* route {key} failed (legacy 14m clamp?): {r}"
        assert r["inBounds"] is True and r["pointCount"] >= 2, (key, r)


def test_t2_f10_03_trivial_same_point_astar_and_all_8_break_points_distinct_and_reachable(
    node_probe: dict[str, Any],
) -> None:
    """F10 BVA: Zero-length planWalkPath(p, p) returns 2-point segment; 8 BREAK_POINTS >=0.55m apart & 32/32 reachable."""
    assert node_probe.get("ok"), node_probe.get("error")
    triv = node_probe["spatialAudit"]["astarRoutes"]["trivial_same_point"]
    assert triv["ok"] is True and triv["pointCount"] == 2 and triv["start"] == triv["end"], triv

    bp = node_probe["spatialAudit"]["breakPoints"]
    assert bp["count"] == 8, bp
    assert bp["minPairDistM"] >= 0.55, bp
    assert bp["reachableFromStagesCount"] == 32, bp


def test_t2_f10_04_astar_rejects_nan_coordinates_and_fully_enclosed_obstacle_trap(
    node_probe: dict[str, Any],
) -> None:
    """F10 Negative: planWalkPath([NaN, 0, 0], ...) and an enclosed obstacle trap throw cleanly (no hang)."""
    assert node_probe.get("ok"), node_probe.get("error")
    sp = node_probe["negativeChecks"]["spatial"]
    assert sp["badAstarNan"]["threw"] is True, sp["badAstarNan"]
    assert sp["badAstarTrap"]["threw"] is True, sp["badAstarTrap"]


def test_t2_f10_05_spatial_rejects_out_of_range_stages_negative_fractional_slots_and_unknown_worker(
    node_probe: dict[str, Any],
) -> None:
    """F10 Negative: actorPosition rejects stage 0/5, slot -1/1.5, and slotAt rejects unknown worker 'w99'."""
    assert node_probe.get("ok"), node_probe.get("error")
    sp = node_probe["negativeChecks"]["spatial"]
    assert sp["badActorStage0"]["threw"] is True
    assert sp["badActorStage5"]["threw"] is True
    assert sp["badActorNegSlot"]["threw"] is True
    assert sp["badActorFracSlot"]["threw"] is True
    assert sp["badSlotWorker"]["threw"] is True


def test_t2_f10_06_queue_and_outcome_stack_visible_caps_and_exact_overflow_counts_bva(
    node_probe: dict[str, Any],
) -> None:
    """F10 BVA: Q2=12/0, Q3=10/0, Q4=8/0 exact caps; Q1(25)=18/7, R(25)=18/7, good/escaped(20)=12/8, scrap(15)=8/7."""
    assert node_probe.get("ok"), node_probe.get("error")
    ss = node_probe["spatialAudit"]["stackSummary"]
    expected = {
        "Q2_12": (12, 0),
        "Q3_10": (10, 0),
        "Q4_8": (8, 0),
        "Q1_25": (18, 7),
        "R_25": (18, 7),
        "good_20": (12, 8),
        "escaped_20": (12, 8),
        "scrap_15": (8, 7),
    }
    for key, (vis_exp, ov_exp) in expected.items():
        actual = ss[key]
        assert (actual["visibleCount"], actual["overflow"]) == (vis_exp, ov_exp), (key, actual)


# ==============================================================================
# FEATURE F11: Cross-Config Sync, Asset Hashes, Studio Staging & Build Parity — 6 Tests
# ==============================================================================


def test_t2_f11_01_prepare_assets_rejects_1byte_tampered_glb_in_tmp_path_sandbox(
    repo_root: Path,
    v02_dir: Path,
    studio_dir: Path,
    tmp_path: Path,
) -> None:
    """F11 Negative + BVA: prepare-assets.mjs succeeds on untampered hashes then rejects 1-byte carton_closed.glb flip."""
    env = build_e2e_env(repo_root)
    node_bin = env["NODE_BIN"]

    sb_v02 = tmp_path / "4_Horses_Environment_v02"
    sb_modules = sb_v02 / "modules"
    sb_modules.mkdir(parents=True, exist_ok=True)
    for item in v02_dir.iterdir():
        if item.name == "modules":
            continue
        (sb_v02 / item.name).symlink_to(item)
    for mod_item in (v02_dir / "modules").iterdir():
        if mod_item.name == "carton_closed.glb":
            shutil.copy2(mod_item, sb_modules / mod_item.name)
        else:
            (sb_modules / mod_item.name).symlink_to(mod_item)

    baseline_hashes: dict[str, dict[str, Any]] = {}
    for rel in ALL_15_GLB_RELS:
        raw_bytes = (sb_v02 / rel).read_bytes()
        baseline_hashes[f"4_Horses_Environment_v02/{rel}"] = {
            "bytes": len(raw_bytes),
            "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        }

    sb_studio = tmp_path / "studio"
    sb_scripts = sb_studio / "scripts"
    sb_scripts.mkdir(parents=True, exist_ok=True)
    (sb_studio / "asset-hashes.json").write_text(json.dumps(baseline_hashes, indent=2), encoding="utf-8")
    shutil.copy2(studio_dir / "scripts" / "prepare-assets.mjs", sb_scripts / "prepare-assets.mjs")

    clean_run = subprocess.run(
        [node_bin, str(sb_scripts / "prepare-assets.mjs")],
        cwd=str(sb_studio),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert clean_run.returncode == 0, f"Untampered sandbox failed prepare-assets.mjs: {clean_run.stderr}"

    # Flip 1 byte in carton_closed.glb and verify prepare-assets.mjs rejects it specifically
    tampered_bytes = bytearray((sb_modules / "carton_closed.glb").read_bytes())
    tampered_bytes[-1] ^= 0xFF
    (sb_modules / "carton_closed.glb").write_bytes(bytes(tampered_bytes))

    tampered_run = subprocess.run(
        [node_bin, str(sb_scripts / "prepare-assets.mjs")],
        cwd=str(sb_studio),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    combined_err = (tampered_run.stdout or "") + "\n" + (tampered_run.stderr or "")
    assert tampered_run.returncode != 0, "prepare-assets.mjs failed to reject 1-byte tampered GLB!"
    assert "Original GLB changed" in combined_err and "carton_closed.glb" in combined_err, combined_err


def test_t2_f11_02_exact_14_module_glbs_zero_stray_files_and_valid_gltf_v2_binary_headers(
    v02_dir: Path,
) -> None:
    """F11 BVA: modules/ has exact 14 canonical .glb files (0 .bak/.tmp/strays) & all 15 GLBs have v2 headers."""
    mod_entries = sorted(p.name for p in (v02_dir / "modules").iterdir())
    expected_mods = sorted(Path(r).name for r in ALL_15_GLB_RELS if r.startswith("modules/"))
    assert len(expected_mods) == 14
    assert mod_entries == expected_mods, f"Unexpected or missing files in modules/: {mod_entries}"

    for rel in ALL_15_GLB_RELS:
        p = v02_dir / rel
        raw = p.read_bytes()
        assert len(raw) >= 28, rel
        magic, version, total_len = struct.unpack_from("<III", raw, 0)
        assert magic == 0x46546C67 and version == 2 and total_len == len(raw), (rel, magic, version, total_len, len(raw))


def test_t2_f11_03_visual_bindings_three_way_byte_and_semantic_parity(
    v02_configs: dict[str, Any],
    studio_dir: Path,
) -> None:
    """F11 BVA: v02/visual_bindings.json, v02/config/visual_bindings.json & studio/public/scene match."""
    f_root = v02_configs["files"]["visual_bindings"]
    f_cfg = v02_configs["files"]["config_visual_bindings"]
    assert f_root["ok"] and f_cfg["ok"], (f_root["error"], f_cfg["error"])
    assert f_root["data"] == f_cfg["data"], "visual_bindings.json drifted from config/visual_bindings.json"

    staged_vb = studio_dir / "public" / "scene" / "visual_bindings.json"
    assert staged_vb.exists(), f"Missing staged {staged_vb}"
    assert json.loads(staged_vb.read_text(encoding="utf-8")) == f_root["data"]


def test_t2_f11_04_environment_config_dual_copy_parity_and_exact_36x18x36_room_contract(
    v02_configs: dict[str, Any],
) -> None:
    """F11 BVA: environment_config.json == config/environment.json with room 36×18×3.6m & matching anchors."""
    f_env = v02_configs["files"]["environment_config"]
    f_cfg = v02_configs["files"]["config_environment"]
    f_anc = v02_configs["files"]["anchors"]
    assert f_env["ok"] and f_cfg["ok"] and f_anc["ok"]
    assert f_env["data"] == f_cfg["data"], "environment_config.json drifted from config/environment.json"
    room = f_env["data"].get("room")
    assert room == {"width": 36, "depth": 18, "wall_height": 3.6}, room


def test_t2_f11_05_asset_hashes_asset_stats_and_staged_scene_sha256_parity_across_all_15_glbs(
    v02_configs: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F11 BVA: studio/asset-hashes.json, asset_stats_v02.json, public/scene & dist/scene match live SHA-256."""
    assert node_probe.get("ok"), node_probe.get("error")
    hashes_doc = v02_configs["studio_asset_hashes"]
    stats_doc = v02_configs["asset_stats_v02"]
    assert isinstance(hashes_doc, dict), "studio/asset-hashes.json missing or invalid"
    assert isinstance(stats_doc, dict) and isinstance(stats_doc.get("files"), (dict, list)), "asset_stats_v02.json invalid"
    raw_stats_files = stats_doc["files"]
    if isinstance(raw_stats_files, list):
        stats_by_rel = {
            str(entry.get("file") or entry.get("path") or "").removeprefix("4_Horses_Environment_v02/"): entry
            for entry in raw_stats_files
            if isinstance(entry, dict)
        }
    else:
        stats_by_rel = {
            str(k).removeprefix("4_Horses_Environment_v02/"): v
            for k, v in raw_stats_files.items()
        }

    gv = node_probe["gltfValidation"]
    hash_entries = hashes_doc.get("files") if isinstance(hashes_doc.get("files"), dict) else hashes_doc
    mismatches = []
    for rel in ALL_15_GLB_RELS:
        live = gv[rel]
        rec = hash_entries.get(f"4_Horses_Environment_v02/{rel}") or hash_entries.get(rel)
        if not isinstance(rec, dict) or rec.get("sha256") != live["sha256"] or rec.get("bytes") != live["bytes"]:
            mismatches.append((rel, rec, live["sha256"], live["bytes"]))
        st_rec = stats_by_rel.get(rel)
        if not isinstance(st_rec, dict) or st_rec.get("bytes") != live["bytes"]:
            mismatches.append((f"asset_stats:{rel}", st_rec, live["bytes"]))
    assert mismatches == [], f"Asset hash/byte parity mismatches: {mismatches}"

    sba = node_probe["studioBundleAudit"]
    assert sba["publicScene"]["exists"] is True and sba["publicScene"]["missingAssets"] == [], sba["publicScene"]
    assert sba["publicScene"]["parityMismatches"] == [], sba["publicScene"]
    assert sba["dist"]["exists"] is True and sba["dist"]["scene"]["exists"] is True, sba["dist"]
    assert sba["dist"]["scene"]["missingAssets"] == [] and sba["dist"]["scene"]["parityMismatches"] == [], sba["dist"]


def test_t2_f11_06_studio_dist_html_asset_references_resolve_and_v02_npm_sandbox_passes(
    studio_dir: Path,
    v02_configs: dict[str, Any],
    run_v02_npm_test_sandbox,
) -> None:
    """F11 BVA: studio/dist/index.html JS/CSS refs exist with >0 bytes; v02 check_v02.mjs passes in sandbox."""
    dist_dir = studio_dir / "dist"
    index_html = dist_dir / "index.html"
    assert index_html.exists(), "studio/dist/index.html missing (run pnpm build)"
    html = index_html.read_text(encoding="utf-8")

    refs = re.findall(r"""(?:src|href)=["']([^"']+)["']""", html)
    local_asset_refs = [r for r in refs if "/assets/" in r or r.startswith("./assets/") or r.startswith("assets/")]
    assert len(local_asset_refs) >= 2, f"Expected bundled JS & CSS refs in dist/index.html, got {refs}"
    for ref in local_asset_refs:
        clean_rel = ref.lstrip("./").lstrip("/")
        target = dist_dir / clean_rel
        assert target.is_file() and target.stat().st_size > 0, f"Broken dist asset ref {ref!r} -> {target}"

    pkg_v02 = v02_configs["v02_package_json"]
    assert isinstance(pkg_v02, dict) and "test" in (pkg_v02.get("scripts") or {}), pkg_v02
    sb_res = run_v02_npm_test_sandbox()
    assert sb_res["ok"] is True, f"v02 check_v02.mjs failed in sandbox: {sb_res}"


# ==============================================================================
# FEATURE F12: Fresh Blender Renders, Resolution/Entropy Gates & PNG Integrity — 6 Tests
# ==============================================================================


def _fast_rgba_png(width: int, height: int, row_builder) -> bytes:
    """Construct a valid 8-bit RGBA PNG quickly using row byte slices (avoids 1.6M per-pixel loops)."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw.extend(row_builder(y, width))
    idat = zlib.compress(bytes(raw), level=1)

    def _chunk(ctype: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(ctype + body) & 0xFFFFFFFF
        return struct.pack(">I4s", len(body), ctype) + body + struct.pack(">I", crc)

    return PNG_SIG + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def test_t2_f12_01_png_validator_rejects_bad_magic_and_1bit_flipped_idat_crc32() -> None:
    """F12 Negative: inspect_png_bytes rejects JPEG/corrupt magic and 1-bit CRC32 corruption with ValueError."""
    valid_png = make_synthetic_png(32, 32)
    with pytest.raises(ValueError, match="Invalid PNG magic signature"):
        inspect_png_bytes(b"\xff\xd8\xff\xe0" + valid_png[4:])

    # Flip 1 bit inside the IDAT payload without recomputing its trailing CRC32
    idat_idx = valid_png.index(b"IDAT")
    tampered = bytearray(valid_png)
    tampered[idat_idx + 6] ^= 0x01
    with pytest.raises(ValueError, match="CRC32 mismatch"):
        inspect_png_bytes(bytes(tampered))


def test_t2_f12_02_png_validator_rejects_truncated_idat_missing_iend_and_invalid_filter_99() -> None:
    """F12 Negative: Truncated IDAT, stripped IEND, and scanline filter byte 99 raise ValueError."""
    valid_png = make_synthetic_png(24, 24)

    with pytest.raises(ValueError, match="Truncated PNG chunk"):
        inspect_png_bytes(valid_png[:-18])

    iend_chunk_start = valid_png.rindex(b"IEND") - 4
    with pytest.raises(ValueError, match="Missing required IHDR/IDAT/IEND"):
        inspect_png_bytes(valid_png[:iend_chunk_start])

    ihdr = struct.pack(">IIBBBBB", 8, 8, 8, 6, 0, 0, 0)
    bad_scan = bytes([99] + [128] * (8 * 4)) * 8
    bad_idat = zlib.compress(bad_scan, level=1)

    def _ck(ct: bytes, bd: bytes) -> bytes:
        return struct.pack(">I4s", len(bd), ct) + bd + struct.pack(">I", zlib.crc32(ct + bd) & 0xFFFFFFFF)

    bad_filter_png = PNG_SIG + _ck(b"IHDR", ihdr) + _ck(b"IDAT", bad_idat) + _ck(b"IEND", b"")
    with pytest.raises(ValueError, match="Invalid PNG scanline filter 99"):
        inspect_png_bytes(bad_filter_png)


def test_t2_f12_03_render_quality_rejects_solid_background_and_flat_two_color_pngs() -> None:
    """F12 Negative: Solid #dce2e8 (1280×720) & 2-color flat bands fail rgb_std, unique_5bit & entropy gates."""
    solid_row = bytes([0xDC, 0xE2, 0xE8, 0xFF]) * 1280
    solid_png = _fast_rgba_png(1280, 720, lambda _y, _w: solid_row)
    solid_metrics = inspect_png_bytes(solid_png, sample_stride=4)
    solid_errs = validate_render_quality(solid_metrics, is_overview=False)
    assert any("rgb_std" in e for e in solid_errs), solid_errs
    assert any("unique_5bit" in e for e in solid_errs), solid_errs
    assert any("entropy_bits" in e for e in solid_errs), solid_errs

    row_a = bytes([30, 40, 50, 255]) * 1280
    row_b = bytes([210, 200, 190, 255]) * 1280
    two_color_png = _fast_rgba_png(1280, 720, lambda y, _w: row_a if y < 360 else row_b)
    two_metrics = inspect_png_bytes(two_color_png, sample_stride=4)
    two_errs = validate_render_quality(two_metrics, is_overview=False)
    assert any("unique_5bit" in e for e in two_errs), two_errs
    assert any("entropy_bits" in e for e in two_errs), two_errs


def test_t2_f12_04_exact_resolution_cutoff_bva_1200x720_detail_and_1600x1000_overview() -> None:
    """F12 BVA: 1199×720 & 1200×719 fail while 1200×720 passes; 1599×1000 & 1600×999 fail while 1600×1000 passes."""
    base_rich = inspect_png_bytes(make_synthetic_png(64, 64), sample_stride=1)
    rich_template = {
        **base_rich,
        "third_foreground_ratio": [0.55, 0.75, 0.55],
    }

    assert any("Resolution" in e for e in validate_render_quality({**rich_template, "width": 1199, "height": 720}))
    assert any("Resolution" in e for e in validate_render_quality({**rich_template, "width": 1200, "height": 719}))
    assert validate_render_quality({**rich_template, "width": 1200, "height": 720}) == []

    assert any(
        "Resolution" in e
        for e in validate_render_quality({**rich_template, "width": 1599, "height": 1000}, is_overview=True)
    )
    assert any(
        "Resolution" in e
        for e in validate_render_quality({**rich_template, "width": 1600, "height": 999}, is_overview=True)
    )
    assert validate_render_quality({**rich_template, "width": 1600, "height": 1000}, is_overview=True) == []


def test_t2_f12_05_east_clipped_overview_framing_rejected_while_live_overview_passes_bva(
    v02_dir: Path,
) -> None:
    """F12 Negative + Live BVA: Overview with blank East third (<12% fg) fails; live environment_overview.png passes."""
    pattern_16 = bytearray()
    for i in range(16):
        pattern_16.extend(((i * 53) & 0xFF, (i * 97 + 40) & 0xFF, (i * 137 + 90) & 0xFF, 255))
    bg_px = bytes([0xDC, 0xE2, 0xE8, 0xFF])

    def _east_clipped_row(y: int, width: int) -> bytes:
        fg_w = (width * 2) // 3
        bg_w = width - fg_w
        y_shift = ((y * 29) & 0xFF)
        tile = bytes(((b + y_shift) & 0xFF) if idx % 4 != 3 else 255 for idx, b in enumerate(pattern_16))
        fg_part = (tile * ((fg_w // 16) + 1))[: fg_w * 4]
        return fg_part + (bg_px * bg_w)

    clipped_png = _fast_rgba_png(1600, 1000, _east_clipped_row)
    clipped_metrics = inspect_png_bytes(clipped_png, sample_stride=4)
    assert clipped_metrics["third_foreground_ratio"][2] < 0.05, clipped_metrics
    clipped_errs = validate_render_quality(clipped_metrics, is_overview=True)
    assert any("Overview horizontal third foreground framing" in e for e in clipped_errs), clipped_errs

    live_overview = v02_dir / "environment_overview.png"
    assert live_overview.is_file(), f"Missing {live_overview}"
    live_metrics = inspect_png_bytes(live_overview.read_bytes(), sample_stride=4)
    live_errs = validate_render_quality(live_metrics, is_overview=True)
    assert live_errs == [], f"Live environment_overview.png failed quality/framing gates: {live_errs} ({live_metrics})"


def test_t2_f12_06_render_suite_all_valid_non_empty_and_100pct_pairwise_distinct_sha256(
    node_probe: dict[str, Any],
) -> None:
    """F12 BVA: Every renders_presentation/*.png (>=8) & detail_*.png passes quality gates with unique SHA-256."""
    assert node_probe.get("ok"), node_probe.get("error")
    files = node_probe["pngAudit"]["files"]

    pres_keys = sorted(k for k in files if k.startswith("renders_presentation/") and k.endswith(".png"))
    detail_keys = sorted(k for k in files if k.startswith("detail_") and k.endswith(".png"))
    assert len(pres_keys) >= 8, f"Expected >= 8 presentation renders, found {pres_keys}"
    assert len(detail_keys) >= 3, f"Expected >= 3 detail_*.png renders, found {detail_keys}"

    seen_hashes: dict[str, str] = {}
    duplicates: list[tuple[str, str, str]] = []
    for key in [*pres_keys, *detail_keys]:
        info = files[key]
        assert info["valid"] is True, (key, info)
        py_style = {
            "width": info["width"],
            "height": info["height"],
            "rgb_std": tuple(info["rgbStd"]),
            "unique_5bit": info["unique5bit"],
            "entropy_bits": info["entropyBits"],
            "third_foreground_ratio": info["thirdForegroundRatio"],
        }
        q_errs = validate_render_quality(py_style, is_overview=False)
        assert q_errs == [], (key, q_errs, py_style)
        h = info["sha256"]
        if h in seen_hashes:
            duplicates.append((seen_hashes[h], key, h))
        else:
            seen_hashes[h] = key
    assert duplicates == [], f"Duplicate/copied render outputs detected: {duplicates}"


# ==============================================================================
# FEATURE F13: Frozen Core Benchmark, Replay Pack Export & Safe HTTP Serving — 6 Tests
# ==============================================================================


def _raw_http_request(
    host: str,
    port: int,
    method: str,
    target: str,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection(host, port, timeout=5.0)
    try:
        conn.request(method, target, headers=headers or {})
        resp = conn.getresponse()
        body = resp.read()
        hdrs = {k.lower(): v for k, v in resp.getheaders()}
        return resp.status, hdrs, body
    finally:
        conn.close()


def test_t2_f13_01_serve_3d_blocks_directory_listing_path_traversal_absolute_uri_nul_and_symlinks(
    live_serve_3d_pack: dict[str, Any],
) -> None:
    """F13 Negative/Security: serve_3d returns 403 on dir/traversal/NUL/symlink, 400 on abs URI, 404 on missing."""
    host = live_serve_3d_pack["host"]
    port = live_serve_3d_pack["port"]

    for forbidden_target in (
        "/",
        "/v1-candidate-seed11/",
        "/../pyproject.toml",
        "/%2e%2e/pyproject.toml",
        "//evil.example/index.json",
        "/index.json%00",
        "/evil_symlink.json",
    ):
        status, hdrs, _ = _raw_http_request(host, port, "GET", forbidden_target)
        assert status == 403, f"Expected 403 for {forbidden_target!r}, got {status}"
        assert hdrs.get("access-control-allow-origin") == "*", (forbidden_target, hdrs)

    status_abs, _, _ = _raw_http_request(host, port, "GET", "http://evil.example/index.json")
    assert status_abs == 400, status_abs

    status_404, _, _ = _raw_http_request(host, port, "GET", "/nonexistent_shift_999.json")
    assert status_404 == 404, status_404


def test_t2_f13_02_serve_3d_rejects_post_put_delete_405_invalid_ranges_416_and_serves_1byte_206(
    live_serve_3d_pack: dict[str, Any],
) -> None:
    """F13 BVA/Negative: POST/PUT/DELETE -> 405; invalid byte Ranges -> 416; unknown unit -> 200; 0-0 & -16 -> 206."""
    host = live_serve_3d_pack["host"]
    port = live_serve_3d_pack["port"]
    full_bytes = (live_serve_3d_pack["serve_pack"] / "index.json").read_bytes()

    for bad_method in ("POST", "PUT", "DELETE"):
        st, hdrs, _ = _raw_http_request(host, port, bad_method, "/index.json")
        assert st == 405, (bad_method, st)
        assert "GET" in hdrs.get("allow", "") and "HEAD" in hdrs.get("allow", ""), hdrs

    for bad_range in ("bytes=99999999-100000000", "bytes=0-1,4-5", "bytes=10-3", "bytes=-0"):
        st_r, hdrs_r, _ = _raw_http_request(host, port, "GET", "/index.json", {"Range": bad_range})
        assert st_r == 416, (bad_range, st_r)
        assert hdrs_r.get("content-range") == f"bytes */{len(full_bytes)}", (bad_range, hdrs_r)

    # RFC 9110 §14.2: unknown range unit (items=0-5) must be ignored and served as full 200 OK
    st_unk, _, body_unk = _raw_http_request(host, port, "GET", "/index.json", {"Range": "items=0-5"})
    assert st_unk == 200 and body_unk == full_bytes, st_unk

    st_1b, hdrs_1b, body_1b = _raw_http_request(host, port, "GET", "/index.json", {"Range": "bytes=0-0"})
    assert st_1b == 206 and body_1b == full_bytes[:1], (st_1b, body_1b)
    assert hdrs_1b.get("content-range") == f"bytes 0-0/{len(full_bytes)}", hdrs_1b

    st_suf, _, body_suf = _raw_http_request(host, port, "GET", "/index.json", {"Range": "bytes=-16"})
    assert st_suf == 206 and body_suf == full_bytes[-16:], (st_suf, body_suf)


def test_t2_f13_03_export_3d_pack_rejects_protected_dirs_symlinks_and_invalid_seed_boundaries(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    """F13 Negative/BVA: _check_safe_out_dir rejects repo/protected/file/symlinks; _validate_seeds checks 0/-1/bool/dup."""
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from scripts import export_3d_pack

    with pytest.raises(ValueError, match="repository root"):
        export_3d_pack._check_safe_out_dir(repo_root)
    with pytest.raises(ValueError, match="protected repository path"):
        export_3d_pack._check_safe_out_dir(repo_root / "src" / "nested_out")

    reg_file = tmp_path / "not_a_dir.txt"
    reg_file.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="not a directory"):
        export_3d_pack._check_safe_out_dir(reg_file)

    real_dir = tmp_path / "real_out"
    real_dir.mkdir()
    sym_dir = tmp_path / "sym_out"
    sym_dir.symlink_to(real_dir)
    with pytest.raises(ValueError, match="Refusing symlink output directory"):
        export_3d_pack._check_safe_out_dir(sym_dir)

    (real_dir / "inner_link").symlink_to(reg_file)
    with pytest.raises(ValueError, match="Refusing symlink inside output directory"):
        export_3d_pack._check_safe_out_dir(real_dir)

    clean_dir = tmp_path / "clean_pack_out"
    assert export_3d_pack._check_safe_out_dir(clean_dir) == clean_dir

    assert export_3d_pack._validate_seeds([0, 11, 29]) == [0, 11, 29]
    for bad_seeds in ([], [-1], [True], [11, 11]):
        with pytest.raises(ValueError):
            export_3d_pack._validate_seeds(bad_seeds)  # type: ignore[arg-type]


def test_t2_f13_04_studio_replay_rejects_tampered_format_economy_raw_non_monotonic_overflow_and_truncated(
    node_probe: dict[str, Any],
) -> None:
    """F13 Negative: createReplay throws ReplayError on badFormat, badEcon, badRaw, nonMonotonicTick, q2Overflow & truncated."""
    assert node_probe.get("ok"), node_probe.get("error")
    rn = node_probe["negativeChecks"]["replayNegatives"]
    for key in ("badFormat", "badEcon", "badRaw", "nonMonotonicTick", "q2Overflow", "truncatedMissingFinish"):
        res = rn[key]
        assert res["threw"] is True and res["name"] == "ReplayError", (key, res)


def test_t2_f13_05_studio_data_loader_rejects_parent_traversal_events_file_and_invalid_quarter_weeks(
    direct_studio_bva_probe: dict[str, Any],
) -> None:
    """F13 Negative: openLocal('../secret.jsonl'), ftp:// remote & quarterly packs with 0 or 13 weeks throw DataError."""
    assert direct_studio_bva_probe.get("ok"), direct_studio_bva_probe
    dn = direct_studio_bva_probe["dataNegatives"]
    for key in ("badEventsFile", "badQuarter13Weeks", "badQuarter0Weeks", "badRemoteScheme", "emptyLocalFiles"):
        res = dn[key]
        assert res["threw"] is True and res["name"] == "DataError", (key, res)


def test_t2_f13_06_python_plan_bva_negatives_and_frozen_core_immutability_and_pytest_suite(
    repo_root: Path,
    v02_configs: dict[str, Any],
    core_pytest_report: dict[str, Any],
) -> None:
    """F13 BVA/Negative: parse_plan/decode_plan enforce 1..8 workers & route rules; frozen core has >=90 passed & 0 diff."""
    src_dir = str(repo_root / "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    from robotization_bench.contracts import SCHEMA_VERSION, InvalidPlan
    from robotization_bench.validation import decode_plan, parse_plan

    world = v02_configs["world_spec"]
    assert isinstance(world, dict), "data/world_spec.json missing or invalid"

    # Exact valid lower (1 worker) and upper (8 workers) BVA plans
    min_plan = parse_plan(
        {"schema_version": SCHEMA_VERSION, "robot": False, "trays": False, "route": "manual", "workers": [[1, 2, 3, 4]]},
        world,
    )
    max_plan = parse_plan(
        {
            "schema_version": SCHEMA_VERSION,
            "robot": True,
            "trays": True,
            "route": "bypass",
            "workers": [[1], [2], [3], [3], [3], [3], [4], [4]],
        },
        world,
    )
    assert len(min_plan.workers) == 1 and len(max_plan.workers) == 8

    invalid_plans = [
        {"schema_version": SCHEMA_VERSION, "robot": False, "trays": False, "route": "manual", "workers": []},
        {"schema_version": SCHEMA_VERSION, "robot": False, "trays": False, "route": "manual", "workers": [[1]] * 9},
        {"schema_version": SCHEMA_VERSION, "robot": False, "trays": False, "route": "manual", "workers": [[0]]},
        {"schema_version": SCHEMA_VERSION, "robot": False, "trays": False, "route": "manual", "workers": [[5]]},
        {"schema_version": SCHEMA_VERSION, "robot": False, "trays": False, "route": "manual", "workers": [[1, 1]]},
        {"schema_version": SCHEMA_VERSION, "robot": False, "trays": False, "route": "bypass", "workers": [[1, 2, 3, 4]]},
    ]
    for bad_obj in invalid_plans:
        with pytest.raises(InvalidPlan):
            parse_plan(bad_obj, world)

    dup_key_json = (
        f'{{"schema_version": {SCHEMA_VERSION}, "robot": false, "robot": true, '
        f'"trays": false, "route": "manual", "workers": [[1]]}}'
    )
    nan_json = (
        f'{{"schema_version": NaN, "robot": false, "trays": false, "route": "manual", "workers": [[1]]}}'
    )
    for bad_text in (dup_key_json, nan_json):
        with pytest.raises(InvalidPlan):
            decode_plan(bad_text, world)

    assert core_pytest_report["ok"] is True, core_pytest_report
    assert core_pytest_report["passed"] >= 90 and core_pytest_report["failed"] == 0, core_pytest_report
    assert core_pytest_report["frozen_core_git_diff_rc"] == 0, core_pytest_report["frozen_core_git_diff"]

    # Scoped immutable contract diff check (strictly scoped per 2026-11-15T01:47:10Z workspace safety rule)
    scoped_paths = [
        "src/robotization_bench",
        "data/world_spec.json",
        "scripts/export_3d_pack.py",
        "scripts/serve_3d.py",
        *[str(p.relative_to(repo_root)) for p in sorted((repo_root / "tests").glob("test_*.py"))],
    ]
    if (repo_root / "studio" / "public" / "demo-pack").exists():
        scoped_paths.append("studio/public/demo-pack")

    diff_check = subprocess.run(
        ["git", "diff", "--exit-code", "HEAD", "--", *scoped_paths],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert diff_check.returncode == 0, f"Frozen core/benchmark contract modified:\n{diff_check.stdout}"
