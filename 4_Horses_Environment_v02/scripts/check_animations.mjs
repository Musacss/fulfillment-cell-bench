// Authoritative M2 production character & animation validator for
// 4_Horses_Environment_v02/modules/{warehouse_worker,humanoid_robot}.glb + manifests.
import fs from 'node:fs/promises';
import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import validator from 'gltf-validator';
import {cloneActorRig, createActorVisual} from '../visual/visual-integration.js';

const root = new URL('../', import.meta.url);
const FPS = 30;
const TIME_TOLERANCE = 3e-5;
const CONTACT_LIMIT_M = 0.020;

const EXPECTED_CLIPS = {
  worker: [
    'Idle', 'Walk', 'CarryIdle', 'Reach', 'PickUp', 'PlaceDown', 'CarryWalk',
    'Prepare', 'Pick', 'Pack', 'Inspect', 'Assist', 'Break',
    'Prepare_Oversize', 'Pick_Oversize', 'Pack_Oversize', 'Inspect_Oversize',
  ],
  robot: [
    'Idle', 'Walk', 'CarryIdle', 'Reach', 'PickUp', 'PlaceDown', 'CarryWalk',
    'RobotPack', 'Jammed', 'Service', 'Offline',
    'RobotPack_Oversize', 'Jammed_Oversize', 'Service_Oversize',
  ],
};
const EXPECTED_BONES = {worker: 35, robot: 41};
const PROP_ROLES = [
  'prop_closed', 'prop_shell', 'prop_flap_front', 'prop_flap_back',
  'prop_flap_left', 'prop_flap_right', 'prop_item', 'prop_tote', 'prop_tape',
];
const ALL_PROP_BONES = ['prop_box', 'prop_stand', ...PROP_ROLES];
const PROP_NODE_SUFFIXES = [
  'ClosedCarton', 'OpenCarton', 'Flap_front', 'Flap_back',
  'Flap_left', 'Flap_right', 'Product', 'PickingTote', 'SealingTape',
];
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
function check(cond, msg) {
  if (!cond) errors.push(msg);
  return cond;
}

function parseGLB(bytes) {
  let json, binary;
  for (let offset = 12; offset < bytes.length;) {
    const length = bytes.readUInt32LE(offset), type = bytes.readUInt32LE(offset + 4);
    const chunk = bytes.subarray(offset + 8, offset + 8 + length);
    if (type === 0x4e4f534a) json = JSON.parse(chunk.toString('utf8').replace(/[\u0000\s]+$/, ''));
    if (type === 0x004e4942) binary = chunk;
    offset += 8 + length;
  }
  return {json, binary};
}

function triangles(prim, json) {
  const n = json.accessors[prim.indices ?? prim.attributes.POSITION].count;
  const m = prim.mode ?? 4;
  return m === 4 ? n / 3 : (m === 5 || m === 6 ? Math.max(0, n - 2) : 0);
}

function worldRotation(node) {
  const chain = [];
  for (let cur = node; cur; cur = cur.parent) chain.push(cur.quaternion);
  const out = new THREE.Quaternion();
  for (const q of chain.reverse()) out.multiply(q);
  return out.normalize();
}

function closestMeshSurface(meshes, point) {
  let closest = {distance: Infinity, normal: new THREE.Vector3(0, 1, 0)};
  const tri = new THREE.Triangle(), cp = new THREE.Vector3();
  for (const mesh of meshes) {
    if (mesh.isSkinnedMesh) mesh.skeleton.update();
    const pos = Array.from({length: mesh.geometry.attributes.position.count}, (_, i) =>
      mesh.getVertexPosition(i, new THREE.Vector3()).applyMatrix4(mesh.matrixWorld)
    );
    const idx = mesh.geometry.index, count = idx ? idx.count : pos.length;
    for (let i = 0; i < count; i += 3) {
      const ids = [0, 1, 2].map(k => idx ? idx.getX(i + k) : i + k);
      tri.set(pos[ids[0]], pos[ids[1]], pos[ids[2]]);
      const d = tri.closestPointToPoint(point, cp).distanceTo(point);
      if (d < closest.distance) closest = {distance: d, normal: tri.getNormal(new THREE.Vector3())};
    }
  }
  return closest;
}

