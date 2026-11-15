// Validate the delivered 30-FPS character and interaction-object GLBs in animations_frame_by_frame/
// and verify 100% synchronization with modules/{warehouse_worker,humanoid_robot}.glb.
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import validator from 'gltf-validator';

const defaultOutput = fileURLToPath(new URL('../animations_frame_by_frame/', import.meta.url));
const output = path.resolve(process.argv[2] || defaultOutput);
const FPS = 30;
const TIME_TOLERANCE = 3e-5;
const MATRIX_TOLERANCE = 3e-5;
const CONTACT_LIMIT_M = 0.020;
const REQUIRED_PROPS = [
  'prop_closed', 'prop_shell', 'prop_flap_front', 'prop_flap_back',
  'prop_flap_left', 'prop_flap_right', 'prop_item', 'prop_tote', 'prop_tape',
];
const ALL_PROP_BONES = ['prop_box', 'prop_stand', ...REQUIRED_PROPS];
const EXPECTED_BONES = {worker: 35, robot: 41};
const BASE = ['Idle', 'Walk', 'CarryIdle', 'Reach', 'PickUp', 'PlaceDown', 'CarryWalk'];
const EXPECTED = {
  worker: [...BASE, 'Prepare', 'Pick', 'Pack', 'Inspect', 'Assist', 'Break', 'Prepare_Oversize', 'Pick_Oversize', 'Pack_Oversize', 'Inspect_Oversize'],
  robot: [...BASE, 'RobotPack', 'Jammed', 'Service', 'Offline', 'RobotPack_Oversize', 'Jammed_Oversize', 'Service_Oversize'],
};
const EMPTY_HANDED = new Set(['Idle', 'Walk', 'Reach', 'Assist', 'Break', 'Offline']);
const MOTION_THRESHOLDS = {
  Assist: 0.22,
  Break: 0.15,
  Service: 0.12,
  Service_Oversize: 0.12,
  Jammed: 0.03,
  Jammed_Oversize: 0.03,
  Offline: 0.01,
};

const errors = [];
const report = {
  passed: false,
  fps: FPS,
  assets: [],
  hidden_props: [],
  motion: [],
  contacts: [],
  bounds_and_joints: [],
  modules_sync: [],
  synchronization: [],
  errors,
};

function check(condition, message) {
  if (!condition) errors.push(message);
  return condition;
}
function finite(values) {
  return Array.from(values).every(Number.isFinite);
}
const maxMatrixDifference = (a, b) => Math.max(...a.elements.map((value, i) => Math.abs(value - b.elements[i])));

function worldRotation(node) {
  const chain = [];
  for (let current = node; current; current = current.parent) chain.push(current.quaternion);
  const result = new THREE.Quaternion();
  for (const quaternion of chain.reverse()) result.multiply(quaternion);
  return result.normalize();
}

function glbData(bytes) {
  if (bytes.readUInt32LE(0) !== 0x46546c67 || bytes.readUInt32LE(4) !== 2) throw new Error('Expected a glTF 2.0 binary file');
  let document, binary;
  for (let offset = 12; offset < bytes.length;) {
    const length = bytes.readUInt32LE(offset), type = bytes.readUInt32LE(offset + 4);
    const chunk = bytes.subarray(offset + 8, offset + 8 + length);
    if (type === 0x4e4f534a) document = JSON.parse(chunk.toString('utf8').replace(/[\u0000\s]+$/, ''));
    if (type === 0x004e4942) binary = chunk;
    offset += 8 + length;
  }
  if (!document || !binary) throw new Error('Missing JSON or BIN chunk');
  return {document, binary};
}

function scalarFloats(document, binary, index) {
  const accessor = document.accessors[index], view = document.bufferViews[accessor.bufferView];
  if (accessor.componentType !== 5126 || accessor.type !== 'SCALAR' || accessor.sparse) throw new Error(`Unsupported animation-time accessor ${index}`);
  const start = (view.byteOffset || 0) + (accessor.byteOffset || 0), stride = view.byteStride || 4;
  return Array.from({length: accessor.count}, (_, i) => binary.readFloatLE(start + i * stride));
}

