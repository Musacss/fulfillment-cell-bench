"""Add visual bindings, empty buffers and reusable markers; no simulation rules."""
import bpy,math,json,sys,argparse
from pathlib import Path
from mathutils import Vector
p=argparse.ArgumentParser();p.add_argument('--output',required=True);opt=p.parse_args(sys.argv[sys.argv.index('--')+1:]);out=Path(opt.output);root=Path(__file__).resolve().parent.parent
for ob in list(bpy.data.objects):
 if ob.get('integration_visual'):bpy.data.objects.remove(ob,do_unlink=True)
for name in ['INTEGRATION / Stations and anchors','INTEGRATION / Visual templates']:
 c=bpy.data.collections.get(name)
 if c:bpy.data.collections.remove(c)
overlay=bpy.data.collections.new('INTEGRATION / Stations and anchors');bpy.context.scene.collection.children.link(overlay)
library=bpy.data.collections.new('INTEGRATION / Visual templates');bpy.context.scene.collection.children.link(library);library.hide_render=True
def srgb_hex(value):
 # Blender shader colors are scene-linear; palette specifications are sRGB.
 value=value.lstrip('#');channels=[int(value[i:i+2],16)/255 for i in (0,2,4)]
 return tuple(c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4 for c in channels)
def material(name,rgb,rough=.48,metal=0):
 m=bpy.data.materials.get('Integration / '+name) or bpy.data.materials.new('Integration / '+name);m.use_nodes=True;m.diffuse_color=(*rgb,1)
 q=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED');q.inputs['Base Color'].default_value=(*rgb,1);q.inputs['Roughness'].default_value=rough;q.inputs['Metallic'].default_value=metal;return m
# Keep material identifiers stable for existing integrations and native recoloring.
steel=material('Petrol steel',srgb_hex('#0e4c92'),.36,.25)
top=material('Sage worktop',srgb_hex('#e7ecef'),.42,.04)
line=material('Slot lines',srgb_hex('#738293'),.52)
amber=material('Ochre warning',srgb_hex('#ffb300'),.40)
dark=material('Graphite symbol',srgb_hex('#2b3137'),.54)
kraft=material('Kraft order',srgb_hex('#bc874f'),.78)
tape=material('Paper tape',srgb_hex('#e2bd87'),.65)
green=material('Good marker',srgb_hex('#2e9f43'),.42)
red=material('Scrap marker',srgb_hex('#d8322f'),.42)
white=material('White lettering',srgb_hex('#ffffff'),.56)
roller_metal=material('Bright roller steel',srgb_hex('#c4cdd5'),.26,.78)
orange=material('Flow rack orange',srgb_hex('#e85d04'),.38,.18)
def empty(name,col,parent=None,position=(0,0,0),**meta):
 ob=bpy.data.objects.new(name,None);col.objects.link(ob);ob.parent=parent;ob.location=position;ob['integration_visual']=True;ob.empty_display_size=.08
 for key,value in meta.items():ob[key]=value
 return ob
def box(name,center,size,mat,col,parent=None):
 x,y,z=center;rx,ry,rz=[v/2 for v in size];verts=[(x+sx*rx,y+sy*ry,z+sz*rz) for sz in [-1,1] for sy in [-1,1] for sx in [-1,1]];faces=[]
 for a,b,c,d in [(0,2,3,1),(4,5,7,6),(0,1,5,4),(2,6,7,3),(0,4,6,2),(1,3,7,5)]:faces.extend([(a,b,c),(a,c,d)])
 mesh=bpy.data.meshes.new(name+'_Mesh');mesh.from_pydata(verts,[],faces);mesh.materials.append(mat);ob=bpy.data.objects.new(name,mesh);col.objects.link(ob);ob.parent=parent;ob['integration_visual']=True;return ob
def roller(name,center,radius,length,mat,col,parent=None,axis='X'):
 # Finite closed cylinder, radius measured to the exact .86 m tangent plane.
 n=24;verts=[];faces=[]
 for end in [-length/2,length/2]:
  for i in range(n):
   a=i*2*math.pi/n;c=radius*math.cos(a);ss=radius*math.sin(a)
   verts.append((end,c,ss) if axis=='X' else (c,end,ss))
 for i in range(n):faces.append((i,(i+1)%n,(i+1)%n+n,i+n))
 faces.extend([tuple(range(n-1,-1,-1)),tuple(range(n,2*n))])
 mesh=bpy.data.meshes.new(name+'_Mesh');mesh.from_pydata(verts,[],faces);mesh.materials.append(mat);mesh.update()
 ob=bpy.data.objects.new(name,mesh);col.objects.link(ob);ob.parent=parent;ob.location=center;ob['integration_visual']=True
 for poly in mesh.polygons:poly.use_smooth=len(poly.vertices)==4
 return ob

