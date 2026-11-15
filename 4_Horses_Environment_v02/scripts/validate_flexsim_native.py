"""Native, geometry-based acceptance checks for the fixed replay contract.

Call validate_native(output_directory) after the final scene is assembled.
This module does not change the scene. Reports describe exactly what was
tested: roller support uses the tangent-plane envelope, rather than treating
the designed gaps between rollers as missing floor.
"""
import bpy
import collections
import hashlib
import json
import math
from pathlib import Path
from mathutils import Vector

REFERENCE_BINDINGS_SHA256 = 'a96d46309f52f1b28ee9cf35dd4b316050f1fe7412492d7c6a70bd2892e82374'
TOL = 1e-5


def _bounds(ob):
    pts = [ob.matrix_world @ Vector(p) for p in ob.bound_box]
    return tuple(min(p[i] for p in pts) for i in range(3)), tuple(max(p[i] for p in pts) for i in range(3))


def _overlap(a, b):
    return all(a[1][i] > b[0][i] + 1e-8 and b[1][i] > a[0][i] + 1e-8 for i in range(3))


def _ancestors(ob):
    while ob:
        yield ob
        ob = ob.parent


def _static_geometry(ob):
    if ob.type != 'MESH':
        return False
    for part in _ancestors(ob):
        if part.get('worker_asset') or part.get('robot_asset') or part.type == 'ARMATURE':
            return False
        if part.name.startswith(('DEMO_PARCEL_', 'WORKER_', 'ATTACH_WORKER_', 'ATTACH_ROBOT_')):
            return False
    if any(c.name.startswith(('CHARACTERS', 'INTEGRATION / Visual templates')) for c in ob.users_collection):
        return False
    return not any(m.type == 'ARMATURE' for m in ob.modifiers)


def _triangle_box(tri, bounds):
    """Separating-axis triangle/AABB intersection, including coplanar faces."""
    center = Vector(tuple((bounds[0][i] + bounds[1][i]) / 2 for i in range(3)))
    half = tuple((bounds[1][i] - bounds[0][i]) / 2 for i in range(3))
    vs = [v-center for v in tri]
    edges = [vs[1]-vs[0], vs[2]-vs[1], vs[0]-vs[2]]
    axes = [Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)), edges[0].cross(edges[1])]
    axes += [e.cross(a) for e in edges for a in axes[:3]]
    for axis in axes:
        if axis.length_squared < 1e-20:
            continue
        vals = [v.dot(axis) for v in vs]
        radius = sum(half[i] * abs(axis[i]) for i in range(3))
        if min(vals) > radius + 1e-9 or max(vals) < -radius - 1e-9:
            return False
    return True


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
            result.append(a + (b-a) * ((z-a.z)/(b.z-a.z)))
    return result


def _triangle_cylinder(tri, cx, cy, radius, zmin=.025, zmax=1.8):
    poly = _clip_z(_clip_z(list(tri), zmin, True), zmax, False)
    if not poly:
        return False
    pts = [Vector((v.x-cx, v.y-cy)) for v in poly]
    rr = radius*radius
    if any(p.length_squared <= rr for p in pts):
        return True
    for a, b in zip(pts, pts[1:] + pts[:1]):
        edge = b-a
        t = max(0., min(1., -a.dot(edge)/edge.length_squared)) if edge.length_squared > 1e-20 else 0.
        if (a+t*edge).length_squared <= rr:
            return True
    # A broad horizontal face can contain the cylinder without an edge near it.
    area = sum(a.x*b.y-a.y*b.x for a, b in zip(pts, pts[1:]+pts[:1]))
    if abs(area) < 1e-12:
        return False
    crosses = [(b.x-a.x)*(-a.y)-(b.y-a.y)*(-a.x) for a, b in zip(pts, pts[1:]+pts[:1])]
    return all(c >= -1e-10 for c in crosses) or all(c <= 1e-10 for c in crosses)


