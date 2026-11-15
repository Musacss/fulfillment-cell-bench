"""Author 30 FPS character/object interactions in an isolated Blender scene.

Run inside the source .blend. The original scene, meshes and actions are retained.
The output is a separate animation library, not a replacement production replay.
"""
import bpy
import json
import math
from pathlib import Path
from mathutils import Vector, Quaternion, Matrix

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'animations_frame_by_frame'
FPS = 30
SOURCE = Vector((0, -.34, .985))
IDENTITY = Quaternion((1, 0, 0, 0))


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


def boxes(col, rig, name, parts, bone, mats):
    vertices, faces, mids = [], [], []
    for center, size, mid in parts:
        start = len(vertices)
        vertices.extend(tuple(center[i]+sign[i]*size[i]/2 for i in range(3))
                        for sign in [(x,y,z) for z in (-1,1) for y in (-1,1) for x in (-1,1)])
        for face in [(0,2,3,1),(4,5,7,6),(0,1,5,4),(2,6,7,3),(0,4,6,2),(1,3,7,5)]:
            faces.append(tuple(start+i for i in face))
            mids.append(mid)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    for mat in mats:
        mesh.materials.append(mat)
    for poly, mid in zip(mesh.polygons, mids):
        poly.material_index = mid
    ob = bpy.data.objects.new(name, mesh)
    col.objects.link(ob)
    ob.parent = rig
    ob.vertex_groups.new(name=bone).add(list(range(len(vertices))), 1, 'REPLACE')
    mod = ob.modifiers.new('Rigid animated object', 'ARMATURE')
    mod.object = rig
    ob['handling_prop'] = bone
    ob['frame_by_frame'] = True
    return ob


def add_props(col, rig, prefix, mats):
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
    for ob in col.objects:
        if ob.get('handling_prop') == 'box':
            ob.vertex_groups['prop_box'].name = 'prop_closed'
    kraft, blue, item, tape = mats
    boxes(col,rig,prefix+'_OpenCarton',[
        ((0,-.34,.864),(.36,.28,.008),0),
        ((-.176,-.34,.987),(.008,.28,.246),0),
        ((.176,-.34,.987),(.008,.28,.246),0),
        ((0,-.476,.987),(.344,.008,.246),0),
        ((0,-.204,.987),(.344,.008,.246),0)],'prop_shell',[kraft])
    for name, center, size in [
        ('front',(0,-.410,1.111),(.344,.140,.003)),
        ('back',(0,-.270,1.111),(.344,.140,.003)),
        ('left',(.090,-.34,1.115),(.180,.280,.003)),
        ('right',(-.090,-.34,1.115),(.180,.280,.003))]:
        boxes(col,rig,prefix+'_Flap_'+name,[(center,size,0)],'prop_flap_'+name,[kraft])
    boxes(col,rig,prefix+'_Product',[((.32,-.32,1.029),(.085,.08,.09),0),
                                   ((.32,-.361,1.029),(.06,.002,.045),1)],'prop_item',[item,tape])
    boxes(col,rig,prefix+'_PickingTote',[
        ((.32,-.32,.916),(.22,.22,.112),0),
        ((.32,-.32,.978),(.20,.20,.012),0),
        ((.225,-.32,1.015),(.01,.20,.075),0),
        ((.415,-.32,1.015),(.01,.20,.075),0),
        ((.32,-.415,1.015),(.18,.01,.075),0),
        ((.32,-.225,1.015),(.18,.01,.075),0)],'prop_tote',[blue])
    boxes(col,rig,prefix+'_SealingTape',[((0,-.48,1.12),(.042,.28,.002),0)],'prop_tape',[tape])
    for ob in col.objects:
        if ob.get('handling_prop') == 'support':
            for vertex in ob.data.vertices:
                if vertex.co.z > .83:
                    vertex.co.x *= 2.1
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

    def contact(self, side, target, normal, forward=(0,-1,0), curl=0):
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
        pole = Vector(((1 if side=='L' else -1)*.61,-.10,1.16))-shoulder
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
        self.prop('prop_stand')
        self.prop('prop_shell' if opened else 'prop_closed')
        if opened:
            for name in ('front','back','left','right'):
                self.prop('prop_flap_'+name)


