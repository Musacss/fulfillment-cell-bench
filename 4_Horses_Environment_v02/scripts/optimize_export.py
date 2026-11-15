"""Batch static meshes directly, without operator undo/dependency-graph overhead."""
import bpy, math, gc, collections, sys, argparse
import numpy as np
from pathlib import Path
from mathutils import Vector

def independent_motion(obj,root):
    while obj and obj!=root:
        if obj.get('dynamic',False):return True
        obj=obj.parent
    return False

def _excluded_from_env(obj):
    cur=obj
    while cur:
        if cur.get('integration_visual') or cur.get('worker_asset') or cur.get('robot_asset') or cur.type=='ARMATURE':
            return True
        cur=cur.parent
    return any(c.name.startswith(('CHARACTERS','INTEGRATION /')) for c in obj.users_collection)

def export_optimized(output,render=False,details=False):
    output=Path(output);bpy.context.preferences.edit.use_global_undo=False
    overhead_root=bpy.data.objects.get('ENV_OVERHEAD')
    overhead_desc=set(overhead_root.children_recursive) if overhead_root else set()
    allowed_arrows={'WALKWAY_DIRECTION_ARROW_01','WALKWAY_DIRECTION_ARROW_02','WALKWAY_DIRECTION_ARROW_03'}
    allowed_empty_lanes={'INBOUND_TRANSFER_LANE','DISPATCH_TRANSFER_LANE'}
    stale_overhead=[
        o for o in list(bpy.data.objects)
        if o!=overhead_root and o.type!='LIGHT' and not (o.type=='EMPTY' and o.name in allowed_empty_lanes) and (
            o in overhead_desc or o.name.startswith((
                'OVERHEAD_TRUSS','OVERHEAD_CABLE_TRAY','HIGH_BAY_LED','HIGHBAY_','ENV_LIGHTING_RIG',
                'Truss longitudinal chord','Truss diagonal web','High bay LED','High bay suspension','Cable tray ',
                'INBOUND_TRANSFER','DISPATCH_TRANSFER','REWORK_RETURN','SCRAP_TRANSFER','SPUR_TRANSFER','SPUR_GUIDE',
                'Walkway arrow',
            )) or ((
                'CHEVRON' in o.name.upper() or 'ARROW' in o.name.upper() or '_DASH' in o.name.upper()
                or 'TRANSFER_LANE' in o.name.upper() or 'RETURN_LANE' in o.name.upper()
                or ('BREAK' in o.name.upper() and ('LANE' in o.name.upper() or 'ARROW' in o.name.upper() or 'DASH' in o.name.upper()))
                or ('FLOW' in o.name.upper() and not o.get('integration_visual'))
            ) and o.name not in allowed_arrows)
        )
    ]
    if stale_overhead:bpy.data.batch_remove(stale_overhead)
    bpy.context.view_layer.update()
    roots=[o for o in bpy.data.objects if o.type=='EMPTY' and o.parent is None and not _excluded_from_env(o)]
    to_remove=[]
    for root in roots:
        buckets=collections.defaultdict(list)
        for ob in root.children_recursive:
            if ob.type=='MESH' and not independent_motion(ob,root) and not _excluded_from_env(ob):
                buckets[ob.data.materials[0].name if ob.data.materials else 'none'].append(ob)
        root_inv=root.matrix_world.inverted()
        for name,obs in buckets.items():
            if len(obs)<2:continue
            v_chunks=[];l_chunks=[];ls_chunks=[];lt_chunks=[];sm_chunks=[];n_chunks=[]
            v_off=0;l_off=0
            material=obs[0].data.materials[0] if obs[0].data.materials else None
            for ob in obs:
                mesh=ob.data
                nv=len(mesh.vertices);nl=len(mesh.loops);np_cnt=len(mesh.polygons)
                if nv==0 or np_cnt==0:continue
                mat=root_inv@ob.matrix_world
                m3=np.array(mat.to_3x3(),dtype=np.float64)
                tr=np.array(mat.translation,dtype=np.float64)
                nm3=np.array(mat.to_3x3().inverted().transposed(),dtype=np.float64)
                co=np.empty(nv*3,dtype=np.float32);mesh.vertices.foreach_get('co',co)
                co=(co.reshape(-1,3)@m3.T+tr).astype(np.float32)
                v_chunks.append(co.ravel())
                lv=np.empty(nl,dtype=np.int32);mesh.loops.foreach_get('vertex_index',lv)
                l_chunks.append(lv+v_off)
                ls=np.empty(np_cnt,dtype=np.int32);mesh.polygons.foreach_get('loop_start',ls)
                ls_chunks.append(ls+l_off)
                lt=np.empty(np_cnt,dtype=np.int32);mesh.polygons.foreach_get('loop_total',lt)
                lt_chunks.append(lt)
                sm=np.empty(np_cnt,dtype=bool);mesh.polygons.foreach_get('use_smooth',sm)
                sm_chunks.append(sm)
                cn=np.empty(nl*3,dtype=np.float32);mesh.corner_normals.foreach_get('vector',cn)
                cn=cn.reshape(-1,3)@nm3.T
                lens=np.linalg.norm(cn,axis=1,keepdims=True)
                cn=np.divide(cn,np.maximum(lens,1e-12)).astype(np.float32)
                n_chunks.append(cn)
                v_off+=nv;l_off+=nl
            if not v_chunks:continue
            all_v=np.concatenate(v_chunks);all_l=np.concatenate(l_chunks)
            all_ls=np.concatenate(ls_chunks);all_lt=np.concatenate(lt_chunks)
            all_sm=np.concatenate(sm_chunks);all_n=np.vstack(n_chunks)
            mesh=bpy.data.meshes.new(root.name+'_'+name+'_batch')
            mesh.vertices.add(len(all_v)//3);mesh.vertices.foreach_set('co',all_v)
            mesh.loops.add(len(all_l));mesh.loops.foreach_set('vertex_index',all_l)
            mesh.polygons.add(len(all_ls))
            mesh.polygons.foreach_set('loop_start',all_ls)
            mesh.polygons.foreach_set('loop_total',all_lt)
            mesh.polygons.foreach_set('use_smooth',all_sm)
            mesh.update(calc_edges=True)
            if material:mesh.materials.append(material)
            if len(all_n)==len(mesh.loops):mesh.normals_split_custom_set(all_n)
            ob=bpy.data.objects.new(root.name+'__'+name.replace(' ','_'),mesh)
            bpy.context.scene.collection.objects.link(ob);ob.parent=root
            to_remove.extend(obs)
        print('BATCHED',root.name,flush=True)
    if to_remove:bpy.data.batch_remove(to_remove)
    gc.collect()
    bpy.data.orphans_purge(do_recursive=True)
    bpy.ops.object.select_all(action='DESELECT')
    for ob in bpy.data.objects:
        if ob.type in ['MESH','EMPTY'] and not _excluded_from_env(ob):ob.select_set(True)
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
