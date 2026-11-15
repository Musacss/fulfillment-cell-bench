"""Compact authored industrial details. No logical simulation bindings are changed.

Call ``build_equipment(api)`` after the environment and visual layout exist. ``api``
contains the primitive functions from build_environment.py: group, box, cyl,
beam, text and the shared M material dictionary. All distances are metres.
"""
import math
import bpy


def _linear(hex_color):
    rgb = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return tuple(v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb)


def _material(name, color, metallic=0, roughness=.4, emission=0):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    rgb = _linear(color)
    mat.diffuse_color = (*rgb, 1)
    p = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    p.inputs['Base Color'].default_value = (*rgb, 1)
    p.inputs['Metallic'].default_value = metallic
    p.inputs['Roughness'].default_value = roughness
    if emission:
        p.inputs['Emission Color'].default_value = (*rgb, 1)
        p.inputs['Emission Strength'].default_value = emission
    mat['srgb_color'] = color
    return mat


def build_docks_and_cutaway(api, walls, width=36, depth=18, wall_height=3.6):
    """Dimensioned gate-to-gate front access, reusable by native map updates."""
    group, box, cyl, beam, text = [api[k] for k in ('group', 'box', 'cyl', 'beam', 'text')]
    yellow = _material('FlexSim / Signal yellow', '#f4b400', .18, .3)
    graphite = _material('FlexSim / Graphite steel', '#2b3137', .55, .34)
    blue = _material('FlexSim / Equipment blue', '#0e4c92', .2, .35)
    wall = _material('FlexSim / Cutaway wall', '#e6ebef', .02, .65)
    silver = _material('FlexSim / Brushed aluminium', '#c8d0d6', .78, .26)
    dark = _material('FlexSim / Dark mesh and rubber', '#25313b', .18, .5)
    white = _material('FlexSim / White signage', '#f6f8fa', .02, .45)
    screen = _material('FlexSim / HMI screen', '#17485b', .1, .28, .18)
    cyan = _material('FlexSim / HMI cyan', '#5ce1e6', .05, .3, .35)
    red = _material('FlexSim / Red signal', '#e53935', .04, .3, .25)
    green = _material('FlexSim / Green signal', '#43a047', .04, .3, .25)
    # Continuous side walls close the former low-parapet gaps. The front
    # facade remains the open cutaway; both gates share the front aisle.
    # Each dock is a real gap between two wall sections; the sectional leaf is
    # modelled in that gap and does not overlap a hidden solid wall.
    for side, number, label in [(-1, '01', 'INBOUND'), (1, '02', 'DISPATCH')]:
        x = side * (width / 2 - .15)
        dock = group('DOCK_' + number, (x, -5.15, 0), walls, typ='sectional_dock', dynamic=True)
        dock['dock_label'] = 'DOCK ' + number + ' - ' + label
        # 3.6 m clear doorway around aisle center y=-5.15.
        for lo, hi, height in [(-depth / 2 + .15, -6.95, wall_height),
                               (-3.35, depth / 2 - .15, wall_height)]:
            cy, span = (lo + hi) / 2, hi - lo
            box('Cutaway side wall', (.13, span, height), (x, cy, height / 2), wall, walls, .007)
            box('Side wall skirting', (.18, span, .16), (x - side * .025, cy, .08), graphite, walls, .003)
        box('Dock overdoor lintel', (.16, 3.6, .65), (0, 0, 3.275), wall, dock, .006)
        if wall_height > 3.6:
            box('Dock upper wall', (.16, 3.6, wall_height - 3.6),
                (0, 0, (wall_height + 3.6) / 2), wall, dock, .006)
        for y in [-1.8, 1.8]:
            box('Dock jamb', (.22, .14, 2.95), (0, y, 1.475), graphite, dock, .01)
            box('Dock guide rail', (.07, .055, 2.9), (-side * .14, y, 1.45), silver, dock, .003)
            box('Dock rubber bumper', (.15, .24, .68), (-side * .18, y - math.copysign(.18, y), .34), dark, dock, .02)
            box('Dock corner protection', (.24, .13, .42), (-side * .23, y + math.copysign(.17, y), .21), yellow, dock, .012)
        # Closed panel geometry is intentionally separate from the structural wall.
        shutter = group('DOCK_' + number + '_SECTIONAL_LEAF', (0, 0, 0), dock, dynamic=True)
        shutter['animation_role'] = 'dock_leaf'
        for row in range(7):
            z = .21 + row * .42
            box('Dock sectional panel', (.075, 3.39, .407), (0, 0, z), silver, shutter, .006)
            for y in [-1.15, 0, 1.15]:
                box('Dock panel stiffener', (.012, .028, .38), (-side * .046, y, z), graphite, shutter, .002)
        for y in [-.9, 0, .9]:
            box('Dock vision window', (.006, .55, .21), (-side * .043, y, 1.89), screen, shutter, .002)
            box('Dock window reflection', (.003, .045, .17), (-side * .047, y - .16, 1.89), cyan, shutter, .001)
        # Face labels into the room: font plane local XY rotated to lateral YZ.
        rotation = (math.pi / 2, 0, -side * math.pi / 2)
        signx = -side * .111
        box('Dock sign backing', (.025, 2.86, .36), (signx, 0, 3.22), blue, dock, .006)
        sign = text('DOCK_' + number + '_SIGN', 'DOCK ' + number + '  /  ' + label,
                    .16, (signx - side * .016, 0, 3.16), white, dock, rotation, 'CENTER')
        # Two individually addressable lamps and compact call button.
        lamp = group('DOCK_' + number + '_TRAFFIC_LIGHT', (-side * .24, 2.1, 1.74), dock)
        box('Dock traffic light housing', (.13, .17, .42), (0, 0, 0), graphite, lamp, .015)
        for z, name, material in [(.105, 'RED', red), (-.105, 'GREEN', green)]:
            light = cyl('DOCK_' + number + '_SIGNAL_' + name, .052, .018,
                        (-side * .077, 0, z), material, lamp, (0, math.pi / 2, 0), n=20)
            light['dynamic'] = True
            light['signal_state'] = name.lower()
        box('Dock control box', (.13, .20, .25), (-side * .22, 2.1, .97), white, dock, .008)
        cyl('Dock open pushbutton', .025, .018, (-side * .30, 2.1, 1.01), green, dock, (0, math.pi / 2, 0), n=16)

    # Hydraulic pallet jack in the expanded west service pocket, clear of Q1 and aisle.
    jack = group('PALLET_JACK', (-width / 2 + 1.15, -2.8, 0), walls, typ='hydraulic_pallet_jack', dynamic=True)
    jack['parking_position'] = True
    for x in [-.235, .235]:
        box('Pallet jack fork', (.16, 1.12, .07), (x, .40, .085), yellow, jack, .018)
        cyl('Pallet jack load wheel', .045, .09, (x, .87, .045), dark, jack, (0, math.pi / 2, 0), n=16)
    box('Pallet jack rear bridge', (.62, .25, .16), (0, -.20, .12), yellow, jack, .025)
    cyl('Pallet jack hydraulic cylinder', .065, .29, (0, -.20, .32), silver, jack, n=20)
    for x in [-.12, .12]:
        cyl('Pallet jack steering wheel', .095, .065, (x, -.30, .095), dark, jack, (0, math.pi / 2, 0), n=20)
    beam('Pallet jack tiller', (0, -.22, .34), (0, -.62, 1.03), .045, graphite, jack)
    for x in [-.17, .17]:
        beam('Pallet jack handle side', (0, -.62, 1.03), (x, -.66, 1.18), .028, graphite, jack)
    beam('Pallet jack handgrip', (-.17, -.66, 1.18), (.17, -.66, 1.18), .034, dark, jack)


