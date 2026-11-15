"""Final art direction and export. Run after build_environment.py; no network assets.

blender -b warehouse_environment.blend --python scripts/flexsim_finish.py -- 
  --output PATH --source ORIGINAL.blend [--render]
"""
import bpy, bmesh, ast, math, json, sys, argparse, hashlib
from pathlib import Path
from mathutils import Vector

P=argparse.ArgumentParser()
P.add_argument('--output',required=True); P.add_argument('--source',required=True)
P.add_argument('--render',action='store_true'); P.add_argument('--render-only',action='store_true')
opt=P.parse_args(sys.argv[sys.argv.index('--')+1:])
OUT=Path(opt.output).resolve(); ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
sc=bpy.context.scene
bpy.context.preferences.filepaths.save_version=0
bpy.context.preferences.edit.use_global_undo=False

def rgb(h):
    v=[int(h[i:i+2],16)/255 for i in (0,2,4)]
    return tuple(c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4 for c in v)

def material(name,h,metal=0,rough=.5,emission=0):
    m=bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes=True; c=(*rgb(h),1); m.diffuse_color=c
    p=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
    p.inputs['Base Color'].default_value=c
    p.inputs['Metallic'].default_value=metal; p.inputs['Roughness'].default_value=rough
    p.inputs['Emission Color'].default_value=c; p.inputs['Emission Strength'].default_value=emission
    m['color_srgb']='#'+h; return m

def api_functions():
    # Reuse the dimensioned native modelling functions, without running the build.
    tree=ast.parse((ROOT/'scripts/build_environment.py').read_text())
    tree.body=[n for n in tree.body if isinstance(n,ast.FunctionDef)]
    g=dict(bpy=bpy,bmesh=bmesh,math=math,Vector=Vector,sc=sc,cache={},assets={},roots=[])
    exec(compile(tree,'native_geometry_helpers','exec'),g)
    return g

def palette():
    specs={
      'floor':('Warm mineral concrete','d5dbe0',.04,.42),
      'edge':('Plinth edge','9ca9b5',.12,.44),
      'wall':('Porcelain wall panels','e9edf0',0,.63),
      'steel':('Satin zinc steel','798995',.55,.32),
      'silver':('Bright aluminium','c7d1da',.78,.26),
      'teal':('Petrol powder coat','0e4c92',.15,.38),
      'dark':('Graphite rubber and guards','2b3137',.25,.36),
      'yellow':('Safety ochre','f4b400',.08,.38),
      'white':('Warm white laminate','e7ecef',.03,.43),
      'kraft':('Kraft cardboard','ba884d',0,.8),
      'kraftLight':('Cardboard cut edge','d3a76f',0,.78),
      'tape':('Paper tape','d1b489',0,.64),
      'paper':('Packing paper','ddc493',0,.75),
      'wood':('Pallet timber','c5a16e',0,.73),
      'label':('Paper labels','f4f6f7',0,.6),
      'red':('Emergency stop','d32f2f',0,.4),
      'green':('Status green','36b559',.05,.32),
      'amber':('Status amber','ffb300',.05,.33),
      'blue':('Status blue','2187c9',.05,.32),
      'black':('Printed charcoal','242b32',0,.57),
      'orange':('FlexSim / Rack orange','e85d04',.12,.36),
      'walk':('FlexSim / Pedestrian green','2e7d32',0,.56),
      'grid':('FlexSim / CAD grid minor','b8c1ca',0,.8),
      'gridMajor':('FlexSim / CAD grid major','8d99a6',0,.8),
    }
    return {k:material(name,h,me,ro,.25 if k in ('green','amber','blue') else 0)
            for k,(name,h,me,ro) in specs.items()}

def layer(api,name):
    g=api['group'](name); g['ui_layer']=name; g['default_visible']=name!='ENV_OVERHEAD'
    c=bpy.data.collections.get(name) or bpy.data.collections.new(name)
    if c.name not in sc.collection.children:sc.collection.children.link(c)
    return g,c

