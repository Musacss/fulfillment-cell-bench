"""Render the actual activity clips and reusable geometry, without saving the scene."""
import bpy, sys, argparse
from pathlib import Path
from mathutils import Vector

p=argparse.ArgumentParser()
p.add_argument('--output',required=True)
p.add_argument('--mode',choices=['activities','catalog','environment'],required=True)
opt=p.parse_args(sys.argv[sys.argv.index('--')+1:])
out=Path(opt.output);out.mkdir(parents=True,exist_ok=True)
sc=bpy.context.scene
sc.render.engine='CYCLES';sc.cycles.samples=32;sc.cycles.use_denoising=False
sc.render.resolution_percentage=100
sc.view_settings.view_transform='AgX';sc.view_settings.look='AgX - Medium High Contrast'

if opt.mode=='environment':
    for prefix in ['WORKER','ROBOT']:
        rig=bpy.data.objects[prefix+'_Rig']
        for track in rig.animation_data.nla_tracks:track.mute=True
        rig.animation_data.action=bpy.data.actions[prefix.title()+'_Idle']
    bpy.data.collections['INTEGRATION / Visual templates'].hide_render=True
    sc.frame_set(1)
    sc.camera=bpy.data.objects['CAMERA_OVERVIEW']
    sc.render.resolution_x=1600;sc.render.resolution_y=1100
    sc.render.filepath=str(out/'environment_overview.png');bpy.ops.render.render(write_still=True)
else:
    for ob in sc.objects:ob.hide_render=True
    stage=bpy.data.collections.new('VISUAL_REVIEW_STAGE');sc.collection.children.link(stage)
    def link(ob):stage.objects.link(ob);return ob
    def instance(name,position=(0,0,0)):
        src=bpy.data.objects['VIS_'+name]
        group=link(bpy.data.objects.new('Review_'+name,None));group.location=position
        for child in src.children:
            ob=child.copy();link(ob);ob.parent=group;ob.hide_render=False
        return group
    mat=bpy.data.materials.new('Visual review floor');mat.use_nodes=True
    bsdf=mat.node_tree.nodes.get('Principled BSDF');bsdf.inputs['Base Color'].default_value=(.105,.145,.14,1);bsdf.inputs['Roughness'].default_value=.94
    mesh=bpy.data.meshes.new('Review floor');mesh.from_pydata([(-200,-200,-.003),(200,-200,-.003),(200,200,-.003),(-200,200,-.003)],[],[(0,1,2,3)]);mesh.materials.append(mat)
    link(bpy.data.objects.new('Review floor',mesh))
    world=bpy.data.worlds.new('Visual review world');world.use_nodes=True
    world.node_tree.nodes['Background'].inputs[0].default_value=(.30,.37,.35,1);world.node_tree.nodes['Background'].inputs[1].default_value=.48;sc.world=world
    for name,pos,power,size in [('Key',(-3,-4,5),420,4),('Fill',(3,-2,3),160,3),('Rim',(1,3,4),470,3)]:
        d=bpy.data.lights.new('Review '+name,'AREA');d.energy=power;d.shape='DISK';d.size=size
        ob=link(bpy.data.objects.new('Review '+name,d));ob.location=pos;ob.rotation_euler=(Vector((0,0,1))-ob.location).to_track_quat('-Z','Y').to_euler()
    d=bpy.data.cameras.new('Visual review camera');camera=link(bpy.data.objects.new('Visual review camera',d));d.type='ORTHO';sc.camera=camera
    def shot(name,pos,target,scale,size):
        camera.location=pos;camera.rotation_euler=(Vector(target)-camera.location).to_track_quat('-Z','Y').to_euler();d.ortho_scale=scale
        sc.render.resolution_x,sc.render.resolution_y=size;sc.render.filepath=str(out/name);bpy.ops.render.render(write_still=True)
    if opt.mode=='catalog':
        for kind,x in [('regular',-.65),('fragile',0),('oversize',.65)]:instance('order_'+kind,(x,.2,0))
        instance('order_tray',(-.35,-.52,0));instance('reserved_slot',(.35,-.52,0))
        shot('asset_catalog.png',(2.6,-5,3.8),(0,-.05,.11),2.22,(1400,980))
    else:
        bench=instance('manual_bench',(0,-.34,0))
        marker=None
        cases=[('prepare','worker','Prepare',24),('pick','worker','Pick',36),('pack','worker','Pack',26),('inspect','worker','Inspect',33),('assist','worker','Assist',29),('break','worker','Break',35),('robot_pack_oversize','robot','RobotPack_Oversize',27),('jammed','robot','Jammed',0)]
        for name,kind,clip,frame in cases:
            for title in ['Warehouse worker','Humanoid robot']:
                for ob in bpy.data.collections['CHARACTERS / '+title].objects:ob.hide_render=True
            prefix=kind.upper();rig=bpy.data.objects[prefix+'_Rig'];rig.location=(0,0,0)
            for ob in bpy.data.collections['CHARACTERS / '+('Warehouse worker' if kind=='worker' else 'Humanoid robot')].objects:ob.hide_render='_DemoSupport' in ob.name
            for track in rig.animation_data.nla_tracks:track.mute=True
            rig.animation_data.action=bpy.data.actions[prefix.title()+'_'+clip];sc.frame_set(frame)
            for child in bench.children:child.hide_render=name in ['assist','break']
            if marker:
                for child in marker.children:bpy.data.objects.remove(child,do_unlink=True)
                bpy.data.objects.remove(marker,do_unlink=True);marker=None
            if name in ['jammed','assist','break']:marker=instance('status_'+{'jammed':'jammed','assist':'service','break':'break'}[name],(0,0,2.03))
            shot(name+'.png',(2.8,-6,2.8),(0,-.08,1.00),2.40,(560,700))
print('VISUAL_REVIEW_RENDER_COMPLETE',opt.mode,flush=True)
