"""Rebake the existing native visual replay using the shared scene configuration."""
import bpy,math,json
from pathlib import Path
cfg=json.loads((Path(__file__).resolve().parent.parent/'config/environment.json').read_text())['demo']
start,end,stop,speed,dwell,cycle,count=[cfg[k] for k in ['start_x','end_x','stop_x','speed_mps','inspection_stop_seconds','cycle_seconds','carton_count']]
sc=bpy.context.scene;arrival=(stop-start)/speed;frames=cycle*30
def smooth(x):
    x=max(0,min(1,x));return x*x*(3-2*x)
for i in range(count):
    o=bpy.data.objects['DEMO_PARCEL_%02d'%(i+1)]
    for frame in range(1,frames+1):
        age=((frame-1)/30+i*cycle/count)%cycle
        travel=age if age<arrival else arrival if age<arrival+dwell else age-dwell
        o.location.x=min(end,start+travel*speed)
        o.hide_render=age>(end-start)/speed+dwell
        o.keyframe_insert(data_path='location',index=0,frame=frame)
        o.keyframe_insert(data_path='hide_render',frame=frame)
    for fc in o.animation_data.action.fcurves:
        for k in fc.keyframe_points:k.interpolation='CONSTANT' if fc.data_path=='hide_render' else 'LINEAR'
gate=bpy.data.objects['STOPPER_GATE']
for frame in range(1,frames+1):
    t=(frame-1)/30;lift=0
    for i in range(count):
        age=(t+i*cycle/count)%cycle
        if arrival-.8<=age<arrival+dwell:
            lift=max(lift,min(smooth((age-(arrival-.8))/.25),1-smooth((age-(arrival+dwell-.25))/.25)))
    gate.location.z=.805+.085*lift;gate.keyframe_insert(data_path='location',index=2,frame=frame)
sc.frame_end=frames;sc.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
