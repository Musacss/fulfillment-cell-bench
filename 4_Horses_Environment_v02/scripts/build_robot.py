"""Original low-poly humanoid robot in the existing 4 Horses Blender project.

blender -b warehouse_environment.blend -t 6 --python scripts/build_robot.py -- --output PATH --render
All armor, joints, hands and feet are authored meshes. Rigid panels keep one bone.
"""
import bpy, bmesh, math, json, argparse, sys
from pathlib import Path
from mathutils import Vector, Quaternion, Matrix

P=argparse.ArgumentParser();P.add_argument('--output',required=True);P.add_argument('--render',action='store_true');P.add_argument('--quick',action='store_true')
opt=P.parse_args(sys.argv[sys.argv.index('--')+1:]);OUT=Path(opt.output);ROOT=Path(__file__).resolve().parent.parent
(OUT/'modules').mkdir(exist_ok=True,parents=True)
sc=bpy.context.scene;bpy.context.preferences.filepaths.save_version=0;bpy.context.preferences.edit.use_global_undo=False
for ob in list(bpy.data.objects):
    if ob.get('robot_asset') or ob.name.startswith(('ROBOT_','ATTACH_ROBOT_')):bpy.data.objects.remove(ob,do_unlink=True)
old=bpy.data.collections.get('CHARACTERS / Humanoid robot')
if old:bpy.data.collections.remove(old)
for blocks in [bpy.data.meshes,bpy.data.armatures]:
    for data in list(blocks):
        if data.name.startswith('ROBOT_') and data.users==0:blocks.remove(data)
col=bpy.data.collections.new('CHARACTERS / Humanoid robot');sc.collection.children.link(col)
def link(ob):col.objects.link(ob);ob['robot_asset']=True;return ob

palette={
 'shell':('Warm porcelain armor',(.53,.58,.56),.68,.30),
 'secondary':('Petrol gray side panels',(.105,.165,.18),.76,.35),
 'joint':('Graphite joint bellows',(.023,.038,.041),.88,.10),
 'metal':('Satin actuator metal',(.235,.29,.30),.50,.65),
 'accent':('Ochre safety markings',(.72,.365,.055),.71,.15),
 'visor':('Blank graphite faceplate',(.028,.047,.052),.48,.30),
 'sole':('Rubber contact pads',(.017,.025,.027),.96,0),
}
materials=[];mi={}
for key,(name,rgb,rough,metallic) in palette.items():
    m=bpy.data.materials.get('Robot / '+name) or bpy.data.materials.new('Robot / '+name)
    m.use_nodes=True;m.diffuse_color=(*rgb,1);p=m.node_tree.nodes.get('Principled BSDF')
    p.inputs['Base Color'].default_value=(*rgb,1);p.inputs['Roughness'].default_value=rough;p.inputs['Metallic'].default_value=metallic
    mi[key]=len(materials);materials.append(m)
V=[];F=[];FM=[];W=[];parts=[]
def vert(co,bone):V.append(tuple(co));W.append({bone:1});return len(V)-1
def face(ids,mat):
    if len(ids)==4:
        a,b,c,d=ids;tris=[(a,b,c),(a,c,d)]
    else:tris=[tuple(ids)]
    for tri in tris:F.append(tri);FM.append(mi[mat])
def bridge(a,b,mat):
    for j in range(len(a)):face([a[j],a[(j+1)%len(a)],b[(j+1)%len(a)],b[j]],mat(j) if callable(mat) else mat)
def cap(rr,mat,reverse=False):
    for j in range(1,len(rr)-1):face([rr[0],rr[j+1],rr[j]] if reverse else [rr[0],rr[j],rr[j+1]],mat)
def outline(rx,ry,chamfer=.27):
    bx=rx*chamfer;by=ry*chamfer
    return [(-rx+bx,-ry),(rx-bx,-ry),(rx,-ry+by),(rx,ry-by),(rx-bx,ry),(-rx+bx,ry),(-rx,ry-by),(-rx,-ry+by)]