function checkCadence(file, document, binary) {
  return (document.animations || []).map(animation => {
    const samplers = animation.samplers.map(s => scalarFloats(document, binary, s.input));
    const duration = Math.max(...samplers.map(times => times.at(-1)));
    const intervals = Math.round(duration * FPS), expectedSamples = intervals + 1;
    const sparse = [], invalid = [];
    for (let i = 0; i < samplers.length; i++) {
      const times = samplers[i];
      if (times.length !== expectedSamples) sparse.push({sampler: i, samples: times.length});
      const bad = times.findIndex((t, frame) => !Number.isFinite(t) || Math.abs(t - frame / FPS) > TIME_TOLERANCE);
      if (bad !== -1) invalid.push({sampler: i, sample: bad, time: times[bad]});
    }
    check(Math.abs(duration - intervals / FPS) < TIME_TOLERANCE, `${file}/${animation.name}: duration is not an integer number of 30 FPS frames`);
    check(sparse.length === 0, `${file}/${animation.name}: ${sparse.length} samplers lack full per-frame keys`);
    check(invalid.length === 0, `${file}/${animation.name}: ${invalid.length} samplers do not follow the 30 FPS frame grid`);
    return {clip: animation.name, duration_seconds: duration, expected_samples_per_sampler: expectedSamples, samplers: samplers.length};
  });
}

function checkAssetLayout(file, document, gltf, kind) {
  const propsOnly = file.startsWith('interaction_objects_');
  const forbidden = (document.nodes || [])
    .filter(n => /DemoSupport|_DemoCarton|^FBF_/i.test(n.name || '') || n.extras?.handling_prop || n.extras?.demo_only)
    .map(n => n.name || '(unnamed)');
  check(forbidden.length === 0, `${file}: forbidden demo/FBF/handling_prop nodes: ${forbidden.join(', ')}`);

  const meshNodes = (document.nodes || []).filter(node => node.mesh !== undefined);
  const unexpected = meshNodes.filter(node => {
    const extras = node.extras || {};
    const meshExtras = document.meshes[node.mesh]?.extras || {};
    if (extras.operation_prop === true && meshExtras.operation_prop === true) {
      return !ALL_PROP_BONES.includes(extras.prop_role) || extras[kind + '_asset'] !== true;
    }
    return propsOnly || extras[kind + '_asset'] !== true;
  }).map(node => node.name || '(unnamed mesh)');

  let unweightedVerts = 0;
  gltf.scene.traverse(ob => {
    if (!ob.isSkinnedMesh) return;
    const wAttr = ob.geometry.attributes.skinWeight;
    check(Boolean(wAttr), `${file}/${ob.name}: missing skinWeight attribute`);
    if (!wAttr) return;
    for (let i = 0; i < wAttr.count; i++) {
      const sum = wAttr.getX(i) + wAttr.getY(i) + wAttr.getZ(i) + wAttr.getW(i);
      if (!Number.isFinite(sum) || Math.abs(sum - 1) > 1e-3) unweightedVerts++;
    }
  });
  check(unweightedVerts === 0, `${file}: ${unweightedVerts} unweighted/unnormalized skinned vertices`);
  check(document.scenes.length === 1, `${file}: exported ${document.scenes.length} scenes instead of 1`);
  check(unexpected.length === 0, `${file}: unexpected or untagged meshes: ${unexpected.join(', ')}`);
  return {scenes: document.scenes.length, raw_mesh_nodes: meshNodes.length, objects_only: propsOnly, unweighted_vertices: unweightedVerts, unexpected_meshes: unexpected};
}

function player(gltf) {
  const mixer = new THREE.AnimationMixer(gltf.scene);
  let action;
  return {
    start(clip) {
      mixer.stopAllAction();
      action = mixer.clipAction(clip);
      action.reset().setLoop(THREE.LoopOnce, 1);
      action.clampWhenFinished = true;
      action.play();
    },
    at(time) { mixer.setTime(time); gltf.scene.updateMatrixWorld(true); },
    stop() { mixer.stopAllAction(); mixer.uncacheRoot(gltf.scene); },
  };
}

