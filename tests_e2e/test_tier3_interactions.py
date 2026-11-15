"""Tier 3 Cross-Feature Combinatorial Interaction Tests for 4 Horses Environment v02 (`tests_e2e/`).

Pairwise / Multi-Feature Coverage Matrix across all 13 Core Requirement Features (`F1..F13`):
Every single feature `F1..F13` participates in `>= 2` distinct cross-feature interaction tests:

| Test # | Test Function                                                             | Features Exercised         |
|--------|---------------------------------------------------------------------------|----------------------------|
| T3.01  | `test_t3_01_f1_x_f2_chain_zones_docks_camera_and_stage3_label`            | F1 × F2                    |
| T3.02  | `test_t3_02_f1_x_f3_chain_edges_backed_by_physical_spurs_and_lanes`       | F1 × F3                    |
| T3.03  | `test_t3_03_f1_x_f4_chain_equipment_clean_glbs_and_086m_supports`         | F1 × F4                    |
| T3.04  | `test_t3_04_f1_x_f5_x_f6_chain_roles_and_30fps_worker_robot_clips`        | F1 × F5 × F6               |
| T3.05  | `test_t3_05_f2_x_f3_hall_envelope_overhead_cad_grid_plc_and_walkways`     | F2 × F3                    |
| T3.06  | `test_t3_06_f2_x_f9_native_36x18x36_glb_and_studio_map_idempotency`       | F2 × F4 × F9               |
| T3.07  | `test_t3_07_f3_x_f8_physical_spurs_conveyors_and_subtick_parcel_transit`  | F3 × F8                    |
| T3.08  | `test_t3_08_f4_x_f7_robot_chamfer_bench_tops_and_grasp_tray_clearance`    | F4 × F7                    |
| T3.09  | `test_t3_09_f5_x_f8_worker_30fps_handoff_clips_and_post_break_return`     | F5 × F8                    |
| T3.10  | `test_t3_10_f5_x_f9_worker_operation_props_and_active_bench_sync`         | F5 × F9                    |
| T3.11  | `test_t3_11_f6_x_f7_x_f8_robot_jam_assist_yaw_andon_and_live_replay`      | F6 × F7 × F8               |
| T3.12  | `test_t3_12_f7_x_f9_tray_plus_12mm_vs_bare_support_in_templates_and_replay`| F7 × F9                   |
| T3.13  | `test_t3_13_f2_x_f3_x_f10_eight_worker_parallel_benches_and_full_hall_astar`| F2 × F3 × F10            |
| T3.14  | `test_t3_14_f4_x_f11_fifteen_validated_glbs_manifests_and_studio_scene_parity`| F4 × F11               |
| T3.15  | `test_t3_15_f5_x_f6_x_f11_x_f12_character_manifests_npm_test_and_preview_renders`| F5 × F6 × F11 × F12 |
| T3.16  | `test_t3_16_f1_x_f2_x_f12_centered_camera_chain_zones_and_presentation_pngs`| F1 × F2 × F12            |
| T3.17  | `test_t3_17_f8_x_f10_x_f13_python_core_counters_studio_replay_and_queue_stacks`| F8 × F10 × F13        |
| T3.18  | `test_t3_18_f10_x_f11_x_f13_export_3d_pack_frozen_core_and_studio_readiness`| F10 × F11 × F13          |

Per-Feature Participation Counts (`>= 2` required for every `F1..F13`):
- F1: 5 tests (T3.01, T3.02, T3.03, T3.04, T3.16)
- F2: 5 tests (T3.01, T3.05, T3.06, T3.13, T3.16)
- F3: 4 tests (T3.02, T3.05, T3.07, T3.13)
- F4: 4 tests (T3.03, T3.06, T3.08, T3.14)
- F5: 4 tests (T3.04, T3.09, T3.10, T3.15)
- F6: 3 tests (T3.04, T3.11, T3.15)
- F7: 3 tests (T3.08, T3.11, T3.12)
- F8: 4 tests (T3.07, T3.09, T3.11, T3.17)
- F9: 3 tests (T3.06, T3.10, T3.12)
- F10: 3 tests (T3.13, T3.17, T3.18)
- F11: 3 tests (T3.14, T3.15, T3.18)
- F12: 2 tests (T3.15, T3.16)
- F13: 2 tests (T3.17, T3.18)
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
from typing import Any

from tests_e2e.conftest import REQUIRED_9_V1_RUN_IDS, build_e2e_env, is_stage3_pack_station
from tests_e2e.helpers import normalize_zone_bounds, validate_render_quality

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

EXPECTED_WORKER_17_CLIPS = frozenset(
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

EXPECTED_ROBOT_14_CLIPS = frozenset(
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
    """Convert node_probe pngAudit camelCase entry to snake_case for validate_render_quality."""
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
    """Resolve a GLB entry inside studio/asset-hashes.json across supported schema layouts."""
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


def _min_clip_motion_threshold(clip_name: str, actor_kind: str) -> float:
    """Return authoritative PROJECT.md §3 skeletal motion threshold (maxBodyDeltaM in meters)."""
    if clip_name in ("Idle", "CarryIdle"):
        return 0.002
    if clip_name in ("Walk", "CarryWalk"):
        return 0.40
    if clip_name in ("PickUp", "PlaceDown"):
        return 0.30
    if clip_name == "Reach":
        return 0.20
    if actor_kind == "worker":
        if clip_name in ("Prepare", "Prepare_Oversize", "Pack", "Pack_Oversize", "Assist"):
            return 0.20
        if clip_name in ("Pick", "Pick_Oversize"):
            return 0.25
        if clip_name in ("Inspect", "Inspect_Oversize"):
            return 0.14
        if clip_name == "Break":
            return 0.15
    if actor_kind == "robot":
        if clip_name in ("RobotPack", "RobotPack_Oversize"):
            return 0.20
        if clip_name in ("Service", "Service_Oversize"):
            return 0.10
        if clip_name in ("Jammed", "Jammed_Oversize"):
            return 0.02
        if clip_name == "Offline":
            return 0.01
    return 0.01


_GROUNDING_MAP_CACHE: dict[str, dict[str, Any]] = {}

_GROUNDING_AND_MAP_MJS = r"""
import fs from 'node:fs/promises';
import fsSync from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const [repoRoot, outPath] = process.argv.slice(2);
const toUrl = (rel) => pathToFileURL(path.join(repoRoot, rel)).href;

const THREE = await import(toUrl('studio/node_modules/three/build/three.module.js'));
const { GLTFLoader } = await import(toUrl('studio/node_modules/three/examples/jsm/loaders/GLTFLoader.js'));
const { applyEnvironmentDefaults } = await import(toUrl('4_Horses_Environment_v02/visual/environment-layers.js'));
const { stageSlotTransform } = await import(toUrl('studio/src/spatial.js'));
const { applyMapGeometryFixes } = await import(toUrl('studio/src/map-geometry.js'));
const { applyMapLayoutExpansion, findFloorSlab } = await import(toUrl('studio/src/map-layout.js'));
const { applyMapFloorFixes } = await import(toUrl('studio/src/map-floor.js'));

async function parseGlb(absPath) {
  const buf = await fs.readFile(absPath);
  const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
  return new Promise((resolve, reject) => new GLTFLoader().parse(ab, '', resolve, reject));
}

function measureVerticesBox(sceneRoot, nodeNames) {
  sceneRoot.updateMatrixWorld(true);
  const pt = new THREE.Vector3();
  let meshCount = 0;
  let minY = Infinity, maxY = -Infinity;
  let minX = Infinity, maxX = -Infinity;
  let minZ = Infinity, maxZ = -Infinity;
  const foundNodes = [];
  for (const name of nodeNames) {
    const root = sceneRoot.getObjectByName(name);
    if (!root) continue;
    foundNodes.push(name);
    root.traverse((o) => {
      if (!o.visible || !o.isMesh || !o.geometry?.attributes?.position) return;
      const pos = o.geometry.attributes.position;
      if (pos.count === 0) return;
      meshCount++;
      for (let i = 0; i < pos.count; i++) {
        pt.fromBufferAttribute(pos, i).applyMatrix4(o.matrixWorld);
        if (pt.x < minX) minX = pt.x;
        if (pt.x > maxX) maxX = pt.x;
        if (pt.y < minY) minY = pt.y;
        if (pt.y > maxY) maxY = pt.y;
        if (pt.z < minZ) minZ = pt.z;
        if (pt.z > maxZ) maxZ = pt.z;
      }
    });
  }
  if (meshCount === 0 || !Number.isFinite(minY)) {
    return { exists: false, foundNodes, meshCount: 0, minY: null, maxY: null };
  }
  return {
    exists: true,
    foundNodes,
    meshCount,
    minY: Number(minY.toFixed(5)),
    maxY: Number(maxY.toFixed(5)),
    span: [
      Number((maxX - minX).toFixed(4)),
      Number((maxY - minY).toFixed(4)),
      Number((maxZ - minZ).toFixed(4)),
    ],
  };
}

function measureMapMetrics(envRoot, layoutRoot) {
  envRoot.updateMatrixWorld(true);
  layoutRoot.updateMatrixWorld(true);
  const slab = findFloorSlab(envRoot) || envRoot.getObjectByName('Raised_concrete_slab');
  const slabBox = slab ? new THREE.Box3().setFromObject(slab, true) : null;
  const walls = envRoot.getObjectByName('ENV_WALLS_AND_DOCKS');
  const wallsBox = walls ? new THREE.Box3().setFromObject(walls, true) : null;
  const dock01 = envRoot.getObjectByName('DOCK_01');
  const dock02 = envRoot.getObjectByName('DOCK_02');
  let meshCount = 0;
  let patchGroups = 0;
  for (const r of [envRoot, layoutRoot]) {
    r.traverse((o) => {
      if (o.isMesh) meshCount++;
      if (
        !o.userData?.__syntheticMarker &&
        /^MAP_(LAYOUT_EXPANSION|EXPANDED_GRID|GEOMETRY|FLOOR|ROBOT_REINFORCEMENT_FEET|ROBOT_TABLE_UNDERFRAME|WATER_COOLER_PLINTH)/.test(
          o.name || '',
        )
      ) {
        patchGroups++;
      }
    });
  }
  const toDict = (b) => b && !b.isEmpty()
    ? { min: b.min.toArray(), max: b.max.toArray(), span: [b.max.x - b.min.x, b.max.y - b.min.y, b.max.z - b.min.z] }
    : null;
  return {
    slabBox: toDict(slabBox),
    wallsBox: toDict(wallsBox),
    dock01Pos: dock01 ? dock01.getWorldPosition(new THREE.Vector3()).toArray() : null,
    dock02Pos: dock02 ? dock02.getWorldPosition(new THREE.Vector3()).toArray() : null,
    meshCount,
    patchGroups,
  };
}

function runIdempotencyTrial(envTemplate, layoutTemplate) {
  try {
    const env = envTemplate.clone(true);
    const lay = layoutTemplate.clone(true);
    for (const r of [env, lay]) {
      r.traverse((o) => { if (o.isMesh && o.geometry) o.geometry = o.geometry.clone(); });
    }
    const h1 = applyMapGeometryFixes(env, lay);
    const h2 = applyMapLayoutExpansion(env, lay);
    const h3 = applyMapFloorFixes(env, lay);
    const pass1 = measureMapMetrics(env, lay);

    applyMapGeometryFixes(env, lay);
    applyMapLayoutExpansion(env, lay);
    applyMapFloorFixes(env, lay);
    const pass2 = measureMapMetrics(env, lay);

    applyMapGeometryFixes(env, lay);
    applyMapLayoutExpansion(env, lay);
    applyMapFloorFixes(env, lay);
    const pass3 = measureMapMetrics(env, lay);

    h3?.dispose?.();
    h2?.dispose?.();
    h1?.dispose?.();
    const afterDispose = measureMapMetrics(env, lay);

    applyMapGeometryFixes(env, lay);
    applyMapLayoutExpansion(env, lay);
    applyMapFloorFixes(env, lay);
    const afterReapply = measureMapMetrics(env, lay);

    return { ok: true, pass1, pass2, pass3, afterDispose, afterReapply };
  } catch (err) {
    return { ok: false, error: `${err?.name || 'Error'}: ${err?.message || err}` };
  }
}