def shell(name,specs,bone,mat='shell',n=8,center=(0,0),rect=False,angle=0,side_mats=None):
    start=len(V);rings=[]
    for z,rx,ry in specs:
        coords=outline(rx,ry) if rect else [(rx*math.cos(angle+j*2*math.pi/n),ry*math.sin(angle+j*2*math.pi/n)) for j in range(n)]
        rings.append([vert((center[0]+x,center[1]+y,z),bone) for x,y in coords])
    cap(rings[0],mat,True)
    for k,(a,b) in enumerate(zip(rings,rings[1:])):bridge(a,b,(lambda j:side_mats(k,j)) if side_mats else mat)
    cap(rings[-1],mat);parts.append({'name':name,'bone':bone,'vertices':len(V)-start})
    return rings
def beam(name,a,b,sections,bone,mat='shell',rect=True,n=8):
    a=Vector(a);b=Vector(b);axis=(b-a).normalized();u=Vector((0,1,0));u=(u-axis*u.dot(axis)).normalized();v=u.cross(axis).normalized()
    rings=[];start=len(V)
    for t,rx,ry in sections:
        coords=outline(rx,ry) if rect else [(rx*math.cos(j*2*math.pi/n),ry*math.sin(j*2*math.pi/n)) for j in range(n)]
        rings.append([vert(a+axis*t+v*x+u*y,bone) for x,y in coords])
    cap(rings[0],mat,True)
    for a,b in zip(rings,rings[1:]):bridge(a,b,mat)
    cap(rings[-1],mat);parts.append({'name':name,'bone':bone,'vertices':len(V)-start})
    return rings
def box(name,c,size,bone,mat='shell',chamfer=.27):
    x,y,z=c;rx,ry,rz=[v/2 for v in size]
    return shell(name,[(z-rz,rx,ry),(z+rz,rx,ry)],bone,mat,center=(x,y),rect=True)
def ball(name,c,r,bone,mat='joint',n=10):
    cx,cy,cz=c;rx,ry,rz=r if isinstance(r,tuple) else (r,r,r)
    specs=[]
    for a in [-math.pi*.46,-math.pi*.25,0,math.pi*.25,math.pi*.46]:specs.append((cz+rz*math.sin(a),rx*math.cos(a),ry*math.cos(a)))
    shell(name,specs,bone,mat,n=n,center=(cx,cy))
def axle(name,c,length,r,bone,mat='metal',axis=(1,0,0)):
    c=Vector(c);ax=Vector(axis).normalized()
    return beam(name,c-ax*length/2,c+ax*length/2,[(0,r*.80,r*.80),(.004,r,r),(length-.004,r,r),(length,r*.80,r*.80)],bone,mat,rect=False,n=10)

# Human-sized central body. The ribbed waist is separate from rigid chest armor.
shell('Pelvic frame',[(.866,.104,.073),(.899,.155,.094),(1.010,.159,.096),(1.052,.143,.083)],'hips',rect=True)
box('Pelvic front inset',(0,-.099,.976),(.148,.014,.076),'hips','secondary')
box('Pelvic ochre center',(0,-.108,.985),(.037,.008,.039),'hips','accent')
shell('Abdominal core',[(1.035,.104,.076),(1.205,.133,.087),(1.255,.149,.095)],'spine','joint',rect=True)
for z,rx,ry in [(1.078,.111,.080),(1.137,.121,.085),(1.198,.131,.091)]:
    shell('Segmented abdominal rib',[(z-.010,rx,ry),(z+.010,rx,ry)],'spine','metal',rect=True)
shell('Chest armor',[(1.226,.137,.094),(1.272,.173,.109),(1.414,.211,.112),(1.470,.180,.093),(1.493,.073,.066)],'chest',rect=True,
      side_mats=lambda k,j:'secondary' if j in [2,3,4,5,6] else ('accent' if k==0 and j==0 else 'shell'))
