// Texturas procedurais (cor + relevo + rugosidade) geradas em canvas. Sem arquivos de imagem.
import * as THREE from 'three';

// ---- ruido de valor determinista
function rng(seed) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}
function makeNoise(seed, n = 256) {
  const r = rng(seed), g = new Float32Array(n * n);
  for (let i = 0; i < g.length; i++) g[i] = r();
  const sm = t => t * t * (3 - 2 * t);
  // periodico: cobre a textura sem emenda
  return (x, y, period) => {
    const fx = x * period, fy = y * period;
    const x0 = Math.floor(fx), y0 = Math.floor(fy), tx = sm(fx - x0), ty = sm(fy - y0);
    const w = (a, b) => g[(((b % period) + period) % period * 7 + ((a % period) + period) % period * 13) % g.length];
    const a = w(x0, y0), b = w(x0 + 1, y0), c = w(x0, y0 + 1), d = w(x0 + 1, y0 + 1);
    return a + (b - a) * tx + (c - a) * ty + (a - b - c + d) * tx * ty;
  };
}
function fbm(noise, x, y, base, oct = 4) {
  let v = 0, a = .5, p = base;
  for (let i = 0; i < oct; i++, p *= 2, a *= .5) v += a * noise(x, y, p);
  return v;
}
const hex = c => [(c >> 16) & 255, (c >> 8) & 255, c & 255];
const mix = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];

export const TEX = { size: 512 };
function finish(size, fn, { repeat = 1 } = {}) {
  size = Math.min(size, TEX.size);
  // fn(x,y) -> {c:[r,g,b], h:0..1, r:0..1}
  const mk = () => { const c = document.createElement('canvas'); c.width = c.height = size; return c; };
  const cc = mk(), cb = mk(), cr = mk();
  const ic = cc.getContext('2d').createImageData(size, size);
  const ib = cb.getContext('2d').createImageData(size, size);
  const ir = cr.getContext('2d').createImageData(size, size);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const o = (y * size + x) * 4, v = fn(x / size, y / size);
    ic.data.set([v.c[0], v.c[1], v.c[2], 255], o);
    const h = Math.max(0, Math.min(1, v.h)) * 255;
    ib.data.set([h, h, h, 255], o);
    const r = Math.max(0, Math.min(1, v.r)) * 255;
    ir.data.set([0, r, 0, 255], o);
  }
  cc.getContext('2d').putImageData(ic, 0, 0);
  cb.getContext('2d').putImageData(ib, 0, 0);
  cr.getContext('2d').putImageData(ir, 0, 0);
  const tex = (cv, srgb) => {
    const t = new THREE.CanvasTexture(cv);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.anisotropy = 8;
    t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
    return t;
  };
  return { map: tex(cc, true), bumpMap: tex(cb, false), roughnessMap: tex(cr, false) };
}

// ---- materiais
// cor do sprite aplicada aos modelos-modelo: multiplicador por canal sobre as cores base de wood()/stone()
export const OVR = { wood: null, stone: null };
const ovr = (c, k) => (k ? [Math.min(255, c[0] * k[0]), Math.min(255, c[1] * k[1]), Math.min(255, c[2] * k[2])] : c);

export function wood({ base = 0x8a5a32, dark = 0x4d2f18, seed = 1, planks = 4, rough = .62, bump = 1 } = {}) {
  const n = makeNoise(seed), n2 = makeNoise(seed + 9);
  const b = ovr(hex(base), OVR.wood), d = ovr(hex(dark), OVR.wood);
  const t = finish(512, (x, y) => {
    const p = Math.floor(x * planks), px = x * planks - p;
    const shade = .9 + .1 * Math.sin(p * 12.9898 + seed * 3.1);
    // veios: ruido esticado ao longo de y, deformado por ruido lento
    const warp = fbm(n2, x, y, 3, 2) * 2.2;
    const rings = Math.sin((x * planks * 9 + warp * 5 + fbm(n, x * .3 + p, y, 2, 3) * 4) * Math.PI * 2 / 1.4);
    const fiber = fbm(n, x * 40 % 1, y * 2 % 1, 8, 3);
    let k = .5 + .22 * rings + .5 * (fiber - .5);
    k = Math.max(0, Math.min(1, k));
    const gap = px < .018 || px > .982;          // junta entre tabuas
    const c = mix(b, d, k * .75);
    const f = gap ? .35 : shade;
    return { c: [c[0] * f, c[1] * f, c[2] * f], h: gap ? 0 : .55 + .3 * (fiber - .5) + .1 * rings, r: rough + .15 * fiber };
  });
  return kind(mat(t, { metalness: 0, bump: .9 * bump, rough: 1 }), 'wood');
}