function checkFiniteFrames(file, gltf) {
  const playback = player(gltf), rows = [];
  const nodes = [];
  gltf.scene.traverse(node => nodes.push(node));
  for (const clip of gltf.animations) {
    let frameCount = 0, matrixChecks = 0, problem = null;
    for (const track of clip.tracks) check(finite(track.times) && finite(track.values), `${file}/${clip.name}/${track.name}: non-finite animation data`);
    playback.start(clip);
    const frames = Math.round(clip.duration * FPS);
    for (let frame = 0; frame <= frames; frame++) {
      playback.at(frame / FPS);
      frameCount++;
      for (const node of nodes) {
        matrixChecks++;
        if (!finite(node.matrixWorld.elements)) { problem = `${node.name || node.type} at frame ${frame}`; break; }
      }
      if (problem) break;
    }
    check(!problem, `${file}/${clip.name}: non-finite world transform on ${problem}`);
    rows.push({clip: clip.name, frames_checked: frameCount, node_matrices_checked: matrixChecks, finite: !problem});
  }
  playback.stop();
  return rows;
}

function checkHiddenProps(kind, gltf) {
  const playback = player(gltf);
  const ws = new THREE.Vector3();
  let checkedFrames = 0, violations = 0;
  for (const clip of gltf.animations) {
    playback.start(clip);
    const frames = Math.round(clip.duration * FPS);
    const emptyHanded = EMPTY_HANDED.has(clip.name);
    for (let frame = 0; frame <= frames; frame++) {
      playback.at(frame / FPS);
      checkedFrames++;
      const stand = gltf.scene.getObjectByName('prop_stand');
      if (stand && (stand.scale.length() > 1e-6 || stand.getWorldScale(ws).length() > 1e-6)) violations++;
      if (emptyHanded) {
        for (const pname of ALL_PROP_BONES) {
          const b = gltf.scene.getObjectByName(pname);
          if (b && (b.scale.length() > 1e-6 || b.getWorldScale(ws).length() > 1e-6)) violations++;
        }
      }
    }
  }
  playback.stop();
  check(violations === 0, `${kind}: ${violations} non-zero prop bone scale violations in empty-handed / prop_stand checks`);
  report.hidden_props.push({character: kind, frames_checked: checkedFrames, violations});
}

function motionSamples(gltf, clip, boneNames) {
  const playback = player(gltf), result = Object.fromEntries(boneNames.map(name => [name, []]));
  playback.start(clip);
  const frames = Math.round(clip.duration * FPS);
  for (let frame = 0; frame <= frames; frame++) {
    playback.at(frame / FPS);
    for (const name of boneNames) {
      const node = gltf.scene.getObjectByName(name);
      if (!node) continue;
      result[name].push({position: node.getWorldPosition(new THREE.Vector3()), quaternion: worldRotation(node), scale: node.scale.clone()});
    }
  }
  playback.stop();
  return result;
}

function motionRange(samples) {
  if (!samples.length) return {position_m: 0, rotation_rad: 0, scale: 0};
  const positions = new THREE.Box3(), scales = new THREE.Box3();
  let rotation = 0;
  for (const sample of samples) {
    positions.expandByPoint(sample.position);
    scales.expandByPoint(sample.scale);
    rotation = Math.max(rotation, samples[0].quaternion.angleTo(sample.quaternion));
  }
  return {position_m: positions.getSize(new THREE.Vector3()).length(), rotation_rad: rotation, scale: scales.getSize(new THREE.Vector3()).length()};
}

