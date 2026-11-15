"""Render actual native actions as full-rate PNG sequences and review stills."""
import bpy
from mathutils import Vector
from pathlib import Path

OUT=Path(__file__).resolve().parent.parent/'animations_frame_by_frame'


def setup():
    sc=next(s for s in bpy.data.scenes if s.name.startswith('FRAME BY FRAME /'))
    bpy.context.window.scene=sc
    if sc.camera is None:
        data=bpy.data.cameras.new('FBF Preview camera')
        cam=bpy.data.objects.new('FBF Preview camera',data)
        sc.collection.objects.link(cam)
        data.type='ORTHO'
        data.ortho_scale=2.95
        cam.location=(1.5,-7,3.5)
        cam.rotation_euler=(Vector((0,-.12,.98))-cam.location).to_track_quat('-Z','Y').to_euler()
        sc.camera=cam
    sc.render.engine='BLENDER_WORKBENCH'
    sc.render.resolution_x=960
    sc.render.resolution_y=720
    sc.render.resolution_percentage=100
    sc.render.image_settings.file_format='PNG'
    sc.render.film_transparent=False
    sc.display.shading.light='STUDIO'
    sc.display.shading.color_type='MATERIAL'
    sc.display.shading.show_shadows=True
    sc.display.shading.show_cavity=True
    sc.display.shading.cavity_type='BOTH'
    sc.display.shading.curvature_ridge_factor=1.2
    sc.display.shading.curvature_valley_factor=1.1
    sc.display.shading.background_type='WORLD'
    if sc.world is None:
        sc.world=bpy.data.worlds.new('FBF Preview world')
    sc.world.color=(.055,.07,.09)
    sc.view_settings.view_transform='Standard'
    return sc


def assign(rig,action):
    rig.animation_data.action=action
    rig.animation_data.action_slot=action.slots[0]
    for tr in rig.animation_data.nla_tracks:
        tr.mute=True


def shot(clip,frame,path,sequence=False):
    sc=setup()
    rigs=[ob for ob in sc.objects if ob.type=='ARMATURE']
    for rig in rigs:
        kind='Worker' if 'WORKER' in rig.name else 'Robot'
        name='RobotPack' if kind=='Robot' and clip=='Pack' else clip
        action=bpy.data.actions.get('FBF_'+kind+'_'+name) or bpy.data.actions['FBF_'+kind+'_Idle']
        assign(rig,action)
    sc.frame_set(frame)
    sc.render.filepath=str(path)
    bpy.ops.render.render(write_still=True)


def sequence(clip):
    durations={'Pick':4.,'Pack':3.,'Inspect':3.6}
    sc=setup()
    sc.render.resolution_x=720
    sc.render.resolution_y=540
    folder=OUT/'frames'/clip
    folder.mkdir(parents=True,exist_ok=True)
    # RobotPack originally lasts 2.8s; both actors are sampled by normalized phase.
    for frame in range(round(durations[clip]*30)+1):
        for rig in [o for o in sc.objects if o.type=='ARMATURE']:
            kind='Worker' if 'WORKER' in rig.name else 'Robot'
            name='RobotPack' if kind=='Robot' and clip=='Pack' else clip
            action=bpy.data.actions['FBF_'+kind+'_'+name]
            assign(rig,action)
        sc.frame_set(frame)
        # RobotPack ends at frame 84 and holds its last pose for the final six frames.
        sc.render.filepath=str(folder/f'{frame:04d}.png')
        bpy.ops.render.render(write_still=True)
    print('PNG_SEQUENCE_COMPLETE',clip,frame+1,flush=True)