def move_to_layer(obj,root,col):
    world=obj.matrix_world.copy();obj.parent=root;obj.matrix_world=world
    for c in list(obj.users_collection):c.objects.unlink(obj)
    col.objects.link(obj)

def floor_and_grid(api):
    M=api['M'];box=api['box'];text=api['text'];beam=api['beam']
    root,col=layer(api,'ENV_FLOOR_AND_GRID')
    for o in list(bpy.data.objects):
        if o.name.startswith(('Concrete control joint','Walkway ','Floor zone ','Service lane text','Inbound paint','Outbound paint','Inbound legend','Outbound legend')):
            bpy.data.objects.remove(o,do_unlink=True)
        elif o.name.startswith(('Raised concrete slab','Lower reveal')):move_to_layer(o,root,col)
    # Grid runs 5 m beyond the 36 x 18 slab. Mesh geometry, compatible with glTF.
    for x in range(-23,24):
        major=x%5==0
        box('CAD_GRID_X_%+03d'%x,(.014 if major else .006,28,.0003),(x,0,.00045),M['gridMajor' if major else 'grid'],root,0)
    for y in range(-14,15):
        major=y%5==0
        box('CAD_GRID_Y_%+03d'%y,(46,.014 if major else .006,.0003),(0,y,.00045),M['gridMajor' if major else 'grid'],root,0)
    # Bottom surface of every broad 5S paint film is 1.5 mm above the slab.
    def paint(name,w,d,x,y,ma,z=.00165):
        return box(name,(w,d,.0003),(x,y,z),ma,root,0)
    paint('WALKWAY_GREEN_5S',35.4,1.5,0,-5.15,M['walk'])
    for y in [-5.88,-4.42]:paint('WALKWAY_WHITE_BORDER',35.4,.045,0,y,M['label'],.00205)
    for x in [-17.7,17.7]:paint('WALKWAY_END',.045,1.5,x,-5.15,M['label'],.00205)
    for x in [-11.8,0,11.8]:
        o=api['floor_arrow']('WALKWAY_DIRECTION',x,-5.15,root);o.location.z=.00235
    def outline(name,label,x,y,w,d,ma,caption=True,label_size=.235):
        for xx,yy,ww,dd in [(x,y-d/2,w,.036),(x,y+d/2,w,.036),(x-w/2,y,.036,d),(x+w/2,y,.036,d)]:paint(name,ww,dd,xx,yy,ma)
        for sx in [-1,1]:
            for sy in [-1,1]:
                paint(name+'_CORNER',.25,.065,x+sx*(w/2-.125),y+sy*d/2,ma,.002)
                paint(name+'_CORNER',.065,.25,x+sx*w/2,y+sy*(d/2-.125),ma,.002)
        if caption:text(name+'_LABEL',label,label_size,(x-w/2+.15,y-d/2+.15,.0024),ma,root)
    for args in [
       ('FLOOR_ZONE_01','01 PREP',-10.475,2.775,3.85,4.25),
       ('FLOOR_ZONE_02','02 PICK',-6.05,2.775,4.2,4.25),
       ('FLOOR_ZONE_03','03 PACK + ROBOT',.775,2.775,8.65,4.25),
       ('FLOOR_ZONE_04','04 QC',7.0875,2.775,3.375,4.25),
       ('FLOOR_ZONE_R','R REWORK',4.36,-7.23,2.8,1.55)]:outline(*args,M['teal'])
    for state,x,y,w,d,ma in [('GOOD',10,2.2,1.8,1.25,M['green']),('ESCAPED / HOLD',10,4.4,2.0,1.35,M['amber']),('SCRAP',7.2,-7,1.65,1.5,M['red'])]:
        outline('OUTCOME_FLOOR_'+state.split()[0],state,x,y,w,d,ma,label_size=.18 if state.startswith('ESCAPED') else .235)
    # Yellow/black clipped diagonal border; front service opening remains clear.
    def hatch(x,y,w,d):
        paint('ROBOT_HAZARD_YELLOW',w,d,x,y,M['yellow'],.0018)
        # Clip parallelograms to rectangular strip in 2D.
        def clip(poly,axis,bound,keep_greater):
            out=[]
            for a,b in zip(poly,poly[1:]+poly[:1]):
                ia=(a[axis]>=bound) if keep_greater else (a[axis]<=bound)
                ib=(b[axis]>=bound) if keep_greater else (b[axis]<=bound)
                if ia:out.append(a)
                if ia!=ib:
                    t=(bound-a[axis])/(b[axis]-a[axis]);out.append(tuple(a[i]+t*(b[i]-a[i]) for i in range(2)))
            return out
        for k in range(-int((w+d)/.22)-3,int((w+d)/.22)+4):
            a=k*.22
            pts=[(a-d,-d),(a-d+.11,-d),(a+d+.11,d),(a+d,d)]
            for axis,bound,greater in [(0,-w/2,True),(0,w/2,False),(1,-d/2,True),(1,d/2,False)]:
                if pts:pts=clip(pts,axis,bound,greater)
            if len(pts)>2:
                me=bpy.data.meshes.new('Hazard stripe mesh');me.from_pydata([(px+x,py+y,.0022) for px,py in pts],[],[tuple(range(len(pts)))]);me.materials.append(M['black'])
                o=bpy.data.objects.new('ROBOT_HAZARD_STRIPE',me);sc.collection.objects.link(o);o.parent=root
    hatch(3.65,4.4,2.5,.13);hatch(4.87,2.9,.13,3.0)
    hatch(2.46,3.7,.13,1.4);hatch(4.25,1.40,1.25,.13)
    for o in root.children_recursive:
        if col not in o.users_collection:
            for c in list(o.users_collection):c.objects.unlink(o)
            col.objects.link(o)

