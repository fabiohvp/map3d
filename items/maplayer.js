// Camada "Itens 3D" do viewer do mapa (../index.html): os objetos (moveis, recipientes, armas, decoracao,
// vegetacao...) viram o modelo de items/ (Destaques feitos a mao, conjuntos e gerador automatico), desenhado pelo
// three.js no mesmo contexto WebGL2 e depth buffer do terreno. A arquitetura fica na malha do conversor (keepData).
// Conjuntos (cama, mesa longa, canhao, arvore de varias pecas...) sao reconhecidos no mapa pelas pecas vizinhas e
// viram um modelo so. Cada modelo e achatado em uma malha por material e desenhado por instancias.
import * as THREE from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { ITEMS } from './models.js';
import { buildOne, buildSet, mapTree, fieldCannon } from './gen.js';
import { TEX } from './textures.js';

TEX.size = 256;
const ZU = .144;                                 // altura de 1 z do UO em unidades de modelo (como em buildSet: dz * .144)
const UP = new THREE.Vector3(0, 1, 0);
const hexOf = g => g.toString(16).toUpperCase().padStart(4, '0');
// canhoes: o oeste/leste (ao longo de x) tem conjunto; o norte/sul (ao longo de y) e o mesmo canhao girado
const ROTATED = [[[0xE8E, 0xE8F, 0xE90], [0xE8D, 0xE8C, 0xE8B]], [[0xE94, 0xE95, 0xE96], [0xE93, 0xE92, 0xE91]]];
const CANNON_DIR = { 0xE8E: -1, 0xE94: 1 };      // boca do canhao de muralha: oeste (-x) / leste (+x)
const TRUNK = /\b(tree|trunk)\b/, LEAVES = /\b(leaves|needles|foliage)\b/;   // pecas da arvore no mesmo tile
const FLOOR = /\b(hay|straw)\b/;                 // decalque de chao com a art deitada (floorDecal)
// moveis de varias pecas (o gerador faz um por tile), arte de parede (quadro, banner, tapecaria),
// trepadeira e ossos (classificados como arbusto e lingote), vaso e ervas penduradas
const MESH_NAME = /display case|counter|showcase|banner|tapestr|painting|portrait|\b(table|bench|desk|vines?|ivy|bones?|bone pile|gravestone|tombstone|headstone|potted|herbs)\b/;
const LYING = /^(weapon|armor|clothing|jewelry|consumable)$/;   // deitados ou expostos num movel: vao para a malha
const SB = 5;                                   // sprBox por sprite: x0, x1, y0, y1, topo (z)
const PS = 4;                                    // place por instancia: x, altura (z), y, giro

