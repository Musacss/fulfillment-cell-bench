"""Author 30 FPS character/object interactions from read-only v01 character rigs.

Reads clean base character meshes/rigs strictly read-only from v01/warehouse_environment.blend,
applies v02 safety helmet & FlexSim palette in memory, writes ONLY characters_animated.blend,
and exports synchronized 30-FPS GLBs to modules/*.glb and animations_frame_by_frame/*.glb.
"""
import argparse
import bpy
import json
import math
import sys
from pathlib import Path
from mathutils import Vector, Quaternion, Matrix

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_V01_SOURCE = Path('/Users/musaka/Downloads/4_Horses_Environment_v01/warehouse_environment.blend')
OUT = ROOT / 'animations_frame_by_frame'
MODULES_OUT = ROOT / 'modules'
FPS = 30
SOURCE = Vector((0, -.34, .985))
IDENTITY = Quaternion((1, 0, 0, 0))

CONTRACT_CLIPS = {
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
EMPTY_HANDED_CLIPS = {'Idle', 'Walk', 'Reach', 'Assist', 'Break', 'Offline'}
STATE_CLIPS = {'Assist', 'Break', 'Service', 'Service_Oversize', 'Jammed', 'Jammed_Oversize', 'Offline'}
OPERATION_CLIPS = {'Prepare', 'Pick', 'Pack', 'RobotPack', 'Inspect'}


def ease(t):
    t = min(1., max(0., t))
    return t*t*(3-2*t)


def ramp(t, start, end):
    return ease((t-start)/(end-start))


def curves(action):
    if hasattr(action, 'fcurves'):
        return list(action.fcurves)
    return [fc for layer in action.layers for strip in layer.strips
            for bag in strip.channelbags for fc in bag.fcurves]


def assign(rig, action):
    rig.animation_data_create()
    rig.animation_data.action = action
    if action.slots:
        rig.animation_data.action_slot = action.slots[0]


def key_pose(rig, frame):
    for pb in rig.pose.bones:
        for prop in ('location', 'rotation_quaternion', 'scale'):
            pb.keyframe_insert(prop, frame=frame, group=pb.name)


def finish_action(rig, action, name, count):
    for fc in curves(action):
        for key in fc.keyframe_points:
            key.interpolation = 'LINEAR'
    rig.animation_data.action = None
    track = rig.animation_data.nla_tracks.new()
    track.name = name
    strip = track.strips.new(name, 0, action)
    strip.action_frame_start = 0
    strip.action_frame_end = count
    strip.frame_end = count
    track.mute = True


def material(name, color, metallic=0):
    mat = bpy.data.materials.new('FBF / '+name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    shader = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    shader.inputs['Base Color'].default_value = (*color, 1)
    shader.inputs['Roughness'].default_value = .72
    shader.inputs['Metallic'].default_value = metallic
    return mat


def boxes(col, rig, name, parts, bone, mats, kind):
    vertices, faces, mids = [], [], []
    for center, size, mid in parts:
        start = len(vertices)
        vertices.extend(tuple(center[i]+sign[i]*size[i]/2 for i in range(3))
                        for sign in [(x,y,z) for z in (-1,1) for y in (-1,1) for x in (-1,1)])
        for face in [(0,2,3,1),(4,5,7,6),(0,1,5,4),(2,6,7,3),(0,4,6,2),(1,3,7,5)]:
            faces.append(tuple(start+i for i in face))
            mids.append(mid)
    mesh = bpy.data.meshes.new(name + '_Mesh')
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    for mat in mats:
        mesh.materials.append(mat)
    for poly, mid in zip(mesh.polygons, mids):
        poly.material_index = mid
        poly.use_smooth = False
    ob = bpy.data.objects.new(name, mesh)
    col.objects.link(ob)
    ob.parent = rig
    ob.vertex_groups.new(name=bone).add(list(range(len(vertices))), 1, 'REPLACE')
    mod = ob.modifiers.new('Rigid animated object', 'ARMATURE')
    mod.object = rig
    asset_key = f'{kind}_asset'
    for target in (ob, mesh):
        target['operation_prop'] = True
        target['prop_role'] = bone
        target[asset_key] = True
        target['frame_by_frame'] = True
    return ob


def strip_legacy_props(target):
    if target is None:
        return
    for bad in ('handling_prop', 'demo_only'):
        if target.get(bad) is not None:
            del target[bad]
        sys_props = target.bl_system_properties_get() if hasattr(target, 'bl_system_properties_get') else None
        if sys_props is not None and bad in sys_props:
            del sys_props[bad]


def add_props(col, rig, prefix, kind, mats):
    bpy.ops.object.select_all(action='DESELECT')
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    specs = {
        'prop_closed': (SOURCE, 'prop_box'),
        'prop_shell': (SOURCE, 'prop_box'),
        'prop_flap_front': ((0,-.48,1.111), 'prop_shell'),
        'prop_flap_back': ((0,-.20,1.111), 'prop_shell'),
        'prop_flap_left': ((.18,-.34,1.115), 'prop_shell'),
        'prop_flap_right': ((-.18,-.34,1.115), 'prop_shell'),
        'prop_item': ((.32,-.32,1.029), 'root'),
        'prop_tote': ((.32,-.32,1.00), 'root'),
        'prop_tape': ((0,-.48,1.12), 'prop_shell'),
    }
    for name, (pos, parent) in specs.items():
        bone = rig.data.edit_bones.new(name)
        bone.head = pos
        bone.tail = Vector(pos)+Vector((0,0,.06))
        bone.parent = rig.data.edit_bones[parent]
        bone.use_deform = True
    bpy.ops.object.mode_set(mode='OBJECT')
    asset_key = f'{kind}_asset'
    for ob in list(col.objects):
        if ob.name == prefix + '_ClosedCarton':
            if 'prop_box' in ob.vertex_groups:
                ob.vertex_groups['prop_box'].name = 'prop_closed'
            for target in (ob, ob.data):
                strip_legacy_props(target)
                target['operation_prop'] = True
                target['prop_role'] = 'prop_closed'
                target[asset_key] = True
                target['frame_by_frame'] = True
    kraft, blue, item, tape = mats
    boxes(col,rig,prefix+'_OpenCarton',[
        ((0,-.34,.864),(.36,.28,.008),0),
        ((-.176,-.34,.987),(.008,.28,.246),0),
        ((.176,-.34,.987),(.008,.28,.246),0),
        ((0,-.476,.987),(.344,.008,.246),0),
        ((0,-.204,.987),(.344,.008,.246),0)],'prop_shell',[kraft],kind)
    for name, center, size in [
        ('front',(0,-.410,1.111),(.344,.140,.003)),
        ('back',(0,-.270,1.111),(.344,.140,.003)),
        ('left',(.090,-.34,1.115),(.180,.280,.003)),
        ('right',(-.090,-.34,1.115),(.180,.280,.003))]:
        boxes(col,rig,prefix+'_Flap_'+name,[(center,size,0)],'prop_flap_'+name,[kraft],kind)
    boxes(col,rig,prefix+'_Product',[((.32,-.32,1.029),(.085,.08,.09),0),
                                   ((.32,-.361,1.029),(.06,.002,.045),1)],'prop_item',[item,tape],kind)
    boxes(col,rig,prefix+'_PickingTote',[
        ((.32,-.32,.916),(.22,.22,.112),0),
        ((.32,-.32,.978),(.20,.20,.012),0),
        ((.225,-.32,1.015),(.01,.20,.075),0),
        ((.415,-.32,1.015),(.01,.20,.075),0),
        ((.32,-.415,1.015),(.18,.01,.075),0),
        ((.32,-.225,1.015),(.18,.01,.075),0)],'prop_tote',[blue],kind)
    boxes(col,rig,prefix+'_SealingTape',[((0,-.48,1.12),(.042,.28,.002),0)],'prop_tape',[tape],kind)
    return list(specs)


class Controller:
    def __init__(self, rig, kind, grip):
        self.rig, self.kind, self.grip = rig, kind, grip
        self.rest = {b.name:b.matrix_local.copy() for b in rig.data.bones}
        self.contacts = []

    def reset(self):
        for pb in self.rig.pose.bones:
            pb.rotation_mode = 'QUATERNION'
            pb.location = (0,0,0)
            pb.rotation_quaternion = IDENTITY
            pb.scale = (1,1,1)
        for side,s in [('L',1),('R',-1)]:
            self.delta('upper_arm.'+side, Quaternion((0,1,0),s*.245))
            self.delta('forearm.'+side, Quaternion((1,0,0),-.065))
        for pb in self.rig.pose.bones:
            if pb.name.startswith('prop_'):
                pb.scale = (0,0,0)

    def delta(self, name, quat):
        r = self.rest[name].to_quaternion()
        self.rig.pose.bones[name].rotation_quaternion = r.inverted()@quat@r

    def rotation(self, name, quat):
        pb = self.rig.pose.bones[name]
        b = pb.bone
        base = pb.parent.matrix@b.parent.matrix_local.inverted()@b.matrix_local if pb.parent else b.matrix_local
        pb.rotation_quaternion = base.to_quaternion().inverted()@quat

    def prop(self, name, pos=None, rotation=None, scale=(1,1,1)):
        pb = self.rig.pose.bones[name]
        if pos is not None:
            rot = (rotation or IDENTITY)@self.rest[name].to_quaternion()
            pb.matrix = Matrix.Translation(Vector(pos))@rot.to_matrix().to_4x4()
        elif rotation is not None:
            self.delta(name, rotation)
        # Pose scales follow bone-local axes; public sizes use Blender XYZ.
        basis = self.rest[name].to_3x3()
        local = basis.inverted()@Matrix.Diagonal(Vector(scale))@basis
        pb.scale = tuple(local[i][i] for i in range(3))
        bpy.context.view_layer.update()

    def contact(self, side, target, normal, forward=(0,-1,0), curl=0, pole_target=None):
        rig = self.rig
        name = 'hand.'+side
        b = rig.data.bones[name]
        f = (b.tail_local-b.head_local).normalized()
        n = Vector((0,1,0))
        n = (n-f*n.dot(f)).normalized()
        w = n.cross(f)
        tf,tn = Vector(forward).normalized(),Vector(normal).normalized()
        tn = (tn-tf*tn.dot(tf)).normalized()
        q = Matrix((tn.cross(tf),tn,tf)).transposed().to_quaternion()@Matrix((w,n,f)).transposed().to_quaternion().inverted()
        offset = f*(.0625 if self.kind=='robot' else .052)+n*(.0325 if self.kind=='robot' else .046)
        wrist = Vector(target)-q@offset
        up,fore = rig.data.bones['upper_arm.'+side],rig.data.bones['forearm.'+side]
        bpy.context.view_layer.update()
        shoulder = rig.pose.bones[up.name].head.copy()
        v = wrist-shoulder
        distance = v.length
        assert abs(up.length-fore.length)+1e-5 < distance < up.length+fore.length-1e-5, (self.kind,side,'unreachable',tuple(target),distance)
        direction = v.normalized()
        a = (up.length**2-fore.length**2+distance**2)/(2*distance)
        h = math.sqrt(max(0,up.length**2-a*a))
        pt = Vector(pole_target) if pole_target is not None else Vector(((1 if side=='L' else -1)*.61,-.10,1.16))
        pole = pt-shoulder
        perp = (pole-direction*pole.dot(direction)).normalized()
        elbow = shoulder+direction*a+perp*h
        rot = (up.tail_local-up.head_local).rotation_difference(elbow-shoulder)
        self.rotation(up.name,rot@self.rest[up.name].to_quaternion())
        bpy.context.view_layer.update()
        rot = (fore.tail_local-fore.head_local).rotation_difference(wrist-elbow)
        self.rotation(fore.name,rot@self.rest[fore.name].to_quaternion())
        bpy.context.view_layer.update()
        self.rotation(name,q@self.rest[name].to_quaternion())
        for pb in rig.pose.bones:
            if pb.name.startswith(('finger','thumb')) and pb.name.endswith('.'+side):
                pb.rotation_quaternion = IDENTITY.slerp(self.grip[pb.name],curl)
        bpy.context.view_layer.update()
        actual = rig.pose.bones[name].head+q@offset
        error = (actual-Vector(target)).length
        assert error < .00002, ('contact error',error)
        self.contacts.append(error)

    def carton(self, center=SOURCE, rot=IDENTITY, oversize=False, opened=False):
        scale = (4/3, .34/.28, .32/.25) if oversize else (1,1,1)
        self.prop('prop_box',center,rot,scale)
        # prop_stand stays (0,0,0) across 100% of clips; DemoSupport mesh is excluded.
        self.prop('prop_shell' if opened else 'prop_closed')
        if opened:
            for name in ('front','back','left','right'):
                self.prop('prop_flap_'+name)


def pitched_quat(n_surf, f_hint, pitch_deg=0.0):
    ns = Vector(n_surf).normalized()
    ft = Vector(f_hint)
    ft = (ft - ns * ft.dot(ns)).normalized()
    if pitch_deg == 0.0:
        return Matrix((ns.cross(ft), ns, ft)).transposed().to_quaternion()
    ang = math.radians(pitch_deg)
    tf = (ft * math.cos(ang) + ns * math.sin(ang)).normalized()
    tn = (ns * math.cos(ang) - ft * math.sin(ang)).normalized()
    return Matrix((tn.cross(tf), tn, tf)).transposed().to_quaternion()


def set_flap_pose(rig, ctrl, flap, axis, sign, deg, z_lift=0.0, out_shift=0.001):
    name = 'prop_flap_' + flap
    ctrl.prop(name, rotation=Quaternion(axis, sign * math.radians(deg)))
    pb = rig.pose.bones[name]
    loc = Vector((0.0, z_lift, 0.0))
    if out_shift != 0.0:
        if flap in ('left', 'right'):
            loc.x = (1 if flap == 'left' else -1) * out_shift
        else:
            loc.z = (1 if flap == 'front' else -1) * out_shift
    pb.location = loc
    bpy.context.view_layer.update()


def author_state_clip(rig, ctrl, name, duration, oversize=False):
    count = round(duration * FPS)
    action = bpy.data.actions.new('FBF_' + ctrl.kind.title() + '_' + name)
    assign(rig, action)
    base = name.removesuffix('_Oversize')
    size = Vector((0.48, 0.34, 0.32) if oversize else (0.36, 0.28, 0.25))
    center = SOURCE + Vector((0, 0, 0.035 if oversize else 0))
    top = center.z + size.z / 2
    c_scale = (4/3, 0.34/0.28, 0.32/0.25) if oversize else (1, 1, 1)

    for frame in range(count + 1):
        ctrl.reset()  # Sets ALL 11 prop_* bones to (0, 0, 0)
        t = frame / count
        p = 2 * math.pi * t

        if base == 'Assist':
            # Two-handed unjamming gesture reaching toward robot bench while keeping >= 15 cm world clearance from S3C_ROBOT_WORK
            reach = ramp(t, 0.0, 0.22) * (1.0 - ramp(t, 0.78, 1.0))
            work = math.sin(2 * math.pi * (t - 0.22) / 0.56) if 0.22 < t < 0.78 else 0.0
            lift = math.sin(math.pi * (t - 0.22) / 0.56) ** 2 if 0.22 < t < 0.78 else 0.0
            ctrl.delta('hips', Quaternion((1, 0, 0), 0.05 * reach) @ Quaternion((0, 0, 1), 0.08 * reach))
            for side in ('L', 'R'):
                ctrl.delta('thigh.' + side, Quaternion((1, 0, 0), -0.05 * reach))
            ctrl.delta('spine', Quaternion((1, 0, 0), 0.11 * reach) @ Quaternion((0, 0, 1), 0.06 * reach))
            ctrl.delta('chest', Quaternion((1, 0, 0), 0.10 * reach) @ Quaternion((0, 0, 1), 0.06 * reach + 0.04 * work))
            ctrl.delta('neck', Quaternion((1, 0, 0), 0.06 * reach))
            ctrl.delta('head', Quaternion((1, 0, 0), 0.06 * reach) @ Quaternion((0, 0, 1), 0.08 * work))
            bpy.context.view_layer.update()
            for side, s in [('L', 1), ('R', -1)]:
                rest_p = Vector((s * 0.24, -0.12, 1.02))
                if side == 'L':
                    act_p = Vector((0.26 + 0.02 * work, -0.44 - 0.03 * lift, 1.12 + 0.06 * lift))
                    tgt_p = rest_p.lerp(act_p, reach)
                    pole = (0.62, 0.02, 1.28)
                else:
                    act_p = Vector((0.05 + 0.02 * work, -0.40 - 0.02 * lift, 1.10 + 0.05 * lift))
                    tgt_p = rest_p.lerp(act_p, reach) + Vector((0.0, -0.05 * math.sin(math.pi * reach), 0.0))
                    pole = (-0.40, -0.18, 1.24)
                ctrl.contact(side, tgt_p,
                             Vector((-s * 0.78, 0.15, -0.60)).normalized(),
                             Vector((0.12, -0.88, -0.46)).normalized(),
                             curl=0.30 + 0.45 * reach,
                             pole_target=pole)

        elif base == 'Break':
            # Natural weight shift + chest/shoulder roll + right-hand hydration/visor stretch (max Δpos ~ 0.58 m >= 0.15 m)
            active = ramp(t, 0.0, 0.18) * (1.0 - ramp(t, 0.82, 1.0))
            stretch = ramp(t, 0.12, 0.42) * (1.0 - ramp(t, 0.56, 0.84))
            roll = math.sin(2 * math.pi * (t - 0.15) / 0.70) if 0.15 < t < 0.85 else 0.0
            rig.pose.bones['hips'].location = Vector((0.025 * math.sin(p), 0.0, 0.0))
            ctrl.delta('hips', Quaternion((0, 1, 0), 0.035 * math.sin(p)))
            for side in ('L', 'R'):
                ctrl.delta('thigh.' + side, Quaternion((0, 1, 0), -0.035 * math.sin(p)))
            ctrl.delta('spine', Quaternion((1, 0, 0), -0.07 * stretch) @ Quaternion((0, 0, 1), 0.06 * roll))
            ctrl.delta('chest', Quaternion((1, 0, 0), -0.09 * stretch) @ Quaternion((0, 0, 1), 0.08 * roll))
            ctrl.delta('head', Quaternion((1, 0, 0), -0.10 * stretch + 0.04 * math.sin(p)) @ Quaternion((0, 0, 1), 0.12 * roll))
            bpy.context.view_layer.update()
            r_tgt = Vector((-0.30, -0.10, 0.98)).lerp(Vector((-0.20, -0.26, 1.38)), stretch)
            r_nrm = Vector((1, 0, 0)).lerp(Vector((0.40, 0.82, -0.40)), stretch).normalized()
            r_fwd = Vector((0, -0.50, -0.86)).lerp(Vector((0.20, -0.45, 0.87)), stretch).normalized()
            ctrl.contact('R', r_tgt, r_nrm, r_fwd, curl=0.25 + 0.35 * stretch)
            l_tgt = Vector((0.30, -0.10, 0.98)).lerp(Vector((0.25, -0.16, 1.06)), active)
            ctrl.contact('L', l_tgt, Vector((-1, 0, -0.2)).normalized(), Vector((0, -0.8, -0.6)).normalized(), curl=0.35)

        elif base == 'Service':
            # Cooperative robot gripper retraction clearing open Stage-3 carton & Worker Assist space (max Δpos >= 0.12 m)
            ctrl.prop('prop_box', center, IDENTITY, c_scale)
            ctrl.prop('prop_shell')
            clear_prog = ramp(t, 0.30, 0.72) * (1.0 - ramp(t, 0.80, 1.0))
            set_flap_pose(rig, ctrl, 'front', (1, 0, 0), 1, 0.0, z_lift=0.0015, out_shift=0.001)
            set_flap_pose(rig, ctrl, 'back', (1, 0, 0), -1, 0.0, z_lift=0.0015, out_shift=0.001)
            set_flap_pose(rig, ctrl, 'left', (0, 1, 0), 1, 62.0 * (1.0 - 0.65 * clear_prog), z_lift=0.0025, out_shift=0.001)
            set_flap_pose(rig, ctrl, 'right', (0, 1, 0), -1, 42.0 * (1.0 - 0.65 * clear_prog), z_lift=0.0025, out_shift=0.001)
            ret = ramp(t, 0.0, 0.28) * (1.0 - ramp(t, 0.74, 1.0))
            nod = math.sin(2 * math.pi * (t - 0.25) / 0.50) if 0.25 < t < 0.75 else 0.0
            rig.pose.bones['hips'].location = Vector((-0.05 * ret, 0.03 * ret, 0.0))
            ctrl.delta('spine', Quaternion((1, 0, 0), 0.02 * (1.0 - ret) - 0.04 * ret))
            ctrl.delta('chest', Quaternion((1, 0, 0), 0.02 * (1.0 - ret) - 0.05 * ret) @ Quaternion((0, 0, 1), -0.10 * ret))
            ctrl.delta('head', Quaternion((1, 0, 0), 0.10 * (1.0 - 0.4 * ret) + 0.07 * nod) @ Quaternion((0, 0, 1), -0.18 * ret))
            bpy.context.view_layer.update()
            l_start = Vector((0.21, -0.16, 1.72))
            l_clear = Vector((0.18, -0.08, 1.80))
            ctrl.contact('L', l_start.lerp(l_clear, ret),
                         Vector((-0.78, 0.35, -0.52)).normalized(),
                         Vector((0.0, -0.55, 0.83)).normalized(),
                         curl=0.25 * (1 - ret),
                         pole_target=(0.22, -0.46, 1.46))
            r_start = Vector((-(size.x / 2 + 0.075), -0.22, top + 0.14))
            r_clear = Vector((-(size.x / 2 + 0.145), -0.12, top + 0.26))
            ctrl.contact('R', r_start.lerp(r_clear, ret),
                         Vector((0.80, 0.0, -0.60)).normalized(),
                         Vector((0.0, -0.75, -0.66)).normalized(),
                         curl=0.25 * (1 - ret),
                         pole_target=(-0.68, 0.06, 1.34))

        elif base == 'Jammed':
            # Halted arm recoil above snagged Stage-3 carton (minor flaps folded flat, major flaps snagged, 0 overlaps)
            recoil = math.sin(math.pi * t) ** 2
            scan = math.sin(p)
            ctrl.prop('prop_box', center, IDENTITY, c_scale)
            ctrl.prop('prop_shell')
            set_flap_pose(rig, ctrl, 'front', (1, 0, 0), 1, 0.0, z_lift=0.0015, out_shift=0.001)
            set_flap_pose(rig, ctrl, 'back', (1, 0, 0), -1, 0.0, z_lift=0.0015, out_shift=0.001)
            set_flap_pose(rig, ctrl, 'left', (0, 1, 0), 1, 64.0 + 4.0 * recoil, z_lift=0.0025, out_shift=0.001)
            set_flap_pose(rig, ctrl, 'right', (0, 1, 0), -1, 44.0 + 5.0 * recoil, z_lift=0.0025, out_shift=0.001)
            ctrl.delta('spine', Quaternion((1, 0, 0), 0.02 - 0.02 * recoil))
            ctrl.delta('chest', Quaternion((1, 0, 0), 0.02 - 0.02 * recoil) @ Quaternion((0, 0, 1), -0.05 + 0.04 * scan))
            ctrl.delta('head', Quaternion((1, 0, 0), 0.12) @ Quaternion((0, 0, 1), 0.26 * scan))
            bpy.context.view_layer.update()
            l_base = Vector((0.21, -0.16, 1.72))
            l_rec = l_base + Vector((-0.02 * recoil, 0.03 * recoil, 0.055 * recoil + 0.010 * scan))
            ctrl.contact('L', l_rec,
                         Vector((-0.78, 0.35, -0.52)).normalized(),
                         Vector((0.0, -0.55, 0.83)).normalized(),
                         curl=0.35,
                         pole_target=(0.22, -0.46, 1.46))
            r_base = Vector((-(size.x / 2 + 0.075), -0.22, top + 0.14))
            r_rec = r_base + Vector((-0.025 * recoil, 0.030 * recoil, 0.050 * recoil - 0.012 * scan))
            ctrl.contact('R', r_rec,
                         Vector((0.75, 0.0, -0.66)).normalized(),
                         Vector((0.0, -0.75, -0.66)).normalized(),
                         curl=0.35,
                         pole_target=(-0.68, 0.06, 1.34))

        elif base == 'Offline':
            # Powered-down standby posture (all props (0,0,0)) with smooth servo-hold settle (max Δpos ~ 0.038 m >= 0.01 m)
            pulse = 0.5 * (1.0 - math.cos(p))
            ctrl.delta('spine', Quaternion((1, 0, 0), 0.06 + 0.018 * pulse))
            ctrl.delta('chest', Quaternion((1, 0, 0), 0.08 + 0.022 * pulse))
            ctrl.delta('neck', Quaternion((1, 0, 0), 0.10 + 0.015 * pulse))
            ctrl.delta('head', Quaternion((1, 0, 0), 0.22 + 0.035 * pulse))
            for side, s in [('L', 1), ('R', -1)]:
                ctrl.delta('upper_arm.' + side, Quaternion((0, 1, 0), s * 0.20) @ Quaternion((1, 0, 0), 0.08 + 0.035 * pulse))
                ctrl.delta('forearm.' + side, Quaternion((1, 0, 0), -0.22 - 0.04 * pulse))

        key_pose(rig, frame)
    finish_action(rig, action, name, count)
    info = {
        'name': name,
        'action': action.name,
        'duration_seconds': duration,
        'frames': count + 1,
        'loop': True,
        'fps': FPS,
        'key_every_frame': True,
        'object_sync': True,
    }
    if base in ('Service', 'Jammed', 'Offline'):
        info['order_variant'] = 'oversize' if oversize else 'standard'
    return info


def author_operation(rig, ctrl, name, duration, oversize=False):
    count = round(duration*FPS)
    action = bpy.data.actions.new('FBF_'+ctrl.kind.title()+'_'+name)
    assign(rig,action)
    base = name.removesuffix('_Oversize')
    size = Vector((.48,.34,.32) if oversize else (.36,.28,.25))
    if base in ('Prepare', 'Pack', 'RobotPack'):
        center = Vector((0.0, -0.355 if oversize else -0.35, 0.985 + (0.035 if oversize else 0.0)))
    else:
        center = SOURCE+Vector((0,0,.035 if oversize else 0))
    top = center.z+size.z/2
    # Gestures are single operations: no instantaneous item/tape reset at the seam.
    for frame in range(count+1):
        ctrl.reset()
        t = frame/count
        lean = base in ('Prepare','Pack','RobotPack')
        if lean:
            if base == 'Prepare':
                ease_back = 0.10 + 0.46 * ramp(t, .28, .50)
                yaw_z = -0.04 * ramp(t, .28, .50)
            else:
                front_phase = 1.0 - ramp(t, .18, .40)
                tape_start = ramp(t, .60, .72) * (1.0 - ramp(t, .76, .90))
                ease_back = 0.10 + 0.46 * front_phase + 0.48 * tape_start
                yaw_z = -0.04 * front_phase + 0.10 * tape_start
            ctrl.delta('hips',Quaternion((1,0,0),.05 * ease_back))
            for side in ('L','R'):
                ctrl.delta('thigh.'+side,Quaternion((1,0,0),-.05 * ease_back))
            ctrl.delta('spine',Quaternion((1,0,0),.13 * ease_back) @ Quaternion((0,0,1), 0.4 * yaw_z))
            ctrl.delta('chest',Quaternion((1,0,0),.11 * ease_back) @ Quaternion((0,0,1), 0.6 * yaw_z))
        elif base == 'Pick' and oversize:
            reach_tote = ramp(t, 0.0, 0.12) * (1.0 - ramp(t, 0.34, 0.50))
            ctrl.delta('spine', Quaternion((1, 0, 0), .07) @ Quaternion((0, 0, 1), -0.05 * reach_tote))
            ctrl.delta('chest', Quaternion((1, 0, 0), .06) @ Quaternion((0, 0, 1), -0.07 * reach_tote))
        else:
            ctrl.delta('spine',Quaternion((1,0,0),.055))
            ctrl.delta('chest',Quaternion((1,0,0),.045))
        ctrl.delta('neck',Quaternion((1,0,0),.025))
        bpy.context.view_layer.update()
        opened = base in ('Prepare','Pick','Pack','RobotPack')
        ctrl.carton(center,oversize=oversize,opened=opened)
        if base == 'Pick':
            set_flap_pose(rig, ctrl, 'front', (1, 0, 0), 1, 255.0, z_lift=0.002, out_shift=0.003)
            set_flap_pose(rig, ctrl, 'back', (1, 0, 0), -1, 262.0, z_lift=0.002, out_shift=0.003)
            set_flap_pose(rig, ctrl, 'left', (0, 1, 0), 1, 265.0, z_lift=0.002, out_shift=0.003)
            set_flap_pose(rig, ctrl, 'right', (0, 1, 0), -1, 265.0, z_lift=0.002, out_shift=0.003)
            tx = .41 if oversize else .38
            ctrl.prop('prop_tote', pos=(tx, -.32, 1.00))
            a=Vector((tx,-.32,1.029))
            b=Vector((tx-.02,-.32,1.34+(.08 if oversize else 0)))
            c=Vector((0,center.y,1.34+(.08 if oversize else 0)))
            d=Vector((0,center.y,1.22+(.06 if oversize else 0)))
            held = a.lerp(b,ramp(t,.15,.34)).lerp(c,ramp(t,.34,.50)).lerp(d,ramp(t,.50,.66))
            item = held.lerp(Vector((0,center.y,.915)),ramp(t,.69,.80))
            ctrl.prop('prop_item',item)
            retract = ramp(t,.73,1)
            ready_l = Vector((tx-.04,-.22,1.28+(.06 if oversize else 0)))
            hand = ready_l.lerp(held+Vector((.0425,0,.015)),ramp(t,0,.12))
            hand = hand.lerp(ready_l,retract)
            ctrl.contact('L',hand,(-1,0,0),forward=(0,-.40,-.916),
                         curl=(ramp(t,.08,.15)*(1-ramp(t,.66,.72))),
                         pole_target=(.78,-.05,1.44))
            ctrl.contact('R',center+Vector((-size.x/2-.016,0,.030)),(1,0,0),forward=(0,-.45,-.893),
                         curl=.85,pole_target=(-.78,-.02,1.48))
        elif base in ('Prepare','Pack','RobotPack'):
            # Coordinated outer-tip roll + flat horizontal splay (176 deg) so side flaps never block forearms (< 1.5 cm gap, 0 overlaps).
            if base == 'Prepare':
                close = 1.0 - ramp(t, .52, .78)
                deg_maj = 108.0 * ramp(t, .06, .24) + 68.0 * ramp(t, .24, .35)
                t_b0, t_b1 = 0.24, 0.46
                b1, b2 = 0.25, 0.50
                blend = (t - t_b0) / (t_b1 - t_b0) if t_b0 < t < t_b1 else (0.0 if t <= t_b0 else 1.0)
                maj_tip_frac = ramp(t, .08, .24)
                maj_open_frac = ramp(t, .06, .24)
            else:
                close = ramp(t, .03, .14)
                deg_maj = 176.0 - 68.0 * ramp(t, .30, .41) - 108.0 * ramp(t, .41, .62)
                t_b0, t_b1 = 0.20, 0.41
                b1, b2 = 0.26, 0.52
                blend = 1.0 - ((t - t_b0) / (t_b1 - t_b0) if t_b0 < t < t_b1 else (0.0 if t <= t_b0 else 1.0))
                maj_tip_frac = 1.0 - ramp(t, .41, .60)
                maj_open_frac = 1.0 - ramp(t, .41, .62)

            set_flap_pose(rig, ctrl, 'front', (1, 0, 0), 1, 62.0 * (1.0 - close), z_lift=0.0015, out_shift=0.001)
            set_flap_pose(rig, ctrl, 'back', (1, 0, 0), -1, 56.0 * (1.0 - close), z_lift=0.0015, out_shift=0.001)
            set_flap_pose(rig, ctrl, 'left', (0, 1, 0), 1, deg_maj, z_lift=0.003, out_shift=0.002)
            set_flap_pose(rig, ctrl, 'right', (0, 1, 0), -1, deg_maj, z_lift=0.003, out_shift=0.002)

            pad = .007 if ctrl.kind == 'robot' else .006
            sx = 4.0 / 3.0 if oversize else 1.0
            tip_extra = (pad + 0.0005) / sx
            tip_in = 0.009 / sx

            for side, flap, sign in [('L','left',1),('R','right',-1)]:
                pb = rig.pose.bones['prop_flap_'+flap]
                deform = pb.matrix@pb.bone.matrix_local.inverted()

                # 1) Major +dz face (elevated elbow + 16 deg wrist pitch when flat closed at 0 deg so forearms never graze carton/flaps):
                dx_maj = 0.110 + (0.180 - tip_in - 0.110) * maj_tip_frac
                y_maj = -0.012 * (1.0 - maj_open_frac) + 0.015 * maj_open_frac
                z_maj = (0.002 + pad) + (0.0045 if oversize else 0.0025) * (1.0 - maj_open_frac)
                local_maj = Vector((-sign * dx_maj, y_maj, z_maj))
                target_maj = deform@(pb.bone.head_local+local_maj)
                n_maj = (deform.to_3x3().inverted().transposed()@Vector((0,0,-1))).normalized()
                f_maj = deform.to_3x3()@Vector((sign*.68,-.73,0))
                q_maj = pitched_quat(n_maj, f_maj, 16.0 * (1.0 - maj_open_frac))
                pole_maj = Vector((sign*.68,-.06,1.64)).lerp(Vector((sign*.84,.02,1.44)), maj_open_frac)

                # 2) wp1: outside outer tip end-cap (z_local == 0.0 strictly inside ±0.0015 m half-thickness!)
                wp1_local = Vector((-sign * (0.180 + tip_extra), 0.0, 0.0))
                target_wp1 = deform@(pb.bone.head_local+wp1_local)
                n_wp1 = (deform.to_3x3().inverted().transposed()@Vector((sign,0,0))).normalized()
                f_wp1 = Vector((0.12 if side=='L' else 0.30,-.90,-.38))
                q_wp1 = pitched_quat(n_wp1, f_wp1, 0.0)
                pole_wp1 = Vector((sign*.82,.02,1.50))

                # 3) wp2: -dz upper face near outer tip (flat horizontal at 176 deg, matching wp1 yaw/pole to eliminate forearm/wrist counter-roll!)
                dx_wp2 = 0.180 - 0.4 * tip_in
                wp2_local = Vector((-sign * dx_wp2, -0.008 if side=='L' else 0.008, -0.002 - pad))
                target_wp2 = deform@(pb.bone.head_local+wp2_local)
                n_wp2 = (deform.to_3x3().inverted().transposed()@Vector((0,0,1))).normalized()
                f_wp2 = Vector((.06,-.95,-.28)) if side=='L' else Vector((.32,-.90,-.28))
                q_wp2 = pitched_quat(n_wp2, f_wp2, 0.0)
                pole_wp2 = Vector((sign*.78,-.02,1.54))

                # 4) Minor flap target (Flap_front / Flap_back):
                front = rig.pose.bones['prop_flap_front' if side=='L' else 'prop_flap_back']
                b = front.bone
                minor_deform = front.matrix@b.matrix_local.inverted()
                n_min = (minor_deform.to_3x3().inverted().transposed()@Vector((0,0,-1))).normalized()
                minor_local = Vector((sign*.115, (.118 if side=='L' else -.118), .002 + pad))
                target_min = minor_deform@(b.head_local+minor_local)
                if side == 'L':
                    f_min = minor_deform.to_3x3()@Vector((-.25,-.97,0))
                    pole_min = Vector((.46,-.09,1.72))
                else:
                    f_min = minor_deform.to_3x3()@Vector((.84,.54,0))
                    pole_min = Vector((-.48,-.08,1.72))
                q_min = pitched_quat(n_min, f_min, 15.0)

                # [0.00..b1]: maj -> wp1 | [b1..b2]: wp1 -> wp2 | [b2..1.00]: wp2 -> min
                if blend <= 0.0:
                    target, q_cur, pole_cur = target_maj, q_maj, pole_maj
                elif blend >= 1.0:
                    target, q_cur, pole_cur = target_min, q_min, pole_min
                elif blend < b1:
                    u = blend / b1
                    r_z = local_maj.z - 0.0015
                    if u <= 0.42:
                        dx_abs = dx_maj + (0.180 - dx_maj) * (u / 0.42)
                        z_cur = 0.0015 + r_z
                    elif u < 0.58:
                        th = 0.5 * math.pi * ((u - 0.42) / 0.16)
                        dx_abs = 0.180 + tip_extra * math.sin(th)
                        z_cur = 0.0015 + r_z * math.cos(th)
                    else:
                        dx_abs = 0.180 + tip_extra
                        z_cur = 0.0015 * (1.0 - (u - 0.58) / 0.42)
                    loc_cur = Vector((-sign * dx_abs, local_maj.y * (1.0 - u), z_cur))
                    target = deform@(pb.bone.head_local+loc_cur)
                    q_cur = q_maj.slerp(q_wp1, u)
                    pole_cur = pole_maj.lerp(pole_wp1, u)
                elif blend < b2:
                    u = (blend - b1) / (b2 - b1)
                    r_z2 = -wp2_local.z - 0.0015
                    if u <= 0.42:
                        dx_abs = 0.180 + tip_extra
                        z_cur = -0.0015 * (u / 0.42)
                    elif u < 0.58:
                        th = 0.5 * math.pi * ((u - 0.42) / 0.16)
                        dx_abs = 0.180 + tip_extra * math.cos(th)
                        z_cur = -0.0015 - r_z2 * math.sin(th)
                    else:
                        dx_abs = 0.180 - (0.180 - dx_wp2) * ((u - 0.58) / 0.42)
                        z_cur = -0.0015 - r_z2
                    loc_cur = Vector((-sign * dx_abs, wp2_local.y * u, z_cur))
                    target = deform@(pb.bone.head_local+loc_cur)
                    q_cur = q_wp1.slerp(q_wp2, u)
                    pole_cur = pole_wp1.lerp(pole_wp2, u)
                else:
                    u = (blend - b2) / (1.0 - b2)
                    s3 = 0.35 * ease(u) + 0.65 * u
                    target = target_wp2.lerp(target_min, s3)
                    q_cur = q_wp2.slerp(q_min, s3)
                    pole_cur = pole_wp2.lerp(pole_min, s3)

                m_cur = q_cur.to_matrix()
                normal = Vector((m_cur[0][1], m_cur[1][1], m_cur[2][1])).normalized()
                forward = Vector((m_cur[0][2], m_cur[1][2], m_cur[2][2])).normalized()

                # Apply sealing tape along exact growing leading edge in Pack / RobotPack.
                if base in ('Pack','RobotPack') and t>.61:
                    if side=='R':
                        y_start = center.y - size.y/2 + 0.035
                        y_end = center.y + size.y/2 - 0.035
                        tape_target = Vector((0.0, y_start + (y_end - y_start)*ramp(t,.71,.90), top + .010))
                        q_tape = pitched_quat(Vector((0,0,-1)), Vector((.72,-.45,0)), 25.0)
                    else:
                        tape_target = Vector((size.x/2 - .035, center.y - .020, top + .010))
                        q_tape = pitched_quat(Vector((0,0,-1)), Vector((-.45,-.89,0)), 23.0)
                    w_lin = min(1.0, max(0.0, (t - .61) / .10))
                    w_pos = ramp(t, .61, .71)
                    q_from = pitched_quat(normal, forward, 0.0)
                    q_blend = q_from.slerp(q_tape, w_lin).to_matrix()
                    target = target.lerp(tape_target, w_pos)
                    normal = Vector((q_blend[0][1], q_blend[1][1], q_blend[2][1])).normalized()
                    forward = Vector((q_blend[0][2], q_blend[1][2], q_blend[2][2])).normalized()
                    pole_cur = pole_cur.lerp(Vector((sign*.72,-.08,1.62)), w_pos)
                ctrl.contact(side,target,normal,forward,curl=0,pole_target=pole_cur)
            if base in ('Pack','RobotPack'):
                reveal=ramp(t,.68,.90)
                ctrl.prop('prop_tape',pos=(0,center.y-size.y/2+size.y/2*reveal,top+.009),
                          scale=(1,max(.0001,reveal),1) if t>=.68 else (0,0,0))
        elif base == 'Inspect':
            lift = ramp(t,.17,.34)*(1-ramp(t,.75,.91))
            max_ang = 12 if oversize else 20
            angle = math.radians(max_ang)*math.sin(2*math.pi*ramp(t,.36,.72)) if .36<t<.72 else 0
            tilt = math.radians(5)*math.sin(math.pi*ramp(t,.36,.72)) if .36<t<.72 else 0
            rot = Quaternion((0,0,1),angle)@Quaternion((1,0,0),tilt)
            pos = center+Vector((0,(-.04 if oversize else .02)*lift,.10*lift))
            ctrl.carton(pos,rot,oversize)
            side_pad = .008 if oversize else .004
            for side,s in [('L',1),('R',-1)]:
                contact = pos+rot@Vector((s*(size.x/2 + side_pad),0,.025))
                ctrl.contact(side,contact,rot@Vector((-s,0,0)),rot@Vector((0,-.88,-.47)),
                             curl=ramp(t,0,.12)*(1-ramp(t,.92,1)),
                             pole_target=(s*.74,-.06,1.34))
            ctrl.delta('head',Quaternion((0,0,1),angle*.5))
        key_pose(rig,frame)
    finish_action(rig,action,name,count)
    return {'name':name,'action':action.name,'duration_seconds':duration,'frames':count+1,
            'loop':False,'fps':FPS,'key_every_frame':True,'object_sync':True,
            'order_variant':'oversize' if oversize else 'standard'}


def copy_actor(source_col, scene, kind):
    col = bpy.data.collections.new('FRAME ANIMATIONS / '+kind.title())
    scene.collection.children.link(col)
    prefix = kind.upper()
    asset_key = f'{kind}_asset'
    mapping = {}
    parent_state = {}
    for old in list(source_col.objects):
        if old.get('handling_prop') == 'support' or 'DemoSupport' in old.name:
            continue
        orig_name = old.name
        orig_data_name = old.data.name if old.data else None
        if orig_name.endswith('_DemoCarton'):
            target_name = f'{prefix}_ClosedCarton'
            target_data_name = f'{prefix}_ClosedCarton_Mesh'
        else:
            target_name = orig_name
            target_data_name = orig_data_name
        parent_state[old] = (
            old.parent_type,
            old.parent_bone,
            old.matrix_parent_inverse.copy(),
            old.matrix_basis.copy(),
        )
        old.name = '_V01_SRC_' + orig_name
        if old.data and not old.data.name.startswith('_V01_SRC_'):
            old.data.name = '_V01_SRC_' + orig_data_name
        new = old.copy()
        if old.data:
            new.data = old.data.copy()
            new.data.name = target_data_name
        new.name = target_name
        new.hide_render = False
        new.hide_viewport = False
        new[asset_key] = True
        strip_legacy_props(new)
        if new.type == 'MESH' and new.data is not None:
            new.data[asset_key] = True
            strip_legacy_props(new.data)
        col.objects.link(new)
        mapping[old] = new
    for old, new in mapping.items():
        if old.parent in mapping:
            ptype, pbone, mpi, mb = parent_state[old]
            new.parent = mapping[old.parent]
            new.parent_type = ptype
            if ptype == 'BONE' and pbone:
                new.parent_bone = pbone
            new.matrix_parent_inverse = mpi
            new.matrix_basis = mb
        for mod in new.modifiers:
            if mod.type == 'ARMATURE' and mod.object in mapping:
                mod.object = mapping[mod.object]
    rig = next(ob for ob in col.objects if ob.type == 'ARMATURE')
    rig.location = (0, 0, 0)
    rig.rotation_mode = 'XYZ'
    rig.rotation_euler = (0, 0, 0)
    rig.scale = (1, 1, 1)
    sources = {track.name: track.strips[0].action for track in rig.animation_data.nla_tracks}
    rig.animation_data_clear()
    return col, rig, sources


def bake_source(rig, source, ctrl, name, duration, new_bones):
    count=round(duration*FPS)
    poses=[]
    assign(rig,source)
    for frame in range(count+1):
        bpy.context.scene.frame_set(frame)
        poses.append({pb.name:(pb.location.copy(),pb.rotation_quaternion.copy(),pb.scale.copy())
                      for pb in rig.pose.bones if pb.name not in new_bones})
    action=bpy.data.actions.new('FBF_'+ctrl.kind.title()+'_'+name)
    assign(rig,action)
    for frame,pose in enumerate(poses):
        ctrl.reset()
        for key,(loc,rot,scale) in pose.items():
            pb=rig.pose.bones[key]
            pb.location,pb.rotation_quaternion,pb.scale=loc,rot,scale
        rig.pose.bones['prop_stand'].scale = (0, 0, 0)
        if name in EMPTY_HANDED_CLIPS:
            for pb in rig.pose.bones:
                if pb.name.startswith('prop_'):
                    pb.scale = (0, 0, 0)
        else:
            show_box = rig.pose.bones['prop_box'].scale.length > 0.01
            rig.pose.bones['prop_closed'].scale = (1, 1, 1) if show_box else (0, 0, 0)
        key_pose(rig,frame)
    finish_action(rig,action,name,count)
    return {'name':name,'action':action.name,'duration_seconds':duration,'frames':count+1,
            'loop':name in ('Idle','Walk','CarryIdle','CarryWalk'),
            'fps':FPS,'key_every_frame':True,'object_sync':True}


def export_actor(col, rig, path, expected_clips, props_only=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    rig.location = (0, 0, 0)
    rig.rotation_mode = 'XYZ'
    rig.rotation_euler = (0, 0, 0)
    rig.scale = (1, 1, 1)
    bpy.ops.object.select_all(action='DESELECT')
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    selected = []
    for ob in col.objects:
        if 'DemoSupport' in ob.name or ob.get('handling_prop') == 'support':
            continue
        if ob.type == 'ARMATURE' or (bool(ob.get('operation_prop')) if props_only else True):
            ob.select_set(True)
            selected.append(ob)
    rig.animation_data.action = None
    actual_tracks = [tr.name for tr in rig.animation_data.nla_tracks]
    assert actual_tracks == expected_clips, ('NLA track order mismatch', actual_tracks, expected_clips)
    for tr in rig.animation_data.nla_tracks:
        tr.mute = False
    bpy.context.scene.frame_set(0)
    mesh_parents = []
    for ob in selected:
        if ob.type == 'MESH':
            mesh_parents.append((ob, ob.parent, ob.matrix_world.copy()))
            world = ob.matrix_world.copy()
            ob.parent = None
            ob.matrix_world = world
    bpy.ops.export_scene.gltf(filepath=str(path),export_format='GLB',use_selection=True,use_active_scene=True,
        export_yup=True,export_extras=True,export_animations=True,
        export_animation_mode='NLA_TRACKS',export_nla_strips=True,
        export_force_sampling=True,export_frame_step=1,export_frame_range=False,
        export_optimize_animation_size=False,export_optimize_animation_keep_anim_armature=True,
        export_skins=True,export_def_bones=False,export_cameras=False,export_lights=False)
    for ob,parent,world in mesh_parents:
        ob.parent=parent
        ob.matrix_world=world
    for tr in rig.animation_data.nla_tracks:
        tr.mute=True


def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', default=str(DEFAULT_V01_SOURCE))
    parser.add_argument('--out-fbf', default=str(OUT))
    parser.add_argument('--out-modules', default=str(MODULES_OUT))
    return parser.parse_args(argv)


def build(source_path=DEFAULT_V01_SOURCE, out_fbf=OUT, out_modules=MODULES_OUT):
    source_path = Path(source_path).resolve()
    out_fbf = Path(out_fbf).resolve()
    out_modules = Path(out_modules).resolve()
    assert source_path != (ROOT / 'warehouse_environment.blend').resolve(), (
        'ZERO-CONTENTION RULE: never read/open v02/warehouse_environment.blend in M2!'
    )
    if not bpy.data.filepath or Path(bpy.data.filepath).resolve() != source_path:
        bpy.ops.wm.open_mainfile(filepath=str(source_path))
    out_fbf.mkdir(parents=True, exist_ok=True)
    out_modules.mkdir(parents=True, exist_ok=True)
    source_scene = next(s for s in bpy.data.scenes if 'WORKER_Rig' in s.objects)
    bpy.context.window.scene = source_scene
    # Apply v02 WORKER_Helmet + FlexSim bright sRGB palette in memory (never saving v01).
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from flexsim_character_palette import apply_character_palette
    helmet = apply_character_palette(add_helmet=True)
    worker_src_col = bpy.data.collections['CHARACTERS / Warehouse worker']
    if helmet is not None and helmet.name not in worker_src_col.objects:
        worker_src_col.objects.link(helmet)

    # Re-running removes only this builder's scratch scenes and copied objects.
    for old in list(bpy.data.scenes):
        if old.name.startswith('FRAME BY FRAME /'):
            bpy.data.scenes.remove(old)
    for old in list(bpy.data.collections):
        if old.name.startswith('FRAME ANIMATIONS /'):
            for ob in list(old.objects):
                bpy.data.objects.remove(ob,do_unlink=True)
            bpy.data.collections.remove(old)
    for old in list(bpy.data.actions):
        if old.name.startswith('FBF_'):
            bpy.data.actions.remove(old)
    source_cols={kind:bpy.data.collections['CHARACTERS / '+label] for kind,label in
                 [('worker','Warehouse worker'),('robot','Humanoid robot')]}
    scene=bpy.data.scenes.new('FRAME BY FRAME / 30 FPS')
    bpy.context.window.scene=scene
    scene.render.fps=FPS
    scene.frame_start=0
    scene.frame_end=120
    scene.unit_settings.system='METRIC'
    scene['animation_notes']='Every bone transform is keyed on every frame. Objects share the actor action.'
    mats=[material('Carton kraft',(.49,.285,.125)),material('Picking tote',(.035,.22,.48)),
          material('Product',(.72,.18,.06)),material('Paper tape',(.80,.68,.42))]
    result={'fps':FPS,'native_keys':'every integer frame, location / quaternion / scale',
            'source':str(source_path),'actors':{},
            'objects':['closed carton','open carton','four hinged flaps','product','picking tote','sealing tape'],
            'notes':['Operations are single shots; do not loop Pick/Pack/Inspect without resetting objects.',
                     'Object-only GLBs use the same clip names, times and origins as their character GLBs.',
                     'In-place walking: route translation is supplied by the application.']}
    actors={}
    for kind in ('worker','robot'):
        col,rig,sources=copy_actor(source_cols[kind],scene,kind)
        assign(rig,sources['CarryIdle'])
        scene.frame_set(0)
        grip={pb.name:pb.rotation_quaternion.copy() for pb in rig.pose.bones if pb.name.startswith(('thumb','finger'))}
        rig.animation_data.action=None
        new_bones=add_props(col,rig,kind.upper(),kind,mats)
        # Verify zero unweighted vertices across all character and operational prop meshes.
        deform_names={b.name for b in rig.data.bones if b.use_deform}
        for ob in col.objects:
            if ob.type=='MESH':
                vg_map={vg.index:vg.name for vg in ob.vertex_groups}
                for v in ob.data.vertices:
                    w=sum(g.weight for g in v.groups if vg_map.get(g.group) in deform_names)
                    assert w > 0.999, (kind, ob.name, 'unweighted vertex', v.index, w)
        ctrl=Controller(rig,kind,grip)
        manifest=json.loads((ROOT/(kind+'_manifest.json')).read_text())
        manifest_durations={c['name']:c['duration_seconds'] for c in manifest['clips']}
        expected_list=CONTRACT_CLIPS[kind]
        assert list(manifest_durations.keys()) == expected_list, (
            kind, 'manifest clip order mismatch', list(manifest_durations.keys()), expected_list
        )
        clips=[]
        for name in expected_list:
            duration = manifest_durations[name]
            base = name.removesuffix('_Oversize')
            if base in OPERATION_CLIPS:
                clips.append(author_operation(rig,ctrl,name,duration,name.endswith('_Oversize')))
            elif name in STATE_CLIPS:
                clips.append(author_state_clip(rig,ctrl,name,duration,name.endswith('_Oversize')))
            else:
                clips.append(bake_source(rig,sources[name],ctrl,name,duration,new_bones))
            print('FRAME_CLIP',kind,name,flush=True)
        file='warehouse_worker' if kind=='worker' else 'humanoid_robot'
        export_actor(col,rig,out_modules/(file+'.glb'),expected_list,False)
        export_actor(col,rig,out_fbf/(file+'.glb'),expected_list,False)
        export_actor(col,rig,out_fbf/('interaction_objects_'+kind+'.glb'),expected_list,True)
        preview_clip = 'Pick' if kind == 'worker' else 'RobotPack'
        assign(rig,bpy.data.actions['FBF_'+kind.title()+'_'+preview_clip])
        scene.frame_set(57)
        actors[kind]=(col,rig)
        result['actors'][kind]={'file':file+'.glb','objects_file':'interaction_objects_'+kind+'.glb',
                               'bones':len(rig.data.bones),'clips':clips,
                               'max_ik_contact_error_m':max(ctrl.contacts)}
    # Arrange the editable native animation stage side by side AFTER GLB export, both facing -Y.
    actors['worker'][1].location.x=-.7
    actors['robot'][1].location.x=.7
    scene.frame_set(57)
    bpy.data.libraries.write(str(out_fbf/'characters_animated.blend'),{scene},fake_user=True,compress=True)
    (out_fbf/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('FRAME_ANIMATIONS_COMPLETE',str(out_fbf),str(out_modules),flush=True)
    return scene,actors


if __name__=='__main__':
    opts=parse_args()
    FBF_SCENE,FBF_ACTORS=build(opts.source,opts.out_fbf,opts.out_modules)