def recolor_equipment(api):
    M=api['M']
    ports=[(-6.46,.64),(.42,.64),(6.44,.64)]
    for o in bpy.data.objects:
        if o.type!='MESH':continue
        p=o
        ancestors=[]
        while p:ancestors.append(p.name);p=p.parent
        ma=None
        if any(a.startswith('RACK_0') for a in ancestors):
            if o.name.startswith('Rack upright'):ma=M['teal']
            elif o.name.startswith('Shelf front return'):ma=M['orange']
        if any(a.startswith('CONVEYOR_') for a in ancestors):
            if o.name.startswith(('Folded side profile','Square leg','Cross member','Support cross tie','Guard rail','Guide stanchion')):ma=M['dark']
            elif o.name.startswith('ROLLER_'):ma=M['silver']
        if ma:
            # Linked geometry may have other uses: isolate only when replacing.
            o.data=o.data.copy();o.data.materials.clear();o.data.materials.append(ma)
    # Open the front guide at each physical buffer transfer. Preserve the ten
    # module roots and all 200 individual animated rollers.
    for i in range(1,11):
        g=bpy.data.objects['CONVEYOR_%02d'%i];gx=g.location.x
        for o in list(g.children):
            if o.name.startswith('Guard rail') and o.location.y<0:
                bpy.data.objects.remove(o,do_unlink=True)
            elif o.name.startswith(('Guide stanchion','Guide fastener')) and o.location.y<0:
                if any(abs(gx+o.location.x-c)<w/2+.025 for c,w in ports):bpy.data.objects.remove(o,do_unlink=True)
        intervals=[(-.9,.9)]
        for c,w in ports:
            a,b=c-w/2-gx,c+w/2-gx
            rest=[]
            for lo,hi in intervals:
                if b<=lo or a>=hi:rest.append((lo,hi));continue
                if a>lo:rest.append((lo,min(a,hi)))
                if b<hi:rest.append((max(b,lo),hi))
            intervals=rest
        for a,b in intervals:
            if b-a>.005:api['box']('Guard rail transfer opening',(b-a,.018,.025),((a+b)/2,-.33,.928),M['dark'],g,.002)
    for i in range(1,11):
        g=bpy.data.objects['CONVEYOR_%02d'%i]
        for side,y in [('L',-.405),('R',.405)]:
            sx=-.42
            if side=='L' and any(abs(g.location.x+sx-c)<w/2+.05 for c,w in ports):
                sx=next(v for v in [-.8,.8] if all(abs(g.location.x+v-c)>w/2+.06 for c,w in ports))
            p=api['group']('PHOTOEYE_%02d_%s'%(i,side),(sx,y,.96),g)
            p['animation_role']='photoeye';p['line_module']=i
            api['box']('PHOTOEYE_BODY',(.062,.038,.07),(0,0,0),M['dark'],p,.004)
            api['cyl']('PHOTOEYE_LENS',.012,.004,(0,-math.copysign(.021,y),0),M['blue'],p,(math.pi/2,0,0),n=16)
            api['cyl']('PHOTOEYE_LED',.004,.004,(.02,-math.copysign(.021,y),.022),M['green'],p,(math.pi/2,0,0),n=12)