const v02Dir = path.join(repoRoot, '4_Horses_Environment_v02');
const [envGltf, layoutGltf, supportGltf, bindingsRaw] = await Promise.all([
  parseGlb(path.join(v02Dir, 'warehouse_environment.glb')),
  parseGlb(path.join(v02Dir, 'modules', 'visual_layout.glb')),
  parseGlb(path.join(v02Dir, 'modules', 'visual_support.glb')),
  fs.readFile(path.join(v02Dir, 'visual_bindings.json'), 'utf8'),
]);
const bindings = JSON.parse(bindingsRaw);

// 1. Standalone warehouse_environment.glb workstation floor-grounding (R2)
const standaloneEnv = envGltf.scene.clone(true);
applyEnvironmentDefaults(standaloneEnv);
const walkwayChevronsOrArrows = [];
standaloneEnv.traverse((o) => {
  if (o.visible && /(ARROW|CHEVRON)/i.test(o.name || '')) {
    walkwayChevronsOrArrows.push(o.name);
  }
});
const standaloneWorkstations = {
  STAGE1_PREP_TABLE: measureVerticesBox(standaloneEnv, ['STAGE1_PREP_TABLE']),
  BENCH_PICK: measureVerticesBox(standaloneEnv, ['BENCH_PICK']),
  BENCH_PACK: measureVerticesBox(standaloneEnv, ['BENCH_PACK']),
  BENCH_REWORK: measureVerticesBox(standaloneEnv, ['BENCH_REWORK']),
  BENCH_SCRAP: measureVerticesBox(standaloneEnv, ['BENCH_SCRAP']),
  ROBOT_PACK_TABLE: measureVerticesBox(standaloneEnv, ['ROBOT_PACK_TABLE', 'ROBOT_TABLE_REINFORCEMENT']),
  STAGE4_QC_TABLE: measureVerticesBox(standaloneEnv, ['STAGE4_QC_TABLE']),
  BREAK_BENCH: measureVerticesBox(standaloneEnv, ['BREAK_BENCH']),
  WATER_COOLER: measureVerticesBox(standaloneEnv, ['WATER_COOLER']),
  SHIPPING_MANIFEST_PODIUM: measureVerticesBox(standaloneEnv, ['SHIPPING_MANIFEST_PODIUM']),
};

// 2. Combined Studio (env + layout + cloned parallel benches) floor-grounding (R2 x R4)
const studioScene = new THREE.Scene();
const studioEnv = envGltf.scene.clone(true);
const studioLay = layoutGltf.scene.clone(true);
for (const r of [studioEnv, studioLay]) {
  r.traverse((o) => { if (o.isMesh && o.geometry) o.geometry = o.geometry.clone(); });
}
studioScene.add(studioEnv, studioLay);
applyEnvironmentDefaults(studioEnv);
applyMapGeometryFixes(studioEnv, studioLay);
applyMapLayoutExpansion(studioEnv, studioLay);
applyMapFloorFixes(studioEnv, studioLay);

const manualBenchTemplate = supportGltf.scene.getObjectByName('VIS_manual_bench');
const clonedBenchNames = [];
const maxSlotsByStage = { 1: 3, 2: 3, 3: 6, 4: 3 };
for (const [stStr, count] of Object.entries(maxSlotsByStage)) {
  const stage = Number(stStr);
  for (let i = 1; i < count; i++) {
    const slot = stageSlotTransform(bindings, stage, i);
    const bench = manualBenchTemplate.clone(true);
    bench.name = `PARALLEL_STAGE_${stage}_${i}`;
    bench.position.fromArray(slot.bench);
    bench.rotation.y = slot.benchRotY;
    studioScene.add(bench);
    clonedBenchNames.push(bench.name);
  }
}

const studioStationary = {
  STAGE1_PREP: measureVerticesBox(studioScene, ['STAGE1_PREP_TABLE', 'VIS_STAGE_1_TABLE']),
  STAGE2_PICK: measureVerticesBox(studioScene, ['BENCH_PICK']),
  STAGE3_PACK: measureVerticesBox(studioScene, ['BENCH_PACK']),
  BENCH_REWORK: measureVerticesBox(studioScene, ['BENCH_REWORK']),
  BENCH_SCRAP: measureVerticesBox(studioScene, ['BENCH_SCRAP']),
  STAGE3_ROBOT: measureVerticesBox(studioScene, ['ROBOT_PACK_TABLE', 'ROBOT_TABLE_REINFORCEMENT', 'VIS_ROBOT_PACK_TABLE']),
  STAGE4_QC: measureVerticesBox(studioScene, ['STAGE4_QC_TABLE', 'VIS_STAGE_4_TABLE', 'QC_TABLE_TOOLING']),
  BREAK_BENCH: measureVerticesBox(studioScene, ['BREAK_BENCH']),
  WATER_COOLER: measureVerticesBox(studioScene, ['WATER_COOLER']),
  SHIPPING_MANIFEST_PODIUM: measureVerticesBox(studioScene, ['SHIPPING_MANIFEST_PODIUM']),
};
const studioClonedBenches = {};
for (const bName of clonedBenchNames) {
  studioClonedBenches[bName] = measureVerticesBox(studioScene, [bName]);
}

// 3. Superseding F02 Unobstructed Ceiling & Active Studio Lighting Audit (02:42:13Z)
function isOverheadBeamOrLampMesh(o) {
  if (!o?.isMesh) return false;
  for (let cur = o; cur; cur = cur.parent) {
    const nm = cur.name || '';
    if (/^(ENV_OVERHEAD|OVERHEAD_TRUSS|OVERHEAD_CABLE_TRAY|HIGHBAY|ENV_LIGHTING_RIG)/i.test(nm)) {
      return true;
    }
    if (/\b(OVERHEAD_TRUSS|OVERHEAD_CABLE_TRAY|HIGHBAY|LIGHTING_RIG|RAFTER)\b/i.test(nm)) {
      return true;
    }
    if (/^(Cable_tray_|Truss_|Rafter_|Highbay_)/i.test(nm) || /^Truss\b/i.test(nm)) {
      return true;
    }
  }
  return false;
}

function isEffectivelyVisible(o) {
  for (let cur = o; cur; cur = cur.parent) {
    if (cur.visible === false) return false;
  }
  return true;
}

const glbOverheadMeshes = [];
for (const [label, root] of [
  ['warehouse_environment.glb', envGltf.scene],
  ['modules/visual_layout.glb', layoutGltf.scene],
  ['modules/visual_support.glb', supportGltf.scene],
]) {
  root.traverse((o) => {
    if (isOverheadBeamOrLampMesh(o)) glbOverheadMeshes.push(`${label}:${o.name}`);
  });
}

const studioVisibleOverheadMeshes = [];
studioScene.traverse((o) => {
  if (isOverheadBeamOrLampMesh(o) && isEffectivelyVisible(o)) {
    studioVisibleOverheadMeshes.push(o.name);
  }
});

const sceneJsSrc = await fs.readFile(path.join(repoRoot, 'studio', 'src', 'scene.js'), 'utf8');
const lightMatches = sceneJsSrc.match(/\b(HemisphereLight|DirectionalLight|AmbientLight|PointLight|SpotLight|RectAreaLight)\b/g) || [];
const studioLightConstructs = lightMatches.length;

// 4. Map idempotency across shipped, synthetic 36m native clone, and staged Studio scene
const shippedTrial = runIdempotencyTrial(envGltf.scene, layoutGltf.scene);
const synthEnv = envGltf.scene.clone(true);
const marker = new THREE.Group();
marker.name = 'MAP_LAYOUT_EXPANSION';
marker.userData = { nativeExpanded: true, __syntheticMarker: true };
synthEnv.add(marker);
const syntheticNative36mTrial = runIdempotencyTrial(synthEnv, layoutGltf.scene);

let stagedTrial = null;
for (const relDir of ['studio/dist/scene', 'studio/public/scene']) {
  const envP = path.join(repoRoot, relDir, 'warehouse_environment.glb');
  const layP = path.join(repoRoot, relDir, 'modules', 'visual_layout.glb');
  if (fsSync.existsSync(envP) && fsSync.existsSync(layP)) {
    const [sEnv, sLay] = await Promise.all([parseGlb(envP), parseGlb(layP)]);
    stagedTrial = { dir: relDir, ...runIdempotencyTrial(sEnv.scene, sLay.scene) };
    break;
  }
}