def flow_buffer(name,cx,cy,width,depth):
 g=empty('VIS_QUEUE_'+name+'_FRAME',overlay,support_height_m=.86,equipment_type='roller_accumulation_table')
 for y in [cy-depth/2+.025,cy+depth/2-.025]:
  box('VIS_QUEUE_'+name+'_BEAM',(cx,y,.763),(width,.05,.12),orange,overlay,g)
 # End guides sit outside all slot envelopes; the north guide has an infeed opening.
 box('VIS_QUEUE_'+name+'_GUIDE',(cx,cy-depth/2-.0125,.885),(width,.025,.035),steel,overlay,g)
 for side in [-1,1]:
  box('VIS_QUEUE_'+name+'_GUIDE',(cx+side*(width+.64)/4,cy+depth/2+.0125,.885),((width-.64)/2,.025,.035),steel,overlay,g)
 for x in [cx-width/2+.025,cx+width/2-.025]:
  box('VIS_QUEUE_'+name+'_CROSSMEMBER',(x,cy,.765),(.05,depth-.05,.12),steel,overlay,g)
 for x in [cx-width/2-.0125,cx+width/2+.0125]:
  box('VIS_QUEUE_'+name+'_GUIDE',(x,cy,.885),(.025,depth,.035),steel,overlay,g)
 for x in [cx-width/2+.08,cx+width/2-.08]:
  for y in [cy-depth/2+.08,cy+depth/2-.08]:
   box('VIS_QUEUE_'+name+'_LEG',(x,y,.3825),(.06,.06,.735),steel,overlay,g)
   box('VIS_QUEUE_'+name+'_FOOT',(x,y,.0125),(.13,.13,.025),dark,overlay,g)
   box('VIS_QUEUE_'+name+'_FLOOR_ANCHOR',(x+.035,y+.035,.029),(.015,.015,.008),roller_metal,overlay,g)
 count=math.ceil((depth-.08)/.075)+1
 for i in range(count):
  yy=cy-(depth-.08)/2+i*(depth-.08)/(count-1)
  label='VIS_QUEUE_'+name+'_TOP' if i==0 else 'VIS_QUEUE_'+name+'_ROLLER_'+str(i).zfill(2)
  ob=roller(label,(cx,yy,.835),.025,width-.02,roller_metal,overlay,g)
  ob['surface_height_m']=.86
 return g

def transition_infeed(name,cx):
 # Straight tangent-height transfer section ends before the first slot footprint.
 north,south=-.31,-2.03;cy=(north+south)/2;length=north-south;width=.60
 g=empty('VIS_QUEUE_'+name+'_INFEED',overlay,support_height_m=.86,equipment_type='conveyor_buffer_transition')
 for x in [cx-width/2-.025,cx+width/2+.025]:
  box('VIS_QUEUE_'+name+'_INFEED_FRAME',(x,cy,.77),(.04,length,.12),steel,overlay,g)
  box('VIS_QUEUE_'+name+'_INFEED_GUIDE',(x,cy,.895),(.018,length,.045),orange,overlay,g)
 count=22
 for i in range(count):
  yy=south+.035+i*(length-.07)/(count-1)
  roller('VIS_QUEUE_'+name+'_INFEED_ROLLER_'+str(i).zfill(2),(cx,yy,.835),.025,width,roller_metal,overlay,g)
 # Flush transfer tongue closes the short gap to the first buffer roller.
 box('VIS_QUEUE_'+name+'_TRANSFER_TONGUE',(cx,-2.0575,.851),(.60,.055,.018),roller_metal,overlay,g)
 for x in [cx-.20,cx+.20]:
  box('VIS_QUEUE_'+name+'_INFEED_LEG',(x,cy,.39),(.045,.045,.755),steel,overlay,g)
 return g

def beam(name,a,b,width,mat,col,parent=None):
 a,b=Vector(a),Vector(b);ob=box(name,(0,0,0),(width,width,(b-a).length),mat,col,parent);ob.location=(a+b)/2;ob.rotation_euler=(b-a).to_track_quat('Z','Y').to_euler();return ob
