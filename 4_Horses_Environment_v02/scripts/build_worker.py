"""Original faceted warehouse worker, authored into the existing warehouse .blend.

blender -b warehouse_environment.blend -t 6 --python scripts/build_worker.py -- --output PATH --render
No downloaded character geometry, textures, remeshing, or decimation.
"""
import bpy, bmesh, math, json, argparse, sys
from pathlib import Path
from mathutils import Vector, Quaternion, Matrix

P=argparse.ArgumentParser(); P.add_argument('--output',required=True);P.add_argument('--render',action='store_true');P.add_argument('--motion-only',action='store_true');P.add_argument('--back-only',action='store_true');P.add_argument('--quick',action='store_true')
opt=P.parse_args(sys.argv[sys.argv.index('--')+1:])
OUT=Path(opt.output);ROOT=Path(__file__).resolve().parent.parent
(OUT/'modules').mkdir(exist_ok=True,parents=True)
sc=bpy.context.scene
bpy.context.preferences.filepaths.save_version=0
bpy.context.preferences.edit.use_global_undo=False
for ob in list(bpy.data.objects):
    if ob.get('worker_asset') or ob.name.startswith(('WORKER_','ATTACH_WORKER_')):
        bpy.data.objects.remove(ob,do_unlink=True)
old=bpy.data.collections.get('CHARACTERS / Warehouse worker')
if old:bpy.data.collections.remove(old)
for blocks in [bpy.data.meshes,bpy.data.armatures]:
    for data in list(blocks):
        if data.name.startswith('WORKER_') and data.users==0:blocks.remove(data)
col=bpy.data.collections.new('CHARACTERS / Warehouse worker');sc.collection.children.link(col)
def link(ob):
    col.objects.link(ob);ob['worker_asset']=True;return ob

def srgb_hex(value):
    # Palette specifications are sRGB; Principled shader inputs are scene-linear.
    value=value.lstrip('#')
    channels=[int(value[i:i+2],16)/255 for i in (0,2,4)]
    return tuple(c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4 for c in channels)

# Legacy material names are retained so existing native files can be recolored.
palette={
 'shirt':('Deep petrol work shirt',srgb_hex('#0e4c92'),.62),
 'trousers':('Graphite blue cargo trousers',srgb_hex('#2b3137'),.76),
 'vest':('Muted ochre safety vest',srgb_hex('#ffdf00'),.57),
 'tape':('Satin silver reflective bands',srgb_hex('#e2e8ee'),.32),
 'edge':('Vest charcoal binding',srgb_hex('#242b32'),.78),
 'skin':('Warm skin / featureless face',srgb_hex('#c68e66'),.72),
 'hair':('Faceted dark brown hair',srgb_hex('#493427'),.88),
 'glove':('Charcoal protective gloves',srgb_hex('#424c57'),.82),
 'boot':('Graphite safety boot uppers',srgb_hex('#262e36'),.80),
 'sole':('Rubber soles',srgb_hex('#161b20'),.95),
 'pocket':('Cargo pocket accents',srgb_hex('#3b4653'),.78),
 'helmet':('Safety yellow helmet',srgb_hex('#f4b400'),.36),
}
materials=[]; mi={}
for key,(name,rgb,rough) in palette.items():
    m=bpy.data.materials.get('Worker / '+name) or bpy.data.materials.new('Worker / '+name)
    m.use_nodes=True;m.diffuse_color=(*rgb,1)
    p=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED');p.inputs['Base Color'].default_value=(*rgb,1)
    p.inputs['Roughness'].default_value=rough
    p.inputs['Metallic'].default_value=.30 if key=='tape' else .03 if key=='helmet' else 0
    mi[key]=len(materials);materials.append(m)

# All shapes use deliberate rings and cloth panels. Flat faces are the style.
V=[];F=[];FM=[];W=[]
def vert(co,weights):V.append(tuple(co));W.append(weights);return len(V)-1
def face(ids,ma):
    if len(ids)==4:
        a,b,c,d=ids
        # Stable, alternating diagonals produce controlled broad triangular planes.
        tris=[(a,b,c),(a,c,d)] if (a+b)%2 else [(a,b,d),(b,c,d)]
    else:tris=[tuple(ids)]
    for ids in tris:F.append(ids);FM.append(mi[ma])
def bridge(a,b,ma,skip=()):
    for j in range(len(a)):
        if j not in skip:face([a[j],a[(j+1)%len(a)],b[(j+1)%len(a)],b[j]],ma)
def cap(r,ma,reverse=False):
    for j in range(1,len(r)-1):face([r[0],r[j+1],r[j]] if reverse else [r[0],r[j],r[j+1]],ma)