export async function createItemLayer(gl, canvas) {
  const data = await (await fetch(new URL('data/items.json', import.meta.url))).json();
  const byHex = {};
  data.items.forEach(it => byHex[it.hex] = it);
  const curated = new Map(ITEMS.map(it => [it.pieces.map(p => p[0]).sort().join('|'), it]));

  // conjuntos por peca-ancora (a primeira), maiores primeiro: 4 pecas de dossel antes de 2 de cama
  const SETS = data.sets.map(st => {
    const xs = st.pieces.map(p => p.dx), ys = st.pieces.map(p => p.dy);
    return { st, ids: st.pieces.map(p => parseInt(p.id, 16)), cx: (Math.min(...xs) + Math.max(...xs)) / 2, cy: (Math.min(...ys) + Math.max(...ys)) / 2 };
  });
  // conjuntos que so existem num sentido: a versao girada (outros graphics, ao longo de y) usa o modelo do original
  // girado; [graphics do original em x, graphics da versao em y na mesma ordem]
  for (const [a, b] of ROTATED) {
    const src = SETS.findIndex(s => s.ids.join() === a.join());
    if (src < 0) continue;
    const pieces = b.map((id, k) => ({ ...SETS[src].st.pieces[k], id: hexOf(id), dx: 0, dy: SETS[src].st.pieces[k].dx }));
    const ys = pieces.map(p => p.dy);
    SETS.push({ st: { ...SETS[src].st, pieces }, ids: b, cx: 0, cy: (Math.min(...ys) + Math.max(...ys)) / 2, rot: -Math.PI / 2, src });
  }
  // arvore de um tile so (tronco + folhas): fica para a montagem pela malha (mapTree), nao para o conjunto
  for (const s of SETS) s.skip = s.st.cat === 'vegetation' && s.st.pieces.every(p => !p.dx && !p.dy);
  const byAnchor = new Map();
  SETS.forEach((s, i) => { const k = s.ids[0]; if (!byAnchor.has(k)) byAnchor.set(k, []); byAnchor.get(k).push(i); });
  for (const l of byAnchor.values()) l.sort((a, b) => SETS[b].ids.length - SETS[a].ids.length);

  const renderer = new THREE.WebGLRenderer({ canvas, context: gl });
  renderer.autoClear = false;
  renderer.setPixelRatio(1);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  const scene = new THREE.Scene();
  scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), .04).texture;
  scene.environmentIntensity = .55;
  const sun = new THREE.DirectionalLight(0xfff1dc, 2.4);
  scene.add(sun, new THREE.HemisphereLight(0xcfe0ff, 0x4a3a2a, .5));
  const fog = new THREE.Fog(0xffffff, 1, 2);
  const root = new THREE.Group();
  scene.add(root);
  const cam = new THREE.PerspectiveCamera();
  cam.matrixAutoUpdate = false;
  const restore = () => {
    renderer.resetState();
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
  };
  restore();

  // ---------------------------------------------------------------- modelos
  const models = new Map();    // chave ('g' + graphic | 's' + conjunto) -> { parts: [{ geo, mat, mesh, cap }] }
  const queue = [];
  let place = new Map();       // chave -> [x, altura, y, giro, ...] da ultima montagem
  let missing = 0;

  const matKey = m => [m.type, m.color && m.color.getHexString(), m.roughness, m.metalness, m.emissive && m.emissive.getHexString(),
    m.emissiveIntensity, m.opacity, m.transparent, m.side, m.map && m.map.uuid, m.bumpMap && m.bumpMap.uuid,
    m.roughnessMap && m.roughnessMap.uuid, m.bumpScale].join('|');
  // malhas do modelo -> uma geometria por material (posicao, normal, uv), no referencial do modelo
  function flatten(obj) {
    obj.updateMatrixWorld(true);
    const groups = new Map();
    obj.traverse(o => {
      if (!o.isMesh || !o.visible) return;
      const m = Array.isArray(o.material) ? o.material[0] : o.material;
      const g = o.geometry.index ? o.geometry.toNonIndexed() : o.geometry.clone();
      for (const k of Object.keys(g.attributes)) if (k !== 'position' && k !== 'normal' && k !== 'uv') g.deleteAttribute(k);
      g.morphAttributes = {}; g.clearGroups();
      if (!g.attributes.normal) g.computeVertexNormals();
      if (!g.attributes.uv) g.setAttribute('uv', new THREE.Float32BufferAttribute(new Float32Array(g.attributes.position.count * 2), 2));
      g.applyMatrix4(o.matrixWorld);
      if (o.matrixWorld.determinant() < 0) for (const a of Object.values(g.attributes)) {   // espelhado: desvira os triangulos
        const s = a.itemSize, arr = a.array;
        for (let t = 0; t + 2 < a.count; t += 3) for (let c = 0; c < s; c++) {
          const i = (t + 1) * s + c, j = (t + 2) * s + c, v = arr[i]; arr[i] = arr[j]; arr[j] = v;
        }
      }
      const k = matKey(m);
      if (!groups.has(k)) groups.set(k, { mat: m, geos: [] });
      groups.get(k).geos.push(g);
    });
    return [...groups.values()].map(({ mat, geos }) => ({ mat, geo: geos.length > 1 ? mergeGeometries(geos) : geos[0], mesh: null, cap: 0 }));
  }
  // decalque de chao: a art do atlas de items/ deitada no tile, pela projecao do viewer (z = 0):
  // pixel = (22 (x - y) + w/2, 22 (x + y) + hp - 44), com x, y a partir do canto do tile
  const atlasTex = new Map();
  function atlas(i) {
    if (!atlasTex.has(i)) {
      const t = new THREE.TextureLoader().load(new URL(`data/atlas_${i}.png`, import.meta.url).href);
      t.colorSpace = THREE.SRGBColorSpace;
      t.magFilter = t.minFilter = THREE.NearestFilter;
      t.generateMipmaps = false;
      atlasTex.set(i, t);
    }
    return atlasTex.get(i);
  }
  function floorDecal(it) {
    const { w, hp } = it, S = 2048, pos = [], uv = [];
    const s0 = -w / 44, s1 = w / 44, t0 = (44 - hp) / 22, t1 = 2;   // s = x - y, t = x + y cobrindo a art
    for (const [s, t] of [[s0, t0], [s1, t1], [s1, t0], [s0, t0], [s0, t1], [s1, t1]]) {   // face para cima
      pos.push((t + s) / 2, .6 * ZU, (t - s) / 2);                  // acima do piso (malha de ~0,4 z)
      uv.push((it.ax + 22 * s + w / 2) / S, 1 - (it.ay + 22 * t + hp - 44) / S);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    geo.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
    geo.setAttribute('normal', new THREE.Float32BufferAttribute(pos.map((_, i) => i % 3 === 1 ? 1 : 0), 3));
    const g = new THREE.Group();
    g.add(new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ map: atlas(it.atlas), alphaTest: .5, side: THREE.DoubleSide, roughness: 1 })));
    return g;
  }
  function build(key) {
    let obj;
    try {
      if (key[0] === 'F') obj = floorDecal(byHex[hexOf(+key.slice(1))]);
      else if (key[0] === 'T') {                                // arvore: tronco + folhas do tile, altura da malha (z)
        const [t, l, top] = key.slice(1).split(',').map(Number);
        obj = mapTree([t, l].filter(Boolean).map(g => byHex[hexOf(g)]), Math.max(1, top * ZU * .95));
      } else if (key[0] === 's') {
        const { st, ids } = SETS[+key.slice(1)];
        const cur = curated.get(ids.map(hexOf).sort().join('|'));
        obj = cur ? cur.build() : CANNON_DIR[ids[0]] ? fieldCannon(CANNON_DIR[ids[0]]) : buildSet(st, id => byHex[id], () => null);
      } else {
        const it = byHex[hexOf(+key.slice(1))], cur = curated.get(it.hex);
        obj = cur ? cur.build() : buildOne(it, null);
      }
    } catch (e) { console.warn('modelo falhou', key, e); obj = new THREE.Group(); }
    return { parts: flatten(obj) };
  }
  const tmp = new THREE.Matrix4(), q = new THREE.Quaternion(), v = new THREE.Vector3(), one = new THREE.Vector3(1, 1, 1);
  function apply(key) {
    const md = models.get(key), pos = place.get(key) || [], n = pos.length / PS;
    for (const p of md.parts) {
      if (n > p.cap) {
        if (p.mesh) { root.remove(p.mesh); p.mesh.dispose(); }
        p.cap = Math.max(8, Math.ceil(n * 1.5));
        p.mesh = new THREE.InstancedMesh(p.geo, p.mat, p.cap);
        p.mesh.frustumCulled = false;
        root.add(p.mesh);
      }
      if (!p.mesh) continue;
      for (let i = 0, o = 0; i < n; i++, o += PS) {
        q.setFromAxisAngle(UP, pos[o + 3]);
        p.mesh.setMatrixAt(i, tmp.compose(v.set(pos[o], pos[o + 1] * ZU, pos[o + 2]), q, one));
      }
      p.mesh.count = n;
      p.mesh.visible = n > 0;
      p.mesh.instanceMatrix.needsUpdate = true;
    }
  }

  // ficam na malha do conversor, fiel a art: arquitetura, o que a classificacao nao reconheceu (unknown), decalques
  // (itens de parede, cabides, pecas de mesa/vitrine), moveis de varias pecas sem conjunto (vitrine, balcao) e o que
  // nao tem modelo; arma/armadura/roupa/joia/consumivel deitado (top: altura da malha em z, <= 4) ou apoiada num movel do tile
  // (onSurface: exposta em vitrine ou mesa); o que e plano (< 1 z: terra de cova, tapete, mancha) e o que tem hue
  // (cor da instancia: os modelos nao tingem, a malha sim)
  const kept = new Map();
  function keepData(g, top, onSurface, hue) {
    let k = kept.get(g);
    if (k === undefined) {
      const it = byHex[hexOf(g)];
      k = !it ? 2 : it.cat === 'architecture' || it.cat === 'terrain' || it.cat === 'unknown' || it.cat === 'effect' || it.sub === 'painting' || MESH_NAME.test(it.name || '') ? 2
        : LYING.test(it.cat) ? 1 : 0;
      kept.set(g, k);
    }
    return !!hue || k === 2 || top < 1 || (k === 1 && (onSurface || (top !== undefined && top <= 4)));
  }

  return {
    // chunks: [{ cx, cy, A, B, S, n0, count }] perto da camera (S: apoiada num movel, por instancia); sprG: graphic por sprite; roofs: telhados visiveis;
    // sprBox: pegada/altura da malha de cada sprite
    update(chunks, sprG, roofs, sprBox) {
      const cells = new Map(), list = [];
      missing = 0;
      for (const c of chunks) for (let i = c.n0; i < c.count; i++) {
        const a = c.A[i], s = c.B[i] & 0xFFFF, g = sprG[s];
        if (!roofs && ((a >>> 25) & 1)) continue;             // sob telhado/andar, como nas malhas do conversor
        if (keepData(g, sprBox && sprBox[s * SB + 4], c.S && c.S[i], c.B[i] >>> 16)) continue;
        if (!byHex[hexOf(g)]) { missing++; continue; }
        const e = { g, s, x: c.cx * 64 + (a & 63), y: c.cy * 64 + ((a >>> 6) & 63), z: ((a >>> 12) & 255) - 128, used: false };
        list.push(e);
        const k = e.x * 65536 + e.y;
        if (!cells.has(k)) cells.set(k, []);
        cells.get(k).push(e);
      }
      const out = new Map();
      const push = (key, x, y, z, rot = 0) => { if (!out.has(key)) out.set(key, []); out.get(key).push(x, z, y, rot); };
      // palha solta: pontos da art deitados no chao antes dos conjuntos (pares de palha viravam plantacao);
      // a malha do conversor e uma placa em pe, quase invisivel de cima
      for (const e of list) if (!e.used && FLOOR.test(byHex[hexOf(e.g)].name || '')) { e.used = true; push('F' + e.g, e.x, e.y, e.z); }
      for (const e of list) {                                  // 1a passada: conjuntos a partir da ancora
        if (e.used || !byAnchor.has(e.g)) continue;
        for (const si of byAnchor.get(e.g)) {
          const { st, cx, cy, rot = 0, src = si, skip } = SETS[si], p0 = st.pieces[0], hit = [e];
          if (skip) continue;
          for (let j = 1; j < st.pieces.length; j++) {
            const p = st.pieces[j], id = parseInt(p.id, 16), z = e.z + p.dz - p0.dz;
            const f = (cells.get((e.x + p.dx - p0.dx) * 65536 + e.y + p.dy - p0.dy) || [])
              .find(o => !o.used && o.g === id && Math.abs(o.z - z) <= 1 && !hit.includes(o));
            if (!f) break;
            hit.push(f);
          }
          if (hit.length < st.pieces.length) continue;
          hit.forEach(o => o.used = true);
          push('s' + src, e.x - p0.dx + cx + .5, e.y - p0.dy + cy + .5, e.z - p0.dz, rot);
          break;
        }
      }
      // arvores: tronco e folhas do mesmo tile viram uma arvore so, da altura da malha do conversor (a art)
      for (const e of list) {
        if (e.used || !TRUNK.test(byHex[hexOf(e.g)].name || '') || byHex[hexOf(e.g)].cat !== 'vegetation') continue;
        const l = (cells.get(e.x * 65536 + e.y) || []).find(o => !o.used && Math.abs(o.z - e.z) <= 1 && LEAVES.test(byHex[hexOf(o.g)].name || ''));
        const top = Math.max(...[e, l].filter(Boolean).map(o => sprBox ? sprBox[o.s * SB + 4] : 20));
        e.used = true;
        if (l) l.used = true;
        push(`T${e.g},${l ? l.g : 0},${Math.round(top)}`, e.x + .5, e.y + .5, e.z);
      }
      // 2a: pecas avulsas; objeto pequeno fica no centro da pegada da malha (varios por tile, encostados na parede...)
      const cl = v => Math.min(.85, Math.max(.15, v));
      for (const e of list) {
        if (e.used) continue;
        const b = sprBox && sprBox.subarray(e.s * SB, e.s * SB + SB), small = b && b[1] - b[0] < .8 && b[3] - b[2] < .8;
        push('g' + e.g, e.x + (small ? cl((b[0] + b[1]) / 2) : .5), e.y + (small ? cl((b[2] + b[3]) / 2) : .5), e.z);
      }
      for (const k of place.keys()) if (!out.has(k)) out.set(k, []);
      place = out;
      for (const k of out.keys()) {
        if (models.has(k)) apply(k);
        else if (!queue.includes(k) && out.get(k).length) queue.push(k);
      }
    },
    keepData,
    // monta modelos pendentes ate estourar o orcamento (ms) do quadro
    tick(budget) {
      const t0 = performance.now();
      while (queue.length && performance.now() - t0 < budget) {
        const k = queue.shift();
        models.set(k, build(k));
        apply(k);
      }
    },
    // proj/view: matrizes coluna-maior do viewer (vista 2D: proj = vp e view = identidade)
    render({ proj, view, w, h, zScale, sunDir, fogColor, fogNear, fogFar }) {
      root.scale.y = zScale / ZU;
      sun.position.set(...sunDir);
      cam.projectionMatrix.fromArray(proj);
      cam.projectionMatrixInverse.copy(cam.projectionMatrix).invert();
      cam.matrix.fromArray(view).invert();
      cam.matrixWorldNeedsUpdate = true;
      if (fogFar) { fog.color.setRGB(...fogColor, THREE.SRGBColorSpace); fog.near = fogNear; fog.far = fogFar; scene.fog = fog; }
      else scene.fog = null;
      renderer.resetState();
      renderer.setViewport(0, 0, w, h);
      renderer.render(scene, cam);
      restore();
    },
    stats() {
      let inst = 0;
      for (const v of place.values()) inst += v.length / PS;
      return { inst, models: models.size, queue: queue.length, missing };
    },
  };
}
