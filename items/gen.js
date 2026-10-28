// Gerador automatico de modelos 3D: categoria/subcategoria do taxonomy + nome + paleta do sprite -> malha procedural.
// Unidades: 1 tile = 1, y para cima, origem no centro da pegada.
import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { mergeVertices } from 'three/addons/utils/BufferGeometryUtils.js';
import { tinted, OVR } from './textures.js';
import { box, soft, lathe, sphere, ring, place, turnedLeg, barrel as hmBarrel, crate as hmCrate, bench as hmBench, tableOne, chairOne, stoneTable, stoneBench,
  bed as hmBed, canopyBed, counter as hmCounter, longTable } from './models.js';

const STONEY = /stone|marble|granite|rock|brick|plaster|wall|floor|post|column|pillar|stair|arch|wood|sand|slate|cobble|statue/;
const hexLum = h =>{ const c = new THREE.Color(h); return .3 * c.r + .59 * c.g + .11 * c.b; };
const mkRng = seed => { let s = (seed * 2654435761) >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); };
const shade = (hex, k) => { const c = new THREE.Color(hex); c.multiplyScalar(k); return '#' + c.getHexString(); };
const has = (n, rx) => rx.test(n);

// contexto de um item: dimensoes aproximadas a partir do sprite + cores
function ctx(it) {
  const fw = Math.max(.14, Math.min(2.4, it.w * .9 / 44));
  const H = Math.max(.05, Math.min(3.2, (it.hp - 14) / 46));
  const pal = it.pal.slice();
  const bySat = [...pal].sort((a, b) => hexLum(b) - hexLum(a));
  const st = CUR || styleOf(it);
  // sprite muito escuro (sombra do desenho): o modelo usa o tom mais claro da paleta para nao virar um bloco preto
  const c0 = hexLum(st.frame) < .16 && hexLum(bySat[0]) > hexLum(st.frame) ? bySat[0] : st.frame;
  return { it, n: (it.name || '').toLowerCase(), fw, fd: fw, H, c0, c1: st.accent || pal[1] || pal[0], c2: pal[2] || pal[0],
    light: bySat[0], dark: bySat[bySat.length - 1], r: mkRng(it.id + 7), flags: it.flags || [] };
}
let CUR = null;       // estilo do item em construcao (material: madeira/pedra viram metal/ouro quando o sprite e assim)
const M = (t, c, o) => (CUR && CUR.metal && (t === 'wood' || t === 'stone') ? tinted('metal', c, { rough: .32, metal: .9, ...(o && o.side ? { side: o.side } : {}) }) : tinted(t, c, o));
const ironC = '#8d939a';
const brassC = '#c9a24a';
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const UP = new THREE.Vector3(0, 1, 0);
const hslOf = hx => { const o = {}; new THREE.Color(hx).getHSL(o, THREE.SRGBColorSpace); return o; };
// cor de folhagem da paleta (matiz verde), ou null
function greenOf(pal) { return pal.find(hx => { const o = hslOf(hx); return o.h > .16 && o.h < .45 && o.s > .12 && o.l > .1 && o.l < .7; }) || null; }

// bolha organica (copa, moita, pedra lisa): icosaedro deformado por ruido continuo na posicao, vertices soldados (sombra suave)
function blob(g, r, mat, x, y, z, seed = 0, flat = .85) {
  let geo = new THREE.IcosahedronGeometry(r, 3);
  geo.deleteAttribute('normal');
  geo = mergeVertices(geo);
  const p = geo.attributes.position;
  for (let i = 0; i < p.count; i++) {
    const X = p.getX(i) / r, Y = p.getY(i) / r, Z = p.getZ(i) / r;
    const k = 1 + .12 * Math.sin(X * 5.1 + seed) * Math.cos(Z * 4.3 + seed * .7) + .1 * Math.sin(Y * 7.7 + X * 3 + seed * 1.3);
    p.setXYZ(i, p.getX(i) * k, p.getY(i) * k * flat, p.getZ(i) * k);
  }
  geo.computeVertexNormals();
  const m = place(new THREE.Mesh(geo, mat), x, y, z);
  g.add(m);
  return m;
}
// galho/raiz/haste: cilindro afunilado saindo de `from` na direcao `dir`
function limb(g, r0, r1, len, mat, from, dir, seg = 7) {
  const geo = new THREE.CylinderGeometry(r1, r0, len, seg);
  geo.translate(0, len / 2, 0);
  const m = place(new THREE.Mesh(geo, mat), from.x, from.y, from.z);
  m.quaternion.setFromUnitVectors(UP, dir.clone().normalize());
  g.add(m);
  return m;
}
// peca deitada no chao ao longo de x (cabo, lamina): cilindro com eixo x
function rod(g, r0, r1, len, mat, x, y, z, seg = 10) {
  const m = place(new THREE.Mesh(new THREE.CylinderGeometry(r1, r0, len, seg), mat), x, y, z);
  m.rotation.z = -Math.PI / 2;
  g.add(m);
  return m;
}

// ---------------------------------------------------------------- generico: bloco / cartao com o sprite
export function spriteCard(it, tex, w, h, y0 = 0) {
  const g = new THREE.Group();
  const m = new THREE.MeshStandardMaterial({ map: tex, transparent: true, alphaTest: .4, side: THREE.DoubleSide, roughness: 1 });
  const p = place(new THREE.Mesh(new THREE.PlaneGeometry(w, h), m), 0, y0 + h / 2, 0);
  g.add(p);
  return g;
}
function genericBlock(c) {
  const g = new THREE.Group();
  const m = M(has(c.n, /stone|rock|marble|statue/) ? 'stone' : 'wood', c.c0);
  box(g, Math.min(c.fw, 1.2), Math.max(.1, c.H * .8), Math.min(c.fd, 1.2), m, 0, 0, 0);
  return g;
}

// ---------------------------------------------------------------- arquitetura
const ARCH = {
  // parede: rodape saliente, corpo, cinta de pedra no meio e capeamento em dois degraus; madeira ganha montantes e travessa
  wall(c) {
    const g = new THREE.Group();
    const t = has(c.n, /brick/) ? 'brick' : has(c.n, /plaster|board|wood|log|plank/) ? 'wood' : 'stone';
    const m = M(t, c.c0), dk = M('stone', shade(c.c0, .72)), cap = M('stone', shade(c.c0, .85));
    const h = Math.max(.9, Math.min(2.6, c.H * 1.1));
    const run = (L, D, x, z, alongX) => {
      const B = (w, hh, d, mat, y) => alongX ? box(g, w, hh, d, mat, x, y, z) : box(g, d, hh, w, mat, x, y, z);
      B(L + .02, .14, D + .06, dk, 0);
      B(L, h - .2, D, m, .14);
      if (t === 'wood') {
        for (const k of [-.5, 0, .5]) (alongX ? box(g, .08, h - .2, D + .03, M('wood', shade(c.c0, .6)), x + k * (L - .08), .14, z) : box(g, D + .03, h - .2, .08, M('wood', shade(c.c0, .6)), x, .14, z + k * (L - .08)));
        B(L, .08, D + .03, M('wood', shade(c.c0, .6)), h * .55);
      } else if (h > 1.4) B(L + .01, .06, D + .025, cap, h * .5);
      B(L + .04, .04, D + .08, dk, h - .06);
      B(L + .02, .04, D + .04, cap, h - .1);
    };
    if (has(c.n, /corner/)) { run(1, .22, -.39, 0, false); run(.78, .22, .11, -.39, true); }
    else run(1, .22, 0, 0, true);
    return g;
  },
  floor(c) {
    const g = new THREE.Group();
    const t = has(c.n, /plank|wood|board/) ? 'wood' : has(c.n, /cobble|flag|stone|marble|tile|pave/) ? 'tiles' : 'tiles';
    box(g, 1, .06, 1, M(t, c.c0), 0, 0, 0);
    return g;
  },
  roof(c) {
    const g = new THREE.Group();
    const s = new THREE.Shape(); s.moveTo(-.5, 0); s.lineTo(.5, 0); s.lineTo(0, .55); s.closePath();
    const geo = new THREE.ExtrudeGeometry(s, { depth: 1, bevelEnabled: false });
    geo.translate(0, 0, -.5);
    const uv = geo.attributes.uv; for (let i = 0; i < uv.count; i++) uv.setXY(i, uv.getX(i) * 2, uv.getY(i) * 2);
    g.add(place(new THREE.Mesh(geo, M(has(c.n, /thatch/) ? 'noisy' : 'shingle', c.c0)), 0, 0, 0));
    box(g, .08, .06, 1.04, M('wood', shade(c.c0, .6)), 0, .52, 0);                 // cumeeira
    return g;
  },
  // escada: degraus com focinho saliente e banzos laterais
  stairs(c) {
    const g = new THREE.Group(), wood = has(c.n, /wood/), m = M(wood ? 'wood' : 'stone', c.c0), dk = M(wood ? 'wood' : 'stone', shade(c.c0, .75)), n = 5;
    for (let i = 0; i < n; i++) {
      const z = -.5 + (i + .5) / n, y = .16 * (i + 1);
      box(g, .92, y - .03, 1 / n, dk, 0, 0, z);
      box(g, .92, .035, 1 / n + .03, m, 0, y - .035, z + .015);
    }
    for (const s of [-1, 1]) {                                                       // banzo: faixa inclinada acompanhando os degraus
      const sh = new THREE.Shape(); sh.moveTo(-.5, 0); sh.lineTo(-.3, 0); sh.lineTo(.5, .68); sh.lineTo(.5, .86); sh.lineTo(.42, .86); sh.lineTo(-.5, .12); sh.closePath();
      const sg = place(new THREE.Mesh(new THREE.ExtrudeGeometry(sh, { depth: .04, bevelEnabled: false }), dk), s * .48 + (s > 0 ? .04 : 0), 0, 0); sg.rotation.y = -Math.PI / 2; g.add(sg);
    }
    return g;
  },
  // arco: pilares com base e impostas, aduelas em leque e pedra de fecho saliente
  arch(c) {
    const g = new THREE.Group(), m = M('stone', c.c0), dk = M('stone', shade(c.c0, .8));
    for (const s of [-1, 1]) { box(g, .26, .12, .3, dk, s * .39, 0, 0); box(g, .22, 1.38, .26, m, s * .39, .12, 0); box(g, .28, .08, .32, dk, s * .39, 1.42, 0); }
    const n = 9;
    for (let i = 0; i < n; i++) {
      const a0 = Math.PI * i / n + .01, a1 = Math.PI * (i + 1) / n - .01;
      const ring2 = new THREE.Shape(); ring2.absarc(0, 0, .5, a0, a1, false); ring2.absarc(0, 0, .3, a1, a0, true);
      const v = place(new THREE.Mesh(new THREE.ExtrudeGeometry(ring2, { depth: .26, bevelEnabled: false }), i === (n >> 1) ? dk : m), 0, 1.5, -.13);
      if (i === (n >> 1)) v.scale.set(1.08, 1.08, 1.1);
      g.add(v);
    }
    return g;
  },
  // janela: peitoril, verga, caixilho com travessas de chumbo, vidro, e postigos abertos
  window(c) {
    const g = new THREE.Group(), fr = M('wood', c.c0), st = M('stone', shade(c.c0, .9)), gl = M('plain', '#9fc4d8', { opacity: .35, rough: .1 });
    const w = .8, h = 1, y0 = .55, lead = M('metal', '#3a3d42', { rough: .5 });
    box(g, 1, y0 - .05, .2, st, 0, 0, 0);
    box(g, w + .2, .06, .3, st, 0, y0 - .06, .04);                                    // peitoril
    box(g, w + .2, .12, .22, st, 0, y0 + h, 0);                                       // verga
    box(g, w, .07, .12, fr, 0, y0 + h - .07, 0); box(g, w, .07, .12, fr, 0, y0, 0);
    box(g, .07, h, .12, fr, -w / 2 + .035, y0, 0); box(g, .07, h, .12, fr, w / 2 - .035, y0, 0);
    box(g, .04, h - .1, .08, fr, 0, y0 + .05, 0); box(g, w - .1, .04, .08, fr, 0, y0 + h / 2, 0);
    for (let i = 1; i < 4; i++) { box(g, w - .1, .008, .02, lead, 0, y0 + i * h / 4, 0); box(g, .008, h - .1, .02, lead, -w / 2 + i * w / 4, y0 + .05, 0); }
    g.add(place(new THREE.Mesh(new THREE.PlaneGeometry(w - .1, h - .1), gl), 0, y0 + h / 2, 0));
    for (const s of [-1, 1]) {
      const sh = new THREE.Group(); sh.position.set(s * (w / 2 + .02), y0, .08); sh.rotation.y = s * -1.2; g.add(sh);
      for (let i = 0; i < 3; i++) box(sh, .12, h - .04, .03, M('wood', shade(c.c0, .85 + i * .06)), s * (.07 + i * .13), .02, 0);
      box(sh, .38, .06, .035, M('wood', shade(c.c0, .7)), s * .2, h * .25, .01); box(sh, .38, .06, .035, M('wood', shade(c.c0, .7)), s * .2, h * .7, .01);
    }
    return g;
  },
  // coluna classica: plinto, toro, fuste com caneluras, colarinho, capitel e abaco
  column(c) {
    const g = new THREE.Group(), m = M('stone', c.c0), dk = M('stone', shade(c.c0, .85)), h = Math.max(1, Math.min(2.6, c.H));
    box(g, .64, .1, .64, dk, 0, 0, 0);
    lathe(g, [[.001, .1], [.3, .1], [.31, .14], [.26, .2], [.21, .22], [.2, .26], [.001, .26]], m, 0, 0, 0, 28);
    lathe(g, [[.001, .26], [.2, .26], [.18, h * .5], [.165, h - .3], [.001, h - .3]], m, 0, 0, 0, 28);
    for (let i = 0; i < 12; i++) { const a = i / 12 * 6.28; limb(g, .012, .01, h - .6, dk, new THREE.Vector3(Math.cos(a) * .18, .28, Math.sin(a) * .18), new THREE.Vector3(Math.cos(a) * -.03, 1, Math.sin(a) * -.03), 4); }
    lathe(g, [[.001, h - .3], [.18, h - .3], [.19, h - .27], [.18, h - .25], [.24, h - .14], [.28, h - .1], [.001, h - .1]], m, 0, 0, 0, 28);
    box(g, .62, .1, .62, dk, 0, h - .1, 0);
    return g;
  },
  // porta: batente e verga, tabuas verticais com juntas, travessas, dobradicas de ferro em "T", argola e espelho
  door(c) {
    const g = new THREE.Group(), fr = M('wood', shade(c.c0, .75)), pn = M('wood', c.c0), fe = M('metal', '#3a3d42', { rough: .5 });
    const h = 1.75, w = .85, n = 5;
    if (has(c.n, /portcullis|\bgate\b|\bbars\b|grate/)) {                            // grade de ferro com pontas
      for (let i = 0; i < 7; i++) { const x = -w / 2 + .06 + i * (w - .12) / 6; box(g, .035, h - .1, .035, fe, x, 0, 0); g.add(place(new THREE.Mesh(new THREE.ConeGeometry(.03, .1, 4), fe), x, h - .05, 0)); }
      for (const y of [.3, .9, 1.45]) box(g, w, .05, .05, fe, 0, y, 0);
      box(g, .1, h, .22, fr, -w / 2 - .05, 0, 0); box(g, .1, h, .22, fr, w / 2 + .05, 0, 0);
      return g;
    }
    box(g, .1, h, .22, fr, -w / 2 - .05, 0, 0); box(g, .1, h, .22, fr, w / 2 + .05, 0, 0); box(g, w + .2, .12, .22, fr, 0, h, 0);
    for (let i = 0; i < n; i++) box(g, w / n - .008, h - .02, .07, M('wood', shade(c.c0, .92 + (i % 2) * .1)), -w / 2 + (i + .5) * w / n, 0, 0);
    for (const y of [.25, h - .35]) box(g, w - .06, .1, .03, pn, 0, y, -.045);
    for (const y of [.3, h - .3]) { box(g, .5, .045, .02, fe, -w / 2 + .25, y, .045); sphere(g, .03, fe, -w / 2 + .05, y + .022, .05); }
    box(g, .1, .16, .015, fe, w / 2 - .14, .82, .042);
    const rg = place(new THREE.Mesh(new THREE.TorusGeometry(.045, .009, 6, 16), fe), w / 2 - .14, .82, .06); g.add(rg);
    return g;
  },
  // cerca: mouroes com ponta chanfrada, duas travessas e escora diagonal
  fence(c) {
    const g = new THREE.Group(), m = M('wood', c.c0), dk = M('wood', shade(c.c0, .8));
    for (const x of [-.45, .45]) { box(g, .09, .85, .09, m, x, 0, 0); g.add(place(new THREE.Mesh(new THREE.ConeGeometry(.066, .1, 4), m), x, .9, 0)).children.at(-1).rotation.y = Math.PI / 4; }
    for (const y of [.28, .62]) box(g, 1, .07, .04, dk, 0, y, .045);
    const br = box(g, .05, 1.0, .03, dk, 0, -.05, .045).children.at(-1); br.rotation.z = .65; br.position.y = .48;
    return g;
  },
  bridge(c) {
    const g = new THREE.Group(), m = M('wood', c.c0);
    if (!has(c.n, /bridge|rail/)) {   // tabuas de piso/passadico: so as tabuas
      for (let i = 0; i < 5; i++) box(g, 1, .07, .19, M('wood', shade(c.c0, .9 + (i % 2) * .15)), 0, 0, -.4 + i * .2);
      return g;
    }
    box(g, 1, .08, 1, m, 0, 0, 0);
    for (const x of [-.46, .46]) { box(g, .07, .7, .07, m, x, 0, -.45); box(g, .07, .7, .07, m, x, 0, .45); box(g, .05, .06, 1, m, x, .55, 0); }
    return g;
  },
  sign(c) {
    const g = new THREE.Group(), m = M('wood', c.c0);
    box(g, .08, 1.3, .08, m, -.4, 0, 0); box(g, .8, .4, .06, m, 0, .85, 0);
    return g;
  },
};

// ---------------------------------------------------------------- terreno
const TERR = {
  water(c) { const g = new THREE.Group(); g.add(place(new THREE.Mesh(new THREE.BoxGeometry(1, .05, 1), M('plain', c.c0, { opacity: .8, rough: .1, metal: .3 })), 0, .025, 0)); return g; },
  lava(c) { const g = new THREE.Group(); box(g, 1, .06, 1, M('noisy', '#e0501a', { emissive: '#ff4a10', ei: 1.1 }), 0, 0, 0); return g; },
  ground(c) { const g = new THREE.Group(); box(g, 1, .08, 1, M('noisy', c.c0), 0, 0, 0); return g; },
};

// ---------------------------------------------------------------- vegetacao
const treeKind = n => /stump/.test(n) ? 'stump' : /palm|coconut|banana/.test(n) ? 'palm' : /dead|bare|burnt/.test(n) ? 'dead'
  : /cedar|pine|spruce|\bfir\b|cypress|conifer|yew|needles/.test(n) ? 'conifer' : 'leafy';