function checkClipAndInteractionMotion(kind, gltf) {
  const bodyBoneNames = [];
  gltf.scene.traverse(n => { if (n.isBone && !n.name.startsWith('prop_')) bodyBoneNames.push(n.name); });
  for (const clip of gltf.animations) {
    const samples = motionSamples(gltf, clip, bodyBoneNames);
    const maxBodyDeltaM = Math.max(...bodyBoneNames.map(b => motionRange(samples[b]).position_m));
    const minReq = MOTION_THRESHOLDS[clip.name] ?? 0.002;
    check(maxBodyDeltaM >= minReq, `${kind}/${clip.name}: max body bone motion ${maxBodyDeltaM.toFixed(4)} m < required ${minReq} m`);
    report.motion.push({character: kind, clip: clip.name, max_body_delta_m: +maxBodyDeltaM.toFixed(5), required_min_m: minReq});
  }

  for (const suffix of ['', '_Oversize']) {
    const pick = gltf.animations.find(clip => clip.name === 'Pick' + suffix);
    if (pick) {
      const range = motionRange(motionSamples(gltf, pick, ['prop_item']).prop_item);
      check(range.position_m > .04, `${kind}/${pick.name}: the picked item does not travel between the tote and carton`);
    }
    const pack = gltf.animations.find(clip => clip.name === (kind === 'worker' ? 'Pack' : 'RobotPack') + suffix);
    if (pack) {
      const names = ['prop_flap_front', 'prop_flap_back', 'prop_flap_left', 'prop_flap_right', 'prop_tape'];
      const samples = motionSamples(gltf, pack, names), ranges = Object.fromEntries(names.map(name => [name, motionRange(samples[name])]));
      for (const name of names.slice(0, 4)) check(ranges[name].rotation_rad > .15, `${kind}/${pack.name}: ${name} does not fold`);
      check(ranges.prop_tape.position_m > .015, `${kind}/${pack.name}: tape position does not animate`);
      check(ranges.prop_tape.scale > .05, `${kind}/${pack.name}: tape application scale does not animate`);
    }
    const inspect = gltf.animations.find(clip => clip.name === 'Inspect' + suffix);
    if (inspect) {
      const samples = motionSamples(gltf, inspect, ['prop_closed', 'prop_shell']);
      const ranges = Object.fromEntries(Object.entries(samples).map(([name, values]) => [name, motionRange(values)]));
      check(Object.values(ranges).some(range => range.position_m > .025 && range.rotation_rad > .08), `${kind}/${inspect.name}: carton needs both translation and rotation`);
    }
  }
}

function checkContacts(kind, gltf) {
  const playback = player(gltf);
  const anchors = Object.fromEntries(['L', 'R'].map(side => {
    const name = `ATTACH_${kind.toUpperCase()}_HAND_${side}`;
    return [side, gltf.scene.getObjectByName(name)];
  }));
  for (const [side, anchor] of Object.entries(anchors)) check(Boolean(anchor), `${kind}: missing ${side} palm attachment`);
  if (!anchors.L || !anchors.R) { playback.stop(); return; }

  const contactClips = gltf.animations.filter(clip => /^(Inspect|Pick|CarryIdle|CarryWalk|PickUp|PlaceDown)(?:_Oversize)?$/.test(clip.name));
  for (const clip of contactClips) {
    playback.start(clip);
    const oversize = clip.name.endsWith('_Oversize');
    const isPick = clip.name.startsWith('Pick') && !clip.name.startsWith('PickUp');
    const isInspect = clip.name.startsWith('Inspect');
    const width = oversize ? .48 : .36;
    const carton = gltf.scene.getObjectByName(isPick ? 'prop_shell' : 'prop_closed');
    const item = gltf.scene.getObjectByName('prop_item');
    if (!carton || !item) continue;
    let maximumError = 0, minimumNormalDot = 1, contactChecks = 0;
    const totalFrames = Math.round(clip.duration * FPS);
    for (let frame = 0; frame <= totalFrames; frame++) {
      const phase = frame / totalFrames;
      if (clip.name === 'PickUp' && phase < 0.50) continue;
      if (clip.name === 'PlaceDown' && phase > 0.50) continue;
      playback.at(frame / FPS);
      for (const [side, sign] of [['L', 1], ['R', -1]]) {
        if (isPick && side === 'L' && (phase < .15 || phase > .66)) continue;
        const prop = isPick && side === 'L' ? item : carton;
        const rotation = worldRotation(prop);
        const offset = isPick && side === 'L' ? new THREE.Vector3(.0425, .012, 0) : new THREE.Vector3(sign * width / 2, .025, 0);
        const desired = prop.getWorldPosition(new THREE.Vector3()).add(offset.applyQuaternion(rotation));
        const actual = anchors[side].getWorldPosition(new THREE.Vector3());
        maximumError = Math.max(maximumError, desired.distanceTo(actual));
        const normal = new THREE.Vector3(1, 0, 0).transformDirection(anchors[side].matrixWorld);
        const expectedNormal = new THREE.Vector3(-sign, 0, 0).applyQuaternion(rotation);
        minimumNormalDot = Math.min(minimumNormalDot, normal.dot(expectedNormal));
        contactChecks++;
      }
      if ((isInspect || clip.name === 'PickUp') && frame === 0) {
        const closedMesh = gltf.scene.getObjectByName(`${kind.toUpperCase()}_ClosedCarton`);
        if (closedMesh) {
          closedMesh.traverse(n => { if (n.isSkinnedMesh) n.skeleton.update(); });
          const box = new THREE.Box3().setFromObject(closedMesh, true);
          const size = box.getSize(new THREE.Vector3());
          const expected = oversize ? [.48, .32, .34] : [.36, .25, .28];
          check(size.toArray().every((value, axis) => Math.abs(value - expected[axis]) < .004), `${kind}/${clip.name}: carton dimensions ${size.toArray()} differ from ${expected}`);
          check(Math.abs(box.min.y - 0.86) < 0.01, `${kind}/${clip.name}: carton bottom ${box.min.y} m != 0.86 m workstation height`);
        }
      }
    }
    check(maximumError <= CONTACT_LIMIT_M, `${kind}/${clip.name}: palm contact error ${maximumError.toFixed(4)} m > ${CONTACT_LIMIT_M} m`);
    check(minimumNormalDot > .95, `${kind}/${clip.name}: palm normals do not face held object (dot ${minimumNormalDot.toFixed(4)})`);
    report.contacts.push({character: kind, clip: clip.name, contact_checks: contactChecks, maximum_contact_error_m: +maximumError.toFixed(5), minimum_inward_palm_normal_dot: +minimumNormalDot.toFixed(5)});
  }
  playback.stop();
}

