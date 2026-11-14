// Validate the delivered, densely baked character and interaction-object GLBs.
// This reads assets only; its sole output is animations_frame_by_frame/validation.json.
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
const REQUIRED_PROPS = ['prop_closed', 'prop_shell', 'prop_flap_front', 'prop_flap_back', 'prop_flap_left', 'prop_flap_right', 'prop_item', 'prop_tote', 'prop_tape'];
const BASE = ['Idle', 'Walk', 'CarryIdle', 'Reach', 'PickUp', 'PlaceDown', 'CarryWalk'];
const EXPECTED = {
  worker: [...BASE, 'Prepare', 'Pick', 'Pack', 'Inspect', 'Assist', 'Break', 'Prepare_Oversize', 'Pick_Oversize', 'Pack_Oversize', 'Inspect_Oversize'],
  robot: [...BASE, 'RobotPack', 'Jammed', 'Service', 'Offline', 'RobotPack_Oversize', 'Jammed_Oversize', 'Service_Oversize', 'Pick', 'Inspect', 'Pick_Oversize', 'Inspect_Oversize'],
};
const errors = [];
const report = {passed: false, fps: FPS, assets: [], motion: [], contacts: [], preservation: [], synchronization: [], errors};
function check(condition, message) { if (!condition) errors.push(message); return condition; }
function finite(values) { return Array.from(values).every(Number.isFinite); }
function sorted(values) { return [...values].sort(); }
function sameSet(a, b) { return JSON.stringify(sorted(a)) === JSON.stringify(sorted(b)); }
const maxMatrixDifference = (a, b) => Math.max(...a.elements.map((value, i) => Math.abs(value - b.elements[i])));
// Matrix decomposition cannot recover a quaternion from a hidden zero-scale bone.
// Compose rotations directly so hidden frames and inherited carton rotation remain valid.
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
    check(sparse.length === 0, `${file}/${animation.name}: ${sparse.length} samplers lack full per-frame keys (expected ${expectedSamples}; actual ${[...new Set(sparse.map(s => s.samples))].join(', ')})`);
    check(invalid.length === 0, `${file}/${animation.name}: ${invalid.length} samplers do not follow the 30 FPS frame grid`);
    return {clip: animation.name, duration_seconds: duration, expected_samples_per_sampler: expectedSamples, samplers: samplers.length, sparse_samplers: sparse, off_grid_samplers: invalid};
  });
}

