"""Original dimensioned warehouse kit. Blender 4.3+, no external assets.
Run: blender -b --factory-startup --python scripts/build_environment.py -- --output PATH
"""
import bpy, bmesh, math, json, sys, os, argparse, collections
from pathlib import Path
from mathutils import Vector

args = argparse.ArgumentParser()
args.add_argument('--output', required=True)
args.add_argument('--render', action='store_true')
args.add_argument('--details', action='store_true')
opt = args.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
ROOT = Path(__file__).resolve().parent.parent
OUT = Path(opt.output); OUT.mkdir(parents=True, exist_ok=True)
(OUT/'modules').mkdir(exist_ok=True)
# Editable native dimensions; config/environment.json describes frozen GLB buffers.
CFG = json.loads((ROOT/'environment_config.json').read_text())
bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
bpy.context.preferences.edit.use_global_undo=False
bpy.context.preferences.filepaths.save_version=0
for block in list(bpy.data.materials): bpy.data.materials.remove(block)
sc = bpy.context.scene
sc.unit_settings.system='METRIC'; sc.unit_settings.scale_length=1
sc.render.fps=30; sc.frame_start=1; sc.frame_end=CFG['demo']['cycle_seconds']*30
cache={}; assets={}; roots=[]

def mat(name, rgb, metal=0, rough=.5, emission=0):
    m=bpy.data.materials.new(name); m.use_nodes=True
    p=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
    p.inputs['Base Color'].default_value=(*rgb,1)
    p.inputs['Metallic'].default_value=metal
    p.inputs['Roughness'].default_value=rough
    if emission:
        p.inputs['Emission Color'].default_value=(*rgb,1)
        p.inputs['Emission Strength'].default_value=emission
    m.diffuse_color=(*rgb,1)
    return m

def srgb(h):
    values=[int(h[i:i+2],16)/255 for i in (0,2,4)]
    return tuple(v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in values)

M={
 'floor':mat('Warm mineral concrete',srgb('d5dbe0'),0.04,0.42),
 'edge':mat('Plinth edge',srgb('9ca9b5'),0.12,0.44),
 'wall':mat('Porcelain wall panels',srgb('e9edf0'),0,0.63),
 'steel':mat('Satin zinc steel',srgb('798995'),0.55,0.32),
 'silver':mat('Bright aluminium',srgb('c7d1da'),0.78,0.26),
 'teal':mat('Petrol powder coat',srgb('0e4c92'),0.15,0.38),
 'dark':mat('Graphite rubber and guards',srgb('2b3137'),0.25,0.36),
 'yellow':mat('Safety ochre',srgb('f4b400'),0.08,0.38),
 'white':mat('Warm white laminate',srgb('e7ecef'),0.03,0.43),
 'kraft':mat('Kraft cardboard',srgb('ba884d'),0,0.8),
 'kraftLight':mat('Cardboard cut edge',srgb('d3a76f'),0,0.78),
 'tape':mat('Paper tape',srgb('d1b489'),0,0.64),
 'paper':mat('Packing paper',srgb('ddc493'),0,0.75),
 'wood':mat('Pallet timber',srgb('c5a16e'),0,0.73),
 'label':mat('Paper labels',srgb('f4f6f7'),0,0.6),
 'red':mat('Emergency stop',srgb('d32f2f'),0,0.4),
 'green':mat('Status green',srgb('36b559'),0.05,0.32),
 'amber':mat('Status amber',srgb('ffb300'),0.05,0.33),
 'blue':mat('Status blue',srgb('2187c9'),0.05,0.32),
 'black':mat('Printed charcoal',srgb('242b32'),0,0.57),
 'orange':mat('FlexSim / Rack orange',srgb('e85d04'),0.12,0.36),
}

def group(name, pos=(0,0,0), parent=None, typ=None, dynamic=False):
    o=bpy.data.objects.new(name,None); sc.collection.objects.link(o)
    o.empty_display_type='PLAIN_AXES'; o.empty_display_size=.12
    o.parent=parent; o.location=pos
    if typ:o['asset_type']=typ
    if dynamic:o['dynamic']=True
    if parent is None: roots.append(o)
    return o

def mesh_obj(name, mesh, loc, parent, rot=(0,0,0), dynamic=False):
    o=bpy.data.objects.new(name,mesh); sc.collection.objects.link(o)
    o.parent=parent; o.location=loc; o.rotation_euler=rot
    if dynamic:o['dynamic']=True
    return o

def box(name,dims,loc,material,parent=None,bevel=.003,rot=(0,0,0),dynamic=False):
    dims=tuple(round(float(d),6) for d in dims)
    b=min(bevel,min(dims)*.19)
    key=('b',dims,material.name,round(b,6))
    if key not in cache:
        x,y,z=[v*.5 for v in dims]
        verts=[(-x,-y,-z),(-x,-y,z),(-x,y,-z),(-x,y,z),(x,-y,-z),(x,-y,z),(x,y,-z),(x,y,z)]
        faces=[tuple(reversed(f)) for f in [(0,4,6,2),(1,3,7,5),(0,1,5,4),(2,6,7,3),(0,2,3,1),(4,5,7,6)]]
        me=bpy.data.meshes.new(name+'_geometry'); me.from_pydata(verts,[],faces); me.update()
        me.materials.append(material)
        if b>0:
            tmp=mesh_obj('_bevel_temp',me,(0,0,0),None)
            for p in me.polygons:p.use_smooth=True
            mod=tmp.modifiers.new('Manufactured edge radius','BEVEL'); mod.width=b; mod.segments=3
            mod.harden_normals=True
            norm=tmp.modifiers.new('Weighted planar normals','WEIGHTED_NORMAL'); norm.keep_sharp=True; norm.weight=50
            dg=bpy.context.evaluated_depsgraph_get()
            cooked=bpy.data.meshes.new_from_object(tmp.evaluated_get(dg),preserve_all_data_layers=True,depsgraph=dg)
            bpy.data.objects.remove(tmp,do_unlink=True)
            cache[key]=cooked
        else:cache[key]=me
    return mesh_obj(name,cache[key],loc,parent,rot,dynamic)