function closestMeshSurface(meshes, point) {
  let closest = {distance: Infinity, normal: new THREE.Vector3(0, 1, 0)};
  const triangle = new THREE.Triangle(), closestPoint = new THREE.Vector3();
  for (const mesh of meshes) {
    if (mesh.isSkinnedMesh) mesh.skeleton.update();
    const positions = Array.from({length: mesh.geometry.attributes.position.count}, (_, i) => mesh.getVertexPosition(i, new THREE.Vector3()).applyMatrix4(mesh.matrixWorld));
    const index = mesh.geometry.index, count = index ? index.count : positions.length;
    for (let i = 0; i < count; i += 3) {
      const ids = [0, 1, 2].map(offset => index ? index.getX(i + offset) : i + offset);
      triangle.set(...ids.map(id => positions[id]));
      const distance = triangle.closestPointToPoint(point, closestPoint).distanceTo(point);
      if (distance < closest.distance) closest = {distance, normal: triangle.getNormal(new THREE.Vector3())};
    }
  }
  return closest;
}

function checkFlapAndTapeContacts(kind, gltf) {
  const flapMeshes = [], tapeMeshes = [];
  for (const side of ['front', 'back', 'left', 'right']) {
    const flap = gltf.scene.getObjectByName(`${kind.toUpperCase()}_Flap_${side}`);
    flap?.traverse(node => { if (node.isMesh) flapMeshes.push(node); });
  }
  gltf.scene.getObjectByName(`${kind.toUpperCase()}_SealingTape`)?.traverse(node => { if (node.isMesh) tapeMeshes.push(node); });
  if (!check(flapMeshes.length >= 4 && tapeMeshes.length >= 1, `${kind}: missing animated flap or tape meshes`)) return;
  const anchors = ['L', 'R'].map(side => gltf.scene.getObjectByName(`ATTACH_${kind.toUpperCase()}_HAND_${side}`));
  if (anchors.some(anchor => !anchor)) return;

  const playback = player(gltf);
  for (const clip of gltf.animations.filter(clip => /^(Prepare|Pack|RobotPack)(?:_Oversize)?$/.test(clip.name))) {
    playback.start(clip);
    let samples = 0, within2cm = 0, aligned = 0, maximumFlapGap = 0, maximumTapeGap = 0;
    const frames = Math.round(clip.duration * FPS);
    const isPrep = clip.name.startsWith('Prepare');
    for (let frame = 0; frame <= frames; frame++) {
      const phase = frame / frames;
      playback.at(frame / FPS);
      if (frame === 0) {
        const openCarton = gltf.scene.getObjectByName(`${kind.toUpperCase()}_OpenCarton`);
        if (openCarton) {
          openCarton.traverse(n => { if (n.isSkinnedMesh) n.skeleton.update(); });
          const box = new THREE.Box3().setFromObject(openCarton, true);
          check(Math.abs(box.min.y - 0.86) < 0.01, `${kind}/${clip.name}: open carton bottom ${box.min.y} m != 0.86 m`);
        }
      }
      if (isPrep ? (phase >= 0.09 && phase <= 0.78) : (phase >= 0.08 && phase <= 0.60)) {
        for (const anchor of anchors) {
          const point = anchor.getWorldPosition(new THREE.Vector3());
          const nearest = closestMeshSurface(flapMeshes, point);
          maximumFlapGap = Math.max(maximumFlapGap, nearest.distance);
          samples++;
          if (nearest.distance <= CONTACT_LIMIT_M) {
            within2cm++;
            const palmNormal = new THREE.Vector3(1, 0, 0).transformDirection(anchor.matrixWorld);
            if (palmNormal.dot(nearest.normal) < -.90) aligned++;
          }
        }
      }
      if (!isPrep && phase >= 0.71 && phase <= 0.90) {
        const rPoint = anchors[1].getWorldPosition(new THREE.Vector3());
        const nearestTape = closestMeshSurface(tapeMeshes, rPoint);
        maximumTapeGap = Math.max(maximumTapeGap, nearestTape.distance);
      }
    }
    check(maximumFlapGap <= CONTACT_LIMIT_M, `${kind}/${clip.name}: max palm-to-flap gap ${maximumFlapGap.toFixed(4)} m > ${CONTACT_LIMIT_M} m`);
    check(within2cm === samples && samples > 0, `${kind}/${clip.name}: palms within 2cm on ${within2cm}/${samples} flap contact frames`);
    check(aligned / Math.max(within2cm, 1) > .90, `${kind}/${clip.name}: palms do not face contacted flap surfaces`);
    if (!isPrep) {
      check(maximumTapeGap <= CONTACT_LIMIT_M, `${kind}/${clip.name}: max right-palm-to-tape gap ${maximumTapeGap.toFixed(4)} m > ${CONTACT_LIMIT_M} m`);
    }
    report.contacts.push({
      character: kind,
      clip: clip.name,
      flap_surface_samples: samples,
      samples_within_2cm: within2cm,
      surface_normal_aligned_samples: aligned,
      maximum_palm_flap_gap_m: +maximumFlapGap.toFixed(5),
      maximum_palm_tape_gap_m: isPrep ? null : +maximumTapeGap.toFixed(5),
    });
  }
  playback.stop();
}

