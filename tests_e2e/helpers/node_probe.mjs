// Headless Node v24 opaque-box probe for 4 Horses Environment v02 & Studio 3D Player.
// Zero repo writes: all outputs go strictly to --out in a temporary directory.

import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import fsSync from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import zlib from 'node:zlib';

// IMPORTANT: Import gltf-validator & Three.js BEFORE setting globalThis.window = globalThis!
import validator from '../../4_Horses_Environment_v02/node_modules/gltf-validator/index.js';
import * as THREE from '../../studio/node_modules/three/build/three.module.js';
import { GLTFLoader } from '../../studio/node_modules/three/examples/jsm/loaders/GLTFLoader.js';
import * as SkeletonUtils from '../../studio/node_modules/three/examples/jsm/utils/SkeletonUtils.js';
import * as THREE_V02 from '../../4_Horses_Environment_v02/node_modules/three/build/three.module.js';

import {
  environmentLayers,
  applyEnvironmentDefaults,
  setEnvironmentLayer,
  setRobotAndonState,
} from '../../4_Horses_Environment_v02/visual/environment-layers.js';
import {
  createActorVisual,
  createOrderVisualPool,
  queueSlotPositions,
  manualWorkPosition,
  sampleWalkPath,
} from '../../4_Horses_Environment_v02/visual/visual-integration.js';

import * as DataMod from '../../studio/src/data.js';
import { createReplay, ReplayError, COUNTER_KEYS } from '../../studio/src/replay.js';
import { createScenePlayer } from '../../studio/src/scene.js';
import * as SpatialMod from '../../studio/src/spatial.js';
import * as MapGeomMod from '../../studio/src/map-geometry.js';
import * as MapLayoutMod from '../../studio/src/map-layout.js';
import * as MapFloorMod from '../../studio/src/map-floor.js';

const { MAP_GEOMETRY_FIXES, applyMapGeometryFixes } = MapGeomMod;
const { applyMapLayoutExpansion } = MapLayoutMod;
const { applyMapFloorFixes } = MapFloorMod;
const MAP_FLOOR_FIXES = MapFloorMod.MAP_FLOOR_FIXES ?? { patchGroupName: 'MAP_FLOOR_PATCHES' };

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const DEFAULT_REPO_ROOT = path.resolve(__dirname, '..', '..');

const ALL_15_GLBS = [
  'warehouse_environment.glb',
  'modules/carton_closed.glb',
  'modules/carton_open.glb',
  'modules/humanoid_robot.glb',
  'modules/inspection_portal.glb',
  'modules/packing_bench_1800.glb',
  'modules/pallet_1200x800.glb',
  'modules/roller_conveyor_1800.glb',
  'modules/shelving_1800.glb',
  'modules/supply_trolley.glb',
  'modules/tote_600x400.glb',
  'modules/visual_layout.glb',
  'modules/visual_support.glb',
  'modules/warehouse_worker.glb',
  'modules/workbench_1800.glb',
];

const STUDIO_SCENE_PLAYER_ASSETS = [
  'warehouse_environment.glb',
  'modules/visual_layout.glb',
  'modules/visual_support.glb',
  'modules/warehouse_worker.glb',
  'modules/humanoid_robot.glb',
  'visual_bindings.json',
  'anchors.json',
];

const WORKER_CLIPS = [
  'Idle', 'Walk', 'CarryIdle', 'Reach', 'PickUp', 'PlaceDown', 'CarryWalk',
  'Prepare', 'Pick', 'Pack', 'Inspect', 'Assist', 'Break',
  'Prepare_Oversize', 'Pick_Oversize', 'Pack_Oversize', 'Inspect_Oversize',
];

const ROBOT_CLIPS = [
  'Idle', 'Walk', 'CarryIdle', 'Reach', 'PickUp', 'PlaceDown', 'CarryWalk',
  'RobotPack', 'Jammed', 'Service', 'Offline',
  'RobotPack_Oversize', 'Jammed_Oversize', 'Service_Oversize',
];

const REQUIRED_PROP_BONES = [
  'prop_closed', 'prop_shell', 'prop_flap_front', 'prop_flap_back',
  'prop_flap_left', 'prop_flap_right', 'prop_item', 'prop_tote', 'prop_tape',
];

let lastCapturedScene = null;
const assetRouteMap = new Map();

function installHeadlessBrowserShim(v02Dir, repoRoot) {
  assetRouteMap.set('http://local.probe/__local_assets__/', v02Dir);
  assetRouteMap.set('/__local_assets__/', v02Dir);
  assetRouteMap.set('http://local.probe/__public_scene__/', path.join(repoRoot, 'studio', 'public', 'scene'));
  assetRouteMap.set('/__public_scene__/', path.join(repoRoot, 'studio', 'public', 'scene'));
  assetRouteMap.set('http://local.probe/__dist_scene__/', path.join(repoRoot, 'studio', 'dist', 'scene'));
  assetRouteMap.set('/__dist_scene__/', path.join(repoRoot, 'studio', 'dist', 'scene'));

  globalThis.window = globalThis;
  globalThis.self = globalThis;
  globalThis.devicePixelRatio = 1;
  globalThis.requestAnimationFrame ??= () => 0;
  globalThis.cancelAnimationFrame ??= () => {};
  globalThis.ResizeObserver ??= class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  globalThis.ProgressEvent ??= class ProgressEvent extends Event {
    constructor(type, init = {}) {
      super(type);
      this.lengthComputable = Boolean(init.lengthComputable);
      this.loaded = init.loaded ?? 0;
      this.total = init.total ?? 0;
    }
  };

  const glConsts = {
    POINTS: 0, LINES: 1, LINE_LOOP: 2, LINE_STRIP: 3, TRIANGLES: 4, TRIANGLE_STRIP: 5, TRIANGLE_FAN: 6,
    VERSION: 0x1F02, SHADING_LANGUAGE_VERSION: 0x8B8C, VENDOR: 0x1F00, RENDERER: 0x1F01,
    MAX_TEXTURE_SIZE: 0x0D33, MAX_CUBE_MAP_TEXTURE_SIZE: 0x851C, MAX_RENDERBUFFER_SIZE: 0x84E8,
    MAX_VIEWPORT_DIMS: 0x0D3A, MAX_VERTEX_ATTRIBS: 0x8869, MAX_VERTEX_UNIFORM_VECTORS: 0x8DFB,
    MAX_VARYING_VECTORS: 0x8DFC, MAX_FRAGMENT_UNIFORM_VECTORS: 0x8DFD,
    MAX_COMBINED_TEXTURE_IMAGE_UNITS: 0x8B4D, MAX_VERTEX_TEXTURE_IMAGE_UNITS: 0x8B4C,
    MAX_TEXTURE_IMAGE_UNITS: 0x8872, MAX_SAMPLES: 0x8D57, MAX_COLOR_ATTACHMENTS: 0x8CDF,
    MAX_DRAW_BUFFERS: 0x8824, MAX_UNIFORM_BUFFER_BINDINGS: 0x8A2F,
    COMPILE_STATUS: 0x8B81, LINK_STATUS: 0x8B82, FRAMEBUFFER_COMPLETE: 0x8CD5,
  };
  const gl2Context = new Proxy({}, {
    get(_target, prop) {
      if (prop in glConsts) return glConsts[prop];
      if (prop === 'getParameter') {
        return (p) => {
          if (p === 0x1F02) return 'WebGL 2.0';
          if (p === 0x8B8C) return 'WebGL GLSL ES 3.00';
          if (p === 0x1F00 || p === 0x1F01) return 'HeadlessStub';
          if (p === 0x0D3A) return new Int32Array([8192, 8192]);
          if ([0x0D33, 0x851C, 0x84E8].includes(p)) return 8192;
          return 32;
        };
      }
      if (prop === 'getExtension') return (name) => (name === 'EXT_color_buffer_float' ? {} : null);
      if (prop === 'getSupportedExtensions') return () => ['EXT_color_buffer_float'];
      if (prop === 'getShaderPrecisionFormat') return () => ({ rangeMin: 127, rangeMax: 127, precision: 23 });
      if (prop === 'getShaderParameter') return () => true;
      if (prop === 'getProgramParameter') return (_prog, p) => (p === 0x8B82 || p === 0x8B83 ? true : 0);
      if (prop === 'getActiveUniform' || prop === 'getActiveAttrib') return () => ({ name: '', size: 1, type: 0x1406 });
      if (prop === 'getUniformIndices') return (_prog, names) => (names ?? []).map(() => 0);
      if (prop === 'getActiveUniforms') return (_prog, indices) => (indices ?? []).map(() => 0);
      if (prop === 'checkFramebufferStatus') return () => 0x8CD5;
      if (prop === 'getContextAttributes') return () => ({ alpha: false, antialias: true, depth: true, stencil: true });
      if (
        prop === 'createTexture' || prop === 'createBuffer' || prop === 'createFramebuffer' ||
        prop === 'createRenderbuffer' || prop === 'createProgram' || prop === 'createShader' ||
        prop === 'createVertexArray' || prop === 'getUniformLocation'
      ) return () => ({});
      if (prop === 'getProgramInfoLog' || prop === 'getShaderInfoLog') return () => '';
      if (typeof prop === 'string' && /^[A-Z0-9_]+$/.test(prop)) return 0;
      return () => {};
    },
  });
  const ctx2d = new Proxy({}, {
    get(_target, prop) {
      if (prop === 'measureText') return () => ({ width: 50 });
      return () => {};
    },
  });

  globalThis.__makeMockCanvas = (width = 1280, height = 720) => {
    const c = {
      width,
      height,
      style: {},
      ownerDocument: null,
      addEventListener() {},
      removeEventListener() {},
      setPointerCapture() {},
      releasePointerCapture() {},
      getRootNode() { return globalThis.document; },
      getBoundingClientRect() { return { left: 0, top: 0, width, height, right: width, bottom: height }; },
      getContext(type) {
        if (type === '2d') return ctx2d;
        if (type === 'webgl2' || type === 'webgl') return gl2Context;
        return null;
      },
    };
    c.ownerDocument = globalThis.document;
    return c;
  };

  globalThis.document = {
    documentElement: { style: {} },
    addEventListener() {},
    removeEventListener() {},
    createElement(tag) {
      if (tag === 'canvas') return globalThis.__makeMockCanvas(512, 112);
      return { style: {}, addEventListener() {}, removeEventListener() {} };
    },
    createElementNS(_ns, tag) { return this.createElement(tag); },
  };

  const nativeFetch = globalThis.fetch.bind(globalThis);
  globalThis.fetch = async (input, init) => {
    const urlStr = typeof input === 'string' ? input : input?.url ?? String(input);
    for (const [prefix, baseDir] of assetRouteMap.entries()) {
      if (urlStr.startsWith(prefix)) {
        const rel = decodeURIComponent(urlStr.slice(prefix.length));
        const fullPath = path.join(baseDir, rel);
        try {
          const buf = await fs.readFile(fullPath);
          return new Response(buf, {
            status: 200,
            headers: {
              'content-type': fullPath.endsWith('.json') ? 'application/json' : 'model/gltf-binary',
            },
          });
        } catch {
          return new Response('Not Found', { status: 404 });
        }
      }
    }
    return nativeFetch(input, init);
  };

  // Install live THREE.Scene & AnimationAction/AnimationMixer telemetry hooks on both Three.js copies
  for (const T of new Set([THREE, THREE_V02])) {
    if (!T.Object3D.prototype.__hookedSceneCapture) {
      const origAdd = T.Object3D.prototype.add;
      T.Object3D.prototype.add = function (...objects) {
        if (
          this?.isScene &&
          objects.some(
            (o) =>
              o?.name === 'REPLAY_DYNAMIC' ||
              o?.name === 'ENV_FLOOR_AND_GRID' ||
              o?.children?.some?.((c) => c?.name === 'ENV_FLOOR_AND_GRID'),
          )
        ) {
          lastCapturedScene = this;
        }
        return origAdd.apply(this, objects);
      };
      T.Object3D.prototype.__hookedSceneCapture = true;
    }
    if (!T.AnimationAction.prototype.__hookedPlayCapture) {
      const origPlay = T.AnimationAction.prototype.play;
      T.AnimationAction.prototype.play = function () {
        const root = this.getRoot?.();
        if (root?.userData) root.userData.__activeClipName = this.getClip?.()?.name ?? null;
        return origPlay.apply(this, arguments);
      };
      T.AnimationAction.prototype.__hookedPlayCapture = true;
    }
    if (!T.AnimationMixer.prototype.__hookedSetTimeCapture) {
      const origSetTime = T.AnimationMixer.prototype.setTime;
      T.AnimationMixer.prototype.setTime = function (t) {
        const root = this.getRoot?.();
        if (root?.userData) root.userData.__mixerTime = t;
        return origSetTime.apply(this, arguments);
      };
      T.AnimationMixer.prototype.__hookedSetTimeCapture = true;
    }
  }
}

function makeCanvas(w = 1280, h = 720) {
  return globalThis.__makeMockCanvas(w, h);
}

function sha256Hex(buf) {
  return crypto.createHash('sha256').update(buf).digest('hex');
}

function parseGlbChunks(buf) {
  if (buf.length < 20) throw new Error('GLB shorter than 20-byte header');
  const magic = buf.readUInt32LE(0);
  const version = buf.readUInt32LE(4);
  const totalLen = buf.readUInt32LE(8);
  if (magic !== 0x46546C67 || version !== 2) {
    throw new Error(`Invalid GLB header magic=0x${magic.toString(16)} version=${version}`);
  }
  let offset = 12;
  let jsonDoc = null;
  let binChunk = null;
  while (offset + 8 <= Math.min(buf.length, totalLen)) {
    const chunkLen = buf.readUInt32LE(offset);
    const chunkType = buf.readUInt32LE(offset + 4);
    const body = buf.subarray(offset + 8, offset + 8 + chunkLen);
    if (chunkType === 0x4E4F534A) {
      jsonDoc = JSON.parse(body.toString('utf8'));
    } else if (chunkType === 0x004E4942) {
      binChunk = body;
    }
    offset += 8 + chunkLen;
  }
  return { magic, version, totalLen, jsonDoc, binChunk };
}

async function parseGltfScene(buf) {
  const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
  return new Promise((resolve, reject) => {
    new GLTFLoader().parse(ab, '', resolve, reject);
  });
}

function boxToDict(box) {
  if (!box || box.isEmpty()) return null;
  return {
    min: [box.min.x, box.min.y, box.min.z],
    max: [box.max.x, box.max.y, box.max.z],
    span: [box.max.x - box.min.x, box.max.y - box.min.y, box.max.z - box.min.z],
  };
}

function countSceneMeshesAndTris(root) {
  let meshCount = 0;
  let triangleCount = 0;
  let nanVertices = 0;
  let zeroAreaTriangles = 0;
  root.updateMatrixWorld(true);
  const p0 = new THREE.Vector3();
  const p1 = new THREE.Vector3();
  const p2 = new THREE.Vector3();
  const e1 = new THREE.Vector3();
  const e2 = new THREE.Vector3();
  const cr = new THREE.Vector3();

  root.traverse((obj) => {
    if (!obj.isMesh || !obj.geometry?.attributes?.position) return;
    meshCount++;
    const pos = obj.geometry.attributes.position;
    const idx = obj.geometry.index;
    for (let i = 0; i < pos.count; i++) {
      if (!Number.isFinite(pos.getX(i)) || !Number.isFinite(pos.getY(i)) || !Number.isFinite(pos.getZ(i))) {
        nanVertices++;
      }
    }
    const triCount = idx ? Math.floor(idx.count / 3) : Math.floor(pos.count / 3);
    triangleCount += triCount;
    if (!obj.isSkinnedMesh) {
      for (let t = 0; t < triCount; t++) {
        const i0 = idx ? idx.getX(3 * t) : 3 * t;
        const i1 = idx ? idx.getX(3 * t + 1) : 3 * t + 1;
        const i2 = idx ? idx.getX(3 * t + 2) : 3 * t + 2;
        p0.fromBufferAttribute(pos, i0).applyMatrix4(obj.matrixWorld);
        p1.fromBufferAttribute(pos, i1).applyMatrix4(obj.matrixWorld);
        p2.fromBufferAttribute(pos, i2).applyMatrix4(obj.matrixWorld);
        e1.subVectors(p1, p0);
        e2.subVectors(p2, p0);
        const area = 0.5 * cr.crossVectors(e1, e2).length();
        if (area < 1e-12) zeroAreaTriangles++;
      }
    }
  });
  return { meshCount, triangleCount, nanVertices, zeroAreaTriangles };
}

function effectiveUserData(node, stopRoot = null) {
  const merged = {};
  const chain = [];
  for (let cur = node; cur && cur !== stopRoot; cur = cur.parent) chain.push(cur);
  for (const anc of chain.reverse()) Object.assign(merged, anc.userData || {});
  return merged;
}

function worldRotation(node) {
  const chain = [];
  for (let cur = node; cur; cur = cur.parent) chain.push(cur.quaternion);
  const q = new THREE.Quaternion();
  for (const rot of chain.reverse()) q.multiply(rot);
  return q.normalize();
}

function maxPairwiseDistance(points) {
  let maxSq = 0;
  for (let i = 0; i < points.length; i++) {
    for (let j = i + 1; j < points.length; j++) {
      const dSq = points[i].distanceToSquared(points[j]);
      if (dSq > maxSq) maxSq = dSq;
    }
  }
  return Math.sqrt(maxSq);
}

function maxPairwiseAngleRad(quats) {
  let maxAng = 0;
  for (let i = 0; i < quats.length; i++) {
    for (let j = i + 1; j < quats.length; j++) {
      const dot = Math.min(1, Math.abs(quats[i].dot(quats[j])));
      const ang = 2 * Math.acos(dot);
      if (ang > maxAng) maxAng = ang;
    }
  }
  return maxAng;
}

function readFloat32Accessor(jsonDoc, binChunk, accessorIdx) {
  const acc = jsonDoc.accessors?.[accessorIdx];
  if (!acc || acc.componentType !== 5126) return null;
  const bv = jsonDoc.bufferViews?.[acc.bufferView];
  if (!bv || !binChunk) return null;
  const byteOffset = (bv.byteOffset ?? 0) + (acc.byteOffset ?? 0);
  const stride = bv.byteStride ?? 4;
  const out = new Float32Array(acc.count);
  for (let i = 0; i < acc.count; i++) {
    out[i] = binChunk.readFloatLE(byteOffset + i * stride);
  }
  return out;
}

function checkCadenceFromRawGlb(jsonDoc, binChunk) {
  const offGridSamplers = [];
  const clipCadence = {};
  for (const anim of jsonDoc?.animations ?? []) {
    let maxTime = 0;
    let samplerCount = 0;
    let animOffGrid = 0;
    for (let sIdx = 0; sIdx < (anim.samplers ?? []).length; sIdx++) {
      const s = anim.samplers[sIdx];
      const times = readFloat32Accessor(jsonDoc, binChunk, s.input);
      if (!times || times.length === 0) continue;
      samplerCount++;
      const endT = times[times.length - 1];
      if (endT > maxTime) maxTime = endT;
      for (let f = 0; f < times.length; f++) {
        const nearestFrame = Math.round(times[f] * 30);
        if (Math.abs(times[f] - nearestFrame / 30) > 3e-4) {
          animOffGrid++;
          if (offGridSamplers.length < 25) {
            offGridSamplers.push({ clip: anim.name, sampler: sIdx, frameIdx: f, time: times[f] });
          }
          break;
        }
      }
    }
    const intervals = Math.round(maxTime * 30);
    const durationGridErr = Math.abs(maxTime - intervals / 30);
    clipCadence[anim.name] = {
      duration: maxTime,
      intervals,
      durationGridErr,
      samplerCount,
      offGridCount: animOffGrid,
    };
  }
  return { offGridSamplers, clipCadence };
}