def cyl(name,r,depth,loc,material,parent=None,rot=(0,0,0),n=40,dynamic=False):
    key=('c',round(r,6),round(depth,6),n,material.name)
    if key not in cache:
        verts=[(r*math.cos(i*2*math.pi/n),r*math.sin(i*2*math.pi/n),z) for z in [-depth/2,depth/2] for i in range(n)]
        faces=[(i,(i+1)%n,(i+1)%n+n,i+n) for i in range(n)]
        faces += [tuple(range(n-1,-1,-1)),tuple(range(n,2*n))]
        me=bpy.data.meshes.new(name+'_geometry'); me.from_pydata(verts,[],faces); me.update(); me.materials.append(material)
        for p in me.polygons:p.use_smooth=len(p.vertices)==4 and n>8
        cache[key]=me
    return mesh_obj(name,cache[key],loc,parent,rot,dynamic)

def beam(name,a,b,thick,material,parent=None):
    a,b=Vector(a),Vector(b); d=b-a
    o=box(name,(thick,thick,d.length),(a+b)/2,material,parent,bevel=min(.002,thick/6))
    o.rotation_euler=d.to_track_quat('Z','Y').to_euler(); return o

def text(name,body,size,loc,material,parent=None,rot=(0,0,0),align='LEFT'):
    curve=bpy.data.curves.new(name+'_font','FONT');curve.body=body;curve.size=size;curve.align_x=align
    curve.extrude=.00015;curve.resolution_u=4
    o=bpy.data.objects.new(name,curve);sc.collection.objects.link(o);o.parent=parent;o.location=loc;o.rotation_euler=rot
    curve.materials.append(material)
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active=o;o.select_set(True)
    bpy.ops.object.convert(target='MESH');o.select_set(False)
    # Font tessellation can produce zero-area caps at coincident curve points.
    # Remove those faces at the source rather than shipping invalid triangles.
    bm=bmesh.new();bm.from_mesh(o.data)
    bmesh.ops.dissolve_degenerate(bm,dist=1e-8,edges=list(bm.edges))
    bmesh.ops.triangulate(bm,faces=list(bm.faces))
    bad=[f for f in bm.faces if f.calc_area()<1e-10]
    if bad:bmesh.ops.delete(bm,geom=bad,context='FACES_ONLY')
    loose=[v for v in bm.verts if not v.link_faces]
    if loose:bmesh.ops.delete(bm,geom=loose,context='VERTS')
    bm.to_mesh(o.data);bm.free();o.data.update()
    # Blender's single-precision polygon-area cache can round a near-collinear
    # font triangle to zero even after BMesh's higher-precision check.
    bad_ids=[p.index for p in o.data.polygons if p.area<1e-12]
    if bad_ids:
        bm=bmesh.new();bm.from_mesh(o.data);bm.faces.ensure_lookup_table()
        bmesh.ops.delete(bm,geom=[bm.faces[i] for i in bad_ids],context='FACES_ONLY')
        bm.to_mesh(o.data);bm.free();o.data.update()
    o['geometry_role']='surface_lettering'
    return o

def anchor(name,pos,parent=None,**meta):
    o=group(name,pos,parent)
    o['kind']='anchor'
    for k,v in meta.items():o[k]=v
    return o

def floor_arrow(name,x,y,parent):
    # A single contiguous paint polygon: shaft and head share their vertices.
    outline=[(-.48,-.06),(.08,-.06),(.08,-.24),(.48,0),(.08,.24),(.08,.06),(-.48,.06)]
    mesh=bpy.data.meshes.new(name+'_geometry')
    mesh.from_pydata([(px,py,0) for px,py in outline],[],[tuple(range(len(outline)))])
    mesh.materials.append(M['white']);mesh.update()
    bm=bmesh.new();bm.from_mesh(mesh)
    bmesh.ops.triangulate(bm,faces=list(bm.faces));bm.to_mesh(mesh);bm.free();mesh.update()
    o=mesh_obj(name,mesh,(x,y,.0041),parent)
    o['geometry_role']='floor_arrow';o['direction']='+X'
    return o

def center_lettering_xy(o):
    points=[v.co for v in o.data.vertices]
    cx=(min(v.x for v in points)+max(v.x for v in points))/2
    cy=(min(v.y for v in points)+max(v.y for v in points))/2
    for v in o.data.vertices:v.co.x-=cx;v.co.y-=cy
    o.data.update()

def foot(name,x,y,parent):
    cyl(name+'_pad',.055,.018,(x,y,.009),M['dark'],parent,n=32)
    cyl(name+'_thread',.012,.052,(x,y,.044),M['steel'],parent,n=16)

def bolt(name,pos,parent,rot=(0,0,0)):
    return cyl(name,.006,.006,pos,M['silver'],parent,rot,n=6)

def boundary(name,x,y,w,d,parent,colour=None):
    col=colour or M['yellow'];z=.0035;t=.04
    for i,(xx,yy,ww,dd) in enumerate([(x,y-d/2,w,t),(x,y+d/2,w,t),(x-w/2,y,t,d),(x+w/2,y,t,d)]):
        box(name+str(i),(ww,dd,.002),(xx,yy,z),col,parent,bevel=.0005)

def pallet(name,pos,parent=None):
    g=group(name,pos,parent,typ='pallet_1200x800');g['dimensions']=[1.2,.8,.15]
    g['origin']='bottom-center';g['support_height_m']=.15
    # Simulation deck: 22 mm runners + 78 mm blocks + 22 mm stringers + 28 mm deck.
    # The requested 150 mm load surface matches VIS_QUEUE_Q1 and both dispatch outcomes.
    for y in [-.3275,0,.3275]:box('Pallet runner',(1.2,.145,.022),(0,y,.011),M['wood'],g,.004)
    for x in [-.5275,0,.5275]:
        for y in [-.3275,0,.3275]:box('Pallet block',(.145,.145,.078),(x,y,.061),M['wood'],g,.004)
        box('Cross stringer',(.145,.8,.022),(x,0,.111),M['wood'],g,.002)
    for y,w in [(-.3275,.145),(-.16375,.1),(0,.145),(.16375,.1),(.3275,.145)]:
        box('Deck plank',(1.2,w,.028),(0,y,.136),M['wood'],g,.003)
    assets.setdefault('pallet_1200x800',g);return g