// arvore no estilo dos modelos a mao: tronco torneado com raizes, galhos e copa em bolhas; h = altura, spread = raio da copa
function treeModel({ h, spread = .5, leaf = '#3f7a3a', bark = '#6b4a2b', kind = 'leafy', seed = 1 }) {
  const g = new THREE.Group(), r = mkRng(seed), R = .05 + h * .035, bm = M('wood', shade(bark, .72));
  if (kind === 'stump') {
    lathe(g, [[.001, 0], [R * 2.4, 0], [R * 1.7, .07], [R * 1.5, .3], [.001, .3]], bm, 0, 0, 0, 14);
    const top = place(new THREE.Mesh(new THREE.CircleGeometry(R * 1.45, 16), M('wood', shade(bark, 1.7))), 0, .302, 0);
    top.rotation.x = -Math.PI / 2; g.add(top);
    return g;
  }
  const th = kind === 'leafy' ? h * .7 : kind === 'conifer' ? h * .9 : h;
  lathe(g, [[.001, 0], [R * 1.9, 0], [R * 1.3, th * .06], [R, th * .18], [R * .8, th * .6], [R * .45, th], [.001, th]], bm, 0, 0, 0, 12);
  for (let i = 0; i < 5; i++) {                                                     // raizes aparentes
    const a = i / 5 * 6.28 + r();
    limb(g, R * .6, R * .2, R * 2, bm, new THREE.Vector3(Math.cos(a) * R * .7, R * 1.1, Math.sin(a) * R * .7), new THREE.Vector3(Math.cos(a), -.7, Math.sin(a)), 5);
  }
  const la = M('noisy', leaf), lb = M('noisy', shade(leaf, .76));
  if (kind === 'palm') {
    for (let i = 1; i < 7; i++) ring(g, R * (1 - i * .07) + .006, .012, M('wood', shade(bark, .8)), 0, th * i / 7, 0);
    for (let i = 0; i < 9; i++) {                                                   // folhas arqueadas
      const len = spread * 1.5, geo = new THREE.PlaneGeometry(len, .26, 10, 2), p = geo.attributes.position;
      for (let k = 0; k < p.count; k++) { const x = p.getX(k) + len / 2, w = p.getY(k) * (1 - x / len * .8); p.setXYZ(k, x, -(x * x) / len * .55, w); }
      geo.computeVertexNormals();
      const f = place(new THREE.Mesh(geo, M('noisy', i % 2 ? leaf : shade(leaf, .8), { side: THREE.DoubleSide })), 0, th, 0);
      f.rotation.set(0, i / 9 * 6.28 + r() * .3, .25 + r() * .2); g.add(f);
    }
    for (let i = 0; i < 3; i++) sphere(g, .05, M('plain', '#5a3b1c', { rough: .6 }), Math.cos(i * 2.1) * .07, th - .06, Math.sin(i * 2.1) * .07);
    return g;
  }
  if (kind === 'conifer') {
    const n = 7, lc = M('noisy', shade(leaf, 1.15));
    for (let i = 0; i < n; i++) {
      const t = i / n, rad = spread * (1.05 - t * .8), y = th * (.2 + t * .72);
      const geo = new THREE.ConeGeometry(rad, th * .26, 16, 3);
      const p = geo.attributes.position;                                            // galhos caidos: borda serrilhada e arqueada
      for (let k = 0; k < p.count; k++) {
        const rr = Math.hypot(p.getX(k), p.getZ(k)) / rad, s = 1 + .16 * Math.sin(Math.atan2(p.getZ(k), p.getX(k)) * 7 + i * 1.7) * rr;
        p.setX(k, p.getX(k) * s); p.setZ(k, p.getZ(k) * s); p.setY(k, p.getY(k) - rr * rr * th * .05);
      }
      geo.computeVertexNormals();
      g.add(place(new THREE.Mesh(geo, i === n - 1 ? lc : i % 2 ? la : lb), 0, y, 0));
    }
    return g;
  }
  // galhos principais
  const ends = [];
  const nb = kind === 'dead' ? 6 : 5;
  for (let i = 0; i < nb; i++) {
    const a = i / nb * 6.28 + r() * .8, y = th * (.55 + r() * .35), len = spread * (.6 + r() * .35);
    const dir = new THREE.Vector3(Math.cos(a), .55 + r() * .6, Math.sin(a)).normalize();
    limb(g, R * .5, R * .15, len, bm, new THREE.Vector3(0, y, 0), dir, 6);
    const end = new THREE.Vector3(0, y, 0).addScaledVector(dir, len);
    ends.push(end);
    if (kind === 'dead') limb(g, R * .2, R * .05, len * .5, bm, end, new THREE.Vector3(dir.x + r() - .5, .8, dir.z + r() - .5), 5);
  }
  if (kind === 'dead') return g;
  const lc = M('noisy', shade(leaf, 1.2));
  blob(g, spread * .78, lb, 0, th + spread * .3, 0, seed + 11);                       // miolo escuro da copa
  for (const [i, e] of ends.entries()) blob(g, spread * (.42 + r() * .14), i % 2 ? la : lb, e.x, e.y + spread * .1, e.z, seed + i);
  for (let i = 0; i < 7; i++) {                                                     // tufos de fora, os de cima mais claros
    const a = r() * 6.28, el = r() * 1.2 - .2, d = spread * (.55 + r() * .25);
    const y = th + spread * .35 + Math.sin(el) * d;
    blob(g, spread * (.3 + r() * .14), el > .5 ? lc : la, Math.cos(a) * Math.cos(el) * d, y, Math.sin(a) * Math.cos(el) * d, seed + 20 + i);
  }
  blob(g, spread * .5, lc, (r() - .5) * spread * .3, th + spread * .9, (r() - .5) * spread * .3, seed + 13);
  return g;
}
const VEG = {
  tree(c) {
    const kind = treeKind(c.n);
    return treeModel({ h: clamp(c.H * .8, .7, 2.6), spread: clamp(c.fw * .42, .3, .8), leaf: greenOf(c.it.pal) || '#3f7a3a', kind, seed: c.it.id });
  },
  bush(c) {
    const g = new THREE.Group(), leaf = greenOf(c.it.pal) || (hexLum(c.c0) < .7 ? c.c0 : '#3f7a3a');
    const s = clamp(c.fw * .36, .2, .55), a = M('noisy', leaf), b = M('noisy', shade(leaf, .75));
    blob(g, s, b, 0, s * .7, 0, c.it.id, .8);
    for (let i = 0; i < 5; i++) {
      const t = i / 5 * 6.28 + c.r();
      blob(g, s * (.5 + c.r() * .25), i % 2 ? a : b, Math.cos(t) * s * .65, s * (.45 + c.r() * .45), Math.sin(t) * s * .65, c.it.id + i);
    }
    blob(g, s * .7, a, 0, s * 1.15, 0, c.it.id + 9);
    if (has(c.n, /berr|fruit|apple|orange/)) for (let i = 0; i < 7; i++) sphere(g, .03, M('plain', '#b8322a', { rough: .4 }), (c.r() - .5) * s * 1.6, s * (.5 + c.r() * .7), (c.r() - .5) * s * 1.6);
    return g;
  },
  flower(c) {
    const g = new THREE.Group(), st = M('plain', '#3f7a3a', { rough: .7 }), lf = M('noisy', '#4c8a3e', { side: THREE.DoubleSide });
    const petal = [...c.it.pal].sort((a, b) => hslOf(b).s - hslOf(a).s)[0] || c.light, pm = M('plain', petal, { rough: .55 });
    blob(g, .16, M('noisy', '#3f6e34'), 0, .05, 0, c.it.id, .35);                    // touceira de folhas
    for (let i = 0; i < 5; i++) {
      const x = (c.r() - .5) * .45, z = (c.r() - .5) * .45, h = .2 + c.r() * .25;
      limb(g, .011, .007, h, st, new THREE.Vector3(x, 0, z), new THREE.Vector3((c.r() - .5) * .3, 1, (c.r() - .5) * .3), 5);
      const leaf = place(new THREE.Mesh(new THREE.CircleGeometry(.05, 8), lf), x + .03, h * .45, z); leaf.scale.set(1, .4, 1); leaf.rotation.set(-1, c.r() * 3, 0); g.add(leaf);
      for (let k = 0; k < 6; k++) { const a = k / 6 * 6.28; sphere(g, .03, pm, x + Math.cos(a) * .035, h, z + Math.sin(a) * .035).children.at(-1).scale.set(1.3, .35, 1.3); }
      sphere(g, .02, M('plain', '#e8c23a'), x, h + .012, z);
    }
    return g;
  },
  crop(c) {
    const g = new THREE.Group(), m = M('noisy', hexLum(c.c0) < .7 ? c.c0 : '#8aa04a');
    box(g, 1, .05, 1, M('noisy', '#5a4630'), 0, 0, 0);
    for (let i = 0; i < 9; i++) {
      const s = place(new THREE.Mesh(new THREE.ConeGeometry(.05, .4 + c.r() * .25, 5), m), -.35 + (i % 3) * .35, .25, -.35 + Math.floor(i / 3) * .35); g.add(s);
    }
    return g;
  },
  mushroom(c) {
    const g = new THREE.Group(), capC = [...c.it.pal].sort((a, b) => hslOf(b).s - hslOf(a).s)[0] || c.c0;
    const stem = M('plain', '#e8dcc0', { rough: .7 }), capM = M('plain', capC, { rough: .5 }), gill = M('plain', '#c9b48e', { rough: .9 });
    for (let i = 0; i < 4; i++) {
      const x = (c.r() - .5) * .5, z = (c.r() - .5) * .5, h = .08 + c.r() * .14, R = .05 + h * .45;
      lathe(g, [[.001, 0], [R * .45, 0], [R * .32, h * .5], [R * .38, h], [.001, h]], stem, x, 0, z, 10);
      lathe(g, [[.001, h], [R * .9, h - .005], [R, h + .01], [R * .9, h + R * .25], [R * .5, h + R * .5], [.001, h + R * .55]], capM, x, 0, z, 16);
      const gl = place(new THREE.Mesh(new THREE.CircleGeometry(R * .9, 16), gill), x, h - .004, z); gl.rotation.x = Math.PI / 2; g.add(gl);
      if (hslOf(capC).s > .45) for (let k = 0; k < 4; k++) sphere(g, R * .1, M('plain', '#f2ece0'), x + Math.cos(k * 1.6) * R * .5, h + R * .38, z + Math.sin(k * 1.6) * R * .5);
    }
    return g;
  },
};

// ---------------------------------------------------------------- pedras
function boulder(c, scale = 1) {
  const g = new THREE.Group();
  const geo = new THREE.IcosahedronGeometry(.4 * scale, 2), p = geo.attributes.position, r = mkRng(c.it.id);
  for (let i = 0; i < p.count; i++) {
    const k = 1 + (Math.sin(p.getX(i) * 9 + c.it.id) * Math.cos(p.getZ(i) * 7) * .15) + (r() - .5) * .05;
    p.setXYZ(i, p.getX(i) * k, p.getY(i) * k * .8, p.getZ(i) * k);
  }
  geo.computeVertexNormals();
  g.add(place(new THREE.Mesh(geo, M('stone', c.c0)), 0, .3 * scale, 0));
  return g;
}
function stalagmites(c) {
  const g = new THREE.Group(), m = M('stone', c.c0), H = clamp(c.H * .9, .4, 2);
  for (let i = 0; i < 5; i++) {
    const h = H * (i ? .35 + c.r() * .45 : 1), rad = h * (.14 + c.r() * .05);
    const geo = new THREE.ConeGeometry(rad, h, 9, 4), p = geo.attributes.position;
    for (let k = 0; k < p.count; k++) { const s = 1 + .15 * Math.sin(p.getY(k) * 14 + i * 3); p.setX(k, p.getX(k) * s); p.setZ(k, p.getZ(k) * s); }
    geo.computeVertexNormals();
    g.add(place(new THREE.Mesh(geo, m), i ? (c.r() - .5) * .6 : 0, h / 2, i ? (c.r() - .5) * .6 : 0));
  }
  g.add(boulder({ ...c, it: { id: c.it.id + 3 } }, .45));
  return g;
}
const ROCK = {
  boulder(c) {
    const s = Math.min(1.5, c.fw * 1.1), g = boulder(c, s);
    for (let i = 0; i < 3; i++) { const b = boulder({ ...c, it: { id: c.it.id + 17 + i } }, s * (.18 + c.r() * .12)); const a = i * 2.1 + c.r(); b.position.set(Math.cos(a) * s * .45, 0, Math.sin(a) * s * .45); g.add(b); }
    if (greenOf(c.it.pal)) blob(g, s * .22, M('noisy', '#56783a'), s * .05, s * .48, 0, c.it.id, .3);
    return g;
  },
  crystal(c) {
    const g = new THREE.Group(), m = M('plain', c.light, { rough: .15, metal: .2, emissive: c.light, ei: .25, opacity: .92 });
    for (let i = 0; i < 5; i++) {
      const h = .3 + c.r() * .5, k = place(new THREE.Mesh(new THREE.ConeGeometry(.08 + c.r() * .05, h, 6), m), (c.r() - .5) * .4, h / 2, (c.r() - .5) * .4);
      k.rotation.z = (c.r() - .5) * .5; g.add(k);
    }
    return g;
  },
};

// ---------------------------------------------------------------- moveis e containers
const FURN = {
  table(c) {
    const g = new THREE.Group(), t = has(c.n, /stone|marble/) ? 'stone' : 'wood', m = M(t, c.c0), lg = M(t, shade(c.c0, .8));
    const W = clamp(c.fw, .5, 1.2), H = .75;
    if (has(c.n, /round/)) {
      const top = place(new THREE.Mesh(new THREE.CylinderGeometry(W * .5, W * .5, .06, 32), m), 0, H - .03, 0); g.add(top);
      ring(g, W * .5, .015, lg, 0, H - .045, 0);
      lathe(g, [[.001, 0], [.05, 0], [.05, .1], [.04, .2], [.07, .32], [.04, .45], [.045, H - .12], [.09, H - .06], [.001, H - .06]], lg, 0, 0, 0, 16);
      for (let i = 0; i < 4; i++) limb(g, .03, .02, W * .38, lg, new THREE.Vector3(0, .05, 0), new THREE.Vector3(Math.cos(i * Math.PI / 2 + .78), -.08, Math.sin(i * Math.PI / 2 + .78)), 6);
      return g;
    }
    box(g, W, .06, W, m, 0, H - .06, 0);
    box(g, W + .02, .015, W + .02, lg, 0, H - .075, 0);
    box(g, W - .14, .08, W - .14, lg, 0, H - .15, 0);                                  // avental
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) lathe(g, turnedLeg(H - .07), lg, sx * (W / 2 - .07), 0, sz * (W / 2 - .07));
    for (const s of [-1, 1]) box(g, .035, .035, W - .2, lg, s * (W / 2 - .07), .16, 0);
    return g;
  },
  chair(c) {
    const g = new THREE.Group(), t = has(c.n, /stone/) ? 'stone' : 'wood', m = M(t, c.c0), lg = M(t, shade(c.c0, .8));
    const bench = has(c.n, /bench/), stool = has(c.n, /stool/), throne = has(c.n, /throne/);
    const W = bench ? .9 : .5, D = .45, H = .45;
    box(g, W, .06, D, m, 0, H - .06, 0);
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) box(g, .06, H - .06, .06, lg, sx * (W / 2 - .05), 0, sz * (D / 2 - .05));
    if (!stool && !bench) box(g, W, throne ? 1 : .5, .05, m, 0, H, -D / 2 + .03);
    return g;
  },
  bed(c) {                                                                          // peca solta de cama: meia cama no estilo da feita a mao
    const out = new THREE.Group();
    OVR.wood = ratio(woodTone([c.it]) || c.c0, '#8a5a32');
    try { out.add(hmBed({ W: .96, L: .96, cot: /\bcot\b/.test(c.n) })); } finally { OVR.wood = null; }
    return out;
  },
  // armario: rodape, carcaca, cornija em dois degraus, portas almofadadas com moldura, puxadores e gaveta embaixo
  cabinet(c) {
    const g = new THREE.Group(), m = M('wood', c.c0), dk = M('wood', shade(c.c0, .72)), lt = M('wood', shade(c.c0, 1.12)), br = M('metal', brassC, { rough: .3 });
    const H = clamp(c.H, .9, 1.9), W = Math.min(1, Math.max(.5, c.fw)), D = .48, z = D / 2;
    box(g, W, .09, D, dk, 0, 0, 0);
    box(g, W - .04, H - .19, D - .04, m, 0, .09, 0);
    box(g, W + .06, .05, D + .05, dk, 0, H - .1, 0); box(g, W + .02, .05, D + .02, lt, 0, H - .05, 0);
    const dh = H > 1.25 ? .2 : 0, y0 = .12 + dh, ph = H - .26 - y0;
    if (dh) { box(g, W - .1, dh - .04, .03, lt, 0, .12, z - .01); sphere(g, .025, br, 0, .12 + dh / 2 - .02, z + .03); }
    for (const s of [-1, 1]) {
      const x = s * (W / 4 - .005), w = W / 2 - .07;
      box(g, w, ph, .025, dk, x, y0, z - .005);                                     // moldura da porta
      box(g, w - .1, ph - .12, .03, lt, x, y0 + .06, z);                            // almofada
      sphere(g, .022, br, s * .05, y0 + ph * .5, z + .03);
      for (const k of [.12, .88]) box(g, .03, .06, .012, M('metal', '#3a3d42'), s * (W / 2 - .04), y0 + ph * k - .03, z + .01);   // dobradicas
    }
    return g;
  },
  // estante de parede: laterais, fundo, prateleiras com potes, vidros e livros
  shelf(c, W = .92) {
    const g = new THREE.Group(), m = M('wood', c.c0), dk = M('wood', shade(c.c0, .7)), D = .34, H = 1.6;
    box(g, .05, H, D, m, -W / 2 + .025, 0, 0); box(g, .05, H, D, m, W / 2 - .025, 0, 0);
    box(g, W - .05, H, .02, dk, 0, 0, -D / 2 + .01); box(g, W + .04, .04, D + .03, m, 0, H, 0);
    for (let i = 0; i < 4; i++) {
      const y = .06 + i * .42;
      box(g, W - .05, .035, D - .02, m, 0, y, 0);
      let x = -W / 2 + .1;
      while (x < W / 2 - .12) {
        const k = c.r(), col = BOOKC[Math.floor(c.r() * BOOKC.length)];
        if (k < .35) { const r = .04 + c.r() * .03, h = .1 + c.r() * .12; lathe(g, [[.001, 0], [r, 0], [r * 1.1, h * .6], [r * .5, h * .85], [r * .55, h], [.001, h]], M('plain', col, { rough: .4 }), x + r, y + .035, (c.r() - .5) * .1, 12); x += r * 2 + .03; }
        else if (k < .7) { const n = 2 + Math.floor(c.r() * 4); for (let b = 0; b < n; b++) box(g, .035, .22 + c.r() * .1, D * .7, M('leather', BOOKC[Math.floor(c.r() * BOOKC.length)]), x + b * .04, y + .035, 0); x += n * .04 + .03; }
        else x += .1;
      }
    }
    return g;
  },
};
// bau: tabuas sobre rodape, tampa abaulada, cintas e cantoneiras de ferro, espelho de fechadura e alcas laterais
function chest(c) {
  const g = new THREE.Group(), m = M('wood', c.c0), dk = M('wood', shade(c.c0, .7)), ir = M('metal', ironC, { rough: .45 }), br = M('metal', brassC, { rough: .3 });
  const W = Math.min(1, Math.max(.45, c.fw * .85)), H = Math.max(.3, Math.min(.8, c.H * .8)), D = W * .62, hb = H * .6;
  box(g, W + .02, .035, D + .02, dk, 0, 0, 0);
  box(g, W, hb - .035, D, m, 0, .035, 0);
  for (let i = 1; i < 3; i++) box(g, W + .004, .01, D + .004, dk, 0, .035 + i * (hb - .035) / 3, 0);
  const half = (r, len, mat, x) => { const l = place(new THREE.Mesh(new THREE.CylinderGeometry(r, r, len, 18, 1, false, 0, Math.PI), mat), x, hb, 0); l.rotation.z = Math.PI / 2; g.add(l); };
  half(D / 2, W, m, 0);
  for (const x of [-W * .36, 0, W * .36]) { half(D / 2 + .008, .05, ir, x); box(g, .05, hb, D + .016, ir, x, 0, 0); }
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) box(g, .07, .07, .07, ir, sx * (W / 2 - .025), 0, sz * (D / 2 - .025));
  box(g, .1, .12, .02, br, 0, hb - .1, D / 2 + .01);
  box(g, .035, .08, .03, br, 0, hb - .03, D / 2 + .02);
  for (const s of [-1, 1]) { const h = place(new THREE.Mesh(new THREE.TorusGeometry(.05, .01, 6, 14, Math.PI), ir), s * (W / 2 + .012), hb * .62, 0); h.rotation.set(Math.PI, Math.PI / 2, 0); g.add(h); }
  return g;
}
function crateBox(c) {
  const g = new THREE.Group(), m = M('wood', c.c0), s = Math.min(1, Math.max(.4, c.fw * .85)), h = Math.max(.35, Math.min(.9, c.H * .85));
  box(g, s, h, s, m, 0, 0, 0);
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) box(g, .07, h + .01, .07, M('wood', shade(c.c0, .7)), sx * (s / 2 - .035), 0, sz * (s / 2 - .035));
  return g;
}
function barrelG(c) {
  const g = new THREE.Group(), r = Math.min(.45, Math.max(.2, c.fw * .4)), h = Math.max(.4, Math.min(1.1, c.H * .9));
  const w = M('wood', c.c0), ir = M('metal', '#4a4d52');
  const prof = [];
  for (let i = 0; i <= 12; i++) { const t = i / 12; prof.push([r * (1 + .14 * (1 - Math.pow(2 * t - 1, 2))), t * h]); }
  g.add(place(new THREE.Mesh(new THREE.LatheGeometry(prof.map(([a, b]) => new THREE.Vector2(a, b)), 28), w), 0, 0, 0));
  g.add(place(new THREE.Mesh(new THREE.CylinderGeometry(r * .93, r * .93, .03, 28), w), 0, h - .015, 0));
  for (const k of [.12, .35, .65, .88]) ring(g, r * (1 + .14 * (1 - Math.pow(2 * k - 1, 2))) + .006, .014, ir, 0, k * h, 0);
  return g;
}
const CONT = {
  chest, crate: crateBox, barrel: barrelG,
  // saco: corpo torneado assentado, gargalo franzido, corda amarrada e boca aberta em babado
  bag(c) {
    const g = new THREE.Group(), leather = has(c.n, /pouch|backpack|leather/), m = M(leather ? 'leather' : 'fabric', c.c0), s = clamp(c.fw * .5, .22, .5);
    lathe(g, [[.001, 0], [s * .7, 0], [s * .95, s * .25], [s, s * .6], [s * .85, s * 1.05], [s * .45, s * 1.35], [s * .26, s * 1.5], [s * .3, s * 1.62], [s * .42, s * 1.78], [s * .36, s * 1.8], [.001, s * 1.6]], m, 0, 0, 0, 20);
    ring(g, s * .28, .016, M('leather', '#6b4a2b'), 0, s * 1.5, 0);
    limb(g, .012, .01, s * .5, M('leather', '#6b4a2b'), new THREE.Vector3(s * .25, s * 1.5, 0), new THREE.Vector3(.6, -1, .2), 5);
    return g;
  },
};