def clean_geometry():
    seen=set();fixed=0
    for o in bpy.data.objects:
        if o.type!='MESH' or o.data.name in seen:continue
        if any(c.name.startswith('CHARACTERS / ') for c in o.users_collection):continue
        seen.add(o.data.name)
        bm=bmesh.new();bm.from_mesh(o.data)
        bmesh.ops.dissolve_degenerate(bm,dist=1e-8,edges=list(bm.edges))
        bad=[f for f in bm.faces if f.calc_area()<1e-12]
        if bad:bmesh.ops.delete(bm,geom=bad,context='FACES_ONLY');fixed+=len(bad)
        if bm.faces:bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
        loose=[v for v in bm.verts if not v.link_faces]
        if loose:bmesh.ops.delete(bm,geom=loose,context='VERTS')
        bm.to_mesh(o.data);bm.free();o.data.update()
    print('GEOMETRY_CLEANED',len(seen),fixed,flush=True)

def configure_lighting():
    sc.unit_settings.system='METRIC';sc.unit_settings.scale_length=1
    sc.world.use_nodes=True
    nodes=sc.world.node_tree.nodes;links=sc.world.node_tree.links
    bg=next(n for n in nodes if n.type=='BACKGROUND' and n.name!='CAD camera background')
    bg.inputs['Color'].default_value=(*rgb('dce2e8'),1);bg.inputs['Strength'].default_value=.50
    # Camera backdrop is independent of ambient irradiance: light neutral CAD
    # background, with enough directional contrast to read blue/orange steel.
    camera_bg=nodes.get('CAD camera background') or nodes.new('ShaderNodeBackground')
    camera_bg.name='CAD camera background';camera_bg.inputs['Color'].default_value=(*rgb('dce2e8'),1)
    camera_bg.inputs['Strength'].default_value=3.0
    ray=nodes.get('CAD camera ray') or nodes.new('ShaderNodeLightPath');ray.name='CAD camera ray'
    mix=nodes.get('CAD world mix') or nodes.new('ShaderNodeMixShader');mix.name='CAD world mix'
    output=next(n for n in nodes if n.type=='OUTPUT_WORLD')
    links.new(ray.outputs['Is Camera Ray'],mix.inputs[0]);links.new(bg.outputs[0],mix.inputs[1]);links.new(camera_bg.outputs[0],mix.inputs[2]);links.new(mix.outputs[0],output.inputs['Surface'])
    sc.render.engine='CYCLES';sc.cycles.samples=32;sc.cycles.use_denoising=True
    sc.cycles.device='CPU';sc.render.film_transparent=False
    sc.view_settings.view_transform='AgX'
    for look in ['AgX - Punchy','AgX - Base Contrast','None']:
        try:sc.view_settings.look=look;break
        except TypeError:pass
    sc.view_settings.exposure=0;sc.view_settings.gamma=1
    for o in bpy.data.objects:
        if o.type=='LIGHT' and o.name in {'Large softbox','Rear fill','Edge fill'}:
            o.data.energy={'Large softbox':5280,'Rear fill':2970,'Edge fill':1815}[o.name]
    sc.render.resolution_x=1800;sc.render.resolution_y=1200;sc.render.resolution_percentage=100
    sc.render.image_settings.file_format='PNG'
    camera=bpy.data.objects['CAMERA_OVERVIEW'];camera.data.ortho_scale=44
    camera.location=(22,-30,27);camera.rotation_euler=(Vector((0,.3,.1))-camera.location).to_track_quat('-Z','Y').to_euler();sc.camera=camera
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type=='VIEW_3D':
                sp=area.spaces.active;sp.shading.type='MATERIAL';sp.shading.color_type='MATERIAL'
                sp.shading.background_type='WORLD';sp.clip_end=500
                sp.region_3d.view_perspective='CAMERA'
    sc['style']='FlexSim-inspired engineering CAD / sRGB RAL 5010 + RAL 2004'