def carton(name,pos,parent=None,open_top=False,dynamic=False):
    g=group(name,pos,parent,typ='carton_open' if open_top else 'carton_closed',dynamic=dynamic)
    g['dimensions']=[.4,.3,.25];g['origin']='bottom-center'
    if open_top:
        box('Carton bottom',(.4,.3,.004),(0,0,.002),M['kraft'],g,.0006)
        for y in [-.148,.148]:box('Carton side',(.4,.004,.246),(0,y,.127),M['kraft'],g,.0006)
        for x in [-.198,.198]:box('Carton end',(.004,.292,.246),(x,0,.127),M['kraft'],g,.0006)
        for label,x,y,w,d,angle,axis in [('N',0,.15,.4,.15,-.3,'X'),('S',0,-.15,.4,.15,.3,'X'),('E',.2,0,.2,.292,.35,'Y'),('W',-.2,0,.2,.292,-.35,'Y')]:
            p=group('CARTON_FLAP_'+label,(x,y,.25),g,dynamic=True)
            off=(0,d/2,0) if label=='N' else ((0,-d/2,0) if label=='S' else ((w/2,0,0) if label=='E' else (-w/2,0,0)))
            box('Flap paper',(w,d,.004),off,M['kraftLight'],p,.0005)
            p.rotation_euler[0 if axis=='X' else 1]=angle
    else:
        box('Sealed carton',(.4,.3,.25),(0,0,.125),M['kraft'],g,.002)
        box('Top paper tape',(.056,.3006,.001),(0,0,.2507),M['tape'],g,.0002)
        for y in [-.1506,.1506]:box('Tape end',(.056,.001,.08),(0,y,.21),M['tape'],g,.0001)
        box('Shipping label',(.13,.088,.0008),(.106,.055,.2511),M['label'],g,.0002)
        for i in range(18):
            w=.001+(i%3)*.0005
            box('Barcode',(w,.040,.0003),(.056+i*.0055,.056,.2517),M['black'],g,0)
        text('Parcel print','4H / 024',.012,(.052,.027,.2519),M['black'],g)
    assets.setdefault('carton_open' if open_top else 'carton_closed',g);return g

def tote(name,pos,parent=None):
    g=group(name,pos,parent,typ='tote_600x400');g['dimensions']=[.6,.4,.22]
    box('Tote bottom',(.586,.386,.009),(0,0,.0045),M['teal'],g,.004)
    for y in [-.1885,.1885]:
        box('Tote side',(.586,.006,.211),(0,y,.1145),M['teal'],g,.0015)
        box('Top rim long',(.6,.017,.014),(0,math.copysign(.1915,y),.213),M['teal'],g,.003)
        for x in [-.24,-.12,0,.12,.24]:box('Stiffener',(.012,.01,.18),(x,y*1.018,.102),M['teal'],g,.002)
    for x in [-.29,.29]:
        box('End below handle',(.006,.388,.147),(x,0,.0825),M['teal'],g,.001)
        for y in [-.14,.14]:box('Handle side',(.006,.108,.054),(x,y,.183),M['teal'],g,.001)
        box('Handle bridge',(.014,.4,.013),(math.copysign(.293,x),0,.2135),M['teal'],g,.003)
    box('Tote identity plate',(.13,.001,.055),(0,-.1982,.102),M['label'],g,.0002)
    text('Tote identity','BIN 024',.019,(-.049,-.1989,.087),M['black'],g,(math.pi/2,0,0))
    assets.setdefault('tote_600x400',g);return g

def conveyor(index,x):
    g=group('CONVEYOR_%02d'%index,(x,0,0),typ='roller_conveyor_1800');g['dimensions']=[1.8,.7,.98]
    for y in [-.33,.33]:
        box('Folded side profile',(1.8,.04,.12),(0,y,.785),M['dark'],g,.004)
        box('Guard rail',(1.8,.018,.025),(0,y,.928),M['steel'],g,.002)
        for xx in [-.7,0,.7]:
            box('Guide stanchion',(.025,.023,.15),(xx,y,.864),M['steel'],g,.002)
            bolt('Guide fastener',(xx,y,.944),g)
    for xx in [-.66,.66]:
        box('Cross member',(.055,.60,.045),(xx,0,.71),M['steel'],g,.003)
        for y in [-.25,.25]:
            foot('Level foot',xx,y,g)
            box('Square leg',(.045,.045,.65),(xx,y,.395),M['dark'],g,.003)
            bolt('Frame bolt',(xx,y,.725),g)
        box('Support cross tie',(.035,.54,.035),(xx,0,.24),M['steel'],g,.002)
    for i in range(20):
        xx=-.855+i*.09
        o=cyl('ROLLER_%02d_%02d'%(index,i+1),.025,.62,(xx,0,.835),M['silver'],g,(math.pi/2,0,0),n=32,dynamic=True)
        o['animation_role']='roller';o['radius']=.025;o['line_module']=index
    box('Drive cover',(.24,.105,.15),(.52,.396,.72),M['dark'],g,.014)
    for xx in [.44,.60]:bolt('Cover fastener',(xx,.453,.72),g,(math.pi/2,0,0))
    box('Control module',(.16,.075,.09),(-.50,-.396,.72),M['dark'],g,.008)
    cyl('Power indicator',.008,.003,(-.54,-.435,.735),M['green'],g,(math.pi/2,0,0),n=16)
    for xx in [-.72,.72]:
        box('Hazard insert',(.16,.003,.025),(xx,-.352,.806),M['yellow'],g,.001)
    anchor('ANCHOR_C%02d_IN'%index,(-.9,0,.86),g,role='conveyor_in')
    anchor('ANCHOR_C%02d_OUT'%index,(.9,0,.86),g,role='conveyor_out')
    if index==1:assets['roller_conveyor_1800']=g
    return g