def ring_xy(z,rx,ry,c=(0,0),n=16,weights=None,angle=0,direction=1):
    return [vert((c[0]+rx*math.cos(angle+direction*j*2*math.pi/n),c[1]+ry*math.sin(angle+direction*j*2*math.pi/n),z),weights or {'hips':1}) for j in range(n)]
def torso_weights(z):
    if z<1.03:return {'hips':1}
    if z<1.20:
        t=(z-1.03)/.17;return {'hips':1-t,'spine':t}
    if z<1.37:
        t=(z-1.20)/.17;return {'spine':1-t,'chest':t}
    return {'chest':1}
def add_box(name,center,size,ma,weights,bevel=0):
    # Chamfered 8-sided extrusion; useful for glove thumbs, pockets and boot details.
    x,y,z=center;rx,ry,rz=[a/2 for a in size]
    b=min(bevel,rx*.4,ry*.4)
    corners=[(-rx+b,-ry),(rx-b,-ry),(rx,-ry+b),(rx,ry-b),(rx-b,ry),(-rx+b,ry),(-rx,ry-b),(-rx,-ry+b)] if b else [(-rx,-ry),(rx,-ry),(rx,ry),(-rx,ry)]
    rings=[[vert((x+xx,y+yy,z+zz),weights) for xx,yy in corners] for zz in [-rz,rz]]
    bridge(*rings,ma);cap(rings[0],ma,True);cap(rings[1],ma)

# Continuous sewn shirt: shared torso/armhole vertices, no intersecting shoulder caps.
torso_dims=[(.945,.158,.098),(.995,.171,.108),(1.12,.180,.112),(1.30,.211,.116),(1.455,.226,.108),(1.50,.140,.080),(1.535,.061,.061)]
tr=[ring_xy(z,rx,ry,weights=torso_weights(z)) for z,rx,ry in torso_dims]
for k in range(len(tr)-1):bridge(tr[k],tr[k+1],'shirt',skip=[14,15,0,1,6,7,8,9] if k==3 else [])
cap(tr[0],'shirt',True);cap(tr[-1],'shirt')
torso_faces=list(F)
def limb_ring(center,axis,rx,ry,n,weights):
    axis=Vector(axis).normalized();u=Vector((0,1,0));u=(u-axis*u.dot(axis)).normalized();v=axis.cross(u).normalized()
    return [vert(Vector(center)+u*math.cos(j*2*math.pi/n)*ry+v*math.sin(j*2*math.pi/n)*rx,weights) for j in range(n)]
armhole_edges=[]
for side,s in [('L',1),('R',-1)]:
    arc=[14,15,0,1,2] if s==1 else [10,9,8,7,6]
    hole=[tr[3][j] for j in arc]+[tr[4][j] for j in reversed(arc)]
    armhole_edges.extend(tuple(sorted((a,b))) for a,b in zip(hole,hole[1:]+hole[:1]))
    angles=[math.atan2(V[i][2]-1.3775,V[i][1]) for i in hole]
    specs=[((s*.245,0,1.374),(s*.85,0,-.53),.079,.085,{'chest':.30,'upper_arm.'+side:.70}),
           ((s*.281,-.002,1.291),(s*.40,0,-.916),.071,.076,{'upper_arm.'+side:1}),
           ((s*.313,-.01,1.170),(s*.29,-.035,-1),.064,.067,{'upper_arm.'+side:.65,'forearm.'+side:.35}),
           ((s*.335,-.018,1.092),(s*.29,-.035,-1),.059,.062,{'upper_arm.'+side:.15,'forearm.'+side:.85}),
           ((s*.365,-.028,.993),(s*.29,-.035,-1),.050,.053,{'forearm.'+side:1}),
           ((s*.385,-.032,.943),(s*.29,-.035,-1),.044,.046,{'forearm.'+side:1})]
    rings=[]
    for c,axis,rx,ry,w in specs:
        axis=Vector(axis).normalized();u=Vector((0,1,0));u=(u-axis*u.dot(axis)).normalized();v=axis.cross(u).normalized()*s
        rings.append([vert(Vector(c)+u*math.cos(a)*ry+v*math.sin(a)*rx,w) for a in angles])
    bridge(hole,rings[0],'shirt')
    for a,b in zip(rings,rings[1:]):bridge(a,b,'shirt')
    cap(rings[-1],'shirt')
    cuff1=limb_ring((s*.382,-.031,.956),(s*.29,-.035,-1),.046,.048,10,{'forearm.'+side:1})
    cuff2=limb_ring((s*.390,-.033,.931),(s*.29,-.035,-1),.046,.048,10,{'hand.'+side:.2,'forearm.'+side:.8})
    bridge(cuff1,cuff2,'edge');cap(cuff1,'edge',True);cap(cuff2,'edge')
    # Rounded polygonal mittens with a separate thumb; no tiny finger artifacts.
    glove_start=len(V)
    gloves=[]
    for z,x,rx,ry in [(.943,.387,.042,.040),(.917,.396,.044,.044),(.865,.408,.039,.042),(.836,.411,.026,.033)]:
        gloves.append(limb_ring((s*x,-.034,z),(s*.25,0,-1),rx,ry,10,{('fingers.' if z<.89 else 'hand.')+side:1}))
    for a,b in zip(gloves,gloves[1:]):bridge(a,b,'glove')
    cap(gloves[0],'glove',True);cap(gloves[-1],'glove')
    add_box('Thumb',(s*.371,-.064,.889),(.032,.045,.061),'glove',{'thumb.'+side:1},.009)
    wrist=Vector((s*.389,-.033,.943))
    for i in range(glove_start,len(V)):V[i]=tuple(wrist+(Vector(V[i])-wrist)*1.14)