function checkAssetLayout(file, document, kind) {
  const propsOnly = file.startsWith('interaction_objects_');
  const meshNodes = document.nodes.filter(node => node.mesh !== undefined);
  const unexpected = meshNodes.filter(node => {
    const extras = node.extras || {};
    if (extras.handling_prop) return !['box', 'support', ...REQUIRED_PROPS].includes(extras.handling_prop);
    return propsOnly || !extras[kind + '_asset'];
  }).map(node => node.name || '(unnamed mesh)');
  check(document.scenes.length === 1, `${file}: exported ${document.scenes.length} scenes instead of the animation stage only`);
  check(unexpected.length === 0, `${file}: extraneous ${propsOnly ? 'non-prop' : 'environment'} meshes: ${unexpected.join(', ')}`);
  return {scenes: document.scenes.length, raw_mesh_nodes: meshNodes.length, objects_only: propsOnly, unexpected_meshes: unexpected};
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

function checkInteractionMotion(kind, gltf) {
  for (const suffix of ['', '_Oversize']) {
    const pick = gltf.animations.find(clip => clip.name === 'Pick' + suffix);
    if (pick) {
      const range = motionRange(motionSamples(gltf, pick, ['prop_item']).prop_item);
      check(range.position_m > .04, `${kind}/${pick.name}: the picked item does not travel between the tote and carton`);
      report.motion.push({character: kind, clip: pick.name, prop_item: range});
    }
    const pack = gltf.animations.find(clip => clip.name === (kind === 'worker' ? 'Pack' : 'RobotPack') + suffix);
    if (pack) {
      const names = ['prop_flap_front', 'prop_flap_back', 'prop_flap_left', 'prop_flap_right', 'prop_tape'];
      const samples = motionSamples(gltf, pack, names), ranges = Object.fromEntries(names.map(name => [name, motionRange(samples[name])]));
      for (const name of names.slice(0, 4)) check(ranges[name].rotation_rad > .15, `${kind}/${pack.name}: ${name} does not fold`);
      check(ranges.prop_tape.position_m > .015, `${kind}/${pack.name}: tape position does not animate`);
      check(ranges.prop_tape.scale > .05, `${kind}/${pack.name}: tape application scale does not animate`);
      report.motion.push({character: kind, clip: pack.name, props: ranges});
    }
    const inspect = gltf.animations.find(clip => clip.name === 'Inspect' + suffix);
    if (inspect) {
      const samples = motionSamples(gltf, inspect, ['prop_closed', 'prop_shell']);
      const ranges = Object.fromEntries(Object.entries(samples).map(([name, values]) => [name, motionRange(values)]));
      check(Object.values(ranges).some(range => range.position_m > .025 && range.rotation_rad > .08), `${kind}/${inspect.name}: the carton needs both translation and rotation during inspection`);
      report.motion.push({character: kind, clip: inspect.name, props: ranges});
    }
  }
}

function checkContacts(kind, gltf) {
  const playback = player(gltf);
  const anchors = Object.fromEntries(['L', 'R'].map(side => {
    const name = `ATTACH_${kind.toUpperCase()}_HAND_${side}`;
    return [side, gltf.scene.getObjectByName(name) || gltf.scene.getObjectByName('FBF_' + name)];
  }));
  for (const [side, anchor] of Object.entries(anchors)) check(Boolean(anchor), `${kind}: missing ${side} palm attachment`);
  if (!anchors.L || !anchors.R) { playback.stop(); return; }
  for (const clip of gltf.animations.filter(clip => /^(Inspect|Pick)(?:_Oversize)?$/.test(clip.name))) {
    playback.start(clip);
    const oversize = clip.name.endsWith('_Oversize'), inspect = clip.name.startsWith('Inspect');
    const width = oversize ? .48 : .36;
    const carton = gltf.scene.getObjectByName(inspect ? 'prop_closed' : 'prop_shell');
    const item = gltf.scene.getObjectByName('prop_item');
    if (!carton || !item) continue;
    let maximumError = 0, minimumNormalDot = 1, contactChecks = 0;
    for (let frame = 0; frame <= Math.round(clip.duration * FPS); frame++) {
      const phase = frame / Math.round(clip.duration * FPS);
      playback.at(frame / FPS);
      for (const [side, sign] of [['L', 1], ['R', -1]]) {
        if (!inspect && side === 'L' && (phase < .15 || phase > .66)) continue;
        const prop = !inspect && side === 'L' ? item : carton;
        const rotation = worldRotation(prop);
        const offset = !inspect && side === 'L' ? new THREE.Vector3(.0425, .012, 0) : new THREE.Vector3(sign * width / 2, .025, 0);
        const desired = prop.getWorldPosition(new THREE.Vector3()).add(offset.applyQuaternion(rotation));
        const actual = anchors[side].getWorldPosition(new THREE.Vector3());
        maximumError = Math.max(maximumError, desired.distanceTo(actual));
        const normal = new THREE.Vector3(1, 0, 0).transformDirection(anchors[side].matrixWorld);
        const expectedNormal = new THREE.Vector3(-sign, 0, 0).applyQuaternion(rotation);
        minimumNormalDot = Math.min(minimumNormalDot, normal.dot(expectedNormal));
        contactChecks++;
      }
      if (inspect && frame === 0) {
        const closedMesh = gltf.scene.getObjectByName(`FBF_${kind.toUpperCase()}_DemoCarton`);
        if (closedMesh) {
          const size = new THREE.Box3().setFromObject(closedMesh, true).getSize(new THREE.Vector3());
          const expected = oversize ? [.48, .32, .34] : [.36, .25, .28];
          check(size.toArray().every((value, axis) => Math.abs(value - expected[axis]) < .003), `${kind}/${clip.name}: actual carton dimensions ${size.toArray()} differ from ${expected}`);
        }
      }
    }
    check(maximumError < .002, `${kind}/${clip.name}: palms lose object contact by ${maximumError} m`);
    check(minimumNormalDot > .99, `${kind}/${clip.name}: palm normals do not face the held object (dot ${minimumNormalDot})`);
    report.contacts.push({character: kind, clip: clip.name, contact_checks: contactChecks, maximum_contact_error_m: maximumError, minimum_inward_palm_normal_dot: minimumNormalDot});
  }
  playback.stop();
}

function closestFlapSurface(meshes, point) {
  let closest = {distance: Infinity, inwardNormalDot: null};
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

function checkFlapContacts(kind, gltf) {
  const meshes = [];
  for (const side of ['front', 'back', 'left', 'right']) {
    const flap = gltf.scene.getObjectByName(`${kind.toUpperCase()}_Flap_${side}`);
    flap?.traverse(node => { if (node.isMesh) meshes.push(node); });
  }
  if (!check(meshes.length >= 4, `${kind}: missing animated flap meshes`)) return;
  const anchors = ['L', 'R'].map(side => gltf.scene.getObjectByName(`FBF_ATTACH_${kind.toUpperCase()}_HAND_${side}`) || gltf.scene.getObjectByName(`ATTACH_${kind.toUpperCase()}_HAND_${side}`));
  if (anchors.some(anchor => !anchor)) return;
  const playback = player(gltf);
  for (const clip of gltf.animations.filter(clip => /^(Prepare|Pack|RobotPack)(?:_Oversize)?$/.test(clip.name))) {
    playback.start(clip);
    let samples = 0, nearSurface = 0, aligned = 0, maximumGap = 0;
    const frames = Math.round(clip.duration * FPS);
    for (let frame = 0; frame <= frames; frame++) {
      // Sealing begins after .64; the hands then deliberately leave the flaps.
      if (!clip.name.startsWith('Prepare') && frame / frames > .64) continue;
      playback.at(frame / FPS);
      for (const anchor of anchors) {
        const point = anchor.getWorldPosition(new THREE.Vector3()), nearest = closestFlapSurface(meshes, point);
        maximumGap = Math.max(maximumGap, nearest.distance); samples++;
        if (nearest.distance < .01) {
          nearSurface++;
          const palmNormal = new THREE.Vector3(1, 0, 0).transformDirection(anchor.matrixWorld);
          if (palmNormal.dot(nearest.normal) < -.97) aligned++;
        }
      }
    }
    // Natural changes between flap pairs include short periods without contact.
    check(nearSurface / samples > .70, `${kind}/${clip.name}: palms reach a flap surface in only ${nearSurface}/${samples} active samples`);
    check(aligned / Math.max(nearSurface, 1) > .90, `${kind}/${clip.name}: palms do not face the contacted flap surfaces`);
    check(maximumGap < .18, `${kind}/${clip.name}: excessive palm-to-flap gap ${maximumGap} m`);
    report.contacts.push({character: kind, clip: clip.name, flap_surface_samples: samples, samples_within_1cm: nearSurface, surface_normal_aligned_samples: aligned, maximum_palm_flap_gap_m: maximumGap});
  }
  playback.stop();
}

async function compareOriginalMotion(kind, gltf, file) {
  const bytes = await fs.readFile(new URL('../modules/' + file, import.meta.url));
  const original = await new Promise((resolve, reject) => new GLTFLoader().parse(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength), '', resolve, reject));
  const originalPlayer = player(original), nextPlayer = player(gltf);
  const names = [];
  original.scene.traverse(node => { if (node.isBone && !node.name.startsWith('prop_')) names.push(node.name); });
  const copiedClips = original.animations.filter(clip => !/^(Prepare|Pick|Pack|RobotPack|Inspect)(?:_Oversize)?$/.test(clip.name));
  let maximumError = 0, boneChecks = 0, rootPlacementError = 0;
  const rows = [];
  for (const clip of copiedClips) {
    const replacement = gltf.animations.find(next => next.name === clip.name);
    if (!replacement) continue;
    originalPlayer.start(clip); nextPlayer.start(replacement);
    let clipError = 0;
    for (let frame = 0; frame <= Math.round(clip.duration * FPS); frame++) {
      originalPlayer.at(frame / FPS); nextPlayer.at(frame / FPS);
      for (const name of names) {
        const a = original.scene.getObjectByName(name), b = gltf.scene.getObjectByName(name);
        if (!check(Boolean(b), `${kind}/${clip.name}: lost original skeleton bone ${name}`)) continue;
        clipError = Math.max(clipError, maxMatrixDifference(a.matrix, b.matrix));
        boneChecks++;
      }
      const a = original.scene.getObjectByName('root'), b = gltf.scene.getObjectByName('root');
      if (a && b) rootPlacementError = Math.max(rootPlacementError, maxMatrixDifference(a.parent.matrixWorld, b.parent.matrixWorld));
    }
    maximumError = Math.max(maximumError, clipError);
    rows.push({clip: clip.name, maximum_local_bone_matrix_difference: clipError});
  }
  originalPlayer.stop(); nextPlayer.stop();
  check(maximumError < MATRIX_TOLERANCE, `${kind}: original basic motion changed (maximum bone matrix difference ${maximumError})`);
  check(rootPlacementError < MATRIX_TOLERANCE, `${kind}: actor origin/orientation differs from the original standalone model by ${rootPlacementError}`);
  report.preservation.push({character: kind, original_bones: names.length, bone_frame_checks: boneChecks, maximum_local_bone_matrix_difference: maximumError, maximum_actor_placement_difference: rootPlacementError, clips: rows});
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
        const difference = Math.max(...a.matrixWorld.elements.map((value, index) => Math.abs(value - b.matrixWorld.elements[index])));
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
  const gltf = await new Promise((resolve, reject) => new GLTFLoader().parse(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength), '', resolve, reject));
  check(sameSet(gltf.animations.map(clip => clip.name), EXPECTED[kind]), `${file}: animation names differ from the expected ${EXPECTED[kind].length} clips`);
  for (const name of REQUIRED_PROPS) check(Boolean(gltf.scene.getObjectByName(name)), `${file}: missing interaction node ${name}`);
  let meshes = 0; gltf.scene.traverse(node => { if (node.isMesh) meshes++; });
  check(meshes > 0, `${file}: no renderable meshes`);
  const entry = {file, bytes: bytes.length, clips: gltf.animations.length, meshes, layout: checkAssetLayout(file, raw.document, kind), gltf: {errors: validation.issues.numErrors, warnings: validation.issues.numWarnings, messages: validation.issues.messages}, cadence: checkCadence(file, raw.document, raw.binary), finite_frames: checkFiniteFrames(file, gltf)};
  report.assets.push(entry);
  return gltf;
}

