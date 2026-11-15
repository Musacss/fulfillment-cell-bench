"""Re-export both baked character rigs without rebuilding their geometry."""
import bpy,sys,argparse
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from character_motion import reset_pose
p=argparse.ArgumentParser();p.add_argument('--output',required=True);opt=p.parse_args(sys.argv[sys.argv.index('--')+1:]);out=Path(opt.output)
sc=bpy.context.scene
for label,prefix,file in [('Warehouse worker','WORKER','warehouse_worker'),('Humanoid robot','ROBOT','humanoid_robot')]:
 col=bpy.data.collections['CHARACTERS / '+label];rig=bpy.data.objects[prefix+'_Rig'];oldloc=rig.location.copy();rig.location=(0,0,0);rig.animation_data.action=None;reset_pose(rig)
 for track in rig.animation_data.nla_tracks:track.mute=False
 sc.frame_set(0);bpy.ops.object.select_all(action='DESELECT')
 for ob in col.objects:ob.select_set(True)
 bpy.context.view_layer.objects.active=rig;meshes=[o for o in col.objects if o.type=='MESH']
 for ob in meshes:ob.parent=None
 bpy.ops.export_scene.gltf(filepath=str(out/'modules'/str(file+'.glb')),export_format='GLB',use_selection=True,export_yup=True,export_extras=True,export_animations=True,export_animation_mode='NLA_TRACKS',export_nla_strips=True,export_force_sampling=True,export_frame_range=False,export_skins=True,export_def_bones=False,export_cameras=False,export_lights=False)
 for ob in meshes:ob.parent=rig
 for track in rig.animation_data.nla_tracks:track.mute=True
 rig.location=oldloc;rig.animation_data.action=bpy.data.actions[('Worker' if prefix=='WORKER' else 'Robot')+'_Idle'];sc.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
print('CHARACTERS_EXPORT_COMPLETE',flush=True)