def label(name,text,position,size,col,parent=None,rot=(0,0,0),mat=None):
 data=bpy.data.curves.new(name,'FONT');data.body=text;data.size=size;data.align_x='CENTER';data.extrude=.0005;data.materials.append(mat or line)
 ob=bpy.data.objects.new(name,data);col.objects.link(ob);ob.parent=parent;ob.location=position;ob.rotation_euler=rot;ob['integration_visual']=True
 bpy.ops.object.select_all(action='DESELECT');ob.select_set(True);bpy.context.view_layer.objects.active=ob;bpy.ops.object.convert(target='MESH');return ob
def prototype(name,**meta):return empty('VIS_'+name,library,template_id=name,**meta)
bench=prototype('manual_bench',label='Рабочая поверхность 0,86 м',dimensions=[1.1,1.04,.86])
# Extended front supports the entire .40 m tray at the fixed ORDER anchor.
box('VIS_Bench_top',(0,-.05,.8425),(1.1,1.04,.035),top,library,bench)
for x in [-.46,.46]:
 for y in [-.36,.36]:box('VIS_Bench_leg',(x,y,.415),(.045,.045,.83),steel,library,bench)
box('VIS_Bench_rail',(0,.32,.35),(.96,.035,.035),steel,library,bench)
order_sizes={'regular':[.36,.28,.25],'fragile':[.36,.28,.25],'oversize':[.48,.34,.32]}
for kind,(w,d,h) in order_sizes.items():
 g=prototype('order_'+kind,origin='bottom-center',order_kind=kind,label={'regular':'Обычный','fragile':'Хрупкий','oversize':'Крупный'}[kind],size_m=[w,d,h])
 box('VIS_Order_'+kind,(0,0,h/2),(w,d,h),kraft,library,g);box('VIS_Order_tape',(0,0,h+.0005),(.045,d+.001,.001),tape,library,g)
 if kind=='fragile':
  yy=-d/2-.0018;points=[(-.027,yy,h*.76),(-.020,yy,h*.58),(0,yy,h*.51),(.020,yy,h*.58),(.027,yy,h*.76)]
  for a,b in zip(points,points[1:]):beam('VIS_Fragile_glass',a,b,.005,amber,library,g)
  beam('VIS_Fragile_stem',(0,yy,h*.51),(0,yy,h*.32),.005,amber,library,g);beam('VIS_Fragile_foot',(-.022,yy,h*.32),(.022,yy,h*.32),.005,amber,library,g)
 elif kind=='oversize':
  yy=-d/2-.0018
  for x in [-.04,.04]:
   beam('VIS_Large_arrow',(x,yy,h*.28),(x,yy,h*.72),.005,amber,library,g)
   for sign in [-1,1]:beam('VIS_Large_arrow_head',(x+sign*.016,yy,h*.61),(x,yy,h*.72),.005,amber,library,g)
slot=prototype('empty_slot',origin='bottom-center',label='Свободное визуальное место')
for x in [-.27,.27]:box('VIS_Slot_edge',(x,0,.002),(.008,.40,.004),line,library,slot)
for y in [-.20,.20]:box('VIS_Slot_edge',(0,y,.002),(.54,.008,.004),line,library,slot)
reserved=prototype('reserved_slot',origin='bottom-center',label='Резерв; не коробка заказа')
# Preserve the .335 m frame envelope and put its bottom exactly at the root.
for z in [.003,.332]:
 for x in [-.255,.255]:box('VIS_Reserve_edge',(x,0,z),(.006,.37,.006),amber,library,reserved)
 for y in [-.185,.185]:box('VIS_Reserve_edge',(0,y,z),(.51,.006,.006),amber,library,reserved)
for x in [-.255,.255]:
 for y in [-.185,.185]:box('VIS_Reserve_post',(x,y,.1675),(.006,.006,.329),amber,library,reserved)