def author_operation(rig, ctrl, name, duration, oversize=False):
    count = round(duration*FPS)
    action = bpy.data.actions.new('FBF_'+ctrl.kind.title()+'_'+name)
    assign(rig,action)
    base = name.removesuffix('_Oversize')
    size = Vector((.48,.34,.32) if oversize else (.36,.28,.25))
    center = SOURCE+Vector((0,0,.035 if oversize else 0))
    top = center.z+size.z/2
    # Gestures are single operations: no instantaneous item/tape reset at the seam.
    for frame in range(count+1):
        ctrl.reset()
        t = frame/count
        lean = base in ('Prepare','Pack','RobotPack')
        ctrl.delta('spine',Quaternion((1,0,0),.27 if lean else .065))
        ctrl.delta('chest',Quaternion((1,0,0),.22 if lean else .055))
        ctrl.delta('neck',Quaternion((1,0,0),.025))
        bpy.context.view_layer.update()
        opened = base in ('Prepare','Pick','Pack','RobotPack')
        ctrl.carton(center,oversize=oversize,opened=opened)
        if base in ('Prepare','Pick','Pack','RobotPack'):
            close = ramp(t,.15,.42) if base in ('Pack','RobotPack') else 0
            major = ramp(t,.40,.65) if base in ('Pack','RobotPack') else 0
            if base == 'Prepare':
                major = 1-ramp(t,.12,.40)
                close = 1-ramp(t,.43,.73)
            for flap,axis,sign,amount in [
                ('front',(1,0,0),1,close),('back',(1,0,0),-1,close),
                ('left',(0,1,0),1,major),('right',(0,1,0),-1,major)]:
                ctrl.prop('prop_flap_'+flap,rotation=Quaternion(axis,sign*math.radians(100)*(1-amount)))
        if base == 'Pick':
            ctrl.prop('prop_tote')
            a=Vector((.32,-.32,1.029))
            b=Vector((.23,-.28,1.27+(.04 if oversize else 0)))
            c=Vector((0,-.34,1.26+(.05 if oversize else 0)))
            d=Vector((0,-.34,1.08))
            held = a.lerp(b,ramp(t,.15,.34)).lerp(c,ramp(t,.34,.50)).lerp(d,ramp(t,.50,.66))
            item = held.lerp(Vector((0,-.34,.915)),ramp(t,.69,.80))
            ctrl.prop('prop_item',item)
            retract = ramp(t,.73,1)
            hand = Vector((.27,-.23,1.18)).lerp(held+Vector((.0425,0,.012)),ramp(t,0,.12))
            hand = hand.lerp(Vector((.27,-.23,1.18)),retract)
            ctrl.contact('L',hand,(-1,0,0),curl=(ramp(t,.08,.15)*(1-ramp(t,.66,.72))))
            ctrl.contact('R',center+Vector((-size.x/2,0,.025)),(1,0,0),curl=1)
        elif base in ('Prepare','Pack','RobotPack'):
            # Palms follow the actual flap surfaces during the fold/open phases.
            for side, flap, sign in [('L','left',1),('R','right',-1)]:
                pb = rig.pose.bones['prop_flap_'+flap]
                deform=pb.matrix@pb.bone.matrix_local.inverted()
                local = Vector((-sign*.065,0,.003))
                target = deform@(pb.bone.head_local+local)
                normal=(deform.to_3x3().inverted().transposed()@Vector((0,0,-1))).normalized()
                forward=(deform.to_3x3()@Vector((0,-1,0))).normalized()
                if t < .46 or base=='Prepare':
                    front = rig.pose.bones['prop_flap_front' if side=='L' else 'prop_flap_back']
                    b = front.bone
                    minor_deform=front.matrix@b.matrix_local.inverted()
                    minor_target=minor_deform@(b.head_local+Vector((sign*.08,.065 if side=='L' else -.065,.003)))
                    blend=ramp(t,.34,.46)
                    minor_normal=(minor_deform.to_3x3().inverted().transposed()@Vector((0,0,-1))).normalized()
                    minor_forward=(minor_deform.to_3x3()@Vector((0,-1,0))).normalized()
                    if base=='Prepare':
                        target=target.lerp(minor_target,blend)
                        normal=normal.lerp(minor_normal,blend).normalized()
                        forward=forward.lerp(minor_forward,blend).normalized()
                    else:
                        target=minor_target.lerp(target,blend)
                        normal=minor_normal.lerp(normal,blend).normalized()
                        forward=minor_forward.lerp(forward,blend).normalized()
                # Release to a neutral hand position after sealing.
                if base in ('Pack','RobotPack') and t>.64:
                    if side=='R':
                        tape_target = Vector((0,-.43+.20*ramp(t,.68,.88),top+.01))
                    else:
                        tape_target = Vector((.14,-.30,top+.04))
                    target=target.lerp(tape_target,ramp(t,.64,.70))
                    normal=normal.lerp(Vector((0,0,-1)),ramp(t,.64,.70)).normalized()
                    forward=forward.lerp(Vector((0,-1,0)),ramp(t,.64,.70)).normalized()
                # Palm points down; target is the calibrated palm contact point.
                ctrl.contact(side,target,normal,forward,curl=0)
            if base in ('Pack','RobotPack'):
                reveal=ramp(t,.68,.88)
                ctrl.prop('prop_tape',pos=(0,center.y-size.y/2+size.y/2*reveal,top+.008),
                          scale=(1,max(.0001,reveal),1) if t>=.68 else (0,0,0))
        elif base == 'Inspect':
            lift = ramp(t,.17,.34)*(1-ramp(t,.75,.91))
            angle = math.radians(22)*math.sin(2*math.pi*ramp(t,.36,.72)) if .36<t<.72 else 0
            tilt = math.radians(6)*math.sin(math.pi*ramp(t,.36,.72)) if .36<t<.72 else 0
            rot = Quaternion((0,0,1),angle)@Quaternion((1,0,0),tilt)
            pos = center+Vector((0,.04*lift,.11*lift))
            ctrl.carton(pos,rot,oversize)
            for side,s in [('L',1),('R',-1)]:
                contact = pos+rot@Vector((s*size.x/2,0,.025))
                ctrl.contact(side,contact,rot@Vector((-s,0,0)),rot@Vector((0,-1,0)),curl=ramp(t,0,.12)*(1-ramp(t,.92,1)))
            ctrl.delta('head',Quaternion((0,0,1),angle*.5))
        key_pose(rig,frame)
    finish_action(rig,action,name,count)
    return {'name':name,'action':action.name,'duration_seconds':duration,'frames':count+1,
            'loop':False,'fps':FPS,'key_every_frame':True,'object_sync':True,
            'order_variant':'oversize' if oversize else 'standard'}