async function inspectCharacterGlb(buf, kind) {
  const report = await validator.validateBytes(new Uint8Array(buf), {
    uri: `${kind}.glb`,
    maxIssues: 100,
  });
  const { jsonDoc, binChunk } = parseGlbChunks(buf);
  const gltf = await parseGltfScene(buf);
  gltf.scene.updateMatrixWorld(true);

  const clipNames = gltf.animations.map((a) => a.name);
  const forbiddenClips = clipNames.filter((n) => /^(Pick|Inspect)(_Oversize)?$/.test(n));
  const rawNodeNames = (jsonDoc.nodes ?? []).map((n) => n.name ?? '');

  // DemoSupport & operational prop metadata audit
  const demoSupportNodes = [];
  const propMeshInfos = [];
  for (const n of jsonDoc.nodes ?? []) {
    if (/DemoSupport/i.test(n.name ?? '')) demoSupportNodes.push(n.name);
  }

  let totalSkinnedVerts = 0;
  let unweightedVerts = 0;
  let rawUnweightedVerts = 0;
  let outOfRangeIndices = 0;
  let nonNormalizedVerts = 0;
  let nonRigidArmorVerts = 0;
  let helmetHeadWeighted = false;
  const boneSet = new Map();

  // Inspect raw GLB WEIGHTS_0 accessors BEFORE GLTFLoader.normalizeSkinWeights() masks (0,0,0,0) -> (1,0,0,0)
  for (const nodeDef of jsonDoc.nodes ?? []) {
    if (nodeDef.skin === undefined || nodeDef.mesh === undefined) continue;
    const meshDef = jsonDoc.meshes?.[nodeDef.mesh];
    for (const prim of meshDef?.primitives ?? []) {
      const wAccIdx = prim?.attributes?.WEIGHTS_0;
      if (wAccIdx === undefined) continue;
      const wArr = readFloat32Accessor(jsonDoc, binChunk, wAccIdx);
      if (!wArr) continue;
      for (let vi = 0; vi + 3 < wArr.length; vi += 4) {
        const w0 = wArr[vi], w1 = wArr[vi + 1], w2 = wArr[vi + 2], w3 = wArr[vi + 3];
        const s = w0 + w1 + w2 + w3;
        if (!Number.isFinite(s) || s <= 1e-4) rawUnweightedVerts++;
      }
    }
  }

  gltf.scene.traverse((obj) => {
    const ud = effectiveUserData(obj, gltf.scene);
    if (/DemoSupport/i.test(obj.name) || ud.handling_prop === 'support') {
      if (!demoSupportNodes.includes(obj.name)) demoSupportNodes.push(obj.name);
    }
    if (obj.isBone) boneSet.set(obj.name, obj);
    if (obj.isMesh || obj.isSkinnedMesh) {
      const chainNames = [];
      for (let c = obj; c && c !== gltf.scene; c = c.parent) chainNames.push(c.name);
      const joined = chainNames.join('/');
      const isPropMesh = Boolean(
        ud.operation_prop !== undefined ||
        ud.handling_prop !== undefined ||
        /_(OpenCarton|DemoCarton|Carton|Flap_|Product|PickingTote|SealingTape)/i.test(joined) ||
        /\bprop_/i.test(joined),
      );
      if (isPropMesh && !/DemoSupport/i.test(joined)) {
        propMeshInfos.push({
          name: obj.name,
          operation_prop: ud.operation_prop === true,
          demo_only: ud.demo_only === true,
          handling_prop: ud.handling_prop ?? null,
        });
      }
    }
    if (!obj.isSkinnedMesh) return;
    const bones = obj.skeleton?.bones ?? [];
    for (const b of bones) boneSet.set(b.name, b);
    const boneCount = bones.length;
    const pos = obj.geometry.attributes.position;
    const sw = obj.geometry.attributes.skinWeight;
    const si = obj.geometry.attributes.skinIndex;
    if (!sw || !si || sw.count !== pos.count || si.count !== pos.count) {
      unweightedVerts += pos.count;
      return;
    }
    const headIdx = bones.findIndex((b) => b.name === 'head');
    const isHelmet = /Helmet/i.test(obj.name) || /Helmet/i.test(obj.parent?.name ?? '');
    const isRobotBodyArmor =
      kind === 'robot' &&
      !/_(OpenCarton|DemoCarton|Carton|Flap_|Product|PickingTote|SealingTape)/i.test(
        `${obj.parent?.name ?? ''}/${obj.name}`,
      );

    for (let i = 0; i < pos.count; i++) {
      totalSkinnedVerts++;
      const w = [sw.getX(i), sw.getY(i), sw.getZ(i), sw.getW(i)];
      const idx = [si.getX(i), si.getY(i), si.getZ(i), si.getW(i)];
      const sum = w[0] + w[1] + w[2] + w[3];
      if (!w.every(Number.isFinite) || sum <= 1e-4) {
        unweightedVerts++;
      } else if (Math.abs(sum - 1.0) > 1e-2) {
        nonNormalizedVerts++;
      }
      let nonZeroCount = 0;
      for (let k = 0; k < 4; k++) {
        if (w[k] > 1e-6) {
          nonZeroCount++;
          if (!Number.isInteger(idx[k]) || idx[k] < 0 || idx[k] >= boneCount) {
            outOfRangeIndices++;
          }
          if (isHelmet && idx[k] === headIdx && w[k] > 0.5) helmetHeadWeighted = true;
        }
      }
      if (isRobotBodyArmor && nonZeroCount > 1) {
        // Check if blended across distinct body bones (non-prop)
        const activeBones = new Set();
        for (let k = 0; k < 4; k++) {
          if (w[k] > 1e-3 && bones[idx[k]]) activeBones.add(bones[idx[k]].name);
        }
        if (activeBones.size > 1) nonRigidArmorVerts++;
      }
    }
  });

  // Also check if helmet is a rigid Mesh parented directly to head bone
  gltf.scene.traverse((obj) => {
    if (/Helmet/i.test(obj.name)) {
      for (let c = obj.parent; c; c = c.parent) {
        if (c.name === 'head') helmetHeadWeighted = true;
      }
    }
  });

  const boneNames = [...boneSet.keys()];
  const missingPropBones = REQUIRED_PROP_BONES.filter((b) => !boneSet.has(b));
  const sockLName = kind === 'worker' ? 'ATTACH_WORKER_HAND_L' : 'ATTACH_ROBOT_HAND_L';
  const sockRName = kind === 'worker' ? 'ATTACH_WORKER_HAND_R' : 'ATTACH_ROBOT_HAND_R';
  const sockL = gltf.scene.getObjectByName(sockLName);
  const sockR = gltf.scene.getObjectByName(sockRName);

  // Record rest-pose world positions of bones for worker-vs-robot proportion parity
  const restBonePositions = {};
  for (const [bName, bObj] of boneSet.entries()) {
    const wp = bObj.getWorldPosition(new THREE.Vector3());
    restBonePositions[bName] = [wp.x, wp.y, wp.z];
  }

  const cadence = checkCadenceFromRawGlb(jsonDoc, binChunk);

  // Step every clip at 30 FPS to measure body motion, prop scales, prop choreography, and joint inversions
  const bodyBones = [...boneSet.values()].filter((b) => !b.name.startsWith('prop_'));
  const propBones = [...boneSet.values()].filter((b) => b.name.startsWith('prop_'));
  const clipMetrics = {};
  const scaleVec = new THREE.Vector3();

  for (const clip of gltf.animations) {
    const mixer = new THREE.AnimationMixer(gltf.scene);
    const action = mixer.clipAction(clip);
    action.play();

    const frames = Math.max(1, Math.round(clip.duration * 30));
    const bodyTraj = bodyBones.map(() => []);
    const bodyQuats = bodyBones.map(() => []);
    const propPosTraj = new Map(propBones.map((b) => [b.name, []]));
    const propScaleTraj = new Map(propBones.map((b) => [b.name, []]));
    const propRotTraj = new Map(propBones.map((b) => [b.name, []]));

    let maxPropWorldScale = 0;
    let nonFiniteMatrices = 0;
    let maxConsecutiveStepDeg = 0;
    let spineOrderViolations = 0;
    let minBodyBoneY = Infinity;
    let maxPalmDot = -Infinity;
    let maxHandSpanX = 0;

    const hipsBone = boneSet.get('hips');
    const spineBone = boneSet.get('spine');
    const chestBone = boneSet.get('chest');
    const headBone = boneSet.get('head');

    for (let f = 0; f <= frames; f++) {
      mixer.setTime(f / 30);
      gltf.scene.updateMatrixWorld(true);

      for (let bi = 0; bi < bodyBones.length; bi++) {
        const b = bodyBones[bi];
        if (!b.matrixWorld.elements.every(Number.isFinite)) nonFiniteMatrices++;
        const wp = b.getWorldPosition(new THREE.Vector3());
        if (wp.y < minBodyBoneY) minBodyBoneY = wp.y;
        bodyTraj[bi].push(wp);
        const wq = worldRotation(b);
        if (f > 0) {
          const prevQ = bodyQuats[bi][f - 1];
          const dot = Math.min(1, Math.abs(prevQ.dot(wq)));
          const deg = 2 * Math.acos(dot) * (180 / Math.PI);
          if (deg > maxConsecutiveStepDeg) maxConsecutiveStepDeg = deg;
        }
        bodyQuats[bi].push(wq);
      }

      if (hipsBone && spineBone && chestBone && headBone) {
        const hy = hipsBone.getWorldPosition(new THREE.Vector3()).y;
        const sy = spineBone.getWorldPosition(new THREE.Vector3()).y;
        const cy = chestBone.getWorldPosition(new THREE.Vector3()).y;
        const hdy = headBone.getWorldPosition(new THREE.Vector3()).y;
        if (!(hdy > cy && cy > sy && sy > hy && hy > 0.45)) {
          spineOrderViolations++;
        }
      }

      if (sockL && sockR) {
        const pL = sockL.getWorldPosition(new THREE.Vector3());
        const pR = sockR.getWorldPosition(new THREE.Vector3());
        const spanX = Math.abs(pL.x - pR.x);
        if (spanX > maxHandSpanX) maxHandSpanX = spanX;
        const qL = worldRotation(sockL);
        const qR = worldRotation(sockR);
        const nL = new THREE.Vector3(1, 0, 0).applyQuaternion(qL).normalize();
        const nR = new THREE.Vector3(1, 0, 0).applyQuaternion(qR).normalize();
        const pd = nL.dot(nR);
        if (pd > maxPalmDot) maxPalmDot = pd;
      }

      for (const pb of propBones) {
        const ws = scaleVec.setFromMatrixScale(pb.matrixWorld).length();
        if (ws > maxPropWorldScale) maxPropWorldScale = ws;
        propScaleTraj.get(pb.name).push(ws);
        propPosTraj.get(pb.name).push(pb.getWorldPosition(new THREE.Vector3()));
        propRotTraj.get(pb.name).push(worldRotation(pb));
      }
    }

    const maxBodyDeltaM = bodyTraj.length > 0 ? Math.max(...bodyTraj.map(maxPairwiseDistance)) : 0;
    const propDetails = {};
    for (const pb of propBones) {
      const scales = propScaleTraj.get(pb.name);
      const minS = Math.min(...scales);
      const maxS = Math.max(...scales);
      propDetails[pb.name] = {
        maxWorldScale: maxS,
        scaleDelta: maxS - minS,
        posDeltaM: maxPairwiseDistance(propPosTraj.get(pb.name)),
        rotDeltaRad: maxPairwiseAngleRad(propRotTraj.get(pb.name)),
      };
    }

    clipMetrics[clip.name] = {
      duration: clip.duration,
      frames,
      maxBodyDeltaM,
      maxPropWorldScale,
      nonFiniteMatrices,
      maxConsecutiveStepDeg,
      spineOrderViolations,
      minBodyBoneY,
      maxPalmDot,
      maxHandSpanX,
      props: propDetails,
    };
    mixer.stopAllAction();
  }

  // Visual integration runtime adapter check (phase 0 vs 0.5 non-freezing & active prop visibility)
  let adapterAudit = { ok: false, error: null };
  try {
    const actorVis = createActorVisual(gltf, { actorType: kind });
    actorVis.sample({ state: 'pack', phase: 0.5 });
    actorVis.root.updateMatrixWorld(true);
    let visibleOpPropsInPack = 0;
    actorVis.root.traverse((o) => {
      const ud = effectiveUserData(o, actorVis.root);
      if ((o.isMesh || o.isSkinnedMesh) && ud.operation_prop === true && o.visible) {
        const s = scaleVec.setFromMatrixScale(o.matrixWorld).length();
        if (s > 0.05) visibleOpPropsInPack++;
      }
    });

    const sig = () => {
      actorVis.root.updateMatrixWorld(true);
      const vals = [];
      actorVis.root.traverse((o) => {
        if (o.isBone && !o.name.startsWith('prop_')) vals.push(...o.matrixWorld.elements);
      });
      return vals;
    };
    const statePhaseDiffs = {};
    const checkStates = kind === 'worker' ? ['assist', 'break', 'pack'] : ['pack', 'jammed', 'service', 'disabled'];
    for (const st of checkStates) {
      actorVis.sample({ state: st, phase: 0.0 });
      const s0 = sig();
      actorVis.sample({ state: st, phase: 0.5 });
      const s1 = sig();
      let maxElemDiff = 0;
      for (let i = 0; i < Math.min(s0.length, s1.length); i++) {
        const d = Math.abs(s0[i] - s1[i]);
        if (d > maxElemDiff) maxElemDiff = d;
      }
      statePhaseDiffs[st] = maxElemDiff;
    }
    adapterAudit = { ok: true, visibleOpPropsInPack, statePhaseDiffs };
  } catch (err) {
    adapterAudit = { ok: false, error: String(err?.message ?? err) };
  }

  return {
    kind,
    numErrors: report.issues.numErrors,
    numWarnings: report.issues.numWarnings,
    boneCount: boneNames.length,
    boneNames,
    missingPropBones,
    rawNodeNames,
    clipNames,
    forbiddenClips,
    demoSupportNodes,
    propMeshInfos,
    skinning: {
      totalSkinnedVerts,
      unweightedVerts: Math.max(unweightedVerts, rawUnweightedVerts),
      outOfRangeIndices,
      nonNormalizedVerts,
      nonRigidArmorVerts,
      helmetHeadWeighted,
    },
    sockets: {
      leftExists: Boolean(sockL),
      rightExists: Boolean(sockR),
      leftParent: sockL?.parent?.name ?? null,
      rightParent: sockR?.parent?.name ?? null,
    },
    restBonePositions,
    cadence,
    clipMetrics,
    adapterAudit,
  };
}

function auditWorkstationGrasp(workerGltf, robotGltf, layoutGltf, bindings) {
  const results = {};
  const stageConfigs = [
    {
      key: 'stage1_worker',
      gltf: workerGltf,
      kind: 'worker',
      workPos: bindings.stages[0].actor_position_gltf_m,
      yaw: bindings.stages[0].yaw_gltf_rad,
      orderAnchor: 'VIS_STAGE_1_ORDER',
      clips: [['Prepare', 'regular'], ['Prepare_Oversize', 'oversize']],
    },
    {
      key: 'stage2_worker',
      gltf: workerGltf,
      kind: 'worker',
      workPos: bindings.stages[1].actor_position_gltf_m,
      yaw: bindings.stages[1].yaw_gltf_rad,
      orderAnchor: 'VIS_STAGE_2_ORDER',
      clips: [['Pick', 'regular'], ['Pick_Oversize', 'oversize']],
    },
    {
      key: 'stage3_worker',
      gltf: workerGltf,
      kind: 'worker',
      workPos: bindings.stages[2].actor_position_gltf_m,
      yaw: bindings.stages[2].yaw_gltf_rad,
      orderAnchor: 'VIS_STAGE_3_ORDER',
      clips: [['Pack', 'regular'], ['Pack_Oversize', 'oversize']],
    },
    {
      key: 'stage4_worker',
      gltf: workerGltf,
      kind: 'worker',
      workPos: bindings.stages[3].actor_position_gltf_m,
      yaw: bindings.stages[3].yaw_gltf_rad,
      orderAnchor: 'VIS_STAGE_4_ORDER',
      clips: [['Inspect', 'regular'], ['Inspect_Oversize', 'oversize']],
    },
    {
      key: 'stage3_robot',
      gltf: robotGltf,
      kind: 'robot',
      workPos: bindings.robot.position_gltf_m ?? bindings.robot.actor_position_gltf_m ?? [3.5, 0, -2.05],
      yaw: bindings.robot.yaw_gltf_rad,
      orderAnchor: 'VIS_ROBOT_ORDER',
      clips: [['RobotPack', 'regular'], ['RobotPack_Oversize', 'oversize']],
    },
  ];

  const scaleVec = new THREE.Vector3();

  for (const cfg of stageConfigs) {
    const ordNode = layoutGltf.scene.getObjectByName(cfg.orderAnchor);
    if (!ordNode) continue;
    const ordPos = ordNode.getWorldPosition(new THREE.Vector3());
    const rig = SkeletonUtils.clone(cfg.gltf.scene);
    rig.position.set(cfg.workPos[0], cfg.workPos[1], cfg.workPos[2]);
    rig.rotation.set(0, cfg.yaw, 0);
    rig.updateMatrixWorld(true);

    const sockL = rig.getObjectByName(cfg.kind === 'worker' ? 'ATTACH_WORKER_HAND_L' : 'ATTACH_ROBOT_HAND_L');
    const sockR = rig.getObjectByName(cfg.kind === 'worker' ? 'ATTACH_WORKER_HAND_R' : 'ATTACH_ROBOT_HAND_R');
    const propBoneNodes = [];
    rig.traverse((o) => {
      if (o.isBone && o.name.startsWith('prop_')) propBoneNodes.push(o);
    });

    for (const [clipName, orderKind] of cfg.clips) {
      const clip = cfg.gltf.animations.find((a) => a.name === clipName);
      if (!clip || !sockL || !sockR) continue;
      const dims = orderKind === 'oversize' ? [0.48, 0.32, 0.34] : [0.36, 0.25, 0.28];

      for (const trayOffset of [0.0, 0.012]) {
        const baseY = ordPos.y + trayOffset;
        const targetBox = new THREE.Box3(
          new THREE.Vector3(ordPos.x - dims[0] / 2, baseY, ordPos.z - dims[2] / 2),
          new THREE.Vector3(ordPos.x + dims[0] / 2, baseY + dims[1], ordPos.z + dims[2] / 2),
        );

        const mixer = new THREE.AnimationMixer(rig);
        mixer.clipAction(clip).play();
        const frames = Math.max(1, Math.round(clip.duration * 30));

        let minDistL = Infinity;
        let minDistR = Infinity;
        let minOverBenchSocketY = Infinity;
        let minOverBenchPropY = Infinity;

        for (let f = 0; f <= frames; f++) {
          mixer.setTime(f / 30);
          rig.updateMatrixWorld(true);
          const pL = sockL.getWorldPosition(new THREE.Vector3());
          const pR = sockR.getWorldPosition(new THREE.Vector3());

          // Distance to target carton box OR active articulated flap/carton bones
          let dL = targetBox.distanceToPoint(pL);
          let dR = targetBox.distanceToPoint(pR);
          for (const pb of propBoneNodes) {
            const ws = scaleVec.setFromMatrixScale(pb.matrixWorld).length();
            if (ws > 0.5) {
              const pp = pb.getWorldPosition(new THREE.Vector3());
              // Check if prop sits near workstation order anchor
              if (Math.hypot(pp.x - ordPos.x, pp.z - ordPos.z) < 0.45) {
                dL = Math.min(dL, Math.max(0, pL.distanceTo(pp) - 0.18));
                dR = Math.min(dR, Math.max(0, pR.distanceTo(pp) - 0.18));
              }
            }
          }
          if (dL < minDistL) minDistL = dL;
          if (dR < minDistR) minDistR = dR;

          if (trayOffset === 0.0) {
            for (const sp of [pL, pR]) {
              if (Math.abs(sp.x - ordPos.x) <= 0.50 && sp.z >= ordPos.z - 0.45 && sp.z <= ordPos.z + 0.28) {
                if (sp.y < minOverBenchSocketY) minOverBenchSocketY = sp.y;
              }
            }
            for (const pb of propBoneNodes) {
              const ws = scaleVec.setFromMatrixScale(pb.matrixWorld).length();
              if (ws > 0.5) {
                const pp = pb.getWorldPosition(new THREE.Vector3());
                if (Math.abs(pp.x - ordPos.x) <= 0.50 && pp.z >= ordPos.z - 0.45 && pp.z <= ordPos.z + 0.28) {
                  if (pp.y < minOverBenchPropY) minOverBenchPropY = pp.y;
                }
              }
            }
          }
        }
        mixer.stopAllAction();
        results[`${cfg.key}_${clipName}_tray${trayOffset === 0 ? '0' : '12mm'}`] = {
          minDistL,
          minDistR,
          minOverBenchSocketY: Number.isFinite(minOverBenchSocketY) ? minOverBenchSocketY : 0.90,
          minOverBenchPropY: Number.isFinite(minOverBenchPropY) ? minOverBenchPropY : 0.86,
        };
      }
    }
  }
  return results;
}