tray=prototype('order_tray',origin='bottom-center',label='Стандартизованный лоток')
box('VIS_Tray_base',(0,0,.006),(.54,.40,.012),steel,library,tray)
for x in [-.265,.265]:box('VIS_Tray_rim',(x,0,.024),(.01,.40,.036),top,library,tray)
for y in [-.195,.195]:box('VIS_Tray_rim',(0,y,.024),(.54,.01,.036),top,library,tray)
jam=prototype('status_jammed',label='Застрял — нужен работник')
mesh=bpy.data.meshes.new('VIS_Warning_triangle_Mesh');mesh.from_pydata([(-.10,0,-.075),(.10,0,-.075),(0,0,.105)],[],[(0,1,2)]);mesh.materials.append(amber)
ob=bpy.data.objects.new('VIS_Warning_triangle',mesh);library.objects.link(ob);ob.parent=jam;ob['integration_visual']=True
box('VIS_Warning_bar',(0,-.006,.025),(.012,.008,.070),dark,library,jam);box('VIS_Warning_dot',(0,-.006,-.035),(.014,.008,.014),dark,library,jam)
service=prototype('status_service',label='Устранение застревания')
beam('VIS_Wrench_handle',(-.065,0,-.065),(.035,0,.045),.026,amber,library,service)
for x in [-.025,.025]:beam('VIS_Wrench_jaw',(.035,0,.045),(.035+x,0,.09),.018,amber,library,service)
pause=prototype('status_break',label='Перерыв')
for x in [-.025,.025]:box('VIS_Pause_bar',(x,0,0),(.022,.012,.12),amber,library,pause)
offline=prototype('status_offline',label='Куплен, выключен маршрутом')
beam('VIS_Off_slash',(-.06,0,-.06),(.06,0,.06),.024,line,library,offline)
for status,mat in [('good',green),('escaped',amber),('scrap',red)]:
 g=prototype('outcome_'+status,label={'good':'Годен','escaped':'Выдан брак; аналитический исход','scrap':'Окончательный брак'}[status])
 if status=='good':
  beam('VIS_Good_tick',(-.07,0,0),(-.015,0,-.045),.022,mat,library,g);beam('VIS_Good_tick',(-.015,0,-.045),(.075,0,.065),.022,mat,library,g)
 elif status=='scrap':
  for sign in [-1,1]:beam('VIS_Scrap_cross',(-.06,0,-sign*.06),(.06,0,sign*.06),.022,mat,library,g)
 else:
  beam('VIS_Issued_arrow',(-.07,0,0),(.07,0,0),.022,mat,library,g)
  for sign in [-1,1]:beam('VIS_Issued_arrow_head',(.035,0,sign*.035),(.07,0,0),.018,mat,library,g)
def instance(proto,name,position):
 group=empty(name,overlay,position=position)
 for child in proto.children:
  ob=child.copy();overlay.objects.link(ob);ob.parent=group;ob['integration_visual']=True
 return group
def gltf(p):return [p[0],p[2],-p[1]]
stages={1:(-11,1.65,0),2:(-5.4,2.7,0),3:(1.8,2.7,0),4:(6.0,2.7,0)}
stations=[]
for stage,position in stages.items():
 if stage in [1,4]:instance(bench,'VIS_STAGE_'+str(stage)+'_TABLE',position)
 actor=(position[0],position[1]-.65,0);work=(position[0],position[1]-.31,.86)
 a=empty('VIS_STAGE_'+str(stage)+'_WORK',overlay,position=actor,logical_stage=stage,role='manual_work_position')
 empty('VIS_STAGE_'+str(stage)+'_ORDER',overlay,position=work,logical_stage=stage,role='assigned_order_position')
 stations.append({'stage':stage,'actor_anchor':a.name,'actor_position_gltf_m':gltf(actor),'yaw_gltf_rad':math.pi,'order_anchor':'VIS_STAGE_'+str(stage)+'_ORDER','table_height_m':.86,'parallel_slot_spacing_m':[1.6,1.8],'parallel_slot_columns':2})
robot_table=(3.5,2.7,0);instance(bench,'VIS_ROBOT_PACK_TABLE',robot_table);robot_actor=(3.5,2.05,0)
empty('VIS_ROBOT_WORK',overlay,position=robot_actor,logical_stage=3,role='robot_work_position')
empty('VIS_ROBOT_ORDER',overlay,position=(3.5,2.39,.86),logical_stage=3,role='robot_owned_order')
empty('VIS_ROBOT_ASSIST',overlay,position=(2.8,1.95,0),logical_stage=3,role='helper_position')
queues={
 'Q1':{'origin':[-11,3.1,.15],'columns':3,'spacing':[.56,.42],'preview_count':6,'bounded':False},
 'Q2':{'origin':[-7.3,-2.3,.86],'columns':4,'spacing':[.56,-.42],'preview_count':12,'bounded':True},
 'Q3':{'origin':[-.7,-2.3,.86],'columns':5,'spacing':[.56,-.42],'preview_count':10,'bounded':True},
 'Q4':{'origin':[5.6,-2.3,.86],'columns':4,'spacing':[.56,-.42],'preview_count':8,'bounded':True},
 'R':{'origin':[3.8,-7.45,.86],'columns':3,'spacing':[.56,.42],'preview_count':6,'bounded':False}}