box('Chest service panel',(0,-.116,1.348),(.092,.014,.111),'chest','secondary')
box('Chest vertical marking',(0,-.125,1.348),(.022,.006,.083),'chest','accent')
box('Back access panel',(0,.113,1.363),(.142,.014,.118),'chest','secondary')
for s in [-1,1]:box('Back panel recess',(s*.038,.123,1.365),(.012,.006,.067),'chest','joint')
shell('Neck actuator',[(1.473,.037,.035),(1.611,.036,.034)],'neck','joint',n=10,center=(0,.003))
for z in [1.513,1.562]:shell('Neck collar',[(z-.007,.043,.041),(z+.007,.043,.041)],'neck','metal',n=10,center=(0,.003))

# Blank chamfered head: jaw, temples and crown follow human proportions.
head_specs=[(1.595,.046,.049),(1.619,.072,.066),(1.660,.093,.082),(1.760,.096,.084),(1.802,.082,.073),(1.836,.050,.046),(1.851,.021,.022)]
shell('Faceless head',head_specs,'head',rect=True,center=(0,-.004),side_mats=lambda k,j:'visor' if k==2 and j==0 else ('secondary' if j in [3,4,5] and 1<=k<=3 else 'shell'))
box('Occipital panel',(0,.080,1.717),(.064,.011,.074),'head','secondary')

motion_extra_bones=[]
for side,s in [('L',1),('R',-1)]:
    shoulder=Vector((s*.222,0,1.438));elbow=Vector((s*.318,-.012,1.153));wrist=Vector((s*.389,-.033,.945))
    up='upper_arm.'+side;fore='forearm.'+side;hand='hand.'+side
    ball('Shoulder joint',shoulder,.063,up)
    beam('Shoulder and upper arm armor',shoulder,elbow,[(.012,.039,.043),(.041,.075,.075),(.111,.067,.069),(.132,.049,.052),(.241,.044,.050),(.267,.033,.037)],up)
    # Small front safety patch follows the shoulder, rather than widening its outline.
    box('Shoulder safety marking',(s*.248,-.076,1.410),(.049,.009,.025),up,'accent')
    ball('Elbow joint',elbow,(.049,.046,.047),fore)
    axle('Elbow transverse hinge',elbow,.110,.034,fore)
    beam('Forearm armor',elbow,wrist,[(.029,.033,.036),(.053,.055,.058),(.175,.043,.045),(.205,.035,.037)],fore)
    axis=(wrist-elbow).normalized();c=elbow+axis*.128
    box('Forearm dark service strip',(c.x,-.087,c.z),(.035,.008,.085),fore,'secondary')
    ball('Wrist flex joint',wrist,.031,hand,n=8)
    hand_start=len(V)
    hand_axis=Vector((s*.214,-.0034,-1)).normalized();across=Vector((1,0,s*.214)).normalized();depth=Vector((0,1,0))
    def handpos(u,t,d=0):return wrist+hand_axis*t+across*u+depth*d
    beam('Human-sized palm',wrist,wrist+hand_axis,[(.007,.029,.022),(.024,.043,.026),(.064,.039,.024),(.077,.035,.021)],hand)
    for j,off in enumerate([-.027,-.009,.009,.027]):
        end=.113 if j in [1,2] else .105
        a=handpos(off,.071);b=handpos(off,end)
        name='finger_'+str(j+1)+'.'+side
        beam('Finger '+str(j+1),a,b,[(0,.0075,.019),(.009,.0075,.019),(end-.071,.006,.015)],name,'secondary')
        motion_extra_bones.append((name,wrist+(a-wrist)*1.25,wrist+(b-wrist)*1.25,hand))
    a=handpos(-s*.036,.031,-.006);b=handpos(-s*.054,.073,-.002)
    beam('Thumb',a,b,[(0,.011,.020),(.019,.012,.020),((b-a).length,.009,.015)],'thumb.'+side,'shell')
    motion_extra_bones.append(('thumb.'+side,wrist+(a-wrist)*1.25,wrist+(b-wrist)*1.25,hand))
    for i in range(hand_start,len(V)):V[i]=tuple(wrist+(Vector(V[i])-wrist)*1.25)

    hip=Vector((s*.097,0,.940));knee=Vector((s*.097,-.025,.530));ankle=Vector((s*.097,.010,.165))
    thigh='thigh.'+side;shin='shin.'+side;foot='foot.'+side
    ball('Hip joint',hip,(.055,.059,.057),thigh)
    beam('Upper leg armor',hip,knee,[(.046,.051,.058),(.077,.069,.077),(.278,.059,.067),(.355,.041,.046)],thigh)
    box('Thigh outer cover',(s*.158,.003,.753),(.016,.091,.165),thigh,'secondary')
    ball('Knee joint',knee,(.052,.050,.051),shin)
    axle('Knee transverse hinge',knee,.112,.036,shin)
    box('Knee shield',(s*.097,-.080,.530),(.090,.025,.071),shin,'shell')
    box('Knee safety marking',(s*.097,-.095,.532),(.048,.005,.015),shin,'accent')
    beam('Shin armor',knee,ankle,[(.032,.037,.045),(.070,.056,.062),(.254,.044,.051),(.317,.032,.038)],shin)
    box('Rear calf actuator',(s*.097,.043,.355),(.031,.022,.143),shin,'metal')
    ball('Ankle joint',ankle,(.035,.038,.037),foot,n=8)
    # Compact foot with a broad heel support and no oversized shoe silhouette.
    cx=s*.097;outline_foot=[(-.035,-.148),(.035,-.148),(.057,-.126),(.058,.060),(.040,.090),(-.040,.090),(-.058,.060),(-.057,-.126)]
    rr=[]
    for z,scale in [(.012,1),(.032,1),(.043,.96)]:rr.append([vert((cx+x*scale,y,z),foot) for x,y in outline_foot])
    cap(rr[0],'sole',True);bridge(rr[0],rr[1],'sole');bridge(rr[1],rr[2],'secondary')
    top=[vert((cx+x*.90,y*.91,.078+max(0,y+.08)*.29),foot) for x,y in outline_foot]
    bridge(rr[2],top,'shell');cap(top,'shell')
    shell('Ankle top housing',[(.105,.036,.040),(.160,.034,.038),(.179,.025,.029)],foot,'secondary',n=8,center=(cx,.012))