function checkBoundsFloorAndJoints(kind, gltf) {
  const playback = player(gltf);
  const skins = [], bodySkins = [];
  gltf.scene.traverse(o => {
    if (!o.isSkinnedMesh) return;
    skins.push(o);
    if (!o.userData.operation_prop) bodySkins.push(o);
  });
  const p = new THREE.Vector3();
  let minBodyY = Infinity, maxQuatStep = 0, outOfBounds = 0;

  const bodyBones = [];
  gltf.scene.traverse(n => { if (n.isBone && !n.name.startsWith('prop_')) bodyBones.push(n); });

  for (const clip of gltf.animations) {
    playback.start(clip);
    const frames = Math.round(clip.duration * FPS);
    let prevQuats = null;
    for (let frame = 0; frame <= frames; frame++) {
      playback.at(frame / FPS);
      const curQuats = bodyBones.map(b => b.quaternion.clone());
      if (prevQuats && frame < frames) {
        for (let i = 0; i < bodyBones.length; i++) {
          maxQuatStep = Math.max(maxQuatStep, prevQuats[i].angleTo(curQuats[i]));
        }
      }
      prevQuats = curQuats;

      for (const skin of skins) {
        skin.skeleton.update();
        const isBody = !skin.userData.operation_prop;
        for (let i = 0; i < skin.geometry.attributes.position.count; i++) {
          skin.getVertexPosition(i, p).applyMatrix4(skin.matrixWorld);
          if (Math.abs(p.x) >= 1 || Math.abs(p.z) >= 1 || p.y <= -0.07 || p.y >= 2.05) outOfBounds++;
          if (isBody) minBodyY = Math.min(minBodyY, p.y);
        }
      }
    }
  }
  playback.stop();
  check(outOfBounds === 0, `${kind}: ${outOfBounds} skinned vertex samples exceeded check_v02.mjs bounds |x|<1, |z|<1, -0.07<y<2.05`);
  check(minBodyY >= -0.002, `${kind}: foot/body floor penetration min_y = ${minBodyY.toFixed(4)} m < -0.002 m`);
  check(maxQuatStep < 0.35, `${kind}: sudden single-frame joint inversion/flip (${maxQuatStep.toFixed(4)} rad >= 0.35 rad)`);
  report.bounds_and_joints.push({character: kind, min_body_y_m: +minBodyY.toFixed(5), max_single_frame_bone_step_rad: +maxQuatStep.toFixed(5), out_of_bounds_vertices: outOfBounds});
}

