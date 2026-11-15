"""Comprehensive 3D BVH penetration, Z-contact/raycast, 1.0 m walkway BFS, and GLB audit.

Usage (stdout-only by default; writes report file ONLY if --report-json is passed):
  blender -b --factory-startup 4_Horses_Environment_v02/warehouse_environment.blend \
    --python 4_Horses_Environment_v02/scripts/check_scene_geometry.py -- \
    --output 4_Horses_Environment_v02
"""
import argparse
import collections
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


Z_TOL = 0.0020
POS_TOL = 1e-4

FLOOR_GROUNDED_UNITS = [
    *(f'CONVEYOR_{i:02d}' for i in range(1, 11)),
    'INFEED_PREP_C01',
    'OUTFEED_C10_GOOD',
    'SPUR_PICK',
    'SPUR_PACK',
    'SPUR_ROBOT',
    'SPUR_QC',
    'BENCH_PICK',
    'BENCH_PACK',
    'STAGE1_PREP_TABLE',
    'ROBOT_PACK_TABLE',
    'ROBOT_TABLE_REINFORCEMENT',
    'STAGE4_QC_TABLE',
    'QC_TABLE_TOOLING',
    'VIS_STAGE_1_TABLE',
    'VIS_STAGE_4_TABLE',
    'VIS_ROBOT_PACK_TABLE',
    'PREP_TOOLING',
    'VIS_QUEUE_Q2_FRAME',
    'VIS_QUEUE_Q2_INFEED',
    'VIS_QUEUE_Q3_FRAME',
    'VIS_QUEUE_Q3_INFEED',
    'VIS_QUEUE_Q4_FRAME',
    'VIS_QUEUE_Q4_INFEED',
    'QUEUE_R_ROLLER_SECTION',
    'Q1_PAIRED_PALLET_DECK',
    'DISPATCH_PALLET_00',
    'DISPATCH_PALLET_01',
    'SCRAP_BIN',
    'SUPPLY_TROLLEY',
    'RACK_01',
    'RACK_02',
    'RACK_03',
    'QC_PORTAL',
    'INLET_HOOD',
    'OUTLET_HOOD',
    'ROBOT_GUARD_REAR',
    'ROBOT_GUARD_RIGHT',
    'LIGHT_CURTAIN_LEFT',
    'LIGHT_CURTAIN_RIGHT',
    'ROBOT_PLC_CABINET',
    'BREAK_BENCH',
    'WATER_COOLER',
    'PAPER_STOCK_PALLET',
    'PALLET_JACK',
    'DOCK_01',
    'DOCK_02',
    'DOCK_01_BOLLARD_01',
    'DOCK_01_BOLLARD_02',
    'DOCK_02_BOLLARD_01',
    'DOCK_02_BOLLARD_02',
    'WEST_INBOUND_RACK_01',
    'WEST_INBOUND_RACK_02',
    *(f'INBOUND_PALLET_STACK_{i:02d}' for i in range(1, 5)),
    *(f'SHIPPING_PALLET_{i:02d}' for i in range(1, 7)),
    'PALLET_STRETCH_WRAPPER',
    'SHIPPING_MANIFEST_PODIUM',
    'NW_TOTE_RETURN_RACK',
    'NW_CHARGING_CABINET',
    'BENCH_REWORK',
    'BENCH_SCRAP',
]

STAGE_ACCESS_TARGETS = {
    'S0_DOCK01': (-16.00, -5.15),
    'S1_Q1_FRONT': (-10.40, 4.30),
    'S1_PREP_WORK': (-11.00, 0.50),
    'S1_INFEED_W': (-10.25, 0.25),
    'S2_Q2_SOUTH': (-6.46, -4.10),
    'S2_PICK_WORK': (-5.40, 1.55),
    'S3_Q3_SOUTH': (0.42, -3.70),
    'S3_PACK_MANUAL': (1.80, 1.55),
    'S3_ROBOT_ASSIST': (3.40, 1.55),
    'S3_PLC_FRONT': (4.745, 5.38),
    'S4_Q4_SOUTH': (6.44, -3.70),
    'S4_QC_WORK': (6.00, 1.55),
    'S5A_GOOD_WORK': (11.15, 2.20),
    'S5B_ESCAPED': (10.00, 5.45),
    'S5_DOCK02': (16.00, -5.15),
    'S5C_REWORK': (-0.60, -5.15),
    'S5C_BENCH_REWORK_WORK': (1.80, -5.35),
    'S5D_SCRAP': (8.60, -4.15),
    'S5D_BENCH_SCRAP_WORK': (8.65, -5.35),
    'S5E_BREAK': (8.35, 6.80),
}

RUNTIME_PARALLEL_BENCHES_BLENDER = [
    ('PARALLEL_STAGE_1_1', (-13.15, 1.13), (-12.05, 2.17)),
    ('PARALLEL_STAGE_1_2', (-11.55, 5.13), (-10.45, 6.17)),
    ('PARALLEL_STAGE_2_1', (-7.55, 3.43), (-6.45, 4.47)),
    ('PARALLEL_STAGE_3_1', (-0.35, 2.13), (0.75, 3.17)),
    ('PARALLEL_STAGE_4_1', (7.25, 2.13), (8.35, 3.17)),
]

LAYER_CONTAINERS = {
    'ENV_FLOOR_AND_GRID',
    'ENV_WALLS_AND_DOCKS',
    'ENV_WORKSTATIONS_DETAIL',
    'ENV_ROBOT_CELL',
    'ENV_BREAK_AREA',
    'ENV_OVERHEAD',
    'DISPATCH',
    'PROPS',
}

CONVEYOR_JUNCTIONS = {
    frozenset(('CONVEYOR_09', 'QC_PORTAL')),
    frozenset(('VIS_QUEUE_Q2_FRAME', 'VIS_QUEUE_Q2_INFEED')),
    frozenset(('VIS_QUEUE_Q3_FRAME', 'VIS_QUEUE_Q3_INFEED')),
    frozenset(('VIS_QUEUE_Q4_FRAME', 'VIS_QUEUE_Q4_INFEED')),
}

COMPOSITE_MOUNTS = {
    frozenset(('BENCH_PICK', 'ENV_WORKSTATIONS_DETAIL/PICK_BENCH_TOTES')),
    frozenset(('VIS_STAGE_1_TABLE', 'ENV_WORKSTATIONS_DETAIL/STAGE1_PREP_TABLE')),
    frozenset(('VIS_STAGE_4_TABLE', 'ENV_WORKSTATIONS_DETAIL/STAGE4_QC_TABLE')),
    frozenset(('VIS_STAGE_4_TABLE', 'ENV_WORKSTATIONS_DETAIL/QC_TABLE_TOOLING')),
    frozenset(('VIS_ROBOT_PACK_TABLE', 'ENV_ROBOT_CELL/ROBOT_PACK_TABLE')),
    frozenset(('VIS_ROBOT_PACK_TABLE', 'ENV_ROBOT_CELL/ROBOT_TABLE_REINFORCEMENT')),
    frozenset(('VIS_ROBOT_PACK_TABLE', 'ENV_WORKSTATIONS_DETAIL/ROBOT_TABLE_REINFORCEMENT')),
    frozenset(('ENV_ROBOT_CELL/ROBOT_PACK_TABLE', 'ENV_ROBOT_CELL/ROBOT_TABLE_REINFORCEMENT')),
    frozenset(('ENV_ROBOT_CELL/ROBOT_PLC_CABINET', 'ENV_ROBOT_CELL/ANDON_TOWER_ROBOT')),
    frozenset(('PROPS/PAPER_STOCK_PALLET', 'PROPS/PAPER_STOCK_RACK')),
}


def _ancestors(ob):
    chain = []
    cur = ob
    while cur is not None:
        chain.append(cur)
        cur = cur.parent
    chain.reverse()
    return chain


def _is_excluded_mesh(ob):
    if ob.type != 'MESH':
        return True
    chain = _ancestors(ob)
    for part in chain:
        if part.get('worker_asset') or part.get('robot_asset') or part.type == 'ARMATURE':
            return True
        if part.name.startswith(('DEMO_PARCEL_', 'WORKER_', 'ROBOT_Rig', 'ATTACH_WORKER_', 'ATTACH_ROBOT_')):
            return True
    if any(c.name.startswith(('CHARACTERS', 'INTEGRATION / Visual templates')) for c in ob.users_collection):
        return True
    return any(m.type == 'ARMATURE' for m in ob.modifiers)


def _logical_unit(ob):
    chain = _ancestors(ob)
    top = chain[0].name
    if top in LAYER_CONTAINERS and len(chain) >= 2:
        if top == 'ENV_BREAK_AREA' and chain[1].name == 'BREAK_AND_KPI_ZONE' and len(chain) >= 3:
            return f'{top}/{chain[2].name}'
        return f'{top}/{chain[1].name}'
    return top


