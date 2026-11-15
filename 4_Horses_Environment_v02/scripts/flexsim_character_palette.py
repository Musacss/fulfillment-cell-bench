"""Recolor an existing worker and append a head-weighted safety helmet.

No bones, actions, NLA tracks, or grip transforms are changed. The helmet mesh uses
rig-local rest coordinates and the existing head deform group.
"""
import math

WORKER_PALETTE={
 'Deep petrol work shirt':('#0e4c92',.62,0),
 'Graphite blue cargo trousers':('#2b3137',.76,0),
 'Muted ochre safety vest':('#ffdf00',.57,0),
 'Satin silver reflective bands':('#e2e8ee',.32,.30),
 'Vest charcoal binding':('#242b32',.78,0),
 'Warm skin / featureless face':('#c68e66',.72,0),
 'Faceted dark brown hair':('#493427',.88,0),
 'Charcoal protective gloves':('#424c57',.82,0),
 'Graphite safety boot uppers':('#262e36',.80,0),
 'Rubber soles':('#161b20',.95,0),
 'Cargo pocket accents':('#3b4653',.78,0),
 'Safety yellow helmet':('#f4b400',.36,.03),
}

def srgb_hex(value):
    value=value.lstrip('#')
    channels=[int(value[i:i+2],16)/255 for i in (0,2,4)]
    return tuple(c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4 for c in channels)

def helmet_geometry():
    """A closed, faceted hard-hat shell with a brim; all points are worker rest-local."""
    verts=[];faces=[];n=16
    def ring(rx,ry,z,cy=.003):
        ids=[]
        for j in range(n):
            a=2*math.pi*j/n
            ids.append(len(verts));verts.append((rx*math.cos(a),cy+ry*math.sin(a),z))
        return ids
    def join(a,b,reverse=False):
        for j in range(n):
            face=(a[j],a[(j+1)%n],b[(j+1)%n],b[j])
            if reverse:face=face[::-1]
            faces.extend([(face[0],face[1],face[2]),(face[0],face[2],face[3])])
    # brim upper/lower rings, then the dome. Wider front gives useful face shade.
    r0=ring(.145,.160,1.782,-.011)
    r1=ring(.145,.160,1.790,-.011)
    r2=ring(.120,.113,1.802)
    r3=ring(.122,.115,1.840)
    r4=ring(.105,.100,1.886)
    r5=ring(.066,.063,1.924)
    r6=ring(.019,.018,1.941)
    for a,b in zip([r0,r1,r2,r3,r4,r5],[r1,r2,r3,r4,r5,r6]):join(a,b)
    top=len(verts);verts.append((0,.003,1.944))
    for j in range(n):faces.append((r6[j],r6[(j+1)%n],top))
    inner=ring(.112,.105,1.782)
    join(inner,r0)
    # Dome interior is a shallow closure above the wearer's head, concealed in use.
    cap=len(verts);verts.append((0,.003,1.787))
    for j in range(n):faces.append((inner[(j+1)%n],inner[j],cap))
    return verts,faces

def apply_character_palette(add_helmet=True):
    import bpy,bmesh
    for suffix,(value,rough,metal) in WORKER_PALETTE.items():
        name='Worker / '+suffix
        mat=bpy.data.materials.get(name)
        if mat is None:
            if suffix!='Safety yellow helmet':continue
            mat=bpy.data.materials.new(name)
        color=(*srgb_hex(value),1)
        mat.use_nodes=True;mat.diffuse_color=color
        shader=next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
        shader.inputs['Base Color'].default_value=color
        shader.inputs['Roughness'].default_value=rough
        shader.inputs['Metallic'].default_value=metal
    if not add_helmet:return None
    rig=bpy.data.objects.get('WORKER_Rig')
    if rig is None or rig.type!='ARMATURE' or 'head' not in rig.data.bones:
        raise RuntimeError('Cannot attach helmet: WORKER_Rig/head is missing')
    # Fresh build_worker incorporates the same geometry in WORKER_Body already.
    body=bpy.data.objects.get('WORKER_Body')
    if body and any(m and m.name=='Worker / Safety yellow helmet' for m in body.data.materials):
        return body
    old=bpy.data.objects.get('WORKER_Helmet')
    if old:bpy.data.objects.remove(old,do_unlink=True)
    vertices,faces=helmet_geometry()
    mesh=bpy.data.meshes.new('WORKER_Safety_Helmet_Geometry')
    mesh.from_pydata(vertices,[],faces);mesh.update()
    bm=bmesh.new();bm.from_mesh(mesh);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(mesh);bm.free()
    mesh.materials.append(bpy.data.materials['Worker / Safety yellow helmet'])
    helmet=bpy.data.objects.new('WORKER_Helmet',mesh)
    collection=next(iter(body.users_collection)) if body else bpy.context.scene.collection
    collection.objects.link(helmet);helmet.parent=rig
    helmet['worker_asset']=True;helmet['safety_equipment']='hard_hat';helmet['deform_bone']='head'
    group=helmet.vertex_groups.new(name='head');group.add(list(range(len(mesh.vertices))),1,'REPLACE')
    mod=helmet.modifiers.new('WORKER_Helmet_Head_Deformation','ARMATURE');mod.object=rig
    return helmet