# Pants: level hip loops, symmetric crotch seam, gradual pelvis-to-thigh skinning.
pants_start=len(V);pants_faces_start=len(F)
waist=ring_xy(.992,.170,.110)
upperhip=ring_xy(.945,.183,.118)
hip=ring_xy(.880,.186,.119)
bridge(waist,upperhip,'trousers');bridge(upperhip,hip,'trousers')
crotch=[vert((0,y,z),{'hips':1}) for y,z in [(.112,.790),(.097,.780),(.057,.774),(0,.770),(-.057,.774),(-.097,.780),(-.112,.790)]]
for side,s in [('L',1),('R',-1)]:
    outer=[hip[i%16] for i in (range(12,21) if s==1 else range(12,3,-1))]
    # Both outer half-loops end at the back. Both must then traverse back -> front.
    top=outer+crotch
    prev=top
    for z,rx,ry,cy in [(.735,.090,.101,-.002),(.68,.085,.095,-.008),(.63,.080,.088,-.015),(.55,.073,.078,-.025),(.49,.072,.077,-.022),(.40,.067,.072,-.009),(.28,.061,.068,.005),(.185,.055,.062,.010),(.16,.054,.061,.010)]:
        if z>=.70:
            t=(.88-z)/(.88-.68);w={'hips':1-t,'thigh.'+side:t}
        elif z>=.63:w={'thigh.'+side:1}
        elif z>=.49:
            t=(.63-z)/.14;w={'thigh.'+side:1-t,'shin.'+side:t}
        else:w={'shin.'+side:1}
        rr=ring_xy(z,rx,ry,c=(s*.097,cy),weights=w,angle=-math.pi/2,direction=s)
        if z>=.72:
            exponent=.70
            for vi in rr:
                xx,yy,zz=V[vi];u=(yy-cy)/ry
                V[vi]=(xx,cy+math.copysign(abs(u)**exponent,u)*ry,zz)
        bridge(prev,rr,'trousers');prev=rr
    cap(prev,'trousers',True)
cap(waist,'trousers')
pants_faces=F[pants_faces_start:]
for side,s in [('L',1),('R',-1)]:
    add_box('Cargo pocket',(s*.180,.006,.715),(.022,.129,.145),'pocket',{'thigh.'+side:1},.006)
    add_box('Pocket flap',(s*.184,.006,.776),(.027,.137,.029),'trousers',{'thigh.'+side:1},.004)

# Boot shape: low wedge toe, defined ankle, two clean sole layers.
outline=[(-.043,-.178),(.043,-.178),(.067,-.158),(.074,-.096),(.068,.057),(.055,.103),(.033,.116),(-.033,.116),(-.055,.103),(-.068,.057),(-.074,-.096),(-.067,-.158)]
for side,s in [('L',1),('R',-1)]:
    w={'foot.'+side:1};cx=s*.097;boot_start=len(V)
    rs=[]
    for z,scale in [(.012,1.02),(.041,1.02),(.057,.98)]:
        rs.append([vert((cx+x*scale,y*scale,z),w) for x,y in outline])
    cap(rs[0],'sole',True)
    bridge(rs[0],rs[1],'sole');bridge(rs[1],rs[2],'edge')
    mid=[vert((cx+x*.96,y*.96,.106+max(0,y+.06)*.26),w) for x,y in outline]
    bridge(rs[2],mid,'boot')
    ankle=ring_xy(.226,.058,.066,c=(cx,.012),n=12,weights=w,angle=-math.pi/2-math.pi/12)
    bridge(mid,ankle,'boot');cap(ankle,'boot')
    # Toe cap is a broad visible material patch, not a high-poly attachment.
    add_box('Boot toe guard',(cx,-.139,.095),(.111,.068,.029),'edge',w,.008)
    for i in range(boot_start,len(V)):
        x,y,z=V[i]
        # Keep the ankle opening broad enough for the existing trouser hem.
        t=max(0,min(1,(z-.12)/.106));sx=.85+.15*t;sy=.85+.15*t
        V[i]=(cx+(x-cx)*sx,.012+(y-.012)*sy,.012+(z-.012)*.84)


