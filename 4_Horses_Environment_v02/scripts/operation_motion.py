"""Visual-only activity clips for the four logical stages, breaks and robot service.

These loops are sampled inside intervals supplied by the simulation. They never
assign work, release an order or determine a production duration.
"""
import bpy,math,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from mathutils import Vector,Quaternion,Matrix
from character_motion import reset_pose,SOURCE,curves,clear_curves

OPERATIONS={
 'worker':[('Prepare',3.2,False),('Pick',4.,False),('Pack',3.,False),('Inspect',3.6,False),('Assist',3.2,True),('Break',4.,True)],
 'robot':[('RobotPack',2.8,False),('Jammed',1.2,True),('Service',2.4,True),('Offline',2.0,True)]}
for actor in ['worker','robot']:
    OPERATIONS[actor]+=[(name+'_Oversize',duration,loop) for name,duration,loop in list(OPERATIONS[actor]) if name in ['Prepare','Pick','Pack','Inspect','RobotPack','Jammed','Service']]

def build_operation_actions(rig,kind,only=None):
    prefix='Worker' if kind=='worker' else 'Robot';rest={b.name:b.matrix_local.copy() for b in rig.data.bones}
    operations=[item for item in OPERATIONS[kind] if only is None or item[0] in only]
    wanted={n for n,_,_ in operations}
    for track in list(rig.animation_data.nla_tracks):
        if track.name in wanted:rig.animation_data.nla_tracks.remove(track)
    def euler(x=0,y=0,z=0):return Quaternion((0,0,1),z)@Quaternion((0,1,0),y)@Quaternion((1,0,0),x)
    def delta(name,q):
        r=rest[name].to_quaternion();rig.pose.bones[name].rotation_quaternion=r.inverted()@q@r
    def set_rotation(name,q):
        pb=rig.pose.bones[name];b=pb.bone;base=pb.parent.matrix@b.parent.matrix_local.inverted()@b.matrix_local if pb.parent else b.matrix_local
        pb.rotation_quaternion=base.to_quaternion().inverted()@q
    def hand_rotation(side,normal=(0,0,-1),forward=(0,-1,0)):
        b=rig.data.bones['hand.'+side];f=(b.tail_local-b.head_local).normalized();n=Vector((0,1,0));n=(n-f*n.dot(f)).normalized();w=n.cross(f)
        tf=Vector(forward).normalized();tn=Vector(normal).normalized();tn=(tn-tf*tn.dot(tf)).normalized();tw=tn.cross(tf)
        q=Matrix((tw,tn,tf)).transposed().to_quaternion()@Matrix((w,n,f)).transposed().to_quaternion().inverted()
        return q@rest[b.name].to_quaternion()
    top_raise=0.;oversize=False
    def solve(side,target,normal=(0,0,-1),forward=(0,-1,0)):
        s=1 if side=='L' else -1;target=Vector(target);target.z+=top_raise-(.013 if kind=='robot' and normal==(0,0,-1) else 0);up=rig.data.bones['upper_arm.'+side];fore=rig.data.bones['forearm.'+side]
        bpy.context.view_layer.update();shoulder=rig.pose.bones[up.name].head.copy();direction=target-shoulder;dist=direction.length;direction.normalize()
        assert abs(up.length-fore.length)+1e-4<dist<up.length+fore.length-1e-4,(kind,side,tuple(target),dist)
        a=(up.length**2-fore.length**2+dist**2)/(2*dist);h=math.sqrt(max(0,up.length**2-a*a));pole=Vector((s*.63,-.08,1.15))-shoulder
        perp=(pole-direction*pole.dot(direction)).normalized();elbow=shoulder+direction*a+perp*h
        q=(up.tail_local-up.head_local).rotation_difference(elbow-shoulder);set_rotation(up.name,q@rest[up.name].to_quaternion());bpy.context.view_layer.update()
        q=(fore.tail_local-fore.head_local).rotation_difference(target-elbow);set_rotation(fore.name,q@rest[fore.name].to_quaternion());bpy.context.view_layer.update()
        set_rotation('hand.'+side,hand_rotation(side,normal,forward));bpy.context.view_layer.update()
        # Relaxed thumb on the plane of the palm; no demonstration grasp is transferred.
        b=rig.data.bones['thumb.'+side];current=rig.pose.bones[b.name].matrix.to_quaternion();axis=current@Vector((0,1,0))
        desired=Vector((-s*.7,-.7,0)).normalized() if normal==(0,0,-1) else Vector((0,-.2,1)).normalized()
        set_rotation(b.name,axis.rotation_difference(desired)@current)
    def props(show):
        b=rig.data.bones['prop_box'];pb=rig.pose.bones[b.name];base=pb.parent.matrix@b.parent.matrix_local.inverted()@b.matrix_local
        center=SOURCE+Vector((0,0,.035 if oversize else 0));pb.location=base.to_3x3().inverted()@(center-base.translation)
        scale=Matrix.Diagonal((.48/.36,.34/.28,.32/.25)) if oversize else Matrix.Identity(3)
        rotation=b.matrix_local.to_3x3();local=rotation.inverted()@scale@rotation
        pb.scale=tuple(local[i][i] for i in range(3)) if show else (0,0,0);rig.pose.bones['prop_stand'].scale=(0,0,0)
    clips=[]
    for name,duration,loop in operations:
        base_name=name.removesuffix('_Oversize');oversize=name.endswith('_Oversize');top_raise=.07 if oversize else 0.
        action=bpy.data.actions.get(prefix+'_'+name) or bpy.data.actions.new(prefix+'_'+name)
        clear_curves(action)
        rig.animation_data.action=action
        if hasattr(action,'slots') and action.slots:rig.animation_data.action_slot=action.slots[0]
        count=round(duration*30)
        for frame in range(0, count + 1):
            reset_pose(rig);t=frame/count;phase=2*math.pi*t
            p=phase
            for side,s in [('L',1),('R',-1)]:delta('upper_arm.'+side,euler(y=s*.245));delta('forearm.'+side,euler(x=-.065))
            active=base_name not in ['Break','Offline'];props(active and base_name!='Assist')
            if 'prop_closed' in rig.pose.bones:
                rig.pose.bones['prop_closed'].scale = (1,1,1) if (active and base_name not in ['Assist','Prepare','Pick','Pack','RobotPack','Jammed','Service']) else (0,0,0)
            if active:
                delta('spine',euler(x=.045));delta('chest',euler(x=.04));delta('neck',euler(x=.025));bpy.context.view_layer.update()
                if base_name=='Prepare':
                    for side,s in [('L',1),('R',-1)]:solve(side,(s*(.16+.035*math.cos(p)),-.235+.025*math.sin(p),1.155+.025*(1-math.cos(p))))
                elif base_name=='Pick':
                    solve('L',(.235+.055*math.sin(p),-.23-.045*math.cos(p),1.17+.035*math.sin(p)**2))
                    solve('R',(-.12,-.22,1.155))
                elif base_name in ['Pack','RobotPack']:
                    for side,s in [('L',1),('R',-1)]:
                        pp=p+(0 if s==1 else math.pi);solve(side,(s*(.115+.025*math.cos(pp)),-.235-.045*math.sin(pp),1.155+.012*math.sin(pp)**2))
                elif base_name=='Jammed':
                    recoil=math.sin(math.pi*t)**2;delta('head',euler(x=.14,z=.26*math.sin(p)))
                    for side,s in [('L',1),('R',-1)]:solve(side,(s*(.22+.02*recoil),-.26+.025*recoil,1.19+.05*recoil))
                elif base_name=='Service':
                    ret=math.sin(math.pi*t)**2;delta('head',euler(x=.10-.04*ret,z=-.18*ret))
                    for side,s in [('L',1),('R',-1)]:solve(side,(s*(.22+.06*ret),-.26+.08*ret,1.19+.13*ret))
                elif base_name=='Inspect':
                    solve('L',(.12,-.245-.045*math.sin(p),1.185+.018*math.cos(p)))
                    solve('R',(-.13,-.225,1.155));delta('head',euler(z=.035*math.sin(p),x=.025))
                elif base_name=='Assist':
                    reach=math.sin(math.pi*t)**2;delta('spine',euler(x=.22*reach));delta('chest',euler(x=.18*reach));bpy.context.view_layer.update()
                    for side,s in [('L',1),('R',-1)]:solve(side,(s*(.22-.07*reach),-.20-.26*reach,1.08-.08*reach),(0,1,0),(0,0,-1))
            elif base_name=='Break':
                stretch=math.sin(math.pi*t)**2;delta('head',euler(x=.06-.12*stretch,z=.10*math.sin(p)));delta('chest',euler(x=-.08*stretch));bpy.context.view_layer.update()
                solve('R',(-.26+.06*stretch,-.12-.12*stretch,1.02+.32*stretch),(1,0,0),(0,0,-1))
                solve('L',(.245,-.08,1.04),(-1,0,0),(0,0,-1))
            elif base_name=='Offline':
                pulse=.5*(1-math.cos(p));delta('spine',euler(x=.06+.018*pulse));delta('chest',euler(x=.08+.022*pulse));delta('head',euler(x=.22+.035*pulse))
            bpy.context.view_layer.update()
            for pb in rig.pose.bones:
                pb.keyframe_insert('rotation_quaternion',frame=frame,group=pb.name);pb.keyframe_insert('scale',frame=frame,group=pb.name)
                if pb.name in ['hips','root','prop_box']:pb.keyframe_insert('location',frame=frame,group=pb.name)
        for fc in curves(action):
            for key in fc.keyframe_points:key.interpolation='LINEAR'
            fc.modifiers.new('CYCLES')
        rig.animation_data.action=None;track=rig.animation_data.nla_tracks.new();track.name=name;strip=track.strips.new(action.name,0,action);strip.action_frame_end=count;track.mute=True
        clips.append({'name':name,'action':action.name,'duration_seconds':duration,'fps':30,'loop':loop,'root_motion':False,'visual_only':True,'frozen':False,'order_variant':'oversize' if oversize else 'standard'})
    rig.animation_data.action=bpy.data.actions[prefix+'_Idle'];bpy.context.scene.frame_set(1)
    return clips