for name,q in queues.items():
 origin=q['origin'];empty('VIS_QUEUE_'+name,overlay,position=origin,queue=name,role='queue_origin')
 if q['bounded']:
  cols=q['columns'];rows=math.ceil(q['preview_count']/cols);width=cols*.56+.04;depth=rows*.42+.04;cx=origin[0]+(cols-1)*.56/2;cy=origin[1]-(rows-1)*.42/2
  flow_buffer(name,cx,cy,width,depth)
  transition_infeed(name,cx)
  # Front fascia signage leaves the complete .86 m order surface unobstructed.
  front=cy-depth/2
  box('VIS_QUEUE_'+name+'_LABEL_PLATE',(cx,front-.012,.72),(.70,.024,.20),steel,overlay)
  label('VIS_QUEUE_'+name+'_LABEL',name+' ['+str(q['preview_count'])+']',(cx,front-.025,.675),.11,overlay,rot=(math.pi/2,0,0),mat=white)
 for i in range(q['preview_count']):
  position=(origin[0]+i%q['columns']*q['spacing'][0],origin[1]+i//q['columns']*q['spacing'][1],origin[2])
  a=empty('VIS_QUEUE_'+name+'_SLOT_'+str(i).zfill(2),overlay,position=position,queue=name,preview_slot=i)
  if q['bounded']:instance(slot,'VIS_QUEUE_'+name+'_OUTLINE_'+str(i),position)
 q['origin_gltf_m']=gltf(origin);q['anchor']='VIS_QUEUE_'+name;q['capacity_source']='passed explicitly from World by the replay adapter; preview_count is not a limit'
outcomes={'good':[10.0,2.2,.15],'escaped':[10.0,4.4,.15],'scrap':[7.2,-7.0,.02]}
for state,pos in outcomes.items():empty('VIS_OUTCOME_'+state.upper(),overlay,position=pos,role='terminal_outcome',outcome=state)
mapping={'format':'four-horses.visual-bindings.v1','source_contract':'User integration document: Robotization Bench v1, claimed commit 1af71b6; private core not available for verification','units':'meters','axes':'glTF Y-up; character forward +Z','simulation_rules_in_this_file':False,'assets':{'environment':'warehouse_environment.glb','layout':'modules/visual_layout.glb','templates':'modules/visual_support.glb','worker':'modules/warehouse_worker.glb','robot':'modules/humanoid_robot.glb'},'stages':stations,'robot':{'stage':3,'actor_anchor':'VIS_ROBOT_WORK','position_gltf_m':gltf(robot_actor),'yaw_gltf_rad':math.pi,'order_anchor':'VIS_ROBOT_ORDER','helper_anchor':'VIS_ROBOT_ASSIST'},'queues':queues,'outcomes':{k:{'anchor':'VIS_OUTCOME_'+k.upper(),'position_gltf_m':gltf(v)} for k,v in outcomes.items()},'order_visual_sizes_m':order_sizes,'worker_states':{'idle':'Idle','walk':'Walk','prepare':'Prepare','pick':'Pick','pack':'Pack','inspect':'Inspect','assist':'Assist','break':'Break'},'robot_states':{'not_purchased':None,'disabled':'Offline','idle':'Idle','pack':'RobotPack','jammed':'Jammed','helper_walking':'Jammed','service':'Service','finished':'Idle'},'production_hide_embedded_props':True,'oversize_clip_suffix':'_Oversize','travel_clip':'Walk','travel_has_order':False,'order_ownership_source':'replay state only; assisting worker does not own the robot order','templates':[ob.name for ob in library.objects if ob.type=='EMPTY']}
(out/'visual_bindings.json').write_text(json.dumps(mapping,ensure_ascii=False,indent=2));(root/'config/visual_bindings.json').write_text(json.dumps(mapping,ensure_ascii=False,indent=2))
for col,file in [(library,'visual_support'),(overlay,'visual_layout')]:
 bpy.ops.object.select_all(action='DESELECT')
 for ob in col.objects:ob.select_set(True)
 bpy.ops.export_scene.gltf(filepath=str(out/'modules'/str(file+'.glb')),export_format='GLB',use_selection=True,export_yup=True,export_extras=True,export_animations=False,export_cameras=False,export_lights=False)
bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
print('VISUAL_SUPPORT_COMPLETE',json.dumps({'templates':len(mapping['templates']),'stages':4,'queues':5,'preview_slots':sum(q['preview_count'] for q in queues.values()),'native_objects':len(overlay.objects)}),flush=True)
