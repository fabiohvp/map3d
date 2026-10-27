// Gera items/data/proc_meshes.bin + proc_meshes.json: o modelo procedural (gen.js) de cada item achatado em triangulos soltos
// no referencial do tile (x, z = pegada em tiles, y = altura em tiles), com um indice de material por vertice e a cor media
// de cada material. Quem consome (tools/convert.py) monta uma textura de celulas de cor para cada item.
// Uso: python items/serve.py  ->  abrir http://localhost:8087/items/bake.html  (grava sozinho via POST /save)
import * as THREE from 'three';
import { buildOne, setMode } from './gen.js';
import { TEX } from './textures.js';

TEX.size = 64;
setMode('proc');
const log = document.getElementById('log');
const D = await (await fetch('data/items.json')).json();
const MAXV = 3072;
const cv = document.createElement('canvas'); cv.width = cv.height = 1;
const cx = cv.getContext('2d', { willReadFrequently: true });
const meanCache = new Map();

function matColor(m) {
  let k = 1, r = 1, g = 1, b = 1;
  if (m.map && m.map.image) {
    let t = meanCache.get(m.map.uuid);
    if (!t) { cx.clearRect(0, 0, 1, 1); cx.drawImage(m.map.image, 0, 0, 1, 1); const d = cx.getImageData(0, 0, 1, 1).data; t = [d[0] / 255, d[1] / 255, d[2] / 255]; meanCache.set(m.map.uuid, t); }
    [r, g, b] = t.map(v => v ** 2.2 * 1.25);   // map em sRGB, cor do material linear; o viewer sombreia de novo
  }
  const c = m.color.clone();
  let rgb = [c.r * r, c.g * g, c.b * b];
  if (m.emissive && m.emissiveIntensity) rgb = rgb.map((v, i) => v + [m.emissive.r, m.emissive.g, m.emissive.b][i] * m.emissiveIntensity * .6);
  const out = new THREE.Color(rgb[0], rgb[1], rgb[2]).convertLinearToSRGB();
  return [out.r, out.g, out.b].map(v => Math.max(0, Math.min(255, Math.round(v * 255))));
}

const index = {}, chunks = [];
let off = 0, ok = 0, big = 0, fail = 0;
const tex = new THREE.Texture();
const v = new THREE.Vector3(), nm = new THREE.Matrix3();
for (let n = 0; n < D.items.length; n++) {
  const it = D.items[n];
  if (it.sub === 'roof') continue;
  try {
    const g = buildOne(it, tex);
    g.updateMatrixWorld(true);
    const pos = [], nrm = [], mat = [], cols = [], colIdx = new Map();
    g.traverse(o => {
      if (!o.isMesh) return;
      const geo = o.geometry, P = geo.attributes.position, N = geo.attributes.normal, I = geo.index;
      const mats = Array.isArray(o.material) ? o.material : [o.material];
      nm.getNormalMatrix(o.matrixWorld);
      const groups = geo.groups.length ? geo.groups : [{ start: 0, count: I ? I.count : P.count, materialIndex: 0 }];
      for (const gr of groups) {
        const m = mats[gr.materialIndex] || mats[0];
        const c = matColor(m), key = c.join(',');
        if (!colIdx.has(key)) { colIdx.set(key, cols.length / 3); cols.push(...c); }
        const mi = colIdx.get(key);
        for (let i = gr.start; i < gr.start + gr.count; i++) {
          const k = I ? I.getX(i) : i;
          v.fromBufferAttribute(P, k).applyMatrix4(o.matrixWorld);
          pos.push(v.x, v.y, v.z);
          v.fromBufferAttribute(N, k).applyMatrix3(nm).normalize();
          nrm.push(v.x, v.y, v.z);
          mat.push(mi);
        }
      }
    });
    const nv = pos.length / 3;
    if (!nv) continue;
    if (nv > MAXV || colIdx.size > 255) { big++; continue; }
    // descarta o que nao e finito
    if (pos.some(x => !isFinite(x))) { fail++; continue; }
    const nc = cols.length / 3;
    const sz = nv * 12 + nv * 4 + Math.ceil(nv / 4) * 4 + nc * 4;
    const buf = new ArrayBuffer(sz), dv = new DataView(buf);
    new Float32Array(buf, 0, nv * 3).set(pos);
    const n8 = new Int8Array(buf, nv * 12, nv * 4);
    for (let i = 0; i < nv; i++) for (let j = 0; j < 3; j++) n8[i * 4 + j] = Math.round(nrm[i * 3 + j] * 127);
    new Uint8Array(buf, nv * 16, nv).set(mat);
    const cb = new Uint8Array(buf, nv * 16 + Math.ceil(nv / 4) * 4, nc * 4);
    for (let i = 0; i < nc; i++) cb.set([cols[i * 3], cols[i * 3 + 1], cols[i * 3 + 2], 255], i * 4);
    index[it.hex] = { o: off, nv, nc };
    chunks.push(new Uint8Array(buf)); off += sz; ok++;
  } catch (e) { fail++; console.warn(it.hex, it.name, e); }
  if (n % 400 === 0) { log.textContent = `${n}/${D.items.length} ok ${ok} grandes ${big} falhas ${fail}`; await new Promise(r => setTimeout(r)); }
}
const blob = new Blob(chunks);
await fetch('/save?name=proc_meshes.bin', { method: 'POST', body: blob });
await fetch('/save?name=proc_meshes.json', { method: 'POST', body: JSON.stringify(index) });
log.textContent = `pronto: ${ok} modelos (${(off / 1e6).toFixed(1)} MB), ${big} acima de ${MAXV} vertices, ${fail} falhas`;
document.title = 'bake pronto';