def append_characters():
    with bpy.data.libraries.load(str(Path(opt.source).resolve()),link=False) as (src,dst):
        dst.collections=[n for n in src.collections if n.startswith('CHARACTERS / ')]
    for c in dst.collections:
        if c and c.name not in sc.collection.children:sc.collection.children.link(c)

def snapshot_actions():
    records={}
    for a in bpy.data.actions:
        if not a.name.startswith(('Worker_','Robot_')):continue
        data=[]
        for layer in a.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for fc in bag.fcurves:
                        data.append([fc.data_path,fc.array_index,[[float(v) for v in k.co] for k in fc.keyframe_points]])
        if not data and hasattr(a,'fcurves'):
            data=[[fc.data_path,fc.array_index,[[float(v) for v in k.co] for k in fc.keyframe_points]] for fc in a.fcurves]
        records[a.name]=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
    return records

if not opt.render_only:
    append_characters();before=snapshot_actions()
    # Support script keeps its normal CLI contract and saves/export its own modules.
    import runpy
    original_argv=sys.argv[:]
    sys.argv=[str(ROOT/'scripts/build_visual_support.py'),'--','--output',str(OUT)]
    runpy.run_path(str(ROOT/'scripts/build_visual_support.py'),run_name='__main__')
    sys.argv=original_argv
    api=api_functions();api['M']=palette()
    # Keep the portable open carton in the catalog, never on an active bench.
    catalog=api['carton']('CATALOG_CARTON_OPEN',(0,0,0),open_top=True)
    bpy.ops.object.select_all(action='DESELECT')
    for o in [catalog]+list(catalog.children_recursive):o.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(OUT/'modules/carton_open.glb'),export_format='GLB',use_selection=True,export_yup=True,export_extras=True,export_animations=False,export_cameras=False,export_lights=False)
    for o in list(catalog.children_recursive):bpy.data.objects.remove(o,do_unlink=True)
    bpy.data.objects.remove(catalog,do_unlink=True)
    floor_and_grid(api);recolor_equipment(api)
    from industrial_equipment import build_equipment
    build_equipment(api)
    from flexsim_character_palette import apply_character_palette
    apply_character_palette(add_helmet=True)
    clean_geometry()
    for name,file in [('INTEGRATION / Visual templates','visual_support'),('INTEGRATION / Stations and anchors','visual_layout')]:
        bpy.ops.object.select_all(action='DESELECT')
        selected=set(bpy.data.collections[name].objects)
        for o in list(selected):selected.update(o.children_recursive)
        for o in selected:o.select_set(True)
        bpy.ops.export_scene.gltf(filepath=str(OUT/'modules'/(file+'.glb')),export_format='GLB',use_selection=True,export_yup=True,export_extras=True,export_animations=False,export_cameras=False,export_lights=False)
    bpy.data.collections['INTEGRATION / Visual templates'].hide_viewport=True
    configure_lighting()
    after=snapshot_actions();assert before==after,'Character animation data changed'
    (OUT/'animation_preservation.json').write_text(json.dumps({'passed':True,'actions':before,'worker_clips':len([k for k in before if k.startswith('Worker_')]),'robot_clips':len([k for k in before if k.startswith('Robot_')])},indent=2))
    # Default native overview omits the overhead for a clean cutaway; UI can toggle it.
    overhead=bpy.data.objects.get('ENV_OVERHEAD')
    if overhead:
        for o in [overhead]+list(overhead.children_recursive):o.hide_render=True
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'warehouse_environment.blend'))
    sys.argv=[str(ROOT/'scripts/export_characters.py'),'--','--output',str(OUT)]
    runpy.run_path(str(ROOT/'scripts/export_characters.py'),run_name='__main__')
    sys.argv=original_argv
    for prefix,anchor in [('WORKER','VIS_STAGE_2_WORK'),('ROBOT','VIS_ROBOT_WORK')]:
        rig=bpy.data.objects[prefix+'_Rig'];rig.location=bpy.data.objects[anchor].matrix_world.translation
        rig.rotation_euler.z=math.pi
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'warehouse_environment.blend'))
    from validate_flexsim_native import validate_native
    validate_native(OUT)
    # Remove characters/overlay from transient export scene; native source already saved.
    excluded=set()
    for o in bpy.data.objects:
        if o.get('integration_visual') or o.get('worker_asset') or o.get('robot_asset') or any(c.name.startswith('CHARACTERS / ') for c in o.users_collection):
            excluded.add(o);excluded.update(o.children_recursive)
    # Snapshot the full excluded hierarchy before removing parents. A newly
    # authored child may lack its parent's integration_visual custom property.
    for o in excluded:bpy.data.objects.remove(o,do_unlink=True)
    # The optimized GLB keeps the requested root groups and all independent movers.
    from optimize_export import export_optimized
    export_optimized(OUT)
    assert (OUT/'warehouse_environment.glb').stat().st_size<=12*1024*1024
    print('FLEXSIM_ASSETS_COMPLETE',flush=True)

