"""Tier 4 Application-Level End-to-End Scenarios for 4 Horses Environment v02 (`tests_e2e/`).

Implements all 8 realistic end-to-end shift, grading, bundle, HTTP bridge, and presentation scenarios
defined in `TEST_INFRA.md` § Real-World Application Scenarios:

1. `test_t4_s01_manual_baseline_full_shifts_e2e` (`F1, F3, F5, F8, F10, F13`)
2. `test_t4_s02_automated_candidate_full_shifts_e2e` (`F1, F4, F5, F6, F7, F8, F9, F13`)
3. `test_t4_s03_reference_optimal_policy_grading_and_3d_replay_e2e` (`F1, F6, F7, F8, F9, F13`)
4. `test_t4_s04_custom_high_stress_jam_break_rework_scrap_pipeline_e2e` (`F1, F5, F6, F7, F8, F9, F13`)
5. `test_t4_s05_max_8_worker_staffing_and_cross_hall_routing_e2e` (`F2, F3, F8, F10, F13`)
6. `test_t4_s06_cold_start_production_studio_bundle_and_15_glb_integrity_e2e` (`F2, F4, F5, F6, F9, F11`)
7. `test_t4_s07_live_http_3d_bridge_catalog_and_range_streaming_e2e` (`F8, F11, F13`)
8. `test_t4_s08_jury_presentation_readiness_and_multizone_visual_audit_e2e` (`F1, F2, F4, F5, F6, F7, F12`)
"""

from __future__ import annotations

from fractions import Fraction
import http.client
import inspect
import json
from pathlib import Path
import re
from typing import Any
import urllib.request

from tests_e2e.conftest import REQUIRED_9_V1_RUN_IDS, build_e2e_env, is_stage3_pack_station
from tests_e2e.helpers import validate_render_quality
from tests_e2e.test_tier3_interactions import (
    _audit_blend_ceiling_and_lights,
    _audit_workstation_grounding_and_map_idempotency,
    _check_frozen_benchmark_contracts_git_clean,
    _verify_bundle_deep_counters,
)