def bench(name,pos,packing=False):
    g=group(name,pos,typ='packing_bench_1800' if packing else 'workbench_1800')
    g['dimensions']=[1.8,.97,2.04 if packing else .86]
    g['surface_height_m']=.86
    for x in [-.79,.79]:
        for y in [-.34,.34]:
            foot('Bench foot',x,y,g)
            box('Leg profile',(.05,.05,.72),(x,y,.43),M['steel'],g,.0025)
        box('Lower crossbar',(.04,.63,.05),(x,0,.22),M['steel'],g,.002)
    for y in [-.34,.34]:box('Apron',(1.53,.035,.09),(0,y,.78),M['steel'],g,.002)
    # The fixed ORDER anchor is .31 m forward of the bench origin. Extend
    # the front lip 70 mm so the .40 m tray has a fully supported footprint.
    box('Laminate worktop',(1.8,.97,.03),(0,-.035,.845),M['white'],g,.006)
    box('Edge band',(1.8,.012,.028),(0,-.519,.845),M['teal'],g,.002)
    box('Underbench shelf',(1.62,.66,.021),(0,0,.251),M['white'],g,.003)
    box('Drawer unit',(.36,.5,.32),(.55,.05,.61),M['teal'],g,.006)
    for z in [.51,.66]:
        box('Drawer face',(.34,.016,.14),(.55,-.208,z),M['wall'],g,.003)
        box('Drawer pull',(.20,.024,.018),(.55,-.228,z+.02),M['dark'],g,.003)
    if packing:
        for x in [-.83,.83]:box('Rear upright',(.035,.035,1.18),(x,.378,1.45),M['steel'],g,.002)
        box('Upper supply shelf',(1.8,.31,.022),(0,.23,1.72),M['white'],g,.003)
        for x in [-.68,-.34,0,.34,.68]:
            beam('Carton divider',(x,.095,1.74),(x,.095,2.00),.012,M['steel'],g)
            beam('Divider return',(x,.095,2.0),(x,.35,2.0),.012,M['steel'],g)
        # Upright flat blanks on the overhead shelf.
        for i in range(8):box('Flat carton blank',(.015,.28,.25),(-.56+i*.055,.24,1.855),M['kraft'],g,.001)
        for x in [-.83,.83]:beam('Light support',(x,.38,1.96),(x,-.15,1.96),.022,M['steel'],g)
        box('Luminaire housing',(1.72,.055,.032),(0,-.15,1.965),M['silver'],g,.004)
        box('Light diffuser',(1.65,.041,.006),(0,-.15,1.947),M['label'],g,.002)
        cyl('Paper spindle',.012,1.62,(0,.29,1.32),M['steel'],g,(0,math.pi/2,0),n=24)
        for x in [-.825,.825]:
            box('Spindle mounting bracket',(.035,.13,.09),(x,.33,1.32),M['steel'],g,.003)
            cyl('Spindle bearing',.027,.025,(math.copysign(.8,x),.29,1.32),M['steel'],g,(0,math.pi/2,0),n=32)
        roll=cyl('PACK_PAPER_ROLL',.12,1.24,(0,.29,1.32),M['paper'],g,(0,math.pi/2,0),n=64,dynamic=True)
        roll['animation_role']='paper_roll'
        for x in [-.625,.625]:cyl('Roll core',.025,.005,(x,.29,1.32),M['kraft'],g,(0,math.pi/2,0),n=32)
        box('Paper tail',(1.2,.004,.27),(0,.169,1.19),M['paper'],g,.001)
        # Keep the reusable open carton asset on the lower shelf, outside live orders.
        # Tape dispenser, cutter and folded padding.
        cyl('Tape reel',.055,.045,(.64,-.14,.925),M['tape'],g,(0,math.pi/2,0),n=48)
        box('Tape dispenser foot',(.18,.11,.028),(.64,-.14,.875),M['dark'],g,.004)
        box('Cutting strip',(1.52,.025,.015),(0,.42,.868),M['steel'],g,.002)
        for z in [.31,.35,.39]:box('Stored carton blanks',(.48,.42,.026),(.15,0,z),M['kraft'],g,.002)
    else:
        tote('PICK_TOTE',(-.44,0,.2615),g)
        carton('Pick stock 0',(.16,0,.2615),g)
    anchor('ANCHOR_'+name+'_WORK',(0,-.08,.86),g,role='work_surface')
    anchor('ANCHOR_'+name+'_APPROACH',(0,-1.1,0),g,role='worker_approach')
    assets.setdefault('packing_bench_1800' if packing else 'workbench_1800',g)
    return g

def rack(name,pos):
    g=group(name,pos,typ='shelving_1800');g['dimensions']=[1.8,.65,2.4]
    for x in [-.876,.876]:
        for y in [-.301,.301]:
            box('Rack upright',(.048,.048,2.4),(x,y,1.2),M['teal'],g,.002)
            box('Foot plate',(.13,.10,.008),(x,y,.004),M['steel'],g,.002)
            for z in [i*.15+.16 for i in range(15)]:box('Upright slot',(.012,.001,.03),(x,y-.0249,z),M['dark'],g,.0005)
        beam('Rack diagonal',(x,-.29,.2),(x,.29,1.25),.014,M['steel'],g)
        beam('Rack diagonal',(x,.29,1.25),(x,-.29,2.3),.014,M['steel'],g)
    for level,z in enumerate(CFG['shelving']['levels']):
        box('Shelf deck',(1.73,.60,.022),(0,0,z),M['white'],g,.002)
        for y in [-.292,.292]:box('Shelf front return',(1.73,.025,.048),(0,y,z-.013),M['orange'],g,.002)
        box('Shelf ID',(.16,.002,.035),(-.67,-.307,z),M['label'],g,.0002)
        text('Shelf identifier',name[-2:]+' / '+str(level+1),.020,(-.735,-.3087,z-.008),M['black'],g,(math.pi/2,0,0))
        for j in range(2 if level%2==0 else 3):
            if level%2==0:
                tote(name+'_BIN_%d_%d'%(level,j),(-.43+j*.86,0,z+.011),g)
            else:
                carton(name+'_STOCK_%d_%d'%(level,j),(-.52+j*.52,.05,z+.011),g)
    assets.setdefault('shelving_1800',g);return g