await fs.writeFile(outPath, JSON.stringify({
  ok: true,
  walkwayChevronsOrArrows,
  standaloneWorkstations,
  studioStationary,
  studioClonedBenches,
  glbOverheadMeshes,
  studioVisibleOverheadMeshes,
  studioLightConstructs,
  mapIdempotency: {
    shipped: shippedTrial,
    syntheticNative36m: syntheticNative36mTrial,
    stagedScene: stagedTrial,
  },
}));
"""


def _audit_workstation_grounding_and_map_idempotency(
    repo_root: Path,
    session_tmp_dir: Path,
    node_probe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run cached read-only Three.js probe checking workstation floor-grounding and map-*.js idempotency."""
    if isinstance(node_probe, dict) and node_probe.get("ok"):
        env_audit = node_probe.get("environmentAudit") or {}
        wg = env_audit.get("workstationGrounding") or {}
        st_env = wg.get("standaloneEnv") or {}
        cb_st = wg.get("combinedStudio") or {}
        fa = env_audit.get("floorArrowsAudit") or {}
        sra = node_probe.get("studioReplayAudit") or {}
        ceil = sra.get("ceilingAudit") or {}
        return {
            "ok": True,
            "walkwayChevronsOrArrows": [a.get("name") for a in (fa.get("walkwayArrows") or [])],
            "standaloneWorkstations": {
                "STAGE1_PREP_TABLE": st_env.get("stage1_prep"),
                "BENCH_PICK": st_env.get("stage2_pick"),
                "BENCH_PACK": st_env.get("stage3_pack"),
                "BENCH_REWORK": st_env.get("bench_rework"),
                "BENCH_SCRAP": st_env.get("bench_scrap"),
                "ROBOT_PACK_TABLE": st_env.get("stage3_robot"),
                "STAGE4_QC_TABLE": st_env.get("stage4_qc"),
                "BREAK_BENCH": st_env.get("break_bench"),
                "WATER_COOLER": st_env.get("water_cooler"),
                "SHIPPING_MANIFEST_PODIUM": st_env.get("shipping_podium"),
            },
            "studioStationary": {
                "STAGE1_PREP": cb_st.get("stage1_prep"),
                "STAGE2_PICK": cb_st.get("stage2_pick"),
                "STAGE3_PACK": cb_st.get("stage3_pack"),
                "BENCH_REWORK": cb_st.get("bench_rework"),
                "BENCH_SCRAP": cb_st.get("bench_scrap"),
                "STAGE3_ROBOT": cb_st.get("stage3_robot"),
                "STAGE4_QC": cb_st.get("stage4_qc"),
                "BREAK_BENCH": cb_st.get("break_bench"),
                "WATER_COOLER": cb_st.get("water_cooler"),
                "SHIPPING_MANIFEST_PODIUM": cb_st.get("shipping_podium"),
            },
            "studioClonedBenches": wg.get("studioClonedBenches") or {},
            "glbOverheadMeshes": env_audit.get("forbiddenOverheadMeshes") or [],
            "studioVisibleOverheadMeshes": ceil.get("visibleOverheadMeshes") or [],
            "studioLightConstructs": int(ceil.get("activeLightCount") or 0),
            "mapIdempotency": node_probe.get("mapIdempotency") or {},
        }
    cache_key = str(repo_root)
    if cache_key in _GROUNDING_MAP_CACHE:
        return _GROUNDING_MAP_CACHE[cache_key]

    env = build_e2e_env(repo_root)
    script_path = session_tmp_dir / "t3_grounding_and_map_probe.mjs"
    out_path = session_tmp_dir / "t3_grounding_and_map_probe.json"
    script_path.write_text(_GROUNDING_AND_MAP_MJS, encoding="utf-8")

    comp = subprocess.run(
        [env["NODE_BIN"], str(script_path), str(repo_root), str(out_path)],
        cwd=str(repo_root / "studio"),
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    if comp.returncode != 0 or not out_path.exists():
        res: dict[str, Any] = {
            "ok": False,
            "returncode": comp.returncode,
            "error": (comp.stderr or comp.stdout)[-800:],
        }
    else:
        res = json.loads(out_path.read_text(encoding="utf-8"))
    _GROUNDING_MAP_CACHE[cache_key] = res
    return res


_BLEND_CEILING_CACHE: dict[str, dict[str, Any]] = {}

_BLEND_CEILING_PY = r"""
import json
import sys
from pathlib import Path
import bpy

out_path = Path(sys.argv[-1])

def ancestor_names(obj):
    names = []
    cur = obj
    while cur is not None:
        names.append(cur.name)
        cur = cur.parent
    return names

active_lights = [
    {
        "name": o.name,
        "type": getattr(o.data, "type", None),
        "energy": float(getattr(o.data, "energy", 0.0)),
    }
    for o in bpy.data.objects
    if o.type == "LIGHT"
    and not o.hide_render
    and float(getattr(o.data, "energy", 0.0)) > 0.0
]

overhead_meshes = []
for o in bpy.data.objects:
    if o.type != "MESH":
        continue
    chain = ancestor_names(o)
    joined_upper = " | ".join(chain).upper()
    if any(
        tok in joined_upper
        for tok in (
            "ENV_OVERHEAD",
            "OVERHEAD_TRUSS",
            "OVERHEAD_CABLE_TRAY",
            "HIGHBAY",
            "ENV_LIGHTING_RIG",
            "LIGHTING_RIG",
            "CABLE_TRAY",
            "CABLE TRAY",
            "RAFTER",
            "TRUSS",
        )
    ):
        overhead_meshes.append(o.name)

out_path.write_text(
    json.dumps(
        {
            "ok": True,
            "active_lights": active_lights,
            "overhead_meshes": sorted(overhead_meshes),
        }
    ),
    encoding="utf-8",
)
"""


def _audit_blend_ceiling_and_lights(
    repo_root: Path,
    session_tmp_dir: Path,
    blender_probe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run cached read-only Blender check verifying 0 physical overhead beam/lamp meshes & active lights."""
    if isinstance(blender_probe, dict) and blender_probe.get("ok"):
        ov = blender_probe.get("overhead") or {}
        return {
            "ok": True,
            "active_lights": ov.get("active_lights") or [],
            "overhead_meshes": ov.get("forbidden_overhead_meshes") or [],
        }
    cache_key = str(repo_root)
    if cache_key in _BLEND_CEILING_CACHE:
        return _BLEND_CEILING_CACHE[cache_key]

    blend_path = repo_root / "4_Horses_Environment_v02" / "warehouse_environment.blend"
    if not blend_path.exists():
        res: dict[str, Any] = {"ok": False, "error": f"Missing {blend_path}"}
        _BLEND_CEILING_CACHE[cache_key] = res
        return res

    env = build_e2e_env(repo_root)
    py_path = session_tmp_dir / "t3_blend_ceiling_lights.py"
    out_path = session_tmp_dir / "t3_blend_ceiling_lights.json"
    py_path.write_text(_BLEND_CEILING_PY, encoding="utf-8")

    comp = subprocess.run(
        [
            env["BLENDER_BIN"],
            "-b",
            str(blend_path),
            "--factory-startup",
            "--python",
            str(py_path),
            "--",
            str(out_path),
        ],
        cwd=str(session_tmp_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if comp.returncode != 0 or not out_path.exists():
        res = {
            "ok": False,
            "returncode": comp.returncode,
            "error": (comp.stderr or comp.stdout)[-800:],
        }
    else:
        res = json.loads(out_path.read_text(encoding="utf-8"))
    _BLEND_CEILING_CACHE[cache_key] = res
    return res


def _check_frozen_benchmark_contracts_git_clean(repo_root: Path) -> None:
    """Verify 0 git diff on frozen Python core & benchmark contracts without touching external files."""
    env = build_e2e_env(repo_root)
    test_files = [
        str(p.relative_to(repo_root))
        for p in sorted((repo_root / "tests").glob("test_*.py"))
    ]
    scoped_paths = [
        "src/robotization_bench",
        "data/world_spec.json",
        *test_files,
        "scripts/export_3d_pack.py",
        "scripts/serve_3d.py",
        "studio/public/demo-pack",
    ]
    diff_proc = subprocess.run(
        ["git", "diff", "--exit-code", "HEAD", "--", *scoped_paths],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert diff_proc.returncode == 0, (
        f"Immutable benchmark contract files modified relative to HEAD:\n{diff_proc.stdout[:800]}"
    )


_DEEP_COUNTER_CACHE: dict[str, list[str]] = {}

_DEEP_COUNTER_MJS = r"""
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const [repoRoot, outPath, ...runDirs] = process.argv.slice(2);
const { createReplay, COUNTER_KEYS } = await import(
  pathToFileURL(path.join(repoRoot, 'studio/src/replay.js')).href
);

const results = {};
for (const dir of runDirs) {
  const manifest = JSON.parse(await fs.readFile(path.join(dir, 'manifest.json'), 'utf8'));
  const eventsText = await fs.readFile(path.join(dir, manifest.events_file || 'events.jsonl'), 'utf8');
  const rep = createReplay(manifest, eventsText, { runId: path.basename(dir) });
  const endSt = rep.seekTo(rep.horizonTicks * rep.tickSeconds);
  const mismatches = COUNTER_KEYS.filter(
    (k) => JSON.stringify(endSt.counters[k]) !== JSON.stringify(rep.manifest.raw[k]),
  );
  results[dir] = mismatches;
}
await fs.writeFile(outPath, JSON.stringify(results));
"""


def _verify_bundle_deep_counters(
    repo_root: Path,
    session_tmp_dir: Path,
    run_dirs: list[Path],
) -> dict[str, list[str]]:
    """Verify deep-equal end-of-shift counters (including overtime_ticks array) via studio/src/replay.js."""
    missing = [str(d) for d in run_dirs if str(d) not in _DEEP_COUNTER_CACHE]
    if missing:
        env = build_e2e_env(repo_root)
        script_path = session_tmp_dir / "t3_deep_counter_check.mjs"
        out_path = session_tmp_dir / f"t3_deep_counter_check_{len(_DEEP_COUNTER_CACHE)}.json"
        script_path.write_text(_DEEP_COUNTER_MJS, encoding="utf-8")
        comp = subprocess.run(
            [env["NODE_BIN"], str(script_path), str(repo_root), str(out_path), *missing],
            cwd=str(repo_root / "studio"),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert comp.returncode == 0 and out_path.exists(), (
            f"Deep ReplayModel counter check failed (rc={comp.returncode}): {(comp.stderr or comp.stdout)[-600:]}"
        )
        loaded = json.loads(out_path.read_text(encoding="utf-8"))
        for k, v in loaded.items():
            _DEEP_COUNTER_CACHE[k] = list(v)
    return {str(d): _DEEP_COUNTER_CACHE[str(d)] for d in run_dirs}


def test_t3_01_f1_x_f2_chain_zones_docks_camera_and_stage3_label(
    v02_configs: dict[str, Any],
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F1 × F2: Chain zone bounds fit inside 36x18m slab, S0/S5A align with DOCK_01/02, CAMERA_OVERVIEW frames all unobstructed, and Stage-3 label aligns."""
    assert v02_configs["files"]["workshop_chain"]["ok"], (
        f"workshop_chain.json unavailable: {v02_configs['files']['workshop_chain']['error']}"
    )
    assert blender_probe.get("ok"), f"blender_probe failed: {blender_probe.get('error')}"
    assert node_probe.get("ok"), f"node_probe failed: {node_probe.get('error')}"

    chain = v02_configs["workshop_chain"]
    stages = {st["id"]: st for st in chain.get("stages", []) if isinstance(st, dict) and "id" in st}
    assert len(stages) == 12, f"Expected 12 chain stages, got {sorted(stages)}"

    env_audit = node_probe["environmentAudit"]
    slab_box = env_audit["slabBox"]
    assert slab_box is not None, "Raised_concrete_slab missing in warehouse_environment.glb"
    slab_min_x, _, slab_min_z = slab_box["min"]
    slab_max_x, _, slab_max_z = slab_box["max"]
    assert abs((slab_max_x - slab_min_x) - 36.0) <= 0.05, f"Slab width != 36m: {slab_box}"
    assert abs((slab_max_z - slab_min_z) - 18.0) <= 0.05, f"Slab depth != 18m: {slab_box}"

    for sid, st in sorted(stages.items()):
        bounds = normalize_zone_bounds(st.get("zone_bounds_gltf"))
        assert bounds is not None, f"{sid}: invalid zone_bounds_gltf {st.get('zone_bounds_gltf')!r}"
        min_x, max_x, min_z, max_z = bounds
        assert slab_min_x - 0.05 <= min_x < max_x <= slab_max_x + 0.05, (
            f"{sid} X bounds {bounds} protrude outside 36m slab [{slab_min_x}, {slab_max_x}]"
        )
        assert slab_min_z - 0.05 <= min_z < max_z <= slab_max_z + 0.05, (
            f"{sid} Z bounds {bounds} protrude outside 18m slab [{slab_min_z}, {slab_max_z}]"
        )

    assert "DOCK_01" in stages["S0_INBOUND"]["equipment_nodes"], "S0_INBOUND must include DOCK_01"
    assert "DOCK_02" in stages["S5A_GOOD"]["equipment_nodes"], "S5A_GOOD must include DOCK_02"
    dock01_pos = env_audit["dock01Pos"]
    dock02_pos = env_audit["dock02Pos"]
    assert dock01_pos is not None and dock02_pos is not None, "DOCK_01/DOCK_02 missing from GLB"
    assert abs(dock01_pos[0] - (-17.85)) <= 0.05 and abs(dock01_pos[2] - 5.15) <= 0.05, (
        f"DOCK_01 misaligned with S0_INBOUND west portal: {dock01_pos}"
    )
    assert abs(dock02_pos[0] - 17.85) <= 0.05 and abs(dock02_pos[2] - 5.15) <= 0.05, (
        f"DOCK_02 misaligned with S5A_GOOD east portal: {dock02_pos}"
    )

    cam = blender_probe["camera"]
    assert cam["exists"], "CAMERA_OVERVIEW missing in warehouse_environment.blend"
    assert abs(cam["location"][0]) <= 1.0 and abs(cam["target_at_z085"][0]) <= 1.0, (
        f"CAMERA_OVERVIEW not X-centered on 36m hall: loc={cam['location']}, target={cam['target_at_z085']}"
    )
    for dock_name in ("DOCK_01", "DOCK_02"):
        d_cam = cam["docks"][dock_name]
        assert d_cam["in_frustum"] and not d_cam["occluded"], (
            f"{dock_name} obstructed or out of CAMERA_OVERVIEW frustum: {d_cam}"
        )
    for corner_key, corner_info in cam["floor_corners"].items():
        assert corner_info["in_frustum"], f"Hall floor corner {corner_key} outside CAMERA_OVERVIEW: {corner_info}"

    for cfg_key in ("environment_config", "config_environment"):
        st3 = v02_configs["stage3_pack_station"][cfg_key]
        assert st3 is not None and is_stage3_pack_station(st3), (
            f"Stage-3 pack station missing or unaligned in {cfg_key}: {st3}"
        )


def test_t3_02_f1_x_f3_chain_edges_backed_by_physical_spurs_and_lanes(
    v02_configs: dict[str, Any],
    chain_report: dict[str, Any],
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F1 × F3: Every material-flow edge in workshop_chain.json is backed by physical transfer spurs, lanes, widened Zone 01, and clear walkways."""
    assert chain_report["ok"], f"workshop_chain.json failed scene/DAG validation: {chain_report['errors']}"
    assert blender_probe.get("ok"), f"blender_probe failed: {blender_probe.get('error')}"
    assert node_probe.get("ok"), f"node_probe failed: {node_probe.get('error')}"

    chain = v02_configs["workshop_chain"]
    stages = {st["id"]: st for st in chain["stages"]}
    assert "S1_PREP" in stages["S0_INBOUND"]["downstream_ids"]
    assert "S2_PICK" in stages["S1_PREP"]["downstream_ids"]
    assert {"S3A_PACK_MANUAL", "S3B_PACK_ROBOT"}.issubset(stages["S2_PICK"]["downstream_ids"])
    assert "S4_QC" in stages["S3A_PACK_MANUAL"]["downstream_ids"]
    assert {"S4_QC", "S3C_ROBOT_ASSIST"}.issubset(stages["S3B_PACK_ROBOT"]["downstream_ids"])
    assert {"S5A_GOOD", "S5B_ESCAPED", "S5C_REWORK_R", "S5D_SCRAP"}.issubset(
        stages["S4_QC"]["downstream_ids"]
    )
    assert stages["S5C_REWORK_R"]["downstream_ids"] == ["S3A_PACK_MANUAL"] or (
        "S3A_PACK_MANUAL" in stages["S5C_REWORK_R"]["downstream_ids"]
        and "S3B_PACK_ROBOT" not in stages["S5C_REWORK_R"]["downstream_ids"]
    )

    spurs = blender_probe["spurs_and_zones"]
    equip = blender_probe["equipment"]
    env_audit = node_probe["environmentAudit"]

    for spur_name in ("INFEED_PREP_C01", "OUTFEED_C10_GOOD"):
        spur_info = spurs[spur_name]
        assert spur_info["exists"] and spur_info["mesh_count"] >= 1, (
            f"Physical spur {spur_name} missing or empty: {spur_info}"
        )
        assert spur_name in env_audit["additiveSpursPresent"], (
            f"{spur_name} missing from exported warehouse_environment.glb"
        )

    for idx in range(1, 11):
        conv_name = f"CONVEYOR_{idx:02d}"
        assert equip[conv_name]["exists"] and equip[conv_name]["mesh_count"] >= 1, (
            f"{conv_name} missing in Blender scene"
        )

    assert len(spurs["floor_transfer_lanes"]) >= 2 or len(env_audit["transferLaneNodes"]) >= 2, (
        f"Expected physical floor transfer lanes (inbound/dispatch/rework), got blend={spurs['floor_transfer_lanes']}, glb={env_audit['transferLaneNodes']}"
    )

    totes = spurs["pick_totes_tooling"]
    assert totes["root_exists"] and totes["root_mesh_count"] >= 2, (
        f"BENCH_PICK SKU tote tooling missing at S2_PICK: {totes}"
    )
    assert spurs["tray_volume_intrusions"].get("VIS_STAGE_2_ORDER", 0) == 0, (
        f"PICK_BENCH_TOTES intrudes into S2_PICK order tray volume: {spurs['tray_volume_intrusions']}"
    )

    z01 = spurs["floor_zones"]["FLOOR_ZONE_01"]
    assert z01["aabb"] is not None and z01["aabb"]["min"][0] <= -13.15, (
        f"FLOOR_ZONE_01 not widened to enclose Q1 staging: {z01}"
    )
    for q1_pos in spurs["q1_slot_positions_blender"]:
        assert q1_pos[0] >= z01["aabb"]["min"][0] + 0.05, (
            f"Q1 slot {q1_pos} protrudes outside widened FLOOR_ZONE_01 {z01['aabb']}"
        )

    assert blender_probe["bvh"]["walkway_hits"] == [], (
        f"WALKWAY_GREEN_5S obstructed in .blend BVH: {blender_probe['bvh']['walkway_hits']}"
    )
    assert env_audit["walkwayPrismHits"] == 0, (
        f"WALKWAY_GREEN_5S obstructed in GLB prism check: {env_audit['walkwayPrismHits']}"
    )


def test_t3_03_f1_x_f4_chain_equipment_clean_glbs_and_086m_supports(
    v02_configs: dict[str, Any],
    chain_report: dict[str, Any],
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F1 × F4: Chain equipment_nodes and anchors resolve to 0-error GLBs with ±2mm floor grounding, 0.860m worktops, and 0 BVH collisions."""
    assert chain_report["ok"], f"Chain cross-reference failed: {chain_report['errors']}"
    assert blender_probe.get("ok"), f"blender_probe failed: {blender_probe.get('error')}"
    assert node_probe.get("ok"), f"node_probe failed: {node_probe.get('error')}"

    gltf_val = node_probe["gltfValidation"]
    for rel in ALL_15_GLBS:
        info = gltf_val.get(rel) or {}
        assert info.get("exists"), f"Missing required GLB: {rel}"
        assert info.get("numErrors") == 0, f"gltf-validator errors in {rel}: {info}"
        assert info.get("nanVertices", 0) == 0 and info.get("zeroAreaTriangles", 0) == 0, (
            f"Degenerate geometry in {rel}: nan={info.get('nanVertices')}, zeroTri={info.get('zeroAreaTriangles')}"
        )

    env_audit = node_probe["environmentAudit"]
    assert env_audit["benchReworkInEnv"] and env_audit["benchScrapInEnv"], (
        f"Mandatory grounded BENCH_REWORK or BENCH_SCRAP missing in warehouse_environment.glb: rework={env_audit.get('benchReworkInEnv')}, scrap={env_audit.get('benchScrapInEnv')}"
    )
    assert not env_audit["utilityCabinetInEnv"] and env_audit["cabinetRegionTris"] == 0, (
        f"Legacy UTILITY_CABINET clutter remaining: {env_audit['cabinetRegionTris']} tris"
    )
    jack = env_audit["palletJack"]
    assert jack["meshCount"] >= 4 and jack["triangleCount"] >= 200 and jack["aabb"] is not None, (
        f"PALLET_JACK child meshes stripped or broken in S0_INBOUND: {jack}"
    )
    assert abs(jack["aabb"]["min"][1]) <= 0.002, f"PALLET_JACK not grounded at y=0: {jack['aabb']}"

    equip = blender_probe["equipment"]
    chain_floor_roots = (
        "PALLET_JACK",
        "Q1_PAIRED_PALLET_DECK",
        "VIS_STAGE_1_TABLE",
        "BENCH_PICK",
        "BENCH_PACK",
        "BENCH_REWORK",
        "BENCH_SCRAP",
        "VIS_ROBOT_PACK_TABLE",
        "VIS_STAGE_4_TABLE",
        "QC_PORTAL",
        "DISPATCH_PALLET_00",
        "DISPATCH_PALLET_01",
        "QUEUE_R_ROLLER_SECTION",
        "SCRAP_BIN",
        "BREAK_BENCH",
        "WATER_COOLER",
        "ROBOT_PLC_CABINET",
    )
    for name in chain_floor_roots:
        eq = equip.get(name) or {}
        assert eq.get("exists") and eq.get("aabb") is not None, f"Chain equipment {name} missing: {eq}"
        min_z = eq["aabb"]["min"][2]
        assert -0.002 <= min_z <= 0.002, f"{name} floating or sinking (min_z={min_z:.4f}m outside ±2mm)"

    supports = blender_probe["supports"]
    assert supports["main_rollers"]["count"] == 200 and supports["main_rollers"]["offenders"] == [], (
        f"Main conveyor roller height offenders from 0.860m: {supports['main_rollers']}"
    )
    assert supports["buffer_rollers"]["offenders"] == [], (
        f"Queue/rework buffer roller offenders from 0.860m: {supports['buffer_rollers']}"
    )

    chain = v02_configs["workshop_chain"]
    stages = {st["id"]: st for st in chain["stages"]}
    for sid in ("S1_PREP", "S2_PICK", "S3A_PACK_MANUAL", "S3B_PACK_ROBOT", "S4_QC"):
        ord_anc = stages[sid]["order_anchor"]
        wt = supports["workstation_tops"].get(ord_anc) or {}
        assert wt.get("exists") and wt.get("covers_tray_footprint"), (
            f"{sid} ({ord_anc}) missing 0.860m support envelope covering tray footprint: {wt}"
        )
        assert len(wt.get("top_mesh_names") or []) >= 1, (
            f"{sid} ({ord_anc}) has zero 0.860m±0.0025m support top meshes: {wt}"
        )
        oloc = wt.get("order_loc")
        env_xy = wt.get("top_envelope") or {}
        assert isinstance(oloc, list) and len(oloc) == 3 and abs(oloc[2] - 0.860) <= 0.004, (
            f"{sid} ({ord_anc}) order_loc Z={oloc} != 0.860m"
        )
        assert (
            env_xy["min_x"] <= oloc[0] - 0.268
            and env_xy["max_x"] >= oloc[0] + 0.268
            and env_xy["min_y"] <= oloc[1] - 0.198
            and env_xy["max_y"] >= oloc[1] + 0.198
        ), f"{sid} ({ord_anc}) 0.860m support envelope {env_xy} fails to cover tray around {oloc}"

    real_collisions = [
        col
        for col in blender_probe["bvh"]["unintended_collisions"]
        if frozenset((col.get("a"), col.get("b")))
        != frozenset(("ROBOT_PACK_TABLE", "ROBOT_TABLE_REINFORCEMENT"))
    ]
    assert real_collisions == [], (
        f"Unintended BVH static assembly collisions: {real_collisions}"
    )


def test_t3_04_f1_x_f5_x_f6_chain_roles_and_30fps_worker_robot_clips(
    v02_configs: dict[str, Any],
    chain_report: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F1 × F5 × F6: Every stage's character_roles, operation_clips, and transfer_clips resolve to non-degenerate 30-FPS clips on 35-bone worker and 41-bone robot GLBs."""
    assert v02_configs["files"]["workshop_chain"]["ok"], (
        f"workshop_chain.json unavailable: {v02_configs['files']['workshop_chain']['error']}"
    )
    assert chain_report["ok"], f"workshop_chain.json validation errors: {chain_report['errors']}"
    assert node_probe.get("ok"), f"node_probe failed: {node_probe.get('error')}"

    worker = node_probe["characterAudit"]["worker"]
    robot = node_probe["characterAudit"]["robot"]

    assert worker["numErrors"] == 0 and worker["boneCount"] == 35, (
        f"Worker GLB invalid or wrong bone count: errors={worker['numErrors']}, bones={worker['boneCount']}"
    )
    assert set(worker["clipNames"]) == EXPECTED_WORKER_17_CLIPS, (
        f"Worker clips != exact 17 contract set: {worker['clipNames']}"
    )
    assert worker["demoSupportNodes"] == [] and worker["skinning"]["unweightedVerts"] == 0, (
        f"Worker DemoSupport or skinning defect: demo={worker['demoSupportNodes']}, skin={worker['skinning']}"
    )
    assert worker["cadence"]["offGridSamplers"] == [], (
        f"Worker non-30FPS off-grid samplers: {worker['cadence']['offGridSamplers']}"
    )

    assert robot["numErrors"] == 0 and robot["boneCount"] == 41, (
        f"Robot GLB invalid or wrong bone count: errors={robot['numErrors']}, bones={robot['boneCount']}"
    )
    assert set(robot["clipNames"]) == EXPECTED_ROBOT_14_CLIPS and robot["forbiddenClips"] == [], (
        f"Robot clips != exact 14 contract set or leaked Pick*/Inspect*: clips={robot['clipNames']}, forbidden={robot['forbiddenClips']}"
    )
    assert robot["demoSupportNodes"] == [] and robot["skinning"]["unweightedVerts"] == 0, (
        f"Robot DemoSupport or skinning defect: demo={robot['demoSupportNodes']}, skin={robot['skinning']}"
    )
    assert robot["cadence"]["offGridSamplers"] == [], (
        f"Robot non-30FPS off-grid samplers: {robot['cadence']['offGridSamplers']}"
    )

    stages = {st["id"]: st for st in v02_configs["workshop_chain"]["stages"]}
    for sid, st in sorted(stages.items()):
        roles = st["character_roles"]
        assert len(roles) >= 1, f"{sid}: unassigned stage (empty character_roles)"
        has_robot = "robot" in roles
        has_worker = any(r != "robot" for r in roles)
        all_stage_clips = list(st["operation_clips"]) + list(st["transfer_clips"])

        for clip_name in all_stage_clips:
            checked = False
            if has_worker and clip_name in worker["clipMetrics"]:
                cm = worker["clipMetrics"][clip_name]
                req = _min_clip_motion_threshold(clip_name, "worker")
                assert cm["duration"] >= 1.0 and cm["maxBodyDeltaM"] >= req and cm["nonFiniteMatrices"] == 0, (
                    f"{sid} worker clip {clip_name} degenerate: {cm} (req>={req}m)"
                )
                checked = True
            if has_robot and clip_name in robot["clipMetrics"]:
                cm = robot["clipMetrics"][clip_name]
                req = _min_clip_motion_threshold(clip_name, "robot")
                assert cm["duration"] >= 1.0 and cm["maxBodyDeltaM"] >= req and cm["nonFiniteMatrices"] == 0, (
                    f"{sid} robot clip {clip_name} degenerate: {cm} (req>={req}m)"
                )
                checked = True
            assert checked, f"{sid}: clip {clip_name!r} not resolved on assigned roles {roles}"


def test_t3_05_f2_x_f3_hall_envelope_overhead_cad_grid_plc_and_walkways(
    repo_root: Path,
    session_tmp_dir: Path,
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F2 × F3: 36x18x3.6m closed hall, zero physical overhead ceiling beam/truss/lamp meshes (with active lighting), clipped interior CAD grid, ROBOT_PLC_CABINET inside Zone 03, and unobstructed 5S walkway."""
    assert blender_probe.get("ok"), f"blender_probe failed: {blender_probe.get('error')}"
    assert node_probe.get("ok"), f"node_probe failed: {node_probe.get('error')}"
    gm = _audit_workstation_grounding_and_map_idempotency(repo_root, session_tmp_dir, node_probe=node_probe)
    assert gm.get("ok"), f"Three.js grounding/ceiling probe failed: {gm}"
    blend_ceiling = _audit_blend_ceiling_and_lights(repo_root, session_tmp_dir, blender_probe=blender_probe)
    assert blend_ceiling.get("ok"), f"Blender ceiling/lights probe failed: {blend_ceiling}"

    room = blender_probe["room"]
    assert room["dock_upper_walls"] == [], f"Legacy 6m dock upper walls present: {room['dock_upper_walls']}"
    assert abs(room["walls_aabb"]["max"][2] - 3.60) <= 0.01, (
        f"Hall wall height != 3.60m: {room['walls_aabb']}"
    )
    rays = room["parapet_raycast"]
    assert rays["uncovered_wall_rays"] == [] and rays["uncovered_lintel_rays"] == [], (
        f"Parapet or lintel gaps detected: {rays}"
    )
    assert rays["blocked_portal_rays"] == [], f"Dock portal rays blocked by wall mesh: {rays['blocked_portal_rays']}"

    ov = blender_probe["overhead"]
    assert ov["mesh_count"] == 0, (
        f"Physical 3D ceiling beam/truss/cable-tray/lamp meshes still present in .blend ENV_OVERHEAD: {ov}"
    )
    for ov_child_name, ov_child in (ov.get("children") or {}).items():
        assert ov_child["mesh_count"] == 0, (
            f"Physical overhead child {ov_child_name} still contains meshes in .blend: {ov_child}"
        )
    assert blend_ceiling["overhead_meshes"] == [], (
        f"Physical overhead beam/truss/cable-tray/lamp meshes remain in .blend: {blend_ceiling['overhead_meshes'][:12]}"
    )
    assert len(blend_ceiling["active_lights"]) >= 1, (
        f"Blender workshop scene lost active light sources when removing ceiling meshes: {blend_ceiling}"
    )

    spurs = blender_probe["spurs_and_zones"]
    env_audit = node_probe["environmentAudit"]
    assert env_audit["overheadBox"] is None, (
        f"Physical overhead geometry AABB still present in warehouse_environment.glb ENV_OVERHEAD: {env_audit['overheadBox']}"
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
    for label, grid_box, z_idx in (
        ("blender", spurs["cad_grid_aabb"], 1),
        ("glb", env_audit["cadGridAabb"], 2),
    ):
        if grid_box is not None:
            assert grid_box["min"][0] >= -18.02 and grid_box["max"][0] <= 18.02, (
                f"CAD grid ({label}) protrudes outside X=[-18, +18] walls: {grid_box}"
            )
            assert grid_box["min"][z_idx] >= -9.02 and grid_box["max"][z_idx] <= 9.02, (
                f"CAD grid ({label}) protrudes outside ±9.0m front/back walls: {grid_box}"
            )

    real_plc_border_overlaps = [
        ov_entry
        for ov_entry in spurs["plc_border_overlaps"]
        if "FILL" not in str(ov_entry.get("strip", "")).upper()
    ]
    assert real_plc_border_overlaps == [], (
        f"ROBOT_PLC_CABINET straddles painted floor zone border strip: {real_plc_border_overlaps}"
    )
    plc_aabb = blender_probe["equipment"]["ROBOT_PLC_CABINET"]["aabb"]
    z03_aabb = spurs["floor_zones"]["FLOOR_ZONE_03"]["aabb"]
    assert plc_aabb is not None and z03_aabb is not None
    assert (
        plc_aabb["min"][0] >= z03_aabb["min"][0]
        and plc_aabb["max"][0] <= z03_aabb["max"][0]
        and plc_aabb["min"][1] >= z03_aabb["min"][1]
        and plc_aabb["max"][1] <= z03_aabb["max"][1]
    ), f"ROBOT_PLC_CABINET {plc_aabb} not strictly inside FLOOR_ZONE_03 {z03_aabb}"

    bl_arrows = spurs["floor_arrows"]
    assert bl_arrows["off_walkway_arrows"] == [], (
        f"Off-walkway floor arrows/chevrons/dashed shafts remain in .blend (03:14:54Z/03:59:41Z): {bl_arrows}"
    )
    assert bl_arrows["under_table_arrows"] == [] and bl_arrows["misoriented_walkway_arrows"] == []
    env_arrows = env_audit["floorArrowsAudit"]
    assert env_arrows["offWalkwayArrows"] == [] and env_arrows["twistedArrowMeshes"] == [], env_arrows
    studio_arrows = (
        node_probe["studioReplayAudit"].get("floorArrowsAudit")
        or env_audit["studioPatchedFloorArrowsAudit"]
    )
    assert studio_arrows["offWalkwayArrows"] == [] and studio_arrows["duplicateWalkwayPairs"] == [], studio_arrows

    chevron_or_arrow_count = max(
        len(spurs["walkway_arrows"]),
        len(gm.get("walkwayChevronsOrArrows") or []),
    )
    assert chevron_or_arrow_count >= 3, (
        f"Expected >=3 walkway direction arrows/chevrons, got blend={spurs['walkway_arrows']} glb={gm.get('walkwayChevronsOrArrows')}"
    )
    assert blender_probe["bvh"]["walkway_hits"] == [] and env_audit["walkwayPrismHits"] == 0


def test_t3_06_f2_x_f9_native_36x18x36_glb_and_studio_map_idempotency(
    repo_root: Path,
    session_tmp_dir: Path,
    node_probe: dict[str, Any],
) -> None:
    """F2 × F4 × F9: Native 36x18x3.6m GLB + Studio map-*.js idempotency + stationary & cloned workstation floor-grounding (minY <= 0.005m, zero levitating tables)."""
    assert node_probe.get("ok"), f"node_probe failed: {node_probe.get('error')}"

    gm = _audit_workstation_grounding_and_map_idempotency(repo_root, session_tmp_dir, node_probe=node_probe)
    assert gm.get("ok"), f"Three.js workstation grounding & map idempotency probe failed: {gm}"

    for ws_name, ws_box in sorted(gm["standaloneWorkstations"].items()):
        assert ws_box["exists"] and ws_box["minY"] is not None, (
            f"Stationary workstation {ws_name} missing in standalone warehouse_environment.glb: {ws_box}"
        )
        assert -0.005 <= ws_box["minY"] <= 0.005, (
            f"Levitating or sunken workstation {ws_name} in standalone warehouse_environment.glb: minY={ws_box['minY']}m (must be within ±0.005m)"
        )

    for ws_name, ws_box in sorted(gm["studioStationary"].items()):
        assert ws_box["exists"] and ws_box["minY"] is not None, (
            f"Stationary workstation {ws_name} missing in combined Studio (env + layout): {ws_box}"
        )
        assert -0.005 <= ws_box["minY"] <= 0.005, (
            f"Levitating or sunken workstation {ws_name} in combined Studio (env + layout): minY={ws_box['minY']}m (must be within ±0.005m)"
        )

    assert len(gm["studioClonedBenches"]) >= 11
    for b_name, b_box in sorted(gm["studioClonedBenches"].items()):
        assert b_box["exists"] and b_box["minY"] is not None, f"Cloned Studio bench {b_name} empty: {b_box}"
        assert -0.005 <= b_box["minY"] <= 0.005, (
            f"Levitating or sunken cloned Studio bench {b_name}: minY={b_box['minY']}m (must be within ±0.005m)"
        )

    map_idem = gm["mapIdempotency"]
    for trial_key in ("shipped", "syntheticNative36m"):
        trial = map_idem[trial_key]
        assert trial["ok"], f"map-*.js trial {trial_key} threw error: {trial.get('error')}"
        p1, p2, p3, after_disp, after_re = (
            trial["pass1"],
            trial["pass2"],
            trial["pass3"],
            trial["afterDispose"],
            trial["afterReapply"],
        )
        for pass_name, pm in (("pass1", p1), ("pass2", p2), ("pass3", p3), ("afterReapply", after_re)):
            slab = pm["slabBox"]
            walls = pm["wallsBox"]
            assert slab is not None and walls is not None, f"{trial_key}.{pass_name} missing slab/walls"
            assert abs(slab["span"][0] - 36.0) <= 0.10 and abs(slab["span"][2] - 18.0) <= 0.10, (
                f"{trial_key}.{pass_name} double-scaled slab away from 36x18m: {slab}"
            )
            assert abs(walls["max"][1] - 3.60) <= 0.06, (
                f"{trial_key}.{pass_name} corrupted 3.6m wall height: {walls}"
            )
            assert abs(pm["dock01Pos"][0] - (-17.85)) <= 0.15 and abs(pm["dock01Pos"][2] - 5.15) <= 0.25, (
                f"{trial_key}.{pass_name} shifted DOCK_01: {pm['dock01Pos']}"
            )
            assert abs(pm["dock02Pos"][0] - 17.85) <= 0.15 and abs(pm["dock02Pos"][2] - 5.15) <= 0.25, (
                f"{trial_key}.{pass_name} shifted DOCK_02: {pm['dock02Pos']}"
            )
        assert p1["meshCount"] == p2["meshCount"] == p3["meshCount"] == after_re["meshCount"], (
            f"{trial_key} non-idempotent mesh counts across passes: {[p1['meshCount'], p2['meshCount'], p3['meshCount'], after_re['meshCount']]}"
        )
        assert after_disp["patchGroups"] == 0, (
            f"{trial_key} leaked MAP_* patchGroups after dispose(): {after_disp}"
        )

    replay_audit = node_probe["studioReplayAudit"]
    assert replay_audit["ok"], f"studioReplayAudit failed: {replay_audit.get('error')}"
    assert gm["studioVisibleOverheadMeshes"] == [], (
        f"Studio failed to hide/strip overhead beam/truss/lamp meshes: {gm['studioVisibleOverheadMeshes'][:12]}"
    )
    assert gm["studioLightConstructs"] >= 2
    if "ENV_OVERHEAD" in (node_probe["environmentAudit"].get("presentLayers") or []):
        assert replay_audit["overheadLayerToggleOk"], (
            "ENV_OVERHEAD container present but setLayer('ENV_OVERHEAD', true/false) API broke"
        )
    post_env = replay_audit["postMapEnvelope"]
    assert post_env is not None and abs(post_env["slabBox"]["span"][0] - 36.0) <= 0.10
    assert abs(post_env["wallsBox"]["max"][1] - 3.60) <= 0.06

    presets = replay_audit["cameraPresets"]
    for req_preset in ("overview", "blueprint", "rework", "robot", "qc", "break"):
        assert presets.get(req_preset, {}).get("supported"), (
            f"Camera preset {req_preset!r} not supported in Studio player: {presets.get(req_preset)}"
        )
    assert replay_audit["badCameraPreset"]["threw"], "Unknown camera preset did not throw Error"


def test_t3_07_f3_x_f8_physical_spurs_conveyors_and_subtick_parcel_transit(
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F3 × F8: Physical spurs/conveyors (INFEED_PREP_C01, CONVEYOR_01..10, QC_PORTAL, OUTFEED_C10_GOOD) carry live sub-tick parcels with spinning rollers."""
    assert blender_probe.get("ok"), f"blender_probe failed: {blender_probe.get('error')}"
    assert node_probe.get("ok"), f"node_probe failed: {node_probe.get('error')}"

    env_audit = node_probe["environmentAudit"]
    assert env_audit["rollerCount"] == 200 and env_audit["rollerHeightOffenders"] == 0, (
        f"200 rollers incomplete or misaligned at 0.860m: count={env_audit['rollerCount']}, offenders={env_audit['rollerHeightOffenders']}"
    )
    assert env_audit["transferPortHits"] == 0, (
        f"Conveyor Q2/Q3/Q4 transfer ports blocked by geometry: hits={env_audit['transferPortHits']}"
    )

    shifts = node_probe["studioReplayAudit"]["shifts"]
    for run_id in ("v1-manual-seed11", "v1-candidate-seed11"):
        sh = shifts.get(run_id) or {}
        assert sh.get("detailed"), f"Detailed replay telemetry missing for {run_id}: {sh}"
        tr = sh["transit"]
        assert tr["mainConveyorHits"] > 0 and tr["mainConveyorIncreasingXCount"] > 0, (
            f"{run_id}: zero sub-tick +X parcel progression along CONVEYOR_01..10: {tr}"
        )
        assert tr["spurHits"] > 0, f"{run_id}: zero parcel transit observed on queue spurs: {tr}"
        assert tr["qcPortalHits"] > 0, f"{run_id}: zero parcel transit observed through QC_PORTAL: {tr}"
        assert sh["stationaryRollerDelta"] <= 1e-5, (
            f"{run_id}: rollers spun while paused at t=0: {sh['stationaryRollerDelta']}"
        )
        assert sh["activeRollerMaxAngleRad"] > 0.01, (
            f"{run_id}: rollers remained static during active parcel transit: {sh['activeRollerMaxAngleRad']}"
        )
        assert sh["maxRollerCenterDriftM"] <= 0.002, (
            f"{run_id}: roller world centers drifted/tipped during rotation: {sh['maxRollerCenterDriftM']}m"
        )
        rw = sh.get("rework") or {}
        if rw.get("reworkStartedInRaw", 0) > 0:
            assert rw.get("reworkBenchWorkerSamples", 0) > 0 and rw.get("reworkBenchCartonSamples", 0) > 0, (
                f"{run_id}: Stage-3 rework worker/carton never physically operated at BENCH_REWORK: {rw}"
            )
        sc = sh.get("scrap") or {}
        if sc.get("scrapInRaw", 0) > 0:
            assert sc.get("scrapCarryOrTransitObserved", 0) > 0 and sc.get("scrapBenchOrBinVisibleAtEnd", 0) > 0, (
                f"{run_id}: scrap cartons vanished instead of routing onto BENCH_SCRAP / SCRAP_BIN: {sc}"
            )


def test_t3_08_f4_x_f7_robot_chamfer_bench_tops_and_grasp_tray_clearance(
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F4 × F7: VIS_Bench_top_robot_chamfer at y=0.860m off conveyor + <2.5cm L/R hand/gripper grasp contact and >=0.858m non-penetration across bare & +12mm tray modes."""
    assert blender_probe.get("ok"), f"blender_probe failed: {blender_probe.get('error')}"
    assert node_probe.get("ok"), f"node_probe failed: {node_probe.get('error')}"

    env_audit = node_probe["environmentAudit"]
    layout_audit = node_probe["layoutAudit"]
    assert not env_audit["chamferInEnv"], (
        "VIS_Bench_top_robot_chamfer leaked into warehouse_environment.glb conveyor origin"
    )
    r06 = env_audit["roller0601TopHit"]
    assert r06 is not None and "ROLLER_06_01" in r06["name"] and abs(r06["y"] - 0.860) <= 0.0025, (
        f"ROLLER_06_01 obstructed or wrong height at origin: {r06}"
    )

    chamfer = layout_audit["chamfer"]
    assert chamfer["exists"] and chamfer["parent"] == "VIS_ROBOT_PACK_TABLE", (
        f"VIS_Bench_top_robot_chamfer not parented to VIS_ROBOT_PACK_TABLE: {chamfer}"
    )
    assert abs(chamfer["aabb"]["max"][1] - 0.860) <= 0.0025, (
        f"VIS_Bench_top_robot_chamfer top Y != 0.860m: {chamfer['aabb']}"
    )

    grasp = node_probe["characterAudit"]["workstationGrasp"]
    expected_prefixes = (
        "stage1_worker_Prepare",
        "stage1_worker_Prepare_Oversize",
        "stage2_worker_Pick",
        "stage2_worker_Pick_Oversize",
        "stage3_worker_Pack",
        "stage3_worker_Pack_Oversize",
        "stage4_worker_Inspect",
        "stage4_worker_Inspect_Oversize",
        "stage3_robot_RobotPack",
        "stage3_robot_RobotPack_Oversize",
    )
    for prefix in expected_prefixes:
        for suffix in ("tray0", "tray12mm"):
            key = f"{prefix}_{suffix}"
            entry = grasp.get(key)
            assert entry is not None, f"Missing workstationGrasp entry {key}"
            assert entry["minDistL"] <= 0.025 and entry["minDistR"] <= 0.025, (
                f"{key}: hand/gripper grasp contact > 2.5cm: L={entry['minDistL']:.4f}m, R={entry['minDistR']:.4f}m"
            )
            assert entry["minOverBenchSocketY"] >= 0.858 and entry["minOverBenchPropY"] >= 0.858, (
                f"{key}: hand socket or prop penetrated below 0.858m worktop: {entry}"
            )

    for actor_key in ("worker", "robot"):
        for clip_name, cm in node_probe["characterAudit"][actor_key]["clipMetrics"].items():
            assert cm["spineOrderViolations"] == 0 and cm["maxConsecutiveStepDeg"] < 60.0, (
                f"{actor_key}.{clip_name} joint inversion / quaternion flip: {cm}"
            )


def test_t3_09_f5_x_f8_worker_30fps_handoff_clips_and_post_break_return(
    node_probe: dict[str, Any],
) -> None:
    """F5 × F8: Worker 30-FPS clips (Walk, CarryWalk, PickUp, PlaceDown, Break, Assist) play with 0 empty-hand prop leaks and <=2.50m post-break step jumps."""
    assert node_probe.get("ok"), f"node_probe failed: {node_probe.get('error')}"

    w_clips = node_probe["characterAudit"]["worker"]["clipMetrics"]
    for empty_clip in ("Idle", "Walk", "Reach", "Assist", "Break"):
        assert w_clips[empty_clip]["maxPropWorldScale"] < 1e-4, (
            f"Worker empty-hand clip {empty_clip} has visible floating carton scale: {w_clips[empty_clip]}"
        )
    for carry_clip in ("CarryIdle", "CarryWalk", "PickUp", "PlaceDown"):
        assert w_clips[carry_clip]["maxPropWorldScale"] > 0.5, (
            f"Worker carry/handoff clip {carry_clip} missing visible carton prop: {w_clips[carry_clip]}"
        )

    shifts = node_probe["studioReplayAudit"]["shifts"]
    for run_id in ("v1-manual-seed11", "v1-candidate-seed11"):
        sh = shifts[run_id]
        obs = set(sh["observedWorkerClips"])
        assert "CarryWalk" in obs, f"{run_id}: CarryWalk never played in live Studio replay: {sorted(obs)}"
        assert ("PickUp" in obs) or ("PlaceDown" in obs), (
            f"{run_id}: neither PickUp nor PlaceDown observed in live Studio replay: {sorted(obs)}"
        )
        assert "Break" in obs, f"{run_id}: Break clip never observed during mandatory shift break: {sorted(obs)}"
        assert sh["emptyHandPropLeakCount"] == 0, (
            f"{run_id}: {sh['emptyHandPropLeakCount']} empty-hand floating prop leaks observed in live replay"
        )
        brk = sh["breaks"]
        assert brk["count"] >= 4, f"{run_id}: expected >=4 mandatory worker breaks, got {brk['count']}"
        assert brk["maxBreakStepJumpM"] <= 2.50, (
            f"{run_id}: post-break worker teleport detected ({brk['maxBreakStepJumpM']:.3f}m > 2.50m at dt=0.10): {brk['maxBreakJumpInfo']}"
        )
        stranded = [c for c in brk["breakEndChecks"] if c["strandedInBreakArea"]]
        assert stranded == [], f"{run_id}: workers stranded in BREAK_AREA after break_end: {stranded}"


def test_t3_10_f5_x_f9_worker_operation_props_and_active_bench_sync(
    node_probe: dict[str, Any],
) -> None:
    """F5 × F9: Worker operation_prop tracks (OpenCarton flaps, PickingTote, Product, SealingTape) synchronize with Studio job progress while hiding duplicate static bench boxes."""
    assert node_probe.get("ok"), f"node_probe failed: {node_probe.get('error')}"

    worker = node_probe["characterAudit"]["worker"]
    assert worker["missingPropBones"] == [], f"Missing articulated prop_* bones: {worker['missingPropBones']}"
    assert len(worker["propMeshInfos"]) >= 6, f"Missing worker prop meshes: {worker['propMeshInfos']}"
    for pm in worker["propMeshInfos"]:
        assert pm["operation_prop"] is True and not pm["demo_only"], (
            f"Worker prop mesh {pm['name']} lacks operation_prop=true or has demo_only: {pm}"
        )
    assert worker["adapterAudit"]["ok"] and worker["adapterAudit"]["visibleOpPropsInPack"] >= 1, (
        f"visual-integration.js hid operational props in active pack state: {worker['adapterAudit']}"
    )

    cm = worker["clipMetrics"]
    for flap_clip in ("Prepare", "Prepare_Oversize", "Pack", "Pack_Oversize"):
        for fb in ("prop_flap_front", "prop_flap_back", "prop_flap_left", "prop_flap_right"):
            assert cm[flap_clip]["props"][fb]["rotDeltaRad"] > 0.15, (
                f"{flap_clip}.{fb} failed to fold/open (>0.15 rad): {cm[flap_clip]['props'][fb]}"
            )
    assert cm["Pick"]["props"]["prop_item"]["posDeltaM"] > 0.04
    assert cm["Pick"]["props"]["prop_tote"]["maxWorldScale"] > 0.5
    assert cm["Pack"]["props"]["prop_tape"]["posDeltaM"] > 0.015
    assert cm["Inspect"]["props"]["prop_closed"]["posDeltaM"] > 0.025 or (
        cm["Inspect"]["props"]["prop_shell"]["posDeltaM"] > 0.025
    )

    shifts = node_probe["studioReplayAudit"]["shifts"]
    for run_id in ("v1-manual-seed11", "v1-candidate-seed11"):
        sh = shifts[run_id]
        assert sh["activeWorkstationSamples"] > 0, f"{run_id}: zero active workstation samples captured"
        assert sh["activeBenchDuplicateCollisions"] == 0, (
            f"{run_id}: {sh['activeBenchDuplicateCollisions']} duplicate static VIS_order_* Z-fighting collisions on active benches"
        )
        prog = sh["opPhaseProgression"]
        advancing = [
            k
            for k, v in prog.items()
            if v.get("maxDiagSeen", 0.0) > 0.05
            and (v.get("maxPropPhaseDelta", 0.0) > 0.015 or v.get("mixerTimeSpan", 0.0) > 0.05)
        ]
        assert len(advancing) >= 3, (
            f"{run_id}: stage operation_prop animations did not advance over job phase [0..1]: {prog}"
        )


def test_t3_11_f6_x_f7_x_f8_robot_jam_assist_yaw_andon_and_live_replay(
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F6 × F7 × F8: Robot Jammed/Service clips, VIS_ROBOT_ASSIST yaw (+2.13196 rad toward [3.5, -2.39]), Andon isolation, and live helper Assist replay."""
    assert blender_probe.get("ok"), f"blender_probe failed: {blender_probe.get('error')}"
    assert node_probe.get("ok"), f"node_probe failed: {node_probe.get('error')}"

    robot = node_probe["characterAudit"]["robot"]
    for j_clip in ("Jammed", "Jammed_Oversize"):
        assert robot["clipMetrics"][j_clip]["maxBodyDeltaM"] >= 0.02, (
            f"Robot {j_clip} frozen (<0.02m): {robot['clipMetrics'][j_clip]}"
        )
    for s_clip in ("Service", "Service_Oversize"):
        assert robot["clipMetrics"][s_clip]["maxBodyDeltaM"] >= 0.10, (
            f"Robot {s_clip} frozen (<0.10m): {robot['clipMetrics'][s_clip]}"
        )
    phase_diffs = robot["adapterAudit"]["statePhaseDiffs"]
    for st_name in ("jammed", "service"):
        assert phase_diffs.get(st_name, 0.0) > 1e-3, (
            f"visual-integration.js froze robot {st_name} state at t=0: {phase_diffs}"
        )

    bl_assist = blender_probe["artifacts"]["VIS_ROBOT_ASSIST"]
    assert bl_assist["exists"] and bl_assist["cos_sim_to_robot_order"] >= 0.98, (
        f"Blender VIS_ROBOT_ASSIST not oriented toward [3.5, -2.39]: {bl_assist}"
    )
    assert blender_probe["bvh"]["helper_hits"] == [], (
        f"Helper standing cylinder at VIS_ROBOT_ASSIST collides with equipment: {blender_probe['bvh']['helper_hits']}"
    )

    st_assist = node_probe["layoutAudit"]["staticAssistInfo"]
    assert st_assist["nodeCosSim"] >= 0.98, f"visual_layout.glb VIS_ROBOT_ASSIST wrong yaw: {st_assist}"
    assert (st_assist["bindingsHelperCosSim"] or 0.0) >= 0.98, (
        f"visual_bindings.json helper_yaw_gltf_rad wrong yaw: {st_assist}"
    )
    assert (st_assist["spatialAssistCosSim"] or 0.0) >= 0.98, (
        f"spatial.js robotAssistYaw wrong yaw: {st_assist}"
    )

    andon = node_probe["environmentAudit"]["layerAndAndon"]
    assert andon["cloneIsolationOk"] and andon["dockSignalUnmutated"], (
        f"Andon tower material isolation or dock signal safety failed: {andon}"
    )

    shifts = node_probe["studioReplayAudit"]["shifts"]
    all_assist_samples: list[dict[str, Any]] = []
    observed_andon: set[str] = set()
    for run_id in ("v1-candidate-seed11", "v1-candidate-seed29", "test-jam-h32"):
        sh = shifts.get(run_id)
        if isinstance(sh, dict) and sh.get("detailed"):
            all_assist_samples.extend(sh.get("assistSamples") or [])
            observed_andon.update(sh.get("observedAndonStates") or [])

    assert len(all_assist_samples) >= 1, (
        "Zero live jam/assist samples captured across candidate shifts and test-jam-h32"
    )
    for sample in all_assist_samples:
        assert sample["cosSim"] >= 0.98 and sample["angleErrDeg"] <= 12.0, (
            f"Live helper facing away from jammed robot table: {sample}"
        )
        assert sample["distToAnchorM"] <= 0.15, f"Live helper displaced from VIS_ROBOT_ASSIST: {sample}"
        assert sample["helperClip"] == "Assist", f"Live helper not playing Assist clip: {sample}"
        assert (sample["robotMixerTime"] or 0.0) > 0.0, f"Robot clip frozen at mixerTime=0 during assist: {sample}"

    assert {"ANDON_GREEN", "ANDON_RED", "ANDON_AMBER"}.issubset(observed_andon) or (
        len(observed_andon) >= 2 and "ANDON_GREEN" in observed_andon
    ), f"Expected Andon state transitions during robot pack/jam/assist, got {sorted(observed_andon)}"


def test_t3_12_f7_x_f9_tray_plus_12mm_vs_bare_support_in_templates_and_replay(
    node_probe: dict[str, Any],
) -> None:
    """F7 × F9: Tray (+0.012m carton-above-tray offset) vs bare (0.860m) across visual_support.glb templates and live shift playback."""
    assert node_probe.get("ok"), f"node_probe failed: {node_probe.get('error')}"

    templates = node_probe["supportAudit"]["templates"]
    assert len(templates) == 14, f"Expected 14 visual_support.glb templates, got {sorted(templates)}"
    for tpl_name in ("VIS_order_tray", "VIS_order_regular", "VIS_order_fragile", "VIS_order_oversize"):
        tpl = templates.get(tpl_name) or {}
        assert tpl.get("exists"), f"Missing support template {tpl_name}"
        min_y = tpl["localAabb"]["min"][1]
        cx, cz = tpl["centerXZ"]
        assert abs(min_y) <= 0.0015, f"{tpl_name} not bottom-pivoted at y_min=0: {tpl['localAabb']}"
        assert abs(cx) <= 0.003 and abs(cz) <= 0.003, f"{tpl_name} XZ pivot off-center: {tpl['centerXZ']}"

    shifts = node_probe["studioReplayAudit"]["shifts"]
    for tray_run in ("v1-candidate-seed11", "v1-reference-seed11"):
        ta = shifts[tray_run]["trayAlignment"]
        assert ta["trayHeightChecked"] > 0 and ta["trayHeightErrors"] == 0, (
            f"{tray_run} (trays=True): +12mm tray alignment errors: {ta}"
        )

    manual_ta = shifts["v1-manual-seed11"]["trayAlignment"]
    assert manual_ta["untrayedHeightChecked"] > 0 and manual_ta["untrayedHeightErrors"] == 0, (
        f"v1-manual-seed11 (trays=False): bare order surface height errors: {manual_ta}"
    )


def test_t3_13_f2_x_f3_x_f10_eight_worker_parallel_benches_and_full_hall_astar(
    node_probe: dict[str, Any],
) -> None:
    """F2 × F3 × F10: Up to 8 workers (5 & 6 Stage-3 parallel slots) and full 36x18m [-17.6..+17.6, -8.6..+8.6] A* obstacle routing with 0 overlaps/hits."""
    assert node_probe.get("ok"), f"node_probe failed: {node_probe.get('error')}"

    spatial = node_probe["spatialAudit"]
    layouts = spatial["layouts"]
    for layout_name in (
        "stage3_5slots",
        "stage3_6slots",
        "stages124_3slots",
        "stage4_3slots",
        "singleWorkerMin",
    ):
        lay = layouts.get(layout_name) or {}
        assert lay.get("ok"), f"spatial.js layout {layout_name} failed: {lay}"
        assert lay["overlaps"] == [], (
            f"Layout {layout_name} has parallel bench overlaps with equipment/hall/walkway: {lay['overlaps']}"
        )
        assert lay["pathHits"] == 0, (
            f"Layout {layout_name} has {lay['pathHits']} walk path obstacle intersections"
        )
    assert layouts["singleWorkerMin"]["parallelBenchCount"] == 0
    assert layouts["stage3_6slots"]["parallelBenchCount"] >= 5

    routes = spatial["astarRoutes"]
    for route_name in (
        "dock01_to_dock02",
        "sw_to_ne_corners",
        "dock01_to_stage1",
        "boundary_176_86",
        "trivial_same_point",
    ):
        rt = routes.get(route_name) or {}
        assert rt.get("ok") and rt.get("inBounds") and rt.get("pointCount", 0) >= 2, (
            f"Full-hall A* route {route_name} failed or left 36x18m bounds: {rt}"
        )

    bp = spatial["breakPoints"]
    assert bp["count"] == 8 and bp["minPairDistM"] >= 0.60 and bp["reachableFromStagesCount"] == 32, (
        f"8 BREAK_POINTS distinctness or A* reachability from Stages 1..4 failed: {bp}"
    )


def test_t3_14_f4_x_f11_fifteen_validated_glbs_manifests_and_studio_scene_parity(
    v02_configs: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F4 × F11: All 15 validated GLBs match asset_stats_v02.json, asset_manifest.json, studio/asset-hashes.json, studio/public/scene/, and studio/dist/scene/."""
    assert node_probe.get("ok"), f"node_probe failed: {node_probe.get('error')}"
    for cfg_key in ("asset_stats_v02", "asset_manifest", "studio_asset_hashes"):
        assert v02_configs["files"][cfg_key]["ok"], (
            f"{cfg_key} missing or invalid: {v02_configs['files'][cfg_key]['error']}"
        )

    gltf_val = node_probe["gltfValidation"]
    stats_files = {
        entry["file"]: entry
        for entry in (v02_configs["asset_stats_v02"].get("files") or [])
        if isinstance(entry, dict) and "file" in entry
    }
    assert set(stats_files.keys()) == set(ALL_15_GLBS), (
        f"asset_stats_v02.json file set mismatch: {sorted(stats_files)}"
    )

    manifest_list = v02_configs["asset_manifest"]
    assert isinstance(manifest_list, list) and len(manifest_list) == 14, (
        f"asset_manifest.json must list all 14 module GLBs, got {type(manifest_list)}"
    )
    manifest_by_file = {entry.get("file"): entry for entry in manifest_list if isinstance(entry, dict)}
    expected_14_modules = {rel for rel in ALL_15_GLBS if rel.startswith("modules/")}
    assert set(manifest_by_file.keys()) == expected_14_modules, (
        f"asset_manifest.json modules mismatch: {sorted(manifest_by_file)}"
    )

    studio_hashes = v02_configs["studio_asset_hashes"]
    for rel in ALL_15_GLBS:
        g_info = gltf_val[rel]
        assert g_info["exists"] and g_info["numErrors"] == 0, f"GLB {rel} invalid: {g_info}"

        st_rec = stats_files[rel]
        assert st_rec["sha256"] == g_info["sha256"] and st_rec["bytes"] == g_info["bytes"], (
            f"asset_stats_v02.json stale for {rel}: stats=({st_rec['bytes']}, {st_rec['sha256'][:12]}) vs disk=({g_info['bytes']}, {g_info['sha256'][:12]})"
        )

        h_rec = _lookup_studio_hash_record(studio_hashes, rel)
        assert h_rec is not None, f"studio/asset-hashes.json missing entry for {rel}"
        assert h_rec.get("sha256") == g_info["sha256"] and h_rec.get("bytes") == g_info["bytes"], (
            f"studio/asset-hashes.json stale for {rel}: lock={h_rec} vs disk=({g_info['bytes']}, {g_info['sha256']})"
        )

    bundle = node_probe["studioBundleAudit"]
    pub_scene = bundle["publicScene"]
    assert pub_scene["exists"] and pub_scene["missingAssets"] == [] and pub_scene["parityMismatches"] == [], (
        f"studio/public/scene/ out of sync with 4_Horses_Environment_v02: {pub_scene}"
    )
    dist = bundle["dist"]
    assert dist["exists"] and dist["indexHtmlExists"] and len(dist["jsFiles"]) >= 1, (
        f"studio/dist/ production build missing or incomplete: {dist}"
    )
    dist_scene = dist["scene"]
    assert (
        dist_scene["exists"]
        and dist_scene["missingAssets"] == []
        and dist_scene["parityMismatches"] == []
    ), f"studio/dist/scene/ out of sync with 4_Horses_Environment_v02: {dist_scene}"


def test_t3_15_f5_x_f6_x_f11_x_f12_character_manifests_npm_test_and_preview_renders(
    v02_configs: dict[str, Any],
    node_probe: dict[str, Any],
    run_v02_npm_test_sandbox: Any,
) -> None:
    """F5 × F6 × F11 × F12: worker/robot manifests + asset_manifest + v02 npm test sandbox + character preview/contact-sheet PNG renders."""
    assert node_probe.get("ok"), f"node_probe failed: {node_probe.get('error')}"
    for key in ("worker_manifest", "robot_manifest", "asset_manifest", "v02_package_json"):
        assert v02_configs["files"][key]["ok"], f"{key} invalid: {v02_configs['files'][key]['error']}"

    w_man = v02_configs["worker_manifest"]
    r_man = v02_configs["robot_manifest"]
    w_aud = node_probe["characterAudit"]["worker"]
    r_aud = node_probe["characterAudit"]["robot"]

    assert w_man.get("bones") == 35 == w_aud["boneCount"], (
        f"worker_manifest bones={w_man.get('bones')} vs GLB={w_aud['boneCount']}"
    )
    w_man_clips = {c["name"] for c in (w_man.get("clips") or []) if isinstance(c, dict) and c.get("fps") == 30}
    assert w_man_clips == EXPECTED_WORKER_17_CLIPS, f"worker_manifest 30-FPS clips mismatch: {sorted(w_man_clips)}"

    assert r_man.get("bones") == 41 == r_aud["boneCount"], (
        f"robot_manifest bones={r_man.get('bones')} vs GLB={r_aud['boneCount']}"
    )
    r_man_clips = {c["name"] for c in (r_man.get("clips") or []) if isinstance(c, dict) and c.get("fps") == 30}
    assert r_man_clips == EXPECTED_ROBOT_14_CLIPS, f"robot_manifest 30-FPS clips mismatch: {sorted(r_man_clips)}"

    am_by_id = {e["id"]: e for e in v02_configs["asset_manifest"] if isinstance(e, dict) and "id" in e}
    assert am_by_id["warehouse_worker"].get("bones") == 35 and set(
        am_by_id["warehouse_worker"].get("clips") or []
    ) == EXPECTED_WORKER_17_CLIPS, f"asset_manifest.json warehouse_worker stale: {am_by_id['warehouse_worker']}"
    assert am_by_id["humanoid_robot"].get("bones") == 41 and set(
        am_by_id["humanoid_robot"].get("clips") or []
    ) == EXPECTED_ROBOT_14_CLIPS, f"asset_manifest.json humanoid_robot stale: {am_by_id['humanoid_robot']}"

    pkg_scripts = (v02_configs["v02_package_json"] or {}).get("scripts") or {}
    for req_script in ("test", "check", "validate"):
        assert isinstance(pkg_scripts.get(req_script), str) and pkg_scripts[req_script].strip(), (
            f"4_Horses_Environment_v02/package.json missing scripts.{req_script}: {pkg_scripts}"
        )

    sb_res = run_v02_npm_test_sandbox()
    assert sb_res["ok"], (
        f"v02 check_v02.mjs failed in sandbox (rc={sb_res['returncode']}): {sb_res['stderr'][-500:]}"
    )

    png_files = node_probe["pngAudit"]["files"]
    required_char_pngs = (
        "animations_frame_by_frame/prepare_preview.png",
        "animations_frame_by_frame/packing_preview.png",
        "animations_frame_by_frame/interaction_preview.png",
        "animations_frame_by_frame/contact_sheets/sheet_01_prepare_and_pick.png",
        "animations_frame_by_frame/contact_sheets/sheet_02_pack_worker_and_robot.png",
        "animations_frame_by_frame/contact_sheets/sheet_03_inspect_and_oversize.png",
        "animations_frame_by_frame/contact_sheets/sheet_04_assist_and_service.png",
        "animations_frame_by_frame/contact_sheets/sheet_05_jammed_break_offline.png",
        "animations_frame_by_frame/contact_sheets/sheet_06_empty_and_carry_props.png",
    )
    seen_hashes: set[str] = set()
    for rel_png in required_char_pngs:
        p_info = png_files.get(rel_png)
        assert p_info is not None and p_info.get("valid"), f"Character render PNG missing/corrupt: {rel_png} -> {p_info}"
        errs = validate_render_quality(_png_camel_to_snake(p_info), min_width=900, min_height=500)
        assert errs == [], f"{rel_png} failed render quality checks: {errs}"
        seen_hashes.add(p_info["sha256"])
    assert len(seen_hashes) == len(required_char_pngs), "Duplicate SHA-256 among character preview/sheet PNGs"


def test_t3_16_f1_x_f2_x_f12_centered_camera_chain_zones_and_presentation_pngs(
    v02_configs: dict[str, Any],
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F1 × F2 × F12: Centered CAMERA_OVERVIEW + 12 workshop chain zones backed by high-clarity environment_overview.png, detail_*.png, and multi-zone presentation PNGs."""
    assert v02_configs["files"]["workshop_chain"]["ok"]
    assert blender_probe.get("ok"), f"blender_probe failed: {blender_probe.get('error')}"
    assert node_probe.get("ok"), f"node_probe failed: {node_probe.get('error')}"

    cam = blender_probe["camera"]
    assert cam["exists"] and cam["docks"]["DOCK_01"]["in_frustum"] and cam["docks"]["DOCK_02"]["in_frustum"]
    assert not cam["docks"]["DOCK_01"]["occluded"] and not cam["docks"]["DOCK_02"]["occluded"]

    png_files = node_probe["pngAudit"]["files"]
    ov_png = png_files.get("environment_overview.png")
    assert ov_png is not None and ov_png.get("valid"), f"environment_overview.png missing or invalid: {ov_png}"
    ov_errs = validate_render_quality(_png_camel_to_snake(ov_png), is_overview=True)
    assert ov_errs == [], f"environment_overview.png failed F12 overview framing/quality gates: {ov_errs}"

    detail_hashes: set[str] = set()
    for det_name in ("detail_conveyor.png", "detail_packing.png", "detail_storage.png"):
        d_info = png_files.get(det_name)
        assert d_info is not None and d_info.get("valid"), f"{det_name} missing or invalid: {d_info}"
        d_errs = validate_render_quality(_png_camel_to_snake(d_info), min_width=1200, min_height=800)
        assert d_errs == [], f"{det_name} failed F12 detail quality gates: {d_errs}"
        detail_hashes.add(d_info["sha256"])
    assert len(detail_hashes) == 3, "Duplicate SHA-256 among detail_*.png renders"

    pres_pngs = {
        rel: info
        for rel, info in png_files.items()
        if rel.startswith("renders_presentation/") and info.get("valid")
    }
    assert len(pres_pngs) >= 8, (
        f"Expected >=8 valid multi-zone PNGs in 4_Horses_Environment_v02/renders_presentation/, found {len(pres_pngs)}: {sorted(pres_pngs)}"
    )
    pres_hashes: set[str] = set()
    for rel, info in sorted(pres_pngs.items()):
        p_errs = validate_render_quality(_png_camel_to_snake(info), min_width=1200, min_height=720)
        assert p_errs == [], f"{rel} failed F12 presentation render quality check: {p_errs}"
        pres_hashes.add(info["sha256"])
    assert len(pres_hashes) == len(pres_pngs), "Duplicate identical PNGs inside renders_presentation/"

    all_candidate_stems = [
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
        zone_key
        for zone_key, pat in STAGE_ZONE_PATTERNS.items()
        if not any(pat.search(rel) for rel in all_candidate_stems)
    ]
    assert missing_zones == [], (
        f"Presentation renders missing coverage for workshop chain zones {missing_zones}; available={all_candidate_stems}"
    )

    has_studio_renders = any(
        rel.startswith("artifacts/player-check/") or re.search(r"(studio|player|webgl)", rel, re.IGNORECASE)
        for rel in all_candidate_stems
    )
    assert has_studio_renders, (
        f"No live Chrome WebGL2 Studio presentation renders found alongside Blender renders: {all_candidate_stems}"
    )


def test_t3_17_f8_x_f10_x_f13_python_core_counters_studio_replay_and_queue_stacks(
    repo_root: Path,
    session_tmp_dir: Path,
    exported_pack_report: dict[str, Any],
    exported_pack_dir: Path,
    node_probe: dict[str, Any],
) -> None:
    """F8 × F10 × F13: Python core simulation counters match Studio ReplayModel across all 9 v1 benchmark shifts with manual-only rework and bounded/overflow queue stacks."""
    assert exported_pack_report["ok"] and exported_pack_report["all_9_v1_present"], (
        f"3D pack export failed: {exported_pack_report}"
    )
    assert node_probe.get("ok"), f"node_probe failed: {node_probe.get('error')}"

    replay_audit = node_probe["studioReplayAudit"]
    assert replay_audit["all9RequiredV1Present"], f"Studio probe missing required v1 runs: {replay_audit['v1RunIds']}"

    run_dirs = [exported_pack_dir / rid for rid in REQUIRED_9_V1_RUN_IDS]
    deep_mismatches = _verify_bundle_deep_counters(repo_root, session_tmp_dir, run_dirs)

    shifts = replay_audit["shifts"]
    for run_id in REQUIRED_9_V1_RUN_IDS:
        sh = shifts.get(run_id)
        assert sh is not None, f"Missing Studio replay shift report for {run_id}"
        mism = deep_mismatches[str(exported_pack_dir / run_id)]
        assert mism == [], (
            f"{run_id}: Studio ReplayModel end-of-shift counters mismatched Python manifest.raw on keys {mism}"
        )
        assert sh["boundaryClampingOk"], f"{run_id}: seekTo(0 / horizon+999) clamping failed"
        if sh.get("detailed"):
            assert sh["rework"]["robotAssignedAttempt1"] == 0, (
                f"{run_id}: illegal rework routing assigned attempt>=1 order to robot: {sh['rework']}"
            )
            assert sh["maxScrubDeterminismErrM"] == 0, (
                f"{run_id}: non-monotonic scrubbing produced non-deterministic world transforms"
            )

    stacks = node_probe["spatialAudit"]["stackSummary"]
    assert stacks["Q2_12"] == {"visibleCount": 12, "overflow": 0}
    assert stacks["Q3_10"] == {"visibleCount": 10, "overflow": 0}
    assert stacks["Q4_8"] == {"visibleCount": 8, "overflow": 0}
    assert stacks["Q1_25"] == {"visibleCount": 18, "overflow": 7}
    assert stacks["R_25"] == {"visibleCount": 18, "overflow": 7}
    assert stacks["good_20"] == {"visibleCount": 12, "overflow": 8}
    assert stacks["escaped_20"] == {"visibleCount": 12, "overflow": 8}
    assert stacks["scrap_15"] == {"visibleCount": 8, "overflow": 7}


def test_t3_18_f10_x_f11_x_f13_export_3d_pack_frozen_core_and_studio_readiness(
    repo_root: Path,
    exported_pack_report: dict[str, Any],
    exported_pack_dir: Path,
    core_pytest_report: dict[str, Any],
    v02_configs: dict[str, Any],
    node_probe: dict[str, Any],
) -> None:
    """F10 × F11 × F13: Frozen Python core (>=90 pytest, 0 git diff on frozen benchmark contracts) + export_3d_pack (>=9 runs, quarterly compatible) + dual-copy config & Studio bundle readiness."""
    from robotization_bench import reporting

    assert core_pytest_report["ok"], f"Frozen core pytest or git diff check failed: {core_pytest_report}"
    assert core_pytest_report["passed"] >= 90 and core_pytest_report["failed"] == 0 and core_pytest_report["errors"] == 0
    assert core_pytest_report["frozen_core_git_diff_rc"] == 0 and core_pytest_report["frozen_core_git_status"] == ""
    _check_frozen_benchmark_contracts_git_clean(repo_root)

    assert exported_pack_report["ok"] and exported_pack_report["total_runs"] >= 9
    assert exported_pack_report["all_9_v1_present"]
    index_runs = {r["id"]: r for r in exported_pack_report["index"]["runs"]}
    for run_id in REQUIRED_9_V1_RUN_IDS:
        manifest_rel = index_runs[run_id].get("manifest", f"{run_id}/manifest.json")
        run_dir = (exported_pack_dir / manifest_rel).parent
        reporting.validate_shift_bundle(run_dir)

    assert v02_configs["environment_config"] == v02_configs["config_environment"], (
        "4_Horses_Environment_v02/environment_config.json and config/environment.json drifted out of sync"
    )
    assert v02_configs["visual_bindings"] == v02_configs["config_visual_bindings"], (
        "4_Horses_Environment_v02/visual_bindings.json and config/visual_bindings.json drifted out of sync"
    )

    bundle = node_probe["studioBundleAudit"]
    assert bundle["publicScene"]["exists"] and bundle["publicScene"]["missingAssets"] == []
    assert bundle["dist"]["exists"] and bundle["dist"]["indexHtmlExists"]
    assert node_probe["spatialAudit"]["layouts"]["stage3_6slots"]["ok"]