async function compareModulesSync(kind, gltf, file) {
  const bytes = await fs.readFile(new URL('../modules/' + file, import.meta.url));
  const prod = await new Promise((resolve, reject) => new GLTFLoader().parse(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength), '', resolve, reject));
  check(JSON.stringify(prod.animations.map(c => c.name)) === JSON.stringify(EXPECTED[kind]), `modules/${file}: clip list/order mismatch`);
  const prodPlayer = player(prod), fbfPlayer = player(gltf);
  const boneNames = [];
  prod.scene.traverse(node => { if (node.isBone) boneNames.push(node.name); });
  check(boneNames.length === EXPECTED_BONES[kind], `modules/${file}: expected ${EXPECTED_BONES[kind]} bones, got ${boneNames.length}`);
  let maximumError = 0, rootPlacementError = 0, checks = 0;
  for (const clip of prod.animations) {
    const fbfClip = gltf.animations.find(next => next.name === clip.name);
    if (!check(Boolean(fbfClip), `${kind}/${clip.name}: missing in animations_frame_by_frame/${file}`)) continue;
    prodPlayer.start(clip); fbfPlayer.start(fbfClip);
    for (const phase of [0, 0.25, 0.5, 0.75, 1]) {
      prodPlayer.at(clip.duration * phase); fbfPlayer.at(fbfClip.duration * phase);
      for (const name of boneNames) {
        const a = prod.scene.getObjectByName(name), b = gltf.scene.getObjectByName(name);
        if (!a || !b) continue;
        maximumError = Math.max(maximumError, maxMatrixDifference(a.matrixWorld, b.matrixWorld));
        checks++;
      }
      const ra = prod.scene.getObjectByName('root'), rb = gltf.scene.getObjectByName('root');
      if (ra && rb) rootPlacementError = Math.max(rootPlacementError, maxMatrixDifference(ra.parent.matrixWorld, rb.parent.matrixWorld));
    }
  }
  prodPlayer.stop(); fbfPlayer.stop();
  check(maximumError < MATRIX_TOLERANCE, `${kind}: modules/${file} and animations_frame_by_frame/${file} differ by ${maximumError}`);
  check(rootPlacementError < MATRIX_TOLERANCE, `${kind}: root placement differs by ${rootPlacementError}`);
  report.modules_sync.push({character: kind, bones: boneNames.length, bone_checks: checks, max_matrix_diff: maximumError, root_placement_diff: rootPlacementError});
}

function compareObjects(kind, character, objects) {
  const characterPlayer = player(character), objectsPlayer = player(objects);
  let maxDifference = 0, checks = 0;
  const samples = [0, .125, .25, .5, .75, .875, 1];
  for (const clip of character.animations) {
    const objectClip = objects.animations.find(item => item.name === clip.name);
    if (!check(Boolean(objectClip), `${kind}: object-only export lacks ${clip.name}`)) continue;
    check(Math.abs(clip.duration - objectClip.duration) < TIME_TOLERANCE, `${kind}/${clip.name}: character and object durations differ`);
    characterPlayer.start(clip); objectsPlayer.start(objectClip);
    for (const phase of samples) {
      characterPlayer.at(clip.duration * phase); objectsPlayer.at(objectClip.duration * phase);
      for (const name of REQUIRED_PROPS) {
        const a = character.scene.getObjectByName(name), b = objects.scene.getObjectByName(name);
        if (!a || !b) continue;
        const difference = maxMatrixDifference(a.matrixWorld, b.matrixWorld);
        maxDifference = Math.max(maxDifference, difference); checks++;
        check(difference < MATRIX_TOLERANCE, `${kind}/${clip.name}/${name} at phase ${phase}: character/object exports are out of sync by ${difference}`);
      }
    }
  }
  characterPlayer.stop(); objectsPlayer.stop();
  return {character: kind, clips: character.animations.length, sample_phases: samples, prop_matrix_checks: checks, maximum_matrix_difference: maxDifference, tolerance: MATRIX_TOLERANCE};
}