try {
  const manifest = JSON.parse(await fs.readFile(path.join(output, 'manifest.json'), 'utf8'));
  report.manifest_present = true;
  report.manifest_schema = manifest.schema_version ?? manifest.version ?? null;
} catch (error) { errors.push(`manifest.json: ${error.message}`); }

for (const [kind, characterFile] of [['worker', 'warehouse_worker.glb'], ['robot', 'humanoid_robot.glb']]) {
  let character, objects;
  try { character = await loadAsset(characterFile, kind); } catch (error) { errors.push(`${characterFile}: ${error.stack || error.message}`); }
  try { objects = await loadAsset(`interaction_objects_${kind}.glb`, kind); } catch (error) { errors.push(`interaction_objects_${kind}.glb: ${error.stack || error.message}`); }
  if (character) {
    checkInteractionMotion(kind, character);
    checkContacts(kind, character);
    checkFlapContacts(kind, character);
    try { await compareOriginalMotion(kind, character, characterFile); } catch (error) { errors.push(`${kind}: original motion comparison failed: ${error.message}`); }
  }
  if (character && objects) report.synchronization.push(compareObjects(kind, character, objects));
}

report.passed = errors.length === 0;
await fs.mkdir(output, {recursive: true});
await fs.writeFile(path.join(output, 'validation.json'), JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify({passed: report.passed, fps: FPS, assets: report.assets.map(asset => ({file: asset.file, clips: asset.clips, gltf_errors: asset.gltf.errors, gltf_warnings: asset.gltf.warnings})), synchronization: report.synchronization, errors, report: path.join(output, 'validation.json')}, null, 2));
if (!report.passed) process.exitCode = 1;