function auditLayoutAndSupport(layoutGltf, supportGltf, bindings, anchorsJson) {
  layoutGltf.scene.updateMatrixWorld(true);
  supportGltf.scene.updateMatrixWorld(true);

  const layoutNodeNames = [];
  layoutGltf.scene.traverse((o) => {
    if (o !== layoutGltf.scene && o.name) layoutNodeNames.push(o.name);
  });

  const chamfer = layoutGltf.scene.getObjectByName('VIS_Bench_top_robot_chamfer');
  const chamferBox = chamfer ? boxToDict(new THREE.Box3().setFromObject(chamfer, true)) : null;

  const queueRacks = {};
  for (const qId of ['Q2', 'Q3', 'Q4']) {
    const topObj = layoutGltf.scene.getObjectByName(`VIS_QUEUE_${qId}_TOP`);
    const labelObj = layoutGltf.scene.getObjectByName(`VIS_QUEUE_${qId}_LABEL`);
    const guideObjs = [];
    layoutGltf.scene.traverse((o) => {
      if (o.isMesh && o.name.startsWith(`VIS_QUEUE_${qId}_GUIDE`)) guideObjs.push(o);
    });
    const previewCount =
      bindings.queues[qId]?.preview_count ??
      bindings.queues[qId]?.preview_slots ??
      bindings.queues[qId]?.preview_slot_count ??
      ({ Q2: 12, Q3: 10, Q4: 8 }[qId] ?? 8);
    const slots = queueSlotPositions(bindings, qId, previewCount);
    let maxGuideSlotOverlapM = 0;
    for (const g of guideObjs) {
      const gb = new THREE.Box3().setFromObject(g, true);
      for (const sp of slots) {
        const ox = Math.min(gb.max.x, sp[0] + 0.27) - Math.max(gb.min.x, sp[0] - 0.27);
        const oz = Math.min(gb.max.z, sp[2] + 0.20) - Math.max(gb.min.z, sp[2] - 0.20);
        if (ox > 0 && oz > 0 && gb.max.y > 0.861) {
          maxGuideSlotOverlapM = Math.max(maxGuideSlotOverlapM, Math.min(ox, oz));
        }
      }
    }
    queueRacks[qId] = {
      topAabb: topObj ? boxToDict(new THREE.Box3().setFromObject(topObj, true)) : null,
      labelAabb: labelObj ? boxToDict(new THREE.Box3().setFromObject(labelObj, true)) : null,
      maxGuideSlotOverlapM,
    };
  }

  const assistNode = layoutGltf.scene.getObjectByName('VIS_ROBOT_ASSIST');
  const robotOrderNode = layoutGltf.scene.getObjectByName('VIS_ROBOT_ORDER');
  let staticAssistInfo = null;
  if (assistNode && robotOrderNode) {
    const ap = assistNode.getWorldPosition(new THREE.Vector3());
    const rp = robotOrderNode.getWorldPosition(new THREE.Vector3());
    const aq = assistNode.getWorldQuaternion(new THREE.Quaternion());
    const fwd = new THREE.Vector3(0, 0, 1).applyQuaternion(aq);
    const fwdXZ = new THREE.Vector3(fwd.x, 0, fwd.z).normalize();
    const targetXZ = new THREE.Vector3(rp.x - ap.x, 0, rp.z - ap.z).normalize();
    const bindingsYaw =
      bindings.robot?.helper_yaw_gltf_rad ??
      bindings.robot?.assist_yaw_gltf_rad ??
      null;
    let bindingsHelperCosSim = null;
    if (typeof bindingsYaw === 'number' && Number.isFinite(bindingsYaw)) {
      const bq = new THREE.Quaternion().setFromEuler(new THREE.Euler(0, bindingsYaw, 0));
      const bf = new THREE.Vector3(0, 0, 1).applyQuaternion(bq);
      bindingsHelperCosSim = new THREE.Vector3(bf.x, 0, bf.z).normalize().dot(targetXZ);
    }
    const spatialAssistYawRad =
      typeof SpatialMod.robotAssistYaw === 'function' ? SpatialMod.robotAssistYaw(bindings) : null;
    let spatialAssistCosSim = null;
    if (typeof spatialAssistYawRad === 'number' && Number.isFinite(spatialAssistYawRad)) {
      const sq = new THREE.Quaternion().setFromEuler(new THREE.Euler(0, spatialAssistYawRad, 0));
      const sf = new THREE.Vector3(0, 0, 1).applyQuaternion(sq);
      spatialAssistCosSim = new THREE.Vector3(sf.x, 0, sf.z).normalize().dot(targetXZ);
    }
    staticAssistInfo = {
      assistPos: [ap.x, ap.y, ap.z],
      robotOrderPos: [rp.x, rp.y, rp.z],
      expectedYawRad: Math.atan2(0.70, -0.44),
      nodeCosSim: fwdXZ.dot(targetXZ),
      bindingsHelperYaw: bindingsYaw,
      bindingsHelperCosSim,
      spatialAssistYawRad,
      spatialAssistCosSim,
    };
  }

  // Conveyor joint gaps in anchors.json (supports both {id, position_m} array and {name: ...} object schemas)
  const anchorEntries = anchorsJson?.anchors ?? anchorsJson ?? {};
  const getAnchorPos = (name) => {
    if (Array.isArray(anchorEntries)) {
      const f = anchorEntries.find((e) => (e?.id ?? e?.name) === name);
      return f?.position_m ?? f?.position_gltf_m ?? f?.location_gltf_m ?? f?.position ?? null;
    }
    const v = anchorEntries[name];
    return Array.isArray(v)
      ? v
      : (v?.position_m ?? v?.position_gltf_m ?? v?.location_gltf_m ?? v?.position ?? null);
  };
  let maxConveyorJointGapM = 0;
  let conveyorJointCount = 0;
  for (let i = 1; i <= 9; i++) {
    const aOut = getAnchorPos(`ANCHOR_C${String(i).padStart(2, '0')}_OUT`);
    const bIn = getAnchorPos(`ANCHOR_C${String(i + 1).padStart(2, '0')}_IN`);
    if (aOut && bIn) {
      conveyorJointCount++;
      const d = Math.hypot(aOut[0] - bIn[0], aOut[1] - bIn[1], aOut[2] - bIn[2]);
      if (d > maxConveyorJointGapM) maxConveyorJointGapM = d;
    }
  }
  let anchorsOutOfHall = 0;
  const iterAnchors = Array.isArray(anchorEntries) ? anchorEntries : Object.values(anchorEntries);
  for (const ent of iterAnchors) {
    const p = Array.isArray(ent)
      ? ent
      : (ent?.position_m ?? ent?.position_gltf_m ?? ent?.location_gltf_m ?? ent?.position);
    if (Array.isArray(p) && p.length >= 3) {
      if (Math.abs(p[0]) > 18.05 || p[1] < -0.25 || p[1] > 3.65 || Math.abs(p[2]) > 9.05) {
        anchorsOutOfHall++;
      }
    }
  }

  // Support templates audit (14 VIS_* templates per PROJECT.md §1 & visual_bindings.json)
  const expectedTemplates = [
    'VIS_manual_bench',
    'VIS_order_regular',
    'VIS_order_fragile',
    'VIS_order_oversize',
    'VIS_order_tray',
    'VIS_empty_slot',
    'VIS_reserved_slot',
    'VIS_status_jammed',
    'VIS_status_service',
    'VIS_status_break',
    'VIS_status_offline',
    'VIS_outcome_good',
    'VIS_outcome_escaped',
    'VIS_outcome_scrap',
  ];
  const supportTemplates = {};
  for (const tName of expectedTemplates) {
    const tObj = supportGltf.scene.getObjectByName(tName);
    if (!tObj) {
      supportTemplates[tName] = { exists: false };
      continue;
    }
    const clone = tObj.clone(true);
    clone.position.set(0, 0, 0);
    clone.rotation.set(0, 0, 0);
    clone.scale.set(1, 1, 1);
    clone.updateMatrixWorld(true);
    const lb = new THREE.Box3().setFromObject(clone, true);
    supportTemplates[tName] = {
      exists: true,
      localAabb: boxToDict(lb),
      centerXZ: [(lb.min.x + lb.max.x) / 2, (lb.min.z + lb.max.z) / 2],
    };
  }

  return {
    layoutAudit: {
      nodeCount: layoutNodeNames.length,
      nodeNames: layoutNodeNames,
      chamfer: {
        exists: Boolean(chamfer),
        parent: chamfer?.parent?.name ?? null,
        aabb: chamferBox,
      },
      queueRacks,
      staticAssistInfo,
      conveyorJointCount,
      maxConveyorJointGapM,
      anchorsOutOfHall,
    },
    supportAudit: {
      templates: supportTemplates,
    },
  };
}

function triangleIntersectsBoxXZ_Y(p0, p1, p2, box) {
  const minX = Math.min(p0.x, p1.x, p2.x);
  const maxX = Math.max(p0.x, p1.x, p2.x);
  const minY = Math.min(p0.y, p1.y, p2.y);
  const maxY = Math.max(p0.y, p1.y, p2.y);
  const minZ = Math.min(p0.z, p1.z, p2.z);
  const maxZ = Math.max(p0.z, p1.z, p2.z);
  if (
    maxX < box.min.x || minX > box.max.x ||
    maxY < box.min.y || minY > box.max.y ||
    maxZ < box.min.z || minZ > box.max.z
  ) {
    return false;
  }
  const tri = new THREE.Triangle(p0, p1, p2);
  return box.intersectsTriangle(tri);
}

function isEffectivelyVisibleNode(obj) {
  for (let cur = obj; cur; cur = cur.parent) {
    if (cur.visible === false) return false;
  }
  return true;
}

function isForbiddenOverheadMeshNode(obj) {
  if (!obj?.isMesh) return false;
  for (let cur = obj; cur; cur = cur.parent) {
    const nm = cur.name ?? '';
    if (/^(ENV_OVERHEAD|OVERHEAD_TRUSS|OVERHEAD_CABLE_TRAY|HIGHBAY|HIGH_BAY|ENV_LIGHTING_RIG|CEILING_BEAM|HANGING_LAMP)/i.test(nm)) {
      return true;
    }
    if (/\b(OVERHEAD_TRUSS|OVERHEAD_CABLE_TRAY|HIGHBAY|LIGHTING_RIG|CEILING_BEAM|HANGING_LAMP|RAFTER)\b/i.test(nm)) {
      return true;
    }
    if (/^(Cable_tray_|Truss_|Rafter_|Highbay_)/i.test(nm) || /^Truss\b/i.test(nm)) {
      return true;
    }
  }
  return false;
}

function measureVerticesBoxOnRoots(roots, nodeNames) {
  const pt = new THREE.Vector3();
  let meshCount = 0;
  let minX = Infinity, maxX = -Infinity;
  let minY = Infinity, maxY = -Infinity;
  let minZ = Infinity, maxZ = -Infinity;
  const foundNodes = [];
  for (const r of roots) {
    if (!r) continue;
    r.updateMatrixWorld(true);
    for (const name of nodeNames) {
      const target = r.getObjectByName(name);
      if (!target) continue;
      if (!foundNodes.includes(name)) foundNodes.push(name);
      target.traverse((o) => {
        if (!isEffectivelyVisibleNode(o) || !o.isMesh || !o.geometry?.attributes?.position) return;
        const pos = o.geometry.attributes.position;
        if (pos.count === 0) return;
        meshCount++;
        for (let i = 0; i < pos.count; i++) {
          pt.fromBufferAttribute(pos, i).applyMatrix4(o.matrixWorld);
          if (pt.x < minX) minX = pt.x;
          if (pt.x > maxX) maxX = pt.x;
          if (pt.y < minY) minY = pt.y;
          if (pt.y > maxY) maxY = pt.y;
          if (pt.z < minZ) minZ = pt.z;
          if (pt.z > maxZ) maxZ = pt.z;
        }
      });
    }
  }
  if (meshCount === 0 || !Number.isFinite(minY)) {
    return { exists: false, foundNodes, meshCount: 0, minY: null, maxY: null, centerXZ: null, span: null };
  }
  return {
    exists: true,
    foundNodes,
    meshCount,
    minY: Number(minY.toFixed(5)),
    maxY: Number(maxY.toFixed(5)),
    min: [Number(minX.toFixed(4)), Number(minY.toFixed(4)), Number(minZ.toFixed(4))],
    max: [Number(maxX.toFixed(4)), Number(maxY.toFixed(4)), Number(maxZ.toFixed(4))],
    center: [
      Number(((minX + maxX) * 0.5).toFixed(4)),
      Number(((minY + maxY) * 0.5).toFixed(4)),
      Number(((minZ + maxZ) * 0.5).toFixed(4)),
    ],
    centerXZ: [Number(((minX + maxX) * 0.5).toFixed(4)), Number(((minZ + maxZ) * 0.5).toFixed(4))],
    span: [
      Number((maxX - minX).toFixed(4)),
      Number((maxY - minY).toFixed(4)),
      Number((maxZ - minZ).toFixed(4)),
    ],
  };
}

function auditFloorArrowsAndZones(roots) {
  const tableNames = [
    'STAGE1_PREP_TABLE', 'VIS_STAGE_1_TABLE',
    'BENCH_PICK', 'BENCH_PACK', 'BENCH_REWORK', 'BENCH_SCRAP',
    'ROBOT_PACK_TABLE', 'VIS_ROBOT_PACK_TABLE',
    'STAGE4_QC_TABLE', 'VIS_STAGE_4_TABLE',
  ];
  const tableBoxes = [];
  for (const tn of tableNames) {
    const info = measureVerticesBoxOnRoots(roots, [tn]);
    if (info.exists && info.min && info.max) {
      tableBoxes.push({ name: tn, min: info.min, max: info.max });
    }
  }

  const greenWalkwayArrows = [];
  const offWalkwayArrows = [];
  const underTableArrows = [];
  const misorientedWalkwayArrows = [];
  const twistedArrowMeshes = [];
  const zoneNodesPresent = new Set();
  let walkwayVisible = false;
  let cadGridVisible = false;

  const vA = new THREE.Vector3();
  const vB = new THREE.Vector3();
  const vC = new THREE.Vector3();
  const e1 = new THREE.Vector3();
  const e2 = new THREE.Vector3();
  const cr = new THREE.Vector3();

  for (const root of roots) {
    if (!root) continue;
    root.updateMatrixWorld(true);
    root.traverse((o) => {
      if (!isEffectivelyVisibleNode(o)) return;
      const nm = o.name ?? '';
      if (/^(WALKWAY_GREEN_5S|MAP_WALKWAY_GREEN)/i.test(nm)) walkwayVisible = true;
      if (o.isMesh && /GRID/i.test(nm)) cadGridVisible = true;
      if (/^(FLOOR_ZONE_0[1234]|FLOOR_ZONE_R|OUTCOME_FLOOR_ESCAPED|MAP_ZONE_|MAP_REWORK|MAP_SCRAP|MAP_ESCAPED|MAP_GOOD|MAP_INBOUND|MAP_SHIPPING|MAP_BREAK)/i.test(nm)) {
        zoneNodesPresent.add(nm);
      }

      if (!o.isMesh || !o.geometry?.attributes?.position) return;
      const chainNames = [];
      for (let cur = o; cur; cur = cur.parent) {
        if (cur.name) chainNames.push(cur.name);
      }
      const joined = chainNames.join('/');
      const hasArrowOrChevron = /(ARROW|CHEVRON)/i.test(joined);
      const hasFlowDash =
        /(DASH|SPUR_GUIDE|SPUR_TRANSFER_GUIDE|TRANSFER_LANE|RETURN_LANE|SCRAP_TRANSFER|FLOW_SHAFT|FLOW_LINE)/i.test(
          joined,
        ) && !/(FLOOR_ZONE_|OUTCOME_FLOOR_|MAP_FLOOR_ZONE_|MAP_ZONE_|COLUMN_TAG_|GRID)/i.test(joined);
      if (!hasArrowOrChevron && !hasFlowDash) return;

      const bb = new THREE.Box3().setFromObject(o, true);
      if (bb.isEmpty() || bb.max.y >= 0.08) return;

      const pos = o.geometry.attributes.position;
      const idx = o.geometry.index;
      const triCount = idx ? Math.floor(idx.count / 3) : Math.floor(pos.count / 3);
      let zeroOrFlippedTris = 0;
      let upSign = 0;
      for (let t = 0; t < triCount; t++) {
        vA.fromBufferAttribute(pos, idx ? idx.getX(3 * t) : 3 * t).applyMatrix4(o.matrixWorld);
        vB.fromBufferAttribute(pos, idx ? idx.getX(3 * t + 1) : 3 * t + 1).applyMatrix4(o.matrixWorld);
        vC.fromBufferAttribute(pos, idx ? idx.getX(3 * t + 2) : 3 * t + 2).applyMatrix4(o.matrixWorld);
        e1.subVectors(vB, vA);
        e2.subVectors(vC, vA);
        cr.crossVectors(e1, e2);
        const area2 = cr.length();
        if (area2 < 2e-8) {
          zeroOrFlippedTris++;
        } else if (Math.abs(cr.y) > 1e-7) {
          const sgn = cr.y > 0 ? 1 : -1;
          if (upSign === 0) upSign = sgn;
          else if (upSign !== sgn) zeroOrFlippedTris++;
        }
      }
      if (zeroOrFlippedTris > 0) twistedArrowMeshes.push(nm || joined);

      const wZsEast = [];
      const wZsWest = [];
      const spanX = Math.max(1e-6, bb.max.x - bb.min.x);
      for (let vi = 0; vi < pos.count; vi++) {
        vA.fromBufferAttribute(pos, vi).applyMatrix4(o.matrixWorld);
        if (vA.x >= bb.max.x - 0.12 * spanX) wZsEast.push(vA.z);
        if (vA.x <= bb.min.x + 0.35 * spanX) wZsWest.push(vA.z);
      }
      const eastSpanZ = wZsEast.length > 0 ? Math.max(...wZsEast) - Math.min(...wZsEast) : 99;
      const westSpanZ = wZsWest.length > 0 ? Math.max(...wZsWest) - Math.min(...wZsWest) : 0;
      const pointsPlusX = spanX >= 0.15 && eastSpanZ < westSpanZ * 0.75;

      const inGreenWalkway =
        bb.min.x >= -17.85 &&
        bb.max.x <= 17.85 &&
        bb.min.z >= 4.34 &&
        bb.max.z <= 5.96;

      const cx = 0.5 * (bb.min.x + bb.max.x);
      const cz = 0.5 * (bb.min.z + bb.max.z);
      const rec = {
        name: nm || joined,
        path: joined,
        centerXZ: [Number(cx.toFixed(4)), Number(cz.toFixed(4))],
        aabb: boxToDict(bb),
        pointsPlusX,
      };

      for (const tb of tableBoxes) {
        if (
          bb.max.x > tb.min[0] + 0.01 &&
          tb.max[0] > bb.min.x + 0.01 &&
          bb.max.z > tb.min[2] + 0.01 &&
          tb.max[2] > bb.min.z + 0.01
        ) {
          underTableArrows.push({ arrow: rec.name, table: tb.name });
        }
      }

      if (inGreenWalkway) {
        greenWalkwayArrows.push(rec);
        if (!pointsPlusX) misorientedWalkwayArrows.push(rec.name);
      } else {
        offWalkwayArrows.push(rec);
      }
    });
  }

  // Check duplicate co-located walkway arrows (e.g. raw .glb + MAP_WALKWAY_ARROW_* both visible)
  const duplicateWalkwayPairs = [];
  for (let i = 0; i < greenWalkwayArrows.length; i++) {
    for (let j = i + 1; j < greenWalkwayArrows.length; j++) {
      const a = greenWalkwayArrows[i];
      const b = greenWalkwayArrows[j];
      const d = Math.hypot(a.centerXZ[0] - b.centerXZ[0], a.centerXZ[1] - b.centerXZ[1]);
      if (d < 0.40) {
        duplicateWalkwayPairs.push([a.name, b.name, Number(d.toFixed(4))]);
      }
    }
  }

  return {
    walkwayArrows: greenWalkwayArrows,
    greenWalkwayArrows,
    offWalkwayArrows,
    underTableArrows,
    misorientedWalkwayArrows,
    twistedArrowMeshes,
    duplicateWalkwayPairs,
    hasWalkwayGreen5S: walkwayVisible,
    walkwayVisible,
    cadGridVisible,
    zoneNodesPresent: [...zoneNodesPresent].sort(),
  };
}