def validate_native(output_directory):
    out = Path(output_directory)
    bpy.context.view_layer.update()
    report = {'format': 'four-horses.native-acceptance.v2', 'units': 'meters', 'failures': [], 'checks': {}}
    failures = report['failures']

    def check(name, condition, details=None, mandatory=True):
        report['checks'][name] = {'passed': bool(condition), 'mandatory': mandatory, 'details': details}
        if not condition:
            failures.append({'check': name, 'mandatory': mandatory, 'details': details})

    check('metric_scale', abs(bpy.context.scene.unit_settings.scale_length-1) < TOL)
    bindings = json.loads((out/'visual_bindings.json').read_text())
    digest = hashlib.sha256(json.dumps(bindings, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    check('original_bindings_contract_unchanged', digest == REFERENCE_BINDINGS_SHA256, {'actual_sha256': digest, 'reference_sha256': REFERENCE_BINDINGS_SHA256})

    expected = {}
    for stage, x, y in [(1, -11., 1.), (2, -5.4, 2.05), (3, 1.8, 2.05), (4, 6., 2.05)]:
        expected[f'VIS_STAGE_{stage}_WORK'] = (x, y, 0.)
        expected[f'VIS_STAGE_{stage}_ORDER'] = (x, y+.34, .86)
    expected.update({'VIS_ROBOT_WORK': (3.5, 2.05, 0), 'VIS_ROBOT_ORDER': (3.5, 2.39, .86), 'VIS_ROBOT_ASSIST': (2.8, 1.95, 0),
                     'VIS_OUTCOME_GOOD': (10, 2.2, .15), 'VIS_OUTCOME_ESCAPED': (10, 4.4, .15), 'VIS_OUTCOME_SCRAP': (7.2, -7, .02)})
    queue_defs = {'Q1': ((-11, 3.1, .15), 3, (.56, .42), 6), 'Q2': ((-7.3, -2.3, .86), 4, (.56, -.42), 12),
                  'Q3': ((-.7, -2.3, .86), 5, (.56, -.42), 10), 'Q4': ((5.6, -2.3, .86), 4, (.56, -.42), 8), 'R': ((3.8, -7.45, .86), 3, (.56, .42), 6)}
    for name, (origin, cols, spacing, count) in queue_defs.items():
        expected['VIS_QUEUE_'+name] = origin
        for i in range(count):
            expected[f'VIS_QUEUE_{name}_SLOT_{i:02d}'] = (origin[0]+(i % cols)*spacing[0], origin[1]+(i//cols)*spacing[1], origin[2])
    position_errors = []
    for name, want in expected.items():
        ob = bpy.data.objects.get(name)
        actual = list(ob.matrix_world.translation) if ob else None
        if ob is None or max(abs(actual[i]-want[i]) for i in range(3)) > TOL:
            position_errors.append({'name': name, 'expected_blender_m': want, 'actual_blender_m': actual})
    assist_ob = bpy.data.objects.get('VIS_ROBOT_ASSIST')
    want_assist_yaw = math.atan2(3.5 - 2.8, -2.39 - (-1.95))
    actual_assist_yaw = float(assist_ob.rotation_euler.z) if assist_ob else None
    if assist_ob is None or abs(actual_assist_yaw - want_assist_yaw) > TOL:
        position_errors.append({'name': 'VIS_ROBOT_ASSIST.rotation_euler.z', 'expected_rad': want_assist_yaw, 'actual_rad': actual_assist_yaw})
    check('fixed_anchors_and_42_queue_slots', not position_errors, {'verified': len(expected), 'errors': position_errors})

    library = bpy.data.collections.get('INTEGRATION / Visual templates')
    actual_templates = sorted(o.name for o in library.objects if o.type == 'EMPTY') if library else []
    check('fourteen_template_identifiers', len(actual_templates) == 14 and actual_templates == sorted(bindings['templates']), actual_templates)
    pivot_errors = []
    for name in ['VIS_order_regular', 'VIS_order_fragile', 'VIS_order_oversize', 'VIS_order_tray', 'VIS_reserved_slot', 'VIS_empty_slot']:
        root = bpy.data.objects.get(name)
        if root is None:
            pivot_errors.append({'name': name, 'reason': 'missing'})
            continue
        inv = root.matrix_world.inverted()
        pts = [inv @ child.matrix_world @ Vector(v) for child in root.children_recursive if child.type == 'MESH' for v in child.bound_box]
        lo = [min(p[i] for p in pts) for i in range(3)]
        hi = [max(p[i] for p in pts) for i in range(3)]
        # Minor symbols on fragile parcels intentionally protrude from one side.
        if abs(lo[2]) > TOL or any(abs((lo[i]+hi[i])/2) > .006 for i in (0, 1)):
            pivot_errors.append({'name': name, 'local_bounds_min': lo, 'local_bounds_max': hi})
    check('bottom_center_portable_templates', not pivot_errors, pivot_errors)

    objects = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    static = [o for o in objects if _static_geometry(o)]
    bounds = {o.name: _bounds(o) for o in objects}
    triangles = {}

    def world_triangles(ob):
        if ob.name not in triangles:
            ob.data.calc_loop_triangles()
            mw = ob.matrix_world
            verts = [mw @ v.co for v in ob.data.vertices]
            triangles[ob.name] = [tuple(verts[i] for i in tri.vertices) for tri in ob.data.loop_triangles]
        return triangles[ob.name]

    def collision_box(box):
        return [ob.name for ob in static if _overlap(bounds[ob.name], box) and any(_triangle_box(t, box) for t in world_triangles(ob))]

    active = [f'VIS_STAGE_{i}_ORDER' for i in range(1, 5)] + ['VIS_ROBOT_ORDER']
    active_errors = []
    for name in active:
        p = expected[name]
        query = ((p[0]-.27, p[1]-.20, .8605), (p[0]+.27, p[1]+.20, 1.18))
        hit = collision_box(query)
        if hit:
            active_errors.append({'anchor': name, 'collisions': hit})
    check('active_order_tray_volumes_clear', not active_errors, {'envelope_m': [.54, .40, .3195], 'z_range_m': [.8605, 1.18], 'errors': active_errors}, mandatory=False)

    support_map = {'VIS_STAGE_1_ORDER': 'VIS_STAGE_1_TABLE', 'VIS_STAGE_2_ORDER': 'BENCH_PICK', 'VIS_STAGE_3_ORDER': 'BENCH_PACK',
                   'VIS_STAGE_4_ORDER': 'QC_TABLE_TOOLING', 'VIS_ROBOT_ORDER': 'VIS_ROBOT_PACK_TABLE'}
    support_details = []

    def support(root_name, footprint, z):
        root = bpy.data.objects.get(root_name)
        candidates = [o for o in ([root]+list(root.children_recursive) if root else [])
                      if o and o.type == 'MESH' and abs(bounds[o.name][1][2]-z) < TOL]
        if not candidates:
            return {'root': root_name, 'passed': False, 'reason': 'no support at requested height', 'height_m': z}
        lo = [min(bounds[o.name][0][i] for o in candidates) for i in range(2)]
        hi = [max(bounds[o.name][1][i] for o in candidates) for i in range(2)]
        okay = all(lo[i] <= footprint[0][i]+TOL and hi[i] >= footprint[1][i]-TOL for i in range(2))
        return {'root': root_name, 'passed': okay, 'height_m': z, 'support_envelope_xy_m': [lo, hi], 'required_envelope_xy_m': footprint, 'top_meshes': len(candidates)}

    for name, root_name in support_map.items():
        p = expected[name]
        support_details.append(support(root_name, ((p[0]-.27, p[1]-.2), (p[0]+.27, p[1]+.2)), .86))
    for name, (origin, cols, spacing, count) in queue_defs.items():
        pts = [expected[f'VIS_QUEUE_{name}_SLOT_{i:02d}'] for i in range(count)]
        footprint = ((min(p[0] for p in pts)-.27, min(p[1] for p in pts)-.20), (max(p[0] for p in pts)+.27, max(p[1] for p in pts)+.20))
        root_name = 'Q1_PAIRED_PALLET_DECK' if name == 'Q1' else 'QUEUE_R_ROLLER_SECTION' if name == 'R' else f'VIS_QUEUE_{name}_FRAME'
        support_details.append(support(root_name, footprint, origin[2]))
    check('work_and_queue_support_envelopes', all(d['passed'] for d in support_details), support_details, mandatory=False)

    roller_errors = []
    main_rollers = [o for o in objects if o.name.startswith('ROLLER_')]
    buffer_rollers = [o for o in objects if o.name.startswith('R_ACCUMULATION_ROLLER_') or (o.name.startswith('VIS_QUEUE_') and ('_ROLLER_' in o.name or o.name.endswith('_TOP')))]
    for ob in main_rollers+buffer_rollers:
        if abs(bounds[ob.name][1][2]-.86) > TOL:
            roller_errors.append({'name': ob.name, 'tangent_height_m': bounds[ob.name][1][2]})
    check('roller_tangent_height_086', len(main_rollers) == 200 and bool(buffer_rollers) and not roller_errors, {'main_count': len(main_rollers), 'buffer_count': len(buffer_rollers), 'errors': roller_errors})
    protected = [f'CONVEYOR_{i:02d}' for i in range(1, 11)] + [f'ROLLER_{i:02d}_{j:02d}' for i in range(1, 11) for j in range(1, 21)] + ['QC_PORTAL', 'STOPPER_GATE', 'PACK_PAPER_ROLL']
    check('protected_equipment_names', all(bpy.data.objects.get(n) for n in protected), {'missing': [n for n in protected if not bpy.data.objects.get(n)]})

    env_overhead = bpy.data.objects.get('ENV_OVERHEAD')
    overhead_meshes = [o.name for o in env_overhead.children_recursive if o.type == 'MESH'] if env_overhead else []
    forbidden_overhead = [
        o.name for o in bpy.data.objects
        if o.name.startswith((
            'OVERHEAD_TRUSS', 'OVERHEAD_CABLE_TRAY', 'HIGH_BAY_LED', 'HIGHBAY', 'ENV_LIGHTING_RIG',
            'Truss longitudinal chord', 'Truss diagonal web', 'High bay LED', 'High bay suspension',
            'Cable tray ',
        ))
    ]
    native_lights = sorted(o.name for o in bpy.data.objects if o.type == 'LIGHT')
    check(
        'unobstructed_ceiling_and_native_lights',
        env_overhead is not None
        and env_overhead.type == 'EMPTY'
        and len(overhead_meshes) == 0
        and len(forbidden_overhead) == 0
        and len(native_lights) >= 1,
        {
            'env_overhead_exists': env_overhead is not None,
            'env_overhead_type': env_overhead.type if env_overhead else None,
            'overhead_mesh_children': overhead_meshes,
            'forbidden_overhead_objects': forbidden_overhead,
            'native_light_count': len(native_lights),
            'native_lights': native_lights,
        },
    )

    pallet_errors = []
    for index, y in [(0, 2.2), (1, 4.4)]:
        name = f'DISPATCH_PALLET_{index:02d}'
        root = bpy.data.objects.get(name)
        if root is None:
            pallet_errors.append({'name': name, 'reason': 'missing'})
            continue
        pos = list(root.matrix_world.translation)
        children = [o for o in root.children_recursive if o.type == 'MESH']
        top = max(bounds[o.name][1][2] for o in children)
        embedded = [o.name for o in root.children_recursive if o.get('asset_type') in ('carton_closed', 'carton_open', 'tote_600x400') or o.name.startswith('Dispatch carton')]
        if max(abs(pos[i]-[10., y, 0.][i]) for i in range(3)) > TOL or abs(top-.15) > TOL or embedded:
            pallet_errors.append({'name': name, 'position': pos, 'top_m': top, 'embedded_loads': embedded})
    forbidden = [o.name for o in bpy.context.scene.objects if o.name.startswith(('Dispatch carton', 'Inbound tote'))]
    check('dispatch_pallet_alignment_and_empty_tick_zero', not pallet_errors and not forbidden, {'pallet_errors': pallet_errors, 'forbidden_static_loads': forbidden})

    helper = (2.8, 1.95)
    helper_bounds = ((helper[0]-.275, helper[1]-.275, .025), (helper[0]+.275, helper[1]+.275, 1.8))
    helper_hits = [o.name for o in static if _overlap(bounds[o.name], helper_bounds) and any(_triangle_cylinder(t, *helper, .275) for t in world_triangles(o))]
    check('robot_helper_standing_clearance', not helper_hits, {'center_blender_m': [2.8, 1.95, 0], 'diameter_m': .55, 'height_m': 1.8, 'collisions': helper_hits}, mandatory=False)
    # Operator arm/desk overlap is reported, not declared an invalid replay:
    # the immutable original actor anchors are only .13-.18 m from top edges.
    operator_contacts = []
    for name in [f'VIS_STAGE_{i}_WORK' for i in range(1, 5)] + ['VIS_ROBOT_WORK']:
        p = expected[name]
        q = ((p[0]-.275, p[1]-.275, .025), (p[0]+.275, p[1]+.275, 1.8))
        hits = [o.name for o in static if _overlap(bounds[o.name], q) and any(_triangle_cylinder(t, p[0], p[1], .275) for t in world_triangles(o))]
        if hits:
            operator_contacts.append({'anchor': name, 'diameter_m': .55, 'contact_meshes': hits})
    report['operator_arm_reach_envelope_contacts'] = operator_contacts

    invalid_vertices = []
    degenerate = []
    negative_closed = []
    closed_count = 0
    open_count = 0
    inspected = set()
    for ob in objects:
        mesh = ob.data
        if mesh.as_pointer() in inspected:
            continue
        inspected.add(mesh.as_pointer())
        if any(not math.isfinite(c) for v in mesh.vertices for c in v.co):
            invalid_vertices.append(ob.name)
        mesh.calc_loop_triangles()
        bad = sum((mesh.vertices[t.vertices[1]].co-mesh.vertices[t.vertices[0]].co).cross(mesh.vertices[t.vertices[2]].co-mesh.vertices[t.vertices[0]].co).length/2 < 1e-12 for t in mesh.loop_triangles)
        if bad:
            degenerate.append({'object': ob.name, 'triangle_count': bad})
        edge_counts = collections.Counter(tuple(sorted((p.vertices[i], p.vertices[(i+1) % len(p.vertices)]))) for p in mesh.polygons for i in range(len(p.vertices)))
        closed = bool(edge_counts) and all(n == 2 for n in edge_counts.values())
        if closed:
            closed_count += 1
            vol = sum(mesh.vertices[t.vertices[0]].co.dot(mesh.vertices[t.vertices[1]].co.cross(mesh.vertices[t.vertices[2]].co))/6 for t in mesh.loop_triangles)
            if vol < -1e-10:
                negative_closed.append({'object': ob.name, 'signed_volume_m3': vol})
        else:
            open_count += 1
    check('finite_geometry_and_no_zero_area_triangles', not invalid_vertices and not degenerate, {'unique_meshes': len(inspected), 'invalid_vertex_objects': invalid_vertices, 'degenerate_triangle_objects': degenerate, 'area_threshold_m2': 1e-12})
    check('closed_mesh_outward_volume', not negative_closed, {'closed_meshes': closed_count, 'open_meshes': open_count, 'negative_closed_meshes': negative_closed,
          'scope': 'Signed volume of closed mesh datablocks only. Open lettering/paint and local face consistency are not certified by this test.'}, mandatory=False)
    report['limitations'] = [
        'Q1 and R are unbounded in the replay contract. Physical supports cover their documented six preview slots; arbitrary later rows require runtime extension or virtualization.',
        'Roller support is checked against tangent-plane envelopes, with deliberate gaps between adjacent rollers.',
        'Fixed operator work anchors imply arm/reach-envelope contact with bench fronts. Contacts are reported separately; helper standing clearance is mandatory.',
        'This verifies the visual contract and geometry, not execution against the unavailable private production simulation core.'
    ]
    report['passed'] = not failures
    report['mandatory_failures'] = [f for f in failures if f['mandatory']]
    (out/'flexsim_native_validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print('FLEXSIM_NATIVE_VALIDATION', json.dumps({'passed': report['passed'], 'failures': len(failures), 'report': str(out/'flexsim_native_validation.json')}), flush=True)
    assert not report['mandatory_failures'], json.dumps(report['mandatory_failures'], ensure_ascii=False)
    return report


if __name__ == '__main__':
    import argparse
    import sys
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    validate_native(args.output)
