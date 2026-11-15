"""Shared box handling: exact two-bone reach, full palm frames and rigid props."""
import bpy,math,json
from mathutils import Vector,Quaternion,Matrix

BOX_SIZE=(.36,.28,.25)
CONTACT_Z=.025
SOURCE=Vector((0,-.34,.985));HELD=Vector((0,-.30,1.125))
CLIPS=[('Idle',3.2,True),('Walk',1.,True),('CarryIdle',2.4,True),('Reach',2.4,False),('PickUp',3.2,False),('PlaceDown',3.2,False),('CarryWalk',1.,True)]

def reset_pose(rig):
    for pb in rig.pose.bones:pb.rotation_mode='QUATERNION';pb.location=(0,0,0);pb.rotation_quaternion=(1,0,0,0);pb.scale=(1,1,1)

def supplement_bones(bone,extras):
    for name,head,tail,parent in extras:bone(name,head,tail,parent)
    bone('prop_box',SOURCE,SOURCE+Vector((0,0,.10)),'root')
    bone('prop_stand',(0,0,0),(0,0,.10),'root')

def curves(action):
    if hasattr(action,'fcurves'):return list(action.fcurves)
    return [fc for layer in action.layers for strip in layer.strips for bag in strip.channelbags for fc in bag.fcurves]

def clear_curves(action):
    if hasattr(action,'fcurves'):
        for fc in list(action.fcurves):action.fcurves.remove(fc)
    else:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for fc in list(bag.fcurves):bag.fcurves.remove(fc)

def ease(t):t=max(0,min(1,t));return t*t*(3-2*t)
def pose_state(name,t):
    if name in ['Idle','Walk']:return {'center':HELD.copy(),'grip':0.,'approach':0.,'lean':0.,'box':False,'stand':False}
    if name in ['CarryIdle','CarryWalk']:
        center=HELD.copy();center.z+=(.002 if name=='CarryIdle' else .005)*math.sin(2*math.pi*t)
        return {'center':center,'grip':1.,'approach':1.,'lean':0.,'box':True,'stand':False}
    if name=='Reach':
        a=math.sin(math.pi*t)**2
        return {'center':SOURCE.copy(),'grip':0.,'approach':a,'lean':a,'box':False,'stand':False}
    u=t if name=='PickUp' else 1-t
    approach=ease(u/.32);grip=ease((u-.32)/.15);lift=ease((u-.50)/.40)
    return {'center':SOURCE.lerp(HELD,lift),'grip':grip,'approach':approach,'lean':approach*(1-lift),'box':True,'stand':False}

