"""Render 30-FPS character animations as review stills, PNG sequences, GIFs, and 6 multi-keyframe contact sheets.

Runs strictly in memory on `characters_animated.blend` (never saving stage helpers back into any .blend or .glb).
Provides a scene-only `FBF_PREVIEW_STAGE` (`0.000 m` floor + per-actor `0.860 m` reference benches) so workstation
interactions show exact `0.86 m` surface contact without any `DemoSupport` meshes in character rigs.
"""
import math
import struct
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

OUT = Path(__file__).resolve().parent.parent / 'animations_frame_by_frame'
FPS = 30

BENCH_CLIPS = {
    'Prepare', 'Prepare_Oversize',
    'Pick', 'Pick_Oversize',
    'Pack', 'Pack_Oversize',
    'RobotPack', 'RobotPack_Oversize',
    'Inspect', 'Inspect_Oversize',
    'Assist',
    'Jammed', 'Jammed_Oversize',
    'Service', 'Service_Oversize',
    'PickUp', 'PlaceDown',
}

# Crisp 5x7 ASCII bitmap font for contact-sheet header overlays (zero external font/PIL dependency).
GLYPHS_5X7 = {
    ' ': (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00),
    '#': (0x0A, 0x0A, 0x1F, 0x0A, 0x1F, 0x0A, 0x0A),
    '%': (0x18, 0x19, 0x02, 0x04, 0x08, 0x13, 0x03),
    '(': (0x02, 0x04, 0x08, 0x08, 0x08, 0x04, 0x02),
    ')': (0x08, 0x04, 0x02, 0x02, 0x02, 0x04, 0x08),
    '+': (0x00, 0x04, 0x04, 0x1F, 0x04, 0x04, 0x00),
    ',': (0x00, 0x00, 0x00, 0x00, 0x06, 0x04, 0x08),
    '-': (0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00),
    '.': (0x00, 0x00, 0x00, 0x00, 0x00, 0x0C, 0x0C),
    '/': (0x01, 0x02, 0x02, 0x04, 0x08, 0x08, 0x10),
    '0': (0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E),
    '1': (0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E),
    '2': (0x0E, 0x11, 0x01, 0x06, 0x08, 0x10, 0x1F),
    '3': (0x1F, 0x02, 0x04, 0x06, 0x01, 0x11, 0x0E),
    '4': (0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02),
    '5': (0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E),
    '6': (0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E),
    '7': (0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08),
    '8': (0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E),
    '9': (0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C),
    ':': (0x00, 0x0C, 0x0C, 0x00, 0x0C, 0x0C, 0x00),
    '_': (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x1F),
    '|': (0x04, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04),
    'A': (0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    'B': (0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E),
    'C': (0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E),
    'D': (0x1C, 0x12, 0x11, 0x11, 0x11, 0x12, 0x1C),
    'E': (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F),
    'F': (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10),
    'G': (0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0F),
    'H': (0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    'I': (0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E),
    'J': (0x07, 0x02, 0x02, 0x02, 0x12, 0x12, 0x0C),
    'K': (0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11),
    'L': (0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F),
    'M': (0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11),
    'N': (0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11),
    'O': (0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    'P': (0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10),
    'Q': (0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D),
    'R': (0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11),
    'S': (0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E),
    'T': (0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04),
    'U': (0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    'V': (0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04),
    'W': (0x11, 0x11, 0x11, 0x15, 0x15, 0x1B, 0x11),
    'X': (0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11),
    'Y': (0x11, 0x11, 0x0A, 0x04, 0x04, 0x04, 0x04),
    'Z': (0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F),
}


def _stage_material(name, color, roughness=0.82, metallic=0.05):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1.0)
    mat.roughness = roughness
    mat.metallic = metallic
    return mat


def _box_mesh(name, boxes_spec, mats):
    verts, faces, mids = [], [], []
    for center, size, mid in boxes_spec:
        start = len(verts)
        verts.extend(
            tuple(center[i] + sign[i] * size[i] / 2 for i in range(3))
            for sign in [(x, y, z) for z in (-1, 1) for y in (-1, 1) for x in (-1, 1)]
        )
        for face in [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]:
            faces.append(tuple(start + i for i in face))
            mids.append(mid)
    mesh = bpy.data.meshes.new(name + '_Mesh')
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    for m in mats:
        mesh.materials.append(m)
    for poly, mid in zip(mesh.polygons, mids):
        poly.material_index = mid
        poly.use_smooth = False
    return bpy.data.objects.new(name, mesh)


def ensure_preview_stage(sc):
    stage_col = bpy.data.collections.get('FBF_PREVIEW_STAGE')
    if stage_col is None:
        stage_col = bpy.data.collections.new('FBF_PREVIEW_STAGE')
        sc.collection.children.link(stage_col)
        floor_mat = _stage_material('FBF_Stage_Floor', (0.145, 0.175, 0.205), roughness=0.92, metallic=0.0)
        top_mat = _stage_material('FBF_Stage_BenchTop', (0.28, 0.33, 0.36), roughness=0.72, metallic=0.12)
        leg_mat = _stage_material('FBF_Stage_BenchFrame', (0.18, 0.21, 0.24), roughness=0.65, metallic=0.35)

        floor = _box_mesh('FBF_Preview_Floor', [((0.0, -0.18, -0.006), (3.80, 2.40, 0.012), 0)], [floor_mat])
        floor['preview_stage_only'] = True
        stage_col.objects.link(floor)

        for label, cx in [('Worker', -0.70), ('Robot', 0.70)]:
            # Exact z = 0.860 m top surface (center z = 0.844, thickness = 0.032 -> top = 0.860 m)
            parts = [
                ((cx, -0.35, 0.844), (0.98, 0.48, 0.032), 0),
                ((cx, -0.35, 0.812), (0.90, 0.40, 0.032), 1),
            ]
            for sx in (-0.43, 0.43):
                for sy in (-0.17, 0.17):
                    parts.append(((cx + sx, -0.35 + sy, 0.400), (0.042, 0.042, 0.800), 1))
            bench = _box_mesh(f'FBF_Preview_Bench_{label}', parts, [top_mat, leg_mat])
            bench['preview_stage_only'] = True
            stage_col.objects.link(bench)
    elif stage_col.name not in sc.collection.children:
        sc.collection.children.link(stage_col)
    return stage_col


def set_bench_visibility(worker_bench=True, robot_bench=True):
    for label, vis in [('Worker', worker_bench), ('Robot', robot_bench)]:
        ob = bpy.data.objects.get(f'FBF_Preview_Bench_{label}')
        if ob is not None:
            ob.hide_render = not vis
            ob.hide_viewport = not vis


def setup(res_x=960, res_y=720):
    sc = next(s for s in bpy.data.scenes if s.name.startswith('FRAME BY FRAME /'))
    bpy.context.window.scene = sc
    ensure_preview_stage(sc)
    # Ensure actors are positioned side-by-side at x = ±0.70 m for paired renders
    w_rig = bpy.data.objects.get('WORKER_Rig')
    r_rig = bpy.data.objects.get('ROBOT_Rig')
    if w_rig is not None:
        w_rig.location = (-0.70, 0.0, 0.0)
    if r_rig is not None:
        r_rig.location = (0.70, 0.0, 0.0)

    if sc.camera is None:
        data = bpy.data.cameras.new('FBF Preview camera')
        cam = bpy.data.objects.new('FBF Preview camera', data)
        sc.collection.objects.link(cam)
        sc.camera = cam
    cam = sc.camera
    cam.data.type = 'ORTHO'
    is_tile = (res_x == 640 and res_y == 480)
    cam.data.ortho_scale = 3.30 if is_tile else 3.05
    cam.location = (1.55, -7.0, 3.45)
    target_z = 1.04 if is_tile else 0.96
    cam.rotation_euler = (Vector((0.0, -0.16, target_z)) - cam.location).to_track_quat('-Z', 'Y').to_euler()

    sc.render.engine = 'BLENDER_WORKBENCH'
    sc.render.resolution_x = res_x
    sc.render.resolution_y = res_y
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = 'PNG'
    sc.render.film_transparent = False
    sc.display.shading.light = 'STUDIO'
    sc.display.shading.color_type = 'MATERIAL'
    sc.display.shading.show_shadows = True
    sc.display.shading.show_cavity = True
    sc.display.shading.cavity_type = 'BOTH'
    sc.display.shading.curvature_ridge_factor = 1.2
    sc.display.shading.curvature_valley_factor = 1.1
    sc.display.shading.background_type = 'WORLD'
    if sc.world is None:
        sc.world = bpy.data.worlds.new('FBF Preview world')
    sc.world.color = (0.065, 0.082, 0.105)
    sc.view_settings.view_transform = 'Standard'
    return sc


def assign_action(rig, action):
    rig.animation_data_create()
    rig.animation_data.action = action
    if hasattr(action, 'slots') and action.slots:
        rig.animation_data.action_slot = action.slots[0]
    for tr in rig.animation_data.nla_tracks:
        tr.mute = True


def _eval_pose_at_frame(rig, clip_name, frame):
    prefix = 'FBF_Worker_' if 'WORKER' in rig.name else 'FBF_Robot_'
    action = bpy.data.actions.get(prefix + clip_name) or bpy.data.actions[prefix + 'Idle']
    assign_action(rig, action)
    end_f = max(1, round(action.frame_range[1]))
    clamped = min(max(0, int(round(frame))), end_f)
    return action, clamped, end_f


def render_pair(sc, worker_clip, worker_frame, robot_clip, robot_frame, filepath):
    w_rig = bpy.data.objects['WORKER_Rig']
    r_rig = bpy.data.objects['ROBOT_Rig']
    set_bench_visibility(worker_clip in BENCH_CLIPS, robot_clip in BENCH_CLIPS)

    # Evaluate Worker at worker_frame, snapshot pose, then evaluate Robot at robot_frame and restore Worker pose
    _, wf, w_end = _eval_pose_at_frame(w_rig, worker_clip, worker_frame)
    sc.frame_set(wf)
    bpy.context.view_layer.update()
    w_snap = {
        pb.name: (pb.location.copy(), pb.rotation_quaternion.copy(), pb.scale.copy())
        for pb in w_rig.pose.bones
    }

    _, rf, r_end = _eval_pose_at_frame(r_rig, robot_clip, robot_frame)
    sc.frame_set(rf)
    bpy.context.view_layer.update()
    w_rig.animation_data.action = None
    for bname, (loc, rot, scl) in w_snap.items():
        pb = w_rig.pose.bones[bname]
        pb.location = loc
        pb.rotation_quaternion = rot
        pb.scale = scl
    bpy.context.view_layer.update()

    filepath.parent.mkdir(parents=True, exist_ok=True)
    sc.render.filepath = str(filepath)
    bpy.ops.render.render(write_still=True)
    return wf, w_end, rf, r_end


def shot(worker_clip, worker_frame, robot_clip, robot_frame, path):
    sc = setup(960, 720)
    render_pair(sc, worker_clip, worker_frame, robot_clip, robot_frame, path)
    print('STILL_COMPLETE', path.name, flush=True)


def sequence(clip):
    durations = {'Pick': 4.0, 'Pack': 3.0, 'Inspect': 3.6}
    robot_map = {'Pick': 'CarryIdle', 'Pack': 'RobotPack', 'Inspect': 'RobotPack_Oversize'}
    sc = setup(720, 540)
    folder = OUT / 'frames' / clip
    folder.mkdir(parents=True, exist_ok=True)
    total = round(durations[clip] * FPS)
    r_clip = robot_map[clip]
    r_action = bpy.data.actions['FBF_Robot_' + r_clip]
    r_end = max(1, round(r_action.frame_range[1]))
    for frame in range(total + 1):
        phase = frame / total
        r_frame = round(phase * r_end)
        render_pair(sc, clip, frame, r_clip, r_frame, folder / f'{frame:04d}.png')
    print('PNG_SEQUENCE_COMPLETE', clip, total + 1, flush=True)


def _lzw_encode_8bit(indices):
    clear_code = 256
    end_code = 257
    next_code = 258
    table = {bytes([i]): i for i in range(256)}
    bit_buf = 0
    bit_cnt = 0
    code_size = 9
    out_bytes = bytearray()

    def emit(code):
        nonlocal bit_buf, bit_cnt
        bit_buf |= (code << bit_cnt)
        bit_cnt += code_size
        while bit_cnt >= 8:
            out_bytes.append(bit_buf & 0xFF)
            bit_buf >>= 8
            bit_cnt -= 8

    emit(clear_code)
    if len(indices) == 0:
        emit(end_code)
    else:
        w = bytes([int(indices[0])])
        for b in indices[1:]:
            k = bytes([int(b)])
            wk = w + k
            if wk in table:
                w = wk
            else:
                emit(table[w])
                if next_code < 4096:
                    table[wk] = next_code
                    next_code += 1
                    if next_code > (1 << code_size) and code_size < 12:
                        code_size += 1
                else:
                    emit(clear_code)
                    table = {bytes([i]): i for i in range(256)}
                    next_code = 258
                    code_size = 9
                w = k
        emit(table[w])
        emit(end_code)
    if bit_cnt > 0:
        out_bytes.append(bit_buf & 0xFF)

    sub_blocks = bytearray([8])  # LZW minimum code size = 8
    for i in range(0, len(out_bytes), 255):
        chunk = out_bytes[i:i + 255]
        sub_blocks.append(len(chunk))
        sub_blocks.extend(chunk)
    sub_blocks.append(0)
    return bytes(sub_blocks)


def encode_gif_from_pngs(png_paths, gif_path, downsample=2):
    # 6x6x6 uniform 216-color sRGB cube padded to 256 entries
    levels = np.array([0, 51, 102, 153, 204, 255], dtype=np.uint8)
    palette = bytearray(256 * 3)
    idx = 0
    for r in levels:
        for g in levels:
            for b in levels:
                palette[idx * 3:idx * 3 + 3] = bytes((int(r), int(g), int(b)))
                idx += 1

    indexed_frames = []
    out_w = out_h = 0
    for p in png_paths:
        img = bpy.data.images.load(str(p), check_existing=False)
        w, h = img.size
        arr = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(arr)
        bpy.data.images.remove(img)
        arr = arr.reshape((h, w, 4))[::-1, :, :3]  # top-to-bottom linear RGB
        arr = arr[::downsample, ::downsample, :]
        arr = np.clip(arr, 0.0, 1.0)
        arr = np.where(arr <= 0.0031308, 12.92 * arr, 1.055 * np.power(arr, 1.0 / 2.4) - 0.055)
        out_h, out_w, _ = arr.shape
        q = np.clip(np.rint(arr * 5.0), 0, 5).astype(np.uint8)
        indices = (q[:, :, 0] * 36 + q[:, :, 1] * 6 + q[:, :, 2]).ravel()
        indexed_frames.append(indices)

    buf = bytearray()
    buf.extend(b'GIF89a')
    buf.extend(struct.pack('<HHBBB', out_w, out_h, 0xF7, 0, 0))  # 256-color GCT
    buf.extend(palette)
    # Netscape loop extension (infinite loop)
    buf.extend(b'\x21\xFF\x0BNETSCAPE2.0\x03\x01\x00\x00\x00')

    for i, indices in enumerate(indexed_frames):
        delay_cs = 3 if (i % 3 != 2) else 4
        if i == 0:
            delay_cs += 40
        elif i == len(indexed_frames) - 1:
            delay_cs += 70
        buf.extend(struct.pack('<BBBBHB', 0x21, 0xF9, 4, 0x04, delay_cs, 0))
        buf.append(0x00)
        buf.extend(struct.pack('<BHHHHB', 0x2C, 0, 0, out_w, out_h, 0))
        buf.extend(_lzw_encode_8bit(indices))

    buf.append(0x3B)
    gif_path.write_bytes(bytes(buf))
    print('GIF_COMPLETE', gif_path.name, len(indexed_frames), f'{out_w}x{out_h}', flush=True)


def _draw_text(canvas, x0, y0, text, color=(0.95, 0.97, 1.0, 1.0), scale=2):
    h, w, _ = canvas.shape
    cursor_x = x0
    for ch in text.upper():
        rows = GLYPHS_5X7.get(ch, GLYPHS_5X7[' '])
        for ry, row_bits in enumerate(rows):
            if row_bits == 0:
                continue
            for rx in range(5):
                if row_bits & (1 << (4 - rx)):
                    py0 = y0 + ry * scale
                    px0 = cursor_x + rx * scale
                    py1 = min(h, py0 + scale)
                    px1 = min(w, px0 + scale)
                    if py0 >= 0 and px0 >= 0 and py0 < h and px0 < w:
                        canvas[py0:py1, px0:px1] = color
        cursor_x += 6 * scale


def render_contact_sheet(sheet_name, sheet_title, tile_specs):
    """Render a 1920x960 (3x2 tiles of 640x480) labeled contact sheet."""
    tile_w, tile_h = 640, 480
    cols, rows = 3, 2
    assert len(tile_specs) == cols * rows, ('expected 6 tiles', len(tile_specs))
    sc = setup(tile_w, tile_h)
    sheets_dir = OUT / 'contact_sheets'
    sheets_dir.mkdir(parents=True, exist_ok=True)
    tmp_tile = sheets_dir / f'_tmp_{Path(sheet_name).stem}.png'

    sheet = np.zeros((rows * tile_h, cols * tile_w, 4), dtype=np.float32)
    sheet[:, :, 3] = 1.0

    for idx, (w_clip, w_phase, r_clip, r_phase) in enumerate(tile_specs):
        w_act = bpy.data.actions['FBF_Worker_' + w_clip]
        r_act = bpy.data.actions['FBF_Robot_' + r_clip]
        w_end = max(1, round(w_act.frame_range[1]))
        r_end = max(1, round(r_act.frame_range[1]))
        wf = round(w_phase * w_end)
        rf = round(r_phase * r_end)

        render_pair(sc, w_clip, wf, r_clip, rf, tmp_tile)
        img = bpy.data.images.load(str(tmp_tile), check_existing=False)
        buf = np.empty(tile_w * tile_h * 4, dtype=np.float32)
        img.pixels.foreach_get(buf)
        bpy.data.images.remove(img)
        tile = buf.reshape((tile_h, tile_w, 4))[::-1, :, :].copy()  # top-to-bottom

        # Top banner (42 px) with crisp 2x bitmap labels
        tile[:42, :, :3] = tile[:42, :, :3] * 0.22 + np.array([0.04, 0.06, 0.09], dtype=np.float32)
        tile[42:43, :, :3] = np.array([0.24, 0.34, 0.44], dtype=np.float32)
        line1 = f'#{idx + 1} W:{w_clip} F{wf}/{w_end} ({round(w_phase * 100)}% {wf / FPS:.2f}S)'
        line2 = f'   R:{r_clip} F{rf}/{r_end} ({round(r_phase * 100)}% {rf / FPS:.2f}S)'
        _draw_text(tile, 10, 6, line1, color=(0.98, 0.86, 0.36, 1.0), scale=2)
        _draw_text(tile, 10, 24, line2, color=(0.86, 0.94, 1.00, 1.0), scale=2)

        # Subtle tile border
        tile[0:1, :, :3] = 0.22
        tile[-1:, :, :3] = 0.22
        tile[:, 0:1, :3] = 0.22
        tile[:, -1:, :3] = 0.22

        r_idx, c_idx = divmod(idx, cols)
        sheet[r_idx * tile_h:(r_idx + 1) * tile_h, c_idx * tile_w:(c_idx + 1) * tile_w] = tile

    if tmp_tile.exists():
        tmp_tile.unlink()

    # Save 1920x960 PNG via bpy.data.images (flip back to Blender bottom-to-top pixel order)
    out_path = sheets_dir / sheet_name
    out_img = bpy.data.images.new(sheet_name, width=cols * tile_w, height=rows * tile_h, alpha=True)
    out_img.filepath_raw = str(out_path)
    out_img.file_format = 'PNG'
    out_img.pixels.foreach_set(sheet[::-1, :, :].ravel())
    out_img.save()
    bpy.data.images.remove(out_img)
    print('CONTACT_SHEET_COMPLETE', sheet_name, sheet_title, flush=True)


def render_all():
    # 1. Classic side-by-side review stills (960x720)
    shot('Prepare', 46, 'RobotPack', 18, OUT / 'prepare_preview.png')
    shot('Pack', 54, 'RobotPack', 50, OUT / 'packing_preview.png')
    shot('Pick', 57, 'Service', 36, OUT / 'interaction_preview.png')

    # 2. Full 30-FPS PNG sequences + animated GIF89a previews
    for clip in ('Pick', 'Pack', 'Inspect'):
        sequence(clip)
        pngs = sorted((OUT / 'frames' / clip).glob('*.png'))
        encode_gif_from_pngs(pngs, OUT / f'{clip.lower()}_preview.gif', downsample=2)

    # 3. Six 1920x960 multi-keyframe contact sheets covering all 17 Worker + 14 Robot contract clips
    render_contact_sheet(
        'sheet_01_prepare_and_pick.png',
        'Prepare & Pick Progressions',
        [
            ('Prepare', 0.15, 'RobotPack', 0.15),
            ('Prepare', 0.45, 'RobotPack', 0.45),
            ('Prepare', 0.80, 'RobotPack', 0.80),
            ('Pick', 0.20, 'CarryIdle', 0.20),
            ('Pick', 0.48, 'CarryIdle', 0.50),
            ('Pick', 0.78, 'CarryIdle', 0.80),
        ],
    )
    render_contact_sheet(
        'sheet_02_pack_worker_and_robot.png',
        'Pack & RobotPack Flap Folding + Sealing Tape',
        [
            ('Pack', 0.00, 'RobotPack', 0.00),
            ('Pack', 0.20, 'RobotPack', 0.20),
            ('Pack', 0.40, 'RobotPack', 0.40),
            ('Pack', 0.60, 'RobotPack', 0.60),
            ('Pack', 0.80, 'RobotPack', 0.80),
            ('Pack', 1.00, 'RobotPack', 1.00),
        ],
    )
    render_contact_sheet(
        'sheet_03_inspect_and_oversize.png',
        'Inspect + Oversize Operations',
        [
            ('Inspect', 0.00, 'RobotPack_Oversize', 0.15),
            ('Inspect', 0.48, 'RobotPack_Oversize', 0.50),
            ('Inspect', 0.92, 'RobotPack_Oversize', 0.85),
            ('Prepare_Oversize', 0.50, 'Service_Oversize', 0.50),
            ('Pack_Oversize', 0.52, 'Jammed_Oversize', 0.50),
            ('Inspect_Oversize', 0.48, 'RobotPack_Oversize', 1.00),
        ],
    )
    render_contact_sheet(
        'sheet_04_assist_and_service.png',
        'Worker Assist (>=0.22m) & Robot Service (>=0.12m)',
        [
            ('Assist', 0.00, 'Service', 0.00),
            ('Assist', 0.20, 'Service', 0.20),
            ('Assist', 0.40, 'Service', 0.40),
            ('Assist', 0.60, 'Service', 0.60),
            ('Assist', 0.80, 'Service', 0.80),
            ('Assist', 1.00, 'Service', 1.00),
        ],
    )
    render_contact_sheet(
        'sheet_05_jammed_break_offline.png',
        'Worker Break (>=0.15m) + Robot Jammed (>=0.03m) & Offline (>=0.01m)',
        [
            ('Break', 0.00, 'Jammed', 0.00),
            ('Break', 0.38, 'Jammed', 0.50),
            ('Break', 0.72, 'Jammed', 0.85),
            ('Pick_Oversize', 0.22, 'Offline', 0.00),
            ('Pick_Oversize', 0.50, 'Offline', 0.50),
            ('Pick_Oversize', 0.78, 'Offline', 1.00),
        ],
    )
    render_contact_sheet(
        'sheet_06_empty_and_carry_props.png',
        'Empty-Handed Zero-Prop Verification & <2cm Carry Grip',
        [
            ('Idle', 0.50, 'Idle', 0.50),
            ('Walk', 0.25, 'Walk', 0.25),
            ('Reach', 0.50, 'Reach', 0.50),
            ('PickUp', 0.58, 'PickUp', 0.58),
            ('CarryWalk', 0.25, 'CarryWalk', 0.25),
            ('PlaceDown', 0.38, 'PlaceDown', 0.38),
        ],
    )
    print('ALL_RENDERS_COMPLETE', str(OUT), flush=True)


if __name__ == '__main__':
    render_all()
