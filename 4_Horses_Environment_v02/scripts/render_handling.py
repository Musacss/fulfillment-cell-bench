"""Portraits of the actual baked box handling actions, without altering the .blend."""
import bpy,sys,argparse
from pathlib import Path
from mathutils import Vector
p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--quick',action='store_true');p.add_argument('--orientation-only',action='store_true');p.add_argument('--thumb-detail-only',action='store_true');p.add_argument('--comparisons-only',action='store_true');p.add_argument('--contact-only',action='store_true');p.add_argument('--actor',choices=['all','worker','robot'],default='all');opt=p.parse_args(sys.argv[sys.argv.index('--')+1:]);out=Path(opt.output)
sc=bpy.context.scene
for ob in sc.objects:ob.hide_render=True
stage=bpy.data.collections.new('HANDLING_RENDER_STAGE');sc.collection.children.link(stage)
def link(ob):stage.objects.link(ob);return ob
mat=bpy.data.materials.new('Handling backdrop');mat.use_nodes=True;pp=mat.node_tree.nodes.get('Principled BSDF');pp.inputs['Base Color'].default_value=(.105,.145,.14,1);pp.inputs['Roughness'].default_value=.94
plane=bpy.data.meshes.new('Handling floor');plane.from_pydata([(-200,-200,-.001),(200,-200,-.001),(200,200,-.001),(-200,200,-.001)],[],[(0,1,2,3)]);plane.materials.append(mat);link(bpy.data.objects.new('Handling floor',plane))
world=bpy.data.worlds.new('Handling portrait world');world.use_nodes=True;world.node_tree.nodes['Background'].inputs[0].default_value=(.30,.37,.35,1);world.node_tree.nodes['Background'].inputs[1].default_value=.48;sc.world=world
for name,pos,power,size in [('Key',(-3,-4,5),420,4),('Fill',(3,-2,3),160,3),('Rim',(1,3,4),470,3)]:
 d=bpy.data.lights.new('Handling '+name,'AREA');d.energy=power;d.shape='DISK';d.size=size;o=link(bpy.data.objects.new('Handling '+name,d));o.location=pos;o.rotation_euler=(Vector((0,0,1))-o.location).to_track_quat('-Z','Y').to_euler()
d=bpy.data.cameras.new('Handling portrait camera');cam=link(bpy.data.objects.new('Handling portrait camera',d));d.type='ORTHO';sc.camera=cam
sc.render.engine='CYCLES';sc.cycles.samples=32 if opt.quick else 96;sc.cycles.use_denoising=False;sc.render.resolution_percentage=100;sc.view_settings.view_transform='AgX';sc.view_settings.look='AgX - Medium High Contrast'
actors={}
for kind,title,prefix in [('worker','Warehouse worker','Worker'),('robot','Humanoid robot','Robot')]:
 col=bpy.data.collections['CHARACTERS / '+title];rig=bpy.data.objects[prefix.upper()+'_Rig'];rig.location=(0,0,0)
 actors[kind]=(col,rig,prefix)
def render(name,kinds,action='CarryIdle',frame=1,detail=False,front=False,back=False):
 for kind,(col,rig,prefix) in actors.items():
  for ob in col.objects:ob.hide_render=kind not in kinds
  rig.location=(-.52 if kind=='worker' else .52,0,0) if len(kinds)==2 else (0,0,0)
  rig.animation_data.action=bpy.data.actions[prefix+'_'+action]
 sc.frame_set(frame)
 if len(kinds)==2:
  sc.render.resolution_x=1100;sc.render.resolution_y=1000;d.ortho_scale=2.40;target=Vector((0,-.07,.94));pos=(1,-8,2.2)
  if detail:sc.render.resolution_x=1400;sc.render.resolution_y=680;d.ortho_scale=1.75;target=Vector((0,-.25,1.12));pos=(0,-6,2.25)
 elif detail:
  sc.render.resolution_x=1000;sc.render.resolution_y=850;d.ortho_scale=.77;target=Vector((0,-.25,1.10));pos=(1.5,-4,2.1)
 else:
  sc.render.resolution_x=800;sc.render.resolution_y=960;d.ortho_scale=2.32;target=Vector((0,-.04,.94));pos=(-3,6,2.55) if back else (0,-6,1.6) if front else (3,-6,2.65)
 if opt.quick:sc.render.resolution_percentage=65
 cam.location=pos;cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler();sc.render.filepath=str(out/name);bpy.ops.render.render(write_still=True)
if opt.comparisons_only:
 render('handling_comparison.png',['worker','robot'])
 render('thumb_orientation_comparison.png',['worker','robot'],detail=True)
elif opt.thumb_detail_only:
 render('thumb_orientation_comparison.png',['worker','robot'],detail=True)
elif opt.quick:
 render('grip_check_comparison.png',['worker','robot'])
 render('grip_check_robot.png',['robot'],detail=True)
 render('grip_check_worker.png',['worker'],detail=True)
 render('grip_check_reach.png',['worker','robot'],'Reach',36)
else:
 if not opt.orientation_only:
  render('robot_preview.png',['robot'],'Idle');render('robot_front.png',['robot'],'Idle',front=True);render('robot_back.png',['robot'],'Idle',back=True)
  render('worker_robot_comparison.png',['worker','robot'],'Idle')
 if opt.actor=='all':render('handling_comparison.png',['worker','robot'])
 for kind in (['worker','robot'] if opt.actor=='all' else [opt.actor]):
  render(kind+'_carry.png',[kind]);render(kind+'_pickup.png',[kind],'PickUp',68);render(kind+'_place.png',[kind],'PlaceDown',62)
  render(kind+'_carry_walk.png',[kind],'CarryWalk',8)
  if not opt.contact_only:render(kind+'_reach.png',[kind],'Reach',36)
  render(kind+'_grip_detail.png',[kind],detail=True)
 if not opt.orientation_only and opt.actor in ['all','robot']:render('robot_walk.png',['robot'],'Walk',8)
 if opt.actor in ['all','robot']:render('robot_joints.png',['robot'],detail=True)
print('HANDLING_RENDER_COMPLETE',flush=True)