// ---------------------------------------------------------------- armas / armaduras / ferramentas
// pecas de mao: montadas de perfil no plano xy (comprimento em x) e deitadas no chao por `lay`
const lay = (g, y = .03) => { g.rotation.x = -Math.PI / 2; const o = new THREE.Group(); o.add(g); o.rotation.y = -.5; o.position.y = y; return o; };
// aro em volta do eixo x (empunhadura enrolada, colar)
function band(g, r, t, mat, x, y = 0) { const m = place(new THREE.Mesh(new THREE.TorusGeometry(r, t, 6, 16), mat), x, y, 0); m.rotation.y = Math.PI / 2; g.add(m); return m; }
// cabo torneado ao longo de x com empunhadura de couro enrolada
function haft(g, L, r, m, x = 0, grip = null) {
  rod(g, r, r * .9, L, m, x, 0, 0, 10);
  if (grip) { const gl = L * .28, x0 = x - L / 2 + gl / 2 + .02; rod(g, r * 1.12, r * 1.12, gl, grip, x0, 0, 0, 10); for (let i = 0; i < 6; i++) band(g, r * 1.12, .004, grip, x0 - gl / 2 + (i + .5) * gl / 6); }
  return g;
}
function steelOf(c) { return M('metal', c.light && hexLum(c.light) > .5 ? c.light : '#b8bec6', { rough: .28 }); }
// lamina: perfil com ponta curva, gume chanfrado (bevel largo) e sulco central escuro
function blade(c, len, w, thick = .02, mat = steelOf(c)) {
  const g = new THREE.Group();
  const bl = new THREE.Shape(); bl.moveTo(0, -w / 2); bl.lineTo(len * .78, -w * .44); bl.quadraticCurveTo(len * .95, -w * .3, len, 0); bl.quadraticCurveTo(len * .95, w * .3, len * .78, w * .44); bl.lineTo(0, w / 2); bl.closePath();
  const geo = new THREE.ExtrudeGeometry(bl, { depth: thick * .3, bevelEnabled: true, bevelThickness: thick * .35, bevelSize: w * .16, bevelOffset: -w * .16, bevelSegments: 2 });
  g.add(place(new THREE.Mesh(geo, mat), 0, 0, -thick * .15));
  box(g, len * .6, w * .16, thick * 1.05, M('metal', '#6f757c', { rough: .35 }), len * .33, -w * .08, 0);
  return g;
}
const WEAP = {
  // espada: lamina com sulco, guarda com pontas, empunhadura enrolada e pomo torneado
  sword(c, sc = 1) {
    const g = new THREE.Group(), grip = M('leather', '#4b2f1c'), au = M('metal', brassC, { rough: .3 });
    const L = .75 * sc, b = blade(c, L, .07 * sc, .022); b.position.x = .1 * sc; g.add(b);
    box(g, .035, .26 * sc, .045, au, .085 * sc, -.13 * sc, 0);
    for (const s of [-1, 1]) sphere(g, .022, au, .085 * sc, s * .13 * sc, 0);
    rod(g, .02, .018, .16 * sc, grip, 0, 0, 0, 10);
    for (let i = 0; i < 5; i++) band(g, .02, .004, grip, -.065 * sc + i * .032 * sc);
    lathe(g, [[.001, 0], [.02, 0], [.034, .03], [.02, .055], [.001, .06]], au, -.08 * sc, 0, 0, 12).children.at(-1).rotation.z = Math.PI / 2;
    return lay(g, .03);
  },
  dagger: c => WEAP.sword(c, .5),
  // machado: cabo com empunhadura, barba curva do gume, olho e contra-cabeca
  axe(c) {
    const g = new THREE.Group(), w = M('wood', '#6b4a2b'), st = steelOf(c), dk = M('metal', '#5a5f66', { rough: .45 });
    haft(g, .9, .022, w, 0, M('leather', '#4b2f1c'));
    const s = new THREE.Shape(); s.moveTo(-.035, .025); s.lineTo(.035, .025); s.quadraticCurveTo(.06, .12, .13, .2); s.quadraticCurveTo(0, .25, -.13, .2); s.quadraticCurveTo(-.06, .12, -.035, .025); s.closePath();
    g.add(place(new THREE.Mesh(new THREE.ExtrudeGeometry(s, { depth: .012, bevelEnabled: true, bevelThickness: .008, bevelSize: .006, bevelSegments: 2 }), st), .36, 0, -.006));
    box(g, .08, .07, .05, dk, .36, -.035, 0);
    box(g, .05, .06, .04, dk, .36, -.09, 0);
    return lay(g, .03);
  },
  // maca: cabeca de flanges sobre nucleo, colares, ponta e cabo enrolado
  mace(c) {
    const g = new THREE.Group(), w = M('wood', '#5b3b22'), st = M('metal', '#8f959c', { rough: .35 });
    haft(g, .7, .022, w, 0, M('leather', '#4b2f1c'));
    sphere(g, .06, st, .4, 0, 0);
    for (let i = 0; i < 7; i++) { const a = i / 7 * 6.28, f = place(new THREE.Mesh(new THREE.BoxGeometry(.16, .07, .012), st), .4, Math.cos(a) * .05, Math.sin(a) * .05); f.rotation.x = a; g.add(f); }
    for (const x of [.31, .49]) band(g, .035, .01, st, x);
    rod(g, .02, .001, .07, st, .52, 0, 0, 8);
    return lay(g, .07);
  },
  // cajado: madeira nodosa torneada, garras segurando um orbe brilhante
  staff(c) {
    const g = new THREE.Group(), w = M('wood', c.c0 && hexLum(c.c0) < .6 ? c.c0 : '#6b4a2b'), r = mkRng(c.it.id);
    const prof = [[.001, 0], [.022, 0]];
    for (let i = 1; i <= 10; i++) prof.push([.022 + (i % 3 === 0 ? .01 : 0) + r() * .004, i * .15]);
    prof.push([.04, 1.55], [.001, 1.56]);
    const s = new THREE.Group(); lathe(s, prof, w, 0, 0, 0, 9);
    for (let i = 0; i < 3; i++) { const a = i * 2.094; limb(s, .012, .005, .14, w, new THREE.Vector3(Math.cos(a) * .03, 1.53, Math.sin(a) * .03), new THREE.Vector3(Math.cos(a) * .5, 1, Math.sin(a) * .5), 5); }
    const orb = c.light || '#7fd0ff';
    sphere(s, .055, M('plain', orb, { emissive: orb, ei: .8, rough: .15, opacity: .9 }), 0, 1.63, 0);
    s.rotation.z = -Math.PI / 2; s.position.x = -.8; g.add(s);
    return lay(g, .045);
  },
  // arco: bracos recurvos em tubo, punho de couro, corda tensa
  bow(c) {
    const g = new THREE.Group(), w = M('wood', c.c0 && hexLum(c.c0) < .6 ? c.c0 : '#7a4c27');
    const curve = new THREE.CatmullRomCurve3([[-.04, -.62], [.04, -.5], [.13, -.28], [.15, 0], [.13, .28], [.04, .5], [-.04, .62]].map(([x, y]) => new THREE.Vector3(x, y, 0)));
    g.add(place(new THREE.Mesh(new THREE.TubeGeometry(curve, 40, .016, 7), w), 0, 0, 0));
    g.add(place(new THREE.Mesh(new THREE.CylinderGeometry(.024, .024, .14, 10), M('leather', '#4b2f1c')), .15, 0, 0));
    g.add(place(new THREE.Mesh(new THREE.CylinderGeometry(.0035, .0035, 1.22, 4), M('plain', '#e8dcc0')), -.035, 0, 0));
    return lay(g, .02);
  },
  // arma de haste: alabarda (gume, ponta e gancho) com ponteira e aneis
  polearm(c) {
    const g = new THREE.Group(), st = steelOf(c), fe = M('metal', '#5a5f66', { rough: .45 });
    haft(g, 1.7, .02, M('wood', '#6b4a2b'));
    const s = new THREE.Shape(); s.moveTo(0, .02); s.lineTo(.12, .02); s.quadraticCurveTo(.16, .12, .12, .2); s.quadraticCurveTo(.04, .16, 0, .2); s.closePath();
    g.add(place(new THREE.Mesh(new THREE.ExtrudeGeometry(s, { depth: .012, bevelEnabled: true, bevelThickness: .006, bevelSize: .005, bevelSegments: 1 }), st), .62, 0, -.006));
    const sp = blade(c, .3, .05, .02, st); sp.position.x = .84; g.add(sp);
    const hook = new THREE.Shape(); hook.moveTo(0, -.02); hook.lineTo(.06, -.02); hook.quadraticCurveTo(.04, -.08, .1, -.13); hook.quadraticCurveTo(0, -.09, 0, -.02);
    g.add(place(new THREE.Mesh(new THREE.ExtrudeGeometry(hook, { depth: .014, bevelEnabled: false }), st), .66, 0, -.007));
    for (const x of [.6, .8]) band(g, .025, .008, fe, x);
    rod(g, .024, .02, .06, fe, -.84, 0, 0, 8);
    return lay(g, .03);
  },
  // canhao: carreta de vigas com rodas raiadas e cano torneado com reforcos
  siege(c) {
    const g = new THREE.Group(), w = M('wood', c.c0), st = M('metal', '#3d4045', { rough: .4 });
    for (const s of [-1, 1]) box(g, .08, .22, 1, w, s * .18, .12, 0);
    box(g, .44, .06, .9, w, 0, .1, 0);
    const cn = new THREE.Group(); cn.position.set(0, .42, -.05); cn.rotation.x = Math.PI / 2 - .12; g.add(cn);
    lathe(cn, [[.001, -.45], [.1, -.45], [.13, -.38], [.14, -.3], [.12, -.25], [.13, -.22], [.11, .2], [.12, .45], [.1, .5], [.07, .5], [.07, .3], [.001, .3]], st, 0, 0, 0, 18);
    sphere(cn, .07, st, 0, -.5, 0);
    for (const x of [-.24, .24]) for (const z of [-.3, .3]) {
      const wh = new THREE.Group(); wh.position.set(x, .2, z); wh.rotation.z = Math.PI / 2; g.add(wh);
      wh.add(place(new THREE.Mesh(new THREE.TorusGeometry(.17, .025, 6, 20), w), 0, 0, 0)).children.at(-1).rotation.x = Math.PI / 2;
      for (let i = 0; i < 6; i++) { const sp = new THREE.Mesh(new THREE.BoxGeometry(.02, .04, .32), w); sp.rotation.y = i * Math.PI / 6; wh.add(sp); }
      wh.add(new THREE.Mesh(new THREE.CylinderGeometry(.04, .04, .06, 10), st));
    }
    g.traverse(o => { if (o.isMesh) o.castShadow = o.receiveShadow = true; });
    return g;
  },
};
// aco: sprite escuro demais (sombra do desenho) vira o tom claro da paleta ou aco padrao
const steelTone = c => hexLum(c.c0) >= .4 ? c.c0 : c.light && hexLum(c.light) > .45 ? c.light : '#9aa0a8';
// suporte de armadura: base em cruz, haste e travessa dos ombros
function armorStand(g, h, wd) {
  box(g, .5, .05, .08, wd, 0, 0, 0); box(g, .08, .05, .5, wd, 0, 0, 0);
  lathe(g, [[.001, .05], [.03, .05], [.025, h], [.001, h]], wd, 0, 0, 0, 8);
  box(g, .5, .04, .05, wd, 0, h - .1, 0);
}
const ARMOR = {
  // couraca no suporte: peitoral torneado, ombreiras em placas, cinto e (couro) tachas
  body(c) {
    const g = new THREE.Group(), leather = has(c.n, /leather|studded|hide/), m = M(leather ? 'leather' : 'metal', leather ? c.c0 : steelTone(c), { rough: leather ? .7 : .38 });
    const trim = M('metal', leather ? '#8a6a3a' : brassC, { rough: .3 });
    armorStand(g, 1.15, M('wood', '#5b3b22'));
    const t = new THREE.Group(); t.position.y = .45; t.scale.set(1.15, 1, .72); g.add(t);
    lathe(t, [[.001, 0], [.2, 0], [.23, .06], [.21, .18], [.25, .38], [.27, .5], [.2, .56], [.08, .6], [.001, .6]], m, 0, 0, 0, 22);
    ring(t, .215, .012, trim, 0, .05, 0);
    ring(t, .23, .02, M('leather', '#3a2a1a'), 0, .14, 0);
    for (const s of [-1, 1]) for (let k = 0; k < 3; k++) {
      const p = place(new THREE.Mesh(new THREE.SphereGeometry(.13 - k * .015, 14, 8, 0, 6.28, 0, 1.3), m), s * (.3 + k * .02), .99 - k * .06, 0);
      p.rotation.z = -s * (.5 + k * .15); g.add(p);
    }
    if (leather) for (let i = 0; i < 12; i++) sphere(g, .012, trim, Math.cos(i * .52) * .2, .7 + Math.sin(i * 1.7) * .1, .2);
    return g;
  },
  // elmo: calota torneada com crista, aba, nasal e protetores de face; plumas nos ornamentados
  helm(c) {
    const g = new THREE.Group(), st = steelTone(c), m = M('metal', st, { rough: .38 }), dk = M('metal', shade(st, .7), { rough: .45 });
    const closed = has(c.n, /plate|close|great|bascinet|norse|orc/);
    lathe(g, [[.2, .02], [.22, .1], [.21, .22], [.17, .33], [.09, .39], [.001, .4]], m, 0, 0, 0, 24);
    ring(g, .205, .014, dk, 0, .04, 0);
    box(g, .018, .05, .36, dk, 0, .36, 0).children.at(-1).rotation.x = .1;
    if (closed) {
      g.add(place(new THREE.Mesh(new THREE.CylinderGeometry(.215, .2, .2, 20, 1, true, -1.1, 2.2), M('metal', st, { rough: .38, side: THREE.DoubleSide })), 0, .12, 0));
      box(g, .26, .015, .02, M('plain', '#111'), 0, .17, .2);
    } else {
      box(g, .03, .14, .02, m, 0, .02, .21);
      for (const s of [-1, 1]) box(g, .08, .14, .02, m, s * .15, .0, .14).children.at(-1).rotation.y = s * .7;
    }
    if (c.it.flags && has(c.n, /plumed|crest|winged/)) for (let i = 0; i < 5; i++) limb(g, .025, .01, .25, M('fabric', '#a0302a'), new THREE.Vector3(0, .38, -.05 + i * .02), new THREE.Vector3(0, .6, -1 + i * .1), 6);
    return g;
  },
  // escudo encostado: redondo (tabuas ou chapa, aro, umbo) ou de bico (extrudado com faixa heraldica)
  shield(c) {
    const g = new THREE.Group(), woody = has(c.n, /wood|buckler/), m = M(woody ? 'wood' : 'metal', c.c0, { rough: .4 }), tr = M('metal', brassC, { rough: .3 }), fe = M('metal', ironC, { rough: .4 });
    const kite = has(c.n, /heater|kite|bronze|order|chaos/), face = new THREE.Group(); face.position.y = .5; g.add(face);
    if (kite) {
      const s = new THREE.Shape(); s.moveTo(-.3, .4); s.lineTo(.3, .4); s.lineTo(.3, 0); s.quadraticCurveTo(.2, -.35, 0, -.52); s.quadraticCurveTo(-.2, -.35, -.3, 0); s.closePath();
      face.add(new THREE.Mesh(new THREE.ExtrudeGeometry(s, { depth: .04, bevelEnabled: true, bevelSize: .02, bevelThickness: .015, bevelSegments: 2 }), m));
      const st = new THREE.Shape(); st.moveTo(-.06, .4); st.lineTo(.06, .4); st.lineTo(.06, -.3); st.lineTo(0, -.42); st.lineTo(-.06, -.3); st.closePath();
      face.add(place(new THREE.Mesh(new THREE.ShapeGeometry(st), M('plain', c.c1 !== c.c0 ? c.c1 : '#a0302a', { rough: .6 })), 0, 0, .058));
    } else {
      const d = new THREE.Mesh(new THREE.CylinderGeometry(.38, .38, .04, 32), m); d.rotation.x = Math.PI / 2; face.add(d);
      if (woody) for (let i = -2; i <= 2; i++) { const p = new THREE.Mesh(new THREE.BoxGeometry(.004, .7 - Math.abs(i) * .1, .005), M('wood', shade(c.c0, .6))); p.position.set(i * .14, 0, .021); face.add(p); }
      const rim = new THREE.Mesh(new THREE.TorusGeometry(.38, .018, 6, 36), fe); face.add(rim);
      const b = new THREE.Mesh(new THREE.SphereGeometry(.09, 16, 8, 0, 6.28, 0, 1.4), tr); b.rotation.x = Math.PI / 2; b.position.z = .02; face.add(b);
    }
    face.traverse(o => { if (o.isMesh) o.castShadow = o.receiveShadow = true; });
    g.rotation.x = -.3; g.rotation.y = .5;
    return g;
  },
};
const CLOTH = {
  // tunica/manto pendurado num cabide de pe: saia torneada, mangas, capuz, cinto de corda e barra em cor de destaque
  robe(c) {
    const g = new THREE.Group(), m = M('fabric', c.c0), hem = M('fabric', c.c1 !== c.c0 ? c.c1 : shade(c.c0, .65)), wd = M('wood', '#5b3b22');
    armorStand(g, 1.3, wd);
    lathe(g, [[.001, .08], [.36, .08], [.3, .5], [.22, .9], [.24, 1.1], [.12, 1.2], [.001, 1.2]], m, 0, 0, 0, 24);
    lathe(g, [[.362, .08], [.345, .16]], hem, 0, 0, 0, 24);
    for (const s of [-1, 1]) {
      limb(g, .1, .065, .52, m, new THREE.Vector3(s * .26, 1.08, 0), new THREE.Vector3(s * .35, -1, .05), 12);
      ring(g, .1, .015, hem, s * .44, .6, .03).children.at(-1).rotation.set(Math.PI / 2, 0, s * .34);
    }
    const hood = place(new THREE.Mesh(new THREE.SphereGeometry(.15, 16, 10, 0, 6.28, 0, 1.6), m), 0, 1.12, -.12); hood.rotation.x = -1.2; g.add(hood);
    ring(g, .23, .016, M('fabric', '#c9b48e'), 0, .82, 0);
    limb(g, .012, .01, .35, M('fabric', '#c9b48e'), new THREE.Vector3(.08, .82, .2), new THREE.Vector3(.05, -1, .1), 5);
    return g;
  },
};
const JEWEL = {
  // anel: aro torneado com garras segurando a pedra lapidada
  ring(c) {
    const g = new THREE.Group(), au = M('metal', '#d4af37', { rough: .22 });
    const r = place(new THREE.Mesh(new THREE.TorusGeometry(.1, .016, 12, 32), au), 0, .11, 0); g.add(r);
    lathe(g, [[.001, .2], [.03, .2], [.035, .225], [.001, .23]], au, 0, 0, 0, 12);
    for (let i = 0; i < 4; i++) limb(g, .005, .004, .04, au, new THREE.Vector3(Math.cos(i * 1.57) * .03, .21, Math.sin(i * 1.57) * .03), new THREE.Vector3(Math.cos(i * 1.57) * -.3, 1, Math.sin(i * 1.57) * -.3), 4);
    const gem = c.light || '#e04a5a';
    g.add(place(new THREE.Mesh(new THREE.OctahedronGeometry(.03), M('plain', gem, { emissive: gem, ei: .3, rough: .08 })), 0, .245, 0));
    return g;
  },
};