def _world_tris_and_verts(meshes):
    verts = []
    tris = []
    for ob in meshes:
        mesh = ob.data
        mesh.calc_loop_triangles()
        mw = ob.matrix_world
        offset = len(verts)
        verts.extend(mw @ v.co for v in mesh.vertices)
        tris.extend(tuple(offset + idx for idx in tri.vertices) for tri in mesh.loop_triangles)
    return verts, tris


def _aabb_from_verts(verts):
    return (
        tuple(min(v[i] for v in verts) for i in range(3)),
        tuple(max(v[i] for v in verts) for i in range(3)),
    )


def _aabb_intersection(a, b):
    lo = tuple(max(a[0][i], b[0][i]) for i in range(3))
    hi = tuple(min(a[1][i], b[1][i]) for i in range(3))
    if all(hi[i] > lo[i] + 1e-8 for i in range(3)):
        return lo, hi
    return None


def _is_intentional_pair(u1, u2, inter):
    pair = frozenset((u1, u2))
    lo, hi = inter
    # Rule A1: Floor & plinth slab contacts (strictly near Z=0.000 m, never deep subterranean sinking)
    slab_units = {
        'ENV_FLOOR_AND_GRID/Raised concrete slab',
        'ENV_FLOOR_AND_GRID/Raised_concrete_slab',
        'ENV_FLOOR_AND_GRID/Lower reveal',
        'ENV_FLOOR_AND_GRID/Lower_reveal',
    }
    if (u1 in slab_units or u2 in slab_units) and lo[2] >= -0.0025 and hi[2] <= 0.0025:
        return True
    # Rule A2: 5S floor markings, matte zone fills & grid layers (strictly thin decal Z in [0.000, 0.0080] m)
    if u1.startswith('ENV_FLOOR_AND_GRID/') and u2.startswith('ENV_FLOOR_AND_GRID/') and hi[2] <= 0.0080:
        return True
    if ((u1.startswith('ENV_FLOOR_AND_GRID/') and u1 not in slab_units)
            or (u2.startswith('ENV_FLOOR_AND_GRID/') and u2 not in slab_units)):
        if lo[2] >= -1e-5 and hi[2] <= 0.0080:
            return True
    # Rule A3: Architectural shell joints (explicitly excluding PALLET_JACK!)
    if u1.startswith('ENV_WALLS_AND_DOCKS/') and u2.startswith('ENV_WALLS_AND_DOCKS/'):
        if 'PALLET_JACK' not in u1 and 'PALLET_JACK' not in u2:
            return True
    # Rule A4: Conveyor functional junctions (never QC_PORTAL <-> VIS_QUEUE_Q4_INFEED or INFEED <-> CONVEYOR)
    if pair in CONVEYOR_JUNCTIONS:
        return True
    # Rule A5: Composite workstation/cell/prop mounts (never ROBOT_GUARD_REAR <-> ROBOT_GUARD_RIGHT)
    if pair in COMPOSITE_MOUNTS:
        return True
    if (u1.startswith('PROPS/PAPER_STOCK_PALLET') and (u2.startswith('PROPS/Paper stock') or u2.startswith('PROPS/PROPS__'))) or (
        u2.startswith('PROPS/PAPER_STOCK_PALLET') and (u1.startswith('PROPS/Paper stock') or u1.startswith('PROPS/PROPS__'))
    ):
        return True
    if (u1.startswith('PROPS/Paper stock') or u1.startswith('PROPS/PROPS__')) and (
        u2.startswith('PROPS/Paper stock') or u2.startswith('PROPS/PROPS__')
    ):
        return True
    for q in ('Q2', 'Q3', 'Q4'):
        frame = f'VIS_QUEUE_{q}_FRAME'
        prefixes = (f'VIS_QUEUE_{q}_LABEL', f'VIS_QUEUE_{q}_OUTLINE_')
        if (u1 == frame and u2.startswith(prefixes)) or (u2 == frame and u1.startswith(prefixes)):
            return True
        if u1.startswith(f'VIS_QUEUE_{q}_LABEL') and u2.startswith(f'VIS_QUEUE_{q}_LABEL'):
            return True
    return False


def _clip_z(poly, z, keep_above):
    result = []
    if not poly:
        return result
    for a, b in zip(poly, poly[1:] + poly[:1]):
        ia = a.z >= z if keep_above else a.z <= z
        ib = b.z >= z if keep_above else b.z <= z
        if ia:
            result.append(a)
        if ia != ib:
            result.append(a + (b - a) * ((z - a.z) / (b.z - a.z)))
    return result


def _triangle_cylinder(tri, cx, cy, radius, zmin=0.025, zmax=2.000):
    poly = _clip_z(_clip_z(list(tri), zmin, True), zmax, False)
    if not poly:
        return False
    pts = [Vector((v.x - cx, v.y - cy)) for v in poly]
    rr = radius * radius
    if any(p.length_squared <= rr for p in pts):
        return True
    for a, b in zip(pts, pts[1:] + pts[:1]):
        edge = b - a
        t = max(0.0, min(1.0, -a.dot(edge) / edge.length_squared)) if edge.length_squared > 1e-20 else 0.0
        if (a + t * edge).length_squared <= rr:
            return True
    area = sum(a.x * b.y - a.y * b.x for a, b in zip(pts, pts[1:] + pts[:1]))
    if abs(area) < 1e-12:
        return False
    crosses = [(b.x - a.x) * (-a.y) - (b.y - a.y) * (-a.x) for a, b in zip(pts, pts[1:] + pts[:1])]
    return all(c >= -1e-10 for c in crosses) or all(c <= 1e-10 for c in crosses)


def _find_object_flexible(name):
    ob = bpy.data.objects.get(name)
    if ob is not None:
        return ob
    alt = name.replace(' ', '_')
    ob = bpy.data.objects.get(alt)
    if ob is not None:
        return ob
    for cand in bpy.data.objects:
        if cand.name.split('.')[0] in (name, alt):
            return cand
    return None


def _subtree_meshes(root):
    if root is None:
        return []
    return [o for o in [root] + list(root.children_recursive) if o.type == 'MESH' and not _is_excluded_mesh(o)]


def _box_bvh(lo, hi):
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    verts = [
        Vector((x0, y0, z0)), Vector((x1, y0, z0)), Vector((x1, y1, z0)), Vector((x0, y1, z0)),
        Vector((x0, y0, z1)), Vector((x1, y0, z1)), Vector((x1, y1, z1)), Vector((x0, y1, z1)),
    ]
    tris = [
        (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4), (2, 3, 7), (2, 7, 6),
        (0, 4, 7), (0, 7, 3), (1, 2, 6), (1, 6, 5),
    ]
    return BVHTree.FromPolygons(verts, tris, all_triangles=True, epsilon=0.0)


def _group_bvh_from_meshes(meshes):
    if not meshes:
        return None
    verts, tris = _world_tris_and_verts(meshes)
    if not verts or not tris:
        return None
    return BVHTree.FromPolygons(verts, tris, all_triangles=True, epsilon=0.0)


