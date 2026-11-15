"""Batch static meshes directly, without operator undo/dependency-graph overhead."""
import bpy, math, gc, collections, sys, argparse
from pathlib import Path
from mathutils import Vector

def independent_motion(obj,root):
    while obj and obj!=root:
        if obj.get('dynamic',False):return True
        obj=obj.parent
    return False

def export_optimized(output,render=False,details=False):
    output=Path(output);bpy.context.preferences.edit.use_global_undo=False
    bpy.context.view_layer.update()
    roots=[o for o in bpy.data.objects if o.type=='EMPTY' and o.parent is None]
    for root in roots:
        buckets=collections.defaultdict(list)
        for ob in root.children_recursive:
            if ob.type=='MESH' and not independent_motion(ob,root):
                buckets[ob.data.materials[0].name if ob.data.materials else 'none'].append(ob)
        for name,obs in buckets.items():
            if len(obs)<2:continue
            vertices=[];faces=[];normals=[];smoothing=[]
            material=obs[0].data.materials[0] if obs[0].data.materials else None
            for ob in obs:
                mesh=ob.data;matrix=root.matrix_world.inverted()@ob.matrix_world
                nmat=matrix.to_3x3().inverted().transposed();offset=len(vertices)
                vertices.extend(tuple(matrix@v.co) for v in mesh.vertices)
                faces.extend(tuple(i+offset for i in p.vertices) for p in mesh.polygons)
                smoothing.extend(p.use_smooth for p in mesh.polygons)
                normals.extend(tuple((nmat@n.vector).normalized()) for n in mesh.corner_normals)
            mesh=bpy.data.meshes.new(root.name+'_'+name+'_batch')
            mesh.from_pydata(vertices,[],faces);mesh.update()
            if material:mesh.materials.append(material)
            for p,smooth in zip(mesh.polygons,smoothing):p.use_smooth=smooth
            if len(normals)==len(mesh.loops):mesh.normals_split_custom_set(normals)
            ob=bpy.data.objects.new(root.name+'__'+name.replace(' ','_'),mesh)
            bpy.context.scene.collection.objects.link(ob);ob.parent=root
            for old in obs:bpy.data.objects.remove(old,do_unlink=True)
            del vertices,faces,normals,smoothing
        print('BATCHED',root.name,flush=True)
        gc.collect()
    bpy.data.orphans_purge(do_recursive=True)
    bpy.ops.object.select_all(action='DESELECT')
    for ob in bpy.data.objects:
        if ob.type in ['MESH','EMPTY']:ob.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(output/'warehouse_environment.glb'),export_format='GLB',use_selection=True,export_yup=True,export_apply=True,export_extras=True,export_animations=False,export_cameras=False,export_lights=False)
    print('ENVIRONMENT_GLB_EXPORTED',flush=True)
    if render:
        bpy.context.scene.render.filepath=str(output/'environment_overview.png')
        bpy.ops.render.render(write_still=True)
    if details:
        from render_details import render_details
        render_details(output)
    print('OPTIMIZATION_COMPLETE',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--render',action='store_true')
    args=p.parse_args(sys.argv[sys.argv.index('--')+1:])
    export_optimized(args.output,args.render)