def trolley(name,pos):
    g=group(name,pos,typ='supply_trolley')
    for x in [-.42,.42]:
        for y in [-.25,.25]:
            cyl('Castor tire',.065,.04,(x,y,.065),M['dark'],g,(math.pi/2,0,0),n=32)
            cyl('Wheel hub',.027,.043,(x,y,.065),M['steel'],g,(math.pi/2,0,0),n=24)
            box('Castor fork',(.08,.06,.045),(x,y,.128),M['steel'],g,.003)
            box('Trolley upright',(.025,.025,.70),(x,y,.52),M['steel'],g,.002)
    for z in [.18,.50,.86]:box('Trolley tray',(.92,.60,.025),(0,0,z),M['teal'],g,.005)
    for y in [-.25,.25]:beam('Handle post',(.42,y,.86),(.42,y,1.04),.022,M['steel'],g)
    beam('Push handle',(.42,-.25,1.04),(.42,.25,1.04),.022,M['dark'],g)
    tote('Trolley tote',(0,0,.8725),g)
    assets['supply_trolley']=g;return g

def build_shell_back_wall(parent,width,depth,height):
    back_y=depth/2-.15
    for i in range(int(width/2)):
        x=-width/2+1+i*2
        box('Back wall panel',(1.98,.13,height),(x,back_y,height/2),M['wall'],parent,.007)
        box('Wall skirting',(1.98,.04,.18),(x,back_y-.09,.09),M['edge'],parent,.003)
    for x in [-width/2+.15]+list(range(-14,15,4))+[width/2-.15]:
        box('Structural column',(.15,.21,height),(x,back_y-.15,height/2),M['steel'],parent,.004)
        box('Column guard',(.23,.26,.55),(x,back_y-.17,.275),M['yellow'],parent,.014)
    box('Back horizontal service rail',(width-.4,.045,.10),(0,back_y-.12,2.78),M['steel'],parent,.004)
    text('Warehouse wordmark','4 HORSES',.48,(2.8,back_y-.079,2.17),M['teal'],parent,(math.pi/2,0,0))
    text('Warehouse descriptor','FULFILMENT / ENVIRONMENT 01',.105,(2.83,back_y-.082,1.91),M['black'],parent,(math.pi/2,0,0))

shell=group('ENV_SHELL',typ='environment_shell')
rw,rd,rh=CFG['room']['width'],CFG['room']['depth'],CFG['room']['wall_height']
back_y=rd/2-.15
box('Raised concrete slab',(rw,rd,.20),(0,0,-.10),M['floor'],shell,.04)
box('Lower reveal',(rw-.08,rd-.08,.055),(0,0,-.185),M['edge'],shell,.025)
for x in range(-12,13,4):box('Concrete control joint',(.006,rd-.15,.001),(x,0,.001),M['edge'],shell,0)
for y in range(-6,7,3):box('Concrete control joint',(rw-.15,.006,.001),(0,y,.001),M['edge'],shell,0)
build_shell_back_wall(shell,rw,rd,rh)
# Physical floor paint, including a clear pedestrian aisle.
lane_front,lane_back=CFG['layout']['walkway_y'];lane_center=(lane_front+lane_back)/2
for y in [lane_front,lane_back]:box('Walkway edge',(rw-.6,.045,.002),(0,y,.003),M['white'],shell,.0005)
for x in [-(rw-.6)/2,(rw-.6)/2]:box('Walkway end',(.045,abs(lane_back-lane_front),.002),(x,lane_center,.003),M['white'],shell,.0005)
walkway_arrows=[floor_arrow('Walkway arrow %02d'%(i+1),x,lane_center,shell) for i,x in enumerate([-(rw-.6)/3,0,(rw-.6)/3])]
for z in CFG['stations']:
    x=z['center'][0]
    text('Floor zone '+z['id'],z['label'],.18,(x-.72,-1.15,.004),M['white'],shell)
lane_label=text('Service lane text','SERVICE / KEEP CLEAR',.14,(0,lane_center,.0041),M['white'],shell,align='CENTER')
center_lettering_xy(lane_label)
ix,iy,_=CFG['layout']['inbound'];dx=CFG['layout']['dispatch_x']
boundary('Inbound paint',ix,iy,2.4,2.2,shell)
boundary('Outbound paint',dx,3.3,2.4,5.0,shell)
text('Inbound legend','INBOUND',.17,(ix-.9,iy-1.3,.004),M['white'],shell)
text('Outbound legend','DISPATCH',.17,(dx-.9,.53,.004),M['white'],shell)

for i,x in enumerate(CFG['conveyor']['centers_x'],1):conveyor(i,x)
pick_x,pick_y=CFG['packing_bench']['positions'][0];pack_x,pack_y=CFG['packing_bench']['positions'][1]
bench('BENCH_PICK',(pick_x,pick_y,0))
bench('BENCH_PACK',(pack_x,pack_y,0),True)
# R has a complete independent roller frame. Retain the legacy reference
# anchors without placing another desk, shelf or tote beneath the accumulator.
rework=group('BENCH_REWORK',CFG['layout']['rework'],typ='rework_station_reference')
anchor('ANCHOR_BENCH_REWORK_WORK',(0,-.08,.86),rework,role='work_surface')
anchor('ANCHOR_BENCH_REWORK_APPROACH',(0,-1.1,0),rework,role='worker_approach')
r_buffer=group('QUEUE_R_ROLLER_SECTION',(4.36,-7.24,0),typ='rework_accumulation')
r_buffer['surface_height_m']=.86;r_buffer['queue']='R';r_buffer['preview_capacity']=6
r_buffer['slot_envelope_m']=[1.66,.82]
box('R buffer label plate',(.95,.024,.20),(0,-.505,.71),M['teal'],r_buffer,.004)
text('R buffer label','R [REWORK]',.105,(0,-.519,.671),M['label'],r_buffer,(math.pi/2,0,0),align='CENTER')
for y in [-.47,.47]:
    box('R buffer side frame',(1.94,.045,.11),(0,y,.77),M['dark'],r_buffer,.003)