// ferramentas por nome: cada uma com cabeca propria (martelo de unha, serrote dentado, picareta curva, pa, tesoura, caldeirao)
function tool(c) {
  const g = new THREE.Group(), n = c.n, w = M('wood', '#6b4a2b'), st = M('metal', '#aeb4bb', { rough: .32 }), dk = M('metal', '#5a5f66', { rough: .45 });
  if (has(n, /saw/)) {
    const s = new THREE.Shape(); s.moveTo(0, -.05); for (let i = 0; i <= 24; i++) s.lineTo(i * .025, (i % 2 ? -.065 : -.05) + i * .0015); s.lineTo(.6, .015); s.lineTo(0, .05); s.closePath();
    g.add(place(new THREE.Mesh(new THREE.ExtrudeGeometry(s, { depth: .004, bevelEnabled: false }), st), .02, 0, -.002));
    const hd = new THREE.Shape(); hd.moveTo(-.14, -.06); hd.lineTo(.04, -.06); hd.lineTo(.04, .09); hd.lineTo(-.14, .07); hd.closePath();
    const hole = new THREE.Path(); hole.absellipse(-.06, .015, .045, .025, 0, 6.28, true); hd.holes.push(hole);
    g.add(place(new THREE.Mesh(new THREE.ExtrudeGeometry(hd, { depth: .03, bevelEnabled: true, bevelSize: .006, bevelThickness: .006, bevelSegments: 2 }), w), 0, 0, -.015));
    return lay(g, .025);
  }
  if (has(n, /hammer|mallet|sledge|maul/)) {
    haft(g, .5, .02, w, 0, M('leather', '#4b2f1c'));
    const mallet = has(n, /mallet/);
    if (mallet) rod(g, .07, .07, .12, w, .25, 0, 0, 14).rotation.set(0, 0, 0);
    else { box(g, .07, .14, .06, st, .26, -.02, 0); limb(g, .025, .006, .12, st, new THREE.Vector3(.26, -.08, 0), new THREE.Vector3(-.4, -1, 0), 6); band(g, .028, .006, dk, .23); }
    return lay(g, .045);
  }
  if (has(n, /pick/)) {
    haft(g, .8, .02, w, 0, M('leather', '#4b2f1c'));
    const curve = new THREE.QuadraticBezierCurve3(new THREE.Vector3(.38, -.28, 0), new THREE.Vector3(.44, 0, 0), new THREE.Vector3(.38, .28, 0));
    g.add(place(new THREE.Mesh(new THREE.TubeGeometry(curve, 16, .02, 6), st), 0, 0, 0));
    box(g, .07, .07, .05, dk, .42, -.035, 0);
    return lay(g, .035);
  }
  if (has(n, /shovel|spade/)) {
    haft(g, .8, .02, w);
    const s = new THREE.Shape(); s.moveTo(0, -.03); s.lineTo(.05, -.11); s.quadraticCurveTo(.25, -.12, .3, 0); s.quadraticCurveTo(.25, .12, .05, .11); s.lineTo(0, .03); s.closePath();
    g.add(place(new THREE.Mesh(new THREE.ExtrudeGeometry(s, { depth: .006, bevelEnabled: true, bevelSize: .004, bevelThickness: .004, bevelSegments: 1 }), st), .4, 0, -.003));
    box(g, .1, .015, .015, w, -.42, -.007, 0).children.at(-1).rotation.z = Math.PI / 2;
    return lay(g, .02);
  }
  if (has(n, /scythe|sickle|hoe|rake|fork/)) {
    haft(g, .9, .02, w);
    if (has(n, /rake|fork/)) { box(g, .03, .26, .03, dk, .44, -.13, 0); for (let i = 0; i < (has(n, /fork/) ? 3 : 7); i++) { const y = -.12 + i * (has(n, /fork/) ? .12 : .04); rod(g, .006, .002, .12, st, .52, y, 0, 5); } }
    else { const s = new THREE.Shape(); s.moveTo(0, 0); s.quadraticCurveTo(.05, .25, -.25, .45); s.quadraticCurveTo(.0, .2, -.03, .02); s.closePath(); g.add(place(new THREE.Mesh(new THREE.ExtrudeGeometry(s, { depth: .006, bevelEnabled: false }), st), .45, 0, -.003)); }
    return lay(g, .03);
  }
  if (has(n, /scissors|shears|tongs|pliers/)) {
    for (const s of [-1, 1]) {
      const b = blade(c, .2, .03, .008, st); b.position.set(0, s * .006, 0); b.rotation.z = s * .12; g.add(b);
      const r = place(new THREE.Mesh(new THREE.TorusGeometry(.035, .008, 6, 16), dk), -.06, s * .04, 0); g.add(r);
    }
    sphere(g, .01, dk, 0, 0, 0);
    return lay(g, .015);
  }
  if (has(n, /pot|pan|cauldron|kettle|bowl|cup|mug|jug|pitcher/)) {
    const big = has(n, /cauldron|kettle|pot/), r = big ? .26 : .12, m = M('metal', big ? '#3d4045' : c.c0, { rough: .45 });
    lathe(g, [[.001, r * .3], [r * .6, r * .3], [r * .95, r * .8], [r, r * 1.3], [r * .9, r * 1.75], [r * .95, r * 1.85], [r * .88, r * 1.85], [r * .82, r * 1.7], [.001, r * .5]], m, 0, 0, 0, 24);
    if (big) {
      for (let i = 0; i < 3; i++) { const a = i * 2.094; limb(g, .02, .015, r * .5, m, new THREE.Vector3(Math.cos(a) * r * .55, r * .4, Math.sin(a) * r * .55), new THREE.Vector3(Math.cos(a) * .3, -1, Math.sin(a) * .3), 6); }
      const h = place(new THREE.Mesh(new THREE.TorusGeometry(r * .92, .01, 6, 24, Math.PI), m), 0, r * 1.85, 0); g.add(h);
    } else { const h = place(new THREE.Mesh(new THREE.TorusGeometry(r * .4, .012, 6, 14, Math.PI * 1.2), m), r * 1.05, r * 1.1, 0); h.rotation.z = -1.9; g.add(h); }
    return g;
  }
  haft(g, .45, .02, w, 0, M('leather', '#4b2f1c')); box(g, .09, .09, .06, st, .25, -.045, 0);
  return lay(g, .04);
}

// ---------------------------------------------------------------- consumiveis / recursos / luzes / documentos
const CONS = {
  // frasco: tres formatos (redondo, alto, achatado) pelo id; vidro, liquido brilhante, rolha e cordao no gargalo
  potion(c) {
    const g = new THREE.Group(), glass = M('plain', '#cfe6ef', { opacity: .3, rough: .05 });
    const liq = [...c.it.pal].sort((a, b) => hslOf(b).s - hslOf(a).s)[0] || c.light;
    const shapes = [
      [[.001, 0], [.07, 0], [.12, .05], [.13, .12], [.1, .2], [.035, .25], [.035, .33], [.045, .34], [.001, .34]],
      [[.001, 0], [.07, 0], [.075, .02], [.075, .2], [.04, .26], [.028, .34], [.035, .35], [.001, .35]],
      [[.001, 0], [.12, 0], [.14, .04], [.12, .1], [.04, .14], [.03, .22], [.04, .23], [.001, .23]],
    ];
    const prof = shapes[c.it.id % 3], top = prof.at(-1)[1];
    lathe(g, prof, glass, 0, 0, 0, 22);
    lathe(g, prof.filter(p => p[1] < top * .55).map(([r, y]) => [Math.max(.001, r * .9), y + .006]).concat([[.001, top * .5]]), M('plain', liq, { emissive: liq, ei: .4, rough: .15, opacity: .92 }), 0, 0, 0, 22);
    lathe(g, [[.001, top - .02], [.03, top - .02], [.036, top + .03], [.001, top + .035]], M('wood', '#9a6a3a'), 0, 0, 0, 10);
    ring(g, prof.at(-4)[0] + .004, .006, M('fabric', '#c9b48e'), 0, prof.at(-4)[1] + .02, 0);
    return g;
  },
  food(c) {
    const g = new THREE.Group(), n = c.n;
    const plate = () => lathe(g, [[.001, 0], [.16, 0], [.22, .025], [.2, .03], [.001, .012]], M('plain', '#d8d0c0', { rough: .4 }), 0, 0, 0, 24);
    if (has(n, /bread|loaf/)) {
      const b = place(new THREE.Mesh(new THREE.SphereGeometry(.17, 18, 10), M('noisy', '#c28a45', { rough: .8 })), 0, .07, 0); b.scale.set(1.5, .65, 1); g.add(b);
      for (let i = 0; i < 3; i++) box(g, .03, .012, .2, M('plain', '#e8c890'), -.1 + i * .1, .175, 0).children.at(-1).rotation.y = .5;
    } else if (has(n, /cheese/)) {
      const s = new THREE.Shape(); s.moveTo(0, 0); s.absarc(0, 0, .2, -.45, .45, false); s.closePath();
      const w = place(new THREE.Mesh(new THREE.ExtrudeGeometry(s, { depth: .12, bevelEnabled: false }), M('plain', '#e8c85a', { rough: .5 })), -.08, .12, 0); w.rotation.x = Math.PI / 2; g.add(w);
      for (let i = 0; i < 4; i++) sphere(g, .015, M('plain', '#b89a30'), .02 + c.r() * .1, .121, (c.r() - .5) * .08);
    } else if (has(n, /ham|meat|steak|leg|sausage|fish|bacon|rib/)) {
      plate();
      const b = place(new THREE.Mesh(new THREE.SphereGeometry(.12, 16, 12), M('plain', c.c0, { rough: .55 })), -.03, .1, 0); b.scale.set(1.4, .8, 1); g.add(b);
      rod(g, .018, .014, .14, M('plain', '#eee6d0'), .17, .08, 0, 8); sphere(g, .025, M('plain', '#eee6d0'), .24, .08, 0);
    } else if (has(n, /pie|cake|tart/)) {
      plate();
      lathe(g, [[.001, .03], [.15, .03], [.16, .08], [.14, .09], [.001, .1]], M('noisy', '#c9904a'), 0, 0, 0, 22);
      for (let i = 0; i < 4; i++) box(g, .3, .008, .015, M('plain', '#a8702e'), 0, .095, 0).children.at(-1).rotation.y = i * Math.PI / 4;
    } else if (has(n, /apple|peach|pear|orange|lemon|grapes|banana|melon|pumpkin|fruit|egg/)) {
      for (let i = 0; i < 4; i++) {
        const x = (i - 1.5) * .12, z = (i % 2) * .09, r = .07;
        sphere(g, r, M('plain', c.c0, { rough: .45 }), x, r, z);
        limb(g, .006, .004, .04, M('wood', '#5b3b22'), new THREE.Vector3(x, r * 1.9, z), new THREE.Vector3(.2, 1, 0), 4);
      }
    } else { plate(); sphere(g, .1, M('plain', c.c0, { rough: .5 }), 0, .1, 0); }
    return g;
  },
  reagent(c) {
    const g = new THREE.Group();
    for (let i = 0; i < 5; i++) sphere(g, .06 + c.r() * .03, M('noisy', c.c0, { rough: .7 }), (c.r() - .5) * .25, .07, (c.r() - .5) * .25);
    return g;
  },
};
const RES = {
  // lingotes: tronco de piramide chanfrado, empilhados em camadas cruzadas (3 + 2)
  ingot(c) {
    const g = new THREE.Group(), m = M('metal', c.c0, { rough: .32 });
    const bar = (x, y, z, ry) => {
      const s = new THREE.Shape(); s.moveTo(-.08, 0); s.lineTo(.08, 0); s.lineTo(.06, .07); s.lineTo(-.06, .07); s.closePath();
      const geo = new THREE.ExtrudeGeometry(s, { depth: .36, bevelEnabled: true, bevelThickness: .01, bevelSize: .008, bevelSegments: 2 });
      geo.translate(0, 0, -.18);
      const b = place(new THREE.Mesh(geo, m), x, y, z); b.rotation.y = ry; g.add(b);
    };
    for (const x of [-.17, 0, .17]) bar(x, .008, 0, 0);
    for (const z of [-.09, .09]) bar(0, .095, z, Math.PI / 2);
    return g;
  },
};
// chama em camadas: externa laranja, interna amarela (emissivas)
function flame(g, r, h, x, y, z) {
  const geo = k => { const q = new THREE.SphereGeometry(r * k, 12, 10); q.translate(0, r * k, 0); const p = q.attributes.position; for (let i = 0; i < p.count; i++) { const t = p.getY(i) / (2 * r * k); p.setX(i, p.getX(i) * (1 - t * .75)); p.setZ(i, p.getZ(i) * (1 - t * .75)); p.setY(i, p.getY(i) * h / (2 * r)); } q.computeVertexNormals(); return q; };
  g.add(place(new THREE.Mesh(geo(1), M('plain', '#ff9a2a', { emissive: '#ff6a10', ei: 1.5, opacity: .9 })), x, y, z));
  g.add(place(new THREE.Mesh(geo(.55), M('plain', '#fff0a0', { emissive: '#ffd060', ei: 1.8 })), x, y, z));
}
const LIGHT = {
  // tocha de parede: espelho de ferro, braco, argola e tocha com cabeca enrolada em pano
  torch(c) {
    const g = new THREE.Group(), fe = M('metal', '#33363a', { rough: .5 }), wd = M('wood', '#5b3b22');
    if (has(c.n, /wall|sconce/)) {
      box(g, .14, .3, .025, fe, 0, .7, -.2);
      limb(g, .015, .015, .2, fe, new THREE.Vector3(0, .78, -.19), new THREE.Vector3(0, .35, 1), 6);
      ring(g, .045, .012, fe, 0, .86, -.02);
      const t = new THREE.Group(); t.position.set(0, .7, -.02); t.rotation.x = .25; g.add(t);
      lathe(t, [[.001, 0], [.022, 0], [.028, .38], [.001, .38]], wd, 0, 0, 0, 8);
      lathe(t, [[.001, .3], [.04, .3], [.045, .36], [.04, .44], [.001, .44]], M('fabric', '#4a3a2a'), 0, 0, 0, 10);
      flame(t, .05, .2, 0, .42, 0);
      const pl = new THREE.PointLight(0xffa040, .6, 2); pl.position.set(0, 1.25, 0); g.add(pl);
      return g;
    }
    lathe(g, [[.001, 0], [.12, 0], [.1, .04], [.03, .08], [.03, .7], [.06, .74], [.001, .74]], fe, 0, 0, 0, 12);   // pe de ferro
    lathe(g, [[.001, .74], [.08, .74], [.1, .84], [.09, .86], [.001, .8]], fe, 0, 0, 0, 12);                    // tigela
    lathe(g, [[.001, .78], [.045, .78], [.05, .88], [.001, .9]], M('fabric', '#4a3a2a'), 0, 0, 0, 10);
    flame(g, .07, .3, 0, .86, 0);
    const pl = new THREE.PointLight(0xffa040, .6, 2); pl.position.set(0, 1.05, 0); g.add(pl);
    return g;
  },
};
const DOC = {
  book(c) {
    const g = new THREE.Group();
    if (has(c.n, /scroll/)) {
      const pp = M('fabric', '#e8dcc0'), wd = M('wood', '#6b4a2b');
      rod(g, .04, .04, .3, pp, 0, .04, 0, 14); ring(g, .041, .006, M('plain', '#a0302a'), 0, .04, 0).children.at(-1).rotation.set(0, 0, Math.PI / 2);
      for (const s of [-1, 1]) { rod(g, .012, .012, .05, wd, s * .17, .04, 0, 8); sphere(g, .018, wd, s * .2, .04, 0); }
      g.rotation.y = -.5;
      return g;
    }
    // livro: capas com sobra, miolo de paginas, lombada arredondada com nervuras e fecho
    const cv = M('leather', c.c0), pg = M('plain', '#efe6d0', { rough: .9 }), au = M('metal', brassC, { rough: .3 });
    box(g, .22, .012, .3, cv, 0, 0, 0); box(g, .22, .012, .3, cv, 0, .068, 0);
    box(g, .205, .056, .28, pg, .008, .012, 0);
    const sp = place(new THREE.Mesh(new THREE.CylinderGeometry(.04, .04, .3, 12, 1, false, Math.PI, Math.PI), cv), -.11, .04, 0); sp.rotation.x = Math.PI / 2; g.add(sp);
    for (const z of [-.08, 0, .08]) { const b = place(new THREE.Mesh(new THREE.CylinderGeometry(.043, .043, .012, 12, 1, false, Math.PI, Math.PI), cv), -.11, .04, z); b.rotation.x = Math.PI / 2; g.add(b); }
    box(g, .05, .015, .03, au, .12, .03, 0);
    for (const sx of [-1, 1]) box(g, .03, .014, .03, au, sx * .09 + .01, .068, .135);
    g.rotation.y = .4;
    return g;
  },
};

// ---------------------------------------------------------------- decoracao
// pedestal classico: plinto, dado e cornija
function pedestal(g, w, h, mat, dk) {
  box(g, w + .08, .08, w + .08, dk, 0, 0, 0); box(g, w, h - .16, w, mat, 0, .08, 0); box(g, w + .06, .08, w + .06, dk, 0, h - .08, 0);
  return h;
}
// figura de pe em tunica (estatua): saia torneada, tronco, bracos, cabeca e um braco erguido
function figure(g, mat, y0, H, seed) {
  const r = mkRng(seed);
  lathe(g, [[.001, 0], [H * .16, 0], [H * .13, H * .2], [H * .1, H * .45], [H * .11, H * .55], [H * .13, H * .68], [H * .08, H * .78], [H * .04, H * .8], [.001, H * .8]], mat, 0, y0, 0, 18);
  sphere(g, H * .065, mat, 0, y0 + H * .87, 0);
  sphere(g, H * .068, mat, 0, y0 + H * .9, -H * .015).children.at(-1).scale.set(1, .7, 1);   // cabelo
  for (const s of [-1, 1]) {
    const up = s > 0 && r() < .6;
    const sh = new THREE.Vector3(s * H * .12, y0 + H * .72, 0);
    sphere(g, H * .045, mat, sh.x, sh.y, sh.z);
    limb(g, H * .035, H * .028, H * .3, mat, sh, up ? new THREE.Vector3(s * .3, 1, .25) : new THREE.Vector3(s * .25, -1, .1), 8);
  }
}
const DECO = {
  // vaso/anfora: perfil torneado com labio, faixa pintada e alcas quando largo
  vase(c) {
    const g = new THREE.Group(), r = clamp(c.fw * .25, .1, .25), m = M('plain', c.c0, { rough: .3 });
    lathe(g, [[.001, 0], [r * .55, 0], [r * .6, r * .15], [r * .95, r * .9], [r, r * 1.3], [r * .85, r * 2.1], [r * .42, r * 2.55], [r * .38, r * 2.8], [r * .6, r * 3], [r * .55, r * 3.05], [r * .32, r * 2.9], [.001, r * 2.9]], m, 0, 0, 0, 28);
    const band = c.c1 !== c.c0 ? c.c1 : shade(c.c0, .6);
    lathe(g, [[r * 1.003, r * 1.15], [r * 1.003, r * 1.45]], M('plain', band, { rough: .35, side: THREE.DoubleSide }), 0, 0, 0, 28);
    if (r > .14) for (const s of [-1, 1]) { const h = place(new THREE.Mesh(new THREE.TorusGeometry(r * .32, r * .06, 6, 14, Math.PI * 1.2), m), s * r * .62, r * 2.45, 0); h.rotation.z = s > 0 ? -.4 : Math.PI + .4; g.add(h); }
    return g;
  },
  // estatua: pedestal com molduras e figura de pe; bustos e cabecas ficam so com o busto
  statue(c) {
    const g = new THREE.Group(), st = M('stone', c.c0), dk = M('stone', shade(c.c0, .8));
    const H = clamp(c.H, .9, 2.4), ph = clamp(H * .22, .25, .45);
    pedestal(g, .5, ph, st, dk);
    if (has(c.n, /bust|\bhead\b/)) {
      lathe(g, [[.001, 0], [.2, 0], [.16, .1], [.08, .22], [.06, .3], [.001, .3]], st, 0, ph, 0, 18);
      sphere(g, .12, st, 0, ph + .4, 0);
      return g;
    }
    figure(g, st, ph, H - ph, c.it.id);
    return g;
  },
  // tapete: base tecida, barra em cor de destaque, medalhao central e franjas nas pontas
  rug(c, W = Math.min(1.8, Math.max(.6, c.fw)), D = Math.min(1.8, Math.max(.5, c.fw * .7))) {
    const g = new THREE.Group(), base = M('fabric', c.c0), acc = M('fabric', c.c1 !== c.c0 ? c.c1 : shade(c.c0, .6)), mid = M('fabric', c.c2);
    soft(g, W, .025, D, .01, base, 0, 0, 0);
    for (const [w, d] of [[W - .08, D - .08], [W - .2, D - .2]]) {
      box(g, w, .028, .04, acc, 0, 0, d / 2 - .02); box(g, w, .028, .04, acc, 0, 0, -d / 2 + .02);
      box(g, .04, .028, d, acc, w / 2 - .02, 0, 0); box(g, .04, .028, d, acc, -w / 2 + .02, 0, 0);
    }
    const md = place(new THREE.Mesh(new THREE.CylinderGeometry(Math.min(W, D) * .22, Math.min(W, D) * .22, .03, 6), mid), 0, .015, 0); md.scale.set(W / D, 1, 1); g.add(md);
    const fr = M('fabric', '#e8dcc0');
    for (const s of [-1, 1]) for (let i = 0; i < 14; i++) box(g, .06, .006, .012, fr, s * (W / 2 + .025), 0, -D / 2 + .03 + i * (D - .06) / 13);
    return g;
  },
};

