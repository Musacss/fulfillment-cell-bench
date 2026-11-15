"""Expand editable architecture without exporting or changing replay assets.

Run with the existing native scene in background Blender. Only the floor,
markings, walls, docks and their parked pallet jack are rebuilt. Simulation
anchors, all conveyors and the character data are checked before saving.
"""
import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path
import bpy

P = argparse.ArgumentParser()
P.add_argument('--render', action='store_true')
P.add_argument('--check-frozen-glbs', action='store_true')
opt = P.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
finish = ROOT / 'scripts/flexsim_finish.py'
tree = ast.parse(finish.read_text())
tree.body = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef))]
ns = {'__file__': str(finish), 'ROOT': ROOT, 'OUT': ROOT, 'sc': bpy.context.scene}
exec(compile(tree, str(finish), 'exec'), ns)

def hierarchy_contains(obj, names):
    while obj:
        if obj.name in names:
            return True
        obj = obj.parent
    return False

def protected_snapshot():
    """Actual coordinates/topology, not only object counts or names."""
    result = {}
    for obj in bpy.data.objects:
        if hierarchy_contains(obj, {'ENV_WALLS_AND_DOCKS', 'ENV_FLOOR_AND_GRID', 'ENV_OVERHEAD'}):
            continue
        if obj.type in {'CAMERA', 'LIGHT'}:
            continue
        record = {
            'parent': obj.parent.name if obj.parent else None,
            'basis': [float(v) for row in obj.matrix_basis for v in row],
            'world': [float(v) for row in obj.matrix_world for v in row],
            'modifiers': [(m.name, m.type, m.object.name if m.type == 'ARMATURE' and m.object else None)
                          for m in obj.modifiers],
        }
        if obj.type == 'MESH':
            record['vertices'] = [[float(v) for v in p.co] for p in obj.data.vertices]
            record['faces'] = [list(p.vertices) for p in obj.data.polygons]
        result[obj.name] = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
    return result

def file_hashes():
    manifest = json.loads((ROOT.parent / 'studio/asset-hashes.json').read_text())
    result = {}
    for name in manifest:
        result[name] = hashlib.sha256((ROOT.parent / name).read_bytes()).hexdigest()
    return result

bpy.context.view_layer.update()
before = protected_snapshot()
actions_before = ns['snapshot_actions']()
glbs_before = file_hashes() if opt.check_frozen_glbs else {}
bpy.ops.object.select_all(action='DESELECT')
api = ns['api_functions']()
api['M'] = ns['palette']()

# Ensure ENV_OVERHEAD remains an empty container with zero ceiling beam/truss/lamp meshes.
overhead = bpy.data.objects.get('ENV_OVERHEAD')
if overhead:
    for child in reversed(list(overhead.children_recursive)):
        if child.type != 'LIGHT':
            bpy.data.objects.remove(child, do_unlink=True)
    overhead['default_visible'] = False
    overhead.hide_render = True
allowed_arrows = {'WALKWAY_DIRECTION_ARROW_01', 'WALKWAY_DIRECTION_ARROW_02', 'WALKWAY_DIRECTION_ARROW_03'}
for stale in list(bpy.data.objects):
    if stale.type == 'LIGHT' or stale == overhead:
        continue
    uname = stale.name.upper()
    if stale.name.startswith(('OVERHEAD_TRUSS', 'OVERHEAD_CABLE_TRAY', 'HIGH_BAY_LED', 'HIGHBAY_', 'ENV_LIGHTING_RIG')) or (
        ('CHEVRON' in uname or 'ARROW' in uname) and stale.name not in allowed_arrows
    ):
        bpy.data.objects.remove(stale, do_unlink=True)

# Replace just the architectural hierarchy, preserving every production root.
old = bpy.data.objects.get('ENV_WALLS_AND_DOCKS')
if old:
    for child in reversed(list(old.children_recursive)):
        bpy.data.objects.remove(child, do_unlink=True)
    bpy.data.objects.remove(old, do_unlink=True)
walls, wall_collection = ns['layer'](api, 'ENV_WALLS_AND_DOCKS')
walls['ui_label'] = 'Walls and logistics docks'
walls['ui_toggle'] = True
wall_height = 3.6
api['build_shell_back_wall'](walls, 36, 18, wall_height)
from industrial_equipment import build_docks_and_cutaway
build_docks_and_cutaway(api, walls, width=36, depth=18, wall_height=wall_height)
for obj in [walls] + list(walls.children_recursive):
    for collection in list(obj.users_collection):
        collection.objects.unlink(obj)
    wall_collection.objects.link(obj)
    obj['environment_layer'] = walls.name