for x in [-.94,.94]:
    box('R buffer end tie',(.035,.94,.055),(x,0,.755),M['steel'],r_buffer,.003)
for i in range(24):
    roller=cyl('R_ACCUMULATION_ROLLER_%02d'%i,.025,.88,(-.92+i*.08,0,.835),M['silver'],r_buffer,(math.pi/2,0,0),n=24,dynamic=True)
    roller['animation_role']='accumulation_roller';roller['radius']=.025
for x in [-.85,.85]:
    for y in [-.38,.38]:
        foot('R buffer level foot',x,y,r_buffer)
        box('R buffer extension leg',(.045,.045,.67),(x,y,.405),M['steel'],r_buffer,.002)
    box('R buffer lower brace',(.035,.82,.035),(x,0,.26),M['steel'],r_buffer,.002)
for i,pos in enumerate(CFG['shelving']['positions'],1):rack('RACK_%02d'%i,(*pos,0))
trolley('SUPPLY_TROLLEY',CFG['layout']['trolley'])

# Weigh/check portal around the conveyor. Separate stopper slide for replay.
qc=group('QC_PORTAL',CFG['layout']['qc_origin'],typ='inspection_portal')
for y in [-.49,.49]:
    box('Inspection foot',(.30,.20,.022),(0,y,.011),M['steel'],qc,.004)
    box('Inspection upright',(.065,.065,1.5),(0,y,.77),M['teal'],qc,.004)
    bolt('Inspection foot anchor',(.09,y,.026),qc)
box('Inspection crosshead',(.10,1.045,.08),(0,0,1.49),M['teal'],qc,.005)
box('Optical module',(.15,.23,.08),(0,0,1.40),M['dark'],qc,.008)
box('Optical lens',(.09,.13,.006),(0,0,1.357),M['blue'],qc,.003)
for y in [-.36,.36]:
    box('Photoelectric cell',(.06,.04,.05),(-.12,y,1.03),M['dark'],qc,.004)
    cyl('Sensor lens',.008,.002,(-.12,y+(.021 if y<0 else -.021),1.03),M['red'],qc,(math.pi/2,0,0),n=16)
box('Scale housing',(.62,.61,.07),(.03,0,.70),M['steel'],qc,.004)
gate=box('STOPPER_GATE',(.025,.56,.075),(.36,0,.805),M['yellow'],qc,.003,dynamic=True)
gate['animation_role']='stopper';gate['rest_z']=.805;gate['lift']=.085
for y in [-.41,.41]:box('Stopper cylinder',(.065,.065,.14),(.36,y,.70),M['steel'],qc,.004)
cyl('Tower base',.023,.20,(.08,.49,1.68),M['dark'],qc,n=32)
for z,ma in [(1.66,M['red']),(1.72,M['amber']),(1.78,M['green'])]:cyl('Tower segment',.032,.045,(.08,.49,z),ma,qc,n=48)
anchor('ANCHOR_QC_CENTER',(0,0,.86),qc,role='inspection')
assets['inspection_portal']=qc

dispatch=group('DISPATCH')
for i,y in enumerate(CFG['layout']['dispatch_y']):
    p=pallet('DISPATCH_PALLET_%02d'%i,(10.0,y,0),dispatch)
    p['outcome']='good' if i==0 else 'escaped'
# Q1's 3 x 2 preview occupies 1.66 x .82 m. Two empty euro pallets form
# the base; a thin continuous load-spreading deck closes plank gaps and the
# additional 10 mm at each side, precisely at the .15 m queue height.
q1=group('Q1_PAIRED_PALLET_DECK',(-10.44,3.31,0),typ='inbound_queue_support')
q1['queue']='Q1';q1['surface_height_m']=.15;q1['preview_slot_envelope_m']=[1.66,.82]
for i,x in enumerate([-.6,.6]):
    p=pallet('INBOUND_PALLET' if i==0 else 'INBOUND_PALLET_01',(x,0,0),q1)
    p.scale.z=.96
box('Q1 continuous load deck',(2.4,.86,.006),(0,0,.147),M['wood'],q1,.001)

# Open red mesh quarantine container: the load surface remains exactly at
# VIS_OUTCOME_SCRAP z=.02; all four mesh walls leave its top unobstructed.
scrap=group('SCRAP_BIN',(7.2,-7.0,.02),typ='scrap_quarantine_bin')
scrap['origin']='load-surface-center';scrap['open_top']=True
scrap['outcome']='scrap';scrap['load_surface_height_m']=.02
box('Scrap bin base',(1.2,1.0,.02),(0,0,-.01),M['red'],scrap,.003)
for x in [-.59,.59]:
    for y in [-.49,.49]:box('Scrap bin corner',(.025,.025,.72),(x,y,.36),M['red'],scrap,.002)
for z in [.035,.70]:
    for y in [-.49,.49]:box('Scrap bin long rim',(1.2,.025,.025),(0,y,z),M['red'],scrap,.002)
    for x in [-.59,.59]:box('Scrap bin end rim',(.025,1.0,.025),(x,0,z),M['red'],scrap,.002)
for z in [.14,.25,.36,.47,.58]:
    for y in [-.49,.49]:beam('Scrap mesh horizontal',(-.575,y,z),(.575,y,z),.007,M['red'],scrap)
    for x in [-.59,.59]:beam('Scrap mesh horizontal',(x,-.475,z),(x,.475,z),.007,M['red'],scrap)
for x in [-.5+i*.1 for i in range(11)]:
    for y in [-.49,.49]:beam('Scrap mesh vertical',(x,y,.05),(x,y,.69),.007,M['red'],scrap)
for y in [-.4+i*.1 for i in range(9)]:
    for x in [-.59,.59]:beam('Scrap mesh vertical',(x,y,.05),(x,y,.69),.007,M['red'],scrap)