// ---------------------------------------------------------------- navios
const SHIP = {
  sails(c) {
    const g = new THREE.Group(), geo = new THREE.PlaneGeometry(1.2, 1.2, 12, 8), p = geo.attributes.position;
    for (let i = 0; i < p.count; i++) p.setZ(i, Math.sin(p.getX(i) * 3) * .06 + .12 * (1 - (p.getY(i) / 1.2 + .5)) * .5);
    geo.computeVertexNormals();
    g.add(place(new THREE.Mesh(geo, M('fabric', c.light, { side: THREE.DoubleSide })), 0, .75, 0));
    box(g, .08, 1.7, .08, M('wood', '#5b3b22'), -.0, 0, -.05);
    return g;
  },
  hull(c) { const g = new THREE.Group(); box(g, 1, .4, 1, M('wood', c.c0), 0, 0, 0); return g; },
};

// ---------------------------------------------------------------- construtores guiados pela classe da imagem (CLIP)
const BOOKC = ['#7a2230', '#2e4a7a', '#2f6a45', '#7a5a2a', '#4a2f6a', '#8a3a1c', '#2a5a6a', '#6a6a2a'];
function bookshelf(c, W = .92) {
  const g = new THREE.Group(), wd = M('wood', c.c0), D = .32, H = 1.7, rows = 4;
  box(g, .05, H, D, wd, -W / 2 + .025, 0, 0); box(g, .05, H, D, wd, W / 2 - .025, 0, 0);
  box(g, W, .04, D, wd, 0, 0, 0); box(g, W + .04, .05, D + .03, wd, 0, H, 0); box(g, W - .05, H, .02, M('wood', shade(c.c0, .7)), 0, 0, -D / 2 + .01);
  for (let r = 0; r < rows; r++) {
    const y = .04 + r * (H - .04) / rows;
    if (r) box(g, W - .05, .035, D - .02, wd, 0, y, 0);
    let x = -W / 2 + .06; const sh = (H - .04) / rows - .05;
    while (x < W / 2 - .09) {
      const bw = .035 + c.r() * .045, bh = sh * (.6 + c.r() * .35);
      if (c.r() < .12) { x += .07; continue; }
      const col = BOOKC[Math.floor(c.r() * BOOKC.length)];
      const b = box(g, bw, bh, D * .75, M('leather', col), x + bw / 2, y + .035, 0);
      if (c.r() < .1) b.rotation.z = -.25;
      x += bw + .004;
    }
  }
  return g;
}
// cesto de vime: parede tramada (aneis alternados), aro grosso e alca em arco
function basket(c) {
  const g = new THREE.Group(), m = M('wood', c.c0, { rough: 1 }), dk = M('wood', shade(c.c0, .75), { rough: 1 });
  lathe(g, [[.001, 0], [.2, 0], [.27, .22], [.29, .26], [.26, .26], [.19, .03], [.001, .03]], m, 0, 0, 0, 24);
  for (let i = 1; i < 6; i++) { const t = i / 6; ring(g, .2 + .07 * t + .004, .007, i % 2 ? dk : m, 0, .22 * t, 0); }
  ring(g, .285, .018, dk, 0, .255, 0);
  for (let i = 0; i < 12; i++) { const a = i / 12 * 6.28; limb(g, .006, .006, .26, dk, new THREE.Vector3(Math.cos(a) * .2, 0, Math.sin(a) * .2), new THREE.Vector3(Math.cos(a) * .3, 1, Math.sin(a) * .3), 4); }
  const h = place(new THREE.Mesh(new THREE.TorusGeometry(.26, .016, 6, 20, Math.PI), m), 0, .26, 0); g.add(h);
  return g;
}
function banner(c) {
  const g = new THREE.Group(), geo = new THREE.PlaneGeometry(.55, 1.1, 10, 10), p = geo.attributes.position;
  for (let i = 0; i < p.count; i++) p.setZ(i, Math.sin(p.getY(i) * 5) * .03);
  geo.computeVertexNormals();
  g.add(place(new THREE.Mesh(geo, M('fabric', c.c0, { side: THREE.DoubleSide })), 0, .7, 0));
  box(g, .7, .04, .04, M('wood', '#5b3b22'), 0, 1.25, 0);
  return g;
}
function bones(c) {
  const g = new THREE.Group(), m = M('plain', '#e3dcc4', { rough: .7 });
  for (let i = 0; i < 6; i++) {
    const b = place(new THREE.Mesh(new THREE.CylinderGeometry(.015, .015, .2 + c.r() * .15, 6), m), (c.r() - .5) * .5, .02, (c.r() - .5) * .5);
    b.rotation.set(1.57, 0, c.r() * 3); g.add(b); sphere(g, .03, m, b.position.x + .1, .03, b.position.z);
  }
  sphere(g, .07, m, 0, .07, 0).scale.set(1, 1.1, 1.2);
  return g;
}
function gem(c) { const g = new THREE.Group(); g.add(place(new THREE.Mesh(new THREE.OctahedronGeometry(.08), M('plain', c.light, { emissive: c.light, ei: .25, rough: .1 })), 0, .1, 0)); return g; }
// tora deitada ao longo de z (girada por ry): casca + topos claros com aneis
function logPiece(g, r, len, bark, x, y, z, ry = 0) {
  const t = new THREE.Group();
  const body = new THREE.Mesh(new THREE.CylinderGeometry(r, r * 1.05, len, 14), M('wood', bark)); body.rotation.x = Math.PI / 2; t.add(body);
  const endM = M('wood', shade(bark, 1.9)), ringM = M('plain', shade(bark, 1.1), { rough: .9 });
  for (const s of [-1, 1]) {
    const e = new THREE.Mesh(new THREE.CircleGeometry(r * .97, 14), endM); e.position.z = s * (len / 2 + .002); e.rotation.y = s > 0 ? 0 : Math.PI; t.add(e);
    for (const k of [.35, .7]) { const rr = new THREE.Mesh(new THREE.RingGeometry(r * k, r * k + .008, 18), ringM); rr.position.z = s * (len / 2 + .004); rr.rotation.y = e.rotation.y; t.add(rr); }
  }
  t.position.set(x, y, z); t.rotation.y = ry;
  t.traverse(o => { if (o.isMesh) o.castShadow = o.receiveShadow = true; });
  g.add(t);
  return t;
}
function logs(c) {
  const g = new THREE.Group(), bark = woodTone([c.it]) || '#6b4a2b';
  logPiece(g, .09, .85, bark, -.1, .09, 0); logPiece(g, .09, .82, bark, .1, .09, .02); logPiece(g, .085, .8, bark, 0, .25, -.01);
  return g;
}
// tronco caido: tora grossa com toco de galho e musgo; L = comprimento (eixo z)
function fallenLog(c, L = clamp(c.fw * 1.1, .7, 1.4), r = .2) {
  const g = new THREE.Group(), bark = '#5e4630';
  logPiece(g, r, L, bark, 0, r * .85, 0, .15);
  limb(g, r * .35, r * .15, r * 2, M('wood', bark), new THREE.Vector3(.06, r * 1.3, L * .15), new THREE.Vector3(.6, 1, .2), 6);
  const moss = M('noisy', '#56783a');
  for (let i = 0; i < 4; i++) blob(g, r * (.35 + c.r() * .2), moss, (c.r() - .5) * r * .5, r * 1.7, (c.r() - .5) * L * .7, c.it.id + i, .35);
  return g;
}
function ore(c) { const g = new THREE.Group(); for (let i = 0; i < 3; i++) { const b = boulder({ ...c, it: { id: c.it.id + i } }, .22); b.position.set((i - 1) * .22, 0, (c.r() - .5) * .2); g.add(b); } return g; }
// lanterna: base e teto de ferro, montantes, vidros foscos, telhadinho conico com argola e vela acesa dentro
function lantern(c) {
  const g = new THREE.Group(), fe = M('metal', '#33363a', { rough: .5 }), gl = M('plain', '#f3d9a0', { opacity: .35, rough: .1 });
  lathe(g, [[.001, 0], [.11, 0], [.11, .03], [.09, .04], [.001, .04]], fe, 0, 0, 0, 8);
  for (let i = 0; i < 4; i++) { const a = i * Math.PI / 2 + Math.PI / 4; box(g, .016, .26, .016, fe, Math.cos(a) * .085, .04, Math.sin(a) * .085); }
  g.add(place(new THREE.Mesh(new THREE.CylinderGeometry(.08, .08, .25, 4, 1, true), gl), 0, .165, 0)).children.at(-1).rotation.y = Math.PI / 4;
  lathe(g, [[.001, .3], [.12, .3], [.06, .4], [.02, .42], [.001, .42]], fe, 0, 0, 0, 8);
  ring(g, .03, .007, fe, 0, .45, 0).children.at(-1).rotation.x = 0;
  lathe(g, [[.001, .04], [.025, .04], [.025, .14], [.001, .14]], M('plain', '#efe5c8', { rough: .6 }), 0, 0, 0, 10);
  flame(g, .02, .06, 0, .14, 0);
  return g;
}
// vela em castical de prato com alca, pingos de cera e chama
function candle(c) {
  const g = new THREE.Group(), br = M('metal', brassC, { rough: .3 }), wax = M('plain', '#efe5c8', { rough: .6 });
  lathe(g, [[.001, 0], [.09, 0], [.1, .015], [.085, .02], [.03, .025], [.025, .05], [.035, .06], [.001, .06]], br, 0, 0, 0, 18);
  const h = place(new THREE.Mesh(new THREE.TorusGeometry(.025, .006, 6, 12), br), .1, .02, 0); h.rotation.x = Math.PI / 2; g.add(h);
  lathe(g, [[.001, .06], [.028, .06], [.028, .25], [.022, .26], [.001, .26]], wax, 0, 0, 0, 12);
  for (let i = 0; i < 3; i++) { const a = i * 2.2; limb(g, .007, .004, .05 + i * .02, wax, new THREE.Vector3(Math.cos(a) * .027, .2, Math.sin(a) * .027), new THREE.Vector3(0, -1, 0), 5); }
  flame(g, .016, .06, 0, .265, 0);
  return g;
}
// braseiro: trempe de tres pes, bacia rebitada, brasas e chama
function brazier(c) {
  const g = new THREE.Group(), fe = M('metal', '#33363a', { rough: .5 });
  for (let i = 0; i < 3; i++) { const a = i * 2.094; limb(g, .02, .015, .52, fe, new THREE.Vector3(Math.cos(a) * .22, 0, Math.sin(a) * .22), new THREE.Vector3(-Math.cos(a) * .3, 1, -Math.sin(a) * .3), 6); }
  lathe(g, [[.001, .38], [.12, .38], [.26, .48], [.3, .56], [.27, .56], [.001, .46]], fe, 0, 0, 0, 22);
  ring(g, .29, .014, fe, 0, .55, 0);
  for (let i = 0; i < 9; i++) sphere(g, .05, M('plain', '#5a1c08', { emissive: '#ff4a10', ei: .7 }), (c.r() - .5) * .3, .52, (c.r() - .5) * .3);
  flame(g, .14, .45, 0, .52, 0);
  const pl = new THREE.PointLight(0xffa040, .7, 2.5); pl.position.set(0, .9, 0); g.add(pl);
  return g;
}
function grassTuft(c) {
  const g = new THREE.Group(), m = M('noisy', hexLum(c.c0) < .7 ? c.c0 : '#5a9a44', { side: THREE.DoubleSide });
  for (let i = 0; i < 14; i++) {
    const h = .2 + c.r() * .25, b = place(new THREE.Mesh(new THREE.ConeGeometry(.025, h, 4), m), (c.r() - .5) * .45, h / 2, (c.r() - .5) * .45);
    b.rotation.set((c.r() - .5) * .5, 0, (c.r() - .5) * .5); g.add(b);
  }
  return g;
}
function cactus(c) {
  const g = new THREE.Group(), m = M('noisy', '#4f8a4a');
  g.add(place(new THREE.Mesh(new THREE.CapsuleGeometry(.1, .8, 6, 12), m), 0, .5, 0));
  for (const s of [-1, 1]) { box(g, .2, .08, .08, m, s * .15, .4 + (s > 0 ? .1 : 0), 0); g.add(place(new THREE.Mesh(new THREE.CapsuleGeometry(.05, .25, 4, 8), m), s * .25, .65 + (s > 0 ? .1 : 0), 0)); }
  return g;
}
function cart(c) {
  const g = new THREE.Group(), m = M('wood', c.c0);
  box(g, 1.1, .3, .7, m, 0, .3, 0);
  for (const z of [-.4, .4]) { const w = place(new THREE.Mesh(new THREE.CylinderGeometry(.28, .28, .06, 18), m), 0, .28, z); w.rotation.x = 1.57; g.add(w); }
  box(g, .9, .04, .04, m, -.9, .3, 0);
  return g;
}
function anvil(c) {
  const g = new THREE.Group(), m = M('metal', '#4a4d52', { rough: .4 });
  box(g, .5, .08, .3, m, 0, .35, 0); box(g, .22, .28, .22, m, 0, .07, 0); box(g, .4, .07, .3, m, 0, 0, 0);
  const h = place(new THREE.Mesh(new THREE.ConeGeometry(.1, .25, 4), m), .36, .4, 0); h.rotation.z = -1.57; g.add(h);
  return g;
}
function forge(c) {
  const g = new THREE.Group(), m = M('stone', c.c0);
  box(g, 1, .6, .8, m, 0, 0, 0); box(g, .6, .3, .5, M('plain', '#1a1412'), 0, .6, .1);
  g.add(place(new THREE.Mesh(new THREE.ConeGeometry(.2, .3, 8), M('plain', '#ffb030', { emissive: '#ff6a10', ei: 1.4 })), 0, .75, .1));
  box(g, .6, 1.1, .5, m, 0, .6, -.15);
  return g;
}
function well(c) {
  const g = new THREE.Group(), m = M('stone', c.c0);
  lathe(g, [[.35, 0], [.5, 0], [.5, .55], [.35, .55]], m, 0, 0, 0, 24);
  const w = place(new THREE.Mesh(new THREE.CircleGeometry(.36, 20), M('plain', '#1f3a4a', { rough: .1 })), 0, .4, 0); w.rotation.x = -1.57; g.add(w);
  for (const s of [-1, 1]) box(g, .07, 1.1, .07, M('wood', '#5b3b22'), s * .45, .55, 0);
  box(g, 1.05, .06, .3, M('wood', '#5b3b22'), 0, 1.6, 0);
  return g;
}
function fountain(c) {
  const g = new THREE.Group(), m = M('stone', c.c0);
  lathe(g, [[.001, 0], [.6, 0], [.6, .3], [.5, .3], [.001, .25]], m, 0, 0, 0, 28);
  lathe(g, [[.001, .25], [.12, .25], [.08, .9], [.28, .95], [.001, .95]], m, 0, 0, 0, 20);
  const w = place(new THREE.Mesh(new THREE.CircleGeometry(.5, 24), M('plain', '#3a7a98', { opacity: .75, rough: .05 })), 0, .27, 0); w.rotation.x = -1.57; g.add(w);
  return g;
}
function tent(c) {
  const g = new THREE.Group(), t = place(new THREE.Mesh(new THREE.ConeGeometry(.7, .9, 4, 1, true), M('fabric', c.c0, { side: THREE.DoubleSide })), 0, .45, 0);
  t.rotation.y = Math.PI / 4; g.add(t);
  return g;
}
// par de botas: cano arredondado com dobra, peito do pe, sola e salto
function boots(c) {
  const g = new THREE.Group(), m = M('leather', c.c0), sole = M('leather', shade(c.c0, .45));
  for (const s of [-1, 1]) {
    const x = s * .09;
    soft(g, .1, .26, .1, .035, m, x, .04, -.02);
    soft(g, .11, .07, .12, .03, m, x, .265, -.02);
    soft(g, .095, .085, .17, .04, m, x, .04, .07);
    box(g, .1, .025, .25, sole, x, .015, .03); box(g, .09, .04, .06, sole, x, 0, -.06);
  }
  return g;
}
// chapeu: aba com caimento e copa com fita; chapeu de mago vira cone torto
function hat(c) {
  const g = new THREE.Group(), m = M('fabric', c.c0), band = M('fabric', c.c1 !== c.c0 ? c.c1 : shade(c.c0, .55));
  lathe(g, [[.001, 0], [.3, 0], [.3, .02], [.14, .04], [.001, .04]], m, 0, 0, 0, 28);
  if (has(c.n, /wizard|witch|magic|pointed/)) {
    const cn = place(new THREE.Mesh(new THREE.ConeGeometry(.14, .5, 18, 6), m), 0, .28, 0); const p = cn.geometry.attributes.position;
    for (let i = 0; i < p.count; i++) { const t = (p.getY(i) + .25) / .5; p.setX(i, p.getX(i) + t * t * .12); }
    cn.geometry.computeVertexNormals(); g.add(cn);
  } else lathe(g, [[.001, .03], [.14, .03], [.13, .2], [.11, .26], [.001, .28]], m, 0, 0, 0, 20);
  lathe(g, [[.142, .04], [.137, .09]], band, 0, 0, 0, 20);
  return g;
}
function cloak(c) {
  const g = new THREE.Group(), geo = new THREE.PlaneGeometry(.7, 1.1, 14, 8), p = geo.attributes.position;
  for (let i = 0; i < p.count; i++) p.setZ(i, Math.sin(p.getX(i) * 9) * .05);
  geo.computeVertexNormals();
  g.add(place(new THREE.Mesh(geo, M('fabric', c.c0, { side: THREE.DoubleSide })), 0, .6, 0));
  return g;
}
function necklace(c) {
  const g = new THREE.Group(), t = place(new THREE.Mesh(new THREE.TorusGeometry(.14, .008, 6, 24), M('metal', '#d4af37', { rough: .25 })), 0, .14, 0);
  t.rotation.x = 1.4; g.add(t);
  sphere(g, .035, M('plain', c.light, { emissive: c.light, ei: .3, rough: .1 }), 0, .02, .1);
  return g;
}
function dresserMirror(c) {
  const g = FURN.cabinet({ ...c, H: .9 });
  const m = place(new THREE.Mesh(new THREE.CylinderGeometry(.28, .28, .03, 24), M('wood', c.c0)), 0, 1.25, -.12); m.rotation.x = 1.57; g.add(m);
  g.add(place(new THREE.Mesh(new THREE.CircleGeometry(.24, 24), M('plain', '#cfdde6', { metal: .9, rough: .05 })), 0, 1.25, -.1));
  return g;
}
function catapult(c) {
  const g = new THREE.Group(), m = M('wood', c.c0);
  box(g, .8, .12, 1.3, m, 0, .15, 0);
  for (const s of [-1, 1]) { box(g, .08, .7, .08, m, s * .3, .2, -.1); const w = place(new THREE.Mesh(new THREE.CylinderGeometry(.2, .2, .05, 14), m), s * .45, .2, .3); w.rotation.z = 1.57; g.add(w); }
  box(g, .08, .08, 1.2, m, 0, .85, -.1).rotation.x = -.5;
  return g;
}
const named = (fn, label) => c => fn({ ...c, n: label + ' ' + c.n });
const BY_LABEL = {
  tree: VEG.tree, palm: named(VEG.tree, 'palm'), deadtree: named(VEG.tree, 'dead'), bush: VEG.bush, flower: VEG.flower, crop: VEG.crop, mushroom: VEG.mushroom,
  grass: grassTuft, cactus,
  boulder: ROCK.boulder, crystal: ROCK.crystal, bones,
  table: FURN.table, chair: named(FURN.chair, 'chair'), bench: named(FURN.chair, 'bench'), stool: named(FURN.chair, 'stool'),
  bed: FURN.bed, wardrobe: FURN.cabinet, bookcase: bookshelf, shelf: FURN.shelf, dresser: dresserMirror, throne: named(FURN.chair, 'throne'),
  chest: CONT.chest, crate: CONT.crate, barrel: CONT.barrel, bag: CONT.bag, basket,
  vase: DECO.vase, statue: DECO.statue, rug: DECO.rug, banner,
  sword: WEAP.sword, dagger: WEAP.dagger, axe: WEAP.axe, mace: WEAP.mace, bow: WEAP.bow, staff: WEAP.staff, polearm: WEAP.polearm, cannon: WEAP.siege, catapult,
  breastplate: ARMOR.body, helm: ARMOR.helm, shield: ARMOR.shield, boots, robe: CLOTH.robe, hat, cloak, ring: JEWEL.ring, necklace,
  potion: CONS.potion, bread: named(CONS.food, 'bread'), fruit: named(CONS.food, 'fruit'), meat: named(CONS.food, 'meat'), reagent: CONS.reagent, gem,
  tool: tool, pickaxe: named(tool, 'pick'), pot: named(tool, 'pot'), key: named(tool, 'pick'), ingot: RES.ingot, log: logs, ore,
  cloth: c => { const g = new THREE.Group(); soft(g, .4, .1, .3, .03, M('fabric', c.c0), 0, 0, 0); return g; },
  torch: LIGHT.torch, lantern, candle, brazier, book: DOC.book, scroll: named(DOC.book, 'scroll'), books: DOC.book,
  wall: ARCH.wall, floor: ARCH.floor, roof: ARCH.roof, stairs: ARCH.stairs, door: ARCH.door, window: ARCH.window, arch: ARCH.arch, column: ARCH.column, fence: ARCH.fence, bridge: ARCH.bridge,
  water: TERR.water, lava: TERR.lava, ground: TERR.ground, sails: SHIP.sails, hull: SHIP.hull,
  cart, wheel: c => { const g = new THREE.Group(), w = place(new THREE.Mesh(new THREE.CylinderGeometry(.4, .4, .06, 20), M('wood', c.c0)), 0, .4, 0); w.rotation.x = 1.57; g.add(w); return g; },
  anvil, forge, well, fountain, tent, pillar: c => ARCH.column({ ...c, H: 2.4 }),
};
// categoria do taxonomy a que cada classe da imagem pertence (para checar se imagem e nome concordam)
const G = (cat, ...ls) => ls.forEach(l => (LABEL_CAT[l] = cat));
const LABEL_CAT = {};
G('vegetation', 'tree', 'palm', 'deadtree', 'bush', 'flower', 'crop', 'mushroom', 'grass', 'cactus');
G('rock', 'boulder', 'crystal', 'ore'); G('furniture', 'table', 'chair', 'bench', 'stool', 'bed', 'wardrobe', 'bookcase', 'shelf', 'dresser', 'throne');
G('container', 'chest', 'crate', 'barrel', 'bag', 'basket'); G('decoration', 'vase', 'statue', 'painting', 'rug', 'banner', 'sign', 'bones', 'fountain', 'well');
G('weapon', 'sword', 'dagger', 'axe', 'mace', 'bow', 'staff', 'polearm', 'cannon', 'catapult'); G('armor', 'breastplate', 'helm', 'shield', 'boots');
G('clothing', 'robe', 'hat', 'cloak'); G('jewelry', 'ring', 'necklace', 'gem'); G('consumable', 'potion', 'bread', 'fruit', 'meat', 'reagent');
G('tool', 'tool', 'pickaxe', 'pot', 'key', 'anvil'); G('resource', 'ingot', 'log', 'cloth'); G('light', 'torch', 'lantern', 'candle', 'brazier');
G('document', 'book', 'scroll', 'books');
G('architecture', 'wall', 'floor', 'roof', 'stairs', 'door', 'window', 'arch', 'column', 'fence', 'bridge', 'pillar', 'tent', 'forge', 'cart', 'wheel');
G('terrain', 'water', 'lava', 'ground'); G('ship', 'sails', 'hull'); G('effect', 'fire', 'magic', 'smoke', 'web', 'blood');
const STRUCT = new Set(['architecture', 'terrain', 'ship']);
const WEAK = new Set(['unknown', 'effect']);
const NOT_PLANT = /bottle|potion|flask|crystal|wine|armor|kilt|chest|sail|ship|wall|floor|tent|log|painting|nox|gas|light|robe|cloth|sprout/;