def build_equipment(api):
    group, box, cyl, beam, text, M = [api[k] for k in ('group', 'box', 'cyl', 'beam', 'text', 'M')]
    # Distinct material names make asset colour bindings readable in Three.js.
    yellow = _material('FlexSim / Signal yellow', '#f4b400', .18, .3)
    graphite = _material('FlexSim / Graphite steel', '#2b3137', .55, .34)
    blue = _material('FlexSim / Equipment blue', '#0e4c92', .2, .35)
    wall = _material('FlexSim / Cutaway wall', '#e6ebef', .02, .65)
    silver = _material('FlexSim / Brushed aluminium', '#c8d0d6', .78, .26)
    dark = _material('FlexSim / Dark mesh and rubber', '#25313b', .18, .5)
    white = _material('FlexSim / White signage', '#f6f8fa', .02, .45)
    screen = _material('FlexSim / HMI screen', '#17485b', .1, .28, .18)
    cyan = _material('FlexSim / HMI cyan', '#5ce1e6', .05, .3, .35)
    led = _material('FlexSim / High-bay LED diffuser', '#f5f8ff', .02, .25, 1.4)
    red = _material('FlexSim / Red signal', '#e53935', .04, .3, .25)
    amber = _material('FlexSim / Amber signal', '#ffb300', .04, .3, .2)
    green = _material('FlexSim / Green signal', '#43a047', .04, .3, .25)
    kraft = M['kraft']
    layers = {}

    def layer(name, label):
        old = bpy.data.objects.get(name)
        if old:
            for ob in list(old.children_recursive):
                if ob.name.startswith(('Back wall panel', 'Wall skirting', 'Structural column',
                                       'Column guard', 'Back horizontal service rail',
                                       'Warehouse wordmark', 'Warehouse descriptor')):
                    matrix = ob.matrix_world.copy()
                    ob.parent = None
                    ob.matrix_world = matrix
                    if bpy.context.scene.collection not in ob.users_collection:
                        bpy.context.scene.collection.objects.link(ob)
                else:
                    bpy.data.objects.remove(ob, do_unlink=True)
            bpy.data.objects.remove(old, do_unlink=True)
        col = bpy.data.collections.get(name)
        if col is None:
            col = bpy.data.collections.new(name)
            bpy.context.scene.collection.children.link(col)
        root = group(name, typ='ui_visibility_layer')
        root['ui_label'] = label
        root['ui_toggle'] = True
        layers[name] = (root, col)
        return root

    walls = layer('ENV_WALLS_AND_DOCKS', 'Walls and logistics docks')
    details = layer('ENV_WORKSTATIONS_DETAIL', 'Workstation tooling')
    cell = layer('ENV_ROBOT_CELL', 'Robot safety cell')
    rest = layer('ENV_BREAK_AREA', 'Break and shift KPI area')
    overhead = layer('ENV_OVERHEAD', 'Overhead trusses and lighting')
    overhead['default_visible'] = False
    overhead.hide_render = True

    # Retain the existing full-height rear wall, including its branding.
    for ob in list(bpy.data.objects):
        if ob.name.startswith(('Back wall panel', 'Wall skirting', 'Structural column',
                               'Column guard', 'Back horizontal service rail',
                               'Warehouse wordmark', 'Warehouse descriptor')):
            matrix = ob.matrix_world.copy()
            ob.parent = walls
            ob.matrix_world = matrix
        elif ob.name.startswith('Left return wall'):
            bpy.data.objects.remove(ob, do_unlink=True)

    build_docks_and_cutaway(api, walls)

    # PREP side cassette and tray stack occupy a separate auxiliary stand.
    prep = group('PREP_TOOLING', (-10.17, 1.65, 0), details, dynamic=True)
    box('Prep cassette base', (.42, .66, .035), (0, .04, .79), blue, prep, .004)
    for x in [-.17, .17]:
        for y in [-.20, .28]:
            box('Prep cassette leg', (.025, .025, .77), (x, y, .385), graphite, prep, .002)
    for i in range(6):
        x = -.13 + i * .052
        box('Prep flat carton blank', (.018, .46, .50), (x, .05, 1.0575), kraft, prep, .001)
        beam('Prep carton divider', (x - .025, -.22, .81), (x - .025, -.22, 1.30), .008, silver, prep)
    for i in range(3):
        z = .18 + i * .035
        box('Prep standard tray base', (.38, .46, .012), (0, .04, z), silver, prep, .003)
        for x in [-.184, .184]:
            box('Prep standard tray rim', (.012, .46, .026), (x, .04, z + .019), graphite, prep, .002)
        for y in [-.184, .264]:
            box('Prep standard tray rim', (.38, .012, .026), (0, y, z + .019), graphite, prep, .002)

    # INFEED_PREP_C01: Grounded L-shaped roller bridge from VIS_STAGE_1_TABLE East edge (-10.42)
    # into CONVEYOR_01 (-9.00), keeping VIS_STAGE_1_WORK (-11.00, +1.00) >= 0.58 m clear.
    infeed = group('INFEED_PREP_C01', (-9.34, 0.0, 0.0), details, typ='roller_transfer_bridge', dynamic=True)
    infeed['bridge_role'] = 'infeed_prep_to_c01'
    infeed['surface_height_m'] = 0.86
    # West-to-East take-off arm: X_world in [-10.420, -9.660], Y_world in [+0.880, +1.340]
    for wy in (0.894, 1.326):
        box('Infeed arm frame', (.760, .028, .100), (-10.040 + 9.34, wy, .790), graphite, infeed, .003)
    box('Infeed arm north guide', (.760, .018, .065), (-10.040 + 9.34, 1.331, .8725), yellow, infeed, .002)
    box('Infeed arm south guide', (.680, .018, .055), (-9.980 + 9.34, 0.889, .8675), yellow, infeed, .002)
    for ly in (0.945, 1.275):
        box('Infeed arm leg', (.042, .042, .732), (-10.300 + 9.34, ly, .384), graphite, infeed, .003)
        box('Infeed arm foot pad', (.084, .084, .018), (-10.300 + 9.34, ly, .009), dark, infeed, .002)
    box('Infeed arm crossbar', (.036, .310, .036), (-10.300 + 9.34, 1.110, .220), graphite, infeed, .002)
    for idx, wx in enumerate([-10.37, -10.25, -10.13, -10.01, -9.89, -9.77], 1):
        rl = cyl(f'SPUR_PREP_ROLLER_{idx:02d}', .0125, .390, (wx + 9.34, 1.110, .8475), silver, infeed,
                 (math.pi / 2, 0, 0), n=16, dynamic=True)
        rl['animation_role'] = 'spur_roller'
    # North-to-South trunk: X_world in [-9.680, -9.015], Y_world in [-0.340, +1.340]
    box('Infeed west trunk frame', (.028, 1.680, .100), (-9.666 + 9.34, 0.500, .790), graphite, infeed, .003)
    # East trunk frame stops at Y_world = +0.420 (north of INLET_HOOD Y_max = +0.4005)
    box('Infeed east trunk frame', (.028, .920, .100), (-9.074 + 9.34, 0.880, .790), graphite, infeed, .003)
    box('Infeed trunk north stop', (.620, .018, .065), (-9.370 + 9.34, 1.331, .8725), yellow, infeed, .002)
    box('Infeed trunk east guide', (.018, .920, .065), (-9.069 + 9.34, 0.880, .8725), yellow, infeed, .002)
    box('Infeed south guide', (.330, .018, .065), (-9.515 + 9.34, -0.326, .8725), yellow, infeed, .002)
    box('Infeed west stop', (.018, 1.220, .055), (-9.671 + 9.34, 0.270, .8675), yellow, infeed, .002)
    for lx, ly in [(-9.590, -0.260), (-9.590, 0.260), (-9.590, 1.250), (-9.150, 1.250), (-9.150, 0.480)]:
        box('Infeed leg', (.042, .042, .732), (lx + 9.34, ly, .384), graphite, infeed, .003)
        box('Infeed foot pad', (.084, .084, .018), (lx + 9.34, ly, .009), dark, infeed, .002)
    for idx, wy in enumerate([1.25, 1.13, 1.01, 0.89, 0.77, 0.65, 0.53, 0.42], 7):
        rl = cyl(f'SPUR_PREP_ROLLER_{idx:02d}', .0125, .540, (-9.370 + 9.34, wy, .8475), silver, infeed,
                 (0, math.pi / 2, 0), n=16, dynamic=True)
        rl['animation_role'] = 'spur_roller'
    # Axial entry rollers inside INLET_HOOD mouth (Z_b in [0.835, 0.860] > Transfer tray 0.806)
    for idx, wx in enumerate([-9.60, -9.50, -9.40, -9.30, -9.20, -9.11, -9.025], 15):
        rl = cyl(f'SPUR_PREP_ROLLER_{idx:02d}', .0125, .560, (wx + 9.34, 0.0, .8475), silver, infeed,
                 (math.pi / 2, 0, 0), n=16, dynamic=True)
        rl['animation_role'] = 'spur_roller'

    # OUTFEED_C10_GOOD: Horizontal roller deck [9.005, 9.98] x [-0.34, +0.72] (roller top = 0.860 m)
    # + inclined skate-wheel gravity chute [9.42, 10.00] x [+0.73, +1.765] sloping to 0.255 m at DISPATCH_PALLET_00
    outfeed = group('OUTFEED_C10_GOOD', (9.50, 0.21, 0.0), details, typ='roller_transfer_bridge', dynamic=True)
    outfeed['bridge_role'] = 'outfeed_c10_to_good'
    outfeed['surface_height_m'] = 0.86
    for idx, wx in enumerate([9.025, 9.115, 9.205, 9.295], 1):
        rl = cyl(f'SPUR_GOOD_ROLLER_{idx:02d}', .0125, .560, (wx - 9.50, -0.21, .8475), silver, outfeed,
                 (math.pi / 2, 0, 0), n=16, dynamic=True)
        rl['animation_role'] = 'spur_roller'
    # West frame starts at Y_world = +0.420 (north of OUTLET_HOOD Y_max = 0.4005); East frame full horizontal span
    box('Outfeed west frame', (.028, .300, .100), (9.375 - 9.50, 0.570 - 0.21, .790), graphite, outfeed, .003)
    box('Outfeed east frame', (.028, 1.060, .100), (9.965 - 9.50, 0.190 - 0.21, .790), graphite, outfeed, .003)
    box('Outfeed south guide', (.618, .018, .065), (9.670 - 9.50, -0.326 - 0.21, .8725), yellow, outfeed, .002)
    box('Outfeed east guide', (.018, 1.060, .065), (9.971 - 9.50, 0.190 - 0.21, .8725), yellow, outfeed, .002)
    for lx, ly in [(9.440, -0.260), (9.900, -0.260), (9.440, 0.660), (9.900, 0.660)]:
        box('Outfeed leg', (.042, .042, .732), (lx - 9.50, ly - 0.21, .384), graphite, outfeed, .003)
        box('Outfeed foot pad', (.088, .088, .018), (lx - 9.50, ly - 0.21, .009), dark, outfeed, .002)
    for idx, wy in enumerate([-0.26, -0.14, -0.02, 0.10, 0.22, 0.34, 0.46, 0.58, 0.70], 5):
        rl = cyl(f'SPUR_GOOD_ROLLER_{idx:02d}', .0125, .540, (9.670 - 9.50, wy - 0.21, .8475), silver, outfeed,
                 (0, math.pi / 2, 0), n=16, dynamic=True)
        rl['animation_role'] = 'spur_roller'
    # Inclined skate-wheel gravity chute sloping from (Y=+0.74, Z=0.845) to (Y=+1.755, Z=0.255)
    chute_y0, chute_z0 = 0.740, 0.842
    chute_y1, chute_z1 = 1.755, 0.255
    for cx in (9.435, 9.965):
        beam('SPUR_GOOD_CHUTE_RAIL', (cx - 9.50, chute_y0 - 0.21, chute_z0 - 0.025),
             (cx - 9.50, chute_y1 - 0.21, chute_z1 - 0.025), .030, graphite, outfeed)
        beam('SPUR_GOOD_CHUTE_GUIDE', (cx - 9.50, chute_y0 - 0.21, chute_z0 + 0.032),
             (cx - 9.50, chute_y1 - 0.21, chute_z1 + 0.032), .018, yellow, outfeed)
        box('SPUR_GOOD_CHUTE_LEG', (.038, .038, .222), (cx - 9.50, 1.690 - 0.21, .129), graphite, outfeed, .002)
        box('SPUR_GOOD_CHUTE_FOOT', (.082, .082, .018), (cx - 9.50, 1.690 - 0.21, .009), dark, outfeed, .002)
    box('SPUR_GOOD_CHUTE_STOP', (.548, .020, .062), (9.700 - 9.50, 1.755 - 0.21, .272), yellow, outfeed, .002)
    for idx in range(9):
        t = (idx + 0.5) / 9.0
        wy = chute_y0 + (chute_y1 - chute_y0) * t
        wz = chute_z0 + (chute_z1 - chute_z0) * t
        cyl(f'SPUR_GOOD_AXLE_{idx + 1:02d}', .005, .500, (9.700 - 9.50, wy - 0.21, wz - .012), graphite, outfeed,
            (0, math.pi / 2, 0), n=12)
        for sx in (9.52, 9.70, 9.88):
            wh = cyl(f'SPUR_GOOD_WHEEL_{idx + 1:02d}', .014, .016, (sx - 9.50, wy - 0.21, wz - .012), silver, outfeed,
                     (0, math.pi / 2, 0), n=16, dynamic=True)
            wh['animation_role'] = 'chute_skate_wheel'

    # SPUR_ROBOT: Grounded roller spur [3.94, 4.22] x [+0.38, +2.11] (roller top = 0.860 m)
    # connecting CONVEYOR_08 north port directly to VIS_ROBOT_PACK_TABLE without touching
    # LIGHT_CURTAIN_RIGHT [4.23, 4.41], ROBOT_GUARD_RIGHT [4.24, 4.40], or S3_ROBOT_ASSIST (3.40, 1.55).
    spur_robot = group('SPUR_ROBOT', (4.08, 1.245, 0.0), details, typ='roller_transfer_spur', dynamic=True)
    spur_robot['spur_role'] = 'conveyor_to_robot_pack'
    spur_robot['surface_height_m'] = 0.86
    for sx in (-0.126, 0.126):
        box('Robot spur side frame', (.026, 1.730, .096), (sx, 0.0, .792), graphite, spur_robot, .003)
        box('Robot spur guide rail', (.016, 1.730, .056), (sx, 0.0, .868), yellow, spur_robot, .002)
    for ly in (-0.790, 0.0, 0.790):
        for sx in (-0.105, 0.105):
            box('Robot spur leg', (.036, .036, .734), (sx, ly, .385), graphite, spur_robot, .002)
            box('Robot spur foot pad', (.066, .066, .018), (sx, ly, .009), dark, spur_robot, .002)
        box('Robot spur cross tie', (.210, .030, .030), (0.0, ly, .230), graphite, spur_robot, .002)
    for idx in range(15):
        wy = 0.415 + idx * 0.118
        rl = cyl(f'SPUR_ROBOT_ROLLER_{idx + 1:02d}', .0125, .222, (0.0, wy - 1.245, .8475), silver, spur_robot,
                 (0, math.pi / 2, 0), n=16, dynamic=True)
        rl['animation_role'] = 'spur_roller'

    # Manual Station Diverter / Ball-Transfer Take-Off Spurs (SPUR_PICK, SPUR_PACK, SPUR_QC)
    # Y_world in [+0.465, +0.875], roller/ball top = 0.860 m, grounded legs min_z = 0.000 m,
    # leaving >= 1.255 m clear operator walkway in front of all manual & parallel benches.
    def build_ball_takeoff_spur(spur_name, tag, cx):
        sp = group(spur_name, (cx, 0.670, 0.0), details, typ='ball_transfer_spur', dynamic=True)
        sp['spur_role'] = f'conveyor_takeoff_{tag.lower()}'
        sp['surface_height_m'] = 0.86
        box(f'{tag} spur deck frame', (.420, .410, .076), (0.0, 0.0, .804), graphite, sp, .003)
        box(f'{tag} spur ball plate', (.388, .250, .012), (0.0, 0.065, .844), blue, sp, .002)
        for sx in (-0.201, 0.201):
            box(f'{tag} spur side guide', (.018, .410, .054), (sx, 0.0, .869), yellow, sp, .002)
        box(f'{tag} spur front lip', (.384, .016, .032), (0.0, 0.197, .862), yellow, sp, .002)
        # Angled diverter guide paddle above entry rollers (stays strictly within Y >= +0.472)
        beam(f'{tag} diverter guide', (-0.175, -0.190, .886), (0.145, -0.055, .886), .018, yellow, sp)
        for lx in (-0.165, 0.165):
            for ly in (-0.155, 0.155):
                box(f'{tag} spur leg', (.036, .036, .754), (lx, ly, .395), graphite, sp, .002)
                box(f'{tag} spur foot pad', (.072, .072, .018), (lx, ly, .009), dark, sp, .002)
        for idx, ly in enumerate((-0.165, -0.095), 1):
            rl = cyl(f'SPUR_{tag}_ROLLER_{idx:02d}', .0125, .368, (0.0, ly, .8475), silver, sp,
                     (0, math.pi / 2, 0), n=16, dynamic=True)
            rl['animation_role'] = 'spur_roller'
        b_idx = 1
        for bx in (-0.125, 0.0, 0.125):
            for by in (-0.015, 0.065, 0.145):
                cyl(f'{tag} ball cup', .018, .010, (bx, by, .851), graphite, sp, n=14)
                bt = cyl(f'SPUR_{tag}_BALL_{b_idx:02d}', .011, .010, (bx, by, .855), silver, sp, n=14, dynamic=True)
                bt['animation_role'] = 'ball_transfer'
                b_idx += 1
        return sp

    build_ball_takeoff_spur('SPUR_PICK', 'PICK', -4.27)
    build_ball_takeoff_spur('SPUR_PACK', 'PACK', 0.99)
    build_ball_takeoff_spur('SPUR_QC', 'QC', 6.69)

    # PICK_BENCH_TOTES: 3 SKU bins on rear half of BENCH_PICK [-6.22, -4.58] x [2.735, 3.10], Z_min = 0.860 m
    totes = group('PICK_BENCH_TOTES', (-5.40, 2.91, 0.86), details, typ='pick_sku_totes', dynamic=True)
    box('Pick tote rear rail', (1.64, .020, .030), (0, .180, .015), graphite, totes, .002)
    for idx, (tx, sku_mat) in enumerate([(-.56, blue), (0.0, amber), (.56, kraft)], 1):
        bin_grp = group(f'PICK_SKU_TOTE_{idx:02d}', (tx, -.005, 0.0), totes, dynamic=True)
        box('SKU tote base', (.480, .330, .012), (0, 0, .006), blue, bin_grp, .002)
        for sx in (-.234, .234):
            box('SKU tote side', (.012, .330, .183), (sx, 0, .1035), blue, bin_grp, .002)
        box('SKU tote back', (.456, .012, .183), (0, .159, .1035), blue, bin_grp, .002)
        box('SKU tote front lip', (.456, .012, .088), (0, -.159, .056), blue, bin_grp, .002)
        box('SKU tote label', (.140, .004, .036), (0, -.1675, .058), white, bin_grp, .001)
        for ix in (-.11, .11):
            box('SKU stock item', (.160, .180, .085), (ix, .020, .0545), sku_mat, bin_grp, .003)

    def chamfered_slab(name, outline, bottom, top, material, parent):
        """Extrude a CCW polygon, keeping the working face exactly at top."""
        count = len(outline)
        vertices = [(x, y, z) for z in (bottom, top) for x, y in outline]
        faces = [tuple(reversed(range(count))), tuple(range(count, count * 2))]
        faces += [(i, (i + 1) % count, (i + 1) % count + count, i + count)
                  for i in range(count)]
        mesh = bpy.data.meshes.new(name + '_Mesh')
        mesh.from_pydata(vertices, [], faces)
        mesh.materials.append(material)
        mesh.update()
        ob = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(ob)
        ob.parent = parent
        if parent is not None and parent.get('integration_visual'):
            ob['integration_visual'] = True
            for col in list(ob.users_collection):
                col.objects.unlink(ob)
            for col in parent.users_collection:
                col.objects.link(ob)
        ob['surface_height_m'] = top
        ob['helper_corner_clearance_m'] = .275
        return ob

    # Relieve only the two corners facing the helper. This preserves the fixed
    # order support footprints while opening a .275 m radius approach envelope.
    packing_table = bpy.data.objects.get('BENCH_PACK')
    if packing_table:
        for ob in list(packing_table.children):
            if ob.type == 'MESH' and ob.name.startswith(('Laminate worktop', 'Edge band')):
                bpy.data.objects.remove(ob, do_unlink=True)
        chamfered_slab('Laminate worktop', [(-.9, -.52), (.72, -.52),
                        (.9, -.34), (.9, .45), (-.9, .45)], .83, .86,
                       M['white'], packing_table)
        box('Edge band front', (1.62, .012, .028), (-.09, -.519, .845),
            blue, packing_table, .001)
        box('Edge band chamfer', (math.sqrt(2) * .18, .012, .028),
            (.81, -.43, .845), blue, packing_table, .001, rot=(0, 0, math.pi / 4))
    def build_table_underframe(parent, prefix, foot_size=.088):
        for lx in (-0.46, 0.46):
            for ly in (-0.36, 0.36):
                box(f'{prefix} footplate', (foot_size, foot_size, .016), (lx, ly, .008), dark, parent, .002)
                box(f'{prefix} leg', (.052, .052, .808), (lx, ly, .420), blue, parent, .003)
            box(f'{prefix} side apron', (.040, .660, .052), (lx, 0.0, .788), graphite, parent, .002)
        box(f'{prefix} rear rail', (.960, .042, .042), (0.0, .320, .350), blue, parent, .002)

    # Self-contained grounded Stage-1 Prep workstation in warehouse_environment.glb (min_z = 0.000 m).
    s1_table = group('STAGE1_PREP_TABLE', (-11.0, 1.65, 0.0), details, typ='prep_workstation_table', dynamic=True)
    s1_table['surface_height_m'] = 0.86
    build_table_underframe(s1_table, 'Stage1 prep')
    box('Stage1 prep worktop', (1.096, 1.036, .035), (0.0, -.050, .8410), white, s1_table, .004)
    box('Stage1 prep front apron', (.868, .036, .048), (0.0, -.360, .788), blue, s1_table, .002)

    # Grounded interactive Rework workstation BENCH_REWORK at glTF [1.80, 0.000, +6.35] (Blender (1.80, -6.35, 0.000)):
    # 1.60 m x 0.80 m x 0.860 m, 4 grounded legs min_z = 0.000 m, worktop 0.860 m, corner tooling leaving center clear.
    bench_rework = group('BENCH_REWORK', (1.80, -6.35, 0.0), details, typ='rework_workstation_bench', dynamic=True)
    bench_rework['surface_height_m'] = 0.86
    bench_rework['dimensions'] = [1.60, 0.80, 0.86]
    for lx in (-0.70, 0.70):
        for ly in (-0.31, 0.31):
            box('Rework bench footplate', (.092, .092, .016), (lx, ly, .008), dark, bench_rework, .002)
            box('Rework bench leg', (.050, .050, .810), (lx, ly, .421), blue, bench_rework, .003)
        box('Rework side apron', (.038, .570, .052), (lx, 0.0, .795), graphite, bench_rework, .002)
    box('Rework lower rail', (1.350, .040, .040), (0.0, -.310, .260), blue, bench_rework, .002)
    box('Rework lower shelf', (1.340, .540, .020), (0.0, -.020, .270), white, bench_rework, .003)
    box('Rework front apron', (1.350, .036, .048), (0.0, .310, .795), blue, bench_rework, .002)
    box('Rework bench worktop', (1.600, .798, .034), (0.0, -.001, .843), white, bench_rework, .004)
    box('Rework edge band', (1.596, .012, .028), (0.0, .391, .843), amber, bench_rework, .001)
    rework_kit = group('REWORK_BENCH_TOOLING', (-0.625, -0.250, 0.860), bench_rework, dynamic=True)
    box('Rework tool tray', (.210, .160, .016), (0.0, 0.0, .008), graphite, rework_kit, .002)
    box('Rework tape dispenser base', (.070, .120, .036), (.050, 0.0, .034), amber, rework_kit, .003)
    cyl('Rework tape roll', .042, .036, (.050, 0.0, .068), M['tape'], rework_kit, (0, math.pi / 2, 0), n=24)
    box('Rework cutter handle', (.028, .110, .016), (-.045, 0.0, .024), amber, rework_kit, .002)
    api['anchor']('ANCHOR_BENCH_REWORK_WORK', (0.0, 0.0, 0.86), bench_rework, role='work_surface')
    api['anchor']('ANCHOR_BENCH_REWORK_APPROACH', (0.0, 0.80, 0.0), bench_rework, role='worker_approach')

    # Grounded interactive Scrap workstation BENCH_SCRAP at glTF [8.65, 0.000, +6.35] (Blender (8.65, -6.35, 0.000)):
    # 1.40 m x 0.80 m x 0.860 m, clear of SCRAP_BIN at (7.20, -7.00), 4 grounded legs min_z = 0.000 m, worktop 0.860 m.
    bench_scrap = group('BENCH_SCRAP', (8.65, -6.35, 0.0), details, typ='scrap_inspection_bench', dynamic=True)
    bench_scrap['surface_height_m'] = 0.86
    bench_scrap['dimensions'] = [1.40, 0.80, 0.86]
    for lx in (-0.60, 0.60):
        for ly in (-0.31, 0.31):
            box('Scrap bench footplate', (.092, .092, .016), (lx, ly, .008), dark, bench_scrap, .002)
            box('Scrap bench leg', (.050, .050, .810), (lx, ly, .421), blue, bench_scrap, .003)
        box('Scrap side apron', (.038, .570, .052), (lx, 0.0, .795), graphite, bench_scrap, .002)
    box('Scrap lower rail', (1.150, .040, .040), (0.0, -.310, .260), blue, bench_scrap, .002)
    box('Scrap lower shelf', (1.140, .540, .020), (0.0, -.020, .270), white, bench_scrap, .003)
    box('Scrap front apron', (1.150, .036, .048), (0.0, .310, .795), blue, bench_scrap, .002)
    box('Scrap bench worktop', (1.400, .798, .034), (0.0, -.001, .843), white, bench_scrap, .004)
    box('Scrap edge band', (1.396, .012, .028), (0.0, .391, .843), red, bench_scrap, .001)
    scrap_kit = group('SCRAP_BENCH_TOOLING', (0.525, -0.250, 0.860), bench_scrap, dynamic=True)
    box('Scrap reject log clipboard', (.190, .150, .012), (0.0, 0.0, .006), graphite, scrap_kit, .002)
    box('Scrap reject log sheet', (.150, .110, .004), (-.010, 0.0, .014), white, scrap_kit, .001)
    box('Scrap reject scanner cradle', (.055, .065, .042), (.055, -.020, .033), dark, scrap_kit, .003)
    box('Scrap reject scanner head', (.048, .085, .032), (.055, .005, .068), red, scrap_kit, .004)
    api['anchor']('ANCHOR_BENCH_SCRAP_WORK', (0.0, 0.0, 0.86), bench_scrap, role='work_surface')
    api['anchor']('ANCHOR_BENCH_SCRAP_APPROACH', (0.0, 0.80, 0.0), bench_scrap, role='worker_approach')

    robot_table = bpy.data.objects.get('VIS_ROBOT_PACK_TABLE')
    if robot_table:
        for ob in list(robot_table.children):
            if ob.type == 'MESH' and ob.name.startswith('VIS_Bench_top'):
                bpy.data.objects.remove(ob, do_unlink=True)
        chamfered_slab('VIS_Bench_top_robot_chamfer', [(-.31, -.57), (.55, -.57),
                        (.55, .47), (-.55, .47), (-.55, -.33)], .825, .86,
                       white, robot_table)

    # Self-contained grounded Robot Pack table in warehouse_environment.glb (min_z = 0.000 m).
    r_pack_table = group('ROBOT_PACK_TABLE', (3.5, 2.7, 0.0), cell, typ='robot_pack_workstation', dynamic=True)
    r_pack_table['surface_height_m'] = 0.86
    build_table_underframe(r_pack_table, 'Robot pack', foot_size=.084)
    chamfered_slab('Robot pack worktop', [(-.308, -.568), (.548, -.568),
                    (.548, .468), (-.548, .468), (-.548, -.328)], .8235, .8585,
                   white, r_pack_table)

    # The QC scale replaces a region of the old top; its top is exactly .86 m.
    # Parent QC_TABLE_TOOLING under STAGE4_QC_TABLE with a grounded 4-leg underframe
    # so BOTH nodes exist in warehouse_environment.glb with min_z == 0.000 m.
    table = bpy.data.objects.get('VIS_STAGE_4_TABLE')
    if table:
        for ob in list(table.children):
            if ob.type == 'MESH' and ob.name.startswith('VIS_Bench_top'):
                bpy.data.objects.remove(ob, do_unlink=True)
    qc_station = group('STAGE4_QC_TABLE', (6.0, 2.7, 0.0), details, typ='qc_inspection_station', dynamic=True)
    qc_station['surface_height_m'] = 0.86
    qc = group('QC_TABLE_TOOLING', (0.0, 0.0, 0.0), qc_station, dynamic=True)
    build_table_underframe(qc, 'QC bench')
    # Match the expanded manual_bench envelope x ±.55, y[-.57,.47].
    # The scale aperture occupies x ±.28 and y[-.57,-.08].
    chamfered_slab('QC worktop surround', [(-.55, -.57), (-.28, -.57),
                    (-.28, -.08), (.28, -.08), (.28, -.57), (.55, -.57),
                    (.55, .47), (-.55, .47)], .825, .86, white, qc)
    box('QC_SCALE_FLUSH', (.552, .482, .028), (0, -.325, .846), silver, qc, .004, dynamic=True)
    # Four millimetres of open clearance around the scale avoid intersecting
    # volumes and coincident interface faces in the tabletop surround.
    box('QC scale base', (.49, .39, .05), (0, -.315, .807), graphite, qc, .004)
    terminal = group('QC_TERMINAL', (.48, .31, 0), qc, dynamic=True)
    cyl('QC terminal post', .021, .49, (0, 0, 1.105), silver, terminal, n=16)
    box('QC terminal enclosure', (.36, .065, .25), (-.08, -.035, 1.40), graphite, terminal, .012)
    box('QC terminal display', (.30, .004, .19), (-.08, -.070, 1.40), screen, terminal, .002)
    text('QC display heading', 'QC / CHECK', .030, (-.217, -.073, 1.448), cyan, terminal, (math.pi / 2, 0, 0))
    text('QC display value', '00.00 kg', .039, (-.217, -.073, 1.37), white, terminal, (math.pi / 2, 0, 0))
    # Scanner and coiled lead stay on the right-hand accessory bracket.
    beam('QC scanner arm', (.48, .31, 1.30), (.64, .13, 1.30), .017, silver, qc)
    scan = box('QC_BARCODE_SCANNER', (.075, .11, .13), (.64, .13, 1.225), dark, qc, .009, rot=(.20, 0, 0))
    box('QC scanner red window', (.056, .005, .031), (.64, .071, 1.237), red, qc, .002)
    for z in [1.15 + i * .017 for i in range(7)]:
        cyl('QC scanner coiled lead', .017, .006, (.64, .18, z), dark, qc, n=12)

    # Reinforcement and corner guides stay outside robot order/tray envelope and ground at min_z = 0.000 m.
    robot = group('ROBOT_TABLE_REINFORCEMENT', (3.5, 2.7, 0), cell, dynamic=True)
    for x in [-.47, .47]:
        box('Robot table reinforced foot', (.096, .096, .016), (x, .285, .008), dark, robot, .002)
        box('Robot table reinforced leg', (.060, .060, .804), (x, .285, .418), graphite, robot, .003)
        beam('Robot table diagonal', (x, -.32, .10), (x, .285, .79), .025, graphite, robot)
    for x in [-.485, .485]:
        for y in [-.40, .39]:
            if x < 0 and y < 0:
                # Keep this guide on the retained front-west chamfer land.
                y = -.25
            box('Robot corner guide X', (.10, .018, .025), (x - math.copysign(.04, x), y, .8725), yellow, robot, .002)
            box('Robot corner guide Y', (.018, .10, .025), (x, y - math.copysign(.04, y), .8725), yellow, robot, .002)

    # Rear and right mesh guards. Front is fully open for the overview;
    # helper entry is also clear of VIS_ROBOT_ASSIST (2.8,1.95,0).
    def guard_panel(name, a, b, posts=(True, True)):
        panel = group(name, (0, 0, 0), cell, dynamic=True)
        for keep_post, (x, y) in zip(posts, (a, b)):
            if keep_post:
                box('Robot guard post', (.065, .065, 1.60), (x, y, .80), yellow, panel, .004)
                box('Robot guard foot', (.16, .16, .018), (x, y, .009), graphite, panel, .003)
        for z in [.23, 1.54]:
            beam('Robot guard frame', (*a, z), (*b, z), .035, yellow, panel)
        length = math.dist(a, b)
        for i in range(1, max(2, round(length / .115))):
            t = i / max(2, round(length / .115))
            x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            beam('Robot dark mesh wire', (x, y, .25), (x, y, 1.52), .005, dark, panel)
        for z in [.25 + i * .115 for i in range(12)]:
            beam('Robot dark mesh wire', (*a, z), (*b, z), .005, dark, panel)
        return panel

    guard_panel('ROBOT_GUARD_REAR', (2.72, 4.23), (4.32, 4.23), posts=(True, True))
    guard_panel('ROBOT_GUARD_RIGHT', (4.32, 2.25), (4.32, 4.196), posts=(True, False))
    for x in [2.44, 4.32]:
        curtain = group('LIGHT_CURTAIN_' + ('LEFT' if x < 3 else 'RIGHT'), (x, 1.56, 0), cell, dynamic=True)
        box('Light curtain foot', (.18, .18, .025), (0, 0, .0125), graphite, curtain, .004)
        box('Light curtain upright', (.045, .045, 1.37), (0, 0, .71), yellow, curtain, .003)
        box('Light curtain optical strip', (.008, .049, 1.12), (.026 if x < 3 else -.026, 0, .79), dark, curtain, .001)
        for z in [.28 + i * .11 for i in range(10)]:
            cyl('Light curtain optical emitter', .006, .004, (.033 if x < 3 else -.033, 0, z), red, curtain, (0, math.pi / 2, 0), n=8)
    cabinet = group('ROBOT_PLC_CABINET', (4.745, 4.24, 0), cell, typ='robot_plc_cabinet', dynamic=True)
    box('Robot PLC plinth', (.66, .46, .12), (0, 0, .06), graphite, cabinet, .005)
    box('Robot PLC enclosure', (.62, .42, 1.16), (0, 0, .70), white, cabinet, .012)
    box('Robot PLC door', (.56, .018, 1.07), (0, -.221, .70), silver, cabinet, .006)
    box('Robot PLC HMI surround', (.30, .022, .22), (0, -.244, 1.03), graphite, cabinet, .005)
    box('Robot PLC HMI screen', (.25, .005, .17), (0, -.258, 1.03), screen, cabinet, .002)
    cyl('Robot PLC emergency stop', .032, .037, (.19, -.25, .77), red, cabinet, (math.pi / 2, 0, 0), n=20)
    for z in [.36 + i * .035 for i in range(5)]:
        box('Robot PLC ventilation', (.24, .003, .008), (0, -.233, z), dark, cabinet, .001)
    tower = group('ANDON_TOWER_ROBOT', (4.745, 4.24, 0), cell, typ='three_colour_andon', dynamic=True)
    cyl('Andon mast', .021, .86, (0, 0, 1.71), silver, tower, n=16)
    cyl('Andon base', .055, .025, (0, 0, 1.2925), graphite, tower, n=20)
    for name, z, material in [('ANDON_RED', 2.29, red), ('ANDON_AMBER', 2.17, amber), ('ANDON_GREEN', 2.05, green)]:
        ob = cyl(name, .055, .10, (0, 0, z), material, tower, n=24, dynamic=True)
        ob['animation_role'] = 'andon_signal'
        ob['signal_channel'] = name.removeprefix('ANDON_').lower()
    for z in [1.989, 2.11, 2.23, 2.35]:
        cyl('Andon dark separator', .057, .012, (0, 0, z), graphite, tower, n=24)
    tower['state_channels'] = 'Idle:green; Pack:green; Jammed:red; Service:amber'

    # Peripheral industrial logistics bays (West Inbound, East Outbound Shipping, NW Rear Wall)
    # Strictly grounded (min_z = 0.000 m), dynamic=True, outside walk aisles & dock aprons.
    orange = _material('FlexSim / Rack orange', '#e85d04', .12, .36)
    wrap_film = _material('FlexSim / Stretch wrap shroud', '#d7e2ea', .03, .22)
    wood = M['wood']

    def build_safety_bollard(bname, bx, by):
        bl = group(bname, (bx, by, 0.0), details, typ='safety_bollard', dynamic=True)
        box('Bollard base plate', (.22, .22, .018), (0, 0, .009), graphite, bl, .003)
        cyl('Bollard post', .068, 1.02, (0, 0, .528), yellow, bl, n=24)
        for bz in (.74, .90):
            cyl('Bollard hazard band', .070, .055, (0, 0, bz), dark, bl, n=24)
        cyl('Bollard dome cap', .070, .028, (0, 0, 1.052), dark, bl, n=24)
        return bl

    build_safety_bollard('DOCK_01_BOLLARD_01', -17.34, -7.24)
    build_safety_bollard('DOCK_01_BOLLARD_02', -17.34, -3.06)
    build_safety_bollard('DOCK_02_BOLLARD_01', 17.34, -7.24)
    build_safety_bollard('DOCK_02_BOLLARD_02', 17.34, -3.06)

    def build_euro_pallet_base(parent):
        for py in (-0.3275, 0.0, 0.3275):
            box('Euro pallet runner', (1.20, .145, .022), (0, py, .011), wood, parent, .003)
        for px in (-0.5275, 0.0, 0.5275):
            for py in (-0.3275, 0.0, 0.3275):
                box('Euro pallet block', (.145, .145, .078), (px, py, .061), wood, parent, .003)
            box('Euro pallet stringer', (.145, .80, .022), (px, 0, .111), wood, parent, .002)
        for py, pw in [(-0.3275, .145), (-0.16375, .10), (0.0, .145), (0.16375, .10), (0.3275, .145)]:
            box('Euro pallet plank', (1.20, pw, .028), (0, py, .136), wood, parent, .002)

    # 1. West Inbound Receiving Bay: X_b in [-17.15, -15.05], Y_b in [-1.15, +7.50]
    for idx, ry in enumerate((6.45, 3.85), 1):
        rk = group(f'WEST_INBOUND_RACK_{idx:02d}', (-16.55, ry, 0.0), details, typ='pallet_receiving_rack', dynamic=True)
        for rx in (-0.41, 0.41):
            for sy in (-0.98, 0.98):
                box('Receiving rack footplate', (.12, .12, .016), (rx, sy, .008), graphite, rk, .002)
                box('Receiving rack upright', (.055, .055, 2.384), (rx, sy, 1.208), blue, rk, .003)
            for bz in (0.55, 1.35, 2.15):
                beam('Receiving rack end brace', (-0.41, -0.98 if rx < 0 else 0.98, bz - .28),
                     (0.41, -0.98 if rx < 0 else 0.98, bz + .12), .024, blue, rk)
        for lvl, lz in enumerate((0.18, 1.08, 1.96), 1):
            for rx in (-0.41, 0.41):
                box('Receiving rack load beam', (.045, 1.92, .085), (rx, 0.0, lz), orange, rk, .003)
            box('Receiving rack wire deck', (.78, 1.88, .016), (0.0, 0.0, lz + .050), silver, rk, .002)
            for slot_y in (-0.56, 0.0, 0.56):
                if lvl < 3:
                    box('Receiving carton unit', (.52, .42, .32), (0.0, slot_y, lz + .220), kraft, rk, .003)
                    box('Receiving carton strap', (.53, .024, .324), (0.0, slot_y, lz + .220), white, rk, .001)
                else:
                    box('Receiving reserve bin', (.54, .38, .22), (0.0, slot_y, lz + .170), blue, rk, .003)

    for idx, (px, py) in enumerate([(-16.62, -0.55), (-15.52, -0.55), (-16.62, 1.25), (-15.52, 1.25)], 1):
        pst = group(f'INBOUND_PALLET_STACK_{idx:02d}', (px, py, 0.0), details, typ='inbound_flatpack_pallet', dynamic=True)
        pst.rotation_euler = (0.0, 0.0, math.pi / 2)
        build_euro_pallet_base(pst)
        for layer_i in range(5):
            lz = 0.150 + layer_i * 0.115 + 0.055
            box('Flatpack bundle', (1.06, .70, .105), (0.0, 0.0, lz), kraft, pst, .003)
        for sx in (-0.34, 0.34):
            box('Flatpack poly strap', (.022, .712, .585), (sx, 0.0, .442), dark, pst, .001)
        box('Inbound pallet manifest', (.18, .004, .12), (0.0, -.358, .52), white, pst, .001)

    # 2. East Outbound Shipping Marshalling Bay: X_b in [+12.95, +16.95], Y_b in [-2.55, +6.25]
    shipping_coords = [
        (14.30, 1.50), (16.25, 1.50),
        (14.30, 3.65), (16.25, 3.65),
        (14.30, 5.80), (16.25, 5.80),
    ]
    for idx, (sx, sy) in enumerate(shipping_coords, 1):
        spal = group(f'SHIPPING_PALLET_{idx:02d}', (sx, sy, 0.0), details, typ='marshalled_shipping_pallet', dynamic=True)
        build_euro_pallet_base(spal)
        tiers = 2 if idx in (2, 5) else 3
        load_h = tiers * 0.255
        for tier in range(tiers):
            tz = 0.150 + tier * 0.255 + 0.125
            for cx in (-0.27, 0.27):
                for cy in (-0.17, 0.17):
                    box('Marshalled parcel', (.48, .31, .245), (cx, cy, tz), kraft, spal, .003)
        box('Stretch wrap shroud', (1.06, .68, load_h - .02), (0.0, 0.0, .150 + load_h * .5), wrap_film, spal, .006)
        for strap_x in (-0.30, 0.30):
            box('Shipping strap band', (.020, .692, load_h + .01), (strap_x, 0.0, .150 + load_h * .5), green, spal, .001)
        box('Shipping bay placard', (.20, .005, .14), (0.0, -.346, .150 + load_h * .62), white, spal, .001)

    wrapper = group('PALLET_STRETCH_WRAPPER', (15.85, -1.65, 0.0), details, typ='turntable_stretch_wrapper', dynamic=True)
    cyl('Wrapper base frame', .82, .036, (0.0, 0.0, .018), graphite, wrapper, n=36)
    cyl('Wrapper turntable platter', .76, .018, (0.0, 0.0, .045), blue, wrapper, n=36, dynamic=True)
    box('Wrapper approach ramp', (.46, .74, .024), (-0.92, 0.0, .012), yellow, wrapper, .003)
    box('Wrapper mast bridge', (.42, .34, .036), (.74, 0.0, .018), graphite, wrapper, .003)
    box('Wrapper mast column', (.18, .22, 2.22), (.84, 0.0, 1.146), graphite, wrapper, .006)
    box('Wrapper film carriage', (.16, .28, .44), (.71, -.16, 1.05), blue, wrapper, .005, dynamic=True)
    cyl('Wrapper stretch film roll', .085, .38, (.71, -.29, 1.05), wrap_film, wrapper, n=24)
    box('Wrapper HMI box', (.14, .22, .28), (.84, -.21, 1.42), white, wrapper, .005)
    box('Wrapper HMI screen', (.006, .15, .12), (.768, -.21, 1.45), screen, wrapper, .002)

    podium = group('SHIPPING_MANIFEST_PODIUM', (13.35, -1.85, 0.0), details, typ='shipping_manifest_podium', dynamic=True)
    box('Podium base plinth', (.74, .56, .030), (0.0, 0.0, .015), graphite, podium, .003)
    box('Podium cabinet body', (.68, .50, .96), (0.0, 0.0, .510), blue, podium, .006)
    box('Podium writing top', (.76, .58, .032), (0.0, 0.0, 1.006), white, podium, .004)
    box('Podium rear riser', (.76, .16, .16), (0.0, .20, 1.102), graphite, podium, .004)
    box('Manifest label printer', (.24, .26, .17), (-.20, .04, 1.107), dark, podium, .005)
    cyl('Manifest monitor post', .018, .26, (.18, .18, 1.15), silver, podium, n=16)
    box('Manifest monitor panel', (.34, .024, .22), (.18, .14, 1.30), graphite, podium, .004)
    box('Manifest monitor screen', (.30, .005, .18), (.18, .126, 1.30), screen, podium, .002)

    # 3. North-West Rear Wall: X_b in [-13.68, -10.89], Y_b in [+7.66, +8.34]
    # Strictly between X=-14 and X=-10 rear columns (Y_min=8.55) and north of Y_b=+7.55.
    nw_rack = group('NW_TOTE_RETURN_RACK', (-12.90, 8.00, 0.0), details, typ='empty_tote_return_rack', dynamic=True)
    for rx in (-0.74, 0.74):
        for ry in (-0.30, 0.30):
            box('Tote return footplate', (.08, .08, .016), (rx, ry, .008), graphite, nw_rack, .002)
            box('Tote return upright', (.042, .042, 1.72), (rx, ry, .876), blue, nw_rack, .003)
    for lz in (0.28, 0.92, 1.52):
        for ry in (-0.30, 0.30):
            box('Tote return shelf beam', (1.48, .036, .055), (0.0, ry, lz), orange, nw_rack, .002)
        box('Tote return deck', (1.42, .56, .014), (0.0, 0.0, lz + .034), silver, nw_rack, .002)
        for bx in (-0.44, 0.0, 0.44):
            box('Empty return bin', (.40, .48, .18), (bx, 0.0, lz + .132), blue, nw_rack, .003)

    nw_cab = group('NW_CHARGING_CABINET', (-11.35, 8.02, 0.0), details, typ='battery_charging_cabinet', dynamic=True)
    box('Charging cabinet plinth', (.92, .60, .08), (0.0, 0.0, .040), graphite, nw_cab, .004)
    box('Charging cabinet body', (.88, .56, 1.54), (0.0, 0.0, .850), yellow, nw_cab, .008)
    for dx in (-0.21, 0.21):
        box('Charging cabinet door', (.40, .016, 1.42), (dx, -.288, .850), graphite, nw_cab, .004)
        box('Charging door handle', (.022, .024, .14), (dx * .25, -.306, .860), silver, nw_cab, .002)
    for idx, (lx, mat_led) in enumerate([(-.26, green), (-.18, green), (-.10, amber)], 1):
        cyl(f'Charging indicator {idx:02d}', .010, .008, (lx, -.298, 1.46), mat_led, nw_cab, (math.pi / 2, 0, 0), n=12)

    # Rear free sector becomes a compact management and rest island.
    island = group('BREAK_AND_KPI_ZONE', (9.0, 7.75, 0), rest, typ='break_and_shift_control', dynamic=True)
    bench = group('BREAK_BENCH', (-.65, -.15, 0), island, dynamic=True)
    for x in [-.72, .72]:
        for y in [-.18, .18]:
            box('Break bench leg', (.045, .045, .44), (x, y, .22), graphite, bench, .003)
    for y in [-.17, -.055, .06, .175]:
        box('Break bench seat slat', (1.68, .095, .035), (0, y, .4575), blue, bench, .006)
    for x in [-.72, .72]:
        box('Break bench back support', (.035, .035, .45), (x, .205, .65), graphite, bench, .003)
    for z in [.68, .83]:
        box('Break bench backrest', (1.68, .036, .12), (0, .21, z), blue, bench, .006)
    cooler = group('WATER_COOLER', (1.24, .03, 0), island, dynamic=True)
    box('Water cooler plinth', (.36, .34, .02), (0, 0, .01), graphite, cooler, .003)
    box('Water cooler body', (.36, .34, .94), (0, 0, .49), white, cooler, .025)
    box('Water cooler drip recess', (.22, .01, .22), (0, -.176, .69), graphite, cooler, .008)
    box('Water cooler drip tray', (.22, .15, .018), (0, -.20, .58), silver, cooler, .003)
    for x, material in [(-.06, blue), (.06, red)]:
        cyl('Water cooler tap', .016, .04, (x, -.19, .77), material, cooler, (math.pi / 2, 0, 0), n=12)
    cyl('Water bottle', .14, .28, (0, 0, 1.10), cyan, cooler, n=20)
    cyl('Water bottle neck', .055, .08, (0, 0, .96), silver, cooler, n=16)
    board = group('SQDC_KPI_BOARD', (-.35, .91, 0), island, dynamic=True)
    box('SQDC KPI board frame', (2.50, .065, 1.03), (0, 0, 1.90), graphite, board, .012)
    box('SQDC KPI whiteboard', (2.40, .008, .93), (0, -.039, 1.90), white, board, .002)
    text('KPI board heading', 'SHIFT CONTROL / SQDC', .093, (-1.10, -.045, 2.22), blue, board, (math.pi / 2, 0, 0))
    for i, (letter, material) in enumerate([('S', green), ('Q', blue), ('D', amber), ('C', red)]):
        x = -.87 + i * .58
        box('SQDC channel header', (.48, .006, .25), (x, -.047, 1.99), material, board, .002)
        text('SQDC channel ' + letter, letter, .17, (x, -.052, 1.93), white, board, (math.pi / 2, 0, 0), 'CENTER')
        for row in range(3):
            box('SQDC blank metric row', (.46, .003, .008), (x, -.048, 1.77 - row * .09), silver, board, 0)

    # Unobstructed ceiling contract (2026-11-15T02:42:13Z):
    # Keep ENV_OVERHEAD strictly as an empty UI-layer container (0 mesh descendants) and purge any
    # physical ceiling beams, trusses, rafters, cable trays, or hanging lamp fixtures while keeping
    # invisible Blender LIGHT objects active.
    overhead_descendants = set(overhead.children_recursive)
    for stale in list(bpy.data.objects):
        if stale == overhead or stale.type == 'LIGHT':
            continue
        if stale in overhead_descendants or stale.name.startswith((
            'OVERHEAD_TRUSS', 'OVERHEAD_CABLE_TRAY', 'HIGH_BAY_LED', 'HIGHBAY_', 'ENV_LIGHTING_RIG',
            'Truss longitudinal chord', 'Truss diagonal web', 'High bay LED', 'High bay suspension',
            'Cable tray ',
        )):
            bpy.data.objects.remove(stale, do_unlink=True)

    # Native collections and GLB roots expose exactly the same UI toggle layers.
    for name, (root, col) in layers.items():
        for ob in [root] + list(root.children_recursive):
            if col not in ob.users_collection:
                col.objects.link(ob)
            for old in list(ob.users_collection):
                if old != col:
                    old.objects.unlink(ob)
            ob['environment_layer'] = name
    return {name: {'root': name, 'objects': len(col.objects)} for name, (_, col) in layers.items()}
