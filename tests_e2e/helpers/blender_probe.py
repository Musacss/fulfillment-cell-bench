"""Single-pass read-only headless Blender 5.2.3 LTS geometry, BVH & camera probe."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector
from mathutils.bvhtree import BVHTree

FLOOR_STANDING_ROOTS = (
    "CONVEYOR_01",
    "CONVEYOR_02",
    "CONVEYOR_03",
    "CONVEYOR_04",
    "CONVEYOR_05",
    "CONVEYOR_06",
    "CONVEYOR_07",
    "CONVEYOR_08",
    "CONVEYOR_09",
    "CONVEYOR_10",
    "BENCH_PICK",
    "BENCH_PACK",
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

ALLOWED_MOUNTED_PAIRS = frozenset(
    frozenset(pair)
    for pair in (
        ("CONVEYOR_01", "INLET_HOOD"),
        ("CONVEYOR_01", "INFEED_PREP_C01"),
        ("INLET_HOOD", "INFEED_PREP_C01"),
        ("VIS_STAGE_1_TABLE", "INFEED_PREP_C01"),
        ("PREP_TOOLING", "INFEED_PREP_C01"),
        ("PREP_TOOLING", "VIS_STAGE_1_TABLE"),
        ("CONVEYOR_10", "OUTLET_HOOD"),
        ("CONVEYOR_10", "OUTFEED_C10_GOOD"),
        ("OUTLET_HOOD", "OUTFEED_C10_GOOD"),
        ("DISPATCH_PALLET_00", "OUTFEED_C10_GOOD"),
        ("CONVEYOR_09", "QC_PORTAL"),
        ("CONVEYOR_02", "VIS_QUEUE_Q2_INFEED"),
        ("CONVEYOR_03", "VIS_QUEUE_Q2_INFEED"),
        ("CONVEYOR_03", "SPUR_PICK"),
        ("BENCH_PICK", "SPUR_PICK"),
        ("VIS_QUEUE_Q2_FRAME", "SPUR_PICK"),
        ("CONVEYOR_06", "VIS_QUEUE_Q3_INFEED"),
        ("CONVEYOR_05", "VIS_QUEUE_Q3_INFEED"),
        ("CONVEYOR_09", "VIS_QUEUE_Q4_INFEED"),
        ("QC_PORTAL", "VIS_QUEUE_Q4_INFEED"),
        ("VIS_QUEUE_Q2_FRAME", "VIS_QUEUE_Q2_INFEED"),
        ("VIS_QUEUE_Q3_FRAME", "VIS_QUEUE_Q3_INFEED"),
        ("VIS_QUEUE_Q4_FRAME", "VIS_QUEUE_Q4_INFEED"),
        ("QC_TABLE_TOOLING", "VIS_STAGE_4_TABLE"),
        ("QC_TABLE_TOOLING", "STAGE4_QC_TABLE"),
        ("STAGE4_QC_TABLE", "VIS_STAGE_4_TABLE"),
        ("STAGE1_PREP_TABLE", "VIS_STAGE_1_TABLE"),
        ("STAGE1_PREP_TABLE", "PREP_TOOLING"),
        ("STAGE1_PREP_TABLE", "INFEED_PREP_C01"),
        ("ROBOT_PACK_TABLE", "VIS_ROBOT_PACK_TABLE"),
        ("ROBOT_PACK_TABLE", "ROBOT_TABLE_REINFORCEMENT"),
        ("ROBOT_TABLE_REINFORCEMENT", "VIS_ROBOT_PACK_TABLE"),
        ("BENCH_PICK", "PICK_BENCH_TOTES"),
        ("BENCH_PACK", "PACK_PAPER_ROLL"),
        ("BENCH_REWORK", "REWORK_TOOLING"),
        ("BENCH_REWORK", "VIS_REWORK_BENCH"),
        ("BENCH_SCRAP", "SCRAP_TOOLING"),
        ("BENCH_SCRAP", "VIS_SCRAP_BENCH"),
        ("ROBOT_GUARD_REAR", "ROBOT_GUARD_RIGHT"),
        ("ROBOT_GUARD_REAR", "LIGHT_CURTAIN_LEFT"),
        ("ROBOT_GUARD_RIGHT", "LIGHT_CURTAIN_RIGHT"),
        ("ANDON_TOWER_ROBOT", "ROBOT_PLC_CABINET"),
        ("ANDON_TOWER_ROBOT", "ROBOT_GUARD_RIGHT"),
        ("ANDON_TOWER_ROBOT", "ROBOT_GUARD_REAR"),
        ("PAPER_STOCK_PALLET", "PAPER_STOCK_RACK"),
        ("VIS_QUEUE_Q2_FRAME", "VIS_QUEUE_Q2_LABEL_PLATE"),
        ("VIS_QUEUE_Q3_FRAME", "VIS_QUEUE_Q3_LABEL_PLATE"),
        ("VIS_QUEUE_Q4_FRAME", "VIS_QUEUE_Q4_LABEL_PLATE"),
        ("VIS_QUEUE_Q2_LABEL", "VIS_QUEUE_Q2_LABEL_PLATE"),
        ("VIS_QUEUE_Q3_LABEL", "VIS_QUEUE_Q3_LABEL_PLATE"),
        ("VIS_QUEUE_Q4_LABEL", "VIS_QUEUE_Q4_LABEL_PLATE"),
        ("VIS_QUEUE_Q2_FRAME", "VIS_QUEUE_Q2_LABEL"),
        ("VIS_QUEUE_Q3_FRAME", "VIS_QUEUE_Q3_LABEL"),
        ("VIS_QUEUE_Q4_FRAME", "VIS_QUEUE_Q4_LABEL"),
        ("DOCK_01", "WALL_SHELL"),
        ("DOCK_02", "WALL_SHELL"),
        ("SQDC_KPI_BOARD", "WALL_SHELL"),
        ("OVERHEAD_TRUSS_01", "WALL_SHELL"),
        ("OVERHEAD_TRUSS_02", "WALL_SHELL"),
        ("OVERHEAD_TRUSS_03", "WALL_SHELL"),
        ("OVERHEAD_CABLE_TRAY", "WALL_SHELL"),
        ("OVERHEAD_CABLE_TRAY", "OVERHEAD_TRUSS_01"),
        ("OVERHEAD_CABLE_TRAY", "OVERHEAD_TRUSS_02"),
        ("OVERHEAD_CABLE_TRAY", "OVERHEAD_TRUSS_03"),
        ("HIGH_BAY_LIGHTS", "OVERHEAD_TRUSS_01"),
        ("HIGH_BAY_LIGHTS", "OVERHEAD_TRUSS_02"),
        ("HIGH_BAY_LIGHTS", "OVERHEAD_TRUSS_03"),
        ("HIGH_BAY_LIGHTS", "OVERHEAD_CABLE_TRAY"),
        ("HIGH_BAY_LIGHTS", "WALL_SHELL"),
    )
)

ADDITIVE_BRIDGE_AND_SPUR_NAMES = frozenset(
    {
        "INFEED_PREP_C01",
        "OUTFEED_C10_GOOD",
        "QC_PORTAL",
        "STOPPER_GATE",
        "INLET_HOOD",
        "OUTLET_HOOD",
        "VIS_QUEUE_Q2_INFEED",
        "VIS_QUEUE_Q3_INFEED",
        "VIS_QUEUE_Q4_INFEED",
        "SPUR_ROBOT",
        "SPUR_PICK",
        "DIVERT_PICK",
        "SPUR_PACK",
        "DIVERT_PACK",
        "SPUR_QC",
        "DIVERT_QC",
    }
)

CONVEYOR_ASSEMBLY_NAMES = frozenset(f"CONVEYOR_{idx:02d}" for idx in range(1, 11))
QUEUE_FRAME_ASSEMBLY_NAMES = frozenset(
    {"VIS_QUEUE_Q2_FRAME", "VIS_QUEUE_Q3_FRAME", "VIS_QUEUE_Q4_FRAME"}
)
WORKSTATION_AND_TOOLING_NAMES = frozenset(
    {
        "VIS_STAGE_1_TABLE",
        "STAGE1_PREP_TABLE",
        "BENCH_PICK",
        "BENCH_PACK",
        "BENCH_REWORK",
        "BENCH_SCRAP",
        "VIS_ROBOT_PACK_TABLE",
        "ROBOT_PACK_TABLE",
        "VIS_STAGE_4_TABLE",
        "STAGE4_QC_TABLE",
        "SHIPPING_MANIFEST_PODIUM",
        "PREP_TOOLING",
        "PICK_BENCH_TOTES",
        "PACK_PAPER_ROLL",
        "QC_TABLE_TOOLING",
        "ROBOT_TABLE_REINFORCEMENT",
        "REWORK_TOOLING",
        "SCRAP_TOOLING",
    }
)
ROBOT_CELL_GUARD_NAMES = frozenset(
    {
        "ROBOT_GUARD_LEFT",
        "ROBOT_GUARD_RIGHT",
        "ROBOT_GUARD_REAR",
        "LIGHT_CURTAIN_LEFT",
        "LIGHT_CURTAIN_RIGHT",
    }
)


def _is_bridge_or_spur(name: str) -> bool:
    u = name.upper()
    return name in ADDITIVE_BRIDGE_AND_SPUR_NAMES or u.startswith(("SPUR_", "DIVERT_"))


def _is_peripheral_staging_assembly(name: str) -> bool:
    u = name.upper()
    return any(
        tok in u
        for tok in (
            "WEST_INBOUND",
            "INBOUND_STAGING",
            "INBOUND_BAY",
            "EAST_OUTBOUND",
            "OUTBOUND_MARSHAL",
            "OUTBOUND_STAGING",
            "SHIPPING_BAY",
            "NW_TOTE_RACK",
            "REAR_TOTE_RACK",
        )
    )


def is_allowed_mounted_pair(a_name: str, b_name: str) -> bool:
    """Return True iff (a_name, b_name) is an intentional structural/mounted joint."""
    pair_fs = frozenset((a_name, b_name))
    if pair_fs in ALLOWED_MOUNTED_PAIRS:
        return True

    # Never allow legacy collision offenders even if renamed/grouped near spurs
    forbidden = {"UTILITY_CABINET", "VIS_Bench_top_robot_chamfer"}
    if a_name in forbidden or b_name in forbidden:
        return False

    # Mounted tabletop tooling on BENCH_REWORK / BENCH_SCRAP
    for first, second in ((a_name, b_name), (b_name, a_name)):
        if first == "BENCH_REWORK" and ("REWORK" in second.upper() and second != "QUEUE_R_ROLLER_SECTION"):
            return True
        if first == "BENCH_SCRAP" and ("SCRAP" in second.upper() and second != "SCRAP_BIN"):
            return True

    # Dynamic conveyor spur / diverter / roller-bridge joint rule (M1/M3/M4 lock):
    # Intentional joints between any bridge/spur/diverter and adjacent conveyors,
    # queue frames, workstation tables/mounted tooling, or dispatch pallets.
    for first, second in ((a_name, b_name), (b_name, a_name)):
        if _is_bridge_or_spur(first):
            if (
                _is_bridge_or_spur(second)
                or second in CONVEYOR_ASSEMBLY_NAMES
                or second in QUEUE_FRAME_ASSEMBLY_NAMES
                or second in WORKSTATION_AND_TOOLING_NAMES
                or second.startswith("DISPATCH_PALLET_")
                or (first.upper().startswith("SPUR_ROBOT") and second in ROBOT_CELL_GUARD_NAMES)
            ):
                return True

        # Architectural column tags mounted on structural columns / wall shell
        if first.upper().startswith(("COLUMN_TAG", "COL_TAG")) and second == "WALL_SHELL":
            return True

    # Peripheral staging bays / NW rear tote rack internal load-on-deck/rack joints
    if _is_peripheral_staging_assembly(a_name) and _is_peripheral_staging_assembly(b_name):
        return True

    return False


def mesh_descendants(root_obj) -> list:
    if root_obj is None:
        return []
    objs = [root_obj] + list(root_obj.children_recursive)
    return [o for o in objs if o.type == "MESH" and o.data is not None and len(o.data.vertices) > 0]


def world_aabb(mesh_objs: list) -> dict | None:
    pts = []
    for m in mesh_objs:
        mw = m.matrix_world
        for v in m.data.vertices:
            pts.append(mw @ v.co)
    if not pts:
        return None
    lo = [min(p[i] for p in pts) for i in range(3)]
    hi = [max(p[i] for p in pts) for i in range(3)]
    return {"min": lo, "max": hi, "span": [hi[i] - lo[i] for i in range(3)]}


def count_triangles(mesh_objs: list) -> int:
    total = 0
    for ob in mesh_objs:
        ob.data.calc_loop_triangles()
        total += len(ob.data.loop_triangles)
    return total


def build_bvh_from_meshes(mesh_objs: list, z_min_clip: float | None = None):
    verts = []
    polys = []
    for ob in mesh_objs:
        ob.data.calc_loop_triangles()
        mw = ob.matrix_world
        wverts = [mw @ v.co for v in ob.data.vertices]
        off = len(verts)
        verts.extend(wverts)
        for t in ob.data.loop_triangles:
            i0, i1, i2 = t.vertices[0], t.vertices[1], t.vertices[2]
            if z_min_clip is not None:
                if max(wverts[i0].z, wverts[i1].z, wverts[i2].z) <= z_min_clip:
                    continue
            polys.append((i0 + off, i1 + off, i2 + off))
    if not polys:
        return None, None
    used_verts = [verts[idx] for tri in polys for idx in tri]
    aabb = (
        [min(v[i] for v in used_verts) for i in range(3)],
        [max(v[i] for v in used_verts) for i in range(3)],
    )
    return BVHTree.FromPolygons(verts, polys, all_triangles=True), aabb


def build_box_bvh(lo: tuple[float, float, float], hi: tuple[float, float, float]) -> BVHTree:
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    verts = [
        Vector((x0, y0, z0)),
        Vector((x1, y0, z0)),
        Vector((x1, y1, z0)),
        Vector((x0, y1, z0)),
        Vector((x0, y0, z1)),
        Vector((x1, y0, z1)),
        Vector((x1, y1, z1)),
        Vector((x0, y1, z1)),
    ]
    tris = [
        (0, 2, 1),
        (0, 3, 2),
        (4, 5, 6),
        (4, 6, 7),
        (0, 1, 5),
        (0, 5, 4),
        (2, 3, 7),
        (2, 7, 6),
        (0, 4, 7),
        (0, 7, 3),
        (1, 2, 6),
        (1, 6, 5),
    ]
    return BVHTree.FromPolygons(verts, tris, all_triangles=True)


def build_cylinder_bvh(cx: float, cy: float, radius: float, z0: float, z1: float, segs: int = 16) -> BVHTree:
    verts = [Vector((cx, cy, z0)), Vector((cx, cy, z1))]
    for i in range(segs):
        ang = 2.0 * math.pi * i / segs
        px = cx + radius * math.cos(ang)
        py = cy + radius * math.sin(ang)
        verts.append(Vector((px, py, z0)))
        verts.append(Vector((px, py, z1)))
    tris = []
    for i in range(segs):
        j = (i + 1) % segs
        b_i, t_i = 2 + 2 * i, 2 + 2 * i + 1
        b_j, t_j = 2 + 2 * j, 2 + 2 * j + 1
        tris.append((0, b_j, b_i))
        tris.append((1, t_i, t_j))
        tris.append((b_i, b_j, t_j))
        tris.append((b_i, t_j, t_i))
    return BVHTree.FromPolygons(verts, tris, all_triangles=True)


def has_collection_prefix(obj, prefixes: tuple[str, ...]) -> bool:
    for col in obj.users_collection:
        if any(col.name.startswith(p) for p in prefixes):
            return True
    return False


def ancestor_names(obj) -> list[str]:
    names = []
    cur = obj
    while cur is not None:
        names.append(cur.name)
        cur = cur.parent
    return names


def is_static_warehouse_mesh(obj) -> bool:
    if obj.type != "MESH" or obj.data is None or len(obj.data.vertices) == 0:
        return False
    cur = obj
    while cur is not None:
        if cur.get("worker_asset") or cur.get("robot_asset") or cur.type == "ARMATURE":
            return False
        if cur.name.startswith(
            ("DEMO_PARCEL_", "WORKER_", "FBF_", "ATTACH_WORKER_", "ATTACH_ROBOT_")
        ):
            return False
        cur = cur.parent
    if has_collection_prefix(obj, ("CHARACTERS", "INTEGRATION / Visual templates")):
        return False
    if any(m.type == "ARMATURE" for m in obj.modifiers):
        return False
    return True


def classify_assembly(obj, known_assemblies: set[str]) -> str | None:
    if not is_static_warehouse_mesh(obj):
        return None
    if obj.hide_viewport and not has_collection_prefix(obj, ("INTEGRATION / Stations",)):
        return None
    if obj.name.startswith(
        ("DEMO_PARCEL_", "VIS_QUEUE_Q2_OUTLINE_", "VIS_QUEUE_Q3_OUTLINE_", "VIS_QUEUE_Q4_OUTLINE_")
    ):
        return None

    chain = ancestor_names(obj)
    if "Raised concrete slab" in chain or obj.name.startswith("Lower reveal"):
        return "FLOOR_SLAB"

    if "ENV_FLOOR_AND_GRID" in chain:
        bb = world_aabb([obj])
        if bb and bb["max"][2] <= 0.020:
            return None
        return "FLOOR_SLAB"

    for anc in chain:
        if anc in known_assemblies:
            return anc
        base = anc.split(".")[0]
        if base in known_assemblies:
            return base

    if "ENV_WALLS_AND_DOCKS" in chain:
        if any(a.startswith("DOCK_01") for a in chain):
            return "DOCK_01"
        if any(a.startswith("DOCK_02") for a in chain):
            return "DOCK_02"
        if "PALLET_JACK" in chain:
            return "PALLET_JACK"
        return "WALL_SHELL"

    if "ENV_OVERHEAD" in chain:
        for t in ("OVERHEAD_TRUSS_01", "OVERHEAD_TRUSS_02", "OVERHEAD_TRUSS_03", "OVERHEAD_CABLE_TRAY"):
            if t in chain:
                return t
        return "HIGH_BAY_LIGHTS"

    top = chain[-2] if len(chain) >= 2 and chain[-1].startswith("ENV_") else chain[-1]
    return top.split(".")[0]


def unexclude_layer_collections(layer_col) -> None:
    if not layer_col.name.startswith("CHARACTERS"):
        layer_col.exclude = False
        layer_col.hide_viewport = False
    for child in layer_col.children:
        unexclude_layer_collections(child)


def extract_probe() -> dict:
    t0 = time.perf_counter()

    wh_scene = next(
        (s for s in bpy.data.scenes if s.objects.get("Raised concrete slab") is not None),
        bpy.context.scene,
    )
    scene_objs = wh_scene.objects

    # Temporarily unhide visual templates in-memory so bounds evaluate cleanly without saving
    templates_col = bpy.data.collections.get("INTEGRATION / Visual templates")
    if templates_col is not None:
        templates_col.hide_viewport = False
    wh_vl = wh_scene.view_layers[0]
    unexclude_layer_collections(wh_vl.layer_collection)
    wh_vl.update()

    all_object_names = sorted(o.name for o in scene_objs)

    # 1. Room, Walls, Columns, Docks & Parapet Raycasts
    slab_obj = scene_objs.get("Raised concrete slab")
    slab_aabb = world_aabb([slab_obj]) if slab_obj and slab_obj.type == "MESH" else None

    walls_root = scene_objs.get("ENV_WALLS_AND_DOCKS")
    wall_meshes = mesh_descendants(walls_root) if walls_root else []
    back_panels = [o for o in wall_meshes if o.name.startswith("Back wall panel")]
    columns = [o for o in wall_meshes if o.name.startswith("Structural column")]
    side_walls = [o for o in wall_meshes if o.name.startswith("Cutaway side wall")]
    dock_upper_walls = [
        o.name
        for o in (walls_root.children_recursive if walls_root else [])
        if o.name.startswith("Dock upper wall") and not o.hide_viewport
    ]

    side_wall_details = []
    for sw in side_walls:
        bb = world_aabb([sw])
        if bb:
            side_wall_details.append({"name": sw.name, "min": bb["min"], "max": bb["max"]})

    docks_info = {}
    leaf_descendants: set = set()
    jack_obj = scene_objs.get("PALLET_JACK")
    jack_descendants = set(mesh_descendants(jack_obj))

    for d_idx, d_name in enumerate(("DOCK_01", "DOCK_02"), start=1):
        d_obj = scene_objs.get(d_name)
        if d_obj is None:
            docks_info[d_name] = {"exists": False}
            continue
        d_children = [d_obj] + list(d_obj.children_recursive)
        lintels = [
            o for o in d_children if o.type == "MESH" and "lintel" in o.name.lower()
        ]
        leaf = scene_objs.get(f"{d_name}_SECTIONAL_LEAF")
        leaf_meshes = mesh_descendants(leaf)
        leaf_descendants.update(leaf_meshes)
        sig_red = scene_objs.get(f"{d_name}_SIGNAL_RED")
        sig_green = scene_objs.get(f"{d_name}_SIGNAL_GREEN")
        docks_info[d_name] = {
            "exists": True,
            "location": list(d_obj.matrix_world.translation),
            "aabb": world_aabb(mesh_descendants(d_obj)),
            "lintel_aabb": world_aabb(lintels),
            "leaf_exists": leaf is not None,
            "leaf_aabb": world_aabb(leaf_meshes),
            "signals_exist": bool(sig_red is not None and sig_green is not None),
        }

    structural_wall_meshes = [
        o
        for o in wall_meshes
        if o not in leaf_descendants and o not in jack_descendants and not o.hide_viewport
    ]
    wall_bvh, wall_bvh_aabb = build_bvh_from_meshes(structural_wall_meshes)

    uncovered_wall_rays = []
    uncovered_lintel_rays = []
    blocked_portal_rays = []
    outside_jamb_misses = []
    inside_portal_hits = []
    inside_lintel_misses = []

    if wall_bvh is not None:
        for side in (-1, 1):
            origin_x = side * 18.5
            ray_dir = Vector((-side, 0.0, 0.0))
            # Continuous side wall segments outside doorway [-6.95, -3.35]
            y_val = -8.8
            while y_val <= 8.8001:
                if not (-7.02 <= y_val <= -3.28):
                    for z_val in (0.2, 1.0, 2.0, 3.4):
                        hit, _, _, _ = wall_bvh.ray_cast(Vector((origin_x, y_val, z_val)), ray_dir, 1.4)
                        if hit is None:
                            uncovered_wall_rays.append([side, round(y_val, 3), z_val])
                y_val += 0.4

            # Overdoor lintel segment
            for y_val in (-6.8, -5.9, -5.15, -4.4, -3.5):
                hit, _, _, _ = wall_bvh.ray_cast(Vector((origin_x, y_val, 3.30)), ray_dir, 1.4)
                if hit is None:
                    uncovered_lintel_rays.append([side, y_val, 3.30])

            # Open portal segment behind sectional door leaf
            for y_val in (-5.8, -5.15, -4.5):
                hit, _, _, _ = wall_bvh.ray_cast(Vector((origin_x, y_val, 1.50)), ray_dir, 1.4)
                if hit is not None:
                    blocked_portal_rays.append([side, y_val, 1.50, list(hit)])

            # Tier 2 knife-edge boundary rays around jambs & lintel
            for y_jamb in (-7.05, -3.25):
                for z_val in (0.10, 1.50, 3.50):
                    hit, _, _, _ = wall_bvh.ray_cast(Vector((origin_x, y_jamb, z_val)), ray_dir, 1.4)
                    if hit is None:
                        outside_jamb_misses.append([side, y_jamb, z_val])
            for y_in in (-6.50, -5.15, -3.80):
                hit_open, _, _, _ = wall_bvh.ray_cast(Vector((origin_x, y_in, 2.75)), ray_dir, 1.4)
                if hit_open is not None:
                    inside_portal_hits.append([side, y_in, 2.75, list(hit_open)])
                for z_lin in (3.05, 3.55):
                    hit_lin, _, _, _ = wall_bvh.ray_cast(Vector((origin_x, y_in, z_lin)), ray_dir, 1.4)
                    if hit_lin is None:
                        inside_lintel_misses.append([side, y_in, z_lin])

    room_info = {
        "slab": slab_aabb,
        "walls_aabb": world_aabb([o for o in wall_meshes if not o.hide_viewport]),
        "back_wall_panels": {
            "count": len(back_panels),
            "aabb": world_aabb(back_panels),
        },
        "structural_columns": {
            "count": len(columns),
            "aabb": world_aabb(columns),
        },
        "cutaway_side_walls": {
            "count": len(side_walls),
            "west_count": sum(1 for d in side_wall_details if d["min"][0] < -17.5),
            "east_count": sum(1 for d in side_wall_details if d["max"][0] > 17.5),
            "panels": side_wall_details,
        },
        "dock_upper_walls": dock_upper_walls,
        "docks": docks_info,
        "parapet_raycast": {
            "uncovered_wall_rays": uncovered_wall_rays,
            "uncovered_lintel_rays": uncovered_lintel_rays,
            "blocked_portal_rays": blocked_portal_rays,
            "outside_jamb_misses": outside_jamb_misses,
            "inside_portal_hits": inside_portal_hits,
            "inside_lintel_misses": inside_lintel_misses,
        },
    }

    # 2. ENV_OVERHEAD & Unobstructed Ceiling / Active Lights Audit (02:42:13Z)
    ov_root = scene_objs.get("ENV_OVERHEAD")
    ov_meshes = mesh_descendants(ov_root) if ov_root else []
    ov_children = {}
    for cname in ("OVERHEAD_TRUSS_01", "OVERHEAD_TRUSS_02", "OVERHEAD_TRUSS_03", "OVERHEAD_CABLE_TRAY"):
        cobj = scene_objs.get(cname)
        cmeshes = mesh_descendants(cobj)
        ov_children[cname] = {
            "exists": cobj is not None,
            "mesh_count": len(cmeshes),
            "aabb": world_aabb(cmeshes),
        }
    forbidden_overhead_tokens = (
        "ENV_OVERHEAD",
        "OVERHEAD_TRUSS",
        "OVERHEAD_CABLE_TRAY",
        "HIGHBAY",
        "HIGH_BAY",
        "ENV_LIGHTING_RIG",
        "LIGHTING_RIG",
        "CEILING_BEAM",
        "HANGING_LAMP",
        "CABLE_TRAY",
        "CABLE TRAY",
        "RAFTER",
        "TRUSS",
    )
    forbidden_overhead_meshes = []
    for o in scene_objs:
        if o.type != "MESH" or o.data is None or len(o.data.vertices) == 0:
            continue
        joined_upper = " | ".join(ancestor_names(o)).upper()
        if any(tok in joined_upper for tok in forbidden_overhead_tokens):
            forbidden_overhead_meshes.append(o.name)

    active_lights = [
        {
            "name": o.name,
            "type": getattr(o.data, "type", None),
            "energy": float(getattr(o.data, "energy", 0.0)),
        }
        for o in scene_objs
        if o.type == "LIGHT"
        and not o.hide_render
        and float(getattr(o.data, "energy", 0.0)) > 0.0
    ]
    sun_area_lights = [l for l in active_lights if l["type"] in ("SUN", "AREA")]

    overhead_info = {
        "exists": ov_root is not None,
        "default_visible": bool(ov_root.get("default_visible", False)) if ov_root else None,
        "hide_render": bool(ov_root.hide_render) if ov_root else None,
        "mesh_count": len(ov_meshes),
        "aabb": world_aabb(ov_meshes),
        "children": ov_children,
        "forbidden_overhead_meshes": sorted(forbidden_overhead_meshes),
        "active_lights": active_lights,
        "active_light_count": len(active_lights),
        "sun_area_light_count": len(sun_area_lights),
    }

    # 3. Overview Camera & Occlusion Raycasts
    cam = scene_objs.get("CAMERA_OVERVIEW") or wh_scene.camera
    if cam is not None and cam.type == "CAMERA":
        cam_loc = cam.matrix_world.translation.copy()
        cam_fwd = (cam.matrix_world.to_quaternion() @ Vector((0.0, 0.0, -1.0))).normalized()
        t_hit = (0.85 - cam_loc.z) / cam_fwd.z if abs(cam_fwd.z) > 1e-6 else 0.0
        target_085 = cam_loc + t_hit * cam_fwd

        def check_camera_point(pt: Vector, exclude_objs: set) -> dict:
            ndc = world_to_camera_view(wh_scene, cam, pt)
            in_frustum = bool(0.01 <= ndc.x <= 0.99 and 0.01 <= ndc.y <= 0.99 and ndc.z > 0.0)
            occ_meshes = [
                o for o in wall_meshes if o not in exclude_objs and not o.hide_render
            ]
            occ_bvh, _ = build_bvh_from_meshes(occ_meshes)
            occluded = False
            hit_pt = None
            if occ_bvh is not None:
                if cam.data.type == "ORTHO":
                    r_orig = pt - cam_fwd * 60.0
                    r_dir = cam_fwd
                    r_dist = 59.85
                else:
                    vec = pt - cam_loc
                    r_orig = cam_loc
                    r_dir = vec.normalized()
                    r_dist = max(0.01, vec.length - 0.15)
                h_loc, _, _, _ = occ_bvh.ray_cast(r_orig, r_dir, r_dist)
                if h_loc is not None:
                    occluded = True
                    hit_pt = list(h_loc)
            return {
                "ndc": [float(ndc.x), float(ndc.y), float(ndc.z)],
                "in_frustum": in_frustum,
                "occluded": occluded,
                "hit": hit_pt,
            }

        d1_exc = set(mesh_descendants(scene_objs.get("DOCK_01")))
        d2_exc = set(mesh_descendants(scene_objs.get("DOCK_02")))
        cam_docks = {
            "DOCK_01": check_camera_point(Vector((-17.70, -5.15, 1.50)), d1_exc),
            "DOCK_02": check_camera_point(Vector((17.70, -5.15, 1.50)), d2_exc),
        }
        corners = {}
        for sx, lx in (("W", -17.8), ("E", 17.8)):
            for sy, ly in (("S", -8.8), ("N", 8.8)):
                ndc_c = world_to_camera_view(wh_scene, cam, Vector((lx, ly, 0.0)))
                corners[f"{sx}{sy}"] = {
                    "ndc": [float(ndc_c.x), float(ndc_c.y), float(ndc_c.z)],
                    "in_frustum": bool(0.0 <= ndc_c.x <= 1.0 and 0.0 <= ndc_c.y <= 1.0 and ndc_c.z > 0.0),
                }
        camera_info = {
            "exists": True,
            "name": cam.name,
            "camera_type": cam.data.type,
            "ortho_scale": float(cam.data.ortho_scale) if cam.data.type == "ORTHO" else None,
            "location": list(cam_loc),
            "forward": list(cam_fwd),
            "target_at_z085": list(target_085),
            "docks": cam_docks,
            "floor_corners": corners,
        }
    else:
        camera_info = {"exists": False}

    # 4. Equipment, Floor Grounding & 0.860m Supports
    equipment_info = {}
    extra_spur_names = (
        "INFEED_PREP_C01",
        "OUTFEED_C10_GOOD",
        "QC_TABLE_TOOLING",
        "STOPPER_GATE",
        "SPUR_ROBOT",
        "SPUR_PICK",
        "DIVERT_PICK",
        "SPUR_PACK",
        "DIVERT_PACK",
        "SPUR_QC",
        "DIVERT_QC",
        "BENCH_REWORK",
        "BENCH_SCRAP",
        "STAGE1_PREP_TABLE",
        "ROBOT_PACK_TABLE",
        "ROBOT_TABLE_REINFORCEMENT",
        "STAGE4_QC_TABLE",
        "SHIPPING_MANIFEST_PODIUM",
    )
    for rname in (*FLOOR_STANDING_ROOTS, *extra_spur_names):
        robj = scene_objs.get(rname)
        rmeshes = mesh_descendants(robj)
        equipment_info[rname] = {
            "exists": robj is not None,
            "mesh_count": len(rmeshes),
            "triangle_count": count_triangles(rmeshes),
            "aabb": world_aabb(rmeshes),
            "parent": robj.parent.name if (robj and robj.parent) else None,
            "collections": sorted(c.name for c in robj.users_collection) if robj else [],
        }

    chamfer_obj = scene_objs.get("VIS_Bench_top_robot_chamfer")
    chamfer_meshes = mesh_descendants(chamfer_obj)
    bench_rework_obj = scene_objs.get("BENCH_REWORK")
    bench_scrap_obj = scene_objs.get("BENCH_SCRAP")
    util_cab_obj = scene_objs.get("UTILITY_CABINET")
    qc_scale_obj = scene_objs.get("QC_SCALE_FLUSH")
    qc_surround_obj = scene_objs.get("QC worktop surround")
    assist_anchor_obj = scene_objs.get("VIS_ROBOT_ASSIST")
    robot_ord_anchor_obj = scene_objs.get("VIS_ROBOT_ORDER")
    if assist_anchor_obj is not None:
        aloc_b = assist_anchor_obj.matrix_world.translation
        aloc_g = [float(aloc_b.x), float(aloc_b.z), float(-aloc_b.y)]
        aquat_b = assist_anchor_obj.matrix_world.to_quaternion()
        fwd_b = aquat_b @ Vector((0.0, -1.0, 0.0))
        fx, fz = float(fwd_b.x), float(-fwd_b.y)
        flen = math.hypot(fx, fz) or 1.0
        fx, fz = fx / flen, fz / flen
        if robot_ord_anchor_obj is not None:
            rloc_b = robot_ord_anchor_obj.matrix_world.translation
            rloc_g = [float(rloc_b.x), float(rloc_b.z), float(-rloc_b.y)]
        else:
            rloc_g = [3.5, 0.86, -2.39]
        tx, tz = rloc_g[0] - aloc_g[0], rloc_g[2] - aloc_g[2]
        tlen = math.hypot(tx, tz) or 1.0
        assist_cos_sim = (fx * tx + fz * tz) / tlen
        assist_artifact = {
            "exists": True,
            "location_blender": [float(aloc_b.x), float(aloc_b.y), float(aloc_b.z)],
            "location_gltf": aloc_g,
            "target_robot_order_gltf": rloc_g,
            "forward_gltf_xz": [fx, fz],
            "yaw_gltf_rad": math.atan2(fx, fz),
            "cos_sim_to_robot_order": assist_cos_sim,
        }
    else:
        assist_artifact = {"exists": False}

    artifacts_info = {
        "VIS_Bench_top_robot_chamfer": {
            "exists": chamfer_obj is not None,
            "parent": chamfer_obj.parent.name if (chamfer_obj and chamfer_obj.parent) else None,
            "collections": sorted(c.name for c in chamfer_obj.users_collection) if chamfer_obj else [],
            "aabb": world_aabb(chamfer_meshes),
        },
        "VIS_ROBOT_ASSIST": assist_artifact,
        "BENCH_REWORK": {
            "exists": bench_rework_obj is not None,
            "mesh_count": len(mesh_descendants(bench_rework_obj)),
            "visible": bool(bench_rework_obj and not bench_rework_obj.hide_viewport),
            "aabb": world_aabb(mesh_descendants(bench_rework_obj)),
        },
        "BENCH_SCRAP": {
            "exists": bench_scrap_obj is not None,
            "mesh_count": len(mesh_descendants(bench_scrap_obj)),
            "visible": bool(bench_scrap_obj and not bench_scrap_obj.hide_viewport),
            "aabb": world_aabb(mesh_descendants(bench_scrap_obj)),
        },
        "UTILITY_CABINET": {
            "exists": util_cab_obj is not None,
            "mesh_count": len(mesh_descendants(util_cab_obj)),
            "visible": bool(util_cab_obj and not util_cab_obj.hide_viewport),
        },
        "QC_SCALE_FLUSH": {
            "exists": qc_scale_obj is not None,
            "aabb": world_aabb(mesh_descendants(qc_scale_obj)),
        },
        "QC_worktop_surround": {
            "exists": qc_surround_obj is not None,
            "aabb": world_aabb(mesh_descendants(qc_surround_obj)),
        },
    }

    # Main 200 rollers & buffer rollers
    main_roller_errs = []
    main_roller_count = 0
    for c_idx in range(1, 11):
        for r_idx in range(1, 21):
            r_name = f"ROLLER_{c_idx:02d}_{r_idx:02d}"
            ro = scene_objs.get(r_name)
            if ro is not None and ro.type == "MESH":
                main_roller_count += 1
                bb = world_aabb([ro])
                err = abs(bb["max"][2] - 0.860) if bb else 999.0
                if err > 0.002:
                    main_roller_errs.append({"name": r_name, "max_z": bb["max"][2] if bb else None})

    buffer_roller_objs = [
        o
        for o in scene_objs
        if o.type == "MESH"
        and (
            o.name in ("VIS_QUEUE_Q2_TOP", "VIS_QUEUE_Q3_TOP", "VIS_QUEUE_Q4_TOP")
            or o.name.startswith(("VIS_QUEUE_Q2_ROLLER_", "VIS_QUEUE_Q3_ROLLER_", "VIS_QUEUE_Q4_ROLLER_", "R_ACCUMULATION_ROLLER_"))
        )
    ]
    buffer_errs = []
    max_buf_err = 0.0
    for bo in buffer_roller_objs:
        bb = world_aabb([bo])
        if bb:
            err = abs(bb["max"][2] - 0.860)
            max_buf_err = max(max_buf_err, err)
            if err > 0.002:
                buffer_errs.append({"name": bo.name, "max_z": bb["max"][2]})

    # Workstation 0.860m support envelope audit
    station_pairs = (
        ("VIS_STAGE_1_ORDER", ("VIS_STAGE_1_TABLE",)),
        ("VIS_STAGE_2_ORDER", ("BENCH_PICK",)),
        ("VIS_STAGE_3_ORDER", ("BENCH_PACK",)),
        ("VIS_STAGE_4_ORDER", ("VIS_STAGE_4_TABLE", "QC_TABLE_TOOLING")),
        ("VIS_ROBOT_ORDER", ("VIS_ROBOT_PACK_TABLE",)),
    )
    workstation_tops = {}
    for ord_name, sup_roots in station_pairs:
        ord_obj = scene_objs.get(ord_name)
        sup_meshes = []
        for sr in sup_roots:
            sup_meshes.extend(mesh_descendants(scene_objs.get(sr)))
        top_meshes = []
        for sm in sup_meshes:
            bb = world_aabb([sm])
            if bb and abs(bb["max"][2] - 0.860) <= 0.0025:
                top_meshes.append((sm.name, bb))
        if ord_obj is not None and top_meshes:
            oloc = ord_obj.matrix_world.translation
            u_min_x = min(b["min"][0] for _, b in top_meshes)
            u_max_x = max(b["max"][0] for _, b in top_meshes)
            u_min_y = min(b["min"][1] for _, b in top_meshes)
            u_max_y = max(b["max"][1] for _, b in top_meshes)
            covers_tray = bool(
                u_min_x <= oloc.x - 0.268
                and u_max_x >= oloc.x + 0.268
                and u_min_y <= oloc.y - 0.198
                and u_max_y >= oloc.y + 0.198
            )
            workstation_tops[ord_name] = {
                "exists": True,
                "order_loc": list(oloc),
                "top_mesh_names": [n for n, _ in top_meshes],
                "top_envelope": {"min_x": u_min_x, "max_x": u_max_x, "min_y": u_min_y, "max_y": u_max_y},
                "covers_tray_footprint": covers_tray,
            }
        else:
            workstation_tops[ord_name] = {
                "exists": ord_obj is not None,
                "top_mesh_names": [n for n, _ in top_meshes],
                "covers_tray_footprint": False,
            }

    supports_info = {
        "main_rollers": {
            "count": main_roller_count,
            "offenders": main_roller_errs,
        },
        "buffer_rollers": {
            "count": len(buffer_roller_objs),
            "max_abs_err_from_086": max_buf_err,
            "offenders": buffer_errs,
        },
        "workstation_tops": workstation_tops,
    }

    # 5. Spurs, Rear Totes, Floor Transfer Lanes & Floor Zones (F3)
    pick_totes_root = scene_objs.get("PICK_BENCH_TOTES")
    rear_tote_candidates = []
    for o in scene_objs:
        if o.type == "MESH" and not o.hide_viewport:
            if not is_static_warehouse_mesh(o):
                continue
            bb = world_aabb([o])
            if bb and -6.8 <= bb["min"][0] and bb["max"][0] <= -4.0 and 2.0 <= bb["min"][1] and bb["max"][1] <= 4.6:
                if bb["max"][2] >= 0.86 and (
                    "TOTE" in o.name.upper()
                    or "SKU" in o.name.upper()
                    or (pick_totes_root and pick_totes_root in [o, *ancestor_objs(o)])
                ):
                    rear_tote_candidates.append({"name": o.name, "aabb": bb})
    if pick_totes_root is not None:
        pt_meshes = mesh_descendants(pick_totes_root)
    else:
        pt_meshes = []

    transfer_lanes = []
    for o in scene_objs:
        if o.hide_viewport or has_collection_prefix(o, ("INTEGRATION / Visual templates", "CHARACTERS")):
            continue
        uname = o.name.upper()
        if any(tok in uname for tok in ("TRANSFER", "LANE", "ROUTE")) and not uname.startswith("WALKWAY_"):
            ms = mesh_descendants(o) if o.type != "MESH" else [o]
            bb = world_aabb(ms)
            loc = [float(v) for v in o.matrix_world.translation]
            transfer_lanes.append({"name": o.name, "location": loc, "aabb": bb, "mesh_count": len(ms)})

    floor_zones = {}
    zone_strip_meshes: dict[str, list] = {}
    for zid in ("FLOOR_ZONE_01", "FLOOR_ZONE_02", "FLOOR_ZONE_03", "FLOOR_ZONE_04", "FLOOR_ZONE_R", "OUTCOME_FLOOR_ESCAPED"):
        z_objs = [
            o
            for o in scene_objs
            if o.type == "MESH" and not o.hide_viewport and (o.name == zid or o.name.split(".")[0] == zid or o.name.startswith(zid + "_"))
        ]
        # Exclude 3D equipment, keep floor decal strips
        z_strips = []
        z_caps = []
        for zo in z_objs:
            bb = world_aabb([zo])
            if bb and bb["max"][2] <= 0.03:
                z_strips.append(zo)
                if any(tok in zo.name.upper() for tok in ("LABEL", "CAPTION", "TEXT")):
                    z_caps.append(zo)
        zone_strip_meshes[zid] = z_strips
        floor_zones[zid] = {
            "mesh_count": len(z_strips),
            "aabb": world_aabb(z_strips),
            "caption_aabb": world_aabb(z_caps),
        }

    walkway_objs = [
        o
        for o in scene_objs
        if o.type == "MESH" and not o.hide_viewport and o.name.startswith("WALKWAY_")
    ]

    # 03:14:54Z Green-Walkway-Only Floor Arrow Audit across ALL visible floor-level (<0.08m) meshes
    table_footprints = []
    for tname in (
        "VIS_STAGE_1_TABLE",
        "STAGE1_PREP_TABLE",
        "BENCH_PICK",
        "BENCH_PACK",
        "BENCH_REWORK",
        "BENCH_SCRAP",
        "VIS_ROBOT_PACK_TABLE",
        "ROBOT_PACK_TABLE",
        "VIS_STAGE_4_TABLE",
        "STAGE4_QC_TABLE",
    ):
        tbb = (equipment_info.get(tname) or {}).get("aabb")
        if tbb:
            table_footprints.append((tname, tbb))

    walkway_arrows = []
    off_walkway_arrows = []
    under_table_arrows = []
    misoriented_walkway_arrows = []
    for o in scene_objs:
        if o.type != "MESH" or o.hide_viewport or o.data is None or len(o.data.vertices) == 0:
            continue
        if has_collection_prefix(o, ("CHARACTERS", "INTEGRATION / Visual templates")):
            continue
        joined_upper = " | ".join(ancestor_names(o)).upper()
        has_arrow_or_chevron = "ARROW" in joined_upper or "CHEVRON" in joined_upper
        has_flow_dash = any(
            tok in joined_upper
            for tok in (
                "DASH",
                "SPUR_GUIDE",
                "SPUR_TRANSFER_GUIDE",
                "TRANSFER_LANE",
                "RETURN_LANE",
                "SCRAP_TRANSFER",
                "FLOW_SHAFT",
                "FLOW_LINE",
            )
        ) and not any(
            ztok in joined_upper
            for ztok in ("FLOOR_ZONE_", "OUTCOME_FLOOR_", "MAP_FLOOR_ZONE_", "COLUMN_TAG_", "GRID")
        )
        if not (has_arrow_or_chevron or has_flow_dash):
            continue
        bb = world_aabb([o])
        if not bb or bb["max"][2] >= 0.08:
            continue
        in_green_walkway = (
            -17.85 <= bb["min"][0]
            and bb["max"][0] <= 17.85
            and -5.96 <= bb["min"][1]
            and bb["max"][1] <= -4.34
        )
        mw = o.matrix_world
        wvs = [mw @ v.co for v in o.data.vertices]
        max_x = max(v.x for v in wvs)
        min_x = min(v.x for v in wvs)
        span_x = max(1e-6, max_x - min_x)
        east_ys = [v.y for v in wvs if v.x >= max_x - 0.12 * span_x]
        west_ys = [v.y for v in wvs if v.x <= min_x + 0.35 * span_x]
        east_span = (max(east_ys) - min(east_ys)) if east_ys else 99.0
        west_span = (max(west_ys) - min(west_ys)) if west_ys else 0.0
        points_plus_x = bool(span_x >= 0.15 and east_span < west_span * 0.75)

        rec = {"name": o.name, "aabb": bb, "points_plus_x": points_plus_x}
        for tname, tbb in table_footprints:
            if (
                bb["max"][0] > tbb["min"][0] + 0.01
                and tbb["max"][0] > bb["min"][0] + 0.01
                and bb["max"][1] > tbb["min"][1] + 0.01
                and tbb["max"][1] > bb["min"][1] + 0.01
            ):
                under_table_arrows.append({"arrow": o.name, "table": tname})

        if in_green_walkway:
            walkway_arrows.append(rec)
            if not points_plus_x:
                misoriented_walkway_arrows.append(o.name)
        else:
            off_walkway_arrows.append(rec)

    # Check Q1 slots inside FLOOR_ZONE_01
    q1_slots = []
    for idx in range(6):
        so = scene_objs.get(f"VIS_QUEUE_Q1_SLOT_{idx:02d}")
        if so is not None:
            q1_slots.append(list(so.matrix_world.translation))

    # Check ROBOT_PLC_CABINET vs zone border strips (excluding interior _FILL decals)
    plc_aabb = equipment_info["ROBOT_PLC_CABINET"]["aabb"]
    plc_border_overlaps = []
    if plc_aabb:
        for zid in ("FLOOR_ZONE_01", "FLOOR_ZONE_02", "FLOOR_ZONE_03", "FLOOR_ZONE_04"):
            for zs in zone_strip_meshes.get(zid, []):
                if "_FILL" in zs.name.upper():
                    continue
                sbb = world_aabb([zs])
                if sbb:
                    if (
                        plc_aabb["max"][0] > sbb["min"][0] + 0.002
                        and sbb["max"][0] > plc_aabb["min"][0] + 0.002
                        and plc_aabb["max"][1] > sbb["min"][1] + 0.002
                        and sbb["max"][1] > plc_aabb["min"][1] + 0.002
                    ):
                        plc_border_overlaps.append({"zone": zid, "strip": zs.name, "strip_aabb": sbb})

    # Active order tray volume [0.54 x 0.40 x 0.32m] clearance against static tooling above z=0.865m
    tooling_roots = ("PREP_TOOLING", "PICK_BENCH_TOTES", "PACK_PAPER_ROLL", "QC_TABLE_TOOLING", "ROBOT_TABLE_REINFORCEMENT")
    tooling_meshes = []
    for tr in tooling_roots:
        tooling_meshes.extend(mesh_descendants(scene_objs.get(tr)))
    tooling_bvh, _ = build_bvh_from_meshes(tooling_meshes, z_min_clip=0.865)
    tray_volume_intrusions = {}
    for ord_name, _ in station_pairs:
        ord_obj = scene_objs.get(ord_name)
        if ord_obj is not None and tooling_bvh is not None:
            ol = ord_obj.matrix_world.translation
            t_bvh = build_box_bvh((ol.x - 0.27, ol.y - 0.20, 0.865), (ol.x + 0.27, ol.y + 0.20, 1.18))
            hits = tooling_bvh.overlap(t_bvh)
            tray_volume_intrusions[ord_name] = len(hits)
        else:
            tray_volume_intrusions[ord_name] = 0

    # CAD interior grid & peripheral staging bay summaries (M1/M3/M4 additive schema)
    cad_grid_meshes = [
        o
        for o in scene_objs
        if o.type == "MESH"
        and not o.hide_viewport
        and "ENV_FLOOR_AND_GRID" in ancestor_names(o)
        and "GRID" in o.name.upper()
    ]
    west_staging_objs = []
    east_staging_objs = []
    nw_rear_tote_rack_objs = []
    structural_skip = {"Raised concrete slab", "WALKWAY_GREEN_5S"}
    for o in scene_objs:
        if o.type != "MESH" or o.hide_viewport or o.name in structural_skip:
            continue
        anc = ancestor_names(o)
        if any(
            col in anc
            for col in ("ENV_WALLS_AND_DOCKS", "ENV_OVERHEAD", "ENV_FLOOR_AND_GRID", "CHARACTERS", "DOCK_01", "DOCK_02")
        ):
            continue
        bb = world_aabb([o])
        if not bb or bb["max"][2] <= 0.03:
            continue
        if bb["max"][0] <= -14.8:
            west_staging_objs.append(o.name)
        elif bb["min"][0] >= 12.4:
            east_staging_objs.append(o.name)
        if (
            any(tok in (o.name.upper() + " " + " ".join(a.upper() for a in anc)) for tok in ("NW_TOTE", "REAR_TOTE", "EMPTY_TOTE"))
            or (bb["max"][0] <= -11.5 and bb["min"][1] >= 5.2 and bb["max"][2] >= 0.5)
        ):
            nw_rear_tote_rack_objs.append(o.name)

    additive_spur_keys = (
        "INFEED_PREP_C01",
        "OUTFEED_C10_GOOD",
        "STOPPER_GATE",
        "SPUR_ROBOT",
        "SPUR_PICK",
        "DIVERT_PICK",
        "SPUR_PACK",
        "DIVERT_PACK",
        "SPUR_QC",
        "DIVERT_QC",
    )

    spurs_and_zones_info = {
        "INFEED_PREP_C01": equipment_info["INFEED_PREP_C01"],
        "OUTFEED_C10_GOOD": equipment_info["OUTFEED_C10_GOOD"],
        "additive_spurs": {k: equipment_info[k] for k in additive_spur_keys if k in equipment_info},
        "cad_grid_aabb": world_aabb(cad_grid_meshes),
        "peripheral_staging": {
            "west_staging_objects": sorted(west_staging_objs),
            "east_staging_objects": sorted(east_staging_objs),
            "nw_rear_tote_rack_objects": sorted(nw_rear_tote_rack_objs),
        },
        "pick_totes_tooling": {
            "root_exists": pick_totes_root is not None,
            "root_mesh_count": len(pt_meshes),
            "root_aabb": world_aabb(pt_meshes),
            "rear_tote_meshes": rear_tote_candidates,
        },
        "floor_transfer_lanes": transfer_lanes,
        "floor_zones": floor_zones,
        "walkway_aabb": world_aabb(walkway_objs),
        "floor_arrows": {
            "walkway_arrows": walkway_arrows,
            "off_walkway_arrows": off_walkway_arrows,
            "under_table_arrows": under_table_arrows,
            "misoriented_walkway_arrows": misoriented_walkway_arrows,
        },
        "walkway_arrows": walkway_arrows,
        "off_walkway_arrows": off_walkway_arrows,
        "under_table_arrows": under_table_arrows,
        "misoriented_walkway_arrows": misoriented_walkway_arrows,
        "q1_slot_positions_blender": q1_slots,
        "plc_border_overlaps": plc_border_overlaps,
        "tray_volume_intrusions": tray_volume_intrusions,
    }

    # 6. Static Assembly BVHTree Collision Matrix, Walkways & Mesh Integrity
    known_asm_names = set(FLOOR_STANDING_ROOTS) | {
        "BENCH_REWORK",
        "BENCH_SCRAP",
        "STAGE1_PREP_TABLE",
        "ROBOT_PACK_TABLE",
        "STAGE4_QC_TABLE",
        "SHIPPING_MANIFEST_PODIUM",
        "REWORK_TOOLING",
        "SCRAP_TOOLING",
        "INLET_HOOD",
        "OUTLET_HOOD",
        "INFEED_PREP_C01",
        "OUTFEED_C10_GOOD",
        "STOPPER_GATE",
        "SPUR_ROBOT",
        "SPUR_PICK",
        "DIVERT_PICK",
        "SPUR_PACK",
        "DIVERT_PACK",
        "SPUR_QC",
        "DIVERT_QC",
        "PICK_BENCH_TOTES",
        "PACK_PAPER_ROLL",
        "QC_TABLE_TOOLING",
        "ROBOT_TABLE_REINFORCEMENT",
        "ROBOT_GUARD_LEFT",
        "ROBOT_GUARD_REAR",
        "ROBOT_GUARD_RIGHT",
        "LIGHT_CURTAIN_LEFT",
        "LIGHT_CURTAIN_RIGHT",
        "ANDON_TOWER_ROBOT",
        "SQDC_KPI_BOARD",
        "OVERHEAD_TRUSS_01",
        "OVERHEAD_TRUSS_02",
        "OVERHEAD_TRUSS_03",
        "OVERHEAD_CABLE_TRAY",
        "PAPER_STOCK_PALLET",
        "PAPER_STOCK_RACK",
        "VIS_QUEUE_Q2_INFEED",
        "VIS_QUEUE_Q3_INFEED",
        "VIS_QUEUE_Q4_INFEED",
        "VIS_QUEUE_Q2_LABEL_PLATE",
        "VIS_QUEUE_Q3_LABEL_PLATE",
        "VIS_QUEUE_Q4_LABEL_PLATE",
        "VIS_QUEUE_Q2_LABEL",
        "VIS_QUEUE_Q3_LABEL",
        "VIS_QUEUE_Q4_LABEL",
    }

    assemblies: dict[str, list] = {}
    floor_decal_max_z = 0.0
    nan_inf_vertices = 0
    zero_area_triangles = 0

    for obj in scene_objs:
        if obj.type != "MESH" or obj.data is None or len(obj.data.vertices) == 0:
            continue
        # Check vertex finiteness & triangle areas on visible static / template meshes
        if not obj.hide_viewport and not has_collection_prefix(obj, ("CHARACTERS",)):
            mw = obj.matrix_world
            wvs = [mw @ v.co for v in obj.data.vertices]
            for wv in wvs:
                if not (math.isfinite(wv.x) and math.isfinite(wv.y) and math.isfinite(wv.z)):
                    nan_inf_vertices += 1
            obj.data.calc_loop_triangles()
            for tri in obj.data.loop_triangles:
                p0, p1, p2 = wvs[tri.vertices[0]], wvs[tri.vertices[1]], wvs[tri.vertices[2]]
                area = 0.5 * ((p1 - p0).cross(p2 - p0)).length
                if area < 1e-12:
                    zero_area_triangles += 1

        if "ENV_FLOOR_AND_GRID" in ancestor_names(obj) and not obj.hide_viewport:
            bb = world_aabb([obj])
            if bb and bb["max"][2] <= 0.025 and obj.name != "Raised concrete slab":
                floor_decal_max_z = max(floor_decal_max_z, bb["max"][2])

        asm = classify_assembly(obj, known_asm_names)
        if asm is not None:
            assemblies.setdefault(asm, []).append(obj)

    asm_bvhs: dict[str, tuple[BVHTree, tuple[list[float], list[float]]]] = {}
    for asm_name, m_list in sorted(assemblies.items()):
        bvh, aabb = build_bvh_from_meshes(m_list)
        if bvh is not None and aabb is not None:
            asm_bvhs[asm_name] = (bvh, aabb)

    asm_keys = sorted(asm_bvhs.keys())
    mounted_overlaps = []
    unintended_collisions = []
    margin = 0.002  # 2 mm resting-contact tolerance

    for i in range(len(asm_keys)):
        a_name = asm_keys[i]
        bvh_a, ba = asm_bvhs[a_name]
        for j in range(i + 1, len(asm_keys)):
            b_name = asm_keys[j]
            bvh_b, bb = asm_bvhs[b_name]
            # Broad-phase AABB with 2mm contact tolerance
            if not all(
                ba[1][k] > bb[0][k] + margin and bb[1][k] > ba[0][k] + margin for k in range(3)
            ):
                continue
            hits = bvh_a.overlap(bvh_b)
            if not hits:
                continue
            pair_fs = frozenset((a_name, b_name))
            # Resting contact against FLOOR_SLAB within 2mm above z=0 is already excluded by broad-phase
            entry = {"a": a_name, "b": b_name, "hit_count": len(hits)}
            if is_allowed_mounted_pair(a_name, b_name):
                mounted_overlaps.append(entry)
            else:
                unintended_collisions.append(entry)

    # Walkway prism (-17.7, -5.9, 0.025) .. (+17.7, -4.4, 2.20)
    walkway_box = build_box_bvh((-17.7, -5.9, 0.025), (17.7, -4.4, 2.20))
    walkway_hits = []
    for asm_name, (bvh_a, _) in asm_bvhs.items():
        if asm_name in ("FLOOR_SLAB", "DOCK_01", "DOCK_02"):
            continue
        if bvh_a.overlap(walkway_box):
            walkway_hits.append(asm_name)

    # Helper standing cylinder at VIS_ROBOT_ASSIST, r=0.275, z=[0.025, 1.80]
    assist_obj = scene_objs.get("VIS_ROBOT_ASSIST")
    ax = float(assist_obj.matrix_world.translation.x) if assist_obj else 2.8
    ay = float(assist_obj.matrix_world.translation.y) if assist_obj else 1.95
    helper_cyl = build_cylinder_bvh(ax, ay, 0.275, 0.025, 1.80)
    helper_hits = []
    for asm_name, (bvh_a, _) in asm_bvhs.items():
        if asm_name == "FLOOR_SLAB":
            continue
        if bvh_a.overlap(helper_cyl):
            helper_hits.append(asm_name)

    # Synthetic sanity check: verify BVH catches synthetic conveyor & rework bench interpenetrations
    syn_conveyor_box = build_box_bvh((-0.55, -0.50, 0.825), (0.55, 0.50, 0.860))
    syn_conveyor_hits = [
        k for k in ("CONVEYOR_05", "CONVEYOR_06") if k in asm_bvhs and asm_bvhs[k][0].overlap(syn_conveyor_box)
    ]
    syn_rework_box = build_box_bvh((3.9, -7.5, 0.02), (4.9, -6.9, 0.86))
    syn_rework_hits = (
        len(asm_bvhs["QUEUE_R_ROLLER_SECTION"][0].overlap(syn_rework_box))
        if "QUEUE_R_ROLLER_SECTION" in asm_bvhs
        else 0
    )

    bvh_info = {
        "assembly_count": len(asm_bvhs),
        "mounted_overlaps": mounted_overlaps,
        "unintended_collisions": unintended_collisions,
        "walkway_hits": walkway_hits,
        "floor_decal_max_z": floor_decal_max_z,
        "helper_hits": helper_hits,
        "mesh_integrity": {
            "nan_inf_vertices": nan_inf_vertices,
            "zero_area_triangles": zero_area_triangles,
        },
        "synthetic_sanity": {
            "conveyor_box_hits": syn_conveyor_hits,
            "rework_box_hit_count": syn_rework_hits,
        },
    }

    return {
        "exists": True,
        "ok": True,
        "blender_version": bpy.app.version_string,
        "elapsed_s": round(time.perf_counter() - t0, 4),
        "all_object_names": all_object_names,
        "all_collection_names": sorted(c.name for c in bpy.data.collections),
        "room": room_info,
        "overhead": overhead_info,
        "camera": camera_info,
        "equipment": equipment_info,
        "artifacts": artifacts_info,
        "supports": supports_info,
        "spurs_and_zones": spurs_and_zones_info,
        "bvh": bvh_info,
    }


def ancestor_objs(obj) -> list:
    res = []
    cur = obj.parent
    while cur is not None:
        res.append(cur)
        cur = cur.parent
    return res


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        payload = extract_probe()
    except Exception as exc:
        payload = {"exists": True, "ok": False, "error": f"{type(exc).__name__}: {exc}"}

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