function auditEnvironment(envGltf, layoutGltf, supportGltf, bindings) {
  const env = envGltf.scene;
  env.updateMatrixWorld(true);

  const slab = env.getObjectByName('Raised_concrete_slab') || env.getObjectByName('Raised concrete slab');
  const slabBox = slab ? boxToDict(new THREE.Box3().setFromObject(slab, true)) : null;

  const wallsRoot = env.getObjectByName('ENV_WALLS_AND_DOCKS');
  const wallsBox = wallsRoot ? boxToDict(new THREE.Box3().setFromObject(wallsRoot, true)) : null;

  const dock01 = env.getObjectByName('DOCK_01');
  const dock02 = env.getObjectByName('DOCK_02');
  const leaf01 = env.getObjectByName('DOCK_01_SECTIONAL_LEAF');
  const leaf02 = env.getObjectByName('DOCK_02_SECTIONAL_LEAF');
  const jack = env.getObjectByName('PALLET_JACK');

  const excludeRaySet = new Set();
  for (const root of [leaf01, leaf02, jack]) {
    if (root) root.traverse((o) => excludeRaySet.add(o));
  }
  const structuralWallMeshes = [];
  if (wallsRoot) {
    wallsRoot.traverse((o) => {
      if (o.isMesh && o.visible && !excludeRaySet.has(o)) structuralWallMeshes.push(o);
    });
  }

  const raycaster = new THREE.Raycaster();
  raycaster.near = 0.0;
  raycaster.far = 1.4;
  let uncoveredWallRays = 0;
  let uncoveredLintelRays = 0;
  let blockedPortalRays = 0;
  let knifeEdgeFailures = 0;

  for (const side of [-1, 1]) {
    const ox = side * 18.5;
    const dir = new THREE.Vector3(-side, 0, 0);
    for (let z = -8.8; z <= 8.8001; z += 0.5) {
      if (!(z >= 3.28 && z <= 7.02)) {
        for (const y of [0.2, 1.2, 2.4, 3.4]) {
          raycaster.set(new THREE.Vector3(ox, y, z), dir);
          if (raycaster.intersectObjects(structuralWallMeshes, false).length === 0) uncoveredWallRays++;
        }
      }
    }
    for (const z of [3.5, 4.4, 5.15, 5.9, 6.8]) {
      raycaster.set(new THREE.Vector3(ox, 3.30, z), dir);
      if (raycaster.intersectObjects(structuralWallMeshes, false).length === 0) uncoveredLintelRays++;
    }
    for (const z of [4.5, 5.15, 5.8]) {
      raycaster.set(new THREE.Vector3(ox, 1.50, z), dir);
      if (raycaster.intersectObjects(structuralWallMeshes, false).length > 0) blockedPortalRays++;
    }
    // Knife-edge jambs (z=3.25 & z=7.05 must hit; z=5.15 y=2.75 must pass; y=3.35 must hit)
    for (const zJ of [3.25, 7.05]) {
      raycaster.set(new THREE.Vector3(ox, 1.80, zJ), dir);
      if (raycaster.intersectObjects(structuralWallMeshes, false).length === 0) knifeEdgeFailures++;
    }
    raycaster.set(new THREE.Vector3(ox, 2.75, 5.15), dir);
    if (raycaster.intersectObjects(structuralWallMeshes, false).length > 0) knifeEdgeFailures++;
  }

  const ovRoot = env.getObjectByName('ENV_OVERHEAD');
  const ovBox = ovRoot ? boxToDict(new THREE.Box3().setFromObject(ovRoot, true)) : null;
  const forbiddenOverheadMeshes = [];
  for (const [label, root] of [
    ['warehouse_environment.glb', env],
    ['modules/visual_layout.glb', layoutGltf.scene],
    ...(supportGltf?.scene ? [['modules/visual_support.glb', supportGltf.scene]] : []),
  ]) {
    root.traverse((o) => {
      if (isForbiddenOverheadMeshNode(o, root)) {
        forbiddenOverheadMeshes.push(`${label}:${o.name || o.parent?.name || '<unnamed>'}`);
      }
    });
  }

  // Check roller 06_01 unobstructed downward raycast at (0.045, 1.2, 0.1)
  const downRay = new THREE.Raycaster(new THREE.Vector3(0.045, 1.2, 0.1), new THREE.Vector3(0, -1, 0), 0, 0.5);
  const r06Hits = downRay.intersectObjects(env.children, true);
  const topHit = r06Hits[0] ?? null;

  // Check clutter / legacy artifacts
  const cabBox = new THREE.Box3(
    new THREE.Vector3(...MAP_GEOMETRY_FIXES.cabinetBounds.min),
    new THREE.Vector3(...MAP_GEOMETRY_FIXES.cabinetBounds.max),
  );
  let cabinetRegionTris = 0;
  const legacyClutterNodes = [];
  const demoCartonNodes = [];
  const transferLaneNodes = [];
  const p0 = new THREE.Vector3();
  const p1 = new THREE.Vector3();
  const p2 = new THREE.Vector3();

  env.traverse((o) => {
    if (/(TRANSFER|LANE|ROUTE)/i.test(o.name) && !/^WALKWAY_/i.test(o.name)) {
      transferLaneNodes.push(o.name);
    }
    if (!o.visible) return;
    if (/^(ZEBRA_|WAYFINDING_)/.test(o.name) || /Axis_[XY]/.test(o.name)) {
      legacyClutterNodes.push(o.name);
    }
    if (/^(Dispatch carton|Inbound tote|CARTON_OPEN)/.test(o.name)) {
      demoCartonNodes.push(o.name);
    }
    if (o.isMesh && o.geometry?.attributes?.position) {
      let inProps = false;
      for (let c = o; c; c = c.parent) {
        if (c.name === 'ENV_WORKSTATIONS_DETAIL' || c.name === 'PROPS') inProps = true;
      }
      if (inProps) {
        const pos = o.geometry.attributes.position;
        const idx = o.geometry.index;
        const tc = idx ? Math.floor(idx.count / 3) : Math.floor(pos.count / 3);
        for (let t = 0; t < tc; t++) {
          p0.fromBufferAttribute(pos, idx ? idx.getX(3 * t) : 3 * t).applyMatrix4(o.matrixWorld);
          p1.fromBufferAttribute(pos, idx ? idx.getX(3 * t + 1) : 3 * t + 1).applyMatrix4(o.matrixWorld);
          p2.fromBufferAttribute(pos, idx ? idx.getX(3 * t + 2) : 3 * t + 2).applyMatrix4(o.matrixWorld);
          if (triangleIntersectsBoxXZ_Y(p0, p1, p2, cabBox)) cabinetRegionTris++;
        }
      }
    }
  });

  // PALLET_JACK stats
  const jackStats = jack ? countSceneMeshesAndTris(jack) : { meshCount: 0, triangleCount: 0 };
  const jackBox = jack ? boxToDict(new THREE.Box3().setFromObject(jack, true)) : null;

  // 200 rollers check
  let rollerCount = 0;
  let rollerHeightOffenders = 0;
  for (let c = 1; c <= 10; c++) {
    for (let r = 1; r <= 20; r++) {
      const rn = `ROLLER_${String(c).padStart(2, '0')}_${String(r).padStart(2, '0')}`;
      const ro = env.getObjectByName(rn);
      if (ro) {
        rollerCount++;
        const rb = new THREE.Box3().setFromObject(ro, true);
        if (Math.abs(rb.max.y - 0.860) > 0.0025) rollerHeightOffenders++;
      }
    }
  }

  // Conveyor transfer port raycasts
  let transferPortHits = 0;
  const portRay = new THREE.Raycaster();
  portRay.near = 0;
  portRay.far = 0.24;
  for (const cx of [-6.46, 0.42, 6.44]) {
    for (const dx of [-0.25, 0, 0.25]) {
      for (const h of [0.90, 0.95]) {
        portRay.set(new THREE.Vector3(cx + dx, h, 0.24), new THREE.Vector3(0, 0, 1));
        transferPortHits += portRay.intersectObjects(env.children, true).length;
      }
    }
  }

  // Walkway green 5S prism [-17.7, 0.025, 4.4] .. [17.7, 2.20, 5.9]
  const walkwayPrism = new THREE.Box3(
    new THREE.Vector3(-17.7, 0.025, 4.4),
    new THREE.Vector3(17.7, 2.20, 5.9),
  );
  let walkwayPrismHits = 0;
  for (const root of [env, layoutGltf.scene]) {
    root.traverse((o) => {
      if (!o.isMesh || !o.visible || !o.geometry?.attributes?.position) return;
      let skip = false;
      for (let c = o; c; c = c.parent) {
        if (/^DOCK_0[12]/.test(c.name) || /^VIS_QUEUE_Q[234]_OUTLINE/.test(c.name)) skip = true;
      }
      if (skip) return;
      const pos = o.geometry.attributes.position;
      const idx = o.geometry.index;
      const tc = idx ? Math.floor(idx.count / 3) : Math.floor(pos.count / 3);
      for (let t = 0; t < tc; t++) {
        p0.fromBufferAttribute(pos, idx ? idx.getX(3 * t) : 3 * t).applyMatrix4(o.matrixWorld);
        p1.fromBufferAttribute(pos, idx ? idx.getX(3 * t + 1) : 3 * t + 1).applyMatrix4(o.matrixWorld);
        p2.fromBufferAttribute(pos, idx ? idx.getX(3 * t + 2) : 3 * t + 2).applyMatrix4(o.matrixWorld);
        if (triangleIntersectsBoxXZ_Y(p0, p1, p2, walkwayPrism)) {
          walkwayPrismHits++;
          break;
        }
      }
    });
  }

  // Environment layers & Andon clone isolation check
  const envClone1 = env.clone(true);
  const envClone2 = env.clone(true);
  applyEnvironmentDefaults(envClone1);
  applyEnvironmentDefaults(envClone2);
  const ovNode1 = envClone1.getObjectByName('ENV_OVERHEAD');
  let ovHiddenByDefault = true;
  let ovVisibleAfterToggle = true;
  let ovHiddenAfterRevert = true;
  if (ovNode1) {
    ovHiddenByDefault = ovNode1.visible === false;
    setEnvironmentLayer(envClone1, 'ENV_OVERHEAD', true);
    ovVisibleAfterToggle = ovNode1.visible === true;
    setEnvironmentLayer(envClone1, 'ENV_OVERHEAD', false);
    ovHiddenAfterRevert = ovNode1.visible === false;
  } else {
    setEnvironmentLayer(envClone1, 'ENV_OVERHEAD', true);
    setEnvironmentLayer(envClone1, 'ENV_OVERHEAD', false);
  }

  const dockSigBefore = envClone1.getObjectByName('DOCK_01_SIGNAL_RED')?.material?.emissiveIntensity ?? null;
  setRobotAndonState(envClone1, 'jammed');
  setRobotAndonState(envClone2, 'pack');
  const clone1RedActive = envClone1.getObjectByName('ANDON_RED')?.userData?.active === true;
  const clone2RedActive = envClone2.getObjectByName('ANDON_RED')?.userData?.active === true;
  const clone2GreenActive = envClone2.getObjectByName('ANDON_GREEN')?.userData?.active === true;
  const dockSigAfter = envClone1.getObjectByName('DOCK_01_SIGNAL_RED')?.material?.emissiveIntensity ?? null;

  const presentLayers = environmentLayers
    .map((entry) => (Array.isArray(entry) ? entry[0] : entry.name))
    .filter((n) => Boolean(env.getObjectByName(n)));

  const additiveSpursPresent = [
    'INFEED_PREP_C01',
    'OUTFEED_C10_GOOD',
    'STOPPER_GATE',
    'SPUR_ROBOT',
    'SPUR_PICK',
    'DIVERT_PICK',
    'SPUR_PACK',
    'DIVERT_PACK',
    'SPUR_QC',
    'DIVERT_QC',
  ].filter((n) => Boolean(env.getObjectByName(n)));

  const floorRoot = env.getObjectByName('ENV_FLOOR_AND_GRID');
  const gridBoxRaw = new THREE.Box3();
  if (floorRoot) {
    floorRoot.traverse((o) => {
      if (o.isMesh && o.visible && /GRID/i.test(o.name)) {
        gridBoxRaw.expandByObject(o);
      }
    });
  }
  const cadGridAabb = boxToDict(gridBoxRaw);

  // Workstation floor-grounding (standalone warehouse_environment.glb + combined Studio scene + cloned parallel benches)
  const standaloneEnvGrounding = {
    stage1_prep: measureVerticesBoxOnRoots([envClone1], ['STAGE1_PREP_TABLE']),
    stage2_pick: measureVerticesBoxOnRoots([envClone1], ['BENCH_PICK']),
    stage3_pack: measureVerticesBoxOnRoots([envClone1], ['BENCH_PACK']),
    stage3_robot: measureVerticesBoxOnRoots([envClone1], ['ROBOT_PACK_TABLE', 'ROBOT_TABLE_REINFORCEMENT']),
    stage4_qc: measureVerticesBoxOnRoots([envClone1], ['STAGE4_QC_TABLE']),
    break_bench: measureVerticesBoxOnRoots([envClone1], ['BREAK_BENCH']),
    water_cooler: measureVerticesBoxOnRoots([envClone1], ['WATER_COOLER']),
    shipping_podium: measureVerticesBoxOnRoots([envClone1], ['SHIPPING_MANIFEST_PODIUM']),
    bench_rework: measureVerticesBoxOnRoots([envClone1], ['BENCH_REWORK']),
    bench_scrap: measureVerticesBoxOnRoots([envClone1], ['BENCH_SCRAP']),
  };
  const studioGroundingScene = new THREE.Scene();
  const studioEnvClone = env.clone(true);
  const studioLayClone = layoutGltf.scene.clone(true);
  for (const r of [studioEnvClone, studioLayClone]) {
    r.traverse((o) => {
      if (o.isMesh && o.geometry) o.geometry = o.geometry.clone();
    });
  }
  studioGroundingScene.add(studioEnvClone, studioLayClone);
  applyEnvironmentDefaults(studioEnvClone);
  applyMapGeometryFixes(studioEnvClone, studioLayClone);
  applyMapLayoutExpansion(studioEnvClone, studioLayClone);
  applyMapFloorFixes(studioEnvClone, studioLayClone);

  const clonedBenches = [];
  const studioClonedBenches = {};
  const manualBenchTemplate = supportGltf?.scene?.getObjectByName('VIS_manual_bench') ?? null;
  if (manualBenchTemplate && bindings) {
    const maxSlotsByStage = { 1: 3, 2: 3, 3: 6, 4: 3 };
    for (const [stStr, count] of Object.entries(maxSlotsByStage)) {
      const stage = Number(stStr);
      for (let slotIdx = 1; slotIdx < count; slotIdx++) {
        const slot = SpatialMod.stageSlotTransform(bindings, stage, slotIdx);
        const bench = manualBenchTemplate.clone(true);
        const bName = `PARALLEL_STAGE_${stage}_${slotIdx}`;
        bench.name = bName;
        bench.position.fromArray(slot.bench);
        bench.rotation.y = slot.benchRotY;
        studioGroundingScene.add(bench);
        const boxInfo = measureVerticesBoxOnRoots([studioGroundingScene], [bName]);
        studioClonedBenches[bName] = boxInfo;
        clonedBenches.push({
          stage,
          slot: slotIdx,
          name: bName,
          ...boxInfo,
        });
      }
    }
  }
  const combinedStudioGrounding = {
    stage1_prep: measureVerticesBoxOnRoots([studioGroundingScene], ['STAGE1_PREP_TABLE', 'VIS_STAGE_1_TABLE']),
    stage2_pick: measureVerticesBoxOnRoots([studioGroundingScene], ['BENCH_PICK']),
    stage3_pack: measureVerticesBoxOnRoots([studioGroundingScene], ['BENCH_PACK']),
    stage3_robot: measureVerticesBoxOnRoots([studioGroundingScene], [
      'ROBOT_PACK_TABLE',
      'ROBOT_TABLE_REINFORCEMENT',
      'VIS_ROBOT_PACK_TABLE',
    ]),
    stage4_qc: measureVerticesBoxOnRoots([studioGroundingScene], [
      'STAGE4_QC_TABLE',
      'VIS_STAGE_4_TABLE',
      'QC_TABLE_TOOLING',
    ]),
    break_bench: measureVerticesBoxOnRoots([studioGroundingScene], ['BREAK_BENCH']),
    water_cooler: measureVerticesBoxOnRoots([studioGroundingScene], ['WATER_COOLER']),
    shipping_podium: measureVerticesBoxOnRoots([studioGroundingScene], ['SHIPPING_MANIFEST_PODIUM']),
    bench_rework: measureVerticesBoxOnRoots([studioGroundingScene], ['BENCH_REWORK']),
    bench_scrap: measureVerticesBoxOnRoots([studioGroundingScene], ['BENCH_SCRAP']),
  };

  const floorArrowsAudit = auditFloorArrowsAndZones([envClone1]);
  const studioPatchedFloorArrowsAudit = auditFloorArrowsAndZones([studioGroundingScene]);

  return {
    slabBox,
    wallsBox,
    dock01Pos: dock01 ? dock01.getWorldPosition(new THREE.Vector3()).toArray() : null,
    dock02Pos: dock02 ? dock02.getWorldPosition(new THREE.Vector3()).toArray() : null,
    raycasts: {
      uncoveredWallRays,
      uncoveredLintelRays,
      blockedPortalRays,
      knifeEdgeFailures,
    },
    overheadBox: ovBox,
    forbiddenOverheadMeshes,
    chamferInEnv: Boolean(env.getObjectByName('VIS_Bench_top_robot_chamfer')),
    roller0601TopHit: topHit ? { name: topHit.object.name, y: topHit.point.y } : null,
    benchReworkInEnv: Boolean(env.getObjectByName('BENCH_REWORK')),
    benchScrapInEnv: Boolean(env.getObjectByName('BENCH_SCRAP')),
    benchReworkBox: standaloneEnvGrounding.bench_rework,
    benchScrapBox: standaloneEnvGrounding.bench_scrap,
    workstationGrounding: {
      ok: true,
      standaloneEnv: standaloneEnvGrounding,
      combinedStudio: combinedStudioGrounding,
      clonedBenches,
      studioClonedBenches,
    },
    floorArrowsAudit,
    studioPatchedFloorArrowsAudit,
    utilityCabinetInEnv: Boolean(env.getObjectByName('UTILITY_CABINET')),
    cabinetRegionTris,
    legacyClutterNodes,
    demoCartonNodes,
    transferLaneNodes,
    additiveSpursPresent,
    cadGridAabb,
    palletJack: { ...jackStats, aabb: jackBox },
    rollerCount,
    rollerHeightOffenders,
    transferPortHits,
    walkwayPrismHits,
    presentLayers,
    layerAndAndon: {
      ovHiddenByDefault,
      ovVisibleAfterToggle,
      ovHiddenAfterRevert,
      cloneIsolationOk: clone1RedActive && !clone2RedActive && clone2GreenActive,
      dockSignalUnmutated: dockSigBefore === dockSigAfter,
    },
  };
}

function measureMapSceneMetrics(envRoot, layoutRoot) {
  envRoot.updateMatrixWorld(true);
  layoutRoot.updateMatrixWorld(true);
  const slab = envRoot.getObjectByName('Raised_concrete_slab') || envRoot.getObjectByName('Raised concrete slab');
  const walls = envRoot.getObjectByName('ENV_WALLS_AND_DOCKS');
  const dock01 = envRoot.getObjectByName('DOCK_01');
  const dock02 = envRoot.getObjectByName('DOCK_02');
  const chamfer =
    layoutRoot.getObjectByName('VIS_Bench_top_robot_chamfer') ||
    envRoot.getObjectByName('VIS_Bench_top_robot_chamfer');

  const PATCH_GROUP_NAMES = new Set([
    MAP_GEOMETRY_FIXES.patchGroupName,
    MAP_FLOOR_FIXES.patchGroupName,
    'MAP_LAYOUT_EXPANSION',
    'MAP_EXPANDED_GRID',
    'MAP_FLOOR_FIXES',
    'MAP_FLOOR_PATCHES',
    'MAP_GEOMETRY_FIXES',
    'MAP_ROBOT_REINFORCEMENT_FEET',
    'MAP_ROBOT_TABLE_UNDERFRAME',
    'MAP_WATER_COOLER_PLINTH',
  ].filter(Boolean));

  let meshCount = 0;
  let patchGroups = 0;
  for (const r of [envRoot, layoutRoot]) {
    r.traverse((o) => {
      if (o.isMesh) meshCount++;
      if (PATCH_GROUP_NAMES.has(o.name)) {
        patchGroups++;
      }
    });
  }
  return {
    slabBox: slab ? boxToDict(new THREE.Box3().setFromObject(slab, true)) : null,
    wallsBox: walls ? boxToDict(new THREE.Box3().setFromObject(walls, true)) : null,
    dock01Pos: dock01 ? dock01.getWorldPosition(new THREE.Vector3()).toArray() : null,
    dock02Pos: dock02 ? dock02.getWorldPosition(new THREE.Vector3()).toArray() : null,
    chamferBox: chamfer ? boxToDict(new THREE.Box3().setFromObject(chamfer, true)) : null,
    meshCount,
    patchGroups,
  };
}

function runMapPipelineTrial(envSceneTemplate, layoutSceneTemplate) {
  try {
    const env1 = envSceneTemplate.clone(true);
    const lay1 = layoutSceneTemplate.clone(true);
    // Deep-clone geometries & materials so map-*.js vertex mutations do not leak onto templates
    for (const root of [env1, lay1]) {
      root.traverse((o) => {
        if (o.isMesh && o.geometry) o.geometry = o.geometry.clone();
      });
    }

    const h1a = applyMapGeometryFixes(env1, lay1);
    const h1b = applyMapLayoutExpansion(env1, lay1);
    const h1c = applyMapFloorFixes(env1, lay1);
    const pass1 = measureMapSceneMetrics(env1, lay1);

    applyMapGeometryFixes(env1, lay1);
    applyMapLayoutExpansion(env1, lay1);
    applyMapFloorFixes(env1, lay1);
    const pass2 = measureMapSceneMetrics(env1, lay1);

    applyMapGeometryFixes(env1, lay1);
    applyMapLayoutExpansion(env1, lay1);
    applyMapFloorFixes(env1, lay1);
    const pass3 = measureMapSceneMetrics(env1, lay1);

    h1c?.dispose?.();
    h1b?.dispose?.();
    h1a?.dispose?.();
    const afterDispose = measureMapSceneMetrics(env1, lay1);

    applyMapGeometryFixes(env1, lay1);
    applyMapLayoutExpansion(env1, lay1);
    applyMapFloorFixes(env1, lay1);
    const afterReapply = measureMapSceneMetrics(env1, lay1);

    return { ok: true, pass1, pass2, pass3, afterDispose, afterReapply };
  } catch (err) {
    return { ok: false, error: String(err?.stack ?? err?.message ?? err) };
  }
}

