// UI hooks for the authored GLB. No simulation state or routing lives here.
export const environmentLayers = Object.freeze([
  ['ENV_FLOOR_AND_GRID', true],
  ['ENV_WALLS_AND_DOCKS', true],
  ['ENV_WORKSTATIONS_DETAIL', true],
  ['ENV_ROBOT_CELL', true],
  ['ENV_BREAK_AREA', true],
  ['ENV_OVERHEAD', false],
]);

const OVERHEAD_BLOCK_RE = /OVERHEAD_TRUSS|OVERHEAD_CABLE_TRAY|HIGHBAY|LUMINAIRE|CEILING_BEAM|LIGHTING_RIG|ENV_OVERHEAD|ENV_LIGHTING_RIG/i;

function hasLightDescendant(node) {
  let found = false;
  node?.traverse?.(child => { if (child.isLight) found = true; });
  return found;
}

export function suppressOverheadStructures(scene, {keepContainerFlag = false} = {}) {
  if (!scene?.traverse) return;
  scene.traverse(node => {
    if (node.isLight) return;
    if (node.name === 'ENV_OVERHEAD' || node.name === 'ENV_LIGHTING_RIG') {
      if (!keepContainerFlag && !hasLightDescendant(node)) node.visible = false;
      node.traverse(child => {
        if (!child.isLight && child !== node && !hasLightDescendant(child)) child.visible = false;
      });
      return;
    }
    if (node.isMesh || node.isLine || node.isPoints) {
      for (let p = node; p; p = p.parent) {
        if (OVERHEAD_BLOCK_RE.test(p.name || '')) {
          node.visible = false;
          break;
        }
      }
    }
  });
}

export function setEnvironmentLayer(scene, name, visible) {
  const canonical = name === 'overhead' ? 'ENV_OVERHEAD' : name;
  if (!environmentLayers.some(([id]) => id === canonical)) throw new Error(`Unknown environment layer: ${name}`);
  const layer = scene.getObjectByName(canonical);
  if (!layer) throw new Error(`Missing GLB layer: ${canonical}`);
  layer.visible = Boolean(visible);
  if (canonical === 'ENV_OVERHEAD') suppressOverheadStructures(scene, {keepContainerFlag: true});
  return layer;
}

export function applyEnvironmentDefaults(scene) {
  for (const [name, visible] of environmentLayers) setEnvironmentLayer(scene, name, visible);
  suppressOverheadStructures(scene);
  setRobotAndonState(scene, 'idle');
}

const channels = Object.freeze({off:null, offline:null, idle:'GREEN', pack:'GREEN', jammed:'RED', service:'AMBER',not_purchased:null,disabled:null,helper_walking:'RED',finished:'GREEN'});
const ownedAndonNodes = new WeakMap();
export function setRobotAndonState(scene, state) {
  const key = typeof state === 'string' ? state.toLowerCase() : '';
  if (!Object.hasOwn(channels, key)) throw new Error(`Unsupported Andon state: ${state}`);
  const active = channels[key];
  for (const channel of ['RED', 'AMBER', 'GREEN']) {
    const node = scene.getObjectByName(`ANDON_${channel}`);
    if (!node?.isMesh) throw new Error(`Missing Andon lens: ${channel}`);
    if (ownedAndonNodes.get(node) !== node.material) {
      node.material = Array.isArray(node.material) ? node.material.map(m => m.clone()) : node.material.clone();
      ownedAndonNodes.set(node, node.material);
      node.userData.andonMaterialsOwned = true;
    }
    const materials = Array.isArray(node.material) ? node.material : [node.material];
    for (const material of materials) {
      material.emissive.copy(material.color);
      material.emissiveIntensity = channel === active ? 1.6 : .02;
    }
    node.userData.active = channel === active;
  }
}
