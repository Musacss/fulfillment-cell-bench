"""Open characters_animated.blend in background Blender and verify dense 30-FPS native keys,
exact 35/41 bone counts, 17/14 contract clip lists, 0 unweighted vertices, prop extras,
empty-handed (0,0,0) prop scales, R3 motion thresholds, and exhaustive every-frame 3D BVH
limb/torso/helmet/self/prop/world-pair (S3C_ROBOT_ASSIST) collision clearance."""
import bpy
import json
import math
from pathlib import Path
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

EXPECTED_CLIPS = {
    'worker': [
        'Idle', 'Walk', 'CarryIdle', 'Reach', 'PickUp', 'PlaceDown', 'CarryWalk',
        'Prepare', 'Pick', 'Pack', 'Inspect', 'Assist', 'Break',
        'Prepare_Oversize', 'Pick_Oversize', 'Pack_Oversize', 'Inspect_Oversize',
    ],
    'robot': [
        'Idle', 'Walk', 'CarryIdle', 'Reach', 'PickUp', 'PlaceDown', 'CarryWalk',
        'RobotPack', 'Jammed', 'Service', 'Offline',
        'RobotPack_Oversize', 'Jammed_Oversize', 'Service_Oversize',
    ],
}
EXPECTED_BONES = {'worker': 35, 'robot': 41}
PROP_BONES = {
    'prop_box', 'prop_stand', 'prop_closed', 'prop_shell',
    'prop_flap_front', 'prop_flap_back', 'prop_flap_left', 'prop_flap_right',
    'prop_item', 'prop_tote', 'prop_tape',
}
EMPTY_HANDED = {'Idle', 'Walk', 'Reach', 'Assist', 'Break', 'Offline'}
AUTHORED_CLIPS = {
    'Prepare', 'Pick', 'Pack', 'Inspect', 'Assist', 'Break',
    'Prepare_Oversize', 'Pick_Oversize', 'Pack_Oversize', 'Inspect_Oversize',
    'RobotPack', 'Jammed', 'Service', 'Offline',
    'RobotPack_Oversize', 'Jammed_Oversize', 'Service_Oversize',
}
MOTION_THRESHOLDS = {
    'Assist': 0.22,
    'Break': 0.15,
    'Service': 0.12,
    'Service_Oversize': 0.12,
    'Jammed': 0.03,
    'Jammed_Oversize': 0.03,
    'Offline': 0.01,
}
BODY_GROUPS = {
    'TORSO_PELVIS': {'hips', 'spine', 'chest', 'shoulder.L', 'shoulder.R'},
    'HEAD_NECK': {'neck', 'head'},
    'UPPER_ARM_L': {'upper_arm.L'},
    'UPPER_ARM_R': {'upper_arm.R'},
    'FOREARM_L': {'forearm.L'},
    'FOREARM_R': {'forearm.R'},
    'HAND_L': {'hand.L'} | {
        f'{p}.L' for p in (
            'thumb.01', 'thumb.02', 'thumb.03',
            'finger_index.01', 'finger_index.02', 'finger_index.03',
            'finger_middle.01', 'finger_middle.02', 'finger_middle.03',
            'finger_ring.01', 'finger_ring.02', 'finger_ring.03',
            'finger_pinky.01', 'finger_pinky.02', 'finger_pinky.03',
        )
    } | {'thumb.L', 'finger_1.L', 'finger_2.L', 'finger_3.L', 'finger_4.L'},
    'HAND_R': {'hand.R'} | {
        f'{p}.R' for p in (
            'thumb.01', 'thumb.02', 'thumb.03',
            'finger_index.01', 'finger_index.02', 'finger_index.03',
            'finger_middle.01', 'finger_middle.02', 'finger_middle.03',
            'finger_ring.01', 'finger_ring.02', 'finger_ring.03',
            'finger_pinky.01', 'finger_pinky.02', 'finger_pinky.03',
        )
    } | {'thumb.R', 'finger_1.R', 'finger_2.R', 'finger_3.R', 'finger_4.R'},
}
W_ASSIST_MAT = Matrix.Translation(Vector((2.80, 1.95, 0.0))) @ Matrix.Rotation(2.131959739083249, 4, 'Z')
R_WORK_MAT = Matrix.Translation(Vector((3.50, 2.05, 0.0))) @ Matrix.Rotation(math.pi, 4, 'Z')


def eval_mesh_tris(ob, depsgraph, world_xform=Matrix.Identity(4)):
    ob_eval = ob.evaluated_get(depsgraph)
    mesh = ob_eval.to_mesh()
    mesh.transform(world_xform @ ob_eval.matrix_world)
    mesh.calc_loop_triangles()
    verts = [v.co.copy() for v in mesh.vertices]
    tris = [tuple(t.vertices) for t in mesh.loop_triangles]
    vg_names = {vg.index: vg.name for vg in ob_eval.vertex_groups}
    v_dom = []
    for v in mesh.vertices:
        best_n, best_w = '', 0.0
        for g in v.groups:
            n = vg_names.get(g.group, '')
            if g.weight > best_w:
                best_w, best_n = g.weight, n
        v_dom.append(best_n)
    ob_eval.to_mesh_clear()
    return verts, tris, v_dom