// escolhe a classe final: a imagem manda quando concorda com o nome/categoria ou quando tem muita confianca
function pickLabel(it) {
  if (it.cat === 'architecture' && ARCH[it.sub]) return null;   // construcao: nome/subtipo mandam, a imagem so atrapalha (parede virava coluna)
  if (/book ?case|book ?shelf/i.test(it.name || '')) return 'bookcase';
  const top = it.cl && it.cl[0], cat = it.cat;
  const p = top ? top[1] : 0, lab = top ? top[0] : null, lc = lab && LABEL_CAT[lab];
  if (lab && p >= .3) {
    if (lc === cat) return lab;                                   // imagem e nome concordam: refina o subtipo
    if (STRUCT.has(cat)) { if (STRUCT.has(lc) && p >= .45) return lab; }       // construcao: so troca por outra construcao
    else if (WEAK.has(cat) || p >= .85) { if (!STRUCT.has(lc) || p >= .85) return lab; }   // categoria do nome so cede a imagem com muita certeza
    else if (lc !== cat && it.sub === 'misc' && p >= .4) return lab;
  }
  // verde dominante na imagem: planta, mesmo que o nome diga outra coisa
  const gr = it.f && it.f.gr;
  if (gr > .45 && cat !== 'vegetation' && cat !== 'terrain' && !NOT_PLANT.test((it.name || '').toLowerCase())) return 'bush';
  if (cat === 'furniture' && lab === 'bookcase' && p >= .2) return lab;
  return null;
}

// ---------------------------------------------------------------- pecas feitas a mao por nome (pegam antes da classificacao pela imagem)
function clothPlane(w, h, mat, y) {
  const geo = new THREE.PlaneGeometry(w, h, 12, 8), p = geo.attributes.position;
  for (let i = 0; i < p.count; i++) p.setZ(i, Math.sin(p.getX(i) * 11) * .025);
  geo.computeVertexNormals();
  return place(new THREE.Mesh(geo, mat), 0, y, 0);
}
function hanging(c) {
  const g = new THREE.Group(), w = Math.min(1.4, Math.max(.4, c.fw)), h = Math.min(1.8, Math.max(.6, c.H));
  const wd = M('wood', '#5b3b22');
  g.add(clothPlane(w, h, M('fabric', c.c0, { side: THREE.DoubleSide }), h / 2 + .35));
  box(g, w + .12, .05, .05, wd, 0, h + .35, 0);
  g.add(place(new THREE.Mesh(new THREE.PlaneGeometry(w, .08), M('fabric', c.c1, { side: THREE.DoubleSide })), 0, .4, .01));
  for (const s of [-1, 1]) sphere(g, .035, M('metal', '#d4af37', { rough: .3 }), s * (w / 2 + .07), h + .375, 0);
  return g;
}
function painting(c) {
  const g = new THREE.Group(), w = Math.min(1.1, Math.max(.4, c.fw)), h = Math.min(1.2, Math.max(.4, c.H * .9));
  const wd = M('wood', c.c0), au = M('metal', brassC, { rough: .3 }), y0 = .3;
  // moldura em dois degraus (madeira por fora, filete dourado por dentro) e fundo
  box(g, w + .16, .08, .06, wd, 0, y0 + h, 0); box(g, w + .16, .08, .06, wd, 0, y0 - .08, 0);
  box(g, .08, h, .06, wd, -w / 2 - .04, y0, 0); box(g, .08, h, .06, wd, w / 2 + .04, y0, 0);
  box(g, w + .02, .02, .07, au, 0, y0 + h - .01, 0); box(g, w + .02, .02, .07, au, 0, y0 - .01, 0);
  box(g, .02, h, .07, au, -w / 2 - .005, y0, 0); box(g, .02, h, .07, au, w / 2 + .005, y0, 0);
  box(g, w, h, .02, M('wood', shade(c.c0, .6)), 0, y0, -.02);
  // tela: ceu, sol, colinas em duas camadas
  const z = .006, sky = hexLum(c.c1) > hexLum(c.c2) ? c.c1 : c.c2, land = sky === c.c1 ? c.c2 : c.c1;
  g.add(place(new THREE.Mesh(new THREE.PlaneGeometry(w, h), M('plain', sky, { rough: .9 })), 0, y0 + h / 2, z));
  g.add(place(new THREE.Mesh(new THREE.CircleGeometry(Math.min(w, h) * .11, 18), M('plain', c.light, { rough: .9 })), w * .22, y0 + h * .72, z + .001));
  for (const [k, col, amp] of [[.55, shade(land, 1.15), .12], [.35, land, .09]]) {
    const s = new THREE.Shape(); s.moveTo(-w / 2, 0);
    for (let i = 0; i <= 12; i++) { const x = -w / 2 + i * w / 12; s.lineTo(x, h * (k - .2 + amp * Math.sin(i * .9 + k * 9))); }
    s.lineTo(w / 2, 0); s.closePath();
    g.add(place(new THREE.Mesh(new THREE.ShapeGeometry(s), M('plain', col, { rough: .9 })), 0, y0, z + (k < .5 ? .003 : .002)));
  }
  return g;
}
// balanca: base, coluna, travessao e dois pratos pendurados
function scales(c) {
  const g = new THREE.Group(), br = M('metal', brassC, { rough: .3 }), wd = M('wood', '#5b3b22');
  box(g, .3, .04, .18, wd, 0, 0, 0);
  lathe(g, [[.001, .04], [.02, .04], [.015, .45], [.03, .47], [.001, .48]], br, 0, 0, 0, 10);
  box(g, .5, .015, .015, br, 0, .45, 0);
  for (const s of [-1, 1]) {
    for (const k of [-1, 1]) limb(g, .002, .002, .2, br, new THREE.Vector3(s * .24, .455, 0), new THREE.Vector3(k * .25, -1, 0), 3);
    lathe(g, [[.001, .24], [.08, .26], [.085, .27], [.001, .25]], br, s * .24, 0, 0, 16);
  }
  return g;
}
// feixe de flechas: hastes, pontas de ferro e penas
function arrows(c) {
  const g = new THREE.Group(), w = M('wood', '#9a7a4a'), fe = M('metal', '#6a7078'), fe2 = M('plain', '#e8e0d0', { side: THREE.DoubleSide });
  for (let i = 0; i < 6; i++) {
    const y = (i % 3 - 1) * .018, z = (Math.floor(i / 3) - .5) * .02;
    rod(g, .005, .005, .7, w, 0, y, z, 5); rod(g, .012, .001, .05, fe, .37, y, z, 5);
    for (const a of [0, 2.1, 4.2]) { const f = place(new THREE.Mesh(new THREE.PlaneGeometry(.08, .02), fe2), -.3, y + Math.cos(a) * .01, z + Math.sin(a) * .01); f.rotation.x = a; g.add(f); }
  }
  return lay(g, .03);
}
// roupas e miudezas por nome
function pants(c) {
  const g = new THREE.Group(), metal = has(c.n, /plate|chain|ring/), m = M(metal ? 'metal' : 'fabric', metal ? steelTone(c) : c.c0, { rough: .6 });
  lathe(g, [[.001, .62], [.17, .62], [.18, .5], [.001, .5]], m, 0, 0, 0, 18);
  for (const s of [-1, 1]) limb(g, .09, .065, .55, m, new THREE.Vector3(s * .085, .52, 0), new THREE.Vector3(s * .08, -1, 0), 12);
  ring(g, .17, .015, M('leather', '#3a2a1a'), 0, .6, 0);
  return g;
}
function skirt(c) {
  const g = new THREE.Group(), m = M('fabric', c.c0), n = 24, prof = [[.001, .62], [.16, .62], [.2, .4], [.3, .02], [.001, .02]];
  const geo = new THREE.LatheGeometry(prof.map(([r, y]) => new THREE.Vector2(r, y)), n * 2), p = geo.attributes.position;
  for (let i = 0; i < p.count; i++) { const a = Math.atan2(p.getZ(i), p.getX(i)), t = 1 - p.getY(i) / .62, k = 1 + .08 * t * Math.sin(a * 12); p.setX(i, p.getX(i) * k); p.setZ(i, p.getZ(i) * k); }
  geo.computeVertexNormals();
  g.add(place(new THREE.Mesh(geo, m), 0, 0, 0));
  ring(g, .16, .015, M('leather', '#3a2a1a'), 0, .6, 0);
  return g;
}
function horseshoes(c) {
  const g = new THREE.Group(), fe = M('metal', '#5a5f66', { rough: .5 });
  for (const s of [-1, 1]) { const h = place(new THREE.Mesh(new THREE.TorusGeometry(.08, .016, 6, 18, Math.PI * 1.35), fe), s * .1, .016, 0); h.rotation.set(-Math.PI / 2, 0, s * .5 - Math.PI * .17); g.add(h); }
  return g;
}
function bracelet(c) {
  const g = new THREE.Group(), au = M('metal', '#d4af37', { rough: .22 });
  g.add(place(new THREE.Mesh(new THREE.TorusGeometry(.09, .018, 10, 32), au), 0, .02, 0)).children.at(-1).rotation.x = Math.PI / 2;
  for (let i = 0; i < 5; i++) { const a = i / 5 * 6.28; g.add(place(new THREE.Mesh(new THREE.OctahedronGeometry(.016), M('plain', c.light || '#5ab0e0', { emissive: c.light || '#5ab0e0', ei: .3, rough: .1 })), Math.cos(a) * .09, .04, Math.sin(a) * .09)); }
  return g;
}
function earrings(c) {
  const g = new THREE.Group(), au = M('metal', '#d4af37', { rough: .22 });
  for (const s of [-1, 1]) { ring(g, .025, .004, au, s * .05, .03, 0).children.at(-1).rotation.x = 0; g.add(place(new THREE.Mesh(new THREE.OctahedronGeometry(.016), M('plain', c.light || '#e04a5a', { rough: .1 })), s * .05, .01, 0)); }
  return g;
}
function fishingPole(c) {
  const g = new THREE.Group(), w = M('wood', '#8a6a3a');
  rod(g, .018, .006, 1.5, w, 0, 0, 0, 8);
  for (const x of [-.2, .2, .55]) band(g, .012, .004, M('metal', '#5a5f66'), x);
  const reel = place(new THREE.Mesh(new THREE.CylinderGeometry(.04, .04, .03, 14), M('metal', '#5a5f66')), -.45, -.04, 0); g.add(reel);
  g.add(place(new THREE.Mesh(new THREE.CylinderGeometry(.0015, .0015, .5, 3), M('plain', '#ddd')), .75, -.25, 0));
  return lay(g, .02);
}
function fishNet(c) {
  const g = new THREE.Group(), geo = new THREE.PlaneGeometry(.9, .9, 14, 14), p = geo.attributes.position;
  for (let i = 0; i < p.count; i++) p.setZ(i, .04 * Math.sin(p.getX(i) * 9) * Math.cos(p.getY(i) * 7) + .02);
  geo.computeVertexNormals();
  const m = place(new THREE.Mesh(geo, M('plain', '#b8a27a', { rough: 1, side: THREE.DoubleSide, opacity: .9 })), 0, .02, 0); m.rotation.x = -Math.PI / 2; m.material.wireframe = true; g.add(m);
  for (let i = 0; i < 6; i++) sphere(g, .03, M('wood', '#9a6a3a'), -.42 + i * .17, .03, .45);
  return g;
}
// cranio: calota, face, orbitas e cavidade nasal escuras, mandibula; varios viram pilha
function skullPile(c, n = 7) {
  const g = new THREE.Group(), b = M('plain', '#e3dcc4', { rough: .7 }), dk = M('plain', '#2a2218', { rough: 1 });
  for (let i = 0; i < n; i++) {
    const s = new THREE.Group(), k = n > 1 ? .7 + c.r() * .3 : 1;
    sphere(s, .1, b, 0, .1, -.01).children.at(-1).scale.set(.9, .95, 1.05);
    soft(s, .1, .06, .06, .02, b, 0, .02, .06);
    for (const sx of [-1, 1]) sphere(s, .024, dk, sx * .035, .1, .085);
    sphere(s, .012, dk, 0, .065, .1);
    s.scale.setScalar(k);
    const a = i * 2.4, rr = n > 1 ? .12 + (i % 3) * .1 : 0;
    s.position.set(Math.cos(a) * rr, i > 4 ? .15 : 0, Math.sin(a) * rr); s.rotation.y = c.r() * 2 - 1 + a * .2;
    g.add(s);
  }
  return g;
}
const NOT_TEMPL = /\bcounter\b|display case|cauldron|kettle|\bchest\b|drawers|\btub\b|basin|bucket|\bpail\b|casket|coffer/;
// tina de aduelas: parede de tabuas, dois aros, agua quando e de lavar
function tub(c) {
  const g = new THREE.Group(), m = M('wood', woodTone([c.it]) || c.c0), fe = M('metal', '#4a4d52', { rough: .45 }), r = clamp(c.fw * .4, .2, .45), h = r * .9;
  lathe(g, [[.001, 0], [r * .9, 0], [r, h], [r * .93, h], [r * .84, h * .15], [.001, h * .15]], m, 0, 0, 0, 26);
  for (const k of [.25, .8]) ring(g, r * (.9 + .1 * k) + .006, .012, fe, 0, h * k, 0);
  if (has(c.n, /wash|water|bath/)) { const w = place(new THREE.Mesh(new THREE.CircleGeometry(r * .88, 24), M('plain', '#5a8aa8', { opacity: .8, rough: .05 })), 0, h * .7, 0); w.rotation.x = -Math.PI / 2; g.add(w); }
  return g;
}
function telescope(c) {
  const g = new THREE.Group(), br = M('metal', '#b08a3a', { rough: .3 }), wd = M('wood', c.c0);
  for (let i = 0; i < 3; i++) {
    const a = i * 2.094;
    box(g, .05, .75, .05, wd, Math.cos(a) * .14, 0, Math.sin(a) * .14).children.at(-1).rotation.set(Math.sin(a) * .22, 0, -Math.cos(a) * .22);
  }
  const t = place(new THREE.Mesh(new THREE.CylinderGeometry(.06, .08, .9, 14), br), .1, .95, 0); t.rotation.z = 1.05; g.add(t);
  const t2 = place(new THREE.Mesh(new THREE.CylinderGeometry(.09, .09, .06, 14), br), .46, 1.1, 0); t2.rotation.z = 1.05; g.add(t2);
  return g;
}
function skeleton(c) {
  const g = new THREE.Group(), b = M('plain', '#e6dfc8', { rough: .7 });
  sphere(g, .09, b, -.3, .1, 0);
  for (let i = 0; i < 5; i++) { const r = place(new THREE.Mesh(new THREE.TorusGeometry(.1, .012, 5, 14, Math.PI), b), -.12 + i * .06, .1, 0); r.rotation.set(0, 1.57, 0); g.add(r); }
  const sp = place(new THREE.Mesh(new THREE.CylinderGeometry(.015, .015, .5, 6), b), -.04, .04, 0); sp.rotation.z = 1.57; g.add(sp);
  for (const [x, z, a] of [[.3, .1, .4], [.3, -.1, -.4], [-.15, .22, 1.2], [-.15, -.22, -1.2]]) {
    const l = place(new THREE.Mesh(new THREE.CylinderGeometry(.015, .015, .32, 6), b), x, .03, z); l.rotation.z = 1.57; l.rotation.y = a; g.add(l);
  }
  return g;
}
function corpse(c) {
  const g = new THREE.Group(), f = M('fabric', c.c0), sk = M('plain', '#c9a07a', { rough: .8 });
  soft(g, .32, .14, .6, .06, f, 0, 0, 0); sphere(g, .09, sk, 0, .12, -.38);
  for (const s of [-1, 1]) { soft(g, .08, .08, .36, .03, M('fabric', c.c1), s * .1, 0, .46); soft(g, .07, .07, .3, .03, f, s * .22, 0, -.05); }
  return g;
}
function lighthouse(c) {
  const g = new THREE.Group(), st = M('stone', '#e8e4da'), red = M('stone', '#a13a30');
  lathe(g, [[.001, 0], [.48, 0], [.4, 1.1], [.38, 1.6], [.3, 2.8], [.001, 2.8]], st, 0, 0, 0, 24);
  for (const [y0, y1, r0, r1] of [[.5, .9, .44, .41], [1.4, 1.8, .38, .36], [2.1, 2.5, .34, .31]]) lathe(g, [[r0, y0], [r1, y1], [r1 - .01, y1], [r0 - .01, y0]], red, 0, 0, 0, 24);
  box(g, .8, .06, .8, red, 0, 2.8, 0);
  lathe(g, [[.2, 2.86], [.2, 3.3], [.16, 3.3], [.16, 2.86]], M('plain', '#ffe9a0', { emissive: '#ffcf60', ei: 1.2, opacity: .9 }), 0, 0, 0, 14);
  g.add(place(new THREE.Mesh(new THREE.ConeGeometry(.28, .3, 14), red), 0, 3.45, 0));
  return g;
}
function gravestone(c) {
  const g = new THREE.Group(), st = M('stone', c.c0);
  box(g, .42, .55, .09, st, 0, 0, 0);
  const t = place(new THREE.Mesh(new THREE.CylinderGeometry(.21, .21, .09, 18, 1, false, 0, Math.PI), st), 0, .55, 0); t.rotation.x = Math.PI / 2; g.add(t);
  box(g, .5, .08, .26, st, 0, 0, 0);
  return g;
}
function grave(c) {
  const g = new THREE.Group(), st = M('stone', c.c0);
  const mound = place(new THREE.Mesh(new THREE.SphereGeometry(.4, 16, 8, 0, 6.28, 0, 1.2), M('noisy', '#5a4630')), 0, 0, .2); mound.scale.set(.7, .35, 1.4); g.add(mound);
  box(g, .36, .45, .07, st, 0, 0, -.5);
  return g;
}
function moongate(c) {
  const g = new THREE.Group(), st = M('stone', '#8a8f9a');
  g.add(place(new THREE.Mesh(new THREE.TorusGeometry(.5, .06, 10, 32), st), 0, .6, 0));
  g.add(place(new THREE.Mesh(new THREE.CircleGeometry(.5, 32), M('plain', c.c1, { emissive: c.c1, ei: 1, opacity: .7 })), 0, .6, 0));
  box(g, .8, .06, .25, st, 0, 0, 0);
  return g;
}
function shipBow(c) {
  const g = new THREE.Group(), wd = M('wood', c.c0);
  for (let i = 0; i < 5; i++) { const r = place(new THREE.Mesh(new THREE.TorusGeometry(.5 - i * .06, .03, 5, 14, Math.PI * .9), wd), 0, .1, -.4 + i * .22); r.rotation.set(0, 0, Math.PI * .05); g.add(r); }
  box(g, .08, .08, 1.1, wd, 0, .02, 0);
  box(g, .06, .8, .06, wd, 0, .05, -.5).children.at(-1).rotation.x = .5;
  for (const s of [-1, 1]) for (let j = 0; j < 3; j++) box(g, .03, .06, .55, wd, s * (.3 - j * .02), .15 + j * .15, -.1);
  return g;
}
function tiller(c) { const g = new THREE.Group(), wd = M('wood', c.c0); box(g, .08, .1, .9, wd, 0, .25, 0); sphere(g, .06, M('metal', '#b08a3a'), 0, .3, .45); box(g, .12, .3, .12, wd, 0, 0, -.35); return g; }
function prow(c) {
  const g = new THREE.Group(), wd = M('wood', c.c0);
  lathe(g, [[.001, 0], [.2, 0], [.14, .4], [.18, .8], [.1, 1.1], [.001, 1.1]], wd, 0, 0, 0, 14);
  const h = place(new THREE.Mesh(new THREE.ConeGeometry(.1, .35, 8), wd), 0, 1.15, .2); h.rotation.x = 1.2; g.add(h);
  for (const s of [-1, 1]) sphere(g, .03, M('plain', '#e03a2a', { emissive: '#c02010', ei: .8 }), s * .06, 1.2, .1);
  return g;
}
function web(c) {
  const g = new THREE.Group(), m = M('plain', '#e8e8e8', { opacity: .6 });
  for (let i = 0; i < 8; i++) {
    const a = i * Math.PI / 4, l = place(new THREE.Mesh(new THREE.CylinderGeometry(.004, .004, .5, 4), m), Math.cos(a) * .25, .55 + Math.sin(a) * .25, 0);
    l.rotation.z = a - Math.PI / 2; g.add(l);
  }
  for (const r of [.15, .3]) g.add(place(new THREE.Mesh(new THREE.TorusGeometry(r, .004, 4, 16), m), 0, .55, 0));
  return g;
}
function magicRing(c) {
  const g = new THREE.Group(), em = M('plain', c.c1, { emissive: c.c1, ei: .9 });
  const r = place(new THREE.Mesh(new THREE.TorusGeometry(.42, .015, 6, 40), em), 0, .02, 0); r.rotation.x = Math.PI / 2; g.add(r);
  const r2 = place(new THREE.Mesh(new THREE.TorusGeometry(.3, .012, 6, 5), em), 0, .02, 0); r2.rotation.x = Math.PI / 2; g.add(r2);
  const d = place(new THREE.Mesh(new THREE.CircleGeometry(.4, 30), M('plain', c.c0, { opacity: .35 })), 0, .01, 0); d.rotation.x = -Math.PI / 2; g.add(d);
  return g;
}
function sinkhole(c) {
  const g = new THREE.Group();
  lathe(g, [[.5, 0], [.5, .05], [.3, .02], [.001, -.15]], M('noisy', '#3a2a1a'), 0, .06, 0, 20);
  const d = place(new THREE.Mesh(new THREE.CircleGeometry(.3, 20), M('plain', '#0a0806')), 0, .04, 0); d.rotation.x = -Math.PI / 2; g.add(d);
  return g;
}
function treasure(c) {
  const g = CONT.chest({ ...c, c0: '#6b4423' });
  for (let i = 0; i < 9; i++) sphere(g, .045, M('metal', '#e0b93a', { rough: .25 }), (c.r() - .5) * .5 + .45, .03 + c.r() * .05, (c.r() - .5) * .5);
  return g;
}
function refuse(c) {
  const g = new THREE.Group();
  for (let i = 0; i < 9; i++) {
    soft(g, .1 + c.r() * .15, .05 + c.r() * .08, .1 + c.r() * .15, .02, M(i % 2 ? 'fabric' : 'noisy', i % 3 ? c.c0 : c.c2), (c.r() - .5) * .5, c.r() * .1, (c.r() - .5) * .5);
    g.children.at(-1).rotation.y = c.r() * 3;
  }
  return g;
}
function stain(c) { const g = new THREE.Group(), d = place(new THREE.Mesh(new THREE.CircleGeometry(.3, 14), M('plain', c.c0, { rough: .4 })), 0, .012, 0); d.rotation.x = -Math.PI / 2; d.scale.set(1, 1 + c.r() * .5, 1); g.add(d); return g; }
function marker(c) { const g = new THREE.Group(); box(g, .9, .03, .9, M('plain', c.c0, { rough: .8 }), 0, 0, 0); box(g, .2, .045, .2, M('plain', c.light), 0, 0, 0); return g; }
function rugRound(c) { const g = new THREE.Group(); lathe(g, [[.001, .03], [.5, .03], [.5, .0], [.001, 0]], M('fabric', c.c0), 0, 0, 0, 24); lathe(g, [[.001, .035], [.35, .035], [.35, .03]], M('fabric', c.c1), 0, 0, 0, 24); return g; }
function pelt(c) { const g = new THREE.Group(), m = M('fabric', c.c0); soft(g, .6, .04, .9, .02, m, 0, 0, 0); sphere(g, .12, m, 0, .03, -.55); for (const [x, z] of [[-.35, -.3], [.35, -.3], [-.35, .3], [.35, .3]]) sphere(g, .09, m, x, .02, z); return g; }
function glowFlat(c) { const g = new THREE.Group(), d = place(new THREE.Mesh(new THREE.CircleGeometry(.4, 20), M('plain', c.c1, { emissive: c.c1, ei: .7, opacity: .5 })), 0, .02, 0); d.rotation.x = -Math.PI / 2; g.add(d); return g; }
function glowOrb(c) { const g = new THREE.Group(); sphere(g, .18, M('plain', c.c1, { emissive: c.c1, ei: 1, opacity: .75 }), 0, .3, 0); return g; }