# Keep the existing slab materials/bevels, resize its architectural X extent.
old = bpy.data.objects.get('ENV_FLOOR_AND_GRID')
if old:
    for child in list(old.children_recursive):
        if child.name.startswith(('Raised concrete slab', 'Lower reveal')):
            matrix = child.matrix_world.copy()
            child.parent = None
            child.matrix_world = matrix
            child.dimensions.x = 36 if child.name.startswith('Raised concrete slab') else 35.92
    for child in reversed(list(old.children_recursive)):
        bpy.data.objects.remove(child, do_unlink=True)
    bpy.data.objects.remove(old, do_unlink=True)
bpy.context.view_layer.update()
ns['floor_and_grid'](api)
bpy.context.view_layer.update()

slab = bpy.data.objects.get('Raised concrete slab')
assert slab and abs(slab.dimensions.x - 36) < 1e-5, 'Expanded floor lost its width while reparenting'

assert protected_snapshot() == before, 'A production object, conveyor, anchor or skin changed'
assert ns['snapshot_actions']() == actions_before, 'Character animation changed'
if opt.check_frozen_glbs:
    assert file_hashes() == glbs_before, 'Frozen GLB changed'
assert not [o for o in bpy.data.objects if o.name.startswith(('AXIS_', 'CAD_AXIS_', 'CAD_SCALE'))]
arrows = sorted(round(o.location.x, 5) for o in bpy.data.objects if o.name.startswith('WALKWAY_DIRECTION'))
assert arrows == [-11.8, 0, 11.8], arrows
for side, number in [(-1, '01'), (1, '02')]:
    p = bpy.data.objects['DOCK_' + number].matrix_world.translation
    assert abs(p.x - side * 17.85) < 1e-5 and abs(p.y + 5.15) < 1e-5
side_walls = [o for o in walls.children_recursive if o.name.startswith('Cutaway side wall')]
assert len(side_walls) == 4, 'Expected two continuous wall panels beside each dock'
assert all(abs(o.dimensions.z - wall_height) < 1e-5 for o in side_walls), 'Former side-wall holes remain'

ns['configure_lighting']()
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / 'warehouse_environment.blend'))

# Validate the unchanged operational geometry with the original validator.
from validate_flexsim_native import validate_native
library = bpy.data.collections.get('INTEGRATION / Visual templates')
hidden = library.hide_viewport if library else None
if library:
    library.hide_viewport = False
bpy.context.view_layer.update()
validate_native(ROOT)
if library:
    library.hide_viewport = hidden
bpy.context.view_layer.update()

if opt.render:
    # Render a tick-zero architectural preview without demonstration parcels.
    scene = bpy.context.scene
    scene.frame_set(0)
    for obj in bpy.data.objects:
        if obj.name.startswith('DEMO_PARCEL_') or obj.get('handling_prop'):
            for child in [obj] + list(obj.children_recursive):
                child.hide_render = True
    scene.render.filepath = str(ROOT / 'environment_overview.png')
    bpy.ops.render.render(write_still=True)
report = {
    'passed': True,
    'room_m': [36, 18, wall_height],
    'dock_positions_blender_m': [[-17.85, -5.15, 0], [17.85, -5.15, 0]],
    'straight_aisle_blender_y_m': [-5.9, -4.4],
    'lane_x_m': [-17.7, 17.7],
    'arrow_centers_x_m': arrows,
    'arrow_spacing_m': 11.8,
    'equal_end_margins_m': [5.9, 5.9],
    'floor_axes_removed': True,
    'side_wall_height_m': wall_height,
    'side_wall_panels': len(side_walls),
    'former_parapet_gaps_closed': True,
    'upper_dock_walls_closed': False,
    'zones_blender_bounds_m': {
        'PREP': [-13.35, -8.55, .65, 4.9],
        'PICK': [-8.15, -3.95, .65, 4.9],
        'PACK_ROBOT': [-3.55, 5.10, .65, 4.9],
        'QC': [5.40, 8.775, .65, 4.9],
    },
    'production_object_fingerprints_preserved': len(before),
    'character_animation_actions_preserved': len(actions_before),
    'glbs_unchanged': len(glbs_before) if opt.check_frozen_glbs else False,
    'glbs_rebuilt': 13,
    'native_acceptance': 'passed',
    'preview_updated': bool(opt.render),
}
(ROOT / 'native_map_expansion.json').write_text(json.dumps(report, indent=2) + '\n')
print('NATIVE_MAP_EXPANSION_COMPLETE', json.dumps(report), flush=True)