# Neck and deliberately featureless head, with human jaw/temple proportions.
neck=[ring_xy(z,rx,ry,c=(0,.009),n=12,weights={'neck':1}) for z,rx,ry in [(1.51,.049,.047),(1.59,.050,.046),(1.625,.056,.052)]]
for a,b in zip(neck,neck[1:]):bridge(a,b,'skin')
cap(neck[0],'skin',True);cap(neck[-1],'skin')
head=[]
for z,rx,ry,cy in [(1.595,.054,.057,-.012),(1.619,.075,.070,-.014),(1.666,.092,.083,-.008),(1.718,.100,.089,-.004),(1.767,.098,.088,.001),(1.809,.078,.071,.003),(1.835,.036,.036,.003)]:
    head.append(ring_xy(z,rx,ry,c=(0,cy),n=12,weights={'head':1},angle=math.pi/12))
for a,b in zip(head,head[1:]):bridge(a,b,'skin')
cap(head[0],'skin',True);cap(head[-1],'skin')

# Short swept hair, built as a designed shell. No eyes, ears, nose or mouth.
hair=[]
for row in range(4):
    rr=[]
    for j in range(16):
        a=2*math.pi*j/16;front=max(0,-math.sin(a));back=max(0,math.sin(a))
        if row==0:
            x=.103*math.cos(a);y=.094*math.sin(a)+.003;z=1.715+.066*front-.035*back
            if front>.7:z+=.008*math.cos(a)
        elif row==1:x=.111*math.cos(a);y=.096*math.sin(a)+.005;z=1.796+.012*math.cos(a)
        elif row==2:x=.078*math.cos(a)-.007;y=.070*math.sin(a)+.009;z=1.845+.010*math.cos(a)
        else:x=.025*math.cos(a)-.012;y=.025*math.sin(a)+.010;z=1.858+.003*math.cos(a)
        rr.append(vert((x,y,z),{'head':1}))
    hair.append(rr)
for a,b in zip(hair,hair[1:]):bridge(a,b,'hair')
cap(hair[0],'hair',True);cap(hair[-1],'hair')

# Safety helmet follows the existing head bone in every unchanged action.
sys.path.insert(0,str(ROOT/'scripts'))
from flexsim_character_palette import helmet_geometry
helmet_vertices,helmet_faces=helmet_geometry()
helmet_offset=len(V)
for point in helmet_vertices:vert(point,{'head':1})
for triangle in helmet_faces:face([helmet_offset+i for i in triangle],'helmet')

# Open-front safety vest. Each panel follows the underlying faceted shirt.
def shirt_dims(z):
    for (a,ax,ay),(b,bx,by) in zip(torso_dims,torso_dims[1:]):
        if a<=z<=b:
            t=(z-a)/(b-a);return ax*(1-t)+bx*t,ay*(1-t)+by*t
    return torso_dims[-1][1:]
def vest_point(x,z,front=True,extra=0):
    rx,ry=shirt_dims(z);x=max(-rx*.96,min(rx*.96,x))
    # Linear interpolation on the shirt's polygon, avoiding penetration at facets.
    pts=[(rx*math.cos(j*2*math.pi/16),ry*math.sin(j*2*math.pi/16)) for j in range(16)]
    half=sorted((px,abs(py)) for px,py in pts if (py<=1e-6 if front else py>=-1e-6))
    depth=ry
    for (xa,ya),(xb,yb) in zip(half,half[1:]):
        if xa<=x<=xb and xb-xa>1e-8:depth=ya+(yb-ya)*(x-xa)/(xb-xa);break
    actual=surface_y(x,z,torso_faces,front)
    if actual is not None:depth=abs(actual)
    return (x,(-1 if front else 1)*(depth+.012+extra),z)
def surface_y(x,z,triangles,front):
    ys=[]
    for ids in triangles:
        a,b,c=[V[i] for i in ids]
        det=(b[2]-c[2])*(a[0]-c[0])+(c[0]-b[0])*(a[2]-c[2])
        if abs(det)<1e-10:continue
        u=((b[2]-c[2])*(x-c[0])+(c[0]-b[0])*(z-c[2]))/det
        v=((c[2]-a[2])*(x-c[0])+(a[0]-c[0])*(z-c[2]))/det
        w=1-u-v
        if min(u,v,w)>=-1e-6:ys.append(a[1]*u+b[1]*v+c[1]*w)
    return (min(ys) if front else max(ys)) if ys else None