// regras por nome: a primeira que casa vence (so valem fora de arquitetura basica: piso, parede, escada...)
const BY_NAME = [
  [/fallen log|\btree trunk\b/, c => fallenLog(c)], [/stalagmite|stalactite/, c => stalagmites(c)],
  [/chest of drawers|dresser|armoire|wardrobe|cupboard/, c => FURN.cabinet(c)], [/display case/, c => vitrine(c, .96, .8)],
  [/\bcounter\b/, c => { const g = new THREE.Group(); OVR.wood = ratio(woodTone([c.it]) || c.c0, '#8a5a32'); try { g.add(hmCounter({ L: .98 })); } finally { OVR.wood = null; } return g; }],
  [/cauldron|kettle/, c => tool({ ...c, n: 'cauldron' })], [/\btub\b|basin|bucket|\bpail\b/, tub],
  [/\bchest\b|casket|strongbox|coffer/, c => c.it.cat === 'armor' || c.it.cat === 'clothing' ? ARMOR.body(c) : CONT.chest(c)],
  [/skulls|skull spikes/, skullPile], [/\bskull\b/, c => skullPile(c, 1)], [/spike trap|\bspikes\b/, c => spikes(c)],
  [/pickaxe|\bpick\b|hammer|mallet|\bsaw\b|shovel|spade|scythe|sickle|pitchfork|\bhoe\b|\brake\b|tongs|scissors|shears|pliers/, c => tool(c)],
  [/flask|bottle|\bvial\b|goblet|decanter/, c => CONS.potion(c)], [/\bscales?\b/, c => scales(c)], [/bolts? of cloth|folded cloth|\bcloth\b/, c => BY_LABEL.cloth(c)],
  [/\barrows?\b|\bbolts?\b/, c => arrows(c)],
  [/necklace|amulet|talisman|pendant|gorget/, c => necklace(c)], [/bracelet|bangle/, c => bracelet(c)], [/earring/, c => earrings(c)],
  [/\bcloak\b|\bcape\b|\bshroud\b/, c => cloak(c)], [/pants|trousers|leggings|\blegs\b/, c => pants(c)], [/skirt|kilt/, c => skirt(c)],
  [/horse ?shoe/, c => horseshoes(c)], [/\banvil\b/, c => anvil(c)], [/fishing pole|\bpole\b|\brod\b/, c => fishingPole(c)], [/\bnet\b/, c => fishNet(c)],
  [/telescope/, telescope], [/\bskeleton\b|\bbones?\b|\bskull/, skeleton], [/^body$|\bcorpse\b/, corpse], [/lighthouse/, lighthouse],
  [/gravestone|headstone|tombstone/, gravestone], [/\bgrave\b/, grave], [/moongate/, moongate],
  [/shipwreck/, shipBow], [/tiller/, tiller], [/dragon prow|\bprow\b/, prow], [/\bfountain\b/, c => fountain(c)],
  [/bearskin|\bpelt\b/, pelt], [/round rug/, rugRound], [/\brug\b|carpet/, c => DECO.rug(c)],
  [/banner|tapestry|curtain|\bflag\b|drape/, hanging], [/painting|portrait|picture/, painting],
  [/\bweb\b|cobweb/, web], [/pentagram|arcanecircle|arcane circle|exodus|\bcircle\b|\brune/, magicRing],
  [/sinkhole/, sinkhole], [/treasure/, treasure], [/refuse|trash|garbage|rubble|debris/, refuse], [/stain|blood|puddle|splat/, stain],
  [/nodraw|\bqc corner|marker/, marker],
  [/suspension bridge|rope bridge/, c => ARCH.bridge(c)], [/roof/, c => ARCH.roof(c)],
  [/\barch\b/, c => ARCH.arch(c)], [/\bdoor\b/, c => ARCH.door(c)],
  [/field of|\bfield\b|vortex|sparkle|energy|glow/, glowFlat], [/bees|swarm|firefly|wisp/, glowOrb],
  [/sandstone|\brocks?\b|boulder/, c => ROCK.boulder(c)], [/^wood$|\bwood\b|plank/, c => logs(c)], [/\bship\b|ship model/, c => SHIP.hull(c)],
];
// nomes de pecas que a classificacao marcou como efeito/decalque/desconhecido
const LOOSE = [
  [/\bwall\b|\bbeam\b|\bbricks?\b|\bpost\b/, c => ARCH.wall(c)], [/\btable\b|\bdisplay\b|\bcase\b/, c => FURN.table(c)], [/\bbed\b|pillow|blanket|sheets?|\bsleeping/, c => FURN.bed(c)],
  [/chair|\bbench\b|stool/, c => FURN.chair(c)], [/basket/, c => CONT.basket ? CONT.basket(c) : basket(c)], [/\bpot\b|cauldron/, c => tool({ ...c, n: 'pot ' + c.n })],
  [/statue|gargoyle|\bhead\b|knight|melisande|trophy/, c => DECO.statue(c)], [/gate|bars?\b|fence|rail/, c => ARCH.fence(c)],
  [/torch|sconce|\blamp/, c => LIGHT.torch(c)], [/rack|weapons|sword|shelf/, c => FURN.shelf(c)], [/crystal/, c => ROCK.crystal(c)],
  [/sarcophagus|coffin|\btomb/, c => CONT.chest({ ...c, c0: '#8a8f9a' })], [/spike|trap|switch|lever/, c => spikes(c)],
  [/sign(post)?\b/, c => signpost(c)], [/tree|cloud|flower|plant|bush/, c => VEG.bush(c)], [/crack|footprint|patch|spilled|flour|shadow/, stain],
  [/design|floor|rug|carpet|tile/, c => ARCH.floor(c)],
];
function byLoose(c) { for (const [rx, fn] of LOOSE) if (rx.test(c.n)) return fn(c); return null; }
function spikes(c) { const g = new THREE.Group(), m = M('metal', '#8d939a'); box(g, .9, .04, .9, M('stone', c.c0), 0, 0, 0); for (let i = 0; i < 9; i++) g.add(place(new THREE.Mesh(new THREE.ConeGeometry(.04, .25, 5), m), -.3 + (i % 3) * .3, .16, -.3 + Math.floor(i / 3) * .3)); return g; }
function signpost(c) { const g = new THREE.Group(), wd = M('wood', c.c0); box(g, .08, 1.3, .08, wd, 0, 0, 0); box(g, .6, .3, .05, wd, .15, .85, 0); return g; }
const BASIC = new Set(['floor', 'wall', 'stairs', 'column', 'window', 'fence']);
function byName(it, c) {
  if (it.cat === 'architecture' && ARCH[it.sub] && !/lighthouse|fountain|moongate|shipwreck|banner|tapestry|curtain|painting|\bweb\b|telescope/.test(c.n)) return null;
  for (const [rx, fn] of BY_NAME) if (rx.test(c.n)) return fn(c);
  if (it.cat === 'effect' || it.cat === 'unknown') return byLoose(c);
  return null;
}

const FLAT_CARD = new Set(['fire', 'magic', 'smoke', 'web', 'blood', 'painting', 'sign']);   // viram placa com o proprio sprite

const TABLE = {
  architecture: ARCH, terrain: TERR, vegetation: VEG, rock: ROCK, furniture: FURN, container: CONT,
  weapon: WEAP, armor: ARMOR, clothing: CLOTH, jewelry: JEWEL, consumable: CONS, resource: RES,
  light: LIGHT, document: DOC, decoration: DECO, ship: SHIP,
};
const CAT_FALLBACK = {
  tool: tool,
  light: c => LIGHT.torch(c),
  decoration: c => genericBlock(c),
};

// ---------------------------------------------------------------- API
// spriteTex(it): THREE.Texture do sprite (efeitos e desconhecidos viram placas); retorna um Group
export function buildOne(it, spriteTex) {
  CUR = styleOf(it);
  try { return buildOneInner(it, spriteTex); } finally { CUR = null; }
}
function buildOneInner(it, spriteTex) {
  const tk = templateKey(it);
  if (tk) return templated(it, tk);
  if (MODE === 'fiel' && spriteTex && hasHull(it)) return hullModel(it, spriteTex);
  const c = ctx(it);
  try { const byn = byName(it, c); if (byn) return byn; } catch (e) { console.warn('byName falhou', it.hex, it.name, e); }
  const cat = it.cat, sub = it.sub;
  let g;
  try {
    const lab = pickLabel(it);
    if (lab && FLAT_CARD.has(lab)) {
      const w = Math.max(.2, it.w / 44);
      if (lab === 'fire') { g = new THREE.Group(); g.add(place(new THREE.Mesh(new THREE.ConeGeometry(.2, .6, 10), M('plain', '#ffb030', { emissive: '#ff7a10', ei: 1.4 })), 0, .3, 0)); return g; }
      if (lab === 'painting' || lab === 'sign') return painting(c);
      return lab === 'blood' ? stain(c) : glowFlat(c);
    }
    if (lab && BY_LABEL[lab]) return BY_LABEL[lab](c);
    const fn = (TABLE[cat] && TABLE[cat][sub]) || CAT_FALLBACK[cat];
    if (cat !== 'vegetation' && has(c.n, /\bplants?\b|\bgrass\b|\bvines?\b|\bferns?\b|\bweeds?\b/)) g = VEG.bush(c);
    else if (has(c.n, /\b(cannon|iron|stone) ?balls?\b|\bshot\b/)) {
      g = new THREE.Group();
      for (let i = 0; i < 4; i++) sphere(g, .1, M('metal', '#3a3d42', { rough: .5 }), (i % 2 - .5) * .2 + (i > 1 ? .1 : 0), .1 + (i > 1 ? .15 : 0), (i > 1 ? 0 : .05));
    } else if (cat === 'decoration' && (sub === 'painting' || sub === 'web')) g = painting(c);
    else if (fn) g = fn(c);
    else if (cat === 'effect' || cat === 'unknown') {
      const w = Math.max(.2, it.w / 44), h = Math.max(.2, it.hp / 44);
      if (cat === 'effect' && sub === 'fire') {
        g = new THREE.Group();
        g.add(place(new THREE.Mesh(new THREE.ConeGeometry(.2, .6, 10), M('plain', '#ffb030', { emissive: '#ff7a10', ei: 1.4 })), 0, .3, 0));
      } else if (sub === 'decal' || sub === 'marker' || sub === 'field') {
        g = byLoose(c) || stain(c);
      } else g = marker(c);
    } else g = genericBlock(c);
  } catch (e) {
    console.warn('builder falhou', it.hex, it.name, e);
    g = genericBlock(c);
  }
  return g;
}

// conjunto: movel conhecido (cama, balcao, mesa, banco) vira o modelo feito a mao no tamanho da pegada;
// o resto fica com as pecas lado a lado, cada uma o modelo automatico dela mesma
export function buildSet(st, itemOf, spriteTexOf) {
  try { const t = setTemplated(st, itemOf); if (t) return t; } catch (e) { console.warn('conjunto modelo falhou', st.name, e); }
  const g = new THREE.Group();
  const xs = st.pieces.map(p => p.dx), ys = st.pieces.map(p => p.dy);
  const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2;
  // cena mista (arvore + tronco caido + pedras...): as pecas da arvore viram uma arvore so, as do tronco uma tora so
  const done = new Set();
  for (const [rx, cat, name] of [[TREE_PIECE, 'vegetation', 'tree'], [/fallen log/, 'resource', 'fallen log']]) {
    const sub = st.pieces.filter(p => rx.test((itemOf(p.id).name || '').toLowerCase()));
    if (!sub.length || sub.length === st.pieces.length) continue;
    try {
      const m = setTemplated({ ...st, cat, name, pieces: sub }, itemOf);
      if (!m) continue;
      const sx = sub.map(p => p.dx), sy = sub.map(p => p.dy);
      m.position.set((Math.min(...sx) + Math.max(...sx)) / 2 - cx, 0, (Math.min(...sy) + Math.max(...sy)) / 2 - cy);
      g.add(m); sub.forEach(p => done.add(p));
    } catch (e) { console.warn('conjunto misto falhou', st.name, e); }
  }
  for (const p of st.pieces) {
    if (done.has(p)) continue;
    const it = itemOf(p.id);
    const m = buildOne(it, spriteTexOf(it));
    m.position.set(p.dx - cx, p.dz * .144, p.dy - cy);
    g.add(m);
  }
  return g;
}