def run_suite_1_bvh():
    bpy.context.view_layer.update()
    all_meshes = [ob for ob in bpy.context.scene.objects if not _is_excluded_mesh(ob)]
    unit_meshes = collections.defaultdict(list)
    for ob in all_meshes:
        unit_meshes[_logical_unit(ob)].append(ob)

    unit_bvh = {}
    unit_aabb = {}
    for unit, meshes in unit_meshes.items():
        verts, tris = _world_tris_and_verts(meshes)
        if verts and tris:
            unit_bvh[unit] = BVHTree.FromPolygons(verts, tris, all_triangles=True, epsilon=0.0)
            unit_aabb[unit] = _aabb_from_verts(verts)

    units = sorted(unit_bvh)
    penetrations = []
    allowlisted_pairs = 0
    for i, u1 in enumerate(units):
        for u2 in units[i + 1:]:
            inter = _aabb_intersection(unit_aabb[u1], unit_aabb[u2])
            if inter is None:
                continue
            if _is_intentional_pair(u1, u2, inter):
                allowlisted_pairs += 1
                continue
            hits = unit_bvh[u1].overlap(unit_bvh[u2])
            if hits:
                dx, dy, dz = (inter[1][k] - inter[0][k] for k in range(3))
                if min(dx, dy, dz) > 0.0015:
                    penetrations.append({
                        'unit_a': u1,
                        'unit_b': u2,
                        'overlap_triangles': len(hits),
                        'aabb_intersection_min': [round(v, 5) for v in inter[0]],
                        'aabb_intersection_max': [round(v, 5) for v in inter[1]],
                    })

    # Explicit zero-triangle mesh-level checks (zero tolerance, no 1.5 mm skip)
    qc_q4_hits = 0
    if 'QC_PORTAL' in unit_bvh and 'VIS_QUEUE_Q4_INFEED' in unit_bvh:
        qc_q4_hits = len(unit_bvh['QC_PORTAL'].overlap(unit_bvh['VIS_QUEUE_Q4_INFEED']))
        if qc_q4_hits > 0:
            penetrations.append({'unit_a': 'QC_PORTAL', 'unit_b': 'VIS_QUEUE_Q4_INFEED', 'overlap_triangles': qc_q4_hits})

    # 1) 0 overlaps between any ROLLER_*/SPUR_*_ROLLER_*/SPUR_*_BALL_* and INLET_HOOD/OUTLET_HOOD/conveyor steel
    roller_meshes = [
        o for o in all_meshes
        if o.name.split('.')[0].startswith('ROLLER_')
        or ('_ROLLER_' in o.name.split('.')[0] and o.name.split('.')[0].startswith('SPUR_'))
        or ('_BALL_' in o.name.split('.')[0] and o.name.split('.')[0].startswith('SPUR_'))
    ]
    hood_and_conv_steel = []
    for cname in ('INLET_HOOD', 'OUTLET_HOOD', *(f'CONVEYOR_{i:02d}' for i in range(1, 11))):
        croot = _find_object_flexible(cname)
        for m in _subtree_meshes(croot):
            if not m.name.split('.')[0].startswith('ROLLER_'):
                hood_and_conv_steel.append(m)
    roller_bvh = _group_bvh_from_meshes(roller_meshes)
    hood_steel_bvh = _group_bvh_from_meshes(hood_and_conv_steel)
    roller_hood_steel_hits = len(roller_bvh.overlap(hood_steel_bvh)) if (roller_bvh and hood_steel_bvh) else 0
    if roller_hood_steel_hits > 0:
        penetrations.append({
            'unit_a': 'ROLLER_AND_SPUR_SURFACES',
            'unit_b': 'INLET_OUTLET_HOOD_AND_CONVEYOR_STEEL',
            'overlap_triangles': roller_hood_steel_hits,
        })

    # 2) 0 overlaps between VIS_QUEUE_Q{2,3,4}_INFEED* and CONVEYOR_*
    infeed_q_meshes = []
    for q in ('Q2', 'Q3', 'Q4'):
        infeed_q_meshes.extend(_subtree_meshes(_find_object_flexible(f'VIS_QUEUE_{q}_INFEED')))
    conv_all_meshes = []
    for i in range(1, 11):
        conv_all_meshes.extend(_subtree_meshes(_find_object_flexible(f'CONVEYOR_{i:02d}')))
    infeed_q_bvh = _group_bvh_from_meshes(infeed_q_meshes)
    conv_all_bvh = _group_bvh_from_meshes(conv_all_meshes)
    infeed_conv_hits = len(infeed_q_bvh.overlap(conv_all_bvh)) if (infeed_q_bvh and conv_all_bvh) else 0
    if infeed_conv_hits > 0:
        penetrations.append({
            'unit_a': 'VIS_QUEUE_Q2_Q3_Q4_INFEED',
            'unit_b': 'CONVEYOR_01_TO_10',
            'overlap_triangles': infeed_conv_hits,
        })

    # 3) 0 overlaps (including co-planar duplicate post/foot faces) between ROBOT_GUARD_REAR and ROBOT_GUARD_RIGHT
    rg_rear_bvh = _group_bvh_from_meshes(_subtree_meshes(_find_object_flexible('ROBOT_GUARD_REAR')))
    rg_right_bvh = _group_bvh_from_meshes(_subtree_meshes(_find_object_flexible('ROBOT_GUARD_RIGHT')))
    robot_guard_hits = len(rg_rear_bvh.overlap(rg_right_bvh)) if (rg_rear_bvh and rg_right_bvh) else 0
    if robot_guard_hits > 0:
        penetrations.append({
            'unit_a': 'ENV_ROBOT_CELL/ROBOT_GUARD_REAR',
            'unit_b': 'ENV_ROBOT_CELL/ROBOT_GUARD_RIGHT',
            'overlap_triangles': robot_guard_hits,
        })

    # Parcel aperture clearance along [-9.65, +9.35] x [-0.27, +0.27] x [0.862, 1.180]
    parcel_bvh = _box_bvh((-9.65, -0.27, 0.862), (9.35, 0.27, 1.180))
    aperture_blockers = []
    for name in ('INLET_HOOD', 'OUTLET_HOOD', 'QC_PORTAL'):
        root = _find_object_flexible(name)
        meshes = [m for m in _subtree_meshes(root) if not m.name.startswith('STOPPER_GATE')]
        if meshes:
            verts, tris = _world_tris_and_verts(meshes)
            bvh = BVHTree.FromPolygons(verts, tris, all_triangles=True, epsilon=0.0)
            hits = bvh.overlap(parcel_bvh)
            if hits:
                aperture_blockers.append({'unit': name, 'hit_triangles': len(hits)})

    return {
        'passed': (
            not penetrations
            and not aperture_blockers
            and qc_q4_hits == 0
            and roller_hood_steel_hits == 0
            and infeed_conv_hits == 0
            and robot_guard_hits == 0
        ),
        'logical_units_tested': len(units),
        'allowlisted_mating_pairs': allowlisted_pairs,
        'qc_portal_q4_infeed_overlap_tris': qc_q4_hits,
        'roller_hood_steel_overlap_tris': roller_hood_steel_hits,
        'infeed_conveyor_overlap_tris': infeed_conv_hits,
        'robot_guard_corner_overlap_tris': robot_guard_hits,
        'penetrations': penetrations,
        'parcel_aperture_blockers': aperture_blockers,
    }