export function fabric({ base = 0x8a2f3a, alt = 0xa8434e, weave = 90, seed = 4, rough = .85 } = {}) {
  const n = makeNoise(seed);
  const b = hex(base), a = hex(alt);
  const t = finish(512, (x, y) => {
    const u = Math.sin(x * weave * Math.PI * 2), v = Math.sin(y * weave * Math.PI * 2);
    const w = (u * v + 1) / 2;
    const f = fbm(n, x, y, 4, 4);
    const c = mix(b, a, Math.max(0, Math.min(1, .35 * w + 1.1 * (f - .4))));
    const fold = .9 + .2 * fbm(n, x, y, 2, 2);
    return { c: [c[0] * fold, c[1] * fold, c[2] * fold], h: .5 + .35 * w, r: rough };
  });
  return kind(mat(t, { metalness: 0, bump: .5, rough: 1 }), 'fabric');
}

export function stone({ base = 0x9a9a94, dark = 0x5e5e5a, seed = 7, rough = .9 } = {}) {
  const n = makeNoise(seed), n2 = makeNoise(seed + 5);
  const b = ovr(hex(base), OVR.stone), d = ovr(hex(dark), OVR.stone);
  const t = finish(512, (x, y) => {
    const f = fbm(n, x, y, 4, 5), g = fbm(n2, x, y, 12, 3);
    // veias e pequenas rachaduras
    const vein = Math.abs(fbm(n2, x, y, 3, 3) - .5) < .012 ? 1 : 0;
    const c = mix(b, d, Math.max(0, Math.min(1, (f - .3) * 1.6 + vein * .6)));
    const gr = .94 + .12 * g;
    return { c: [c[0] * gr, c[1] * gr, c[2] * gr], h: .45 + .45 * f - vein * .3, r: rough };
  });
  return kind(mat(t, { metalness: 0, bump: 1.4, rough: 1 }), 'stone');
}

export function iron({ base = 0x4a4d52, seed = 11 } = {}) {
  const n = makeNoise(seed);
  const b = hex(base);
  const t = finish(256, (x, y) => {
    const f = fbm(n, x, y, 6, 4);
    const brush = fbm(n, x * 30 % 1, y, 8, 2);
    const rust = Math.max(0, f - .6) * 2.2;
    const c = mix(b, [120, 70, 40], rust);
    const k = .85 + .3 * brush;
    return { c: [c[0] * k, c[1] * k, c[2] * k], h: .5 + .3 * f, r: .38 + .3 * rust + .1 * brush };
  });
  return kind(mat(t, { metalness: .85, bump: .6, rough: 1 }), 'metal');
}

export function gold({ base = 0xc79a3a } = {}) {
  return new THREE.MeshStandardMaterial({ color: base, metalness: .9, roughness: .3 });
}

function kind(m, k) { m.userData.kind = k; return m; }
function mat(t, { metalness, bump, rough }) {
  const m = new THREE.MeshStandardMaterial({
    map: t.map, bumpMap: t.bumpMap, bumpScale: bump, roughnessMap: t.roughnessMap,
    roughness: rough, metalness,
  });
  return m;
}