// ---------------------------------------------------------------- conjuntos com modelo feito a mao
// cada familia: construtor (W = largura, L = comprimento, em unidades de mundo) e o eixo em que o modelo-modelo deita o comprimento
const SET_TEMPL = {
  bed: { axis: 'z', make: (W, L, st, n) => hmBed({ W, L, cot: /\bcot\b/.test(n), ...(st.accent ? { quilt: new THREE.Color(st.accent).getHex() } : {}) }) },
  canopy: { axis: 'z', make: (W, L, st) => canopyBed({ W: W * .83, L, ...(st.accent ? { quilt: new THREE.Color(st.accent).getHex() } : {}) }) },
  counter: { axis: 'x', make: (W, L) => hmCounter({ L, D: W < 1.2 ? .86 : W - .1 }) },
  table: { axis: 'z', make: (W, L) => longTable({ W, L }) },
  stoneTable: { axis: 'z', make: (W, L) => stoneTable({ W, L }) },
  bench: { axis: 'x', make: (W, L) => hmBench({ L }) },
  stoneBench: { axis: 'x', make: (W, L) => stoneBench({ L }) },
  bookcase: { axis: 'x', make: (W, L, st, n, c) => bookshelf(c, L - .04) },
  shelf: { axis: 'x', make: (W, L, st, n, c) => FURN.shelf(c, L - .04) },
  vitrine: { axis: 'x', make: (W, L, st, n, c) => vitrine(c, L, Math.min(W, .9)) },
  sarcophagus: { axis: 'z', make: (W, L, st, n, c) => sarcophagus(c, W * .85, L * .92) },
  coffin: { axis: 'z', make: (W, L, st, n, c) => coffin(c, L * .9) },
  rug: { axis: 'x', make: (W, L, st, n, c) => /bear|pelt|skin/.test(n) ? peltRug(c, W, L) : DECO.rug(c, L - .05, W - .05) },
  hedge: { axis: 'x', make: (W, L, st, n, c) => hedge(c, L, W * .75) },
  log: { axis: 'z', make: (W, L, st, n, c) => fallenLog(c, L * .95, clamp(W * .22, .18, .34)) },
};
const STONE_NAME = /stone|marble|granite|sandstone/;
const TREE_PIECE = /\btree\b|leaves|needles|branch/;
const n0 = st => (st.name || '').toLowerCase();
function setFamily(st, items) {
  const n = n0(st);
  const all = rx => items.every(it => rx.test((it.name || '').toLowerCase()));
  if (all(TREE_PIECE)) return 'tree';
  if (all(/fallen log|tree trunk/)) return 'log';
  if (/hedge/.test(n)) return 'hedge';
  if (/sarcophag/.test(n)) return 'sarcophagus';
  if (/^coffin$/.test(n)) return 'coffin';
  if (/display case|vitrine/.test(n)) return 'vitrine';
  if (/bookcase|bookshelf/.test(n)) return 'bookcase';
  if (/shelf/.test(n)) return 'shelf';
  if (st.sub === 'rug' || /\bmat\b|\brug\b|carpet/.test(n)) return 'rug';
  if (n.includes('+') || /couch|sofa|dresser|writing/.test(n)) return null;
  if (st.sub === 'bed') return items.some(it => it.hp > 95) ? 'canopy' : 'bed';
  if (st.sub === 'table') return /counter|\bbar\b/.test(n) ? 'counter' : STONE_NAME.test(n) ? 'stoneTable' : /\btable\b/.test(n) ? 'table' : null;
  if (st.sub === 'chair' && /bench/.test(n)) return STONE_NAME.test(n) ? 'stoneBench' : 'bench';
  return null;
}
// tom de madeira das pecas: a cor marrom (matiz laranja, saturada, nem clara nem escura demais) mais frequente nas paletas
function woodTone(items) {
  const cnt = new Map();
  for (const it of items) for (const hx of it.pal) {
    const o = {}; new THREE.Color(hx).getHSL(o, THREE.SRGBColorSpace);
    if (o.h > .02 && o.h < .16 && o.s > .25 && o.l > .12 && o.l < .6) cnt.set(hx, (cnt.get(hx) || 0) + 1);
  }
  return [...cnt].sort((a, b) => b[1] - a[1])[0]?.[0] || null;
}
// arvore de varias pecas: altura pelo sprite mais alto, copa pela pegada, folhagem pela paleta das pecas de folha
function bigTree(st, items, nx, ny) {
  const names = items.map(it => (it.name || '').toLowerCase()).join(' ');
  const leafIt = items.filter(it => /leaves|needles/.test((it.name || '').toLowerCase()));
  const leaf = (leafIt.length ? leafIt : items).map(it => greenOf(it.pal)).find(Boolean) || '#3f7a3a';
  const bark = woodTone(items.filter(it => /tree|trunk/.test((it.name || '').toLowerCase()))) || '#5e4630';
  const hp = Math.max(...items.map(it => it.hp));
  const out = treeModel({ h: clamp((hp - 14) / 46 * .62, 1.6, 6), spread: clamp(Math.max(nx, ny) * .5, .7, 2.4), leaf, bark, kind: treeKind(names + ' ' + n0(st)), seed: items[0].id });
  out.userData.templ = 'tree';
  return out;
}
// vitrine de loja: armario de base com portas, caixa de vidro com montantes e tampo (comprimento em x)
function vitrine(c, L, D) {
  const g = new THREE.Group(), m = M('wood', c.c0), dk = M('wood', shade(c.c0, .7)), gl = M('plain', '#cfe6ef', { opacity: .25, rough: .05 });
  box(g, L, .08, D, dk, 0, 0, 0); box(g, L - .04, .6, D - .04, m, 0, .08, 0); box(g, L + .02, .04, D + .02, dk, 0, .68, 0);
  const nd = Math.max(1, Math.round(L / .5));
  for (let i = 0; i < nd; i++) { const x = -L / 2 + (i + .5) * L / nd; box(g, L / nd - .06, .48, .02, dk, x, .14, D / 2 - .01); sphere(g, .015, M('metal', brassC), x, .38, D / 2 + .01); }
  g.add(place(new THREE.Mesh(new THREE.BoxGeometry(L - .06, .4, D - .06), gl), 0, .92, 0));
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) box(g, .03, .42, .03, dk, sx * (L / 2 - .03), .71, sz * (D / 2 - .03));
  for (const sz of [-1, 1]) box(g, L, .03, .03, dk, 0, 1.12, sz * (D / 2 - .03));
  box(g, L + .02, .03, D + .02, m, 0, 1.13, 0);
  return g;
}
// sarcofago: plinto, caixa com almofadas laterais, tampa com efigie deitada (comprimento em z)
function sarcophagus(c, W, L) {
  const g = new THREE.Group(), st = M('stone', c.c0), dk = M('stone', shade(c.c0, .78)), H = .7;
  box(g, W + .1, .1, L + .1, dk, 0, 0, 0); box(g, W, H - .2, L, st, 0, .1, 0);
  for (const s of [-1, 1]) for (let i = 0; i < 3; i++) box(g, .02, H * .4, L / 3 - .1, dk, s * (W / 2 + .005), .2, -L / 3 + i * L / 3);
  box(g, W + .06, .1, L + .06, dk, 0, H - .1, 0);
  const t = new THREE.Group(); t.position.set(0, H + .02, L * .38); t.rotation.x = -Math.PI / 2; t.scale.set(1, 1, .5); g.add(t);
  figure(t, st, 0, L * .76, c.it.id);
  return g;
}
// caixao: perfil hexagonal extrudado (largo nos ombros), tampa com cruz (comprimento em z)
function coffin(c, L) {
  const wc = woodTone([c.it]) || c.c0, g = new THREE.Group(), m = M('wood', wc), dk = M('wood', shade(wc, .65));
  const s = new THREE.Shape(); s.moveTo(-.18, -L / 2); s.lineTo(.18, -L / 2); s.lineTo(.3, L * .2); s.lineTo(.24, L / 2); s.lineTo(-.24, L / 2); s.lineTo(-.3, L * .2); s.closePath();
  const body = place(new THREE.Mesh(new THREE.ExtrudeGeometry(s, { depth: .38, bevelEnabled: true, bevelSize: .015, bevelThickness: .015, bevelSegments: 2 }), m), 0, .015, 0);
  body.rotation.x = -Math.PI / 2; g.add(body);
  box(g, .05, .01, L * .55, dk, 0, .405, .05); box(g, .3, .01, .05, dk, 0, .405, -.12);
  return g;
}
// cerca viva: bloco de folhagem aparado com bolhas no topo (comprimento em x)
function hedge(c, L, D) {
  const g = new THREE.Group(), leaf = greenOf(c.it.pal) || '#3f6e34', a = M('noisy', leaf), b = M('noisy', shade(leaf, .78));
  soft(g, L, .85, D, .15, b, 0, 0, 0);
  const n = Math.max(1, Math.round(L / .35));
  for (let i = 0; i < n; i++) blob(g, D * .42, i % 2 ? a : b, -L / 2 + (i + .5) * L / n, .82, (c.r() - .5) * .1, c.it.id + i, .55);
  return g;
}
// tapete de pele: corpo achatado, cabeca e quatro patas abertas (comprimento em x)
function peltRug(c, W, L) {
  const g = new THREE.Group(), m = M('fabric', c.c0), k = Math.min(W, L * .6);
  soft(g, L * .7, .04, k * .8, .02, m, .05, 0, 0);
  sphere(g, k * .2, m, -L * .38, .05, 0).children.at(-1).scale.set(1.2, .55, 1);
  for (const [x, z] of [[-.2, -.5], [-.2, .5], [.3, -.5], [.3, .5]]) soft(g, k * .16, .03, k * .4, .015, m, x * L, 0, z * k * .75);
  return g;
}
function setTemplated(st, itemOf) {
  const ps = st.pieces;
  const xs = ps.map(p => p.dx), ys = ps.map(p => p.dy);
  const x0 = Math.min(...xs), y0 = Math.min(...ys), nx = Math.max(...xs) - x0 + 1, ny = Math.max(...ys) - y0 + 1;
  const items = ps.map(p => itemOf(p.id));
  const fam = setFamily(st, items);
  if (!fam) return null;
  if (fam === 'tree') return bigTree(st, items, nx, ny);
  if (ps.some(p => p.dz)) return null;                                   // pecas empilhadas (tampa, coisa em cima): lado a lado
  if (fam !== 'log' && new Set(ps.map(p => p.dx + ',' + p.dy)).size !== nx * ny) return null;   // so pegada retangular cheia
  const along = ny >= nx ? 'z' : 'x', Lt = Math.max(nx, ny), Wt = Math.min(nx, ny);
  // cabeceira: a ponta com o sprite mais alto
  const endHp = k => { const sel = ps.filter(p => (along === 'z' ? p.dy : p.dx) === k); return sel.reduce((a, p) => a + itemOf(p.id).hp, 0) / sel.length; };
  const lo = along === 'z' ? y0 : x0, headAtMax = endHp(lo + Lt - 1) > endHp(lo);
  const it = items[0], t = SET_TEMPL[fam], sty = { ...styleOf(it) };
  // lencol/colcha cinza no sprite engana o detector de metal; aqui so o nome decide. Colcha marrom e a propria madeira
  if (!/iron|metal|steel|silver|bronze|gold|brass/.test(n0(st))) { sty.metal = false; sty.kind = 'base'; }
  if (sty.accent) { const o = {}; new THREE.Color(sty.accent).getHSL(o, THREE.SRGBColorSpace); if (o.h > .02 && o.h < .16) sty.accent = null; }
  OVR.wood = ratio(sty.metal ? sty.frame : woodTone(items) || sty.frame, '#8a5a32');
  OVR.stone = ratio(it.pal.find(h => hexLum(h) > .2) || it.pal[0], '#9a9a94');
  let g;
  try { g = t.make(Wt * .96, Lt - .04, sty, n0(st), ctx(it)); } finally { OVR.wood = OVR.stone = null; }
  restyle(g, { ...sty, accent: null });
  // modelo-modelo deita o comprimento em t.axis; gira para o eixo do conjunto (cama: cabeceira modelada em -z)
  let ry = t.axis === along ? 0 : Math.PI / 2;
  if (fam === 'bed' || fam === 'canopy') ry = along === 'z' ? (headAtMax ? Math.PI : 0) : (headAtMax ? -Math.PI / 2 : Math.PI / 2);
  g.rotation.y = ry;
  const out = new THREE.Group();
  out.add(g);
  out.userData.templ = fam;
  return out;
}

// ---------------------------------------------------------------- modelo fiel a art (malha do conversor + sprite modernizado)
let MESH = null;
export let MODE = 'proc';
export function setMeshes(index, buf) { MESH = { index, buf }; }
export function setMode(m) { MODE = m; }
export function hasHull(it) { return !!(MESH && MESH.index[it.hex]); }
export function hullModel(it, tex) {
  const info = MESH.index[it.hex], { o, nv, nt } = info, buf = MESH.buf;
  let p = o;
  const pos = new Float32Array(buf, p, nv * 3); p += nv * 12;
  const uv = new Uint16Array(buf, p, nv * 2); p += nv * 4;
  const nr = new Int8Array(buf, p, nv * 4); p += nv * 4;
  const idx = new Uint32Array(buf, p, nt * 3);
  const uvs = new Float32Array(nv * 2), nrm = new Float32Array(nv * 3);
  for (let i = 0; i < nv; i++) {
    uvs[2 * i] = uv[2 * i] / 16 / it.w; uvs[2 * i + 1] = 1 - uv[2 * i + 1] / 16 / it.hp;
    nrm[3 * i] = nr[4 * i] / 127; nrm[3 * i + 1] = nr[4 * i + 1] / 127; nrm[3 * i + 2] = nr[4 * i + 2] / 127;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos.slice(), 3));
  geo.setAttribute('normal', new THREE.BufferAttribute(nrm, 3));
  geo.setAttribute('uv', new THREE.BufferAttribute(uvs, 2));
  const ix = idx.slice();
  for (let i = 0; i < ix.length; i += 3) { const t = ix[i + 1]; ix[i + 1] = ix[i + 2]; ix[i + 2] = t; }   // a troca de eixos inverte o sentido das faces
  geo.setIndex(new THREE.BufferAttribute(ix, 1));
  const m = new THREE.MeshStandardMaterial({ map: tex, bumpMap: tex.userData.bump || null, bumpScale: .6, roughness: .78, metalness: .04, alphaTest: .5, side: THREE.DoubleSide });
  const g = new THREE.Group();
  g.add(new THREE.Mesh(geo, m));
  return g;
}

// ---------------------------------------------------------------- modelos-modelo (qualidade dos feitos a mao) para classes recorrentes
// o mesmo modelo serve a todo item da classe: escala pelo tamanho do sprite e cor da madeira/pedra pela paleta
const TEMPL = {
  barrel: { make: () => hmBarrel(.36, .98), ref: [50, 48] },
  keg: { make: () => hmBarrel(.2, .52, { staves: 9, hoops: [.14, .5, .86], spigot: true }), ref: [44, 37] },
  crate: { make: hmCrate, ref: [44, 60] },
  bench: { make: hmBench, stone: stoneBench, ref: [44, 54] },
  table: { make: tableOne, stone: stoneTable, ref: [66, 61], minW: 56 },
  chair: { make: () => chairOne('chair'), ref: [30, 63] },
  stool: { make: () => chairOne('stool'), ref: [30, 40] },
};
const SUB_TEMPL = { barrel: 'barrel', crate: 'crate', table: 'table' };
function templateKey(it) {
  if (/\bkeg\b/i.test(it.name || '')) return 'keg';
  if (NOT_TEMPL.test((it.name || '').toLowerCase())) return null;   // o nome diz outra coisa: as regras por nome resolvem
  const lab = pickLabel(it);
  let k = lab && TEMPL[lab] ? lab : null;
  if (!k) {
    const n = (it.name || '').toLowerCase();
    if (it.sub === 'chair') k = /bench/.test(n) ? 'bench' : /stool/.test(n) ? 'stool' : 'chair';
    else k = SUB_TEMPL[it.sub] || null;
  }
  if (k && TEMPL[k].minW && it.w < TEMPL[k].minW) return null;
  return k;
}
const rgb255 = h => { const c = new THREE.Color(h); return [c.r * 255, c.g * 255, c.b * 255]; };
const ratio = (hex, ref) => { const a = rgb255(hex), r = rgb255(ref); return a.map((v, i) => Math.min(2.5, Math.max(.3, v / r[i]))); };
function woodColor(it) { return it.pal.find(h => { const l = hexLum(h); return l > .12 && l < .7; }) || it.pal[0]; }
function templated(it, key) {
  const t = TEMPL[key], st = CUR || styleOf(it);
  const stoneish = (st.stone || /stone|marble|granite/i.test(it.name || '')) && t.stone && !st.metal;
  OVR.wood = ratio(st.frame, '#8a5a32');
  OVR.stone = ratio(it.pal.find(h => hexLum(h) > .2) || it.pal[0], '#9a9a94');
  let g;
  try { g = (key === 'chair' || key === 'stool') ? styledChair(it, key, st) : (stoneish ? t.stone : t.make)(); } finally { OVR.wood = OVR.stone = null; }
  restyle(g, st);
  const out = new THREE.Group();
  out.add(g);
  const sx = Math.min(1.8, Math.max(.5, it.w / t.ref[0])), sy = Math.min(1.8, Math.max(.5, it.hp / t.ref[1]));
  out.scale.set(sx, sy, sx);
  return out;
}

// aplica o estilo medido na imagem a um modelo ja montado: madeira/pedra -> metal/ouro, tecidos -> cor do estofado
function restyle(g, st) {
  const seen = new Set();
  g.traverse(o => {
    if (!o.isMesh || seen.has(o.material)) return;
    const m = o.material; seen.add(m);
    const k = m.userData && m.userData.kind;
    if (st.metal && (k === 'wood' || k === 'stone')) {
      m.map = m.bumpMap = m.roughnessMap = null; m.color.set(st.frame); m.metalness = .85; m.roughness = st.kind === 'gold' ? .3 : .38;
      m.envMapIntensity = 2.4; m.emissive.set(st.frame); m.emissiveIntensity = .22; m.needsUpdate = true;
    } else if (k === 'fabric' && st.accent) { m.map = null; m.color.set(st.accent); m.needsUpdate = true; }
  });
}

// estilo medido na imagem: cor do quadro, cor do estofado, material (madeira, pedra, metal, ouro) e se e ornamentado
function styleOf(it) {
  const f = it.f || {}, n = (it.name || '').toLowerCase();
  const hsl = hx => { const o = {}; new THREE.Color(hx).getHSL(o, THREE.SRGBColorSpace); return o; };
  const cols = it.pal.map(hx => ({ hex: hx, ...hsl(hx) }));
  const sat = [...cols].sort((a, b) => b.s * (1 - Math.abs(b.l - .4)) - a.s * (1 - Math.abs(a.l - .4)))[0];
  const rest = cols.filter(c => c !== sat);
  let frame = [...rest].sort((a, b) => b.l - a.l)[0] || sat, accent = null;
  const dh = rest.length ? Math.min(Math.abs(sat.h - frame.h), 1 - Math.abs(sat.h - frame.h)) : 0;
  if (sat.s > .5 && sat.l > .1 && sat.l < .65 && rest.length && (dh > .06 || Math.abs(sat.l - frame.l) > .25)) accent = sat.hex;
  else frame = cols[0];
  const ornate = (f.fill || 1) < .5 || /elven|ornate|throne|gargoyle|royal|elegant|gilded|golden/.test(n);
  const gold = cols.find(c => c.h > .07 && c.h < .17 && c.s > .4 && c.l > .5);
  // cinza no sprite so vira metal fora de pedra/construcao (parede e coluna cinzas viravam metal preto)
  const steel = /iron|metal|steel|silver|gargoyle|bronze/.test(n) || ((f.gy || 0) > .4 && !STONEY.test(n) && !['architecture', 'rock', 'terrain', 'vegetation'].includes(it.cat));
  let kind = 'base';
  if (steel) kind = 'metal';
  else if (/gold|brass/.test(n) || (ornate && gold && accent)) kind = 'gold';
  if (kind === 'gold' && gold) frame = gold;
  return { frame: frame.hex, accent, kind, metal: kind !== 'base', ornate, stone: (f.gy || 0) > .45 };
}

// ---------------------------------------------------------------- cadeira estilizada pela imagem (ornamentada/metal, almofada colorida)
function styledChair(it, kind, st) {
  if (!st.ornate) {
    const g = chairOne(kind);
    if (st.accent) soft(g, .42, .06, .42, .025, M('fabric', st.accent), 0, .45, 0);
    return g;
  }
  const g = new THREE.Group(), W = .46, H = .46, tall = kind === 'stool' ? 0 : .62;
  const fr = st.metal ? tinted('metal', st.frame, { rough: st.kind === 'gold' ? .3 : .38, metal: .85, emissive: st.frame, ei: .22 }) : M('wood', st.frame);
  if (st.metal) fr.envMapIntensity = 2.4;
  const cu = M('fabric', st.accent || st.frame);
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
    const x = sx * (W / 2 - .03), z = sz * (W / 2 - .03);
    lathe(g, [[.001, 0], [.022, 0], [.03, .08], [.045, .22], [.035, H - .03], [.001, H - .03]], fr, x, 0, z, 10);
    if (sz < 0 && tall) { const post = place(new THREE.Mesh(new THREE.CylinderGeometry(.018, .028, tall + .05, 8), fr), x, H + tall / 2 - .02, z - .03); post.rotation.x = .1; g.add(post); }
  }
  box(g, W, .05, W, fr, 0, H - .05, 0);
  soft(g, W - .04, .07, W - .04, .03, cu, 0, H - .01, 0);
  for (const y of [.14, .26]) for (const sx of [-1, 1]) box(g, .025, .025, W - .06, fr, sx * (W / 2 - .03), y, 0);
  if (tall) {
    const cz = -W / 2 - .02;
    const arch = place(new THREE.Mesh(new THREE.TorusGeometry(W / 2 - .02, .022, 8, 24, Math.PI), fr), 0, H + tall - .08, cz); g.add(arch);
    box(g, W - .06, .02, .02, fr, 0, H + tall - .09, cz);
    soft(g, W - .1, tall * .55, .05, .03, cu, 0, H + .1, -W / 2 + .0);
    for (const sx of [-1, 1]) { const sc = place(new THREE.Mesh(new THREE.TorusGeometry(.06, .012, 6, 18), fr), sx * .11, H + tall * .78, cz); g.add(sc); }
    for (const sx of [-1, 1]) {                                            // bracos com volutas
      box(g, .035, .03, W - .08, fr, sx * (W / 2 + .0), H + .2, .0);
      const cu2 = place(new THREE.Mesh(new THREE.TorusGeometry(.05, .014, 6, 14), fr), sx * (W / 2), H + .2, W / 2 - .02); cu2.rotation.y = Math.PI / 2; g.add(cu2);
      box(g, .025, .2, .025, fr, sx * (W / 2), H, W / 2 - .06);
    }
  }
  return g;
}