ALL_15_GLBS = (
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

STAGE_ZONE_PATTERNS: dict[str, re.Pattern[str]] = {
    "S0_INBOUND": re.compile(r"(inbound|dock_?0?1|q1|s0)", re.IGNORECASE),
    "S1_PREP": re.compile(r"(prep|stage_?0?1|s1)", re.IGNORECASE),
    "S2_PICK": re.compile(r"(pick|stage_?0?2|s2|storage)", re.IGNORECASE),
    "S3A_PACK_MANUAL": re.compile(r"(pack|stage_?0?3|s3a)", re.IGNORECASE),
    "S3B_S3C_ROBOT_ASSIST": re.compile(r"(robot|assist|jam|service|s3b|s3c)", re.IGNORECASE),
    "S4_QC": re.compile(r"(qc|inspect|stage_?0?4|s4)", re.IGNORECASE),
    "S5C_S5D_REWORK_SCRAP": re.compile(r"(rework|scrap|queue_?r|s5c|s5d)", re.IGNORECASE),
    "S5A_S5B_DISPATCH_DOCK02": re.compile(
        r"(good|dispatch|outbound|dock_?0?2|escaped|s5a|s5b)", re.IGNORECASE
    ),
    "S5E_BREAK": re.compile(r"(break|s5e|kpi)", re.IGNORECASE),
}


def _png_camel_to_snake(entry: dict[str, Any]) -> dict[str, Any]:
    rgb_std = entry.get("rgbStd") or entry.get("rgb_std") or (0.0, 0.0, 0.0)
    return {
        "width": int(entry.get("width") or 0),
        "height": int(entry.get("height") or 0),
        "bit_depth": int(entry.get("bitDepth") or entry.get("bit_depth") or 0),
        "color_type": int(entry.get("colorType") or entry.get("color_type") or 0),
        "rgb_std": tuple(float(x) for x in rgb_std),
        "unique_5bit": int(entry.get("unique5bit") or entry.get("unique_5bit") or 0),
        "entropy_bits": float(entry.get("entropyBits") or entry.get("entropy_bits") or 0.0),
        "third_foreground_ratio": list(
            entry.get("thirdForegroundRatio") or entry.get("third_foreground_ratio") or [0.0, 0.0, 0.0]
        ),
    }


def _lookup_studio_hash_record(hashes_data: Any, rel: str) -> dict[str, Any] | None:
    if not isinstance(hashes_data, dict):
        return None
    files_sub = hashes_data.get("files")
    if isinstance(files_sub, dict) and isinstance(files_sub.get(rel), dict):
        return files_sub[rel]
    prefixed = f"4_Horses_Environment_v02/{rel}"
    if isinstance(hashes_data.get(prefixed), dict):
        return hashes_data[prefixed]
    if isinstance(hashes_data.get(rel), dict):
        return hashes_data[rel]
    return None


def _solve_reference_policy(world: dict[str, Any], dev_days: tuple[Any, ...]) -> dict[str, Any]:
    from robotization_bench import episode, reference

    sig = inspect.signature(episode.Episode)
    try:
        ep = episode.Episode(world, dev_days)
        return reference.solve(ep)
    except RuntimeError:
        if "max_pilots" in sig.parameters:
            ep = episode.Episode(world, dev_days, max_pilots=64)
            return reference.solve(ep)
        raise


def _raw_http_request(
    host: str,
    port: int,
    method: str,
    raw_target: str,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection(host, port, timeout=5.0)
    try:
        conn.putrequest(method, raw_target, skip_accept_encoding=True)
        if headers:
            for k, v in headers.items():
                conn.putheader(k, v)
        conn.endheaders()
        resp = conn.getresponse()
        body = resp.read()
        hdrs = {k.lower(): v for k, v in resp.getheaders()}
        return resp.status, hdrs, body
    finally:
        conn.close()


def test_t4_s01_manual_baseline_full_shifts_e2e(
    repo_root: Path,
    session_tmp_dir: Path,
    exported_pack_report: dict[str, Any],
    exported_pack_dir: Path,
    node_probe: dict[str, Any],
) -> None:
    """Scenario 1 (F1, F3, F5, F8, F10, F13): Manual baseline full shifts across seeds 11, 29, 47."""
    from robotization_bench import contracts, economics, engine, grading, scenarios, validation

    _check_frozen_benchmark_contracts_git_clean(repo_root)
    assert exported_pack_report["ok"] and exported_pack_report["all_9_v1_present"], (
        f"Exported 3D pack failed: {exported_pack_report}"
    )
    assert node_probe.get("ok"), f"node_probe failed: {node_probe.get('error')}"

    world = contracts.load_world()
    manual_dict = grading.manual_value()
    manual_plan = validation.parse_plan(manual_dict, world)
    assert manual_plan.robot is False and manual_plan.trays is False and manual_plan.route == "manual"
    assert len(manual_plan.workers) == 6

    dev_days = tuple(scenarios.generate(world, s) for s in (11, 29, 47))
    ev = grading.evaluate(world, manual_dict, dev_days)
    assert ev.valid is True

    assert node_probe["negativeChecks"]["robotAdapter"]["notPurchasedHidden"] is True, (
        "Robot adapter failed to hide robot when state == 'not_purchased'"
    )

    manual_dirs = [exported_pack_dir / f"v1-manual-seed{s}" for s in (11, 29, 47)]
    deep_mismatches = _verify_bundle_deep_counters(repo_root, session_tmp_dir, manual_dirs)

    shifts = node_probe["studioReplayAudit"]["shifts"]
    for seed, day in zip((11, 29, 47), dev_days, strict=True):
        run_id = f"v1-manual-seed{seed}"
        run_dir = exported_pack_dir / run_id
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        sim_raw = engine.simulate(world, manual_plan, day, trace=False)
        sim_econ = economics.calculate(world, manual_plan, sim_raw)

        assert manifest["plan"]["robot"] is False and manifest["plan"]["trays"] is False
        assert manifest["raw"]["good"] == sim_raw.good
        assert manifest["raw"]["escaped"] == sim_raw.escaped
        assert manifest["raw"]["scrap"] == sim_raw.scrap
        assert manifest["raw"]["auto_finished"] == 0
        assert manifest["economy"]["total"] == sim_econ.total

        sh = shifts[run_id]
        assert deep_mismatches[str(run_dir)] == [], (
            f"{run_id}: ReplayModel counter mismatch on {deep_mismatches[str(run_dir)]}"
        )
        assert sh["boundaryClampingOk"] is True
        if not sh.get("detailed"):
            assert sh["robotVisibleAtEnd"] is False, f"{run_id}: unpurchased robot remained visible"

    sh11 = shifts["v1-manual-seed11"]
    assert sh11["detailed"] is True
    tr = sh11["transit"]
    assert tr["mainConveyorHits"] > 0 and tr["mainConveyorIncreasingXCount"] > 0
    assert tr["spurHits"] > 0 and tr["qcPortalHits"] > 0

    obs_clips = set(sh11["observedWorkerClips"])
    for req_clip in ("Prepare", "Pick", "Pack", "Inspect", "CarryWalk", "Break"):
        assert req_clip in obs_clips, f"v1-manual-seed11 missing active worker clip {req_clip}: {sorted(obs_clips)}"
    assert ("PickUp" in obs_clips) or ("PlaceDown" in obs_clips)

    assert sh11["emptyHandPropLeakCount"] == 0
    assert sh11["activeBenchDuplicateCollisions"] == 0
    assert sh11["trayAlignment"]["untrayedHeightChecked"] > 0
    assert sh11["trayAlignment"]["untrayedHeightErrors"] == 0
    assert sh11["rework"]["robotAssignedAttempt1"] == 0
    if sh11["rework"]["reworkStartedInRaw"] > 0:
        assert sh11["rework"]["reworkBenchWorkerSamples"] > 0 and sh11["rework"]["reworkBenchCartonSamples"] > 0, sh11["rework"]
    if (sh11.get("scrap") or {}).get("scrapInRaw", 0) > 0:
        assert sh11["scrap"]["scrapCarryOrTransitObserved"] > 0 and sh11["scrap"]["scrapBenchOrBinVisibleAtEnd"] > 0, sh11["scrap"]

    brk = sh11["breaks"]
    assert brk["count"] == len(manual_plan.workers), (
        f"Expected all {len(manual_plan.workers)} manual workers to take mandatory break, got {brk['count']}"
    )
    assert brk["maxBreakStepJumpM"] <= 2.50, (
        f"Post-break teleport detected in v1-manual-seed11: {brk['maxBreakJumpInfo']}"
    )
    assert [c for c in brk["breakEndChecks"] if c["strandedInBreakArea"]] == []


def test_t4_s02_automated_candidate_full_shifts_e2e(
    repo_root: Path,
    session_tmp_dir: Path,
    exported_pack_report: dict[str, Any],
    exported_pack_dir: Path,
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """Scenario 2 (F1, F4, F5, F6, F7, F8, F9, F13): Automated candidate full shifts across seeds 11, 29, 47."""
    from robotization_bench import contracts, economics, engine, grading, scenarios, validation

    assert exported_pack_report["ok"] and exported_pack_report["all_9_v1_present"]
    assert blender_probe.get("ok"), f"blender_probe failed: {blender_probe.get('error')}"
    assert node_probe.get("ok"), f"node_probe failed: {node_probe.get('error')}"

    world = contracts.load_world()
    cand_text = (repo_root / "data" / "plans" / "candidate.json").read_text(encoding="utf-8")
    cand_plan = validation.decode_plan(cand_text, world)
    assert cand_plan.robot is True and cand_plan.trays is True and cand_plan.route == "bypass"

    dev_days = tuple(scenarios.generate(world, s) for s in (11, 29, 47))
    ev = grading.evaluate(world, json.loads(cand_text), dev_days)
    assert ev.valid is True and ev.metrics["auto_finished"] > 0

    assert not node_probe["environmentAudit"]["chamferInEnv"]
    chamfer = node_probe["layoutAudit"]["chamfer"]
    assert chamfer["exists"] and chamfer["parent"] == "VIS_ROBOT_PACK_TABLE"
    assert abs(chamfer["aabb"]["max"][1] - 0.860) <= 0.0025

    cand_dirs = [exported_pack_dir / f"v1-candidate-seed{s}" for s in (11, 29, 47)]
    deep_mismatches = _verify_bundle_deep_counters(repo_root, session_tmp_dir, cand_dirs)

    shifts = node_probe["studioReplayAudit"]["shifts"]
    assist_samples: list[dict[str, Any]] = []
    robot_clips: set[str] = set()
    andon_states: set[str] = set()

    for seed, day in zip((11, 29, 47), dev_days, strict=True):
        run_id = f"v1-candidate-seed{seed}"
        run_dir = exported_pack_dir / run_id
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        sim_raw = engine.simulate(world, cand_plan, day, trace=False)
        sim_econ = economics.calculate(world, cand_plan, sim_raw)

        assert manifest["raw"]["auto_finished"] == sim_raw.auto_finished > 0
        assert manifest["raw"]["trays_used"] == sim_raw.trays_used > 0
        assert manifest["economy"]["total"] == sim_econ.total

        sh = shifts[run_id]
        assert deep_mismatches[str(run_dir)] == []
        assert sh["boundaryClampingOk"] is True
        if sh.get("detailed"):
            assert sh["transit"]["mainConveyorIncreasingXCount"] > 0
            assert sh["activeBenchDuplicateCollisions"] == 0
            assert sh["emptyHandPropLeakCount"] == 0
            assert sh["trayAlignment"]["trayHeightChecked"] > 0
            assert sh["trayAlignment"]["trayHeightErrors"] == 0
            assert sh["rework"]["robotAssignedAttempt1"] == 0
            assert sh["breaks"]["maxBreakStepJumpM"] <= 2.50
            assist_samples.extend(sh.get("assistSamples") or [])
            robot_clips.update(sh.get("observedRobotClips") or [])
            andon_states.update(sh.get("observedAndonStates") or [])

    if isinstance(shifts.get("test-jam-h32"), dict) and shifts["test-jam-h32"].get("detailed"):
        assist_samples.extend(shifts["test-jam-h32"].get("assistSamples") or [])
        robot_clips.update(shifts["test-jam-h32"].get("observedRobotClips") or [])
        andon_states.update(shifts["test-jam-h32"].get("observedAndonStates") or [])

    assert "RobotPack" in robot_clips, f"RobotPack never observed across candidate shifts: {sorted(robot_clips)}"
    assert len(assist_samples) >= 1, "Zero robot jam/helper assist samples observed across candidate shifts"
    for smp in assist_samples:
        assert smp["cosSim"] >= 0.98 and smp["angleErrDeg"] <= 12.0, f"Helper yaw away from robot order: {smp}"
        assert smp["helperClip"] == "Assist" and (smp["robotMixerTime"] or 0.0) > 0.0
    assert "ANDON_GREEN" in andon_states and len(andon_states) >= 2, (
        f"Expected Andon transitions on candidate robot cell, got {sorted(andon_states)}"
    )


def test_t4_s03_reference_optimal_policy_grading_and_3d_replay_e2e(
    repo_root: Path,
    session_tmp_dir: Path,
    exported_pack_report: dict[str, Any],
    exported_pack_dir: Path,
    node_probe: dict[str, Any],
) -> None:
    """Scenario 3 (F1, F6, F7, F8, F9, F13): Reference optimal policy passes all feasibility & win gates and replays cleanly across seeds 11, 29, 47."""
    from robotization_bench import contracts, grading, scenarios

    assert exported_pack_report["ok"] and exported_pack_report["all_9_v1_present"]
    assert node_probe.get("ok"), f"node_probe failed: {node_probe.get('error')}"

    world = contracts.load_world()
    dev_days = tuple(scenarios.generate(world, s) for s in (11, 29, 47))
    ref_dict = _solve_reference_policy(world, dev_days)
    ev = grading.evaluate(world, ref_dict, dev_days)

    assert ev.valid is True, f"Reference policy invalid: {ev.reasons}"
    assert ev.feasible is True, f"Reference policy failed feasibility gates: {ev.reasons}"
    assert ev.win is True, f"Reference policy failed win gates: {ev.reasons}"
    assert ev.reasons == ()
    assert ev.metrics["total_cost"] < ev.metrics["base_cost"]
    assert ev.metrics["labor_ticks"] < ev.metrics["base_labor_ticks"]
    assert Fraction(ev.reward_num, ev.reward_den) > Fraction(1, 5)

    ref_dirs = [exported_pack_dir / f"v1-reference-seed{s}" for s in (11, 29, 47)]
    deep_mismatches = _verify_bundle_deep_counters(repo_root, session_tmp_dir, ref_dirs)

    index_runs = {r["id"]: r for r in exported_pack_report["index"]["runs"]}
    shifts = node_probe["studioReplayAudit"]["shifts"]
    for seed in (11, 29, 47):
        run_id = f"v1-reference-seed{seed}"
        run_dir = exported_pack_dir / run_id
        pack_entry = index_runs[run_id]
        assert pack_entry["evaluation"]["feasible"] is True and pack_entry["evaluation"]["win"] is True

        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["raw"]["unfinished"] < 20 and manifest["raw"]["good"] > 140

        sh = shifts[run_id]
        assert deep_mismatches[str(run_dir)] == [] and sh["boundaryClampingOk"] is True

    sh11 = shifts["v1-reference-seed11"]
    assert sh11["detailed"] is True
    assert sh11["activeBenchDuplicateCollisions"] == 0
    assert sh11["emptyHandPropLeakCount"] == 0
    assert sh11["trayAlignment"]["trayHeightChecked"] > 0
    assert sh11["trayAlignment"]["trayHeightErrors"] == 0
    assert sh11["rework"]["robotAssignedAttempt1"] == 0
    assert sh11["breaks"]["maxBreakStepJumpM"] <= 2.50
    assert sh11["maxScrubDeterminismErrM"] == 0


def test_t4_s04_custom_high_stress_jam_break_rework_scrap_pipeline_e2e(
    repo_root: Path,
    session_tmp_dir: Path,
    tmp_path: Path,
    run_custom_replay_probe: Any,
) -> None:
    """Scenario 4 (F1, F5, F6, F7, F8, F9, F13): Custom high-stress shift triggering jam+assist, mandatory break, rework (0->1), scrap, escaped, and oversize robot packing."""
    from robotization_bench import contracts, economics, engine, reporting, scenarios, validation

    world = contracts.load_world()
    stress_plan_dict = {
        "schema_version": 1,
        "robot": True,
        "trays": True,
        "route": "all",
        "workers": [[1], [2], [3], [4], [2, 3, 4]],
    }
    stress_plan = validation.parse_plan(stress_plan_dict, world)
    stress_day = scenarios.generate(world, 137)

    raw = engine.simulate(world, stress_plan, stress_day, trace=True)
    econ = economics.calculate(world, stress_plan, raw)

    event_kinds = {e.kind for e in raw.events}
    for critical_kind in ("arrival", "jam", "assist", "break", "good", "escaped", "scrap"):
        assert critical_kind in event_kinds, (
            f"Stress shift seed=137 missing critical event kind {critical_kind!r}: {sorted(event_kinds)}"
        )
    assert raw.rework_started >= 1 and raw.scrap >= 1 and raw.escaped >= 1 and raw.good >= 100
    assert raw.auto_finished >= 100 and raw.trays_used >= 100

    out_bundle = tmp_path / "stress-seed137"
    reporting.export_shift_bundle(world, stress_plan, stress_day, raw, econ, out_bundle)
    audit = reporting.validate_shift_bundle(out_bundle)
    assert audit["summary"]["good"] == raw.good and audit["summary"]["scrap"] == raw.scrap

    deep_mism = _verify_bundle_deep_counters(repo_root, session_tmp_dir, [out_bundle])[str(out_bundle)]
    assert deep_mism == [], f"Stress shift counter mismatch: {deep_mism}"

    probe = run_custom_replay_probe(run_dir=out_bundle)
    assert probe.get("ok"), f"Studio custom replay probe failed on stress-seed137: {probe}"
    sh = probe["shiftReport"]
    assert sh["boundaryClampingOk"] is True
    assert sh["activeBenchDuplicateCollisions"] == 0
    assert sh["emptyHandPropLeakCount"] == 0
    assert sh["trayAlignment"]["trayHeightChecked"] > 0 and sh["trayAlignment"]["trayHeightErrors"] == 0
    assert sh["rework"]["reworkStartedInRaw"] == raw.rework_started >= 1
    assert sh["rework"]["robotAssignedAttempt1"] == 0
    assert sh["rework"]["reworkBenchWorkerSamples"] >= 1 and sh["rework"]["reworkBenchCartonSamples"] >= 1, sh["rework"]
    assert sh["scrap"]["scrapInRaw"] == raw.scrap >= 1
    assert sh["scrap"]["scrapCarryOrTransitObserved"] >= 1 and sh["scrap"]["scrapBenchOrBinVisibleAtEnd"] >= 1, sh["scrap"]
    assert sh["breaks"]["count"] == 5 and sh["breaks"]["maxBreakStepJumpM"] <= 2.50
    assert [c for c in sh["breaks"]["breakEndChecks"] if c["strandedInBreakArea"]] == []

    assist_active = [smp for smp in sh["assistSamples"] if smp.get("helperClip") == "Assist"]
    assert len(assist_active) >= 1, f"Expected live helper Assist sample during stress shift jam, got {sh['assistSamples']}"
    for smp in assist_active:
        assert smp["cosSim"] >= 0.9659 and (smp["robotMixerTime"] or 0.0) > 0.0

    r_clips = set(sh["observedRobotClips"])
    assert "RobotPack" in r_clips or "RobotPack_Oversize" in r_clips, (
        f"Expected RobotPack / RobotPack_Oversize in route='all' stress shift, got {sorted(r_clips)}"
    )


def test_t4_s05_max_8_worker_staffing_and_cross_hall_routing_e2e(
    repo_root: Path,
    session_tmp_dir: Path,
    tmp_path: Path,
    node_probe: dict[str, Any],
    run_custom_replay_probe: Any,
) -> None:
    """Scenario 5 (F2, F3, F8, F10, F13): Maximum 8-worker staffing with heavy Stage-3 parallel benches and full 36x18m A* cross-hall routing."""
    from robotization_bench import contracts, economics, engine, reporting, scenarios, validation

    assert node_probe.get("ok"), f"node_probe failed: {node_probe.get('error')}"

    world = contracts.load_world()
    max8_plan_dict = {
        "schema_version": 1,
        "robot": True,
        "trays": True,
        "route": "all",
        "workers": [[1], [2], [3], [3], [3], [3], [4], [2, 3, 4]],
    }
    max8_plan = validation.parse_plan(max8_plan_dict, world)
    assert len(max8_plan.workers) == 8

    day29 = scenarios.generate(world, 29)
    raw = engine.simulate(world, max8_plan, day29, trace=True)
    econ = economics.calculate(world, max8_plan, raw)

    break_events = [e for e in raw.events if e.kind == "break"]
    walk_events = [e for e in raw.events if e.kind == "walk"]
    assert len(break_events) == 8, f"Expected all 8 workers to take mandatory break, got {len(break_events)}"
    assert len(walk_events) >= 20, f"Expected cross-stage walks from flexible 8th worker, got {len(walk_events)}"
    assert raw.unfinished == 0 and raw.good >= 165

    out_bundle = tmp_path / "max8w-seed29"
    reporting.export_shift_bundle(world, max8_plan, day29, raw, econ, out_bundle)
    reporting.validate_shift_bundle(out_bundle)

    deep_mism = _verify_bundle_deep_counters(repo_root, session_tmp_dir, [out_bundle])[str(out_bundle)]
    assert deep_mism == []

    probe = run_custom_replay_probe(run_dir=out_bundle)
    assert probe.get("ok"), f"Studio custom replay probe failed on 8-worker shift: {probe}"
    assert probe["benchOverlaps"] == 0, f"8-worker parallel benches overlapped: {probe}"
    assert probe["parallelBenchCount"] >= 3 and (probe["maxSlots"].get("3") or probe["maxSlots"].get(3) or 0) >= 4

    sh = probe["shiftReport"]
    assert sh["activeBenchDuplicateCollisions"] == 0
    assert sh["emptyHandPropLeakCount"] == 0
    assert sh["breaks"]["count"] == 8 and sh["breaks"]["maxBreakStepJumpM"] <= 2.50
    assert [c for c in sh["breaks"]["breakEndChecks"] if c["strandedInBreakArea"]] == []

    spatial = node_probe["spatialAudit"]
    for l_key in ("stage3_5slots", "stage3_6slots", "stages124_3slots"):
        assert spatial["layouts"][l_key]["ok"]
        assert spatial["layouts"][l_key]["overlaps"] == []
        assert spatial["layouts"][l_key]["pathHits"] == 0
    for r_key in ("dock01_to_dock02", "sw_to_ne_corners", "boundary_176_86"):
        assert spatial["astarRoutes"][r_key]["ok"] and spatial["astarRoutes"][r_key]["inBounds"]


def test_t4_s06_cold_start_production_studio_bundle_and_15_glb_integrity_e2e(
    repo_root: Path,
    studio_dir: Path,
    session_tmp_dir: Path,
    v02_configs: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """Scenario 6 (F2, F4, F5, F6, F9, F11): Cold-start production Studio bundle (studio/dist/, studio/public/scene/, asset-hashes.json), workstation grounding, & 15-GLB integrity."""
    assert node_probe.get("ok"), f"node_probe failed: {node_probe.get('error')}"
    for key in (
        "asset_stats_v02",
        "asset_manifest",
        "worker_manifest",
        "robot_manifest",
        "studio_asset_hashes",
    ):
        assert v02_configs["files"][key]["ok"], f"{key} invalid: {v02_configs['files'][key]['error']}"

    gltf_val = node_probe["gltfValidation"]
    stats_by_file = {e["file"]: e for e in v02_configs["asset_stats_v02"]["files"]}
    studio_hashes = v02_configs["studio_asset_hashes"]

    for rel in ALL_15_GLBS:
        info = gltf_val[rel]
        assert info["exists"] and info["numErrors"] == 0, f"GLB {rel} failed gltf-validator: {info}"
        assert stats_by_file[rel]["sha256"] == info["sha256"] and stats_by_file[rel]["bytes"] == info["bytes"]
        h_rec = _lookup_studio_hash_record(studio_hashes, rel)
        assert h_rec is not None and h_rec["sha256"] == info["sha256"] and h_rec["bytes"] == info["bytes"], (
            f"studio/asset-hashes.json mismatch for {rel}: {h_rec}"
        )

    assert 100_000 < gltf_val["warehouse_environment.glb"]["bytes"] < 12 * 1024 * 1024
    assert node_probe["layoutAudit"]["nodeCount"] >= 61
    assert len(node_probe["supportAudit"]["templates"]) == 14
    assert node_probe["environmentAudit"]["rollerCount"] == 200
    required_core_layers = {
        "ENV_FLOOR_AND_GRID",
        "ENV_WALLS_AND_DOCKS",
        "ENV_WORKSTATIONS_DETAIL",
        "ENV_ROBOT_CELL",
        "ENV_BREAK_AREA",
    }
    assert required_core_layers.issubset(node_probe["environmentAudit"]["presentLayers"])
    assert node_probe["characterAudit"]["worker"]["boneCount"] == 35 == v02_configs["worker_manifest"]["bones"]
    assert node_probe["characterAudit"]["robot"]["boneCount"] == 41 == v02_configs["robot_manifest"]["bones"]

    gm = _audit_workstation_grounding_and_map_idempotency(repo_root, session_tmp_dir, node_probe=node_probe)
    assert gm.get("ok"), f"Three.js workstation grounding & map idempotency probe failed: {gm}"
    env_audit = node_probe["environmentAudit"]
    assert env_audit["benchReworkInEnv"] is True and env_audit["benchScrapInEnv"] is True, env_audit
    assert env_audit["floorArrowsAudit"]["offWalkwayArrows"] == [], env_audit["floorArrowsAudit"]
    studio_arrows = (
        node_probe["studioReplayAudit"].get("floorArrowsAudit")
        or env_audit["studioPatchedFloorArrowsAudit"]
    )
    assert studio_arrows["offWalkwayArrows"] == [] and studio_arrows["duplicateWalkwayPairs"] == [], studio_arrows
    assert len(studio_arrows["walkwayArrows"]) >= 3 and studio_arrows["hasWalkwayGreen5S"] is True, studio_arrows
    presets = node_probe["studioReplayAudit"]["cameraPresets"]
    assert presets["blueprint"]["supported"] is True and presets["rework"]["supported"] is True, presets
    assert node_probe["environmentAudit"]["overheadBox"] is None, (
        f"Physical overhead geometry AABB still present in warehouse_environment.glb: {node_probe['environmentAudit']['overheadBox']}"
    )
    assert gm["glbOverheadMeshes"] == [], (
        f"Physical overhead beam/truss/cable-tray/lamp meshes remain in exported GLBs: {gm['glbOverheadMeshes'][:12]}"
    )
    assert gm["studioVisibleOverheadMeshes"] == [], (
        f"Visible overhead beam/truss/cable-tray/lamp meshes remain in Studio scene: {gm['studioVisibleOverheadMeshes'][:12]}"
    )
    assert gm["studioLightConstructs"] >= 2, (
        f"Studio Three.js lighting sources missing in studio/src/scene.js: count={gm['studioLightConstructs']}"
    )
    for group_label, group_dict in (
        ("standalone warehouse_environment.glb", gm["standaloneWorkstations"]),
        ("combined Studio (env + layout)", gm["studioStationary"]),
        ("Studio cloned benches", gm["studioClonedBenches"]),
    ):
        for ws_name, ws_box in sorted(group_dict.items()):
            assert ws_box["exists"] and ws_box["minY"] is not None, (
                f"Missing workstation {ws_name} in {group_label}: {ws_box}"
            )
            assert -0.005 <= ws_box["minY"] <= 0.005, (
                f"Levitating or sunken workstation {ws_name} in {group_label}: minY={ws_box['minY']}m"
            )

    bundle = node_probe["studioBundleAudit"]
    pub_scene = bundle["publicScene"]
    assert pub_scene["exists"] and pub_scene["missingAssets"] == [] and pub_scene["parityMismatches"] == [], (
        f"studio/public/scene/ missing or stale assets: {pub_scene}"
    )

    dist = bundle["dist"]
    assert dist["exists"] and dist["indexHtmlExists"], f"studio/dist/index.html missing: {dist}"
    assert len(dist["jsFiles"]) >= 1 and len(dist["cssFiles"]) >= 1, f"studio/dist/assets incomplete: {dist}"
    dist_scene = dist["scene"]
    assert (
        dist_scene["exists"]
        and dist_scene["missingAssets"] == []
        and dist_scene["parityMismatches"] == []
    ), f"studio/dist/scene/ missing or stale assets: {dist_scene}"

    index_html = (studio_dir / "dist" / "index.html").read_text(encoding="utf-8")
    asset_refs = re.findall(r'(?:src|href)=["\'](\.?/assets/[^"\']+)["\']', index_html)
    assert len(asset_refs) >= 2, f"studio/dist/index.html missing bundled JS/CSS refs: {index_html[:400]}"
    for ref in asset_refs:
        clean_rel = ref.lstrip("./")
        target = studio_dir / "dist" / clean_rel
        assert target.exists() and target.stat().st_size > 0, (
            f"studio/dist/index.html references missing/empty bundle asset {ref} -> {target}"
        )

    staged_idem = gm["mapIdempotency"]["stagedScene"]
    assert staged_idem is not None and staged_idem.get("ok"), (
        f"Staged studio scene failed map-*.js idempotency check: {staged_idem}"
    )


def test_t4_s07_live_http_3d_bridge_catalog_and_range_streaming_e2e(
    repo_root: Path,
    session_tmp_dir: Path,
    exported_pack_report: dict[str, Any],
    exported_pack_dir: Path,
    ephemeral_serve_3d: Any,
    run_custom_replay_probe: Any,
) -> None:
    """Scenario 7 (F8, F11, F13): Live read-only serve_3d.py HTTP bridge + catalog + 206 Range streaming + remote Studio replay + 403/404/405 lockdown."""
    assert exported_pack_report["ok"] and exported_pack_report["all_9_v1_present"]

    with ephemeral_serve_3d(exported_pack_dir) as srv:
        assert srv["ready"], f"serve_3d.py failed to start on ephemeral port: {srv}"
        host, port = srv["host"], srv["port"]

        with urllib.request.urlopen(srv["index_url"], timeout=5.0) as resp:
            assert resp.status == 200
            assert resp.headers.get("Access-Control-Allow-Origin") == "*"
            assert resp.headers.get("X-Content-Type-Options") == "nosniff"
            assert resp.headers.get("Cache-Control") == "no-store"
            catalog = json.loads(resp.read().decode("utf-8"))

        run_ids = [r["id"] for r in catalog.get("runs", [])]
        assert len(run_ids) >= 9 and set(REQUIRED_9_V1_RUN_IDS).issubset(run_ids)

        head_status, head_hdrs, head_body = _raw_http_request(host, port, "HEAD", "/index.json")
        assert head_status == 200 and head_body == b"" and int(head_hdrs["content-length"]) > 100

        opt_status, opt_hdrs, _ = _raw_http_request(host, port, "OPTIONS", "/index.json")
        assert opt_status == 204 and "GET" in opt_hdrs.get("allow", "")

        for rel_target in ("v1-candidate-seed11/events.jsonl", "v1-candidate-seed11/manifest.json"):
            disk_bytes = (exported_pack_dir / rel_target).read_bytes()
            st_p, hdr_p, body_p = _raw_http_request(
                host, port, "GET", f"/{rel_target}", {"Range": "bytes=0-63"}
            )
            assert st_p == 206, f"Expected 206 Partial Content on {rel_target}, got {st_p}"
            assert hdr_p.get("content-range") == f"bytes 0-63/{len(disk_bytes)}"
            assert body_p == disk_bytes[:64]

            st_suf, _, body_suf = _raw_http_request(
                host, port, "GET", f"/{rel_target}", {"Range": "bytes=-32"}
            )
            assert st_suf == 206 and body_suf == disk_bytes[-32:]

        st_416, hdr_416, _ = _raw_http_request(
            host, port, "GET", "/index.json", {"Range": "bytes=99999999-100000000"}
        )
        assert st_416 == 416 and hdr_416.get("content-range", "").startswith("bytes */")

        http_probe = run_custom_replay_probe(http_url=srv["index_url"])
        assert http_probe.get("ok"), f"Studio DataMod.openRemote HTTP replay probe failed: {http_probe}"
        assert set(REQUIRED_9_V1_RUN_IDS).issubset(http_probe["loadedRunIds"])
        sample = http_probe["sampleInspection"]
        assert sample is not None and sample["boundaryClampingOk"] is True
        sample_dir = exported_pack_dir / http_probe["loadedRunIds"][0]
        assert _verify_bundle_deep_counters(repo_root, session_tmp_dir, [sample_dir])[str(sample_dir)] == []
        assert sample["activeBenchDuplicateCollisions"] == 0
        assert sample["breaks"]["maxBreakStepJumpM"] <= 2.50

        for forbidden_path in (
            "/",
            "/v1-candidate-seed11/",
            "/../pyproject.toml",
            "/%2e%2e/pyproject.toml",
            "//evil.example/index.json",
        ):
            code, _, _ = _raw_http_request(host, port, "GET", forbidden_path)
            assert code == 403, f"Expected 403 Forbidden on {forbidden_path!r}, got {code}"

        code_404, _, _ = _raw_http_request(host, port, "GET", "/no_such_shift/manifest.json")
        assert code_404 == 404

        for mut_method in ("POST", "PUT", "DELETE"):
            code_405, hdr_405, _ = _raw_http_request(host, port, mut_method, "/index.json")
            assert code_405 == 405 and "GET" in hdr_405.get("allow", "")


def test_t4_s08_jury_presentation_readiness_and_multizone_visual_audit_e2e(
    repo_root: Path,
    session_tmp_dir: Path,
    v02_configs: dict[str, Any],
    chain_report: dict[str, Any],
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """Scenario 8 (F1, F2, F4, F5, F6, F7, F12): End-to-end jury presentation readiness across workshop_chain.json, 36x18x3.6m unobstructed ceiling & collision-free hall, 30-FPS rigs, and multi-zone PNG renders."""
    assert chain_report["ok"], f"workshop_chain.json not presentation-ready: {chain_report['errors']}"
    assert blender_probe.get("ok"), f"blender_probe failed: {blender_probe.get('error')}"
    assert node_probe.get("ok"), f"node_probe failed: {node_probe.get('error')}"

    gm = _audit_workstation_grounding_and_map_idempotency(repo_root, session_tmp_dir)
    assert gm.get("ok"), f"Three.js grounding/ceiling probe failed: {gm}"
    blend_ceiling = _audit_blend_ceiling_and_lights(repo_root, session_tmp_dir)
    assert blend_ceiling.get("ok"), f"Blender ceiling/lights probe failed: {blend_ceiling}"

    for cfg_key in ("environment_config", "config_environment"):
        st3 = v02_configs["stage3_pack_station"][cfg_key]
        assert st3 is not None and is_stage3_pack_station(st3)

    assert blender_probe["overhead"]["mesh_count"] == 0 and blend_ceiling["overhead_meshes"] == [], (
        f"Physical overhead ceiling beam/truss/cable-tray/lamp meshes still block view in .blend: {blend_ceiling['overhead_meshes'][:12]}"
    )
    assert len(blend_ceiling["active_lights"]) >= 1, (
        f"Blender workshop scene lost active light sources: {blend_ceiling}"
    )
    assert node_probe["environmentAudit"]["overheadBox"] is None and gm["glbOverheadMeshes"] == [], (
        f"Physical overhead ceiling beam/truss/cable-tray/lamp meshes remain in GLBs: {gm['glbOverheadMeshes'][:12]}"
    )
    assert gm["studioVisibleOverheadMeshes"] == [] and gm["studioLightConstructs"] >= 2, (
        f"Studio overhead meshes visible or lights missing: {gm}"
    )

    bvh = blender_probe["bvh"]
    real_collisions = [
        col
        for col in bvh["unintended_collisions"]
        if frozenset((col.get("a"), col.get("b")))
        != frozenset(("ROBOT_PACK_TABLE", "ROBOT_TABLE_REINFORCEMENT"))
    ]
    assert real_collisions == [], f"BVH collisions remain: {real_collisions}"
    assert bvh["walkway_hits"] == [], f"5S walkway obstructed: {bvh['walkway_hits']}"
    assert bvh["helper_hits"] == [], f"Robot helper space obstructed: {bvh['helper_hits']}"
    assert bvh["mesh_integrity"]["nan_inf_vertices"] == 0 and bvh["mesh_integrity"]["zero_area_triangles"] == 0

    cam = blender_probe["camera"]
    assert cam["exists"]
    assert cam["docks"]["DOCK_01"]["in_frustum"] and not cam["docks"]["DOCK_01"]["occluded"]
    assert cam["docks"]["DOCK_02"]["in_frustum"] and not cam["docks"]["DOCK_02"]["occluded"]

    char_aud = node_probe["characterAudit"]
    for actor_key, exp_bones in (("worker", 35), ("robot", 41)):
        act = char_aud[actor_key]
        assert act["numErrors"] == 0 and act["boneCount"] == exp_bones
        assert act["demoSupportNodes"] == [] and act["skinning"]["unweightedVerts"] == 0
        assert act["cadence"]["offGridSamplers"] == []
    assert char_aud["proportionParity"]["comparedCoreJoints"] >= 20
    assert char_aud["proportionParity"]["maxCoreJointDiffM"] <= 0.005

    for g_key, g_val in char_aud["workstationGrasp"].items():
        assert g_val["minDistL"] <= 0.025 and g_val["minDistR"] <= 0.025, f"Grasp error on {g_key}: {g_val}"
        assert g_val["minOverBenchSocketY"] >= 0.858 and g_val["minOverBenchPropY"] >= 0.858

    assert blender_probe["artifacts"]["VIS_ROBOT_ASSIST"]["cos_sim_to_robot_order"] >= 0.98
    assert node_probe["layoutAudit"]["staticAssistInfo"]["nodeCosSim"] >= 0.98

    png_files = node_probe["pngAudit"]["files"]
    ov_png = png_files.get("environment_overview.png")
    assert ov_png is not None and ov_png.get("valid"), f"environment_overview.png invalid: {ov_png}"
    ov_errs = validate_render_quality(_png_camel_to_snake(ov_png), is_overview=True)
    assert ov_errs == [], f"environment_overview.png failed overview visual audit: {ov_errs}"

    for det_name in ("detail_conveyor.png", "detail_packing.png", "detail_storage.png"):
        det_info = png_files.get(det_name)
        assert det_info is not None and det_info.get("valid"), f"{det_name} missing/invalid: {det_info}"
        det_errs = validate_render_quality(_png_camel_to_snake(det_info), min_width=1200, min_height=800)
        assert det_errs == [], f"{det_name} failed detail render audit: {det_errs}"

    pres_pngs = {
        rel: info
        for rel, info in png_files.items()
        if rel.startswith("renders_presentation/") and info.get("valid")
    }
    assert len(pres_pngs) >= 8, (
        f"Jury presentation suite requires >=8 valid multi-zone PNGs in renders_presentation/, got {len(pres_pngs)}"
    )
    for rel, info in sorted(pres_pngs.items()):
        errs = validate_render_quality(_png_camel_to_snake(info), min_width=1200, min_height=720)
        assert errs == [], f"{rel} failed presentation quality audit: {errs}"

    candidate_paths = [
        rel
        for rel, info in png_files.items()
        if info.get("valid")
        and (
            rel.startswith("renders_presentation/")
            or rel.startswith("artifacts/player-check/")
            or rel.startswith("detail_")
        )
    ]
    missing_zones = [
        z_key
        for z_key, pat in STAGE_ZONE_PATTERNS.items()
        if not any(pat.search(rel) for rel in candidate_paths)
    ]
    assert missing_zones == [], f"Missing stage/zone render coverage: {missing_zones}"
    assert any(
        rel.startswith("artifacts/player-check/") or re.search(r"(studio|player|webgl)", rel, re.IGNORECASE)
        for rel in candidate_paths
    ), "Missing headless Chrome WebGL2 Studio presentation captures"