def copy_actor(source_col, scene, kind):
    col = bpy.data.collections.new('FRAME ANIMATIONS / '+kind.title())
    scene.collection.children.link(col)
    mapping={}
    for old in source_col.objects:
        new=old.copy()
        if old.data:
            new.data=old.data.copy()
        new.name='FBF_'+old.name
        new.hide_render=False
        new.hide_viewport=False
        col.objects.link(new)
        mapping[old]=new
    for old,new in mapping.items():
        if old.parent in mapping:
            new.parent=mapping[old.parent]
        for mod in new.modifiers:
            if mod.type=='ARMATURE' and mod.object in mapping:
                mod.object=mapping[mod.object]
    rig=next(ob for ob in col.objects if ob.type=='ARMATURE')
    rig.location=(0,0,0)
    rig.rotation_mode='XYZ'
    rig.rotation_euler=(0,0,0)
    rig.scale=(1,1,1)
    sources={track.name:track.strips[0].action for track in rig.animation_data.nla_tracks}
    rig.animation_data_clear()
    return col,rig,sources


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
        # Original closed carton remains the prop in the handling/idle clips.
        rig.pose.bones['prop_closed'].scale=(1,1,1)
        key_pose(rig,frame)
    finish_action(rig,action,name,count)
    return {'name':name,'action':action.name,'duration_seconds':duration,'frames':count+1,
            'loop':name in ('Idle','Walk','CarryIdle','CarryWalk','Assist','Break'),
            'fps':FPS,'key_every_frame':True,'object_sync':True}


