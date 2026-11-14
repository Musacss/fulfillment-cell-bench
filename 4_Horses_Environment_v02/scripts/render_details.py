"""Render the native source with the same original cameras, without GPU dependencies."""
import bpy,sys,argparse
from pathlib import Path
def render_details(out):
    out=Path(out);sc=bpy.context.scene;sc.cycles.use_denoising=False;sc.cycles.samples=128
    sc.render.resolution_x=1440;sc.render.resolution_y=1080
    sc.view_settings.look='AgX - Medium Low Contrast'
    for name,file in [('CAMERA_CONVEYOR','detail_conveyor.png'),('CAMERA_PACK','detail_packing.png'),('CAMERA_STORAGE','detail_storage.png')]:
        sc.camera=bpy.data.objects[name];sc.render.filepath=str(out/file)
        bpy.ops.render.render(write_still=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True)
    args=p.parse_args(sys.argv[sys.argv.index('--')+1:])
    render_details(args.output)