def vest_face(ids):
    # Cut reflective bands into the cloth topology itself: no floating overlays.
    def clip(poly,axis,value,keep_low):
        result=[]
        for a,b in zip(poly,poly[1:]+poly[:1]):
            da=a[0][axis]-value;db=b[0][axis]-value
            ina=da<=1e-10 if keep_low else da>=-1e-10
            inb=db<=1e-10 if keep_low else db>=-1e-10
            if ina:result.append(a)
            if ina!=inb:
                t=da/(da-db);co=a[0].lerp(b[0],t)
                weights={k:a[1].get(k,0)*(1-t)+b[1].get(k,0)*t for k in set(a[1])|set(b[1])}
                result.append((co,weights))
        cleaned=[]
        for p in result:
            if not cleaned or (p[0]-cleaned[-1][0]).length>1e-8:cleaned.append(p)
        if len(cleaned)>1 and (cleaned[0][0]-cleaned[-1][0]).length<1e-8:cleaned.pop()
        return cleaned
    a,b,c,d=ids
    for tri in [(a,b,c),(a,c,d)]:
        pieces=[[(Vector(V[i]),W[i]) for i in tri]]
        for axis,cut in [(0,-.139),(0,-.111),(0,.111),(0,.139),(0,.149),(0,.184),(2,1.255),(2,1.310),(2,1.095),(2,1.127),(2,1.15),(2,1.445)]:
            new=[]
            for poly in pieces:
                if min(p[0][axis] for p in poly)<cut-1e-9 and max(p[0][axis] for p in poly)>cut+1e-9:
                    new.extend(p for p in [clip(poly,axis,cut,True),clip(poly,axis,cut,False)] if len(p)>=3)
                else:new.append(poly)
            pieces=new
        for poly in pieces:
            co=sum((p[0] for p in poly),Vector())/len(poly)
            reflective=(1.095<=co.z<=1.127) or (.111<=abs(co.x)<=.139 and 1.15<=co.z)
            pocket=(.149<=co.x<=.184 and 1.255<=co.z<=1.310 and co.y<0)
            indices=[vert(p,w) for p,w in poly]
            for j in range(1,len(indices)-1):
                aa,bb,cc=[Vector(V[i]) for i in [indices[0],indices[j],indices[j+1]]]
                if (bb-aa).cross(cc-aa).length>1e-12:face([indices[0],indices[j],indices[j+1]],'edge' if pocket else ('tape' if reflective else 'vest'))
def surface_z(x,y,triangles):
    zs=[]
    for ids in triangles:
        a,b,c=[V[i] for i in ids]
        det=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(det)<1e-10:continue
        u=((b[1]-c[1])*(x-c[0])+(c[0]-b[0])*(y-c[1]))/det
        v=((c[1]-a[1])*(x-c[0])+(a[0]-c[0])*(y-c[1]))/det
        w=1-u-v
        if min(u,v,w)>=-1e-6:zs.append(a[2]*u+b[2]*v+c[2]*w)
    return max(zs) if zs else 1.49
vest_faces_start=len(F)
vest_join_pairs=[]
for s in [-1,1]:
    panels={}
    for front in [True,False]:
        rows=[]
        for z,inner,outer in [(1.002,.012,.163),(1.12,.012,.179),(1.27,.013,.203),(1.37,.040,.183),(1.455,.065,.162),(1.49,.075,.150)]:
            xs=[inner+(outer-inner)*u for u in [0,.25,.5,.75,1]] if front else [outer*u for u in [0,.5,.625,.75,.875,1]]
            rows.append([vert(vest_point(s*x,z,front),torso_weights(z)) for x in xs])
        panels[front]=rows
        for rowa,rowb in zip(rows,rows[1:]):
            for j in range(len(rowa)-1):vest_face([rowa[j],rowa[j+1],rowb[j+1],rowb[j]])
        if front:
            for k in range(len(rows)-1):
                a=Vector(V[rows[k][0]]);b=Vector(V[rows[k+1][0]])
                aa=vert(a+Vector((s*.005,-.0015,0)),torso_weights(a.z));bb=vert(b+Vector((s*.005,-.0015,0)),torso_weights(b.z))
                face([rows[k][0],aa,bb,rows[k+1][0]],'edge')
    # Actual side fabric joins the front and rear, ending under the armhole.
    side_rows=[]
    for k in range(3):
        left=panels[True][k][-1];right=panels[False][k][-1];z=V[left][2]
        side_rows.append([left,vert((s*(shirt_dims(z)[0]+.014),0,z),torso_weights(z)),right])
    for a,b in zip(side_rows,side_rows[1:]):
        for j in range(2):vest_face([a[j],a[j+1],b[j+1],b[j]])
    # Curved shoulder straps follow the top of the shirt and share both panel edges.
    front=panels[True][-1];back=panels[False][-1][1:]
    strap_rows=[front]
    for t in [.2,.4,.6,.8]:
        rr=[]
        for a,b in zip(front,back):
            p=Vector(V[a]).lerp(Vector(V[b]),t)
            p.z=max(p.z,surface_z(p.x,p.y,torso_faces)+.010)
            rr.append(vert(p,{'chest':1}))
        strap_rows.append(rr)
    strap_rows.append(back)
    for a,b in zip(strap_rows,strap_rows[1:]):
        for j in range(4):vest_face([a[j],a[j+1],b[j+1],b[j]])