def export_actor(col,rig,path,props_only=False):
    bpy.ops.object.select_all(action='DESELECT')
    rig.select_set(True)
    bpy.context.view_layer.objects.active=rig
    selected=[]
    for ob in col.objects:
        if ob.type=='ARMATURE' or not props_only or ob.get('handling_prop'):
            ob.select_set(True)
            selected.append(ob)
    rig.animation_data.action=None
    for tr in rig.animation_data.nla_tracks:
        tr.mute=False
    bpy.context.scene.frame_set(0)
    mesh_parents=[]
    for ob in selected:
        if ob.type=='MESH':
            mesh_parents.append((ob,ob.parent,ob.matrix_world.copy()))
            world=ob.matrix_world.copy()
            ob.parent=None
            ob.matrix_world=world
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


def build():
    OUT.mkdir(parents=True,exist_ok=True)
    source_scene=next(s for s in bpy.data.scenes if 'WORKER_Rig' in s.objects)
    bpy.context.window.scene=source_scene
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
            'source':str(ROOT/'warehouse_environment.blend'),'actors':{},
            'objects':['closed carton','open carton','four hinged flaps','product','picking tote','sealing tape','support'],
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
        new_bones=add_props(col,rig,kind.upper(),mats)
        ctrl=Controller(rig,kind,grip)
        manifest=json.loads((ROOT/(kind+'_manifest.json')).read_text())
        specs={c['name']:c['duration_seconds'] for c in manifest['clips']}
        if kind=='robot':
            specs.update({'Pick':4.,'Inspect':3.6,'Pick_Oversize':4.,'Inspect_Oversize':3.6})
        clips=[]
        for name,duration in specs.items():
            if name.removesuffix('_Oversize') in ('Prepare','Pick','Pack','RobotPack','Inspect'):
                clips.append(author_operation(rig,ctrl,name,duration,name.endswith('_Oversize')))
            else:
                clips.append(bake_source(rig,sources[name],ctrl,name,duration,new_bones))
            print('FRAME_CLIP',kind,name,flush=True)
        file='warehouse_worker' if kind=='worker' else 'humanoid_robot'
        export_actor(col,rig,OUT/(file+'.glb'))
        export_actor(col,rig,OUT/('interaction_objects_'+kind+'.glb'),True)
        assign(rig,bpy.data.actions['FBF_'+kind.title()+'_Pick'])
        scene.frame_set(57)
        actors[kind]=(col,rig)
        result['actors'][kind]={'file':file+'.glb','objects_file':'interaction_objects_'+kind+'.glb',
                               'bones':len(rig.data.bones),'clips':clips,
                               'max_ik_contact_error_m':max(ctrl.contacts)}
    # Arrange the editable native animation stage side by side, both facing -Y.
    actors['worker'][1].location.x=-.7
    actors['robot'][1].location.x=.7
    scene.frame_set(57)
    bpy.data.libraries.write(str(OUT/'characters_animated.blend'),{scene},fake_user=True,compress=True)
    (OUT/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print('FRAME_ANIMATIONS_COMPLETE',str(OUT),flush=True)
    return scene,actors


if __name__=='__main__':
    FBF_SCENE,FBF_ACTORS=build()