async function auditMapIdempotency(envGltf, layoutGltf, repoRoot) {
  const shipped = runMapPipelineTrial(envGltf.scene, layoutGltf.scene);

  // Build synthetic native 36x18x3.6m clone (no legacy Paper labels / Axis_X, native 36m slab & ±17.85 docks)
  let syntheticNative36m = { ok: false, error: null };
  try {
    const synEnv = new THREE.Group();
    synEnv.name = 'Scene';
    const floorGrp = new THREE.Group();
    floorGrp.name = 'ENV_FLOOR_AND_GRID';
    const slabMesh = new THREE.Mesh(new THREE.BoxGeometry(36, 0.2, 18), new THREE.MeshStandardMaterial());
    slabMesh.position.set(0, -0.1, 0);
    slabMesh.name = 'Raised_concrete_slab';
    floorGrp.add(slabMesh);
    const walkMesh = new THREE.Mesh(new THREE.PlaneGeometry(35.4, 1.5), new THREE.MeshStandardMaterial());
    walkMesh.rotation.x = -Math.PI / 2;
    walkMesh.position.set(0, 0.002, 5.15);
    walkMesh.name = 'WALKWAY_GREEN_5S';
    floorGrp.add(walkMesh);
    synEnv.add(floorGrp);

    const wallsGrp = new THREE.Group();
    wallsGrp.name = 'ENV_WALLS_AND_DOCKS';
    const backWall = new THREE.Mesh(new THREE.BoxGeometry(36, 3.6, 0.16), new THREE.MeshStandardMaterial());
    backWall.position.set(0, 1.8, -9.0);
    backWall.name = 'Back_wall_panel';
    wallsGrp.add(backWall);
    const d1 = new THREE.Group();
    d1.name = 'DOCK_01';
    d1.position.set(-17.85, 0, 5.15);
    d1.add(new THREE.Mesh(new THREE.BoxGeometry(0.3, 3.0, 3.0), new THREE.MeshStandardMaterial()));
    const d2 = new THREE.Group();
    d2.name = 'DOCK_02';
    d2.position.set(17.85, 0, 5.15);
    d2.add(new THREE.Mesh(new THREE.BoxGeometry(0.3, 3.0, 3.0), new THREE.MeshStandardMaterial()));
    wallsGrp.add(d1, d2);
    synEnv.add(wallsGrp);

    const synLay = layoutGltf.scene.clone(true);
    syntheticNative36m = runMapPipelineTrial(synEnv, synLay);
  } catch (err) {
    syntheticNative36m = { ok: false, error: String(err?.message ?? err) };
  }

  // Also test staged studio/public/scene or studio/dist/scene if present
  let stagedScene = null;
  for (const relDir of ['studio/dist/scene', 'studio/public/scene']) {
    const absDir = path.join(repoRoot, relDir);
    const envPath = path.join(absDir, 'warehouse_environment.glb');
    const layPath = path.join(absDir, 'modules', 'visual_layout.glb');
    if (fsSync.existsSync(envPath) && fsSync.existsSync(layPath)) {
      const [eb, lb] = await Promise.all([fs.readFile(envPath), fs.readFile(layPath)]);
      const [eg, lg] = await Promise.all([parseGltfScene(eb), parseGltfScene(lb)]);
      stagedScene = { dir: relDir, ...runMapPipelineTrial(eg.scene, lg.scene) };
      break;
    }
  }

  return { shipped, syntheticNative36m, stagedScene };
}

function getActorAndOrderNodes(liveScene) {
  const dyn = liveScene?.getObjectByName('REPLAY_DYNAMIC');
  const workers = [];
  let robot = null;
  const orders = [];
  if (!dyn) return { dyn: null, workers, robot, orders };
  for (const child of dyn.children) {
    if (child.name?.startsWith('ORDER_')) {
      orders.push(child);
    } else if (child.getObjectByName?.('ATTACH_WORKER_HAND_L') || child.name?.startsWith('WORKER_w') || /^w\d+$/.test(child.name ?? '')) {
      child.userData ??= {};
      child.userData.__workerId ??= `w${workers.length}`;
      workers.push(child);
    } else if (child.getObjectByName?.('ATTACH_ROBOT_HAND_L') || child.name === 'ROBOT_CELL_ACTOR' || child.name === 'ROBOT') {
      child.userData ??= {};
      child.userData.__actorId = 'robot';
      robot = child;
    }
  }
  // Fallback deep search if ScenePlayer nests groups inside REPLAY_DYNAMIC
  if (workers.length === 0 || (!robot && orders.length === 0)) {
    dyn.traverse((o) => {
      if (o === dyn) return;
      if (o.getObjectByName?.('ATTACH_WORKER_HAND_L') && !workers.includes(o) && !workers.some((w) => w.getObjectById?.(o.id))) {
        o.userData ??= {};
        o.userData.__workerId ??= `w${workers.length}`;
        workers.push(o);
      } else if (o.getObjectByName?.('ATTACH_ROBOT_HAND_L') && !robot) {
        o.userData ??= {};
        o.userData.__actorId = 'robot';
        robot = o;
      } else if (o.name?.startsWith('ORDER_') && !orders.includes(o)) {
        orders.push(o);
      }
    });
  }
  return { dyn, workers, robot, orders };
}

function hasActivePropBoneScale(actorRoot) {
  const scaleVec = new THREE.Vector3();
  let active = false;
  actorRoot.traverse((o) => {
    if (active) return;
    if (o.isBone && o.name.startsWith('prop_')) {
      if (scaleVec.setFromMatrixScale(o.matrixWorld).length() > 0.05) active = true;
    }
  });
  return active;
}

function findWorkerNodeById(workers, actorId) {
  if (!actorId) return null;
  const direct = workers.find((w) => w.userData?.__workerId === actorId || w.name?.endsWith(actorId));
  if (direct) return direct;
  const idx = Number(String(actorId).replace(/^w/i, ''));
  return Number.isInteger(idx) && idx >= 0 && idx < workers.length ? workers[idx] : null;
}

function measureActorOpPropDiagAndSignature(actorRoot) {
  let maxDiag = 0;
  const pts = [];
  const scaleVec = new THREE.Vector3();
  actorRoot.updateMatrixWorld(true);
  actorRoot.traverse((o) => {
    if (o.isBone && o.name.startsWith('prop_')) {
      const ws = scaleVec.setFromMatrixScale(o.matrixWorld).length();
      if (ws > 0.05) {
        const wp = o.getWorldPosition(new THREE.Vector3());
        pts.push(wp.x, wp.y, wp.z, ws);
      }
    }
    const ud = effectiveUserData(o, actorRoot);
    if ((o.isMesh || o.isSkinnedMesh) && ud.operation_prop === true && o.visible) {
      const ws = scaleVec.setFromMatrixScale(o.matrixWorld).length();
      if (ws > 0.05) {
        const b = new THREE.Box3().setFromObject(o, true);
        if (!b.isEmpty()) {
          const d = b.min.distanceTo(b.max);
          if (d > maxDiag) maxDiag = d;
        }
      }
    }
  });
  return { maxDiag, sig: pts };
}

async function inspectSingleShiftReplay(player, liveScene, replay, runId, detailed = false) {
  await player.setReplay(replay);
  const ts = replay.tickSeconds;
  const horizon = replay.horizonTicks;

  // 1. Discrete final counter parity
  const endState = replay.seekTo(horizon * ts);
  let counterMismatches = 0;
  for (const k of COUNTER_KEYS) {
    if (JSON.stringify(endState.counters[k]) !== JSON.stringify(replay.manifest.raw[k])) {
      counterMismatches++;
    }
  }

  // Boundary clamping checks
  const st0 = replay.seekTo(0);
  const stClampHigh = replay.seekTo((horizon + 999) * ts);
  const boundaryClampingOk =
    st0.tick === 0 &&
    !st0.ended &&
    Math.abs(stClampHigh.tickFloat - horizon) < 1e-6 &&
    stClampHigh.ended === true;

  // Stationary roller check at t=0, deltaSeconds=0
  player.render(st0, { playing: false, speed: 1, deltaSeconds: 0 });
  liveScene?.updateMatrixWorld(true);
  const rollerSample = liveScene?.getObjectByName('ROLLER_01_05');
  const qStationary0 = rollerSample ? rollerSample.quaternion.clone() : null;
  const cStationary0 = rollerSample
    ? new THREE.Box3().setFromObject(rollerSample, true).getCenter(new THREE.Vector3())
    : null;
  player.render(st0, { playing: false, speed: 1, deltaSeconds: 0 });
  liveScene?.updateMatrixWorld(true);
  const stationaryRollerDelta =
    rollerSample && qStationary0 ? 1 - Math.min(1, Math.abs(qStationary0.dot(rollerSample.quaternion))) : 0;

  if (!detailed) {
    player.render(endState, { playing: false, speed: 1, deltaSeconds: 0 });
    const endMetrics = player.metrics ? structuredClone(player.metrics) : null;
    const { robot } = getActorAndOrderNodes(liveScene);
    return {
      runId,
      detailed: false,
      metrics: endMetrics,
      counterMismatches,
      boundaryClampingOk,
      robotVisibleAtEnd: robot ? robot.visible : false,
    };
  }

  // Detailed sub-tick inspection
  let mainConveyorHits = 0;
  let mainConveyorIncreasingXCount = 0;
  let spurHits = 0;
  let qcPortalHits = 0;
  let infeedBridgeHits = 0;
  let outfeedBridgeHits = 0;
  let activeRollerMaxAngleRad = 0;
  let maxRollerCenterDriftM = 0;

  const observedWorkerClips = new Set();
  const observedRobotClips = new Set();
  const observedAndonStates = new Set();

  let activeBenchDuplicateCollisions = 0;
  let activeWorkstationSamples = 0;
  let emptyHandPropLeakCount = 0;
  let trayHeightChecked = 0;
  let trayHeightErrors = 0;
  let untrayedHeightChecked = 0;
  let untrayedHeightErrors = 0;
  let reworkInQueueRObserved = 0;
  let reworkBadgeObserved = 0;
  let robotAssignedAttempt1 = 0;
  let reworkBenchWorkerSamples = 0;
  let reworkBenchCartonSamples = 0;
  let scrapCarryOrTransitObserved = 0;
  let scrapBenchOrBinVisibleAtEnd = 0;
  const scrapInRaw = Number(
    replay.manifest?.raw?.scrap ??
      replay.manifest?.raw?.outcomes?.scrap ??
      endState?.counters?.scrap ??
      endState?.counters?.outcomes?.scrap ??
      0,
  );

  const lastConveyorXByOrder = new Map();
  const scaleVec = new THREE.Vector3();

  // Sample [12, 72] at dt = 0.50 ticks for conveyor, spur, carry clips, and active prop vs static box
  const maxTransitTick = Math.min(horizon, 72);
  const dynRoot = liveScene?.getObjectByName('REPLAY_DYNAMIC');
  for (let t = 12; t <= maxTransitTick; t += 0.50) {
    const st = replay.seekTo(t * ts);
    player.render(st, { playing: true, speed: 1, deltaSeconds: 0.50 * ts });
    dynRoot?.updateMatrixWorld(true);

    if (rollerSample && qStationary0 && cStationary0 && Number.isInteger(t)) {
      rollerSample.updateMatrixWorld(true);
      const ang = 2 * Math.acos(Math.min(1, Math.abs(qStationary0.dot(rollerSample.quaternion))));
      if (ang > activeRollerMaxAngleRad) activeRollerMaxAngleRad = ang;
      const curCenter = new THREE.Box3().setFromObject(rollerSample, true).getCenter(new THREE.Vector3());
      const drift = curCenter.distanceTo(cStationary0);
      if (drift > maxRollerCenterDriftM) maxRollerCenterDriftM = drift;
    }

    for (const aName of ['ANDON_GREEN', 'ANDON_RED', 'ANDON_AMBER']) {
      const ao = liveScene?.getObjectByName(aName);
      if (ao?.userData?.active === true) observedAndonStates.add(aName);
    }

    const { workers, robot, orders } = getActorAndOrderNodes(liveScene);
    for (const w of workers) {
      const clip = w.userData?.__activeClipName;
      if (clip) observedWorkerClips.add(clip);
      if (['Idle', 'Walk', 'Reach', 'Assist', 'Break'].includes(clip)) {
        if (hasActivePropBoneScale(w)) emptyHandPropLeakCount++;
      }
    }
    if (robot && robot.visible) {
      const rClip = robot.userData?.__activeClipName;
      if (rClip) observedRobotClips.add(rClip);
      if (['Idle', 'Walk', 'Reach', 'Offline'].includes(rClip)) {
        if (hasActivePropBoneScale(robot)) emptyHandPropLeakCount++;
      }
    }
    if ((st.robot?.activity || st.robot?.busy) && st.robot.orderId !== null && st.robot.orderId !== undefined) {
      const rOrd = st.orders?.[st.robot.orderId] ?? st.orders?.get?.(st.robot.orderId);
      if (rOrd && rOrd.attempt >= 1) robotAssignedAttempt1++;
    }
    if (player.metrics?.reworkNorth === true) {
      reworkBadgeObserved++;
    }

    // Collect visible parcel positions (scene ORDER_* + optional world transit descriptors)
    const visibleOrderEntries = [];
    for (const oNode of orders) {
      if (!oNode.visible) continue;
      const wp = oNode.getWorldPosition(new THREE.Vector3());
      visibleOrderEntries.push({ name: oNode.name, node: oNode, pos: wp });

      // Check rework badge & R queue
      if (wp.z >= 6.4 && wp.z <= 7.8 && wp.x >= 2.9 && wp.x <= 5.8) {
        reworkInQueueRObserved++;
      }

      // Check tray vs untrayed vertical alignment on flat 0.860m support zones (queues/conveyors)
      if (Math.abs(wp.y - 0.860) < 0.04 && trayHeightChecked + untrayedHeightChecked < 60) {
        let trayObj = null;
        const cartonMeshes = [];
        oNode.traverse((ch) => {
          if (ch.name?.includes('VIS_order_tray') && ch.visible) trayObj = ch;
          if (
            ch.isMesh &&
            ch.visible &&
            !ch.name?.includes('tray') &&
            !ch.name?.includes('rework_badge')
          ) {
            let insideTray = false;
            for (let p = ch; p && p !== oNode; p = p.parent) {
              if (p.name?.includes('VIS_order_tray')) insideTray = true;
            }
            if (!insideTray) cartonMeshes.push(ch);
          }
        });
        if (cartonMeshes.length > 0) {
          const cb = new THREE.Box3();
          for (const cm of cartonMeshes) cb.expandByObject(cm);
          if (trayObj) {
            const tb = new THREE.Box3().setFromObject(trayObj, true);
            trayHeightChecked++;
            if (Math.abs(tb.min.y - 0.860) > 0.004 || Math.abs(cb.min.y - tb.min.y - 0.012) > 0.004) {
              trayHeightErrors++;
            }
          } else if (!replay.manifest.plan.trays) {
            untrayedHeightChecked++;
            if (Math.abs(cb.min.y - 0.860) > 0.004) untrayedHeightErrors++;
          }
        }
      }
    }

    for (const ent of visibleOrderEntries) {
      const { x, y, z } = ent.pos;
      if (x >= -9.55 && x <= 9.55 && Math.abs(z) <= 0.65 && y >= 0.78 && y <= 1.02) {
        mainConveyorHits++;
        const prevX = lastConveyorXByOrder.get(ent.name);
        if (prevX !== undefined && x > prevX + 0.01 && x - prevX < 4.0) {
          mainConveyorIncreasingXCount++;
        }
        lastConveyorXByOrder.set(ent.name, x);
      }
      if (
        ((x >= -6.85 && x <= -6.05) || (x >= 0.02 && x <= 0.82) || (x >= 6.04 && x <= 6.84)) &&
        z >= 0.35 &&
        z <= 2.05 &&
        y >= 0.78 &&
        y <= 1.02
      ) {
        spurHits++;
      }
      if (x >= 5.70 && x <= 6.60 && Math.abs(z) <= 0.55 && y >= 0.78 && y <= 1.02) {
        qcPortalHits++;
      }
      if (x >= -11.3 && x <= -8.8 && z >= -1.65 && z <= -0.35 && y >= 0.75 && y <= 1.05) {
        infeedBridgeHits++;
      }
      if (x >= 8.8 && x <= 10.3 && z >= -2.4 && z <= -0.35 && y >= 0.12 && y <= 1.05) {
        outfeedBridgeHits++;
      }
    }

    // Active workstation static duplicate check (F9):
    // When an actor is mid-operation (Prepare/Pick/Pack/Inspect/RobotPack), no visible static ORDER_* carton
    // may sit on top of that actor's active order point (within 0.25m XZ) with visible carton meshes!
    const checkActors = [...workers, ...(robot && robot.visible ? [robot] : [])];
    for (const act of checkActors) {
      const cName = act.userData?.__activeClipName ?? '';
      if (/^(Prepare|Pick|Pack|Inspect|RobotPack|Jammed|Service)(_Oversize)?$/.test(cName)) {
        activeWorkstationSamples++;
        const ap = act.getWorldPosition(new THREE.Vector3());
        const fwd = new THREE.Vector3(0, 0, 1).applyQuaternion(act.getWorldQuaternion(new THREE.Quaternion()));
        const workPtX = ap.x + fwd.x * 0.34;
        const workPtZ = ap.z + fwd.z * 0.34;
        for (const ent of visibleOrderEntries) {
          if (Math.hypot(ent.pos.x - workPtX, ent.pos.z - workPtZ) < 0.25) {
            // Check if non-tray static carton mesh is visible inside ORDER_*
            let hasVisibleStaticCarton = false;
            ent.node.traverse((ch) => {
              if (
                ch.isMesh &&
                ch.visible &&
                !ch.name?.includes('VIS_order_tray') &&
                !ch.name?.includes('rework_badge')
              ) {
                let inTray = false;
                for (let p = ch; p && p !== ent.node; p = p.parent) {
                  if (p.name?.includes('VIS_order_tray')) inTray = true;
                }
                if (!inTray) {
                  const s = scaleVec.setFromMatrixScale(ch.matrixWorld).length();
                  if (s > 0.05) hasVisibleStaticCarton = true;
                }
              }
            });
            if (hasVisibleStaticCarton) activeBenchDuplicateCollisions++;
          }
        }
      }
    }
  }

  // Targeted rework & scrap event sampling across full [0, horizon] shift
  for (const ev of replay.events) {
    const evKind = ev.kind ?? ev.event;
    if ((evKind === 'enqueue' && ev.stage === 3 && ev.attempt === 1) || evKind === 'rework') {
      const st = replay.seekTo(Math.min(horizon, ev.tick + 0.5) * ts);
      player.render(st, { playing: false, speed: 1, deltaSeconds: 0 });
      liveScene?.updateMatrixWorld(true);
      const { orders } = getActorAndOrderNodes(liveScene);
      for (const oNode of orders) {
        if (!oNode.visible) continue;
        const wp = oNode.getWorldPosition(new THREE.Vector3());
        if (wp.z >= 6.4 && wp.z <= 7.8 && wp.x >= 2.9 && wp.x <= 5.8) reworkInQueueRObserved++;
      }
    } else if (evKind === 'start' && (ev.attempt ?? 0) >= 1) {
      if (ev.resource === 'robot') robotAssignedAttempt1++;
      const endTick = ev.end_tick ?? ev.end ?? ev.tick + 2;
      for (const frac of [0.40, 0.70]) {
        const midTick = Math.min(horizon, ev.tick + (endTick - ev.tick) * frac);
        const st = replay.seekTo(midTick * ts);
        player.render(st, { playing: true, speed: 1, deltaSeconds: 0.1 * ts });
        liveScene?.updateMatrixWorld(true);
        if (player.metrics?.reworkNorth === true) reworkBadgeObserved++;
        if (ev.stage === 3 && ev.resource !== 'robot') {
          const { workers, orders } = getActorAndOrderNodes(liveScene);
          const wRework = findWorkerNodeById(workers, ev.resource) ?? null;
          const checkWorkers = wRework ? [wRework] : workers;
          for (const wn of checkWorkers) {
            const wp = wn.getWorldPosition(new THREE.Vector3());
            if (Math.hypot(wp.x - 1.80, wp.z - 5.55) <= 1.25 || Math.hypot(wp.x - 1.80, wp.z - 6.35) <= 1.45) {
              reworkBenchWorkerSamples++;
              const { maxDiag } = measureActorOpPropDiagAndSignature(wn);
              if (maxDiag > 0.10) reworkBenchCartonSamples++;
            }
          }
          for (const oNode of orders) {
            if (!oNode.visible) continue;
            const op = oNode.getWorldPosition(new THREE.Vector3());
            if (Math.hypot(op.x - 1.80, op.z - 6.35) <= 1.25 && op.y >= 0.70 && op.y <= 1.40) {
              reworkBenchCartonSamples++;
            }
          }
        }
      }
    } else if (
      ev.outcome === 'scrap' ||
      evKind === 'scrap' ||
      (evKind === 'complete' && ev.outcome === 'scrap') ||
      (evKind === 'finish' && ev.outcome === 'scrap') ||
      (evKind === 'outcome' && (ev.outcome === 'scrap' || ev.status === 'scrap'))
    ) {
      for (const dtOff of [-1.2, -0.4, 0.3, 1.0, 2.0]) {
        const tScrap = Math.max(0, Math.min(horizon, ev.tick + dtOff));
        const st = replay.seekTo(tScrap * ts);
        player.render(st, { playing: true, speed: 1, deltaSeconds: 0.1 * ts });
        liveScene?.updateMatrixWorld(true);
        const { workers, orders } = getActorAndOrderNodes(liveScene);
        for (const wn of workers) {
          const clip = wn.userData?.__activeClipName ?? '';
          const wp = wn.getWorldPosition(new THREE.Vector3());
          if (
            /^(CarryWalk|PlaceDown|PickUp)(_Oversize)?$/.test(clip) &&
            wp.x >= 5.2 &&
            wp.x <= 10.5 &&
            wp.z >= 2.2 &&
            wp.z <= 8.2
          ) {
            scrapCarryOrTransitObserved++;
          }
        }
        for (const oNode of orders) {
          if (!oNode.visible) continue;
          const op = oNode.getWorldPosition(new THREE.Vector3());
          if (op.x >= 6.0 && op.x <= 10.2 && op.z >= 3.2 && op.z <= 8.0 && op.y >= 0.02 && op.y <= 1.50) {
            scrapCarryOrTransitObserved++;
          }
        }
      }
    }
  }

  // Also sample active operation_prop phase progression on real stage events
  const opPhaseProgression = {};
  const scenarioOrders = replay.manifest?.scenario?.orders ?? [];
  for (const ev of replay.events) {
    const evKind = ev.kind ?? ev.event;
    const evActor = ev.resource ?? ev.actor;
    const evEnd = ev.end_tick ?? ev.end;
    if (evKind === 'start' && evActor && evEnd !== undefined && evEnd - ev.tick >= 3) {
      const ordKind = scenarioOrders[ev.order_id]?.kind ?? 'regular';
      const key = `${evActor === 'robot' ? 'robot' : `stage${ev.stage}`}_${ordKind}`;
      if (opPhaseProgression[key]) continue;
      const dur = evEnd - ev.tick;
      const sigs = [];
      let maxDiagSeen = 0;
      let minMixerT = Infinity;
      let maxMixerT = -Infinity;
      let clipSeen = null;
      for (const frac of [0.35, 0.62, 0.88]) {
        const sampleTick = ev.tick + dur * frac;
        const st = replay.seekTo(sampleTick * ts);
        player.render(st, { playing: true, speed: 1, deltaSeconds: 0.1 * ts });
        liveScene?.updateMatrixWorld(true);
        const { workers, robot } = getActorAndOrderNodes(liveScene);
        const targetActor =
          evActor === 'robot' ? robot : findWorkerNodeById(workers, evActor);
        if (targetActor) {
          clipSeen = targetActor.userData?.__activeClipName ?? clipSeen;
          if (clipSeen) {
            if (evActor === 'robot') observedRobotClips.add(clipSeen);
            else observedWorkerClips.add(clipSeen);
          }
          const mt = targetActor.userData?.__mixerTime;
          if (typeof mt === 'number') {
            if (mt < minMixerT) minMixerT = mt;
            if (mt > maxMixerT) maxMixerT = mt;
          }
          const { maxDiag, sig } = measureActorOpPropDiagAndSignature(targetActor);
          if (maxDiag > maxDiagSeen) maxDiagSeen = maxDiag;
          sigs.push(sig);
        }
      }
      let maxPropPhaseDelta = 0;
      if (sigs.length >= 2) {
        for (let a = 0; a < sigs.length; a++) {
          for (let b = a + 1; b < sigs.length; b++) {
            const len = Math.min(sigs[a].length, sigs[b].length);
            for (let i = 0; i < len; i++) {
              const d = Math.abs(sigs[a][i] - sigs[b][i]);
              if (d > maxPropPhaseDelta) maxPropPhaseDelta = d;
            }
          }
        }
      }
      opPhaseProgression[key] = {
        clipSeen,
        maxDiagSeen,
        maxPropPhaseDelta,
        mixerTimeSpan: Number.isFinite(maxMixerT - minMixerT) ? maxMixerT - minMixerT : 0,
      };
    }
  }

  // Sample jam -> assist windows for live VIS_ROBOT_ASSIST yaw cosine & robot Jammed/Service progression
  const assistSamples = [];
  for (const ev of replay.events) {
    const evKind = ev.kind ?? ev.event;
    const evActor = ev.resource ?? ev.actor;
    const evEnd = ev.end_tick ?? ev.end;
    if (evKind === 'assist' && evEnd !== undefined) {
      const evDur = evEnd - ev.tick;
      const activeStart = evDur > 2.2 ? ev.tick + 2.05 : ev.tick + evDur * 0.5;
      const activeSpan = Math.max(0.2, evEnd - activeStart);
      for (const frac of [0.15, 0.50, 0.85]) {
        const tSample = Math.min(evEnd - 0.05, activeStart + activeSpan * frac);
        const st = replay.seekTo(tSample * ts);
        player.render(st, { playing: true, speed: 1, deltaSeconds: 0.1 * ts });
        liveScene?.updateMatrixWorld(true);
        for (const aName of ['ANDON_GREEN', 'ANDON_RED', 'ANDON_AMBER']) {
          if (liveScene?.getObjectByName(aName)?.userData?.active === true) observedAndonStates.add(aName);
        }
        const { workers, robot } = getActorAndOrderNodes(liveScene);
        if (robot) {
          const rc = robot.userData?.__activeClipName;
          if (rc) observedRobotClips.add(rc);
        }
        const helper =
          findWorkerNodeById(workers, evActor) ??
          workers.find((w) => w.userData?.__activeClipName === 'Assist') ??
          null;
        if (helper) {
          const hp = helper.getWorldPosition(new THREE.Vector3());
          const hq = helper.getWorldQuaternion(new THREE.Quaternion());
          const fwd = new THREE.Vector3(0, 0, 1).applyQuaternion(hq);
          const fwdXZ = new THREE.Vector3(fwd.x, 0, fwd.z).normalize();
          const targetXZ = new THREE.Vector3(3.5 - hp.x, 0, -2.39 - hp.z).normalize();
          const cosSim = fwdXZ.dot(targetXZ);
          const angleErrDeg = Math.acos(THREE.MathUtils.clamp(cosSim, -1, 1)) * (180 / Math.PI);
          assistSamples.push({
            tick: tSample,
            actor: evActor,
            pos: [hp.x, hp.y, hp.z],
            distToAnchorM: Math.hypot(hp.x - 2.8, hp.z - (-1.95)),
            cosSim,
            angleErrDeg,
            helperClip: helper.userData?.__activeClipName ?? null,
            robotClip: robot?.userData?.__activeClipName ?? null,
            robotMixerTime: robot?.userData?.__mixerTime ?? null,
          });
        }
      }
    }
    if (evKind === 'jam') {
      const st = replay.seekTo(Math.min(horizon, ev.tick + 0.5) * ts);
      player.render(st, { playing: true, speed: 1, deltaSeconds: 0.1 * ts });
      liveScene?.updateMatrixWorld(true);
      for (const aName of ['ANDON_GREEN', 'ANDON_RED', 'ANDON_AMBER']) {
        if (liveScene?.getObjectByName(aName)?.userData?.active === true) observedAndonStates.add(aName);
      }
      const { robot } = getActorAndOrderNodes(liveScene);
      if (robot?.userData?.__activeClipName) observedRobotClips.add(robot.userData.__activeClipName);
    }
  }

  // Post-break smooth return walk check at CRITICAL dt = 0.10 ticks
  const breakEvents = replay.events.filter((e) => (e.kind ?? e.event) === 'break');
  let maxBreakStepJumpM = 0;
  let maxBreakJumpInfo = null;
  const breakEndChecks = [];

  if (breakEvents.length > 0) {
    // Build merged entry & post-break return windows at exact dt = 0.10 ticks
    const rawWindows = [];
    for (const e of breakEvents) {
      const bStart = e.tick;
      const bEnd = e.end_tick ?? e.end ?? e.tick + 20;
      rawWindows.push([Math.max(0, bStart - 0.5), Math.min(horizon, bStart + 2.5)]);
      rawWindows.push([Math.max(0, bEnd - 2.5), Math.min(horizon, bEnd + 1.5)]);
    }
    rawWindows.sort((a, b) => a[0] - b[0]);
    const mergedWindows = [];
    for (const wWin of rawWindows) {
      const last = mergedWindows.at(-1);
      if (last && wWin[0] <= last[1] + 0.11) {
        last[1] = Math.max(last[1], wWin[1]);
      } else {
        mergedWindows.push([...wWin]);
      }
    }

    for (const [winStart, winEnd] of mergedWindows) {
      const prevWorkerPos = new Map();
      for (let i = 0; winStart + i * 0.10 <= winEnd + 1e-9; i++) {
        const t = Number((winStart + i * 0.10).toFixed(4));
        const st = replay.seekTo(t * ts);
        player.render(st, { playing: true, speed: 1, deltaSeconds: 0.10 * ts });
        dynRoot?.updateMatrixWorld(true);

        const { workers } = getActorAndOrderNodes(liveScene);
        for (let wi = 0; wi < workers.length; wi++) {
          const w = workers[wi];
          const wKey = w.userData?.__workerId ?? `w${wi}`;
          const wp = w.getWorldPosition(new THREE.Vector3());
          const clip = w.userData?.__activeClipName;
          if (clip) observedWorkerClips.add(clip);
          const prev = prevWorkerPos.get(wKey);
          if (prev) {
            const jump = wp.distanceTo(prev);
            if (jump > maxBreakStepJumpM) {
              maxBreakStepJumpM = jump;
              maxBreakJumpInfo = { worker: wKey, tick: t, jumpM: jump, from: prev.toArray(), to: wp.toArray() };
            }
          }
          prevWorkerPos.set(wKey, wp.clone());
        }
      }
    }

    for (const bev of breakEvents) {
      const bActor = bev.resource ?? bev.actor;
      const bEnd = bev.end_tick ?? bev.end ?? bev.tick + 20;
      const nextEv = replay.events.find(
        (e) => (e.resource ?? e.actor) === bActor && e.tick >= bEnd && (e.kind ?? e.event) !== 'break',
      );
      const idleGapTicks = nextEv ? nextEv.tick - bEnd : horizon - bEnd;
      const checkT = Math.min(horizon, bEnd + 0.10);
      const stAfter = replay.seekTo(checkT * ts);
      player.render(stAfter, { playing: false, speed: 1, deltaSeconds: 0 });
      liveScene?.updateMatrixWorld(true);
      const { workers } = getActorAndOrderNodes(liveScene);
      const wNode = findWorkerNodeById(workers, bActor);
      const wp = wNode ? wNode.getWorldPosition(new THREE.Vector3()) : null;
      breakEndChecks.push({
        actor: bActor,
        breakEnd: bEnd,
        idleGapTicks,
        posAfterBreak: wp ? [wp.x, wp.y, wp.z] : null,
        strandedInBreakArea: wp ? wp.z <= -5.8 : true,
      });
    }
  }

  // Non-monotonic scrubbing determinism check
  const scrubTicks = [720.35, 12.10, 480.25, 12.10, 720.35].map((v) => Math.min(horizon - 0.5, v));
  const scrubSnaps = new Map();
  let maxScrubDeterminismErrM = 0;
  for (const stTick of scrubTicks) {
    const st = replay.seekTo(stTick * ts);
    player.render(st, { playing: false, speed: 1, deltaSeconds: 0 });
    liveScene?.updateMatrixWorld(true);
    const { workers, robot, orders } = getActorAndOrderNodes(liveScene);
    const snap = [];
    for (let wi = 0; wi < workers.length; wi++) {
      const n = workers[wi];
      const p = n.getWorldPosition(new THREE.Vector3());
      snap.push(`w${wi}:${p.x.toFixed(6)},${p.y.toFixed(6)},${p.z.toFixed(6)}`);
    }
    if (robot) {
      const p = robot.getWorldPosition(new THREE.Vector3());
      snap.push(`robot:${p.x.toFixed(6)},${p.y.toFixed(6)},${p.z.toFixed(6)}`);
    }
    for (const o of orders.filter((ord) => ord.visible)) {
      const p = o.getWorldPosition(new THREE.Vector3());
      snap.push(`${o.name}:${p.x.toFixed(6)},${p.y.toFixed(6)},${p.z.toFixed(6)}`);
    }
    const key = stTick.toFixed(3);
    if (scrubSnaps.has(key)) {
      const prevSnap = scrubSnaps.get(key);
      if (prevSnap.join('|') !== snap.join('|')) {
        maxScrubDeterminismErrM = 1.0;
      }
    } else {
      scrubSnaps.set(key, snap);
    }
  }

  // Render endState once more so returned metrics reflect final shift state
  player.render(endState, { playing: false, speed: 1, deltaSeconds: 0 });
  liveScene?.updateMatrixWorld(true);
  const endMetrics = player.metrics ? structuredClone(player.metrics) : null;
  {
    const { orders } = getActorAndOrderNodes(liveScene);
    for (const oNode of orders) {
      if (!oNode.visible) continue;
      const op = oNode.getWorldPosition(new THREE.Vector3());
      if (
        (Math.hypot(op.x - 8.65, op.z - 6.35) <= 1.30 && op.y >= 0.78 && op.y <= 1.50) ||
        (Math.hypot(op.x - 7.20, op.z - 7.00) <= 1.15 && op.y >= 0.02 && op.y <= 1.40)
      ) {
        scrapBenchOrBinVisibleAtEnd++;
      }
    }
    if (scrapBenchOrBinVisibleAtEnd === 0 && liveScene) {
      liveScene.traverse((o) => {
        if (!o.visible || !o.isMesh) return;
        if (/SCRAP.*(CARTON|STACK|ORDER|TOTE)/i.test(o.name || '') || /^ORDER_/.test(o.name || '')) {
          const op = o.getWorldPosition(new THREE.Vector3());
          if (
            (Math.hypot(op.x - 8.65, op.z - 6.35) <= 1.30 && op.y >= 0.78 && op.y <= 1.50) ||
            (Math.hypot(op.x - 7.20, op.z - 7.00) <= 1.15 && op.y >= 0.02 && op.y <= 1.40)
          ) {
            scrapBenchOrBinVisibleAtEnd++;
          }
        }
      });
    }
  }

  return {
    runId,
    detailed: true,
    metrics: endMetrics,
    counterMismatches,
    boundaryClampingOk,
    stationaryRollerDelta,
    activeRollerMaxAngleRad,
    maxRollerCenterDriftM,
    transit: {
      mainConveyorHits,
      mainConveyorIncreasingXCount,
      spurHits,
      qcPortalHits,
      infeedBridgeHits,
      outfeedBridgeHits,
    },
    observedWorkerClips: [...observedWorkerClips],
    observedRobotClips: [...observedRobotClips],
    observedAndonStates: [...observedAndonStates],
    activeWorkstationSamples,
    activeBenchDuplicateCollisions,
    emptyHandPropLeakCount,
    trayAlignment: {
      trayHeightChecked,
      trayHeightErrors,
      untrayedHeightChecked,
      untrayedHeightErrors,
    },
    rework: {
      reworkStartedInRaw: replay.manifest.raw.rework_started,
      reworkInQueueRObserved,
      reworkBadgeObserved,
      robotAssignedAttempt1,
      reworkBenchWorkerSamples,
      reworkBenchCartonSamples,
    },
    scrap: {
      scrapInRaw,
      scrapCarryOrTransitObserved,
      scrapBenchOrBinVisibleAtEnd,
    },
    opPhaseProgression,
    assistSamples,
    breaks: {
      count: breakEvents.length,
      maxBreakStepJumpM,
      maxBreakJumpInfo,
      breakEndChecks,
    },
    maxScrubDeterminismErrM,
    importantEvents: replay.importantEvents.map((e) => e.kind ?? e.type ?? e.label ?? String(e)),
  };
}