function segmentPiercesMesh(p0, p1, meshes) {
  const dir = new THREE.Vector3().subVectors(p1, p0);
  const e1 = new THREE.Vector3(), e2 = new THREE.Vector3(), h = new THREE.Vector3();
  const s = new THREE.Vector3(), q = new THREE.Vector3();
  for (const mesh of meshes) {
    if (mesh.isSkinnedMesh) mesh.skeleton.update();
    const pos = Array.from({length: mesh.geometry.attributes.position.count}, (_, i) =>
      mesh.getVertexPosition(i, new THREE.Vector3()).applyMatrix4(mesh.matrixWorld)
    );
    const idx = mesh.geometry.index, count = idx ? idx.count : pos.length;
    for (let i = 0; i < count; i += 3) {
      const v0 = pos[idx ? idx.getX(i) : i];
      const v1 = pos[idx ? idx.getX(i + 1) : i + 1];
      const v2 = pos[idx ? idx.getX(i + 2) : i + 2];
      e1.subVectors(v1, v0);
      e2.subVectors(v2, v0);
      h.crossVectors(dir, e2);
      const a = e1.dot(h);
      if (Math.abs(a) < 1e-9) continue;
      const f = 1.0 / a;
      s.subVectors(p0, v0);
      const u = f * s.dot(h);
      if (u < 0.0 || u > 1.0) continue;
      q.crossVectors(s, e1);
      const v = f * dir.dot(q);
      if (v < 0.0 || u + v > 1.0) continue;
      const t = f * e2.dot(q);
      if (t > 0.02 && t < 0.98) return true;
    }
  }
  return false;
}

const fbfManifest = JSON.parse(await fs.readFile(new URL('animations_frame_by_frame/manifest.json', root), 'utf8'));
const summary = {passed: false, characters: {}, errors};