def create_motion(rig,body,col,link,kind,extras):
    prefix='Worker' if kind=='worker' else 'Robot';upper=prefix.upper()
    rest={name:b.matrix_local.copy() for name,b in rig.data.bones.items()}
    # Parent transforms are included in both the reach solve and wrist rotation.
    def set_rotation(name,rotation):
        pb=rig.pose.bones[name];b=pb.bone
        base=(pb.parent.matrix@b.parent.matrix_local.inverted()@b.matrix_local) if pb.parent else b.matrix_local.copy()
        pb.rotation_quaternion=base.to_quaternion().inverted()@rotation
    def delta(name,q):
        r=rest[name].to_quaternion();rig.pose.bones[name].rotation_quaternion=r.inverted()@q@r
    def euler(x=0,y=0,z=0):return Quaternion((0,0,1),z)@Quaternion((0,1,0),y)@Quaternion((1,0,0),x)
    def translate(name,position):
        pb=rig.pose.bones[name];b=pb.bone;base=(pb.parent.matrix@b.parent.matrix_local.inverted()@b.matrix_local) if pb.parent else b.matrix_local.copy()
        pb.location=base.to_3x3().inverted()@(Vector(position)-base.translation)
    def hanging(swing=0):
        for side,s in [('L',1),('R',-1)]:delta('upper_arm.'+side,euler(x=s*swing,y=s*.245));delta('forearm.'+side,euler(x=-.065))
    frames={};anchors={};contact_depth=.0325 if kind=='robot' else .046
    contact_length=.0625 if kind=='robot' else .052
    for side,s in [('L',1),('R',-1)]:
        b=rig.data.bones['hand.'+side];f=(b.tail_local-b.head_local).normalized();n=Vector((0,1,0));n=(n-f*n.dot(f)).normalized();w=n.cross(f).normalized()
        # The authored thumbs lie on the medial edge: the anatomical palm is +Y.
        # With fingers forward, both radial/thumb edges point upward instead of down.
        rest_frame=Matrix((w,n,f)).transposed();target_n=Vector((-s,0,0));target_f=Vector((0,-1,0));target_w=target_n.cross(target_f)
        target_frame=Matrix((target_w,target_n,target_f)).transposed();q=target_frame.to_quaternion()@rest_frame.to_quaternion().inverted()
        offset=f*contact_length+n*contact_depth;frames[side]=(q,offset,n,w,f)
        point=b.head_local+offset
        anchor=link(bpy.data.objects.new('ATTACH_'+upper+'_HAND_'+side,None));anchor.parent=rig;anchor.parent_type='BONE';anchor.parent_bone=b.name;anchor.empty_display_size=.025
        orientation=Matrix((n,-f,-w)).transposed().to_4x4();orientation.translation=point
        parent_frame=b.matrix_local@Matrix.Translation((0,b.length,0));anchor.matrix_parent_inverse=Matrix.Identity(4);anchor.matrix_basis=parent_frame.inverted()@orientation
        anchor['role']='palm_contact';anchor['normal_axis']='+X';anchors[side]=anchor
    def clip_face(poly,axis,value,keep_high):
        result=[]
        for a,b in zip(poly,poly[1:]+poly[:1]):
            da=a[axis]-value;db=b[axis]-value;ina=da>=0 if keep_high else da<=0;inb=db>=0 if keep_high else db<=0
            if ina:result.append(a)
            if ina!=inb:result.append(a.lerp(b,da/(da-db)))
        return result
    thumb_grips={}
    for side,s in [('L',1),('R',-1)]:
        name='thumb.'+side;b=rig.data.bones[name];q,offset,n,w,f=frames[side];r=rest[name].to_quaternion()
        target=q.inverted()@Vector((0,-.18,1)).normalized()
        up_local=r.inverted()@(b.tail_local-b.head_local).normalized().rotation_difference(target)@r
        axis_local=r.inverted()@(q.inverted()@Vector((0,1,0)))
        group=body.vertex_groups[name].index
        indices={v.index for v in body.data.vertices if any(g.group==group and g.weight>.999 for g in v.groups)}
        triangles=[list(p.vertices) for p in body.data.polygons if all(i in indices for i in p.vertices)]
        assert triangles,(kind,name,'missing thumb surface')
        local_points={i:rest[name].inverted()@body.data.vertices[i].co for i in indices}
        wrist=HELD+Vector((s*BOX_SIZE[0]/2,0,CONTACT_Z))-q@offset
        head=wrist+q@(b.head_local-rig.data.bones['hand.'+side].head_local)
        def gap(angle):
            local=Quaternion(axis_local,-s*angle)@up_local;rotation=q@r@local
            points={i:head+rotation@p for i,p in local_points.items()};distances=[]
            for ids in triangles:
                poly=[points[i] for i in ids]
                for axis,lo,hi in [(1,HELD.y-BOX_SIZE[1]/2,HELD.y+BOX_SIZE[1]/2),(2,HELD.z-BOX_SIZE[2]/2,HELD.z+BOX_SIZE[2]/2)]:
                    if poly:poly=clip_face(poly,axis,lo,True)
                    if poly:poly=clip_face(poly,axis,hi,False)
                distances.extend(s*p.x-BOX_SIZE[0]/2 for p in poly)
            return min(distances) if distances else float('inf')
        open_gap=gap(0);low=0.;high=math.radians(40)
        assert open_gap>0,(kind,name,'thumb already intersects carton',open_gap)
        assert gap(high)<0,(kind,name,'thumb cannot reach carton',open_gap,gap(high))
        for _ in range(30):
            mid=(low+high)/2
            if gap(mid)>0:low=mid
            else:high=mid
        angle=(low+high)/2
        thumb_grips[name]=(up_local,axis_local,angle,open_gap,gap(angle))
        print('THUMB_SURFACE_FIT',kind,side,'angle_deg',math.degrees(angle),'original_gap_m',open_gap,'closed_gap_m',gap(angle),flush=True)
    def solve_arm(side,target,hand_rotation):
        s=1 if side=='L' else -1;up=rig.data.bones['upper_arm.'+side];fore=rig.data.bones['forearm.'+side]
        bpy.context.view_layer.update();shoulder=rig.pose.bones[up.name].head.copy();v=Vector(target)-shoulder;dist=v.length
        assert abs(up.length-fore.length)+1e-5<dist<up.length+fore.length-1e-5,(kind,side,dist)
        direction=v.normalized();a=(up.length**2-fore.length**2+dist**2)/(2*dist);h=math.sqrt(max(0,up.length**2-a*a))
        pole=Vector((s*.61,-.10,1.16))-shoulder;perp=(pole-direction*pole.dot(direction)).normalized();elbow=shoulder+direction*a+perp*h
        q=(up.tail_local-up.head_local).rotation_difference(elbow-shoulder);set_rotation(up.name,q@rest[up.name].to_quaternion());bpy.context.view_layer.update()
        q=(fore.tail_local-fore.head_local).rotation_difference(Vector(target)-elbow);set_rotation(fore.name,q@rest[fore.name].to_quaternion());bpy.context.view_layer.update()
        set_rotation('hand.'+side,hand_rotation);bpy.context.view_layer.update()
        assert (rig.pose.bones['hand.'+side].head-Vector(target)).length<1e-5
    def curl(amount,approach):
        for name,head,tail,parent in extras:
            side=name[-1];s=1 if side=='L' else -1;q,off,n,w,f=frames[side]
            if name.startswith('thumb'):
                up_local,axis_local,angle,_,_=thumb_grips[name]
                local=Quaternion(axis_local,-s*angle*amount)@up_local
                rig.pose.bones[name].rotation_quaternion=Quaternion((1,0,0,0)).slerp(local,approach)
            else:
                local=rest[name].to_quaternion().inverted()@w
                rig.pose.bones[name].rotation_quaternion=Quaternion(local,-.18*amount)
    # The visible carton and its support are part of both native and GLB clips.
    def material(name,rgb,rough):
        m=bpy.data.materials.get('Handling / '+name) or bpy.data.materials.new('Handling / '+name);m.use_nodes=True;m.diffuse_color=(*rgb,1)
        p=m.node_tree.nodes.get('Principled BSDF');p.inputs['Base Color'].default_value=(*rgb,1);p.inputs['Roughness'].default_value=rough;return m
    cardboard=material('Kraft carton',(.38,.218,.095),.91);tape=material('Paper tape',(.59,.432,.233),.78);support=material('Demonstration support',(.11,.16,.16),.83)
    def rigid_boxes(name,boxes,bone_name,mats):
        vertices=[];faces=[];material_indices=[]
        for center,size,matid in boxes:
            x,y,z=center;rx,ry,rz=[v/2 for v in size];start=len(vertices)
            vertices.extend((x+sx*rx,y+sy*ry,z+sz*rz) for sz in [-1,1] for sy in [-1,1] for sx in [-1,1])
            for a,b,c,d in [(0,2,3,1),(4,5,7,6),(0,1,5,4),(2,6,7,3),(0,4,6,2),(1,3,7,5)]:faces.extend([(start+a,start+b,start+c),(start+a,start+c,start+d)]);material_indices.extend([matid,matid])
        mesh=bpy.data.meshes.new(name+'_Mesh');mesh.from_pydata(vertices,[],faces);mesh.update()
        for m in mats:mesh.materials.append(m)
        for p,i in zip(mesh.polygons,material_indices):p.material_index=i;p.use_smooth=False
        ob=link(bpy.data.objects.new(name,mesh));ob.parent=rig;ob.vertex_groups.new(name=bone_name).add(list(range(len(vertices))),1,'REPLACE');mod=ob.modifiers.new('Rigid prop binding','ARMATURE');mod.object=rig
        ob['operation_prop']=True;ob['prop_role']=bone_name;ob[f'{kind}_asset']=True
        mesh['operation_prop']=True;mesh['prop_role']=bone_name;mesh[f'{kind}_asset']=True
        return ob
    box=rigid_boxes(upper+'_ClosedCarton',[(SOURCE,BOX_SIZE,0),(SOURCE+Vector((0,0,.1254)),(.045,.281,.0008),1)],'prop_box',[cardboard,tape])
    clips=[];contacts=[]
    for name,duration,loop in CLIPS:
        action=bpy.data.actions.get(prefix+'_'+name) or bpy.data.actions.new(prefix+'_'+name)
        clear_curves(action)
        rig.animation_data_create();rig.animation_data.action=action
        if hasattr(action,'slots') and action.slots:rig.animation_data.action_slot=action.slots[0]
        count=round(duration*30)
        for frame in range(count+1):
            reset_pose(rig);t=frame/count;phase=2*math.pi*t;state=pose_state(name,t)
            if name=='Idle':
                hanging(.016*math.sin(phase));delta('chest',euler(x=.009*math.sin(phase)));rig.pose.bones['hips'].location.z=.0018*math.sin(phase)
            elif name in ['Walk','CarryWalk']:
                hanging(.24*math.sin(phase) if name=='Walk' else 0)
                for side,s in [('L',1),('R',-1)]:
                    a=phase+(0 if s==1 else math.pi);thigh=-.36*math.sin(a);knee=.09+.49*max(0,-math.sin(a));delta('thigh.'+side,euler(x=thigh));delta('shin.'+side,euler(x=knee));delta('foot.'+side,euler(x=-thigh-knee))
                rig.pose.bones['hips'].location.z=-.008+.009*math.cos(2*phase);delta('hips',euler(z=.028*math.sin(phase)))
            else:hanging()
            if name not in ['Idle','Walk']:
                delta('spine',euler(x=.075*state['lean']));delta('chest',euler(x=.075*state['lean']));bpy.context.view_layer.update()
                for side,s in [('L',1),('R',-1)]:
                    q,offset,n,w,f=frames[side];hand_name='hand.'+side;b=rig.data.bones[hand_name]
                    start=rig.pose.bones[hand_name].head.copy();start_rotation=rig.pose.bones[hand_name].matrix.to_quaternion();end_rotation=q@rest[hand_name].to_quaternion()
                    contact=state['center']+Vector((s*BOX_SIZE[0]/2,0,CONTACT_Z));target=contact-q@offset
                    solve_arm(side,start.lerp(target,state['approach']),start_rotation.slerp(end_rotation,state['approach']))
                curl(state['grip'],state['approach'])
            translate('prop_box',state['center']);rig.pose.bones['prop_box'].scale=(1,1,1) if state['box'] else (0,0,0)
            rig.pose.bones['prop_stand'].scale=(1,1,1) if state['stand'] else (0,0,0);bpy.context.view_layer.update()
            if state['grip']>.999:
                for side,s in [('L',1),('R',-1)]:
                    desired=state['center']+Vector((s*BOX_SIZE[0]/2,0,CONTACT_Z));actual=anchors[side].matrix_world.translation
                    error=(actual-desired).length;assert error<.00002,(kind,name,frame,side,error);contacts.append(error)
            if state['approach']>.999:
                for side in ['L','R']:
                    thumb=rig.pose.bones['thumb.'+side];direction=(thumb.tail-thumb.head).normalized()
                    assert direction.z>.75,(kind,name,frame,side,'thumb must remain above the grip',tuple(direction))
            for pb in rig.pose.bones:
                pb.keyframe_insert('rotation_quaternion',frame=frame,group=pb.name);pb.keyframe_insert('scale',frame=frame,group=pb.name)
                if pb.name in ['hips','root','prop_box']:pb.keyframe_insert('location',frame=frame,group=pb.name)
        for fc in curves(action):
            for key in fc.keyframe_points:key.interpolation='LINEAR'
            if loop:fc.modifiers.new('CYCLES')
        clips.append({'name':name,'action':action.name,'duration_seconds':duration,'loop':loop,'root_motion':False})
        rig.animation_data.action=None;track=rig.animation_data.nla_tracks.new();track.name=name;strip=track.strips.new(action.name,0,action);strip.name=name;strip.action_frame_start=0;strip.action_frame_end=count;track.mute=True
    return clips,{'box_size_m':list(BOX_SIZE),'source_center_blender_m':list(SOURCE),'held_center_blender_m':list(HELD),'palm_contact_offset_z_m':CONTACT_Z,'max_authored_contact_error_m':max(contacts),'thumb_orientation':'upper edge; flexed into surface contact when gripping','thumb_surface_fits':{name:{'flex_degrees':math.degrees(data[2]),'open_gap_m':data[3],'closed_gap_m':data[4]} for name,data in thumb_grips.items()},'finger_direction_blender':[0,-1,0],'finger_bones':len(extras),'hand_scale':1.25 if kind=='robot' else 1.,'prop_bones':['prop_box','prop_stand']}
