// UI hooks for the authored GLB. No simulation state or routing lives here.
export const environmentLayers = Object.freeze([
  ['ENV_FLOOR_AND_GRID', true],
  ['ENV_WALLS_AND_DOCKS', true],
  ['ENV_WORKSTATIONS_DETAIL', true],
  ['ENV_ROBOT_CELL', true],
  ['ENV_BREAK_AREA', true],
  ['ENV_OVERHEAD', false],
]);

export function setEnvironmentLayer(scene, name, visible) {
  if (!environmentLayers.some(([id]) => id === name)) throw new Error(`Unknown environment layer: ${name}`);
  const layer = scene.getObjectByName(name);
  if (!layer) throw new Error(`Missing GLB layer: ${name}`);
  layer.visible = Boolean(visible);
  return layer;
}

export function applyEnvironmentDefaults(scene) {
  for (const [name, visible] of environmentLayers) setEnvironmentLayer(scene, name, visible);
  setRobotAndonState(scene, 'idle');
}

const channels = Object.freeze({off:null, idle:'GREEN', pack:'GREEN', jammed:'RED', service:'AMBER',not_purchased:null,disabled:null,helper_walking:'RED',finished:'GREEN'});
export function setRobotAndonState(scene, state) {
  const key = typeof state === 'string' ? state.toLowerCase() : '';
  if (!Object.hasOwn(channels, key)) throw new Error(`Unsupported Andon state: ${state}`);
  const active = channels[key];
  for (const channel of ['RED', 'AMBER', 'GREEN']) {
    const node = scene.getObjectByName(`ANDON_${channel}`);
    if (!node?.isMesh) throw new Error(`Missing Andon lens: ${channel}`);
    if (!node.userData.andonMaterialsOwned) {
      node.material = Array.isArray(node.material) ? node.material.map(m => m.clone()) : node.material.clone();
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