mesh=bpy.data.meshes.new('ROBOT_Original_LowPoly_Geometry');mesh.from_pydata(V,[],F);mesh.update()
for material in materials:mesh.materials.append(material)
for p,mat in zip(mesh.polygons,FM):p.material_index=mat;p.use_smooth=False
bm=bmesh.new();bm.from_mesh(mesh);bmesh.ops.recalc_face_normals(bm,faces=bm.faces);bm.to_mesh(mesh);bm.free()
body=link(bpy.data.objects.new('ROBOT_Body',mesh));body['asset_id']='humanoid_robot';body['shading']='authored flat triangles';body['faceless']=True;body['rigid_armor']=True

# Deform rig in an A pose; all weights are explicit and reproducible.
adata=bpy.data.armatures.new('ROBOT_DeformSkeleton');rig=link(bpy.data.objects.new('ROBOT_Rig',adata))
rig.show_in_front=True;adata.display_type='OCTAHEDRAL'
bpy.context.view_layer.objects.active=rig;rig.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
bones={}
def bone(name,head,tail,parent=None):
    b=adata.edit_bones.new(name);b.head=head;b.tail=tail
    if parent:b.parent=bones[parent]
    b.align_roll(Vector((0,-1,0)));bones[name]=b;return b
bone('root',(0,0,0),(0,0,.16))
bone('hips',(0,0,.965),(0,0,1.09),'root')
bone('spine',(0,0,1.09),(0,0,1.285),'hips')
bone('chest',(0,0,1.285),(0,0,1.49),'spine')
bone('neck',(0,0,1.49),(0,.003,1.62),'chest')
bone('head',(0,.003,1.62),(0,.003,1.84),'neck')
for side,s in [('L',1),('R',-1)]:
    bone('upper_arm.'+side,(s*.222,0,1.438),(s*.318,-.012,1.153),'chest')
    bone('forearm.'+side,(s*.318,-.012,1.153),(s*.389,-.033,.945),'upper_arm.'+side)
    bone('hand.'+side,(s*.389,-.033,.945),(s*.413,-.0364,.8324),'forearm.'+side)
    bone('thigh.'+side,(s*.097,0,.94),(s*.097,-.025,.53),'hips')
    bone('shin.'+side,(s*.097,-.025,.53),(s*.097,.01,.165),'thigh.'+side)
    bone('foot.'+side,(s*.097,.01,.165),(s*.097,-.13,.065),'shin.'+side)
    bone('toe.'+side,(s*.097,-.13,.065),(s*.097,-.18,.065),'foot.'+side)
