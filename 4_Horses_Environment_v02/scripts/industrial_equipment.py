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


def build_docks_and_cutaway(api, walls, width=36, depth=18):
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
    # Front side walls stay low for an unobstructed cutaway; both gates
    # open onto the same continuous front aisle.
    # Each dock is a real gap between two wall sections; the sectional leaf is
    # modelled in that gap and does not overlap a hidden solid wall.
    for side, number, label in [(-1, '01', 'INBOUND'), (1, '02', 'DISPATCH')]:
        x = side * (width / 2 - .15)
        dock = group('DOCK_' + number, (x, -5.15, 0), walls, typ='sectional_dock')
        dock['dock_label'] = 'DOCK ' + number + ' - ' + label
        # 3.6 m clear doorway around aisle center y=-5.15.
        for lo, hi, height in [(-depth / 2 + .15, -6.95, .32),
                               (-3.35, .30, .32), (.30, depth / 2 - .15, 3.6)]:
            cy, span = (lo + hi) / 2, hi - lo
            box('Cutaway side wall', (.13, span, height), (x, cy, height / 2), wall, walls, .007)
            box('Side wall skirting', (.18, span, .16), (x - side * .025, cy, .08), graphite, walls, .003)
        box('Dock overdoor lintel', (.16, 3.6, .65), (0, 0, 3.275), wall, dock, .006)
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
    jack = group('PALLET_JACK', (-width / 2 + 1.15, -2.8, 0), walls, typ='hydraulic_pallet_jack')
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
    prep = group('PREP_TOOLING', (-10.17, 1.65, 0), details)
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
    robot_table = bpy.data.objects.get('VIS_ROBOT_PACK_TABLE')
    if robot_table:
        for ob in list(robot_table.children):
            if ob.type == 'MESH' and ob.name.startswith('VIS_Bench_top'):
                bpy.data.objects.remove(ob, do_unlink=True)
        chamfered_slab('VIS_Bench_top_robot_chamfer', [(-.31, -.57), (.55, -.57),
                        (.55, .47), (-.55, .47), (-.55, -.33)], .825, .86,
                       white, robot_table)

    # The QC scale replaces a region of the old top; its top is exactly .86 m.
    table = bpy.data.objects.get('VIS_STAGE_4_TABLE')
    if table:
        for ob in list(table.children):
            if ob.type == 'MESH' and ob.name.startswith('VIS_Bench_top'):
                bpy.data.objects.remove(ob, do_unlink=True)
    qc = group('QC_TABLE_TOOLING', (6, 2.7, 0), details)
    # Match the expanded manual_bench envelope x ±.55, y[-.57,.47].
    # The scale aperture occupies x ±.28 and y[-.57,-.08].
    chamfered_slab('QC worktop surround', [(-.55, -.57), (-.28, -.57),
                    (-.28, -.08), (.28, -.08), (.28, -.57), (.55, -.57),
                    (.55, .47), (-.55, .47)], .825, .86, white, qc)
    box('QC_SCALE_FLUSH', (.552, .482, .028), (0, -.325, .846), silver, qc, .004)
    # Four millimetres of open clearance around the scale avoid intersecting
    # volumes and coincident interface faces in the tabletop surround.
    box('QC scale base', (.49, .39, .05), (0, -.315, .807), graphite, qc, .004)
    terminal = group('QC_TERMINAL', (.48, .31, 0), qc)
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

    # Reinforcement and corner guides stay outside robot order/tray envelope.
    robot = group('ROBOT_TABLE_REINFORCEMENT', (3.5, 2.7, 0), details)
    for x in [-.47, .47]:
        box('Robot table reinforced leg', (.065, .065, .78), (x, .30, .42), graphite, robot, .004)
        beam('Robot table diagonal', (x, -.32, .10), (x, .30, .79), .025, graphite, robot)
    for x in [-.485, .485]:
        for y in [-.40, .39]:
            if x < 0 and y < 0:
                # Keep this guide on the retained front-west chamfer land.
                y = -.25
            box('Robot corner guide X', (.10, .018, .025), (x - math.copysign(.04, x), y, .8725), yellow, robot, .002)
            box('Robot corner guide Y', (.018, .10, .025), (x, y - math.copysign(.04, y), .8725), yellow, robot, .002)

    # Rear and right mesh guards. Front is fully open for the overview;
    # helper entry is also clear of VIS_ROBOT_ASSIST (2.8,1.95,0).
    def guard_panel(name, a, b):
        panel = group(name, (0, 0, 0), cell)
        for x, y in [a, b]:
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

    guard_panel('ROBOT_GUARD_REAR', (2.72, 4.23), (4.72, 4.23))
    guard_panel('ROBOT_GUARD_RIGHT', (4.72, 2.25), (4.72, 4.23))
    for x in [2.44, 4.72]:
        curtain = group('LIGHT_CURTAIN_' + ('LEFT' if x < 3 else 'RIGHT'), (x, 1.45, 0), cell)
        box('Light curtain foot', (.18, .18, .025), (0, 0, .0125), graphite, curtain, .004)
        box('Light curtain upright', (.045, .045, 1.37), (0, 0, .71), yellow, curtain, .003)
        box('Light curtain optical strip', (.008, .049, 1.12), (.026 if x < 3 else -.026, 0, .79), dark, curtain, .001)
        for z in [.28 + i * .11 for i in range(10)]:
            cyl('Light curtain optical emitter', .006, .004, (.033 if x < 3 else -.033, 0, z), red, curtain, (0, math.pi / 2, 0), n=8)
    cabinet = group('ROBOT_PLC_CABINET', (5.18, 4.24, 0), cell, typ='robot_plc_cabinet')
    box('Robot PLC plinth', (.66, .46, .12), (0, 0, .06), graphite, cabinet, .005)
    box('Robot PLC enclosure', (.62, .42, 1.16), (0, 0, .70), white, cabinet, .012)
    box('Robot PLC door', (.56, .018, 1.07), (0, -.221, .70), silver, cabinet, .006)
    box('Robot PLC HMI surround', (.30, .022, .22), (0, -.244, 1.03), graphite, cabinet, .005)
    box('Robot PLC HMI screen', (.25, .005, .17), (0, -.258, 1.03), screen, cabinet, .002)
    cyl('Robot PLC emergency stop', .032, .037, (.19, -.25, .77), red, cabinet, (math.pi / 2, 0, 0), n=20)
    for z in [.36 + i * .035 for i in range(5)]:
        box('Robot PLC ventilation', (.24, .003, .008), (0, -.233, z), dark, cabinet, .001)
    tower = group('ANDON_TOWER_ROBOT', (5.18, 4.24, 0), cell, typ='three_colour_andon')
    cyl('Andon mast', .021, .86, (0, 0, 1.71), silver, tower, n=16)
    cyl('Andon base', .055, .025, (0, 0, 1.2925), graphite, tower, n=20)
    for name, z, material in [('ANDON_RED', 2.29, red), ('ANDON_AMBER', 2.17, amber), ('ANDON_GREEN', 2.05, green)]:
        ob = cyl(name, .055, .10, (0, 0, z), material, tower, n=24, dynamic=True)
        ob['animation_role'] = 'andon_signal'
        ob['signal_channel'] = name.removeprefix('ANDON_').lower()
    for z in [1.989, 2.11, 2.23, 2.35]:
        cyl('Andon dark separator', .057, .012, (0, 0, z), graphite, tower, n=24)
    tower['state_channels'] = 'Idle:green; Pack:green; Jammed:red; Service:amber'

    # Rear free sector becomes a compact management and rest island.
    island = group('BREAK_AND_KPI_ZONE', (9.0, 7.75, 0), rest, typ='break_and_shift_control')
    bench = group('BREAK_BENCH', (-.65, -.15, 0), island)
    for x in [-.72, .72]:
        for y in [-.18, .18]:
            box('Break bench leg', (.045, .045, .44), (x, y, .22), graphite, bench, .003)
    for y in [-.17, -.055, .06, .175]:
        box('Break bench seat slat', (1.68, .095, .035), (0, y, .4575), blue, bench, .006)
    for x in [-.72, .72]:
        box('Break bench back support', (.035, .035, .45), (x, .205, .65), graphite, bench, .003)
    for z in [.68, .83]:
        box('Break bench backrest', (1.68, .036, .12), (0, .21, z), blue, bench, .006)
    cooler = group('WATER_COOLER', (1.24, .03, 0), island)
    box('Water cooler body', (.36, .34, .94), (0, 0, .49), white, cooler, .025)
    box('Water cooler drip recess', (.22, .01, .22), (0, -.176, .69), graphite, cooler, .008)
    box('Water cooler drip tray', (.22, .15, .018), (0, -.20, .58), silver, cooler, .003)
    for x, material in [(-.06, blue), (.06, red)]:
        cyl('Water cooler tap', .016, .04, (x, -.19, .77), material, cooler, (math.pi / 2, 0, 0), n=12)
    cyl('Water bottle', .14, .28, (0, 0, 1.10), cyan, cooler, n=20)
    cyl('Water bottle neck', .055, .08, (0, 0, .96), silver, cooler, n=16)
    board = group('SQDC_KPI_BOARD', (-.35, .91, 0), island)
    box('SQDC KPI board frame', (2.50, .065, 1.03), (0, 0, 1.90), graphite, board, .012)
    box('SQDC KPI whiteboard', (2.40, .008, .93), (0, -.039, 1.90), white, board, .002)
    text('KPI board heading', 'SHIFT CONTROL / SQDC', .093, (-1.10, -.045, 2.22), blue, board, (math.pi / 2, 0, 0))
    for i, (letter, material) in enumerate([('S', green), ('Q', blue), ('D', amber), ('C', red)]):
        x = -.87 + i * .58
        box('SQDC channel header', (.48, .006, .25), (x, -.047, 1.99), material, board, .002)
        text('SQDC channel ' + letter, letter, .17, (x, -.052, 1.93), white, board, (math.pi / 2, 0, 0), 'CENTER')
        for row in range(3):
            box('SQDC blank metric row', (.46, .003, .008), (x, -.048, 1.77 - row * .09), silver, board, 0)

    # Separate upper layer: three economical trusses and a cable tray above line.
    for index, y in enumerate([-1.35, 3.80, 7.15], 1):
        truss = group('OVERHEAD_TRUSS_' + str(index).zfill(2), (0, y, 0), overhead, typ='light_steel_truss')
        for z in [3.42, 3.68]:
            beam('Truss longitudinal chord', (-13.8, 0, z), (13.8, 0, z), .035, graphite, truss)
        for i in range(23):
            x = -13.8 + i * 1.2
            beam('Truss diagonal web', (x, 0, 3.42 if i % 2 == 0 else 3.68),
                 (x + 1.2, 0, 3.68 if i % 2 == 0 else 3.42), .018, silver, truss)
        for x in [-10.0, -5.0, 0, 5.0, 10.0]:
            lamp = group('HIGH_BAY_LED', (x, 0, 3.32), truss, typ='linear_high_bay_led')
            box('High bay LED housing', (1.20, .15, .075), (0, 0, 0), graphite, lamp, .005)
            box('High bay LED diffuser', (1.11, .123, .008), (0, 0, -.0415), led, lamp, .002)
            for xx in [-.4, .4]:
                beam('High bay suspension', (xx, 0, .0375), (xx, 0, .10), .007, silver, lamp)
    tray = group('OVERHEAD_CABLE_TRAY', (0, .62, 0), overhead)
    for y in [-.12, .12]:
        beam('Cable tray side rail', (-9.4, y, 3.24), (9.4, y, 3.24), .035, yellow, tray)
    for i in range(48):
        x = -9.4 + i * .4
        beam('Cable tray rung', (x, -.12, 3.24), (x, .12, 3.24), .014, yellow, tray)
    for x in [-8, 0, 8]:
        beam('Cable tray hanger', (x, 0, 3.24), (x, 0, 3.65), .015, silver, tray)

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