def run_suite_2_contacts(is_reimported_glb=False):
    bpy.context.view_layer.update()
    slab = _find_object_flexible('Raised concrete slab')
    errors = []
    if slab is None or slab.type != 'MESH':
        return {'passed': False, 'errors': [{'reason': 'Raised concrete slab missing'}]}

    sverts, stris = _world_tris_and_verts([slab])
    slab_bvh = BVHTree.FromPolygons(sverts, stris, all_triangles=True, epsilon=0.0)

    grounded_checked = 0
    for name in FLOOR_GROUNDED_UNITS:
        root = _find_object_flexible(name)
        meshes = _subtree_meshes(root)
        if not meshes:
            errors.append({'unit': name, 'check': 'floor_grounded_exists', 'reason': 'missing_or_empty'})
            continue
        verts, _ = _world_tris_and_verts(meshes)
        lo, hi = _aabb_from_verts(verts)
        if abs(lo[2] - 0.0) > Z_TOL:
            errors.append({'unit': name, 'check': 'floor_min_z', 'actual_min_z': round(lo[2], 6)})
        foot_pts = [v for v in verts if v.z <= lo[2] + 0.004]
        cx = sum(v.x for v in foot_pts) / len(foot_pts)
        cy = sum(v.y for v in foot_pts) / len(foot_pts)
        loc, _, _, _ = slab_bvh.ray_cast(Vector((cx, cy, 0.05)), Vector((0.0, 0.0, -1.0)), 0.10)
        if loc is None or abs(loc.z - 0.0) > Z_TOL:
            v0 = min(foot_pts, key=lambda p: p.z)
            loc, _, _, _ = slab_bvh.ray_cast(Vector((v0.x, v0.y, 0.05)), Vector((0.0, 0.0, -1.0)), 0.10)
        if loc is None or abs(loc.z - 0.0) > Z_TOL:
            errors.append({'unit': name, 'check': 'slab_ray_cast', 'hit_z': round(loc.z, 6) if loc else None})
        grounded_checked += 1

    # Rollers, ball-transfer tops, and tabletops at 0.860 ± 0.002 m
    all_meshes = [o for o in bpy.context.scene.objects if not _is_excluded_mesh(o)]
    main_rollers = [o for o in all_meshes if o.name.split('.')[0].startswith('ROLLER_')]
    spur_prep = [o for o in all_meshes if o.name.split('.')[0].startswith('SPUR_PREP_ROLLER_')]
    spur_good = [o for o in all_meshes if o.name.split('.')[0].startswith('SPUR_GOOD_ROLLER_')]
    spur_robot = [o for o in all_meshes if o.name.split('.')[0].startswith('SPUR_ROBOT_ROLLER_')]
    spur_manual_rollers = [
        o for o in all_meshes
        if o.name.split('.')[0].startswith(('SPUR_PICK_ROLLER_', 'SPUR_PACK_ROLLER_', 'SPUR_QC_ROLLER_'))
    ]
    spur_manual_balls = [
        o for o in all_meshes
        if o.name.split('.')[0].startswith(('SPUR_PICK_BALL_', 'SPUR_PACK_BALL_', 'SPUR_QC_BALL_'))
    ]
    chute_wheels = [o for o in all_meshes if o.name.split('.')[0].startswith('SPUR_GOOD_WHEEL_')]
    r_rollers = [o for o in all_meshes if o.name.split('.')[0].startswith('R_ACCUMULATION_ROLLER_')]
    q_rollers = [
        o for o in all_meshes
        if o.name.split('.')[0].startswith('VIS_QUEUE_')
        and ('_ROLLER_' in o.name or o.name.split('.')[0].endswith('_TOP'))
    ]
    if len(main_rollers) != 200:
        errors.append({'check': 'main_roller_count_200', 'actual': len(main_rollers)})
    if len(spur_prep) != 21:
        errors.append({'check': 'spur_prep_roller_count_21', 'actual': len(spur_prep)})
    if len(spur_good) != 13:
        errors.append({'check': 'spur_good_roller_count_13', 'actual': len(spur_good)})
    if len(spur_robot) != 15:
        errors.append({'check': 'spur_robot_roller_count_15', 'actual': len(spur_robot)})
    if len(spur_manual_rollers) != 6:
        errors.append({'check': 'spur_manual_roller_count_6', 'actual': len(spur_manual_rollers)})
    if len(spur_manual_balls) != 27:
        errors.append({'check': 'spur_manual_ball_count_27', 'actual': len(spur_manual_balls)})
    if len(chute_wheels) != 27:
        errors.append({'check': 'chute_skate_wheel_count_27', 'actual': len(chute_wheels)})
    else:
        w_verts, _ = _world_tris_and_verts(chute_wheels)
        w_lo, w_hi = _aabb_from_verts(w_verts)
        if not (w_hi[2] >= 0.78 and w_lo[2] <= 0.30):
            errors.append({'check': 'chute_wheel_slope_envelope', 'min_z': round(w_lo[2], 4), 'max_z': round(w_hi[2], 4)})

    for ob in main_rollers + spur_prep + spur_good + spur_robot + spur_manual_rollers + spur_manual_balls + r_rollers + q_rollers:
        verts, _ = _world_tris_and_verts([ob])
        _, hi = _aabb_from_verts(verts)
        if abs(hi[2] - 0.860) > Z_TOL:
            errors.append({'roller': ob.name, 'check': 'roller_top_086', 'actual_max_z': round(hi[2], 6)})

    for top_unit in (
        'STAGE1_PREP_TABLE', 'VIS_STAGE_1_TABLE', 'BENCH_PICK', 'BENCH_PACK',
        'BENCH_REWORK', 'BENCH_SCRAP',
        'ROBOT_PACK_TABLE', 'VIS_ROBOT_PACK_TABLE', 'STAGE4_QC_TABLE', 'QC_TABLE_TOOLING',
    ):
        root = _find_object_flexible(top_unit)
        meshes = _subtree_meshes(root)
        has_086 = False
        for m in meshes:
            verts, _ = _world_tris_and_verts([m])
            _, hi = _aabb_from_verts(verts)
            if abs(hi[2] - 0.860) <= Z_TOL:
                has_086 = True
                break
        if not has_086:
            errors.append({'unit': top_unit, 'check': 'worktop_086_present'})

    # Stacked mounts: PICK_BENCH_TOTES on BENCH_PICK (0.860 m) & ANDON_TOWER_ROBOT on ROBOT_PLC_CABINET (1.280 m)
    for child_name, base_name, want_z in [
        ('PICK_BENCH_TOTES', 'BENCH_PICK', 0.860),
        ('ANDON_TOWER_ROBOT', 'ROBOT_PLC_CABINET', 1.280),
    ]:
        c_root = _find_object_flexible(child_name)
        b_root = _find_object_flexible(base_name)
        c_meshes = _subtree_meshes(c_root)
        b_meshes = _subtree_meshes(b_root)
        if not c_meshes or not b_meshes:
            errors.append({'check': 'stacked_mount_exists', 'child': child_name, 'base': base_name})
            continue
        c_verts, _ = _world_tris_and_verts(c_meshes)
        b_verts, b_tris = _world_tris_and_verts(b_meshes)
        c_lo, c_hi = _aabb_from_verts(c_verts)
        if abs(c_lo[2] - want_z) > Z_TOL:
            errors.append({'unit': child_name, 'check': 'mount_min_z', 'expected': want_z, 'actual': round(c_lo[2], 6)})
        b_bvh = BVHTree.FromPolygons(b_verts, b_tris, all_triangles=True, epsilon=0.0)
        cx = 0.5 * (c_lo[0] + c_hi[0])
        cy = 0.5 * (c_lo[1] + c_hi[1])
        loc, _, _, _ = b_bvh.ray_cast(Vector((cx, cy, want_z + 0.05)), Vector((0.0, 0.0, -1.0)), 0.10)
        if loc is None or abs(loc.z - want_z) > Z_TOL:
            errors.append({'unit': child_name, 'check': 'mount_ray_cast', 'hit_z': round(loc.z, 6) if loc else None})

    # Zone boundary containment & floor blueprint clipping checks
    for cab_name in ('ROBOT_PLC_CABINET', 'ANDON_TOWER_ROBOT'):
        root = _find_object_flexible(cab_name)
        verts, _ = _world_tris_and_verts(_subtree_meshes(root))
        lo, hi = _aabb_from_verts(verts)
        if not (lo[0] >= -3.55 and hi[0] <= 5.080 and lo[1] >= 0.65 and hi[1] <= 4.90):
            errors.append({'unit': cab_name, 'check': 'inside_FLOOR_ZONE_03', 'lo': lo[:2], 'hi': hi[:2]})

    floor_root = _find_object_flexible('ENV_FLOOR_AND_GRID')
    floor_meshes = _subtree_meshes(floor_root)
    if floor_meshes:
        f_verts, _ = _world_tris_and_verts(floor_meshes)
        f_lo, f_hi = _aabb_from_verts(f_verts)
        if not (f_lo[0] >= -18.005 and f_hi[0] <= 18.005 and f_lo[1] >= -9.005 and f_hi[1] <= 9.005):
            errors.append({'unit': 'ENV_FLOOR_AND_GRID', 'check': 'clipped_inside_hall_36x18', 'lo': f_lo[:2], 'hi': f_hi[:2]})
        marking_meshes = [
            m for m in floor_meshes
            if not m.name.startswith(('Raised concrete slab', 'Raised_concrete_slab', 'Lower reveal', 'Lower_reveal'))
        ]
        if marking_meshes:
            m_verts, _ = _world_tris_and_verts(marking_meshes)
            m_lo, m_hi = _aabb_from_verts(m_verts)
            if not (m_lo[0] >= -17.85 and m_hi[0] <= 17.85 and m_lo[1] >= -8.85 and m_hi[1] <= 8.85):
                errors.append({'unit': 'ENV_FLOOR_AND_GRID_MARKINGS', 'check': 'clipped_inside_walls', 'lo': m_lo[:2], 'hi': m_hi[:2]})

    fz1 = _find_object_flexible('FLOOR_ZONE_01')
    fz1_meshes = _subtree_meshes(fz1)
    if fz1_meshes:
        verts, _ = _world_tris_and_verts(fz1_meshes)
        lo, hi = _aabb_from_verts(verts)
        if not (lo[0] <= -13.34 and hi[0] >= -8.56 and lo[1] <= 0.66 and hi[1] >= 4.89):
            errors.append({'unit': 'FLOOR_ZONE_01', 'check': 'encloses_PARALLEL_STAGE_1_1', 'lo': lo[:2], 'hi': hi[:2]})
    elif not is_reimported_glb:
        errors.append({'unit': 'FLOOR_ZONE_01', 'check': 'exists_with_meshes'})

    # Unobstructed ceiling contract: ENV_OVERHEAD empty container (0 mesh descendants) & zero beam/truss/lamp meshes
    ov_root = _find_object_flexible('ENV_OVERHEAD')
    ov_meshes = _subtree_meshes(ov_root)
    if ov_root is None or ov_root.type != 'EMPTY':
        errors.append({'check': 'env_overhead_empty_container_exists', 'type': ov_root.type if ov_root else None})
    elif len(ov_meshes) != 0:
        errors.append({'check': 'env_overhead_zero_meshes', 'found': [m.name for m in ov_meshes]})
    forbidden_overhead = [
        o.name for o in bpy.data.objects
        if o.name.startswith((
            'OVERHEAD_TRUSS', 'OVERHEAD_CABLE_TRAY', 'HIGH_BAY_LED', 'HIGHBAY', 'ENV_LIGHTING_RIG', 'ENV_OVERHEAD__',
            'Truss longitudinal chord', 'Truss_longitudinal_chord', 'Truss diagonal web', 'Truss_diagonal_web',
            'High bay LED', 'High_bay_LED', 'High bay suspension', 'High_bay_suspension',
            'Cable tray ', 'Cable_tray_',
        ))
    ]
    if forbidden_overhead:
        errors.append({'check': 'zero_overhead_beam_lamp_meshes', 'found': forbidden_overhead})

    # Native scene checks: CAMERA_OVERVIEW PERSP + >=1 invisible Blender LIGHTs + 0/18 dock side-wall occlusions + 0 rear-wall 20 mm panel seams
    dock_occlusions = 0
    rear_wall_seam_misses = 0
    native_light_count = 0
    if not is_reimported_glb:
        native_lights = [o.name for o in bpy.data.objects if o.type == 'LIGHT']
        native_light_count = len(native_lights)
        if native_light_count < 1:
            errors.append({'check': 'native_lights_present', 'count': native_light_count})
        cam = bpy.data.objects.get('CAMERA_OVERVIEW')
        if cam is None or cam.type != 'CAMERA' or cam.data.type != 'PERSP':
            errors.append({'check': 'camera_overview_persp', 'actual_type': cam.data.type if (cam and cam.type == 'CAMERA') else None})
        else:
            walls_root = _find_object_flexible('ENV_WALLS_AND_DOCKS')
            side_wall_meshes = [m for m in _subtree_meshes(walls_root) if m.name.startswith('Cutaway side wall')]
            sw_bvh = _group_bvh_from_meshes(side_wall_meshes)
            cam_pos = cam.matrix_world.translation.copy()
            if sw_bvh is not None:
                for dock_x in (-17.85, 17.85):
                    for dy in (-6.35, -5.15, -3.95):
                        for dz in (0.60, 1.50, 2.40):
                            target = Vector((dock_x, dy, dz))
                            vec = target - cam_pos
                            hit_loc, _, _, _ = sw_bvh.ray_cast(cam_pos, vec.normalized(), vec.length - 0.02)
                            if hit_loc is not None:
                                dock_occlusions += 1
                if dock_occlusions > 0:
                    errors.append({'check': 'camera_overview_dock_occlusions_zero', 'occluded_rays': dock_occlusions})

            back_panels = [m for m in _subtree_meshes(walls_root) if m.name.startswith('Back wall panel')]
            bp_bvh = _group_bvh_from_meshes(back_panels)
            if bp_bvh is None:
                errors.append({'check': 'rear_wall_panels_present'})
            else:
                for jx in range(-16, 17, 4):
                    hit_loc, _, _, _ = bp_bvh.ray_cast(Vector((float(jx), 7.50, 1.50)), Vector((0.0, 1.0, 0.0)), 2.00)
                    if hit_loc is None:
                        rear_wall_seam_misses += 1
                if rear_wall_seam_misses > 0:
                    errors.append({'check': 'rear_wall_panel_seams_closed', 'seam_misses': rear_wall_seam_misses})

    return {
        'passed': not errors,
        'grounded_units_checked': grounded_checked,
        'main_rollers': len(main_rollers),
        'spur_prep_rollers': len(spur_prep),
        'spur_good_rollers': len(spur_good),
        'spur_robot_rollers': len(spur_robot),
        'spur_manual_rollers': len(spur_manual_rollers),
        'spur_manual_balls': len(spur_manual_balls),
        'chute_skate_wheels': len(chute_wheels),
        'overhead_meshes': len(ov_meshes),
        'native_lights': native_light_count,
        'camera_dock_occlusions': dock_occlusions,
        'rear_wall_seam_misses': rear_wall_seam_misses,
        'errors': errors,
    }