for (const [kind, file, manifestFile] of [
  ['worker', 'modules/warehouse_worker.glb', 'worker_manifest.json'],
  ['robot', 'modules/humanoid_robot.glb', 'robot_manifest.json'],
]) {
  const prefix = kind.toUpperCase();
  const bytes = await fs.readFile(new URL(file, root));
  const {json} = parseGLB(bytes);
  const manifest = JSON.parse(await fs.readFile(new URL(manifestFile, root), 'utf8'));
  const val = await validator.validateBytes(new Uint8Array(bytes), {uri: file, maxIssues: 100});
  check(val.issues.numErrors === 0 && val.issues.numWarnings === 0,
    `${file}: gltf-validator errors=${val.issues.numErrors}, warnings=${val.issues.numWarnings}`);

  const gltf = await new Promise((res, rej) =>
    new GLTFLoader().parse(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength), '', res, rej)
  );

  // 1. Scene, Rig, Clone Isolation & Adapter Compatibility
  check(json.scenes.length === 1, `${file}: expected 1 scene`);
  check(Boolean(gltf.scene.getObjectByName(`${prefix}_Rig`)), `${file}: missing ${prefix}_Rig`);
  const c1 = cloneActorRig(gltf.scene), c2 = cloneActorRig(gltf.scene);
  const m1 = new THREE.AnimationMixer(c1), m2 = new THREE.AnimationMixer(c2);
  m1.clipAction(gltf.animations[0]).play(); m1.setTime(0);
  m2.clipAction(gltf.animations[1]).play(); m2.setTime(0.5);
  c1.updateMatrixWorld(true); c2.updateMatrixWorld(true);
  const s1 = [], s2 = [];
  c1.traverse(o => { if (o.isBone) s1.push(...o.matrixWorld.elements); });
  c2.traverse(o => { if (o.isBone) s2.push(...o.matrixWorld.elements); });
  check(s1.some((v, i) => Math.abs(v - s2[i]) > 1e-4), `${file}: cloneActorRig shares bone state`);

  const actorVis = createActorVisual(gltf, {actorType: kind});
  let hiddenOperationalProp = false;
  actorVis.root.traverse(o => {
    if (o.userData.operation_prop === true && o.visible === false) hiddenOperationalProp = true;
  });
  check(!hiddenOperationalProp, `${file}: hideDemonstrationProps hid an operational prop!`);
  actorVis.dispose();

  // 2. Skeleton, Skinning & Authored Geometry
  const skins = [];
  gltf.scene.traverse(o => { if (o.isSkinnedMesh) skins.push(o); });
  check(skins.length > 0 && skins[0].skeleton.bones.length === EXPECTED_BONES[kind],
    `${file}: expected ${EXPECTED_BONES[kind]} bones, got ${skins[0]?.skeleton.bones.length}`);
  for (const pb of ALL_PROP_BONES) check(Boolean(gltf.scene.getObjectByName(pb)), `${file}: missing bone ${pb}`);

  let unweighted = 0, nonRigidRobotVerts = 0;
  for (const skin of skins) {
    const wAttr = skin.geometry.attributes.skinWeight;
    const jAttr = skin.geometry.attributes.skinIndex;
    check(Boolean(wAttr && jAttr), `${file}/${skin.name}: missing skin attributes`);
    for (let i = 0; i < wAttr.count; i++) {
      const weights = [wAttr.getX(i), wAttr.getY(i), wAttr.getZ(i), wAttr.getW(i)];
      const indices = [jAttr.getX(i), jAttr.getY(i), jAttr.getZ(i), jAttr.getW(i)];
      const sum = weights.reduce((a, b) => a + b, 0);
      if (!weights.every(Number.isFinite) || Math.abs(sum - 1) > 1e-4 || indices.some(idx => idx >= EXPECTED_BONES[kind])) {
        unweighted++;
      }
      if (kind === 'robot' && !skin.userData.operation_prop) {
        const nonZero = weights.filter(w => w > 1e-4);
        if (nonZero.length !== 1 || Math.abs(nonZero[0] - 1) > 1e-4) nonRigidRobotVerts++;
      }
    }
  }
  check(unweighted === 0, `${file}: ${unweighted} unweighted/invalid skinned vertices`);
  if (kind === 'robot') check(nonRigidRobotVerts === 0, `${file}: ${nonRigidRobotVerts} non-rigid armor vertices on ROBOT_Body`);

  // 3. Exact Node Names, Helmet, Rest Height & Sockets
  const badNames = [];
  gltf.scene.traverse(o => {
    if (/DemoSupport|_DemoCarton|^FBF_/i.test(o.name) || o.userData.handling_prop || o.userData.demo_only) {
      badNames.push(o.name || o.type);
    }
  });
  check(badNames.length === 0, `${file}: forbidden nodes/extras present: ${badNames.join(', ')}`);

  const attachL = gltf.scene.getObjectByName(`ATTACH_${prefix}_HAND_L`);
  const attachR = gltf.scene.getObjectByName(`ATTACH_${prefix}_HAND_R`);
  check(Boolean(attachL && attachR), `${file}: missing hand sockets ATTACH_${prefix}_HAND_L/R`);

  gltf.scene.updateMatrixWorld(true);
  const restBox = new THREE.Box3();
  gltf.scene.traverse(o => {
    if (o.isMesh && !o.userData.operation_prop) restBox.union(new THREE.Box3().setFromObject(o, true));
  });
  const restHeight = restBox.max.y;
  if (kind === 'worker') {
    const bodyNode = json.nodes.find(n => n.name === 'WORKER_Body');
    const helmetNode = json.nodes.find(n => n.name === 'WORKER_Helmet');
    check(Boolean(bodyNode && helmetNode), `${file}: missing WORKER_Body or WORKER_Helmet`);
    if (bodyNode && helmetNode) {
      const bodyTris = json.meshes[bodyNode.mesh].primitives.reduce((s, p) => s + triangles(p, json), 0);
      const helmetTris = json.meshes[helmetNode.mesh].primitives.reduce((s, p) => s + triangles(p, json), 0);
      const matSet = new Set([...json.meshes[bodyNode.mesh].primitives, ...json.meshes[helmetNode.mesh].primitives].map(p => p.material));
      check(bodyTris === 3480 && helmetTris === 256 && matSet.size === 12,
        `${file}: worker geometry mismatch tris=${bodyTris}+${helmetTris}, mats=${matSet.size}`);
    }
    check(Math.abs(restHeight - 1.944) < 1e-4, `${file}: worker rest height ${restHeight} != 1.944 m`);
  } else {
    const bodyNode = json.nodes.find(n => n.name === 'ROBOT_Body');
    check(Boolean(bodyNode), `${file}: missing ROBOT_Body`);
    if (bodyNode) {
      const bodyTris = json.meshes[bodyNode.mesh].primitives.reduce((s, p) => s + triangles(p, json), 0);
      check(bodyTris === 3728, `${file}: robot body tris ${bodyTris} != 3728`);
    }
    check(Math.abs(restHeight - 1.851) < 1e-4, `${file}: robot rest height ${restHeight} != 1.851 m`);
  }

  // 4. Operational Prop Nodes & Extras on BOTH Group & Leaf SkinnedMesh Primitives
  for (const suffix of PROP_NODE_SUFFIXES) {
    const propName = `${prefix}_${suffix}`;
    const node = gltf.scene.getObjectByName(propName);
    check(Boolean(node), `${file}: missing operational prop ${propName}`);
    if (node) {
      check(node.userData.operation_prop === true, `${file}/${propName}: node missing userData.operation_prop === true`);
      let leafCount = 0;
      node.traverse(child => {
        if (child.isMesh) {
          leafCount++;
          check(child.userData.operation_prop === true, `${file}/${propName}/${child.name}: leaf SkinnedMesh missing userData.operation_prop === true`);
        }
      });
      check(leafCount >= 1, `${file}/${propName}: no mesh primitives`);
    }
  }

  // 5. Clip Order, Manifest Sync, Empty-Handed Hiding, Motion Thresholds, <2cm Contacts & Bounds
  const clipNames = gltf.animations.map(c => c.name);
  check(JSON.stringify(clipNames) === JSON.stringify(EXPECTED_CLIPS[kind]),
    `${file}: clip array ${JSON.stringify(clipNames)} != ${JSON.stringify(EXPECTED_CLIPS[kind])}`);
  check(manifest.bones === EXPECTED_BONES[kind], `${manifestFile}: bones=${manifest.bones} != ${EXPECTED_BONES[kind]}`);
  check(JSON.stringify(manifest.clips.map(c => c.name)) === JSON.stringify(EXPECTED_CLIPS[kind]),
    `${manifestFile}: clip list mismatch`);
  const fbfClips = Object.fromEntries((fbfManifest.actors[kind]?.clips ?? []).map(c => [c.name, c]));
  for (const mc of manifest.clips) {
    const gc = gltf.animations.find(a => a.name === mc.name);
    if (gc) check(Math.abs(gc.duration - mc.duration_seconds) < 1e-3, `${manifestFile}/${mc.name}: duration ${mc.duration_seconds} != GLB ${gc.duration}`);
    if (mc.frozen !== undefined) check(mc.frozen === false, `${manifestFile}/${mc.name}: frozen must be false`);
    const fc = fbfClips[mc.name];
    check(Boolean(fc), `${manifestFile}/${mc.name}: missing in animations_frame_by_frame/manifest.json`);
    if (fc) {
      check(mc.loop === fc.loop, `${manifestFile}/${mc.name}: loop=${mc.loop} != FBF manifest loop=${fc.loop}`);
      check(mc.action === fc.action, `${manifestFile}/${mc.name}: action=${mc.action} != FBF manifest action=${fc.action}`);
    }
  }

  const mixer = new THREE.AnimationMixer(gltf.scene);
  const bodyBones = [];
  gltf.scene.traverse(n => { if (n.isBone && !n.name.startsWith('prop_')) bodyBones.push(n); });
  const findBone = name => bodyBones.find(b => b.name === name || b.name === name.replace('.', ''));
  const armBoneSegments = [
    ['upper_arm.L', 'forearm.L'],
    ['upper_arm.R', 'forearm.R'],
    ['forearm.L', 'hand.L'],
    ['forearm.R', 'hand.R'],
  ].map(([a, b]) => [findBone(a), findBone(b)]);
  const propRoleMeshes = PROP_NODE_SUFFIXES.map((suffix, idx) => {
    const meshes = [];
    gltf.scene.getObjectByName(`${prefix}_${suffix}`)?.traverse(n => { if (n.isMesh) meshes.push(n); });
    return {role: PROP_ROLES[idx], suffix, meshes};
  });
  const flapMeshes = ['front', 'back', 'left', 'right'].flatMap(s => {
    const m = [];
    gltf.scene.getObjectByName(`${prefix}_Flap_${s}`)?.traverse(n => { if (n.isMesh) m.push(n); });
    return m;
  });
  const tapeMeshes = [];
  gltf.scene.getObjectByName(`${prefix}_SealingTape`)?.traverse(n => { if (n.isMesh) tapeMeshes.push(n); });

  const clipMetrics = {};
  let minBodyY = Infinity, maxQuatStep = 0, outOfBounds = 0, propScaleViolations = 0, segmentPiercings = 0;
  const vTmp = new THREE.Vector3(), ws = new THREE.Vector3(), segA = new THREE.Vector3(), segB = new THREE.Vector3();

  for (const clip of gltf.animations) {
    mixer.stopAllAction();
    const action = mixer.clipAction(clip);
    action.reset().setLoop(THREE.LoopOnce, 1);
    action.clampWhenFinished = true;
    action.play();

    const frames = Math.round(clip.duration * FPS);
    check(frames >= 2 && Math.abs(clip.duration - frames / FPS) < TIME_TOLERANCE, `${file}/${clip.name}: non-integer 30-FPS duration`);

    const boneBoxes = bodyBones.map(() => new THREE.Box3());
    let prevQuats = null;
    let maxContactErr = 0, minNormalDot = 1, maxFlapGap = 0, maxTapeGap = 0, assistMaxZ = 0;

    const isEmpty = EMPTY_HANDED.has(clip.name);
    const oversize = clip.name.endsWith('_Oversize');
    const width = oversize ? 0.48 : 0.36;
    const isPick = clip.name.startsWith('Pick') && !clip.name.startsWith('PickUp');
    const isInspect = clip.name.startsWith('Inspect');
    const isSideContact = /^(Inspect|Pick|CarryIdle|CarryWalk|PickUp|PlaceDown)(?:_Oversize)?$/.test(clip.name);
    const isFlapOp = /^(Prepare|Pack|RobotPack)(?:_Oversize)?$/.test(clip.name);
    const isPrep = clip.name.startsWith('Prepare');

    for (let f = 0; f <= frames; f++) {
      const phase = f / frames;
      mixer.setTime(f / FPS);
      gltf.scene.updateMatrixWorld(true);

      // Joint step & body motion tracking
      const curQuats = bodyBones.map(b => b.quaternion.clone());
      if (prevQuats && f < frames) {
        for (let i = 0; i < bodyBones.length; i++) {
          maxQuatStep = Math.max(maxQuatStep, prevQuats[i].angleTo(curQuats[i]));
        }
      }
      prevQuats = curQuats;
      bodyBones.forEach((b, i) => boneBoxes[i].expandByPoint(b.getWorldPosition(vTmp)));

      if (clip.name === 'Assist') {
        const lp = attachL.getWorldPosition(new THREE.Vector3());
        assistMaxZ = Math.max(assistMaxZ, lp.z);
      }

      // Prop scale checks
      const stand = gltf.scene.getObjectByName('prop_stand');
      if (stand.scale.length() > 1e-6 || stand.getWorldScale(ws).length() > 1e-6) propScaleViolations++;
      if (isEmpty) {
        for (const pname of ALL_PROP_BONES) {
          const pb = gltf.scene.getObjectByName(pname);
          if (pb.scale.length() > 1e-6 || pb.getWorldScale(ws).length() > 1e-6) propScaleViolations++;
        }
      }

      // Skinned vertex bounds & floor contact
      for (const skin of skins) {
        skin.skeleton.update();
        const isBody = !skin.userData.operation_prop;
        for (let i = 0; i < skin.geometry.attributes.position.count; i++) {
          skin.getVertexPosition(i, vTmp).applyMatrix4(skin.matrixWorld);
          if (!vTmp.toArray().every(Number.isFinite) || Math.abs(vTmp.x) >= 1 || Math.abs(vTmp.z) >= 1 || vTmp.y <= -0.07 || vTmp.y >= 2.05) {
            outOfBounds++;
          }
          if (isBody) minBodyY = Math.min(minBodyY, vTmp.y);
        }
      }

      // Arm bone-segment vs active prop triangle piercing check (0 piercings on every frame)
      if (!isEmpty) {
        const activePropMeshes = propRoleMeshes
          .filter(({role}) => gltf.scene.getObjectByName(role).getWorldScale(ws).length() > 1e-3)
          .flatMap(({meshes}) => meshes);
        if (activePropMeshes.length > 0) {
          for (const [bStart, bEnd] of armBoneSegments) {
            bStart.getWorldPosition(segA);
            bEnd.getWorldPosition(segB);
            if (segmentPiercesMesh(segA, segB, activePropMeshes)) segmentPiercings++;
          }
        }
      }

      // Side grasp & thumb-up checks (< 2 cm)
      if (isSideContact && !(clip.name === 'PickUp' && phase < 0.50) && !(clip.name === 'PlaceDown' && phase > 0.50)) {
        const carton = gltf.scene.getObjectByName(isPick ? 'prop_shell' : 'prop_closed');
        const item = gltf.scene.getObjectByName('prop_item');
        for (const [side, sign, sock] of [['L', 1, attachL], ['R', -1, attachR]]) {
          if (isPick && side === 'L' && (phase < 0.15 || phase > 0.66)) continue;
          const prop = isPick && side === 'L' ? item : carton;
          const rot = worldRotation(prop);
          const off = isPick && side === 'L' ? new THREE.Vector3(0.0425, 0.012, 0) : new THREE.Vector3(sign * width / 2, 0.025, 0);
          const desired = prop.getWorldPosition(new THREE.Vector3()).add(off.applyQuaternion(rot));
          const actual = sock.getWorldPosition(new THREE.Vector3());
          maxContactErr = Math.max(maxContactErr, desired.distanceTo(actual));
          const nrm = new THREE.Vector3(1, 0, 0).transformDirection(sock.matrixWorld);
          const expNrm = new THREE.Vector3(-sign, 0, 0).applyQuaternion(rot);
          minNormalDot = Math.min(minNormalDot, nrm.dot(expNrm));
        }
      }

      // Flap & tape grasp checks (< 2 cm)
      if (isFlapOp) {
        if (isPrep ? (phase >= 0.09 && phase <= 0.78) : (phase >= 0.08 && phase <= 0.60)) {
          for (const sock of [attachL, attachR]) {
            const pt = sock.getWorldPosition(new THREE.Vector3());
            maxFlapGap = Math.max(maxFlapGap, closestMeshSurface(flapMeshes, pt).distance);
          }
        }
        if (!isPrep && phase >= 0.71 && phase <= 0.90) {
          const pt = attachR.getWorldPosition(new THREE.Vector3());
          maxTapeGap = Math.max(maxTapeGap, closestMeshSurface(tapeMeshes, pt).distance);
        }
      }
    }

    const maxBodyDeltaM = Math.max(...boneBoxes.map(b => b.getSize(new THREE.Vector3()).length()));
    const minReq = MOTION_THRESHOLDS[clip.name] ?? 0.002;
    check(maxBodyDeltaM >= minReq, `${file}/${clip.name}: motion ${maxBodyDeltaM.toFixed(4)} m < ${minReq} m`);
    if (clip.name === 'Assist') check(assistMaxZ >= 0.42, `${file}/Assist: forward reach z=${assistMaxZ.toFixed(3)} m < 0.42 m`);
    if (isSideContact) {
      check(maxContactErr <= CONTACT_LIMIT_M, `${file}/${clip.name}: contact error ${maxContactErr.toFixed(4)} m > 0.020 m`);
      check(minNormalDot > 0.95, `${file}/${clip.name}: inward palm dot ${minNormalDot.toFixed(4)} <= 0.95`);
    }
    if (isFlapOp) {
      check(maxFlapGap <= CONTACT_LIMIT_M, `${file}/${clip.name}: flap contact gap ${maxFlapGap.toFixed(4)} m > 0.020 m`);
      if (!isPrep) check(maxTapeGap <= CONTACT_LIMIT_M, `${file}/${clip.name}: tape contact gap ${maxTapeGap.toFixed(4)} m > 0.020 m`);
    }
    clipMetrics[clip.name] = {
      frames: frames + 1,
      duration_s: +clip.duration.toFixed(4),
      max_body_delta_m: +maxBodyDeltaM.toFixed(5),
      ...(isSideContact ? {max_contact_err_m: +maxContactErr.toFixed(5)} : {}),
      ...(isFlapOp ? {max_flap_gap_m: +maxFlapGap.toFixed(5), ...(isPrep ? {} : {max_tape_gap_m: +maxTapeGap.toFixed(5)})} : {}),
    };
  }
  mixer.stopAllAction();

  check(propScaleViolations === 0, `${file}: ${propScaleViolations} prop scale violations`);
  check(segmentPiercings === 0, `${file}: ${segmentPiercings} arm bone-segment prop triangle piercings`);
  check(outOfBounds === 0, `${file}: ${outOfBounds} vertices outside check_v02.mjs bounds`);
  check(minBodyY >= -0.002, `${file}: body floor penetration min_y=${minBodyY.toFixed(4)} m < -0.002 m`);
  check(maxQuatStep < 0.35, `${file}: joint rotation jump ${maxQuatStep.toFixed(4)} rad >= 0.35 rad`);

  summary.characters[kind] = {
    file,
    bones: EXPECTED_BONES[kind],
    clips: clipNames.length,
    rest_height_m: +restHeight.toFixed(5),
    min_body_y_m: +minBodyY.toFixed(5),
    max_joint_step_rad: +maxQuatStep.toFixed(5),
    gltf_errors: val.issues.numErrors,
    gltf_warnings: val.issues.numWarnings,
    clip_metrics: clipMetrics,
  };
}

summary.passed = errors.length === 0;
console.log(JSON.stringify(summary, null, 2));
if (!summary.passed) process.exitCode = 1;