if opt.render:
    # Reopen native to restore editable nodes and all presentation models.
    bpy.ops.wm.open_mainfile(filepath=str(OUT/'warehouse_environment.blend'))
    sc=bpy.context.scene
    configure_lighting()
    sc.frame_set(0)
    # Environment preview at tick zero: no legacy demonstration parcels or props.
    for o in bpy.data.objects:
        if o.name.startswith('DEMO_PARCEL_') or o.get('handling_prop'):
            o.hide_render=True
            for c in o.children_recursive:c.hide_render=True
    sc.render.filepath=str(OUT/'environment_overview.png')
    bpy.ops.render.render(write_still=True)
    for name,pos,target,scale in [
        ('detail_packing',(9,-4,7),(3.2,2.7,.9),9.4),
        ('detail_conveyor',(-2,-7,5.5),(-5.5,-1,.65),10.5),
        ('detail_storage',(-2,1.6,5),(-6,6.25,1.2),10.0),
    ]:
        camera=bpy.data.objects['CAMERA_PACK'];camera.data.type='ORTHO';camera.data.ortho_scale=scale
        camera.location=pos;camera.rotation_euler=(Vector(target)-camera.location).to_track_quat('-Z','Y').to_euler()
        sc.camera=camera;sc.render.resolution_x=1400;sc.render.resolution_y=1000
        sc.render.filepath=str(OUT/(name+'.png'));bpy.ops.render.render(write_still=True)
    print('FLEXSIM_PREVIEW_COMPLETE',flush=True)