async function auditStudioBundle(repoRoot, v02Dir, gltfValidation) {
  const studioDir = path.join(repoRoot, 'studio');
  const hashesPath = path.join(studioDir, 'asset-hashes.json');
  let assetHashes = null;
  let assetHashesCount = 0;
  const hashMismatches = [];
  if (fsSync.existsSync(hashesPath)) {
    assetHashes = JSON.parse(await fs.readFile(hashesPath, 'utf8'));
    const filesMap = assetHashes.files ?? assetHashes;
    assetHashesCount = Object.values(filesMap ?? {}).filter(
      (v) => v && typeof v === 'object' && ('sha256' in v || 'bytes' in v),
    ).length;
    for (const rel of ALL_15_GLBS) {
      const rec = filesMap?.[rel] ?? filesMap?.[`4_Horses_Environment_v02/${rel}`];
      const v02Info = gltfValidation[rel];
      if (!rec || !v02Info?.exists) {
        hashMismatches.push({ file: rel, reason: 'missing_entry' });
      } else if (rec.sha256 !== v02Info.sha256 || rec.bytes !== v02Info.bytes) {
        hashMismatches.push({
          file: rel,
          expectedSha256: v02Info.sha256,
          actualSha256: rec.sha256,
          expectedBytes: v02Info.bytes,
          actualBytes: rec.bytes,
        });
      }
    }
  }

  const checkSceneDir = async (sceneDir) => {
    const exists = fsSync.existsSync(sceneDir);
    const presentAssets = [];
    const missingAssets = [];
    const parityMismatches = [];
    if (exists) {
      for (const rel of STUDIO_SCENE_PLAYER_ASSETS) {
        const abs = path.join(sceneDir, rel);
        const srcAbs = path.join(v02Dir, rel);
        if (!fsSync.existsSync(abs)) {
          missingAssets.push(rel);
        } else {
          presentAssets.push(rel);
          if (fsSync.existsSync(srcAbs)) {
            const [b1, b2] = await Promise.all([fs.readFile(abs), fs.readFile(srcAbs)]);
            if (sha256Hex(b1) !== sha256Hex(b2)) {
              parityMismatches.push(rel);
            }
          }
        }
      }
    }
    return { exists, presentAssets, missingAssets, parityMismatches };
  };

  const publicScene = await checkSceneDir(path.join(studioDir, 'public', 'scene'));
  const distDir = path.join(studioDir, 'dist');
  const distIndexExists = fsSync.existsSync(path.join(distDir, 'index.html'));
  const distAssetsDir = path.join(distDir, 'assets');
  let distJsFiles = [];
  let distCssFiles = [];
  if (fsSync.existsSync(distAssetsDir)) {
    const ents = await fs.readdir(distAssetsDir);
    distJsFiles = ents.filter((e) => e.endsWith('.js')).sort();
    distCssFiles = ents.filter((e) => e.endsWith('.css')).sort();
  }
  const distScene = await checkSceneDir(path.join(distDir, 'scene'));

  return {
    assetHashesExists: Boolean(assetHashes),
    assetHashesCount,
    hashMismatches,
    publicScene,
    dist: {
      exists: fsSync.existsSync(distDir),
      indexHtmlExists: distIndexExists,
      jsFiles: distJsFiles,
      cssFiles: distCssFiles,
      scene: distScene,
    },
  };
}

async function auditStudioReplays(packDir, v02Dir) {
  let player = null;
  try {
    lastCapturedScene = null;
    player = await createScenePlayer(makeCanvas(1280, 720), { assetBase: 'http://local.probe/__local_assets__/' });
    const liveScene = player.scene ?? lastCapturedScene;

    // Test setLayer('ENV_OVERHEAD', true) on live player if supported
    let overheadLayerToggleOk = false;
    if (typeof player.setLayer === 'function' && liveScene) {
      const ovNode = liveScene.getObjectByName('ENV_OVERHEAD');
      player.setLayer('ENV_OVERHEAD', true);
      const v1 = ovNode ? ovNode.visible === true : true;
      player.setLayer('ENV_OVERHEAD', false);
      const v2 = ovNode ? ovNode.visible === false : true;
      overheadLayerToggleOk = v1 && v2;
    }

    // Live Studio ceiling & active light audit (02:42:13Z) + floor arrows audit (03:14:54Z)
    const visibleOverheadMeshes = [];
    let activeLightCount = 0;
    const lightTypes = [];
    if (liveScene) {
      liveScene.traverse((o) => {
        if (isForbiddenOverheadMeshNode(o, liveScene) && isEffectivelyVisibleNode(o)) {
          visibleOverheadMeshes.push(o.name || o.parent?.name || '<unnamed>');
        }
        if (o.isLight && isEffectivelyVisibleNode(o) && (o.intensity ?? 1) > 0) {
          activeLightCount++;
          lightTypes.push(o.type || 'Light');
        }
      });
    }
    const ceilingAudit = {
      visibleOverheadMeshes,
      activeLightCount,
      lightTypes,
    };
    const floorArrowsAudit = liveScene ? auditFloorArrowsAndZones([liveScene]) : null;

    // Test camera presets (including 'blueprint' & 'rework')
    const cameraPresets = {};
    let badCameraPreset = { threw: false, name: null, message: null };
    if (typeof player.setCameraPreset === 'function') {
      for (const pName of ['overview', 'q1', 'q1/pick', 'robot', 'qc', 'break', 'blueprint', 'rework']) {
        try {
          player.setCameraPreset(pName);
          cameraPresets[pName] = {
            supported: true,
            cameraPos: player.camera?.position?.toArray?.() ?? null,
          };
        } catch (err) {
          cameraPresets[pName] = {
            supported: false,
            error: String(err?.message ?? err),
          };
        }
      }
      badCameraPreset = expectThrows(() => player.setCameraPreset('nonexistent_preset'));
      try {
        player.setCameraPreset('overview');
      } catch {}
    }

    // Measure post-map envelope inside liveScene
    const postMapEnvelope = liveScene
      ? {
          slabBox: boxToDict(
            new THREE.Box3().setFromObject(
              liveScene.getObjectByName('Raised_concrete_slab') ||
                liveScene.getObjectByName('Raised concrete slab'),
              true,
            ),
          ),
          wallsBox: boxToDict(
            new THREE.Box3().setFromObject(liveScene.getObjectByName('ENV_WALLS_AND_DOCKS'), true),
          ),
          dock01Pos: liveScene.getObjectByName('DOCK_01')?.getWorldPosition(new THREE.Vector3()).toArray() ?? null,
          dock02Pos: liveScene.getObjectByName('DOCK_02')?.getWorldPosition(new THREE.Vector3()).toArray() ?? null,
        }
      : null;

    const shifts = {};
    let sampleManifest = null;
    let sampleEventsText = null;
    let totalPackRuns = 0;
    let v1RunIds = [];
    let quarterlyRunIds = [];
    const required9V1 = [
      'v1-manual-seed11',
      'v1-manual-seed29',
      'v1-manual-seed47',
      'v1-candidate-seed11',
      'v1-candidate-seed29',
      'v1-candidate-seed47',
      'v1-reference-seed11',
      'v1-reference-seed29',
      'v1-reference-seed47',
    ];

    if (packDir && fsSync.existsSync(path.join(packDir, 'index.json'))) {
      const idx = JSON.parse(await fs.readFile(path.join(packDir, 'index.json'), 'utf8'));
      const allRuns = idx.runs ?? [];
      totalPackRuns = allRuns.length;
      const v1Runs = allRuns.filter((r) => !r.mode || r.mode === 'v1');
      v1RunIds = v1Runs.map((r) => r.id);
      quarterlyRunIds = allRuns.filter((r) => r.mode === 'quarterly').map((r) => r.id);
      const detailedIds = new Set([
        'v1-manual-seed11',
        'v1-candidate-seed11',
        'v1-candidate-seed29',
        'v1-reference-seed11',
      ]);

      for (const runEntry of v1Runs) {
        const runId = runEntry.id;
        const mRel = runEntry.manifest ?? `${runId}/manifest.json`;
        const eRel = runEntry.events ?? `${runId}/events.jsonl`;
        const mObj = JSON.parse(await fs.readFile(path.join(packDir, mRel), 'utf8'));
        const eTxt = await fs.readFile(path.join(packDir, eRel), 'utf8');
        if (!sampleManifest) {
          sampleManifest = mObj;
          sampleEventsText = eTxt;
        }
        const rep = createReplay(mObj, eTxt, { runId });
        shifts[runId] = await inspectSingleShiftReplay(
          player,
          liveScene,
          rep,
          runId,
          detailedIds.has(runId),
        );
      }
    }

    // Also inspect test-jam-h32 fixture if present in 4_Horses_Environment_v02/test_fixtures/test-jam-h32
    const jamDir = path.join(v02Dir, 'test_fixtures', 'test-jam-h32');
    if (fsSync.existsSync(path.join(jamDir, 'manifest.json'))) {
      try {
        const jm = JSON.parse(await fs.readFile(path.join(jamDir, 'manifest.json'), 'utf8'));
        const je = await fs.readFile(path.join(jamDir, 'events.jsonl'), 'utf8');
        const jRep = createReplay(jm, je, { runId: 'test-jam-h32' });
        shifts['test-jam-h32'] = await inspectSingleShiftReplay(player, liveScene, jRep, 'test-jam-h32', true);
      } catch (err) {
        shifts['test-jam-h32'] = { ok: false, error: String(err?.message ?? err) };
      }
    }

    const v1Set = new Set(v1RunIds);
    const all9RequiredV1Present = required9V1.every((id) => v1Set.has(id));

    return {
      ok: true,
      overheadLayerToggleOk,
      ceilingAudit,
      floorArrowsAudit,
      cameraPresets,
      badCameraPreset,
      postMapEnvelope,
      totalPackRuns,
      v1RunIds,
      quarterlyRunIds,
      all9RequiredV1Present,
      shifts,
      _sample: { sampleManifest, sampleEventsText },
    };
  } catch (err) {
    return { ok: false, error: String(err?.stack ?? err?.message ?? err), shifts: {} };
  } finally {
    try { player?.dispose?.(); } catch {}
  }
}