# Two shrouds hide parcel creation and recycling outside the visible belt.
for name,x in [('INLET_HOOD',CFG['demo']['start_x']+.02),('OUTLET_HOOD',CFG['demo']['end_x']-.02)]:
    g=group(name,(x,0,0),typ='transfer_hood')
    box('Transfer tray',(.70,.62,.035),(0,0,.82),M['dark'],g,.004)
    for y in [-.36,.36]:box('Hood side',(.70,.045,.54),(0,y,1.095),M['teal'],g,.009)
    box('Hood top',(.70,.76,.045),(0,0,1.385),M['teal'],g,.009)
    # The opaque end plate masks replay recycling from the main camera.
    endx=-.325 if x<0 else .325
    box('Outer end baffle',(.045,.70,.54),(endx,0,1.095),M['teal'],g,.008)
    box('Transfer support',(.055,.055,.73),(0,0,.42),M['steel'],g,.004)
    box('Transfer foot',(.38,.45,.025),(0,0,.0125),M['steel'],g,.004)

props=group('PROPS')
# Only the paper storage belongs in this rear service pocket.
px,py,pz=CFG['layout']['paper_stock']
paper_pallet=pallet('PAPER_STOCK_PALLET',(px+.32,py,0),props)
paper_pallet['storage_only']=True
paper_rack=group('PAPER_STOCK_RACK',(px+.32,py,0),props,typ='paper_roll_storage')
for x in [-.55,.55]:
    for y in [-.33,.33]:box('Paper rack upright',(.035,.035,.82),(x,y,.41),M['steel'],paper_rack,.003)
for y in [-.33,.33]:
    box('Paper rack top rail',(1.12,.025,.035),(0,y,.80),M['steel'],paper_rack,.002)
pz=.15+.52/2
for i in range(3):
    cyl('Paper stock',.105,.52,(px+i*.32,py,pz),M['paper'],props,n=64)
    cyl('Paper stock core',.027,.005,(px+i*.32,py,pz+.262),M['kraft'],props,n=32)

anchors=group('ANCHORS')
for a in CFG['future_mounts']:
    anchor('MOUNT_'+a['id'],a['position'],anchors,role='future_actor',clearance=a['clearance'])
anchor('ANCHOR_LINE_IN',(CFG['demo']['start_x'],0,.86),anchors,role='line_in')
anchor('ANCHOR_LINE_OUT',(CFG['demo']['end_x'],0,.86),anchors,role='line_out')
anchor('ANCHOR_PACK_GRASP',(pack_x,pack_y-.08,1.11),anchors,role='parcel_grasp')
anchor('ANCHOR_REWORK',(*CFG['layout']['rework'][:2],.86),anchors,role='rework_surface')

demo=CFG['demo'];start_x,end_x,stop_x=demo['start_x'],demo['end_x'],demo['stop_x']
speed,dwell,cycle,count=demo['speed_mps'],demo['inspection_stop_seconds'],demo['cycle_seconds'],demo['carton_count']
arrival=(stop_x-start_x)/speed
def action_fcurves(action):
    # Blender 4.x legacy actions and Blender 5.x layered actions share the
    # same keyframe data, exposed through different containers.
    if hasattr(action,'fcurves'):return list(action.fcurves)
    return [fc for layer in action.layers for strip in layer.strips
            for bag in getattr(strip,'channelbags',[]) for fc in bag.fcurves]
def smooth(x):
    x=max(0,min(1,x));return x*x*(3-2*x)
def visual_pose(t,i):
    age=(t+i*cycle/count)%cycle
    travel=age if age<arrival else arrival if age<arrival+dwell else age-dwell
    return min(end_x,start_x+travel*speed),age<=(end_x-start_x)/speed+dwell,age
for i in range(count):
    o=carton('DEMO_PARCEL_%02d'%(i+1),(visual_pose(0,i)[0],0,.86),dynamic=True)
    o['animation_role']='parcel';o['parcel_id']='demo-%02d'%(i+1)
    # Bake the exact shared-clock replay, including the dwell and masked recycling.
    for f in range(1,sc.frame_end+1):
        x,visible,_=visual_pose((f-1)/30,i)
        o.location.x=x;o.hide_render=not visible
        o.keyframe_insert(data_path='location',index=0,frame=f)
        o.keyframe_insert(data_path='hide_render',frame=f)
    if o.animation_data:
        for fc in action_fcurves(o.animation_data.action):
            for k in fc.keyframe_points:k.interpolation='CONSTANT' if fc.data_path=='hide_render' else 'LINEAR'
for f in range(1,sc.frame_end+1):
    t=(f-1)/30;lift=0
    for i in range(count):
        _,_,age=visual_pose(t,i)
        if arrival-.8<=age<arrival+dwell:
            lift=max(lift,min(smooth((age-(arrival-.8))/.25),1-smooth((age-(arrival+dwell-.25))/.25)))
    gate.location.z=.805+.085*lift;gate.keyframe_insert(data_path='location',index=2,frame=f)
sc.frame_set(1)

# Native lighting and views. No camera/lights are embedded in GLB.
def camera(name,pos,target,lens=48,ortho=None):
    d=bpy.data.cameras.new(name);o=bpy.data.objects.new(name,d);sc.collection.objects.link(o);o.location=pos
    o.rotation_euler=(Vector(target)-o.location).to_track_quat('-Z','Y').to_euler()
    d.lens=lens
    if ortho:d.type='ORTHO';d.ortho_scale=ortho
    return o
hero=camera('CAMERA_OVERVIEW',(22,-29,24),(0,.8,.35),ortho=37)
camera('CAMERA_CONVEYOR',(-3.5,-4.5,3.0),(-4.5,0,.76),lens=52)
camera('CAMERA_PACK',(pack_x+3.4,pack_y-3.6,3.2),(pack_x,pack_y,1.10),lens=55)
camera('CAMERA_STORAGE',(-1.6,1.0,4.0),(-5.2,6.35,1.15),lens=48)
sc.camera=hero
def area(name,pos,power,size,target):
    d=bpy.data.lights.new(name,'AREA');d.energy=power;d.shape='DISK';d.size=size
    o=bpy.data.objects.new(name,d);sc.collection.objects.link(o);o.location=pos
    o.rotation_euler=(Vector(target)-o.location).to_track_quat('-Z','Y').to_euler()