def _bfs_reachable_targets(free, xs, ys, step):
    nx, ny = len(xs), len(ys)
    start_ix = round((0.00 - (-17.40)) / step)
    start_iy = round((-5.15 - (-8.40)) / step)
    visited = set()
    if free[start_ix][start_iy]:
        dq = collections.deque([(start_ix, start_iy)])
        visited.add((start_ix, start_iy))
        while dq:
            cx, cy = dq.popleft()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    qx, qy = cx + dx, cy + dy
                    if not (0 <= qx < nx and 0 <= qy < ny) or (qx, qy) in visited or not free[qx][qy]:
                        continue
                    if dx != 0 and dy != 0 and not (free[cx + dx][cy] and free[cx][cy + dy]):
                        continue
                    visited.add((qx, qy))
                    dq.append((qx, qy))

    unreachable = []
    target_results = {}
    for stage_id, (tx, ty) in STAGE_ACCESS_TARGETS.items():
        tix = round((tx - (-17.40)) / step)
        tiy = round((ty - (-8.40)) / step)
        best = None
        for r in range(0, 2):
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    qx, qy = tix + dx, tiy + dy
                    if (qx, qy) in visited:
                        dist = math.hypot(xs[qx] - tx, ys[qy] - ty)
                        if best is None or dist < best[0]:
                            best = (dist, xs[qx], ys[qy])
            if best is not None:
                break
        if best is None or best[0] > 0.075:
            unreachable.append({'stage': stage_id, 'target_xy': [tx, ty]})
        else:
            target_results[stage_id] = {'target_xy': [tx, ty], 'nearest_free_xy': [best[1], best[2]], 'shift_m': round(best[0], 4)}
    return visited, unreachable, target_results