vest_surface_faces=F[vest_faces_start:]
# Weld exact shared edges, retaining weights. This makes the tailored joins structural.
welded={};remap={};newv=[];neww=[]
for i,(v,w) in enumerate(zip(V,W)):
    clean={k:val for k,val in w.items() if val>1e-9}
    key=(tuple(round(a,8) for a in v),tuple(sorted((k,round(val,8)) for k,val in clean.items())))
    if key not in welded:
        welded[key]=len(newv);newv.append(v);neww.append(clean)
    remap[i]=welded[key]
F=[[remap[i] for i in f] for f in F]
V,W=newv,neww

# Build one skinned mesh; disconnected clothing layers intentionally share a rig.
mesh=bpy.data.meshes.new('WORKER_Original_LowPoly_Geometry');mesh.from_pydata(V,[],F);mesh.update()
for m in materials:mesh.materials.append(m)
for p,matid in zip(mesh.polygons,FM):p.material_index=matid;p.use_smooth=False
bm=bmesh.new();bm.from_mesh(mesh);bmesh.ops.recalc_face_normals(bm,faces=bm.faces);bm.to_mesh(mesh);bm.free()
body=link(bpy.data.objects.new('WORKER_Body',mesh))
body['asset_id']='warehouse_worker';body['faceless']=True;body['shading']='authored flat triangles';body['original_geometry']=True

# Deform rig in an A pose; all weights are explicit and reproducible.
adata=bpy.data.armatures.new('WORKER_DeformSkeleton');rig=link(bpy.data.objects.new('WORKER_Rig',adata))
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
motion_extra_bones=[]
for side,sign in [('L',1),('R',-1)]:
    motion_extra_bones.extend([
      ('fingers.'+side,(sign*.402,-.034,.891),(sign*.417,-.036,.816),'hand.'+side),
      ('thumb.'+side,(sign*.380,-.056,.930),(sign*.365,-.065,.851),'hand.'+side)])
supplement_bones(bone,motion_extra_bones)
bpy.ops.object.mode_set(mode='OBJECT')
for b in adata.bones:
    b.use_deform=b.name!='root'
for name in bones:
    g=body.vertex_groups.new(name=name)
    for i,w in enumerate(W):
        if w.get(name,0)>1e-8:g.add([i],w[name],'REPLACE')
mod=body.modifiers.new('WORKER_Skeletal_Deformation','ARMATURE');mod.object=rig
body.parent=rig
clips,grip_manifest=create_motion(rig,body,col,link,'worker',motion_extra_bones)
def reset():reset_pose(rig)

# Export at origin in A pose. NLA actions become independent named GLB clips.
rig.animation_data.action=None;reset();sc.frame_set(1)
for track in rig.animation_data.nla_tracks:track.mute=False
bpy.ops.object.select_all(action='DESELECT')
for ob in col.objects:ob.select_set(True)
bpy.context.view_layer.objects.active=rig
export_meshes=[o for o in col.objects if o.type=='MESH']
for o in export_meshes:o.parent=None
bpy.ops.export_scene.gltf(filepath=str(OUT/'modules/warehouse_worker.glb'),export_format='GLB',use_selection=True,export_yup=True,export_extras=True,export_animations=True,export_animation_mode='NLA_TRACKS',export_nla_strips=True,export_force_sampling=True,export_frame_range=False,export_skins=True,export_def_bones=False,export_cameras=False,export_lights=False)
for o in export_meshes:o.parent=rig
for track in rig.animation_data.nla_tracks:track.mute=True
rig.animation_data.action=bpy.data.actions['Worker_Idle'];sc.frame_set(1)