def prepare_existing_scene(out,root,variants_only=False,frozen_only=False,robot_only=False,save_blend=False):
    import json
    for kind,prefix,asset in [('worker','WORKER','warehouse_worker'),('robot','ROBOT','humanoid_robot')]:
        if robot_only and kind!='robot':continue
        rig=bpy.data.objects[prefix+'_Rig'];location=rig.location.copy();rig.location=(0,0,0)
        only={name for name,_,_ in OPERATIONS[kind] if name.removesuffix('_Oversize') in ['Jammed','Service','Offline']} if frozen_only else ({name for name,_,_ in OPERATIONS[kind] if name.endswith('_Oversize')} if variants_only else None)
        additions=build_operation_actions(rig,kind,only=only);rig.location=location
        path=out/(kind+'_manifest.json');manifest=json.loads(path.read_text());names={x['name'] for x in additions};manifest['clips']=[c for c in manifest['clips'] if c['name'] not in names]+additions;manifest['version']='2.0.0';manifest['visual_operations']='Robotization Bench v1 document; no production timing in clips'
        path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
        print(kind.upper()+'_OPERATIONS_COMPLETE',len(additions),flush=True)
    if save_blend and Path(bpy.data.filepath).name!='warehouse_environment.blend':
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)

if __name__=='__main__':
    import sys,argparse
    from pathlib import Path
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--variants-only',action='store_true');p.add_argument('--frozen-only',action='store_true');p.add_argument('--robot-only',action='store_true');opt=p.parse_args(sys.argv[sys.argv.index('--')+1:]);prepare_existing_scene(Path(opt.output),Path(__file__).resolve().parent.parent,opt.variants_only,opt.frozen_only,opt.robot_only)
