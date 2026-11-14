"""Replace baked actions and grip anchors while keeping both authored meshes intact."""
import bpy,sys,argparse,json
from pathlib import Path
root=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(root/'scripts'))
from character_motion import create_motion,reset_pose
p=argparse.ArgumentParser();p.add_argument('--output',required=True);opt=p.parse_args(sys.argv[sys.argv.index('--')+1:]);out=Path(opt.output)
for kind,title,prefix,asset in [('worker','Warehouse worker','WORKER','warehouse_worker'),('robot','Humanoid robot','ROBOT','humanoid_robot')]:
 col=bpy.data.collections['CHARACTERS / '+title];rig=bpy.data.objects[prefix+'_Rig'];body=bpy.data.objects[prefix+'_Body'];location=rig.location.copy();rig.location=(0,0,0)
 rig.animation_data.action=None
 for track in list(rig.animation_data.nla_tracks):rig.animation_data.nla_tracks.remove(track)
 reset_pose(rig);bpy.context.scene.frame_set(1);bpy.context.view_layer.update()
 for ob in list(col.objects):
  if ob.get('handling_prop') or ob.name.startswith('ATTACH_'+prefix+'_HAND_'):bpy.data.objects.remove(ob,do_unlink=True)
 def link(ob):col.objects.link(ob);ob[kind+'_asset']=True;return ob
 extras=[(b.name,b.head_local.copy(),b.tail_local.copy(),b.parent.name) for b in rig.data.bones if b.name.startswith(('finger','thumb'))]
 clips,grip=create_motion(rig,body,col,link,kind,extras)
 rig.location=location;rig.animation_data.action=bpy.data.actions[('Worker' if kind=='worker' else 'Robot')+'_Idle'];bpy.context.scene.frame_set(1)
 path=out/(kind+'_manifest.json');manifest=json.loads(path.read_text());manifest['version']='0.2.2';manifest['clips']=clips;manifest['box_handling']=grip;path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2));(root/'config/characters'/str(asset+'.json')).write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
 print(kind.upper()+'_THUMB_POSE_REBAKED',json.dumps(grip),flush=True)
bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
print('THUMB_REBAKE_COMPLETE',flush=True)