function rectsOverlapWithMargin(a, b, margin = 0.05) {
  return (
    a.maxX > b.minX - margin &&
    b.maxX > a.minX - margin &&
    a.maxZ > b.minZ - margin &&
    b.maxZ > a.minZ - margin
  );
}

function makeSyntheticReplayForWorkers(workersSpec) {
  const events = [
    { tick: 0, kind: 'arrival', order_id: 0, resource: null, stage: 1, attempt: 0, end_tick: null },
  ];
  let t = 2;
  workersSpec.forEach((zones, wIdx) => {
    let prevZone = zones[0];
    for (const z of zones) {
      if (z !== prevZone) {
        events.push({
          tick: t,
          kind: 'walk',
          order_id: 0,
          resource: `w${wIdx}`,
          stage: z,
          attempt: 0,
          end_tick: t + 2,
        });
      }
      events.push({
        tick: t,
        kind: 'start',
        order_id: 0,
        resource: `w${wIdx}`,
        stage: z,
        attempt: 0,
        end_tick: t + 5,
      });
      prevZone = z;
      t += 6;
    }
  });
  return {
    horizonTicks: Math.max(60, t + 10),
    manifest: {
      world: { clock: { tick_seconds: 30, walk_ticks: 2 } },
      plan: { robot: true, trays: false, route: 'bypass', workers: workersSpec },
    },
    events,
  };
}

function deriveParallelBenchRects(bindings, maxSlots) {
  const rects = [];
  for (const stage of [1, 2, 3, 4]) {
    const count = maxSlots?.[stage] ?? 0;
    for (let i = 1; i < count; i++) {
      const slot = SpatialMod.stageSlotTransform(bindings, stage, i);
      const obs = slot.obstacle;
      rects.push({
        name: obs?.name ?? `PARALLEL_STAGE_${stage}_${i}`,
        stage,
        slotIndex: i,
        minX: obs ? obs.minX : slot.bench[0] - 0.55,
        maxX: obs ? obs.maxX : slot.bench[0] + 0.55,
        minZ: obs ? obs.minZ : slot.bench[2] - 0.47,
        maxZ: obs ? obs.maxZ : slot.bench[2] + 0.57,
        pos: slot.bench,
      });
    }
  }
  return rects;
}

function auditSpatial(bindings) {
  const staticEquipRects = [
    { name: 'VIS_STAGE_1_TABLE', minX: -11.55, maxX: -10.45, minZ: -2.12, maxZ: -1.08 },
    { name: 'Q1_PAIRED_PALLET_DECK', minX: -11.66, maxX: -9.22, minZ: -3.76, maxZ: -2.86 },
    { name: 'BENCH_PICK', minX: -6.30, maxX: -4.50, minZ: -3.15, maxZ: -2.18 },
    { name: 'BENCH_PACK', minX: 0.90, maxX: 2.70, minZ: -3.15, maxZ: -2.18 },
    { name: 'VIS_ROBOT_PACK_TABLE', minX: 2.95, maxX: 4.06, minZ: -3.18, maxZ: -2.13 },
    { name: 'VIS_STAGE_4_TABLE', minX: 5.45, maxX: 6.55, minZ: -3.17, maxZ: -2.13 },
    { name: 'SUPPLY_TROLLEY', minX: -2.29, maxX: -1.31, minZ: -4.03, maxZ: -3.37 },
    { name: 'RACK_01', minX: -9.76, maxX: -7.84, minZ: -6.72, maxZ: -5.98 },
    { name: 'RACK_02', minX: -6.16, maxX: -4.24, minZ: -6.72, maxZ: -5.98 },
    { name: 'RACK_03', minX: -2.56, maxX: -0.64, minZ: -6.72, maxZ: -5.98 },
    { name: 'CONVEYOR', minX: -9.50, maxX: 9.50, minZ: -0.56, maxZ: 0.56 },
    { name: 'WALKWAY_GREEN_5S', minX: -17.7, maxX: 17.7, minZ: 4.40, maxZ: 5.90 },
  ];

  const evalLayoutConfig = (workersSpec) => {
    try {
      const synReplay = makeSyntheticReplayForWorkers(workersSpec);
      const pres = SpatialMod.buildWorkerPresentationPlan(synReplay, bindings);
      const benchRects = deriveParallelBenchRects(bindings, pres.maxSlots);

      const overlaps = [];
      for (let i = 0; i < benchRects.length; i++) {
        const a = benchRects[i];
        if (Math.abs(a.pos[0]) > 17.4 || Math.abs(a.pos[2]) > 8.4) {
          overlaps.push({ a: a.name, b: 'OUT_OF_HALL' });
        }
        for (let j = i + 1; j < benchRects.length; j++) {
          if (rectsOverlapWithMargin(a, benchRects[j], 0.04)) {
            overlaps.push({ a: a.name, b: benchRects[j].name });
          }
        }
        for (const eq of staticEquipRects) {
          if (rectsOverlapWithMargin(a, eq, 0.04)) {
            overlaps.push({ a: a.name, b: eq.name });
          }
        }
      }

      // Check walk path segments against pres.obstacles (DEFAULT_OBSTACLES + dynamic parallel benches)
      let pathHits = 0;
      const allObs = pres.obstacles ?? SpatialMod.DEFAULT_OBSTACLES ?? [];
      const actIter = pres.activities instanceof Map ? pres.activities.values() : Object.values(pres.activities ?? {});
      for (const act of actIter) {
        for (const pts of [act.path, act.returnPath]) {
          if (!Array.isArray(pts)) continue;
          // Check interior segments (excluding start/end post approach segments)
          for (let s = 1; s + 2 < pts.length; s++) {
            for (const obs of allObs) {
              if (SpatialMod.segmentHitsObstacle(pts[s], pts[s + 1], obs, 0.02)) pathHits++;
            }
          }
        }
      }

      return {
        ok: true,
        parallelBenchCount: benchRects.length,
        maxSlots: pres.maxSlots,
        overlaps,
        pathHits,
      };
    } catch (err) {
      return { ok: false, error: String(err?.message ?? err) };
    }
  };

  const layouts = {
    stage3_5slots: evalLayoutConfig([[1], [2], [3], [3], [3], [3], [3], [4]]),
    stage3_6slots: evalLayoutConfig([[1, 3], [2, 3], [3], [3], [3], [3], [3, 4], [4]]),
    stages124_3slots: evalLayoutConfig([[1], [1], [1], [2], [2], [2], [4], [4, 1]]),
    stage4_3slots: evalLayoutConfig([[1], [2], [3], [4], [4], [4]]),
    singleWorkerMin: evalLayoutConfig([[1, 2, 3, 4]]),
  };

  // A* path tests across full 36x18m hall
  const testAstar = (from, to) => {
    try {
      const pts = SpatialMod.planWalkPath(from, to);
      const inBounds = pts.every((p) => Math.abs(p[0]) <= 17.85 && Math.abs(p[2]) <= 8.85);
      return { ok: true, pointCount: pts.length, inBounds, start: pts[0], end: pts[pts.length - 1] };
    } catch (err) {
      return { ok: false, error: String(err?.message ?? err) };
    }
  };

  const astarRoutes = {
    dock01_to_dock02: testAstar([-17.5, 0, 5.15], [17.5, 0, 5.15]),
    sw_to_ne_corners: testAstar([-17.5, 0, -8.2], [17.5, 0, 8.2]),
    dock01_to_stage1: testAstar([-17.5, 0, 5.15], [-11.0, 0, -1.0]),
    boundary_176_86: testAstar([-17.6, 0, -8.6], [17.6, 0, 8.6]),
    trivial_same_point: testAstar([1.8, 0, -2.05], [1.8, 0, -2.05]),
  };

  // 8 BREAK_POINTS distinctness & reachability
  const bp = SpatialMod.BREAK_POINTS ?? [];
  let minBreakPairDistM = Infinity;
  for (let i = 0; i < bp.length; i++) {
    for (let j = i + 1; j < bp.length; j++) {
      const d = Math.hypot(bp[i][0] - bp[j][0], bp[i][2] - bp[j][2]);
      if (d < minBreakPairDistM) minBreakPairDistM = d;
    }
  }
  let breakRoutesReachable = 0;
  for (let st = 1; st <= 4; st++) {
    const fromP = SpatialMod.actorPosition(bindings, st, 0);
    for (let bi = 0; bi < bp.length; bi++) {
      const r = testAstar(fromP, bp[bi]);
      if (r.ok) breakRoutesReachable++;
    }
  }

  // Queue & outcome stack caps
  const makeDummyOrders = (n) => Array.from({ length: n }, (_, i) => ({ id: i, kind: 'regular' }));
  const qStackAudit = {
    Q2_12: SpatialMod.queueStackPositions(bindings, 'Q2', makeDummyOrders(12)),
    Q3_10: SpatialMod.queueStackPositions(bindings, 'Q3', makeDummyOrders(10)),
    Q4_8: SpatialMod.queueStackPositions(bindings, 'Q4', makeDummyOrders(8)),
    Q1_25: SpatialMod.queueStackPositions(bindings, 'Q1', makeDummyOrders(25)),
    R_25: SpatialMod.queueStackPositions(bindings, 'R', makeDummyOrders(25)),
    good_20: SpatialMod.outcomeStackPositions(bindings, 'good', makeDummyOrders(20)),
    escaped_20: SpatialMod.outcomeStackPositions(bindings, 'escaped', makeDummyOrders(20)),
    scrap_15: SpatialMod.outcomeStackPositions(bindings, 'scrap', makeDummyOrders(15)),
  };
  const stackSummary = {};
  for (const [k, v] of Object.entries(qStackAudit)) {
    const visList = v.visibleOrders ?? v.visible ?? [];
    stackSummary[k] = { visibleCount: visList.length, overflow: v.overflow };
  }

  return {
    layouts,
    astarRoutes,
    breakPoints: {
      count: bp.length,
      minPairDistM: minBreakPairDistM,
      reachableFromStagesCount: breakRoutesReachable,
    },
    stackSummary,
  };
}

function expectThrows(fn) {
  try {
    fn();
    return { threw: false, name: null, message: null };
  } catch (err) {
    return { threw: true, name: err?.name ?? 'Error', message: String(err?.message ?? err) };
  }
}

async function expectThrowsAsync(fn) {
  try {
    await fn();
    return { threw: false, name: null, message: null };
  } catch (err) {
    return { threw: true, name: err?.name ?? 'Error', message: String(err?.message ?? err) };
  }
}

async function runNegativeChecks(bindings, workerGltf, robotGltf, supportGltf, envGltf, sampleManifest, sampleEventsText) {
  const q2_17 = queueSlotPositions(bindings, 'Q2', 17).length;
  const r_101 = queueSlotPositions(bindings, 'R', 101).length;
  const q1_0 = queueSlotPositions(bindings, 'Q1', 0).length;
  const badQueue = expectThrows(() => queueSlotPositions(bindings, 'Q99', 1));
  const negQueueCount = expectThrows(() => queueSlotPositions(bindings, 'Q1', -1));
  const badStageWork = expectThrows(() => manualWorkPosition(bindings, 99, 0));

  const pool = createOrderVisualPool(supportGltf.scene);
  const badOrderKind = expectThrows(() => pool.getOrCreate({ runId: 'r1', orderId: 1, kind: 'invalid' }));
  pool.getOrCreate({ runId: 'r1', orderId: 2, kind: 'regular' });
  const kindMutation = expectThrows(() => pool.getOrCreate({ runId: 'r1', orderId: 2, kind: 'oversize' }));
  pool.dispose();

  // Worker visual adapter negative inputs & clone independence
  const wVis1 = createActorVisual(workerGltf, { actorType: 'worker', templates: supportGltf.scene });
  const wVis2 = createActorVisual(workerGltf, { actorType: 'worker', templates: supportGltf.scene });
  wVis1.sample({ state: 'walk', phase: 0.25 });
  wVis2.sample({ state: 'idle', phase: 0.0 });
  wVis1.root.updateMatrixWorld(true);
  wVis2.root.updateMatrixWorld(true);
  const h1 = wVis1.root.getObjectByName('ATTACH_WORKER_HAND_L')?.getWorldPosition(new THREE.Vector3());
  const h2 = wVis2.root.getObjectByName('ATTACH_WORKER_HAND_L')?.getWorldPosition(new THREE.Vector3());
  const workerClonesIndependent = h1 && h2 ? h1.distanceTo(h2) > 0.01 : false;

  const badWorkerState = expectThrows(() => wVis1.sample({ state: 'teleport' }));
  const badWorkerOrderKind = expectThrows(() => wVis1.sample({ state: 'pack', orderKind: 'pallet' }));
  const badWorkerPhase = expectThrows(() => wVis1.sample({ state: 'pack', phase: Number.NaN }));
  const badWorkerCycles = expectThrows(() => wVis1.sample({ state: 'pack', cycles: -1 }));

  // Robot visual adapter boundary & negative checks
  const rVis = createActorVisual(robotGltf, { actorType: 'robot', templates: supportGltf.scene });
  const rNotPurchased = rVis.sample({ state: 'not_purchased' });
  const notPurchasedHidden = rVis.root.visible === false && rNotPurchased.clip === null;
  const rDisabled = rVis.sample({ state: 'disabled', phase: 0.3 });
  const offlineMarkerVisible = Boolean(rVis.root.getObjectByName('VIS_status_offline')?.visible);
  const disabledShowsOffline = rVis.root.visible === true && rDisabled.clip === 'Offline' && offlineMarkerVisible;
  const badRobotWorkerState = expectThrows(() => rVis.sample({ state: 'prepare' }));

  const envClone = envGltf.scene.clone(true);
  const badEnvLayer = expectThrows(() => setEnvironmentLayer(envClone, 'ENV_NONEXISTENT', true));
  const badAndonState = expectThrows(() => setRobotAndonState(envClone, 'unknown_state'));
  const badMapRoot = expectThrows(() => applyMapGeometryFixes(null, {}));

  // Spatial negative checks
  const badAstarNan = expectThrows(() => SpatialMod.planWalkPath([Number.NaN, 0, 0], [0, 0, 0]));
  const badAstarTrap = expectThrows(() =>
    SpatialMod.planWalkPath([0, 0, 3.0], [5.0, 0, 3.0], {
      obstacles: [{ name: 'TRAP_BOX', minX: 2.0, maxX: 8.0, minZ: 0.0, maxZ: 6.0 }],
    }),
  );
  const badActorStage0 = expectThrows(() => SpatialMod.actorPosition(bindings, 0, 0));
  const badActorStage5 = expectThrows(() => SpatialMod.actorPosition(bindings, 5, 0));
  const badActorNegSlot = expectThrows(() => SpatialMod.actorPosition(bindings, 3, -1));
  const badActorFracSlot = expectThrows(() => SpatialMod.actorPosition(bindings, 3, 1.5));
  const pres1 = SpatialMod.buildWorkerPresentationPlan(makeSyntheticReplayForWorkers([[1]]), bindings);
  const badSlotWorker = expectThrows(() => pres1.slotAt('w99', 10));

  // Replay & Data negative checks
  let replayNegatives = {};
  if (sampleManifest && sampleEventsText) {
    const validRep = createReplay(sampleManifest, sampleEventsText, { runId: 'neg-base' });
    const seekNan = expectThrows(() => validRep.seekTo(Number.NaN));
    const seekInf = expectThrows(() => validRep.seekTo(Number.POSITIVE_INFINITY));

    const badFormatM = structuredClone(sampleManifest);
    badFormatM.replay_format = 'wrong-format-v0';

    const badEconM = structuredClone(sampleManifest);
    badEconM.economy.total += 100;

    const badRawM = structuredClone(sampleManifest);
    badRawM.raw.good += 1;

    const lines = sampleEventsText.trim().split('\n');
    const nonMonoLines = [...lines];
    if (nonMonoLines.length >= 3) {
      const evA = JSON.parse(nonMonoLines[1]);
      const evB = JSON.parse(nonMonoLines[2]);
      evB.tick = evA.tick - 1;
      nonMonoLines[1] = JSON.stringify({ ...evA, tick: 10 });
      nonMonoLines[2] = JSON.stringify({ ...evB, tick: 5 });
    }

    // Q2 capacity overflow (capacity.pick = 0 so first Stage-1 start exceeds Q2 capacity)
    const overflowManifest = structuredClone(sampleManifest);
    overflowManifest.world.capacity.pick = 0;

    // Truncated trace missing finish (drop all 'finish' lines while keeping subsequent ticks)
    const truncLines = lines.filter((l) => !l.includes('"finish"')).slice(0, 25);

    replayNegatives = {
      seekNan,
      seekInf,
      badFormat: expectThrows(() => createReplay(badFormatM, sampleEventsText)),
      badEcon: expectThrows(() => createReplay(badEconM, sampleEventsText)),
      badRaw: expectThrows(() => createReplay(badRawM, sampleEventsText)),
      nonMonotonicTick: expectThrows(() => createReplay(sampleManifest, nonMonoLines.join('\n'))),
      q2Overflow: expectThrows(() => createReplay(overflowManifest, sampleEventsText)),
      truncatedMissingFinish: expectThrows(() => createReplay(sampleManifest, truncLines.join('\n'))),
    };
  }

  // DataMod unsafe events_file & invalid quarter week count
  const unsafeManifest = structuredClone(sampleManifest ?? { replay_format: 'robotization-bench.replay.v1' });
  unsafeManifest.events_file = '../secret.jsonl';
  const badEventsFile = await expectThrowsAsync(async () =>
    DataMod.openLocal([
      { name: 'manifest.json', text: async () => JSON.stringify(unsafeManifest) },
      { name: 'events.jsonl', text: async () => '' },
    ]),
  );

  const badQuarter13Weeks = expectThrows(() =>
    DataMod.parseDocument(
      JSON.stringify({
        pack_format: 'robotization-bench.3d-pack-index.v1',
        runs: [
          {
            id: 'q-bad',
            mode: 'quarterly',
            quarter: { weeks: Array.from({ length: 13 }, (_, i) => ({ week: i + 1 })) },
          },
        ],
      }),
      'index.json',
    ),
  );
  const badQuarter0Weeks = expectThrows(() =>
    DataMod.parseDocument(
      JSON.stringify({
        pack_format: 'robotization-bench.3d-pack-index.v1',
        runs: [{ id: 'q-empty', mode: 'quarterly', quarter: { weeks: [] } }],
      }),
      'index.json',
    ),
  );

  // Assist yaw cosine geometric BVA check
  const evalAssistYaw = (yawRad) => {
    const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(0, yawRad, 0));
    const fwd = new THREE.Vector3(0, 0, 1).applyQuaternion(q);
    const fwdXZ = new THREE.Vector3(fwd.x, 0, fwd.z).normalize();
    const targetXZ = new THREE.Vector3(3.5 - 2.8, 0, -2.39 - (-1.95)).normalize();
    const cos = fwdXZ.dot(targetXZ);
    return { cos, deg: Math.acos(THREE.MathUtils.clamp(cos, -1, 1)) * (180 / Math.PI) };
  };

  return {
    queues: { q2_17, r_101, q1_0, badQueue, negQueueCount, badStageWork },
    orderPool: { badOrderKind, kindMutation },
    workerAdapter: {
      workerClonesIndependent,
      badWorkerState,
      badWorkerOrderKind,
      badWorkerPhase,
      badWorkerCycles,
    },
    robotAdapter: {
      notPurchasedHidden,
      disabledShowsOffline,
      badRobotWorkerState,
    },
    envAndMap: { badEnvLayer, badAndonState, badMapRoot },
    spatial: {
      badAstarNan,
      badAstarTrap,
      badActorStage0,
      badActorStage5,
      badActorNegSlot,
      badActorFracSlot,
      badSlotWorker,
    },
    replayNegatives,
    dataNegatives: { badEventsFile, badQuarter13Weeks, badQuarter0Weeks },
    assistYawBva: {
      exactAtan2: evalAssistYaw(Math.atan2(0.70, -0.44)),
      wrongPi: evalAssistYaw(Math.PI),
      wrongNeg248: evalAssistYaw(-2.48),
      wrongPos2569: evalAssistYaw(2.569),
      wrongZero: evalAssistYaw(0),
    },
  };
}