sys.path.insert(0,str(ROOT/'scripts'))
from character_motion import supplement_bones,create_motion,reset_pose
supplement_bones(bone,motion_extra_bones)
bpy.ops.object.mode_set(mode='OBJECT')
for b in adata.bones:
    b.use_deform=b.name!='root'
for name in bones:
    g=body.vertex_groups.new(name=name)
    for i,w in enumerate(W):
        if w.get(name,0)>1e-8:g.add([i],w[name],'REPLACE')
mod=body.modifiers.new('ROBOT_Skeletal_Deformation','ARMATURE');mod.object=rig
body.parent=rig
clips,grip_manifest=create_motion(rig,body,col,link,'robot',motion_extra_bones)
def reset():reset_pose(rig)

# Export a standalone GLB at the origin. Every hard-surface part uses one bone.
rig.animation_data.action=None;reset();sc.frame_set(1)
for track in rig.animation_data.nla_tracks:track.mute=False
bpy.ops.object.select_all(action='DESELECT')
for ob in col.objects:ob.select_set(True)
bpy.context.view_layer.objects.active=rig;export_meshes=[o for o in col.objects if o.type=='MESH']
for o in export_meshes:o.parent=None
bpy.ops.export_scene.gltf(filepath=str(OUT/'modules/humanoid_robot.glb'),export_format='GLB',use_selection=True,export_yup=True,export_extras=True,export_animations=True,export_animation_mode='NLA_TRACKS',export_nla_strips=True,export_force_sampling=True,export_frame_range=False,export_skins=True,export_def_bones=False,export_cameras=False,export_lights=False)
for o in export_meshes:o.parent=rig
for track in rig.animation_data.nla_tracks:track.mute=True
rig.animation_data.action=bpy.data.actions['Robot_Idle'];sc.frame_set(1);rig.location=(3.0,1.30,0)
rig['asset_type']='humanoid_robot';rig['asset_file']='modules/humanoid_robot.glb';rig['animation_role']='robot'
lo=[min(v[i] for v in V) for i in range(3)];hi=[max(v[i] for v in V) for i in range(3)]
manifest={'id':'humanoid_robot','version':'0.2.2','file':'modules/humanoid_robot.glb','units':'meters','height_rest_m':hi[2],
 'forward':'Blender -Y / glTF +Z','origin':'floor / midpoint between feet','triangles':len(mesh.polygons),'authored_vertices':len(V),'materials':len(materials),'bones':len(adata.bones),
 'faceless':True,'flat_shaded':True,'design':'human proportions; original industrial humanoid; rigid segmented armor and visible joints',
 'human_reference':'warehouse_worker: same 20 core bone lengths and joint locations','box_handling':grip_manifest,'clips':clips,'attachments':['ATTACH_ROBOT_HAND_L','ATTACH_ROBOT_HAND_R'],
 'scene_position_blender_m':list(rig.location),'scene_position_gltf_m':[3,0,-1.30],
 'bounds_blender_rest_m':{'min':lo,'max':hi,'size':[hi[i]-lo[i] for i in range(3)]},
 'simulation_status':'display/animation asset; task scheduling and object grasp not connected','parts':parts}