// ---- texturas extras e materiais tingidos (textura cinza cacheada x cor do sprite)
export function brick({ seed = 81 } = {}) {
  const n = makeNoise(seed);
  const t = finish(512, (x, y) => {
    const rows = 8, cols = 4, r = Math.floor(y * rows), fx = (x * cols + (r % 2) * .5) % 1, fy = (y * rows) % 1;
    const mortar = fx < .06 || fy < .1;
    const cid = Math.floor(x * cols + (r % 2) * .5) + r * 7;
    const v = .8 + .2 * Math.sin(cid * 12.9898) + .15 * (fbm(n, x, y, 8, 3) - .5);
    const g = mortar ? 150 : 205 * v;
    return { c: [g, g, g], h: mortar ? .1 : .6 + .3 * fbm(n, x, y, 16, 2), r: .9 };
  });
  return mat(t, { metalness: 0, bump: 1.6, rough: 1 });
}
export function shingle({ seed = 91 } = {}) {
  const n = makeNoise(seed);
  const t = finish(512, (x, y) => {
    const rows = 8, r = Math.floor(y * rows), fy = (y * rows) % 1, cols = 6;
    const fx = (x * cols + (r % 2) * .5) % 1;
    const edge = Math.max(0, (fy - .75) * 4) + (fx < .04 ? 1 : 0);
    const v = .85 + .15 * Math.sin((Math.floor(x * cols + (r % 2) * .5) + r * 5) * 7.3) + .1 * (fbm(n, x, y, 8, 2) - .5);
    const g = 215 * v * (1 - .45 * Math.min(1, edge));
    return { c: [g, g, g], h: .8 - .6 * Math.min(1, edge), r: .85 };
  });
  return mat(t, { metalness: 0, bump: 1.2, rough: 1 });
}
export function leather({ seed = 101 } = {}) {
  const n = makeNoise(seed);
  const t = finish(256, (x, y) => {
    const f = fbm(n, x, y, 20, 3), g = fbm(n, x, y, 6, 3);
    const v = 200 * (.8 + .3 * f) * (.9 + .2 * g);
    return { c: [v, v, v], h: .4 + .5 * f, r: .55 + .2 * g };
  });
  return mat(t, { metalness: 0, bump: .8, rough: 1 });
}
export function tiles({ seed = 111 } = {}) {
  const n = makeNoise(seed);
  const t = finish(512, (x, y) => {
    const cells = 4, fx = (x * cells) % 1, fy = (y * cells) % 1;
    const joint = fx < .035 || fy < .035;
    const cid = Math.floor(x * cells) * 5 + Math.floor(y * cells) * 11;
    const v = .85 + .12 * Math.sin(cid * 3.7) + .2 * (fbm(n, x, y, 8, 4) - .5);
    const g = joint ? 120 : 215 * v;
    return { c: [g, g, g], h: joint ? .1 : .6 + .2 * fbm(n, x, y, 16, 2), r: .8 };
  });
  return mat(t, { metalness: 0, bump: 1.2, rough: 1 });
}
export function noisy({ seed = 121, freq = 6, contrast = .5 } = {}) {      // terra, grama, folhagem
  const n = makeNoise(seed);
  const t = finish(256, (x, y) => {
    const f = fbm(n, x, y, freq, 5), g = fbm(n, x, y, freq * 6, 2);
    const v = 215 * (1 - contrast + contrast * (.4 * f + .6 * g) * 1.6);
    return { c: [v, v, v], h: .3 + .6 * g, r: .95 };
  });
  return mat(t, { metalness: 0, bump: .7, rough: 1 });
}

const GRAY = {};
const MAKERS = {
  wood: () => wood({ base: 0xf0f0f0, dark: 0x9a9a9a, seed: 5, planks: 4 }),
  stone: () => stone({ base: 0xf2f2f2, dark: 0x9c9c9c }),
  metal: () => iron({ base: 0xffffff }),
  fabric: () => fabric({ base: 0xe8e8e8, alt: 0xffffff }),
  brick, shingle, leather, tiles, noisy,
  plain: () => null,
};
const BOOST = { wood: 1.35, stone: 1.2, metal: 1.0, fabric: 1.15, brick: 1.25, shingle: 1.25, leather: 1.4, tiles: 1.2, noisy: 1.2 };
export function tinted(type, hex, o = {}) {
  const c = new THREE.Color(hex);
  const k = BOOST[type] || 1;
  c.setRGB(Math.min(1, c.r * k), Math.min(1, c.g * k), Math.min(1, c.b * k));
  let src = GRAY[type];
  if (src === undefined) {                 // textura cinza neutra: nunca tingida pelo override do modelo-modelo
    const sv = { ...OVR }; OVR.wood = OVR.stone = null;
    try { src = GRAY[type] = (MAKERS[type] || MAKERS.plain)(); } finally { Object.assign(OVR, sv); }
  }
  const m = new THREE.MeshStandardMaterial({
    color: c, roughness: o.rough ?? (type === 'metal' ? 1 : .8), metalness: o.metal ?? (type === 'metal' ? .85 : 0),
    side: o.side || THREE.FrontSide, transparent: !!o.opacity, opacity: o.opacity ?? 1,
    emissive: o.emissive ? new THREE.Color(o.emissive) : 0x000000, emissiveIntensity: o.emissive ? (o.ei ?? 1) : 0,
  });
  m.userData.kind = type;
  if (src) {
    m.map = src.map; m.bumpMap = src.bumpMap; m.bumpScale = (o.bump ?? src.bumpScale);
    if (type === 'metal') m.roughnessMap = src.roughnessMap;
  }
  return m;
}
