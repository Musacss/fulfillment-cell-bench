"""Update the editable native map without rebuilding the frozen GLBs.

Run Blender in background with warehouse_environment.blend and this script.
The browser applies the matching instance corrections in studio/src/map-*.js.
"""
import ast
import json
from pathlib import Path
import bpy

ROOT=Path(__file__).resolve().parent.parent
finish=ROOT/'scripts/flexsim_finish.py'
tree=ast.parse(finish.read_text())
tree.body=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom,ast.FunctionDef))]
ns={'__file__':str(finish),'ROOT':ROOT,'OUT':ROOT,'sc':bpy.context.scene}
exec(compile(tree,str(finish),'exec'),ns)
before=ns['snapshot_actions']()
rigged_before={o.name:tuple((m.name,m.type,m.object.name if m.type=='ARMATURE' and m.object else None) for m in o.modifiers)
               for o in bpy.data.objects if o.type=='MESH' and any(m.type=='ARMATURE' for m in o.modifiers)}
bpy.ops.object.select_all(action='DESELECT')

cabinet=bpy.data.objects.get('UTILITY_CABINET')
if cabinet:
    for child in reversed(list(cabinet.children_recursive)):
        bpy.data.objects.remove(child,do_unlink=True)
    bpy.data.objects.remove(cabinet,do_unlink=True)

rework=bpy.data.objects.get('BENCH_REWORK')
if rework:
    for child in list(rework.children_recursive):
        if child.name.startswith('ANCHOR_'):
            matrix=child.matrix_world.copy();child.parent=rework;child.matrix_world=matrix
    for child in reversed(list(rework.children_recursive)):
        if not child.name.startswith('ANCHOR_'):
            bpy.data.objects.remove(child,do_unlink=True)

# Preserve the slab, replace the authored floor decals and grid as a group.
old=bpy.data.objects.get('ENV_FLOOR_AND_GRID')
if old:
    for child in list(old.children_recursive):
        if child.name.startswith(('Raised concrete slab','Lower reveal')):
            matrix=child.matrix_world.copy();child.parent=None;child.matrix_world=matrix
    for child in reversed(list(old.children_recursive)):
        bpy.data.objects.remove(child,do_unlink=True)
    bpy.data.objects.remove(old,do_unlink=True)
api=ns['api_functions']();api['M']=ns['palette']()
ns['floor_and_grid'](api)

# The robot top was correctly parented natively but was outside the overlay
# collection used for selection export. Inherit the collection and flag.
table=bpy.data.objects.get('VIS_ROBOT_PACK_TABLE')
overlay=bpy.data.collections.get('INTEGRATION / Stations and anchors')
if table and overlay:
    for child in table.children_recursive:
        child['integration_visual']=True
        for collection in list(child.users_collection):collection.objects.unlink(child)
        overlay.objects.link(child)
ns['clean_geometry']()
bpy.context.view_layer.update()
after=ns['snapshot_actions']()
assert before==after,'Character animation data changed'
for name,modifiers in rigged_before.items():
    obj=bpy.data.objects[name]
    assert tuple((m.name,m.type,m.object.name if m.type=='ARMATURE' and m.object else None) for m in obj.modifiers)==modifiers,('Skin binding changed',name)
arrows=[o for o in bpy.data.objects if o.name.startswith('WALKWAY_DIRECTION')]
assert len(arrows)==3
assert sorted(round(o.location.x,5) for o in arrows)==[-11.8,0,11.8]
assert not [o for o in bpy.data.objects if o.name.startswith(('ZEBRA_','WAYFINDING_','UTILITY_CABINET'))]
bpy.context.preferences.filepaths.save_version=0
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'warehouse_environment.blend'))
(ROOT/'native_map_fixes.json').write_text(json.dumps({
    'passed':True,'cabinet_removed':True,'rework_is_standalone_roller_section':True,
    'arrow_centers_x_m':[-11.8,0,11.8],'zebras':0,'hold_zone_x_m':[9,11],
    'robot_top_export_collection_corrected':True,'character_actions_unchanged':len(after),
    'glb_files_rebuilt':False,
},indent=2)+'\n')
print('NATIVE_MAP_CORRECTIONS_COMPLETE',flush=True)
