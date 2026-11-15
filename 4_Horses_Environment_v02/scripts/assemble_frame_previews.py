"""Encode Blender's existing PNG sequences as compact animated GIF previews."""
from pathlib import Path
from PIL import Image

out=Path(__file__).resolve().parent.parent/'animations_frame_by_frame'
for clip in ('Pick','Pack','Inspect'):
    paths=sorted((out/'frames'/clip).glob('*.png'))
    frames=[]
    for path in paths:
        with Image.open(path) as source:
            frame=source.convert('RGB')
            frame.thumbnail((560,420),Image.Resampling.LANCZOS)
            frames.append(frame.quantize(colors=128))
    durations=[30 if i%3!=2 else 40 for i in range(len(frames))]
    durations[0]+=400
    durations[-1]+=700
    frames[0].save(out/(clip.lower()+'_preview.gif'),save_all=True,
                   append_images=frames[1:],duration=durations,loop=0,disposal=2)
    print(clip,len(frames),'PNG frames encoded')