(OUT/'robot_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2));(ROOT/'config/characters/humanoid_robot.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
asset_path=OUT/'asset_manifest.json';assets=json.loads(asset_path.read_text());assets=[a for a in assets if a['id']!='humanoid_robot']
assets.append({'id':'humanoid_robot','file':'modules/humanoid_robot.glb','bounds_min_m':lo,'bounds_max_m':hi,'actual_envelope_m':[hi[i]-lo[i] for i in range(3)],'origin':'floor-center / Blender Z-up','rigged':True,'bones':len(adata.bones),'clips':[c['name'] for c in clips]});asset_path.write_text(json.dumps(assets,ensure_ascii=False,indent=2))
report_path=OUT/'geometry_report.json';report=json.loads(report_path.read_text());report['robots']=1;report['robot_report']='robot_geometry_report.json';report['robot_triangles']=len(mesh.polygons);report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
bad_faces=[p.index for p in mesh.polygons if p.area<1e-12];bad_weights=[i for i,w in enumerate(W) if len(w)!=1 or abs(sum(w.values())-1)>1e-6];invalid=[i for i,v in enumerate(V) if not all(math.isfinite(c) for c in v)]
assert not bad_faces,bad_faces;assert not bad_weights,bad_weights;assert not invalid,invalid
bm=bmesh.new();bm.from_mesh(mesh);boundary=sum(e.is_boundary for e in bm.edges);nonmanifold=sum(not e.is_manifold for e in bm.edges);bm.free()
assert boundary==0 and nonmanifold==0,(boundary,nonmanifold)
qa={'passed':True,'triangles':len(mesh.polygons),'vertices':len(V),'bones':len(adata.bones),'rigid_skinning':True,'zero_area_triangles':bad_faces,'bad_skin_weights':bad_weights,'invalid_vertices':invalid,'boundary_edges':boundary,'nonmanifold_edges':nonmanifold,'parts':len(parts),'human_height_ratio':hi[2]/1.858}
(OUT/'robot_geometry_report.json').write_text(json.dumps(qa,indent=2));bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath);print('ROBOT_SAVED',json.dumps(qa),flush=True)