def run_suite_3_walkways():
    bpy.context.view_layer.update()
    slab = _find_object_flexible('Raised concrete slab')
    if slab is None:
        return {'passed': False, 'errors': ['Raised concrete slab missing']}
    sverts, stris = _world_tris_and_verts([slab])
    floor_bvh = BVHTree.FromPolygons(sverts, stris, all_triangles=True, epsilon=0.0)

    headroom_meshes = []
    obs_tris = []
    for ob in bpy.context.scene.objects:
        if _is_excluded_mesh(ob):
            continue
        verts, tris_idx = _world_tris_and_verts([ob])
        if not verts or not tris_idx:
            continue
        lo, hi = _aabb_from_verts(verts)
        if hi[2] >= 2.000:
            headroom_meshes.append(ob)
        if hi[2] < 0.025 or lo[2] > 2.000:
            continue
        for i0, i1, i2 in tris_idx:
            t0, t1, t2 = verts[i0], verts[i1], verts[i2]
            tz_lo = min(t0.z, t1.z, t2.z)
            tz_hi = max(t0.z, t1.z, t2.z)
            if tz_hi < 0.025 or tz_lo > 2.000:
                continue
            tx0 = min(t0.x, t1.x, t2.x)
            tx1 = max(t0.x, t1.x, t2.x)
            ty0 = min(t0.y, t1.y, t2.y)
            ty1 = max(t0.y, t1.y, t2.y)
            area2 = abs((t1.x - t0.x) * (t2.y - t0.y) - (t1.y - t0.y) * (t2.x - t0.x))
            obs_tris.append((area2, (t0, t1, t2), tx0, tx1, ty0, ty1))

    obs_tris.sort(key=lambda item: item[0], reverse=True)
    hr_verts, hr_tris = _world_tris_and_verts(headroom_meshes) if headroom_meshes else ([], [])
    headroom_bvh = BVHTree.FromPolygons(hr_verts, hr_tris, all_triangles=True, epsilon=0.0) if hr_tris else None

    step = 0.05
    xs = [round(-17.40 + i * step, 4) for i in range(int(round(34.80 / step)) + 1)]
    ys = [round(-8.40 + j * step, 4) for j in range(int(round(16.80 / step)) + 1)]
    nx, ny = len(xs), len(ys)
    radius = 0.4999
    blocked = [[False] * ny for _ in range(nx)]

    for _, tri, tx0, tx1, ty0, ty1 in obs_tris:
        ix0 = max(0, math.ceil((tx0 - radius - (-17.40)) / step - 1e-9))
        ix1 = min(nx - 1, math.floor((tx1 + radius - (-17.40)) / step + 1e-9))
        iy0 = max(0, math.ceil((ty0 - radius - (-8.40)) / step - 1e-9))
        iy1 = min(ny - 1, math.floor((ty1 + radius - (-8.40)) / step + 1e-9))
        for ix in range(ix0, ix1 + 1):
            x = xs[ix]
            row = blocked[ix]
            for iy in range(iy0, iy1 + 1):
                if not row[iy] and _triangle_cylinder(tri, x, ys[iy], radius, 0.025, 2.000):
                    row[iy] = True

    free = [[False] * ny for _ in range(nx)]
    for ix, x in enumerate(xs):
        row_blk = blocked[ix]
        row_free = free[ix]
        for iy, y in enumerate(ys):
            if row_blk[iy]:
                continue
            hit_floor, _, _, _ = floor_bvh.ray_cast(Vector((x, y, 0.20)), Vector((0.0, 0.0, -1.0)), 0.25)
            if hit_floor is None or abs(hit_floor.z) > 0.005:
                continue
            if headroom_bvh is not None:
                hit_ceil, _, _, _ = headroom_bvh.ray_cast(Vector((x, y, 0.05)), Vector((0.0, 0.0, 1.0)), 2.05)
                if hit_ceil is not None:
                    continue
            row_free[iy] = True

    visited, unreachable, target_results = _bfs_reachable_targets(free, xs, ys, step)

    # Second BFS pass WITH all 5 runtime parallel benches active
    free_with_parallel = [row[:] for row in free]
    for _, (bx0, by0), (bx1, by1) in RUNTIME_PARALLEL_BENCHES_BLENDER:
        ix0 = max(0, math.ceil((bx0 - radius - (-17.40)) / step - 1e-9))
        ix1 = min(nx - 1, math.floor((bx1 + radius - (-17.40)) / step + 1e-9))
        iy0 = max(0, math.ceil((by0 - radius - (-8.40)) / step - 1e-9))
        iy1 = min(ny - 1, math.floor((by1 + radius - (-8.40)) / step + 1e-9))
        for ix in range(ix0, ix1 + 1):
            x = xs[ix]
            dx = 0.0 if bx0 <= x <= bx1 else min(abs(x - bx0), abs(x - bx1))
            for iy in range(iy0, iy1 + 1):
                y = ys[iy]
                dy = 0.0 if by0 <= y <= by1 else min(abs(y - by0), abs(y - by1))
                if dx * dx + dy * dy <= radius * radius:
                    free_with_parallel[ix][iy] = False

    visited_par, unreachable_par, _ = _bfs_reachable_targets(free_with_parallel, xs, ys, step)

    # Explicit geometric bottleneck & handoff measurements
    def unit_bounds(name):
        verts, _ = _world_tris_and_verts(_subtree_meshes(_find_object_flexible(name)))
        return _aabb_from_verts(verts)

    west_bay_hi_x = max(
        unit_bounds(n)[1][0]
        for n in ('WEST_INBOUND_RACK_01', 'WEST_INBOUND_RACK_02', *(f'INBOUND_PALLET_STACK_{i:02d}' for i in range(1, 5)))
    )
    west_inbound_lane_m = -13.35 - west_bay_hi_x

    _, outfeed_hi = unit_bounds('OUTFEED_C10_GOOD')
    dp0_lo, dp0_hi = unit_bounds('DISPATCH_PALLET_00')
    chute_to_good_pallet_gap_m = dp0_lo[1] - outfeed_hi[1]

    east_bay_lo_x = min(
        unit_bounds(n)[0][0]
        for n in ('SHIPPING_MANIFEST_PODIUM', 'PALLET_STRETCH_WRAPPER', *(f'SHIPPING_PALLET_{i:02d}' for i in range(1, 7)))
    )
    east_bypass_m = east_bay_lo_x - dp0_hi[0]

    lc_lo, _ = unit_bounds('LIGHT_CURTAIN_LEFT')
    _, spur_pack_hi = unit_bounds('SPUR_PACK')
    light_curtain_to_spur_pack_m = math.hypot(max(0.0, lc_lo[0] - spur_pack_hi[0]), max(0.0, lc_lo[1] - spur_pack_hi[1]))

    manual_spur_hi_y = max(unit_bounds(n)[1][1] for n in ('SPUR_PICK', 'SPUR_PACK', 'SPUR_QC'))
    bench_front_lo_y = min(unit_bounds(n)[0][1] for n in ('BENCH_PICK', 'BENCH_PACK', 'VIS_STAGE_4_TABLE'))
    north_station_walkway_m = bench_front_lo_y - manual_spur_hi_y

    start_ix = round((0.00 - (-17.40)) / step)
    walkway_free_rows = sum(1 for iy, y in enumerate(ys) if -5.45 <= y <= -4.85 and (start_ix, iy) in visited)
    walkway_width_m = 1.00 + max(0, walkway_free_rows - 1) * step

    _, rack_hi = unit_bounds('RACK_03')
    rear_aisle_m = 8.550 - rack_hi[1]

    bottlenecks = {
        'west_inbound_lane_m': round(west_inbound_lane_m, 4),
        'east_dispatch_bypass_m': round(east_bypass_m, 4),
        'light_curtain_to_spur_pack_m': round(light_curtain_to_spur_pack_m, 4),
        'north_station_walkway_m': round(north_station_walkway_m, 4),
        'main_5s_walkway_m': round(walkway_width_m, 4),
        'rear_rack_aisle_m': round(rear_aisle_m, 4),
    }
    min_required = {
        'west_inbound_lane_m': 1.50,
        'east_dispatch_bypass_m': 1.80,
        'light_curtain_to_spur_pack_m': 1.05,
        'north_station_walkway_m': 1.15,
        'main_5s_walkway_m': 1.00,
        'rear_rack_aisle_m': 1.84,
    }
    narrow = {k: v for k, v in bottlenecks.items() if v < min_required[k] - 1e-4}
    chute_handoff_ok = 0.020 <= chute_to_good_pallet_gap_m <= 0.080
    if not chute_handoff_ok:
        narrow['chute_to_good_pallet_gap_m'] = round(chute_to_good_pallet_gap_m, 4)

    helper_clear = not any(
        _triangle_cylinder(tri, 2.80, 1.95, 0.275, 0.025, 1.800)
        for _, tri, tx0, tx1, ty0, ty1 in obs_tris
        if 2.80 + 0.275 >= tx0 and 2.80 - 0.275 <= tx1 and 1.95 + 0.275 >= ty0 and 1.95 - 0.275 <= ty1
    )
    rework_worker_clear = not any(
        _triangle_cylinder(tri, 1.80, -5.55, 0.275, 0.025, 1.800)
        for _, tri, tx0, tx1, ty0, ty1 in obs_tris
        if 1.80 + 0.275 >= tx0 and 1.80 - 0.275 <= tx1 and -5.55 + 0.275 >= ty0 and -5.55 - 0.275 <= ty1
    )
    scrap_worker_clear = not any(
        _triangle_cylinder(tri, 8.65, -5.55, 0.275, 0.025, 1.800)
        for _, tri, tx0, tx1, ty0, ty1 in obs_tris
        if 8.65 + 0.275 >= tx0 and 8.65 - 0.275 <= tx1 and -5.55 + 0.275 >= ty0 and -5.55 - 0.275 <= ty1
    )

    return {
        'passed': (
            not unreachable
            and not unreachable_par
            and not narrow
            and chute_handoff_ok
            and helper_clear
            and rework_worker_clear
            and scrap_worker_clear
            and len(visited) > 2000
            and len(visited_par) > 2000
        ),
        'connected_1m_cells': len(visited),
        'connected_1m_cells_with_5_parallel': len(visited_par),
        'stage_targets_verified': len(target_results),
        'robot_assist_anchor_055m_clear': helper_clear,
        'rework_worker_anchor_055m_clear': rework_worker_clear,
        'scrap_worker_anchor_055m_clear': scrap_worker_clear,
        'chute_to_good_pallet_gap_m': round(chute_to_good_pallet_gap_m, 4),
        'unreachable_targets': unreachable,
        'unreachable_targets_with_5_parallel': unreachable_par,
        'bottlenecks_m': bottlenecks,
        'narrow_bottlenecks': narrow,
    }