# Scene placement: clear floor beside the second packing bench, facing the camera.
rig.location=(1.8,1.30,0);rig.rotation_euler=(0,0,0)
rig['asset_type']='warehouse_worker';rig['asset_file']='modules/warehouse_worker.glb'
rig['animation_role']='worker';rig['placement_note']='idle display beside packing station; not yet production simulation'
worker_manifest={
 'id':'warehouse_worker','version':'0.2.2','file':'modules/warehouse_worker.glb',
 'units':'meters','forward':'Blender -Y / glTF +Z','origin':'floor / midpoint between feet',
 'height_rest_m':max(v[2] for v in V),'triangles':len(mesh.polygons),'authored_vertices':len(mesh.vertices),
 'materials':len(materials),'bones':len(adata.bones),'faceless':True,'flat_shaded':True,
 'clothing':['long sleeve work shirt','sleeveless ochre safety vest','silver bands','cargo trousers','protective gloves','safety boots'],
 'box_handling':grip_manifest,'clips':clips,'attachments':['ATTACH_WORKER_HAND_L','ATTACH_WORKER_HAND_R'],
 'scene_position_blender_m':list(rig.location),'scene_position_gltf_m':[1.8,0,-1.30],
 'reference':{'url':'https://sketchfab.com/3d-models/stylized-low-poly-office-worker-2dd032b43561407e8523173aeb15065d','author':'DimLitStudio','use':'visual style reference only; all geometry authored independently','reference_triangles':3886},
 'simulation_status':'display/animation asset; task scheduling and production logic not connected',
}
lo=[min(v[i] for v in V) for i in range(3)];hi=[max(v[i] for v in V) for i in range(3)]
worker_manifest['bounds_blender_rest_m']={'min':lo,'max':hi,'size':[hi[i]-lo[i] for i in range(3)]}
(OUT/'worker_manifest.json').write_text(json.dumps(worker_manifest,ensure_ascii=False,indent=2))
(ROOT/'config/characters/warehouse_worker.json').write_text(json.dumps(worker_manifest,ensure_ascii=False,indent=2))
manifest_path=OUT/'asset_manifest.json'
if manifest_path.exists():
    manifest=json.loads(manifest_path.read_text());manifest=[a for a in manifest if a['id']!='warehouse_worker']
    manifest.append({'id':'warehouse_worker','file':'modules/warehouse_worker.glb','bounds_min_m':lo,'bounds_max_m':hi,'actual_envelope_m':[hi[i]-lo[i] for i in range(3)],'origin':'floor-center / Blender Z-up','rigged':True,'bones':len(adata.bones),'clips':[c['name'] for c in clips]})
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
report_path=OUT/'geometry_report.json'
if report_path.exists():
    report=json.loads(report_path.read_text());report['people']=1;report['robots']=int(any(o.get('robot_asset') for o in sc.objects))
    report['character_report']='worker_geometry_report.json';report['character_triangles']=len(mesh.polygons)
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2))

# Structural QA: no zero-area triangles, no unweighted points, exact normalized skinning.
bad_faces=[p.index for p in mesh.polygons if p.area<1e-12]
bad_weights=[i for i,w in enumerate(W) if abs(sum(w.values())-1)>1e-5 or not w]
invalid=[i for i,v in enumerate(V) if not all(math.isfinite(c) for c in v)]
assert not bad_faces,bad_faces;assert not bad_weights,bad_weights;assert not invalid,invalid
# Check the sewn shirt and pants as surfaces, beyond file-format validity.
def surface_topology(material_names,selected=None):
    if selected is None:selected=[f for f,m in zip(F,FM) if m in {mi[name] for name in material_names}]
    edges={};adj={}
    for f in selected:
        for a,b in zip(f,f[1:]+f[:1]):
            edges[tuple(sorted((a,b)))]=edges.get(tuple(sorted((a,b))),0)+1
            adj.setdefault(a,set()).add(b);adj.setdefault(b,set()).add(a)
    pending=set(adj);components=0
    while pending:
        components+=1;stack=[pending.pop()]
        while stack:
            a=stack.pop()
            for b in adj[a]&pending:pending.remove(b);stack.append(b)
    return {'components':components,'boundary_edges':sum(n==1 for n in edges.values()),'nonmanifold_edges':sum(n>2 for n in edges.values())}
shirt_check=surface_topology(['shirt']);pants_check=surface_topology(['trousers'])
vest_check=surface_topology([],F[vest_faces_start:]);assert vest_check['components']==1,vest_check
assert shirt_check=={'components':1,'boundary_edges':0,'nonmanifold_edges':0},shirt_check
assert pants_check['boundary_edges']==0 and pants_check['nonmanifold_edges']==0,pants_check
qa={'vest_topology':vest_check,'shirt_topology':shirt_check,'pants_topology':pants_check,'passed':True,'triangles':len(mesh.polygons),'vertices':len(mesh.vertices),'bones':len(adata.bones),'zero_area_triangles':bad_faces,'bad_skin_weights':bad_weights,'invalid_vertices':invalid,'reference_mesh_downloaded':False}
(OUT/'worker_geometry_report.json').write_text(json.dumps(qa,indent=2))
bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
print('WORKER_SAVED',json.dumps(qa),flush=True)