async function loadAsset(file, kind) {
  const bytes = await fs.readFile(path.join(output, file));
  const raw = glbData(bytes);
  const validation = await validator.validateBytes(new Uint8Array(bytes), {uri: file, maxIssues: 100});
  check(validation.issues.numErrors === 0, `${file}: glTF validator reported ${validation.issues.numErrors} errors`);
  check(validation.issues.numWarnings === 0, `${file}: glTF validator reported ${validation.issues.numWarnings} warnings`);
  const gltf = await new Promise((resolve, reject) => new GLTFLoader().parse(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength), '', resolve, reject));
  check(JSON.stringify(gltf.animations.map(clip => clip.name)) === JSON.stringify(EXPECTED[kind]), `${file}: animation names/order differ from expected ${EXPECTED[kind].length} contract clips`);
  const skins = [];
  gltf.scene.traverse(o => { if (o.isSkinnedMesh) skins.push(o); });
  check(skins.length > 0 && skins[0].skeleton.bones.length === EXPECTED_BONES[kind], `${file}: expected ${EXPECTED_BONES[kind]} skeleton bones`);
  for (const name of ALL_PROP_BONES) check(Boolean(gltf.scene.getObjectByName(name)), `${file}: missing prop bone ${name}`);
  let meshes = 0; gltf.scene.traverse(node => { if (node.isMesh) meshes++; });
  check(meshes > 0, `${file}: no renderable meshes`);
  const entry = {
    file,
    bytes: bytes.length,
    clips: gltf.animations.length,
    bones: skins[0]?.skeleton.bones.length ?? 0,
    meshes,
    layout: checkAssetLayout(file, raw.document, gltf, kind),
    gltf: {errors: validation.issues.numErrors, warnings: validation.issues.numWarnings, messages: validation.issues.messages},
    cadence: checkCadence(file, raw.document, raw.binary),
    finite_frames: checkFiniteFrames(file, gltf),
  };
  report.assets.push(entry);
  return gltf;
}

try {
  const manifest = JSON.parse(await fs.readFile(path.join(output, 'manifest.json'), 'utf8'));
  report.manifest_present = true;
  report.manifest_source = manifest.source ?? null;
  check(typeof manifest.source === 'string' && manifest.source.includes('4_Horses_Environment_v01'), `manifest.json: source must point to read-only v01 (${manifest.source})`);
  check(!manifest.objects?.includes('support'), 'manifest.json: objects list still contains forbidden support pedestal');
} catch (error) { errors.push(`manifest.json: ${error.message}`); }

for (const [kind, characterFile] of [['worker', 'warehouse_worker.glb'], ['robot', 'humanoid_robot.glb']]) {
  let character, objects;
  try { character = await loadAsset(characterFile, kind); } catch (error) { errors.push(`${characterFile}: ${error.stack || error.message}`); }
  try { objects = await loadAsset(`interaction_objects_${kind}.glb`, kind); } catch (error) { errors.push(`interaction_objects_${kind}.glb: ${error.stack || error.message}`); }
  if (character) {
    checkHiddenProps(kind, character);
    checkClipAndInteractionMotion(kind, character);
    checkContacts(kind, character);
    checkFlapAndTapeContacts(kind, character);
    checkBoundsFloorAndJoints(kind, character);
    try { await compareModulesSync(kind, character, characterFile); } catch (error) { errors.push(`${kind}: modules sync check failed: ${error.message}`); }
  }
  if (character && objects) report.synchronization.push(compareObjects(kind, character, objects));
}

report.passed = errors.length === 0;
await fs.mkdir(output, {recursive: true});
await fs.writeFile(path.join(output, 'validation.json'), JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify({
  passed: report.passed,
  fps: FPS,
  assets: report.assets.map(asset => ({file: asset.file, bones: asset.bones, clips: asset.clips, gltf_errors: asset.gltf.errors, gltf_warnings: asset.gltf.warnings})),
  modules_sync: report.modules_sync,
  synchronization: report.synchronization,
  errors,
  report: path.join(output, 'validation.json'),
}, null, 2));
if (!report.passed) process.exitCode = 1;