area('Large softbox',(-6,-8,16),3200,12,(0,1,0))
area('Rear fill',(5,8,12),1800,10,(0,0,0))
area('Edge fill',(13,0,9),1100,9,(0,0,.5))
sc.world.color=(.35,.35,.35);sc.world.use_nodes=True
sc.world.node_tree.nodes['Background'].inputs[0].default_value=(.38,.44,.42,1)
sc.world.node_tree.nodes['Background'].inputs[1].default_value=.35
sc.render.engine='CYCLES';sc.cycles.samples=256;sc.cycles.use_denoising=False
sc.render.resolution_x=1680;sc.render.resolution_y=1120;sc.render.resolution_percentage=100
sc.view_settings.view_transform='AgX'
sc.view_settings.look='AgX - Medium Low Contrast'
sc.render.image_settings.file_format='PNG';sc.render.film_transparent=False
sc.render.filepath=str(OUT/'environment_overview.png')
for screen in bpy.data.screens:
    for area_ui in screen.areas:
        if area_ui.type=='VIEW_3D':
            sp=area_ui.spaces.active;sp.clip_end=500
            sp.shading.type='SOLID';sp.shading.color_type='MATERIAL'
            sp.shading.show_cavity=True
            sp.region_3d.view_perspective='CAMERA'

# Structural QA before optimization; open shells are built from closed walls.
for arrow in walkway_arrows:
    bm=bmesh.new();bm.from_mesh(arrow.data);bm.verts.ensure_lookup_table()
    found=set();pending=[bm.verts[0]]
    while pending:
        vertex=pending.pop()
        if vertex in found:continue
        found.add(vertex);pending.extend(edge.other_vert(vertex) for edge in vertex.link_edges)
    assert len(found)==len(bm.verts),'Disconnected walkway arrow'
    assert all(face.normal.z>.99 for face in bm.faces),'Inverted walkway arrow'
    bm.free()
bpy.context.view_layer.update()
label_points=[lane_label.matrix_world@v.co for v in lane_label.data.vertices]
label_center=[(min(v[i] for v in label_points)+max(v[i] for v in label_points))/2 for i in [0,1]]
assert abs(label_center[0])<1e-6 and abs(label_center[1]-lane_center)<1e-6,label_center
assert max(abs(v.y-lane_center) for v in label_points)<abs(lane_front-lane_back)/2-.1
degenerate=[];bad_vertices=[]
for ob in bpy.data.objects:
    if ob.type=='MESH':
        if any(not math.isfinite(v) for vert in ob.data.vertices for v in vert.co):bad_vertices.append(ob.name)
        if any(p.area<1e-12 for p in ob.data.polygons):degenerate.append(ob.name)
assert not bad_vertices,bad_vertices
assert not degenerate,degenerate
connection_errors=[]
for i in range(1,len(CFG['conveyor']['centers_x'])):
    a=bpy.data.objects['ANCHOR_C%02d_OUT'%i];b=bpy.data.objects['ANCHOR_C%02d_IN'%(i+1)]
    bpy.context.view_layer.update()
    gap=(a.matrix_world.translation-b.matrix_world.translation).length
    if gap>1e-6:connection_errors.append({'join':i,'gap_m':gap})
assert not connection_errors,connection_errors
assert not [o.name for o in bpy.data.objects if o.type=='ARMATURE']
report={'source_mesh_objects':sum(o.type=='MESH' for o in bpy.data.objects),'unique_meshes':len(bpy.data.meshes), 'invalid_vertices':bad_vertices,'degenerate_faces':degenerate,'conveyor_connection_errors':connection_errors,'robots':0,'people':0,'units':'meters','origin_convention':'bottom-center for portable props', 'native_dimensions':CFG}
report['floor_markings']={'arrow_count':len(walkway_arrows),'arrow_connected_components_each':1,'label_center_xy_m':label_center,'lane_center_y_m':lane_center,'label_centered':True}
(OUT/'geometry_report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'warehouse_environment.blend'))
print('NATIVE_SCENE_SAVED',flush=True)

def descendants(root):return [root]+list(root.children_recursive)
def export_selection(path,objects):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objects:o.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(path),export_format='GLB',use_selection=True,export_yup=True,export_apply=True,export_extras=True,export_animations=False,export_cameras=False,export_lights=False)

# Individual assets use a clean local origin, before flattening static draw calls.
asset_manifest=[]
for name,obj in assets.items():
    oldpar=obj.parent;oldmat=obj.matrix_world.copy();oldloc=obj.location.copy();oldrot=obj.rotation_euler.copy()
    obj.parent=None;obj.location=(0,0,0);obj.rotation_euler=(0,0,0)
    bpy.context.view_layer.update()
    selected=descendants(obj)
    if name=='pallet_1200x800':selected=[obj]+[part for part in obj.children if part.type=='MESH']
    points=[]
    inv=obj.matrix_world.inverted()
    for part in selected:
        if part.type=='MESH':points.extend(inv@part.matrix_world@Vector(v) for v in part.bound_box)
    lo=[min(v[i] for v in points) for i in range(3)];hi=[max(v[i] for v in points) for i in range(3)]
    asset_manifest.append({'id':name,'file':f'modules/{name}.glb','bounds_min_m':lo,'bounds_max_m':hi,'actual_envelope_m':[hi[i]-lo[i] for i in range(3)],'origin':'root-local','editable_parts':len(descendants(obj))-1})
    if name=='tote_600x400':
        for actual,want in zip(asset_manifest[-1]['actual_envelope_m'],[.6,.4,.22]):assert abs(actual-want)<.0001,(name,actual,want)
    export_selection(OUT/'modules'/f'{name}.glb',selected)
    obj.parent=oldpar;obj.location=oldloc;obj.rotation_euler=oldrot
    bpy.context.view_layer.update()
print('MODULAR_ASSETS_EXPORTED',flush=True)
(OUT/'asset_manifest.json').write_text(json.dumps(asset_manifest,ensure_ascii=False,indent=2))

sys.path.insert(0,str(ROOT/'scripts'))
from optimize_export import export_optimized
export_optimized(OUT,render=opt.render,details=opt.details)
print('BUILD_COMPLETE',flush=True)