if opt.render or opt.quick:
    saved_camera=sc.camera;saved_world=sc.world;saved_frame=sc.frame_current;saved_location=rig.location.copy();rig.location=(0,0,0)
    hidden={o:o.hide_render for o in sc.objects if o.name not in col.objects}
    for ob in hidden:ob.hide_render=True
    stage=bpy.data.collections.new('ROBOT_PORTRAIT_STAGE');sc.collection.children.link(stage)
    def stage_link(ob):stage.objects.link(ob);return ob
    mat=bpy.data.materials.new('Robot portrait / sage backdrop');mat.use_nodes=True;p=mat.node_tree.nodes.get('Principled BSDF');p.inputs['Base Color'].default_value=(.105,.145,.14,1);p.inputs['Roughness'].default_value=.94
    plane=bpy.data.meshes.new('Robot portrait floor');plane.from_pydata([(-200,-200,-.001),(200,-200,-.001),(200,200,-.001),(-200,200,-.001)],[],[(0,1,2,3)]);plane.materials.append(mat);stage_link(bpy.data.objects.new('Robot portrait floor',plane))
    world=bpy.data.worlds.new('Robot portrait world');world.use_nodes=True;world.node_tree.nodes['Background'].inputs[0].default_value=(.30,.37,.35,1);world.node_tree.nodes['Background'].inputs[1].default_value=.48;sc.world=world
    def area(name,pos,power,size):
        data=bpy.data.lights.new(name,'AREA');data.energy=power;data.shape='DISK';data.size=size;ob=stage_link(bpy.data.objects.new(name,data));ob.location=pos;ob.rotation_euler=(Vector((0,0,1))-ob.location).to_track_quat('-Z','Y').to_euler()
    area('Robot portrait key',(-3,-4,5),420,4);area('Robot portrait fill',(3,-2,3),160,3);area('Robot portrait rim',(1,3,4),470,3)
    data=bpy.data.cameras.new('Robot portrait camera');cam=stage_link(bpy.data.objects.new('Robot portrait camera',data));data.type='ORTHO';data.ortho_scale=2.32;sc.camera=cam
    sc.render.engine='CYCLES';sc.cycles.samples=128;sc.cycles.use_denoising=False;sc.render.resolution_x=1000;sc.render.resolution_y=1200;sc.render.resolution_percentage=100
    sc.view_settings.view_transform='AgX';sc.view_settings.look='AgX - Medium High Contrast'
    def render(name,pos,target=(0,0,.94),action='Robot_Idle',frame=1):
        rig.animation_data.action=bpy.data.actions[action];sc.frame_set(frame);cam.location=pos;cam.rotation_euler=(Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler();sc.render.filepath=str(OUT/name);bpy.ops.render.render(write_still=True)
    if opt.quick:
        sc.cycles.samples=40;sc.render.resolution_x=650;sc.render.resolution_y=780
        render('robot_check_front.png',(3,-6,2.65));render('robot_check_back.png',(-3,6,2.55))
        data.ortho_scale=1.0;render('robot_check_joints.png',(2,-4,2.0),target=(0,0,1.34),action='Robot_CarryIdle')
    else:
        render('robot_preview.png',(3,-6,2.65));render('robot_front.png',(0,-6,1.6));render('robot_back.png',(-3,6,2.55))
        sc.cycles.samples=96;sc.render.resolution_x=800;sc.render.resolution_y=960
        render('robot_walk.png',(3,-6,2.65),action='Robot_Walk',frame=8);render('robot_carry.png',(3,-6,2.65),action='Robot_CarryIdle');render('robot_reach.png',(3,-6,2.65),action='Robot_Reach',frame=36)
        data.ortho_scale=1.02;render('robot_joints.png',(2,-4,2.25),target=(0,0,1.34),action='Robot_CarryIdle')
        # The exact worker and robot share one stage so their proportions are comparable.
        human=bpy.data.objects.get('WORKER_Rig');human_location=human.location.copy();human.location=(-.48,0,0);rig.location=(.48,0,0)
        human_hidden={o:o.hide_render for o in bpy.data.collections['CHARACTERS / Warehouse worker'].objects}
        for ob in human_hidden:ob.hide_render=False
        human.animation_data.action=bpy.data.actions['Worker_Idle'];rig.animation_data.action=bpy.data.actions['Robot_Idle'];sc.frame_set(1)
        data.ortho_scale=2.38;sc.render.resolution_x=1300;sc.render.resolution_y=1100
        render('worker_robot_comparison.png',(1,-8,2.2),target=(0,0,.94))
        human.location=human_location
        for ob,value in human_hidden.items():ob.hide_render=value
    for ob,value in hidden.items():ob.hide_render=value
    for ob in list(stage.objects):bpy.data.objects.remove(ob,do_unlink=True)
    bpy.data.collections.remove(stage);sc.camera=saved_camera;sc.world=saved_world;rig.location=saved_location;rig.animation_data.action=bpy.data.actions['Robot_Idle'];sc.frame_set(saved_frame)
    sc.render.resolution_x=1680;sc.render.resolution_y=1120;sc.cycles.samples=256;sc.cycles.use_denoising=False;sc.view_settings.look='AgX - Medium Low Contrast';sc.render.filepath=str(OUT/'environment_overview.png');bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    if not opt.quick:bpy.ops.render.render(write_still=True)
print('ROBOT_BUILD_COMPLETE',flush=True)