def run_suite_4_reimported_glbs(out_dir):
    out = Path(out_dir)
    env_glb = out / 'warehouse_environment.glb'
    lay_glb = out / 'modules/visual_layout.glb'
    sup_glb = out / 'modules/visual_support.glb'
    bindings = json.loads((out / 'visual_bindings.json').read_text())
    anchors_doc = json.loads((out / 'anchors.json').read_text())

    errors = []
    env_size = env_glb.stat().st_size
    if env_size > 12 * 1024 * 1024:
        errors.append({'check': 'env_glb_size_le_12mib', 'bytes': env_size})

    # 4.1 Standalone warehouse_environment.glb checks + combined runtime scene with visual_layout.glb
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(env_glb))
    bpy.context.view_layer.update()

    env_names = {o.name.split('.')[0] for o in bpy.data.objects}
    for layer_name in (
        'ENV_FLOOR_AND_GRID', 'ENV_WALLS_AND_DOCKS', 'ENV_WORKSTATIONS_DETAIL',
        'ENV_ROBOT_CELL', 'ENV_BREAK_AREA', 'ENV_OVERHEAD',
    ):
        if layer_name not in env_names:
            errors.append({'check': 'env_layer_present', 'layer': layer_name})

    for forbidden_prefix in (
        'VIS_Bench_top_robot_chamfer', 'UTILITY_CABINET',
        'ZEBRA_', 'WAYFINDING_', 'AXIS_', 'MOUNT_actor_', 'ANCHOR_REWORK',
        'WORKER_', 'ROBOT_Rig', 'Dock upper wall', 'Dock_upper_wall',
        'Dispatch carton', 'Dispatch_carton', 'Inbound tote', 'Inbound_tote',
        'OVERHEAD_TRUSS', 'OVERHEAD_CABLE_TRAY', 'HIGH_BAY_LED', 'HIGHBAY', 'ENV_LIGHTING_RIG', 'ENV_OVERHEAD__',
        'Truss longitudinal chord', 'Truss_longitudinal_chord', 'Truss diagonal web', 'Truss_diagonal_web',
        'High bay LED', 'High_bay_LED', 'High bay suspension', 'High_bay_suspension',
        'Cable tray ', 'Cable_tray_',
        'SPUR_TRANSFER_GUIDES', 'SPUR_GUIDE_', 'REWORK_RETURN', 'SCRAP_TRANSFER', 'Walkway arrow', 'Walkway_arrow',
    ):
        bad = [o.name for o in bpy.data.objects if o.name.startswith(forbidden_prefix)]
        if bad:
            errors.append({'check': 'forbidden_absent_in_env_glb', 'prefix': forbidden_prefix, 'found': bad})

    # Check zero orphaned tabletop near (0, 0, 0)
    for ob in bpy.data.objects:
        if ob.type == 'MESH' and ('Bench_top' in ob.name or 'worktop' in ob.name):
            verts, _ = _world_tris_and_verts([ob])
            lo, hi = _aabb_from_verts(verts)
            cx, cy = 0.5 * (lo[0] + hi[0]), 0.5 * (lo[1] + hi[1])
            if math.hypot(cx, cy) < 0.75:
                errors.append({'check': 'no_orphaned_tabletop_at_origin', 'object': ob.name, 'center_xy': [cx, cy]})

    # Wall height == 3.600 m & ENV_OVERHEAD is an empty container (0 mesh descendants)
    walls_root = _find_object_flexible('ENV_WALLS_AND_DOCKS')
    w_verts, _ = _world_tris_and_verts(_subtree_meshes(walls_root))
    w_lo, w_hi = _aabb_from_verts(w_verts)
    if abs(w_hi[2] - 3.600) > 0.010:
        errors.append({'check': 'env_glb_wall_height_360', 'actual_max_z': round(w_hi[2], 5)})

    ov_root = _find_object_flexible('ENV_OVERHEAD')
    ov_meshes = _subtree_meshes(ov_root)
    if ov_root is None or ov_root.type != 'EMPTY':
        errors.append({'check': 'env_overhead_empty_container_exists', 'type': ov_root.type if ov_root else None})
    elif len(ov_meshes) != 0:
        errors.append({'check': 'env_overhead_zero_meshes', 'found': [m.name for m in ov_meshes]})

    jack = _find_object_flexible('PALLET_JACK')
    jack_meshes = _subtree_meshes(jack)
    if len(jack_meshes) != 12:
        errors.append({'check': 'pallet_jack_12_child_meshes', 'actual': len(jack_meshes)})

    for a in anchors_doc['anchors']:
        aid = a['id']
        aob = _find_object_flexible(aid)
        if aob is None:
            errors.append({'check': 'anchor_in_env_glb', 'id': aid})
        else:
            tr = aob.matrix_world.translation
            actual_gltf = [tr.x, tr.z, -tr.y]
            if max(abs(actual_gltf[i] - a['position_m'][i]) for i in range(3)) > POS_TOL:
                errors.append({'check': 'anchor_pos_match', 'id': aid, 'expected': a['position_m'], 'actual': actual_gltf})

    # Standalone warehouse_environment.glb (WITHOUT visual_layout.glb):
    # 1) Every stationary workstation & floor furniture grounded at abs(minY) <= 0.003 m
    for st_name in (
        'STAGE1_PREP_TABLE', 'PREP_TOOLING', 'BENCH_PICK', 'BENCH_PACK',
        'BENCH_REWORK', 'BENCH_SCRAP',
        'ROBOT_PACK_TABLE', 'ROBOT_TABLE_REINFORCEMENT', 'STAGE4_QC_TABLE', 'QC_TABLE_TOOLING',
        'BREAK_BENCH', 'WATER_COOLER', 'SHIPPING_MANIFEST_PODIUM', 'PALLET_STRETCH_WRAPPER',
        'NW_TOTE_RETURN_RACK', 'NW_CHARGING_CABINET', 'WEST_INBOUND_RACK_01', 'WEST_INBOUND_RACK_02',
        'SUPPLY_TROLLEY', 'SCRAP_BIN',
    ):
        st_root = _find_object_flexible(st_name)
        st_meshes = _subtree_meshes(st_root)
        if not st_meshes:
            errors.append({'check': 'standalone_env_grounded_exists', 'unit': st_name})
            continue
        st_verts, _ = _world_tris_and_verts(st_meshes)
        st_lo, _ = _aabb_from_verts(st_verts)
        if abs(st_lo[2]) > 0.003:
            errors.append({
                'check': 'standalone_env_grounded_min_y',
                'unit': st_name,
                'actual_min_y_m': round(st_lo[2], 6),
            })

    # 2) All 7 standalone stationary workstations have worktop maxY in [0.857, 0.862] m
    for ws_name in (
        'STAGE1_PREP_TABLE', 'BENCH_PICK', 'BENCH_PACK', 'BENCH_REWORK', 'BENCH_SCRAP',
        'ROBOT_PACK_TABLE', 'STAGE4_QC_TABLE',
    ):
        ws_root = _find_object_flexible(ws_name)
        ws_meshes = _subtree_meshes(ws_root)
        has_worktop = False
        for wm in ws_meshes:
            wv, _ = _world_tris_and_verts([wm])
            _, whi = _aabb_from_verts(wv)
            if 0.857 <= whi[2] <= 0.862:
                has_worktop = True
                break
        if not has_worktop:
            errors.append({'check': 'standalone_env_worktop_086', 'unit': ws_name})

    # 3) 5-tier floor decal vertical Z-separation (>= 1.0 mm gap between consecutive tiers)
    floor_root = _find_object_flexible('ENV_FLOOR_AND_GRID')
    floor_meshes = _subtree_meshes(floor_root)
    decal_tiers = [
        ('tier1_fill', (0.0009, 0.0013), []),
        ('tier2_grid', (0.0022, 0.0027), []),
        ('tier3_border_dash', (0.0036, 0.0041), []),
        ('tier4_walkway_badge', (0.0049, 0.0054), []),
        ('tier5_top_chevron_label', (0.0062, 0.0070), []),
    ]
    for fm in floor_meshes:
        base = fm.name.split('.')[0]
        if base in ('Raised concrete slab', 'Raised_concrete_slab', 'Lower reveal', 'Lower_reveal'):
            continue
        if '_FILL' in base:
            decal_tiers[0][2].append(fm)
        elif 'CAD_grid' in base or 'CAD_GRID_' in base or 'CAD_DRAWING_BORDER' in base:
            decal_tiers[1][2].append(fm)
        elif '_BORDER' in base or '_DASH' in base or '_LINE' in base or 'Safety_yellow' in base:
            decal_tiers[2][2].append(fm)
        elif 'WALKWAY_GREEN_5S' in base or '_BADGE' in base or '_TICK' in base or 'Deep_black' in base:
            decal_tiers[3][2].append(fm)
        elif '_CORNER' in base or 'WALKWAY_DIRECTION_ARROW' in base or '_LABEL' in base or 'Label_white' in base or base.startswith('GRID_REF_'):
            decal_tiers[4][2].append(fm)

    tier_actual_bounds = []
    for tname, (exp_lo, exp_hi), tmeshes in decal_tiers:
        if not tmeshes:
            errors.append({'check': 'standalone_decal_tier_nonempty', 'tier': tname})
            tier_actual_bounds.append(None)
            continue
        tv, _ = _world_tris_and_verts(tmeshes)
        tlo, thi = _aabb_from_verts(tv)
        tier_actual_bounds.append((tlo[2], thi[2]))
        if tlo[2] < exp_lo or thi[2] > exp_hi:
            errors.append({
                'check': 'standalone_decal_tier_z_band',
                'tier': tname,
                'actual_z': [round(tlo[2], 6), round(thi[2], 6)],
                'expected_z': [exp_lo, exp_hi],
            })
    for idx in range(len(tier_actual_bounds) - 1):
        b0, b1 = tier_actual_bounds[idx], tier_actual_bounds[idx + 1]
        if b0 is not None and b1 is not None and (b1[0] - b0[1]) < 0.00095:
            errors.append({
                'check': 'standalone_decal_tier_gap_ge_1mm',
                'lower_tier': decal_tiers[idx][0],
                'upper_tier': decal_tiers[idx + 1][0],
                'gap_m': round(b1[0] - b0[1], 6),
            })

    # 4) Green-walkway-only arrows contract: 0 non-walkway arrows/chevrons/dashes & 3 crisp +X WALKWAY_DIRECTION_ARROW_01..03
    allowed_arrows = {'WALKWAY_DIRECTION_ARROW_01', 'WALKWAY_DIRECTION_ARROW_02', 'WALKWAY_DIRECTION_ARROW_03'}
    allowed_empty_lanes = {'INBOUND_TRANSFER_LANE', 'DISPATCH_TRANSFER_LANE'}
    for elane in allowed_empty_lanes:
        el_ob = _find_object_flexible(elane)
        if el_ob is None or el_ob.type != 'EMPTY' or len(_subtree_meshes(el_ob)) != 0:
            errors.append({'check': 'empty_transfer_lane_container', 'name': elane, 'exists': el_ob is not None})
    non_walkway_arrow_objs = [
        o.name for o in bpy.data.objects
        if o.name.split('.')[0] not in allowed_arrows
        and not (o.type == 'EMPTY' and o.name.split('.')[0] in allowed_empty_lanes)
        and any(tok in o.name.upper() for tok in ('CHEVRON', 'ARROW', '_DASH', 'TRANSFER_LANE', 'RETURN_LANE', 'SPUR_GUIDE'))
    ]
    if non_walkway_arrow_objs:
        errors.append({'check': 'zero_non_walkway_arrows_chevrons_dashes', 'found': non_walkway_arrow_objs})

    walk_ob = _find_object_flexible('WALKWAY_GREEN_5S')
    if walk_ob is not None and walk_ob.type == 'MESH':
        wv, _ = _world_tris_and_verts([walk_ob])
        wlo, whi = _aabb_from_verts(wv)
        for aname, exp_x in zip(sorted(allowed_arrows), (-11.8, 0.0, 11.8)):
            ao = _find_object_flexible(aname)
            if ao is None or ao.type != 'MESH':
                errors.append({'check': 'walkway_arrow_present_unbatched', 'arrow': aname})
                continue
            av, atris = _world_tris_and_verts([ao])
            alo, ahi = _aabb_from_verts(av)
            if not (alo[0] >= wlo[0] and ahi[0] <= whi[0] and alo[1] >= wlo[1] and ahi[1] <= whi[1]):
                errors.append({'check': 'walkway_arrow_inside_green_walkway', 'arrow': aname, 'aabb': [alo[:2], ahi[:2]]})
            if abs(0.5 * (alo[0] + ahi[0]) - exp_x) > 0.05:
                errors.append({'check': 'walkway_arrow_x_center', 'arrow': aname, 'expected_x': exp_x})
            for t in atris:
                n = (av[t[1]] - av[t[0]]).cross(av[t[2]] - av[t[0]])
                if n.length > 1e-12 and (n.normalized().z < 0.99):
                    errors.append({'check': 'walkway_arrow_upward_normal', 'arrow': aname, 'nz': round(n.normalized().z, 5)})
                    break
            tip = max(av, key=lambda v: v.x)
            wings = [v for v in av if abs(v.y - (-5.15)) > 0.20]
            if len(wings) >= 2:
                wing_mid = sum(wings, Vector((0.0, 0.0, 0.0))) / len(wings)
                d2 = Vector((tip.x - wing_mid.x, tip.y - wing_mid.y))
                if d2.length < 1e-6 or (d2.normalized().x <= 0.98):
                    errors.append({'check': 'walkway_arrow_points_plus_x', 'arrow': aname})

    # Import visual_layout.glb into same scene to re-run Suite 1, Suite 2 & Suite 3 on combined runtime GLBs!
    bpy.ops.import_scene.gltf(filepath=str(lay_glb))
    bpy.context.view_layer.update()
    glb_suite1 = run_suite_1_bvh()
    glb_suite2 = run_suite_2_contacts(is_reimported_glb=True)
    glb_suite3 = run_suite_3_walkways()
    if not glb_suite1['passed']:
        errors.append({'check': 'reimported_glb_suite1_bvh', 'penetrations': glb_suite1['penetrations']})
    if not glb_suite2['passed']:
        errors.append({'check': 'reimported_glb_suite2_contacts', 'details': glb_suite2['errors']})
    if not glb_suite3['passed']:
        errors.append({
            'check': 'reimported_glb_suite3_walkways',
            'unreachable': glb_suite3['unreachable_targets'],
            'unreachable_with_5_parallel': glb_suite3['unreachable_targets_with_5_parallel'],
            'narrow': glb_suite3['narrow_bottlenecks'],
        })

    # 4.2 Standalone visual_layout.glb check
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(lay_glb))
    bpy.context.view_layer.update()

    expected = {}
    for stage, x, y in [(1, -11.0, 1.0), (2, -5.4, 2.05), (3, 1.8, 2.05), (4, 6.0, 2.05)]:
        expected[f'VIS_STAGE_{stage}_WORK'] = (x, y, 0.0)
        expected[f'VIS_STAGE_{stage}_ORDER'] = (x, y + 0.34, 0.86)
    expected.update({
        'VIS_ROBOT_WORK': (3.5, 2.05, 0.0),
        'VIS_ROBOT_ORDER': (3.5, 2.39, 0.86),
        'VIS_ROBOT_ASSIST': (2.8, 1.95, 0.0),
        'VIS_OUTCOME_GOOD': (10.0, 2.2, 0.15),
        'VIS_OUTCOME_ESCAPED': (10.0, 4.4, 0.15),
        'VIS_OUTCOME_SCRAP': (7.2, -7.0, 0.02),
    })
    qdefs = {
        'Q1': ((-11.0, 3.1, 0.15), 3, (0.56, 0.42), 6),
        'Q2': ((-7.3, -2.3, 0.86), 4, (0.56, -0.42), 12),
        'Q3': ((-0.7, -2.3, 0.86), 5, (0.56, -0.42), 10),
        'Q4': ((5.6, -2.3, 0.86), 4, (0.56, -0.42), 8),
        'R': ((3.8, -7.45, 0.86), 3, (0.56, 0.42), 6),
    }
    for qname, (orig, cols, sp, cnt) in qdefs.items():
        expected['VIS_QUEUE_' + qname] = orig
        for idx in range(cnt):
            expected[f'VIS_QUEUE_{qname}_SLOT_{idx:02d}'] = (
                orig[0] + (idx % cols) * sp[0],
                orig[1] + (idx // cols) * sp[1],
                orig[2],
            )
    for name, want in expected.items():
        ob = _find_object_flexible(name)
        if ob is None or max(abs(ob.matrix_world.translation[i] - want[i]) for i in range(3)) > POS_TOL:
            errors.append({'check': 'visual_layout_61_anchors', 'name': name})

    chamfer = _find_object_flexible('VIS_Bench_top_robot_chamfer')
    rtable = _find_object_flexible('VIS_ROBOT_PACK_TABLE')
    if chamfer is None or rtable is None or chamfer.parent != rtable:
        errors.append({'check': 'robot_chamfer_parented_in_visual_layout'})
    else:
        verts, _ = _world_tris_and_verts([chamfer])
        lo, hi = _aabb_from_verts(verts)
        if abs(hi[2] - 0.860) > POS_TOL or abs(0.5 * (lo[0] + hi[0]) - 3.5) > 0.05:
            errors.append({'check': 'robot_chamfer_world_pose', 'lo': lo, 'hi': hi})

    # 4.3 Standalone visual_support.glb check
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(sup_glb))
    bpy.context.view_layer.update()
    actual_templates = sorted(o.name for o in bpy.data.objects if o.parent is None and o.name.startswith('VIS_'))
    if len(actual_templates) != 14 or actual_templates != sorted(bindings['templates']):
        errors.append({'check': 'visual_support_14_templates', 'actual': actual_templates})
    for tname in ('VIS_order_regular', 'VIS_order_fragile', 'VIS_order_oversize', 'VIS_order_tray', 'VIS_reserved_slot', 'VIS_empty_slot'):
        troot = _find_object_flexible(tname)
        tmeshes = _subtree_meshes(troot)
        if not tmeshes:
            errors.append({'check': 'portable_template_meshes', 'name': tname})
            continue
        inv = troot.matrix_world.inverted()
        pts = [inv @ m.matrix_world @ v.co for m in tmeshes for v in m.data.vertices]
        lo, hi = _aabb_from_verts(pts)
        if abs(lo[2]) > POS_TOL or any(abs(0.5 * (lo[i] + hi[i])) > 0.006 for i in (0, 1)):
            errors.append({'check': 'portable_template_bottom_center_pivot', 'name': tname, 'lo': lo, 'hi': hi})

    return {
        'passed': not errors,
        'env_glb_bytes': env_size,
        'env_overhead_meshes': len(ov_meshes),
        'layout_anchors_verified': len(expected),
        'templates_verified': len(actual_templates),
        'reimported_glb_connected_1m_cells': glb_suite3.get('connected_1m_cells', 0),
        'errors': errors,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--report-json', default=None)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])

    out = Path(args.output).resolve()
    suite1 = run_suite_1_bvh()
    suite2 = run_suite_2_contacts(is_reimported_glb=False)
    suite3 = run_suite_3_walkways()
    suite4 = run_suite_4_reimported_glbs(out)

    passed = all(s['passed'] for s in (suite1, suite2, suite3, suite4))
    report = {
        'format': 'four-horses.scene-geometry-check.v1',
        'passed': passed,
        'suite_1_bvh_penetrations': suite1,
        'suite_2_contacts_and_raycasts': suite2,
        'suite_3_walkways_1m_bfs': suite3,
        'suite_4_reimported_glbs': suite4,
    }
    if args.report_json:
        Path(args.report_json).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('SCENE_GEOMETRY_CHECK', json.dumps(report, ensure_ascii=False), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