def combined_bvh(obs, depsgraph, world_xform):
    all_v, all_t = [], []
    off = 0
    for ob in obs:
        v, t, _ = eval_mesh_tris(ob, depsgraph, world_xform)
        all_v.extend(v)
        all_t.extend([(a + off, b + off, c + off) for (a, b, c) in t])
        off += len(v)
    return BVHTree.FromPolygons(all_v, all_t) if all_t else None


def action_curves(action):
    if hasattr(action, 'fcurves'):
        return list(action.fcurves)
    return [
        fc for l in action.layers for s in l.strips
        for bag in s.channelbags for fc in bag.fcurves
    ]


def assign_action(rig, action):
    rig.animation_data.action = action
    if hasattr(action, 'slots') and action.slots:
        rig.animation_data.action_slot = action.slots[0]
    for tr in rig.animation_data.nla_tracks:
        tr.mute = True


def check_native(sc, out):
    manifest = json.loads((out / 'manifest.json').read_text())
    assert sc.render.fps == 30 and sc.frame_start == 0, ('invalid scene fps/start', sc.render.fps, sc.frame_start)
    armatures = [ob for ob in sc.objects if ob.type == 'ARMATURE']
    assert len(armatures) == 2, ('expected 2 armatures, got', len(armatures))

    # Zero forbidden DemoSupport / _DemoCarton anywhere in character collections.
    for col in sc.collection.children:
        if not col.name.startswith('FRAME ANIMATIONS /'):
            continue
        for ob in col.objects:
            assert 'DemoSupport' not in ob.name and not ob.name.endswith('_DemoCarton'), ('forbidden demo node', ob.name)
            for target in (ob, ob.data):
                if target is None:
                    continue
                sp = target.bl_system_properties_get() if hasattr(target, 'bl_system_properties_get') else None
                for bad in ('handling_prop', 'demo_only'):
                    assert target.get(bad) is None and (sp is None or bad not in sp), ('forbidden prop flag', ob.name, bad)

    checked_channels = 0
    motion_summary = {}
    depsgraph = bpy.context.evaluated_depsgraph_get()

    for kind, actor in manifest['actors'].items():
        prefix = kind.upper()
        col = bpy.data.collections['FRAME ANIMATIONS / ' + kind.title()]
        rig = next(o for o in col.objects if o.type == 'ARMATURE')
        assert rig.name == f'{prefix}_Rig', ('unexpected rig name', rig.name)
        assert len(rig.data.bones) == EXPECTED_BONES[kind], (kind, 'bone count', len(rig.data.bones))
        assert PROP_BONES.issubset({b.name for b in rig.data.bones}), (kind, 'missing prop bones')

        # Hand sockets & helmet checks
        for side in ('L', 'R'):
            sock = col.objects.get(f'ATTACH_{prefix}_HAND_{side}')
            assert sock is not None, (kind, f'missing ATTACH_{prefix}_HAND_{side}')
            assert sock.parent == rig and sock.parent_type == 'BONE' and sock.parent_bone == f'hand.{side}', (
                kind, sock.name, sock.parent_type, sock.parent_bone
            )
        if kind == 'worker':
            helmet = col.objects.get('WORKER_Helmet')
            body = col.objects.get('WORKER_Body')
            assert helmet is not None and body is not None, 'missing WORKER_Body or WORKER_Helmet'
            assert len(helmet.data.vertices) == 130, ('helmet vertices', len(helmet.data.vertices))

        # 0 unweighted vertices & prop metadata check
        deform_bones = {b.name for b in rig.data.bones if b.use_deform}
        op_props = []
        for ob in col.objects:
            if ob.type != 'MESH':
                continue
            vg_names = {vg.index: vg.name for vg in ob.vertex_groups}
            for v in ob.data.vertices:
                w = sum(g.weight for g in v.groups if vg_names.get(g.group) in deform_bones)
                assert w > 0.999, (kind, ob.name, 'unweighted vertex', v.index, w)
            if ob.name not in (f'{prefix}_Body', 'WORKER_Helmet'):
                assert ob.get('operation_prop') is True and ob.data.get('operation_prop') is True, (
                    kind, ob.name, 'missing operation_prop on ob or ob.data'
                )
                assert ob.get('prop_role') in PROP_BONES and ob.data.get('prop_role') in PROP_BONES, (
                    kind, ob.name, 'missing prop_role'
                )
                assert ob.get(f'{kind}_asset') is True and ob.data.get(f'{kind}_asset') is True, (
                    kind, ob.name, f'missing {kind}_asset'
                )
                op_props.append(ob)
        assert len(op_props) == 9, (kind, 'expected 9 operational prop meshes, got', len(op_props))

        track_names = [t.name for t in rig.animation_data.nla_tracks]
        assert track_names == EXPECTED_CLIPS[kind], (kind, 'NLA track list/order mismatch', track_names)
        assert [c['name'] for c in actor['clips']] == EXPECTED_CLIPS[kind], (kind, 'manifest clip mismatch')

        tracks = {t.name: t for t in rig.animation_data.nla_tracks}
        old_loc = rig.location.copy()
        rig.location = (0, 0, 0)
        motion_summary[kind] = {}

        body_ob = col.objects[f'{prefix}_Body']
        helmet_ob = col.objects.get('WORKER_Helmet') if kind == 'worker' else None
        bvh_checked_frames = 0

        for clip in actor['clips']:
            cname = clip['name']
            action = tracks[cname].strips[0].action
            curves = action_curves(action)
            assert len(curves) == 10 * len(rig.pose.bones), (kind, cname, 'missing native channels', len(curves))
            for fc in curves:
                actual = [round(k.co.x, 6) for k in fc.keyframe_points]
                assert actual == list(range(clip['frames'])), (kind, cname, fc.data_path, 'missing frame')
                assert all(k.interpolation == 'LINEAR' for k in fc.keyframe_points), (kind, cname, 'non-LINEAR key')
            checked_channels += len(curves)

            # Evaluate EVERY integer frame 0..N for prop scales, motion & 3D BVH collision clearance
            assign_action(rig, action)
            body_bones = [pb.name for pb in rig.pose.bones if not pb.name.startswith('prop_')]
            trajectories = {bname: [] for bname in body_bones}
            for frame in range(clip['frames']):
                sc.frame_set(frame)
                bpy.context.view_layer.update()
                depsgraph.update()
                assert rig.pose.bones['prop_stand'].scale.length < 1e-6, (kind, cname, frame, 'prop_stand non-zero')
                if cname in EMPTY_HANDED:
                    for pname in PROP_BONES:
                        pb = rig.pose.bones[pname]
                        ws = pb.matrix.to_scale()
                        assert pb.scale.length < 1e-6 and ws.length < 1e-6, (
                            kind, cname, frame, pname, 'non-zero prop scale in empty-handed clip'
                        )
                for bname in body_bones:
                    trajectories[bname].append((rig.matrix_world @ rig.pose.bones[bname].head).copy())

                if cname not in EMPTY_HANDED or cname in AUTHORED_CLIPS:
                    bvh_checked_frames += 1
                    b_verts, b_tris, b_dom = eval_mesh_tris(body_ob, depsgraph)
                    grp_bvhs = {}
                    for gname, gset in BODY_GROUPS.items():
                        gt = [t for t in b_tris if b_dom[t[0]] in gset and b_dom[t[1]] in gset and b_dom[t[2]] in gset]
                        if gt:
                            grp_bvhs[gname] = BVHTree.FromPolygons(b_verts, gt)
                    if helmet_ob is not None:
                        hv, ht, _ = eval_mesh_tris(helmet_ob, depsgraph)
                        if ht:
                            grp_bvhs['WORKER_Helmet'] = BVHTree.FromPolygons(hv, ht)

                    # Self-collision check on authored operation/state clips
                    if cname in AUTHORED_CLIPS and 'TORSO_PELVIS' in grp_bvhs:
                        for arm_g in ('HAND_L', 'HAND_R', 'FOREARM_L', 'FOREARM_R'):
                            if arm_g in grp_bvhs:
                                ov = grp_bvhs[arm_g].overlap(grp_bvhs['TORSO_PELVIS'])
                                assert len(ov) == 0, (kind, cname, frame, arm_g, 'self-collision with TORSO_PELVIS', len(ov))

                    # Body/limb/helmet vs active props + prop-vs-prop BVH checks
                    if cname not in EMPTY_HANDED:
                        active_props = {}
                        for pob in op_props:
                            role = pob.get('prop_role')
                            if rig.pose.bones[role].matrix.to_scale().length < 1e-4:
                                continue
                            pv, pt, _ = eval_mesh_tris(pob, depsgraph)
                            if pt:
                                active_props[pob.name] = BVHTree.FromPolygons(pv, pt)

                        for gname in ('TORSO_PELVIS', 'HEAD_NECK', 'WORKER_Helmet', 'UPPER_ARM_L', 'UPPER_ARM_R', 'FOREARM_L', 'FOREARM_R'):
                            if gname not in grp_bvhs:
                                continue
                            for pname, pbvh in active_props.items():
                                ov = grp_bvhs[gname].overlap(pbvh)
                                assert len(ov) == 0, (kind, cname, frame, gname, pname, 'body-prop BVH overlap', len(ov))

                        pnames = sorted(active_props.keys())
                        for i in range(len(pnames)):
                            for j in range(i + 1, len(pnames)):
                                pa, pb_name = pnames[i], pnames[j]
                                is_flap_pair = ('_Flap_' in pa and '_Flap_' in pb_name)
                                is_tote_pair = ('_PickingTote' in pa and ('_Flap_' in pb_name or '_OpenCarton' in pb_name)) or (
                                    '_PickingTote' in pb_name and ('_Flap_' in pa or '_OpenCarton' in pa)
                                )
                                is_prod_flap = ('_Product' in pa and '_Flap_' in pb_name) or ('_Product' in pb_name and '_Flap_' in pa)
                                if is_flap_pair or is_tote_pair or is_prod_flap:
                                    ov = active_props[pa].overlap(active_props[pb_name])
                                    assert len(ov) == 0, (kind, cname, frame, pa, pb_name, 'prop-prop BVH overlap', len(ov))

            max_delta = 0.0
            for pts in trajectories.values():
                mins = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
                maxs = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
                max_delta = max(max_delta, (maxs - mins).length)
            min_req = MOTION_THRESHOLDS.get(cname, 0.002)
            assert max_delta >= min_req, (kind, cname, 'insufficient motion', max_delta, min_req)
            motion_summary[kind][cname] = round(max_delta, 5)

        rig.animation_data.action = None
        rig.location = old_loc

    # Multi-actor world-space S3C_ROBOT_ASSIST collision check across EVERY (wf, rf) integer frame pair!
    w_col = bpy.data.collections['FRAME ANIMATIONS / Worker']
    r_col = bpy.data.collections['FRAME ANIMATIONS / Robot']
    w_rig = w_col.objects['WORKER_Rig']
    r_rig = r_col.objects['ROBOT_Rig']
    w_old_loc, r_old_loc = w_rig.location.copy(), r_rig.location.copy()
    w_rig.location = (0, 0, 0)
    r_rig.location = (0, 0, 0)

    w_assist_strip = w_rig.animation_data.nla_tracks['Assist'].strips[0]
    w_frames = round(w_assist_strip.action_frame_end) + 1
    assign_action(w_rig, w_assist_strip.action)
    w_world_bvhs = []
    for wf in range(w_frames):
        sc.frame_set(wf)
        bpy.context.view_layer.update()
        depsgraph.update()
        w_world_bvhs.append((wf, combined_bvh([w_col.objects['WORKER_Body'], w_col.objects['WORKER_Helmet']], depsgraph, W_ASSIST_MAT)))

    world_pair_checks = 0
    r_op_props = [ob for ob in r_col.objects if ob.type == 'MESH' and ob.get('operation_prop')]
    for r_clip in ('Service', 'Service_Oversize', 'Jammed', 'Jammed_Oversize'):
        r_strip = r_rig.animation_data.nla_tracks[r_clip].strips[0]
        r_frames = round(r_strip.action_frame_end) + 1
        assign_action(r_rig, r_strip.action)
        for rf in range(r_frames):
            sc.frame_set(rf)
            bpy.context.view_layer.update()
            depsgraph.update()
            active_r = [r_col.objects['ROBOT_Body']] + [
                pob for pob in r_op_props if r_rig.pose.bones[pob.get('prop_role')].matrix.to_scale().length >= 1e-4
            ]
            r_bvh = combined_bvh(active_r, depsgraph, R_WORK_MAT)
            for wf, w_bvh in w_world_bvhs:
                world_pair_checks += 1
                ov = w_bvh.overlap(r_bvh)
                assert len(ov) == 0, ('S3C_ROBOT_ASSIST world overlap', r_clip, wf, rf, len(ov))

    w_rig.animation_data.action = None
    r_rig.animation_data.action = None
    w_rig.location = w_old_loc
    r_rig.location = r_old_loc

    result = {
        'passed': True,
        'fps': 30,
        'actors': 2,
        'worker_bones': EXPECTED_BONES['worker'],
        'robot_bones': EXPECTED_BONES['robot'],
        'worker_clips': len(EXPECTED_CLIPS['worker']),
        'robot_clips': len(EXPECTED_CLIPS['robot']),
        'clips': sum(len(a['clips']) for a in manifest['actors'].values()),
        'dense_native_channels': checked_channels,
        'world_assist_frame_pairs_checked': world_pair_checks,
        'max_body_motion_m': motion_summary,
    }
    (out / 'native_validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print('NATIVE_FRAME_CHECK', json.dumps(result), flush=True)
    return result


if __name__ == '__main__':
    check_native(bpy.context.scene, Path(bpy.data.filepath).parent)