function inspectPngBuffer(buf, sampleStride = 2) {
  const sig = Buffer.from([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]);
  if (buf.length < 33 || !buf.subarray(0, 8).equals(sig)) {
    throw new Error('Invalid PNG signature');
  }
  let pos = 8;
  let ihdr = null;
  const idats = [];
  let sawIend = false;

  while (pos + 8 <= buf.length) {
    const len = buf.readUInt32BE(pos);
    const ctype = buf.subarray(pos + 4, pos + 8).toString('latin1');
    const bodyEnd = pos + 8 + len;
    if (bodyEnd + 4 > buf.length) throw new Error(`Truncated chunk ${ctype}`);
    const expectedCrc = buf.readUInt32BE(bodyEnd);
    const actualCrc = zlib.crc32(buf.subarray(pos + 4, bodyEnd)) >>> 0;
    if (actualCrc !== expectedCrc) throw new Error(`CRC32 mismatch in ${ctype}`);
    const body = buf.subarray(pos + 8, bodyEnd);
    if (ctype === 'IHDR') {
      if (len !== 13 || ihdr !== null) throw new Error('Invalid IHDR');
      ihdr = {
        width: body.readUInt32BE(0),
        height: body.readUInt32BE(4),
        bitDepth: body[8],
        colorType: body[9],
        comp: body[10],
        filt: body[11],
        interlace: body[12],
      };
    } else if (ctype === 'IDAT') {
      idats.push(body);
    } else if (ctype === 'IEND') {
      sawIend = true;
      break;
    }
    pos = bodyEnd + 4;
  }

  if (!ihdr || idats.length === 0 || !sawIend) throw new Error('Missing IHDR/IDAT/IEND');
  const channels = { 0: 1, 2: 3, 3: 1, 4: 2, 6: 4 }[ihdr.colorType];
  if (!channels || ![8, 16].includes(ihdr.bitDepth) || ihdr.interlace !== 0) {
    throw new Error(`Unsupported IHDR colorType=${ihdr.colorType} bitDepth=${ihdr.bitDepth}`);
  }
  const raw = zlib.inflateSync(Buffer.concat(idats));
  const bpp = channels * (ihdr.bitDepth / 8);
  const rowBytes = ihdr.width * bpp;
  const stride = 1 + rowBytes;
  if (raw.length !== ihdr.height * stride) {
    throw new Error(`Inflated scanline mismatch ${raw.length} != ${ihdr.height * stride}`);
  }

  let prev = new Uint8Array(rowBytes);
  let cur = new Uint8Array(rowBytes);
  let rS = 0, gS = 0, bS = 0, rS2 = 0, gS2 = 0, bS2 = 0, n = 0;
  const counts = new Map();
  const thirdTotals = [0, 0, 0];
  const thirdFg = [0, 0, 0];
  const stepX = Math.max(1, sampleStride) * bpp;

  for (let y = 0; y < ihdr.height; y++) {
    const off = y * stride;
    const ft = raw[off];
    if (ft === 0) {
      for (let i = 0; i < rowBytes; i++) cur[i] = raw[off + 1 + i];
    } else if (ft === 1) {
      for (let i = 0; i < rowBytes; i++) cur[i] = (raw[off + 1 + i] + (i >= bpp ? cur[i - bpp] : 0)) & 0xFF;
    } else if (ft === 2) {
      for (let i = 0; i < rowBytes; i++) cur[i] = (raw[off + 1 + i] + prev[i]) & 0xFF;
    } else if (ft === 3) {
      for (let i = 0; i < rowBytes; i++) {
        const left = i >= bpp ? cur[i - bpp] : 0;
        cur[i] = (raw[off + 1 + i] + ((left + prev[i]) >> 1)) & 0xFF;
      }
    } else if (ft === 4) {
      for (let i = 0; i < rowBytes; i++) {
        const a = i >= bpp ? cur[i - bpp] : 0;
        const b = prev[i];
        const c = i >= bpp ? prev[i - bpp] : 0;
        const p = a + b - c;
        const pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
        const pr = pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
        cur[i] = (raw[off + 1 + i] + pr) & 0xFF;
      }
    } else {
      throw new Error(`Invalid PNG filter ${ft} at row ${y}`);
    }

    if (y % sampleStride === 0) {
      const cG = (channels >= 3 ? 1 : 0) * (ihdr.bitDepth === 16 ? 2 : 1);
      const cB = (channels >= 3 ? 2 : 0) * (ihdr.bitDepth === 16 ? 2 : 1);
      for (let px = 0; px < rowBytes; px += stepX) {
        const xCoord = Math.floor(px / bpp);
        const rv = cur[px], gv = cur[px + cG], bv = cur[px + cB];
        rS += rv; gS += gv; bS += bv;
        rS2 += rv * rv; gS2 += gv * gv; bS2 += bv * bv;
        const k = ((rv >> 3) << 10) | ((gv >> 3) << 5) | (bv >> 3);
        counts.set(k, (counts.get(k) ?? 0) + 1);
        const tIdx = Math.min(2, Math.floor((xCoord * 3) / Math.max(1, ihdr.width)));
        thirdTotals[tIdx]++;
        if (Math.abs(rv - 0xDC) > 10 || Math.abs(gv - 0xE2) > 10 || Math.abs(bv - 0xE8) > 10) {
          thirdFg[tIdx]++;
        }
        n++;
      }
    }
    const tmp = prev; prev = cur; cur = tmp;
  }

  const std = (s, s2) => (n > 0 ? Math.sqrt(Math.max(0, s2 / n - (s / n) ** 2)) : 0);
  let entropy = 0;
  for (const c of counts.values()) {
    const p = c / n;
    entropy -= p * Math.log2(p);
  }
  return {
    width: ihdr.width,
    height: ihdr.height,
    bitDepth: ihdr.bitDepth,
    colorType: ihdr.colorType,
    rgbStd: [std(rS, rS2), std(gS, gS2), std(bS, bS2)],
    unique5bit: counts.size,
    entropyBits: entropy,
    thirdForegroundRatio: thirdTotals.map((tot, i) => (tot > 0 ? thirdFg[i] / tot : 0)),
  };
}

async function collectPngFiles(baseDir, relPrefix = '') {
  const out = [];
  if (!fsSync.existsSync(baseDir)) return out;
  const entries = await fs.readdir(baseDir, { withFileTypes: true });
  for (const ent of entries) {
    const rel = relPrefix ? `${relPrefix}/${ent.name}` : ent.name;
    if (ent.isDirectory()) {
      if (ent.name === 'node_modules' || rel.startsWith('animations_frame_by_frame/frames')) continue;
      out.push(...(await collectPngFiles(path.join(baseDir, ent.name), rel)));
    } else if (ent.isFile() && ent.name.toLowerCase().endsWith('.png')) {
      out.push({ absPath: path.join(baseDir, ent.name), relPath: rel });
    }
  }
  return out;
}

async function auditPngs(repoRoot, v02Dir) {
  const v02Pngs = await collectPngFiles(v02Dir, '');
  const playerCheckDir = path.join(repoRoot, 'artifacts', 'player-check');
  const playerPngs = await collectPngFiles(playerCheckDir, 'artifacts/player-check');

  const files = {};
  for (const item of [...v02Pngs, ...playerPngs]) {
    try {
      const buf = await fs.readFile(item.absPath);
      const metrics = inspectPngBuffer(buf, 4);
      files[item.relPath] = {
        exists: true,
        valid: true,
        bytes: buf.length,
        sha256: sha256Hex(buf),
        ...metrics,
      };
    } catch (err) {
      files[item.relPath] = {
        exists: true,
        valid: false,
        error: String(err?.message ?? err),
      };
    }
  }
  return { files };
}

async function runReplayCheckMode(args, v02Dir, bindings) {
  lastCapturedScene = null;
  const player = await createScenePlayer(makeCanvas(1280, 720), { assetBase: 'http://local.probe/__local_assets__/' });
  const liveScene = player.scene ?? lastCapturedScene;
  try {
    if (args.httpUrl) {
      const parsedUrl = new URL(args.httpUrl);
      if (parsedUrl.pathname === '' || parsedUrl.pathname === '/') {
        parsedUrl.pathname = '/index.json';
      }
      const handle = await DataMod.openRemote(parsedUrl.href);
      const runs = handle.index?.runs ?? [];
      const v1Runs = runs.filter((r) => !r.mode || r.mode === 'v1');
      const loadedRunIds = [];
      let sampleInspection = null;
      for (const r of v1Runs) {
        const loaded = await handle.loadRun(r.id);
        const rep = loaded?.replay ?? loaded;
        loadedRunIds.push(r.id);
        if (!sampleInspection) {
          sampleInspection = await inspectSingleShiftReplay(player, liveScene, rep, r.id, true);
        }
      }
      return {
        ok: true,
        mode: 'http',
        indexUrl: parsedUrl.href,
        totalRunsCount: runs.length,
        v1RunIds: v1Runs.map((r) => r.id),
        loadedRunIds,
        sampleInspection,
      };
    }
    if (args.runDir) {
      const mObj = JSON.parse(await fs.readFile(path.join(args.runDir, 'manifest.json'), 'utf8'));
      const eTxt = await fs.readFile(path.join(args.runDir, 'events.jsonl'), 'utf8');
      const runId = path.basename(args.runDir);
      const rep = createReplay(mObj, eTxt, { runId });
      const shiftReport = await inspectSingleShiftReplay(player, liveScene, rep, runId, true);
      const spatialPlan = SpatialMod.buildWorkerPresentationPlan(rep, bindings);
      const benchRects = deriveParallelBenchRects(bindings, spatialPlan.maxSlots);
      let benchOverlaps = 0;
      for (let i = 0; i < benchRects.length; i++) {
        for (let j = i + 1; j < benchRects.length; j++) {
          if (rectsOverlapWithMargin(benchRects[i], benchRects[j], 0.04)) benchOverlaps++;
        }
      }
      return {
        ok: true,
        mode: 'run-dir',
        shiftReport,
        maxSlots: spatialPlan.maxSlots,
        parallelBenchCount: benchRects.length,
        benchOverlaps,
      };
    }
    throw new Error('replay-check requires --run-dir or --http-url');
  } finally {
    try { player.dispose?.(); } catch {}
  }
}

async function runSessionMode(repoRoot, packDir) {
  const t0 = performance.now();
  const v02Dir = path.join(repoRoot, '4_Horses_Environment_v02');
  const bindings = JSON.parse(await fs.readFile(path.join(v02Dir, 'visual_bindings.json'), 'utf8'));
  const anchorsPath = path.join(v02Dir, 'anchors.json');
  const anchorsJson = fsSync.existsSync(anchorsPath)
    ? JSON.parse(await fs.readFile(anchorsPath, 'utf8'))
    : {};

  // 1. Validate & load all 15 GLBs
  const gltfValidation = {};
  const loadedGltfs = new Map();
  const loadedBufs = new Map();

  for (const rel of ALL_15_GLBS) {
    const abs = path.join(v02Dir, rel);
    if (!fsSync.existsSync(abs)) {
      gltfValidation[rel] = { exists: false };
      continue;
    }
    const buf = await fs.readFile(abs);
    loadedBufs.set(rel, buf);
    const valReport = await validator.validateBytes(new Uint8Array(buf), { uri: rel, maxIssues: 100 });
    const { jsonDoc } = parseGlbChunks(buf);
    const gltf = await parseGltfScene(buf);
    loadedGltfs.set(rel, gltf);
    gltf.scene.updateMatrixWorld(true);

    const threeNodeNames = [];
    gltf.scene.traverse((o) => {
      if (o.name) threeNodeNames.push(o.name);
    });
    const stats = countSceneMeshesAndTris(gltf.scene);
    const envBox = boxToDict(new THREE.Box3().setFromObject(gltf.scene, true));

    gltfValidation[rel] = {
      exists: true,
      bytes: buf.length,
      sha256: sha256Hex(buf),
      numErrors: valReport.issues.numErrors,
      numWarnings: valReport.issues.numWarnings,
      rawNodeNames: (jsonDoc.nodes ?? []).map((n) => n.name ?? ''),
      threeNodeNames,
      clipNames: gltf.animations.map((a) => a.name),
      ...stats,
      aabb: envBox,
    };
  }

  const envGltf = loadedGltfs.get('warehouse_environment.glb');
  const layoutGltf = loadedGltfs.get('modules/visual_layout.glb');
  const supportGltf = loadedGltfs.get('modules/visual_support.glb');
  const workerGltf = loadedGltfs.get('modules/warehouse_worker.glb');
  const robotGltf = loadedGltfs.get('modules/humanoid_robot.glb');

  // 2. Layout, Support & Environment audits
  const { layoutAudit, supportAudit } = auditLayoutAndSupport(layoutGltf, supportGltf, bindings, anchorsJson);
  const environmentAudit = auditEnvironment(envGltf, layoutGltf, supportGltf, bindings);

  // 3. Character & Workstation Grasp audits
  const workerAudit = await inspectCharacterGlb(loadedBufs.get('modules/warehouse_worker.glb'), 'worker');
  const robotAudit = await inspectCharacterGlb(loadedBufs.get('modules/humanoid_robot.glb'), 'robot');

  // Compute 20-core-joint rest-pose proportion parity between worker and robot
  const sharedCoreJoints = [
    'root', 'hips', 'spine', 'chest', 'neck', 'head',
    'upper_armL', 'forearmL', 'handL', 'upper_armR', 'forearmR', 'handR',
    'thighL', 'shinL', 'footL', 'toeL', 'thighR', 'shinR', 'footR', 'toeR',
  ];
  let maxCoreJointDiffM = 0;
  let comparedCoreJoints = 0;
  for (const jn of sharedCoreJoints) {
    const wp = workerAudit.restBonePositions[jn];
    const rp = robotAudit.restBonePositions[jn];
    if (wp && rp) {
      comparedCoreJoints++;
      const d = Math.hypot(wp[0] - rp[0], wp[1] - rp[1], wp[2] - rp[2]);
      if (d > maxCoreJointDiffM) maxCoreJointDiffM = d;
    }
  }

  const workstationGrasp = auditWorkstationGrasp(workerGltf, robotGltf, layoutGltf, bindings);

  // 4. Map idempotency, Studio Bundle, Studio Replay, Spatial, Negative & PNG audits
  const mapIdempotency = await auditMapIdempotency(envGltf, layoutGltf, repoRoot);
  const studioBundleAudit = await auditStudioBundle(repoRoot, v02Dir, gltfValidation);
  const studioReplayAudit = await auditStudioReplays(packDir, v02Dir);
  const sampleManifest = studioReplayAudit._sample?.sampleManifest ?? null;
  const sampleEventsText = studioReplayAudit._sample?.sampleEventsText ?? null;
  delete studioReplayAudit._sample;

  const spatialAudit = auditSpatial(bindings);
  const negativeChecks = await runNegativeChecks(
    bindings,
    workerGltf,
    robotGltf,
    supportGltf,
    envGltf,
    sampleManifest,
    sampleEventsText,
  );
  const pngAudit = await auditPngs(repoRoot, v02Dir);

  return {
    ok: true,
    nodeVersion: process.version,
    elapsedS: Number(((performance.now() - t0) / 1000).toFixed(4)),
    gltfValidation,
    layoutAudit,
    supportAudit,
    environmentAudit,
    characterAudit: {
      worker: workerAudit,
      robot: robotAudit,
      proportionParity: { comparedCoreJoints, maxCoreJointDiffM },
      workstationGrasp,
    },
    mapIdempotency,
    studioBundleAudit,
    studioReplayAudit,
    spatialAudit,
    negativeChecks,
    pngAudit,
  };
}

async function inspectGenericGlb(buf, uri = 'custom.glb') {
  const valReport = await validator.validateBytes(new Uint8Array(buf), { uri, maxIssues: 100 });
  const { jsonDoc } = parseGlbChunks(buf);
  const gltf = await parseGltfScene(buf);
  gltf.scene.updateMatrixWorld(true);
  const threeNodeNames = [];
  gltf.scene.traverse((o) => {
    if (o.name) threeNodeNames.push(o.name);
  });
  const stats = countSceneMeshesAndTris(gltf.scene);
  return {
    bytes: buf.length,
    sha256: sha256Hex(buf),
    numErrors: valReport.issues.numErrors,
    numWarnings: valReport.issues.numWarnings,
    rawNodeNames: (jsonDoc.nodes ?? []).map((n) => n.name ?? ''),
    threeNodeNames,
    clipNames: gltf.animations.map((a) => a.name),
    ...stats,
    aabb: boxToDict(new THREE.Box3().setFromObject(gltf.scene, true)),
  };
}

function parseCliArgs(argv) {
  const out = { mode: 'session', repo: DEFAULT_REPO_ROOT, packDir: null, outPath: null };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--mode') out.mode = argv[++i];
    else if (a === '--repo') out.repo = argv[++i];
    else if (a === '--pack-dir') out.packDir = argv[++i];
    else if (a === '--out') out.outPath = argv[++i];
    else if (a === '--glb') out.glbPath = argv[++i];
    else if (a === '--validate-glb') { out.mode = 'validate-glb'; out.glbPath = argv[++i]; }
    else if (a === '--probe-custom-glb') { out.mode = 'probe-custom-glb'; out.glbPath = argv[++i]; }
    else if (a === '--kind') out.kind = argv[++i];
    else if (a === '--run-dir') out.runDir = argv[++i];
    else if (a === '--http-url') out.httpUrl = argv[++i];
  }
  return out;
}

async function main() {
  const args = parseCliArgs(process.argv.slice(2));
  const v02Dir = path.join(args.repo, '4_Horses_Environment_v02');
  installHeadlessBrowserShim(v02Dir, args.repo);

  let payload;
  try {
    if (args.mode === 'validate-glb') {
      const buf = await fs.readFile(args.glbPath);
      try {
        const rep = await validator.validateBytes(new Uint8Array(buf), {
          uri: path.basename(args.glbPath),
          maxIssues: 100,
        });
        payload = {
          ok: true,
          numErrors: rep.issues.numErrors,
          numWarnings: rep.issues.numWarnings,
          messages: rep.issues.messages.slice(0, 15),
        };
      } catch (valErr) {
        payload = { ok: true, numErrors: 1, throwError: String(valErr?.message ?? valErr) };
      }
    } else if (args.mode === 'probe-custom-glb' || args.mode === 'custom-glb') {
      const buf = await fs.readFile(args.glbPath);
      if (args.kind === 'generic') {
        payload = { ok: true, ...(await inspectGenericGlb(buf, path.basename(args.glbPath))) };
      } else {
        const charInfo = await inspectCharacterGlb(buf, args.kind ?? 'worker');
        const valReport = await validator.validateBytes(new Uint8Array(buf), {
          uri: path.basename(args.glbPath),
          maxIssues: 100,
        });
        payload = {
          ok: true,
          numErrors: valReport.issues.numErrors,
          numWarnings: valReport.issues.numWarnings,
          ...charInfo,
        };
      }
    } else if (args.mode === 'replay-check') {
      const bindings = JSON.parse(await fs.readFile(path.join(v02Dir, 'visual_bindings.json'), 'utf8'));
      payload = await runReplayCheckMode(args, v02Dir, bindings);
    } else {
      payload = await runSessionMode(args.repo, args.packDir);
    }
  } catch (err) {
    payload = { ok: false, error: String(err?.stack ?? err?.message ?? err) };
  }

  const jsonText = JSON.stringify(payload, null, 2);
  if (args.outPath) {
    await fs.mkdir(path.dirname(args.outPath), { recursive: true });
    await fs.writeFile(args.outPath, jsonText, 'utf8');
  } else {
    process.stdout.write(jsonText + '\n');
  }
}

await main();