if opt.render or opt.motion_only or opt.back_only or opt.quick:
    # Temporary portrait stage; warehouse and its lighting are restored afterwards.
    saved_camera=sc.camera;saved_world=sc.world;saved_frame=sc.frame_current
    saved_location=rig.location.copy();rig.location=(0,0,0)
    hidden={o:o.hide_render for o in sc.objects if o.name not in col.objects}
    for ob in hidden:ob.hide_render=True
    stage=bpy.data.collections.new('WORKER_PORTRAIT_STAGE');sc.collection.children.link(stage)
    def stage_link(ob):stage.objects.link(ob);return ob
    mat=bpy.data.materials.new('Worker portrait / sage backdrop');mat.diffuse_color=(.105,.145,.14,1);mat.use_nodes=True
    mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=(.105,.145,.14,1)
    mat.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value=.94
    plane=bpy.data.meshes.new('Worker portrait floor');plane.from_pydata([(-200,-200,-.001),(200,-200,-.001),(200,200,-.001),(-200,200,-.001)],[],[(0,1,2,3)]);plane.materials.append(mat)
    stage_link(bpy.data.objects.new('Worker portrait floor',plane))
    world=bpy.data.worlds.new('Worker portrait world');world.use_nodes=True;world.node_tree.nodes['Background'].inputs[0].default_value=(.30,.37,.35,1);world.node_tree.nodes['Background'].inputs[1].default_value=.48;sc.world=world
    def area(name,pos,power,size):
        d=bpy.data.lights.new(name,'AREA');d.energy=power;d.shape='DISK';d.size=size
        ob=stage_link(bpy.data.objects.new(name,d));ob.location=pos;ob.rotation_euler=(Vector((0,0,1))-ob.location).to_track_quat('-Z','Y').to_euler()
    area('Portrait key',(-3,-4,5),420,4);area('Portrait fill',(3,-2,3),160,3);area('Portrait rim',(1,3,4),470,3)
    d=bpy.data.cameras.new('Worker portrait camera');cam=stage_link(bpy.data.objects.new('Worker portrait camera',d));d.type='ORTHO';d.ortho_scale=2.32;sc.camera=cam
    sc.render.engine='CYCLES';sc.cycles.samples=192;sc.cycles.use_denoising=False
    sc.render.resolution_x=1000;sc.render.resolution_y=1200;sc.render.resolution_percentage=100
    if opt.quick:sc.cycles.samples=48;sc.render.resolution_x=650;sc.render.resolution_y=780
    sc.view_settings.view_transform='AgX';sc.view_settings.look='AgX - Medium High Contrast'
    def render(name,pos,target=(0,0,.94),action='Worker_Idle',frame=1):
        rig.animation_data.action=bpy.data.actions[action];sc.frame_set(frame)
        cam.location=pos;cam.rotation_euler=(Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler()
        sc.render.filepath=str(OUT/name);bpy.ops.render.render(write_still=True)
    if opt.quick:
        render('worker_check_front.png',(3,-6,2.65))
        render('worker_check_back.png',(-3,6,2.55))
        d.ortho_scale=.72
        render('worker_check_hips.png',(1,-5,1.6),target=(0,0,.84))
    elif opt.back_only:
        render('worker_back.png',(-3,6,2.55))
    elif opt.motion_only:
        sc.cycles.samples=96;sc.render.resolution_x=750;sc.render.resolution_y=900
        render('worker_walk.png',(3,-6,2.65),action='Worker_Walk',frame=8)
        render('worker_reach.png',(3,-6,2.65),action='Worker_Reach',frame=36)
    else:
        render('worker_preview.png',(3,-6,2.65))
        render('worker_front.png',(0,-6,1.6))
        render('worker_back.png',(-3,6,2.55))
        render('worker_carry.png',(3,-6,2.65),action='Worker_CarryIdle')
        sc.cycles.samples=96;sc.render.resolution_x=800;sc.render.resolution_y=960
        render('worker_walk.png',(3,-6,2.65),action='Worker_Walk',frame=8)
        render('worker_reach.png',(3,-6,2.65),action='Worker_Reach',frame=36)
        d.ortho_scale=.98
        render('worker_shoulders.png',(2,-4,3.3),target=(0,0,1.34))
        d.ortho_scale=.72
        render('worker_hips.png',(1,-5,1.6),target=(0,0,.84))
    # Restore the native project; portrait objects never enter the saved scene.
    for ob,val in hidden.items():ob.hide_render=val
    for ob in list(stage.objects):bpy.data.objects.remove(ob,do_unlink=True)
    bpy.data.collections.remove(stage);sc.camera=saved_camera;sc.world=saved_world
    rig.location=saved_location;rig.animation_data.action=bpy.data.actions['Worker_Idle'];sc.frame_set(saved_frame)
    sc.render.resolution_x=1680;sc.render.resolution_y=1120;sc.cycles.samples=256;sc.cycles.use_denoising=False
    sc.view_settings.look='AgX - Medium Low Contrast';sc.render.filepath=str(OUT/'environment_overview.png')
    bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    if not opt.motion_only and not opt.quick:bpy.ops.render.render(write_still=True)
print('WORKER_BUILD_COMPLETE',flush=True)
