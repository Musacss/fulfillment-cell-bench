"""Re-export both 30-FPS articulated character rigs cleanly without mutating .blend files."""
import argparse
import sys
import bpy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from character_motion import reset_pose

CONTRACT_CLIPS = {
    'WORKER': [
        'Idle', 'Walk', 'CarryIdle', 'Reach', 'PickUp', 'PlaceDown', 'CarryWalk',
        'Prepare', 'Pick', 'Pack', 'Inspect', 'Assist', 'Break',
        'Prepare_Oversize', 'Pick_Oversize', 'Pack_Oversize', 'Inspect_Oversize',
    ],
    'ROBOT': [
        'Idle', 'Walk', 'CarryIdle', 'Reach', 'PickUp', 'PlaceDown', 'CarryWalk',
        'RobotPack', 'Jammed', 'Service', 'Offline',
        'RobotPack_Oversize', 'Jammed_Oversize', 'Service_Oversize',
    ],
}


def main():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=str(Path(__file__).resolve().parent.parent))
    opt = parser.parse_args(argv)
    out = Path(opt.output)
    (out / 'modules').mkdir(parents=True, exist_ok=True)

    sc = next((s for s in bpy.data.scenes if s.name.startswith('FRAME BY FRAME /')), bpy.context.scene)
    bpy.context.window.scene = sc

    specs = [
        ('FRAME ANIMATIONS / Worker', 'CHARACTERS / Warehouse worker', 'WORKER', 'warehouse_worker'),
        ('FRAME ANIMATIONS / Robot', 'CHARACTERS / Humanoid robot', 'ROBOT', 'humanoid_robot'),
    ]
    for fbf_col_name, legacy_col_name, prefix, file in specs:
        col = bpy.data.collections.get(fbf_col_name) or bpy.data.collections.get(legacy_col_name)
        rig = bpy.data.objects.get(prefix + '_Rig') or bpy.data.objects.get('FBF_' + prefix + '_Rig')
        if col is None or rig is None:
            raise RuntimeError(f'Missing actor collection or rig for {prefix}')
        old_loc = rig.location.copy()
        old_rot = rig.rotation_euler.copy()
        old_scale = rig.scale.copy()
        rig.location = (0, 0, 0)
        rig.rotation_euler = (0, 0, 0)
        rig.scale = (1, 1, 1)
        rig.animation_data.action = None
        reset_pose(rig)

        allowed = set(CONTRACT_CLIPS[prefix])
        for track in list(rig.animation_data.nla_tracks):
            if track.name not in allowed:
                rig.animation_data.nla_tracks.remove(track)
            else:
                track.mute = False

        sc.frame_set(0)
        bpy.ops.object.select_all(action='DESELECT')
        selected = []
        for ob in col.objects:
            if ob.get('handling_prop') == 'support' or 'DemoSupport' in ob.name:
                continue
            for target in (ob, ob.data):
                if target is None:
                    continue
                for bad in ('handling_prop', 'demo_only'):
                    if target.get(bad) is not None:
                        del target[bad]
                    sp = target.bl_system_properties_get() if hasattr(target, 'bl_system_properties_get') else None
                    if sp is not None and bad in sp:
                        del sp[bad]
            ob.select_set(True)
            selected.append(ob)
        bpy.context.view_layer.objects.active = rig

        mesh_parents = []
        for ob in selected:
            if ob.type == 'MESH':
                mesh_parents.append((ob, ob.parent, ob.matrix_world.copy()))
                world = ob.matrix_world.copy()
                ob.parent = None
                ob.matrix_world = world

        bpy.ops.export_scene.gltf(
            filepath=str(out / 'modules' / f'{file}.glb'),
            export_format='GLB',
            use_selection=True,
            use_active_scene=True,
            export_yup=True,
            export_extras=True,
            export_animations=True,
            export_animation_mode='NLA_TRACKS',
            export_nla_strips=True,
            export_force_sampling=True,
            export_frame_step=1,
            export_frame_range=False,
            export_optimize_animation_size=False,
            export_optimize_animation_keep_anim_armature=True,
            export_skins=True,
            export_def_bones=False,
            export_cameras=False,
            export_lights=False,
        )

        for ob, parent, world in mesh_parents:
            ob.parent = parent
            ob.matrix_world = world
        for track in rig.animation_data.nla_tracks:
            track.mute = True
        rig.location = old_loc
        rig.rotation_euler = old_rot
        rig.scale = old_scale

    # Never save over warehouse_environment.blend or read-only source .blend files!
    print('CHARACTERS_EXPORT_COMPLETE', flush=True)


if __name__ == '__main__':
    main()
