// Gerador automatico de modelos 3D: categoria/subcategoria do taxonomy + nome + paleta do sprite -> malha procedural.
// Unidades: 1 tile = 1, y para cima, origem no centro da pegada.
import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { tinted, OVR } from './textures.js';
import { box, soft, lathe, sphere, ring, place, turnedLeg, barrel as hmBarrel, crate as hmCrate, bench as hmBench, tableOne, chairOne, stoneTable, stoneBench } from './models.js';

const hexLum = h => { const c = new THREE.Color(h); return .3 * c.r + .59 * c.g + .11 * c.b; };
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
  return { it, n: (it.name || '').toLowerCase(), fw, fd: fw, H, c0: st.frame, c1: st.accent || pal[1] || pal[0], c2: pal[2] || pal[0],
    light: bySat[0], dark: bySat[bySat.length - 1], r: mkRng(it.id + 7), flags: it.flags || [] };
}
let CUR = null;       // estilo do item em construcao (material: madeira/pedra viram metal/ouro quando o sprite e assim)
const M = (t, c, o) => (CUR && CUR.metal && (t === 'wood' || t === 'stone') ? tinted('metal', c, { rough: .32, metal: .9, ...(o && o.side ? { side: o.side } : {}) }) : tinted(t, c, o));
const ironC = '#8d939a';

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
  wall(c) {
    const g = new THREE.Group();
    const t = has(c.n, /brick/) ? 'brick' : has(c.n, /plaster|board/) ? 'wood' : 'stone';
    const m = M(t, c.c0), cap = M('stone', shade(c.c0, .8));
    const h = Math.max(.9, Math.min(2.6, c.H * 1.1));
    if (has(c.n, /corner/)) {
      box(g, .22, h, 1, m, -.39, 0, 0); box(g, 1, h, .22, m, 0, 0, -.39);
      box(g, .26, .05, 1.04, cap, -.39, h, 0); box(g, 1.04, .05, .26, cap, 0, h, -.39);
    } else {
      box(g, 1, h, .22, m, 0, 0, 0); box(g, 1.04, .05, .26, cap, 0, h, 0);
    }
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
    return g;
  },
  stairs(c) {
    const g = new THREE.Group(), m = M(has(c.n, /wood/) ? 'wood' : 'stone', c.c0), n = 5;
    for (let i = 0; i < n; i++) box(g, 1, .16 * (i + 1), 1 / n, m, 0, 0, -.5 + (i + .5) / n);
    return g;
  },
  arch(c) {
    const g = new THREE.Group(), m = M('stone', c.c0);
    box(g, .22, 1.5, .26, m, -.39, 0, 0); box(g, .22, 1.5, .26, m, .39, 0, 0);
    const a = place(new THREE.Mesh(new THREE.CylinderGeometry(.5, .5, .26, 24, 1, false, Math.PI / 2, Math.PI), m), 0, 1.5, 0);
    a.rotation.x = Math.PI / 2; g.add(a);
    return g;
  },
  window(c) {
    const g = new THREE.Group(), fr = M('wood', c.c0), gl = M('plain', '#9fc4d8', { opacity: .35, rough: .1 });
    const w = .8, h = 1;
    box(g, w, .08, .14, fr, 0, .55 + h - .08, 0); box(g, w, .08, .14, fr, 0, .55, 0);
    box(g, .08, h, .14, fr, -w / 2 + .04, .55, 0); box(g, .08, h, .14, fr, w / 2 - .04, .55, 0);
    box(g, .04, h - .1, .1, fr, 0, .6, 0); box(g, w - .1, .04, .1, fr, 0, .55 + h / 2, 0);
    g.add(place(new THREE.Mesh(new THREE.PlaneGeometry(w - .1, h - .1), gl), 0, .55 + h / 2, 0));
    g.add(place(new THREE.Mesh(new THREE.BoxGeometry(1, .5, .18), M('stone', shade(c.c0, .9))), 0, .25, 0));
    return g;
  },
  column(c) {
    const g = new THREE.Group(), m = M('stone', c.c0), h = Math.max(1, Math.min(2.6, c.H));
    lathe(g, [[.001, 0], [.3, 0], [.3, .1], [.2, .12], [.17, .3], [.16, h - .3], [.2, h - .12], [.3, h - .1], [.3, h], [.001, h]], m, 0, 0, 0, 24);
    return g;
  },
  door(c) {
    const g = new THREE.Group(), fr = M('wood', shade(c.c0, .8)), pn = M('wood', c.c0);
    const h = 1.75, w = .85;
    box(g, .1, h, .2, fr, -w / 2, 0, 0); box(g, .1, h, .2, fr, w / 2, 0, 0); box(g, w + .1, .1, .2, fr, 0, h, 0);
    box(g, w - .05, h - .02, .08, pn, 0, 0, 0);
    for (let i = 0; i < 3; i++) box(g, w - .2, .06, .1, M('metal', ironC), 0, .35 + i * .6, 0);
    sphere(g, .035, M('metal', '#c9a24a'), w / 2 - .14, .9, .07);
    return g;
  },
  fence(c) {
    const g = new THREE.Group(), m = M('wood', c.c0);
    for (const x of [-.45, .45]) box(g, .09, .9, .09, m, x, 0, 0);
    for (const y of [.3, .65]) box(g, 1, .07, .05, m, 0, y, 0);
    return g;
  },
  bridge(c) {
    const g = new THREE.Group(), m = M('wood', c.c0);
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
const VEG = {
  tree(c) {
    const g = new THREE.Group(), r = c.r;
    const palm = has(c.n, /palm/), dead = has(c.n, /dead|stump|bare/);
    const trunkC = '#6b4a2b', leaf = c.light && hexLum(c.c0) < .62 ? c.c0 : '#3f7a3a';
    const h = Math.max(.7, Math.min(2.6, c.H * .8));
    const tm = M('wood', trunkC);
    const trunk = place(new THREE.Mesh(new THREE.CylinderGeometry(.09, .16, h, 10), tm), 0, h / 2, 0);
    g.add(trunk);
    if (has(c.n, /stump/)) { trunk.scale.set(1.4, .35 / h, 1.4); trunk.position.y = .17; return g; }
    if (dead) { box(g, .04, h * .5, .04, tm, .12, h * .5, 0).rotation.z = -.9; return g; }
    const lm = M('noisy', leaf);
    if (palm) {
      for (let i = 0; i < 7; i++) {
        const a = i / 7 * Math.PI * 2, f = place(new THREE.Mesh(new THREE.ConeGeometry(.1, .75, 4), lm), Math.cos(a) * .3, h + .02, Math.sin(a) * .3);
        f.rotation.z = Math.cos(a) * 1.3; f.rotation.x = -Math.sin(a) * 1.3; f.scale.set(1, 1, .3); g.add(f);
      }
    } else {
      const R = .42 + r() * .12;
      for (let i = 0; i < 6; i++) sphere(g, R * (.55 + r() * .35), lm, (r() - .5) * .5, h + (r() - .3) * .35, (r() - .5) * .5);
      sphere(g, R, lm, 0, h + .1, 0);
    }
    return g;
  },
  bush(c) {
    const g = new THREE.Group(), lm = M('noisy', hexLum(c.c0) < .7 ? c.c0 : '#3f7a3a');
    for (let i = 0; i < 5; i++) sphere(g, .17 + c.r() * .12, lm, (c.r() - .5) * .45, .17 + c.r() * .12, (c.r() - .5) * .45);
    return g;
  },
  flower(c) {
    const g = new THREE.Group(), st = M('plain', '#3f7a3a'), pm = M('plain', c.light, { rough: .6 });
    for (let i = 0; i < 4; i++) {
      const x = (c.r() - .5) * .5, z = (c.r() - .5) * .5, h = .2 + c.r() * .25;
      const s = place(new THREE.Mesh(new THREE.CylinderGeometry(.01, .012, h, 5), st), x, h / 2, z); g.add(s);
      for (let k = 0; k < 5; k++) { const a = k / 5 * 6.28; sphere(g, .035, pm, x + Math.cos(a) * .04, h, z + Math.sin(a) * .04); }
      sphere(g, .025, M('plain', '#e8c23a'), x, h + .01, z);
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
    const g = new THREE.Group();
    for (let i = 0; i < 3; i++) {
      const x = (i - 1) * .22, h = .12 + c.r() * .12;
      g.add(place(new THREE.Mesh(new THREE.CylinderGeometry(.03, .04, h, 8), M('plain', '#e8dcc0')), x, h / 2, (c.r() - .5) * .2));
      const cap = place(new THREE.Mesh(new THREE.SphereGeometry(.1, 14, 8, 0, 6.28, 0, 1.4), M('plain', c.c0, { rough: .6 })), x, h, 0); g.add(cap);
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
const ROCK = {
  boulder: c => boulder(c, Math.min(1.5, c.fw * 1.1)),
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
    const W = Math.min(1.2, c.fw), H = .75;
    if (has(c.n, /round/)) { const top = place(new THREE.Mesh(new THREE.CylinderGeometry(W * .5, W * .5, .07, 28), m), 0, H - .035, 0); g.add(top); lathe(g, turnedLeg(H - .07), lg, 0, 0, 0); return g; }
    box(g, W, .07, W, m, 0, H - .07, 0);
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) lathe(g, turnedLeg(H - .07), lg, sx * (W / 2 - .07), 0, sz * (W / 2 - .07));
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
  bed(c) {
    const g = new THREE.Group(), w = M('wood', c.c0), cl = M('fabric', c.c1);
    box(g, .9, .3, 1.8, w, 0, .1, 0); soft(g, .85, .15, 1.7, .05, cl, 0, .35, 0.02); box(g, .9, .7, .07, w, 0, .1, -.9);
    soft(g, .55, .09, .3, .04, M('fabric', '#eee6d8'), 0, .5, -.7);
    return g;
  },
  cabinet(c) {
    const g = new THREE.Group(), m = M('wood', c.c0), p = M('wood', shade(c.c0, .85));
    const H = Math.max(.9, Math.min(1.9, c.H)), W = Math.min(1, c.fw);
    box(g, W, H, .45, m, 0, 0, 0);
    for (const s of [-1, 1]) box(g, W / 2 - .06, H - .2, .03, p, s * W / 4, .1, .24);
    for (const s of [-1, 1]) sphere(g, .025, M('metal', '#c9a24a'), s * .06, H / 2, .27);
    return g;
  },
  shelf(c) { const g = new THREE.Group(), m = M('wood', c.c0); box(g, .06, 1.6, .35, m, -.45, 0, 0); box(g, .06, 1.6, .35, m, .45, 0, 0); for (let i = 0; i < 4; i++) box(g, .9, .05, .35, m, 0, .1 + i * .45, 0); return g; },
};
function chest(c) {
  const g = new THREE.Group(), m = M('wood', c.c0), ir = M('metal', ironC);
  const W = Math.min(1, Math.max(.45, c.fw * .85)), H = Math.max(.3, Math.min(.8, c.H * .8)), D = W * .65;
  box(g, W, H * .6, D, m, 0, 0, 0);
  const lid = place(new THREE.Mesh(new THREE.CylinderGeometry(D / 2, D / 2, W, 16, 1, false, 0, Math.PI), m), 0, H * .6, 0);
  lid.rotation.z = Math.PI / 2; lid.rotation.y = 0; lid.rotation.order = 'ZYX'; g.add(lid);
  for (const x of [-W * .35, W * .35]) box(g, .05, H * .62, D + .02, ir, x, 0, 0);
  box(g, .07, .1, .04, M('metal', '#c9a24a'), 0, H * .45, D / 2 + .01);
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
  bag(c) {
    const g = new THREE.Group(), m = M('fabric', c.c0), s = Math.min(.6, Math.max(.25, c.fw * .55));
    const b = place(new THREE.Mesh(new THREE.SphereGeometry(s, 18, 12), m), 0, s * .8, 0); b.scale.set(1, 1.05, 1); g.add(b);
    g.add(place(new THREE.Mesh(new THREE.CylinderGeometry(s * .25, s * .45, s * .35, 12), m), 0, s * 1.7, 0));
    ring(g, s * .26, .018, M('leather', '#6b4a2b'), 0, s * 1.55, 0);
    return g;
  },
};

// ---------------------------------------------------------------- armas / armaduras / ferramentas
const lay = (g, y = .06) => { g.rotation.y = -.5; g.position.y = y; return g; };
function haft(g, L, r, m, x = 0) { const h = place(new THREE.Mesh(new THREE.CylinderGeometry(r, r, L, 8), m), x, 0, 0); h.rotation.z = Math.PI / 2; return g.add(h); }
function blade(c, len, w, thick = .02) {
  const g = new THREE.Group(), steel = M('metal', c.light && hexLum(c.light) > .5 ? c.light : '#b8bec6', { rough: .3 });
  const bl = new THREE.Shape(); bl.moveTo(0, -w / 2); bl.lineTo(len * .85, -w / 2); bl.lineTo(len, 0); bl.lineTo(len * .85, w / 2); bl.lineTo(0, w / 2); bl.closePath();
  const geo = new THREE.ExtrudeGeometry(bl, { depth: thick, bevelEnabled: true, bevelThickness: .008, bevelSize: .008, bevelSegments: 1 });
  const m = place(new THREE.Mesh(geo, steel), 0, 0, -thick / 2); g.add(m);
  return g;
}
const WEAP = {
  sword(c, sc = 1) {
    const g = new THREE.Group(), grip = M('leather', '#4b2f1c'), gold = M('metal', '#c9a24a');
    const L = .75 * sc, b = blade(c, L, .07 * sc); b.position.x = .1; g.add(b);
    box(g, .04, .05, .28 * sc, gold, .09, -.025, 0).rotation.y = 0;
    haft(g, .16 * sc, .018, grip, -.0); g.children[g.children.length - 1].position.x = -.0;
    sphere(g, .03, gold, -.09, 0, 0);
    return lay(g, .08);
  },
  dagger: c => WEAP.sword(c, .5),
  axe(c) {
    const g = new THREE.Group(), w = M('wood', '#6b4a2b'), st = M('metal', '#b8bec6', { rough: .3 });
    haft(g, .9, .022, w);
    const s = new THREE.Shape(); s.moveTo(0, 0); s.lineTo(.2, .17); s.lineTo(.2, -.17); s.closePath();
    const h = place(new THREE.Mesh(new THREE.ExtrudeGeometry(s, { depth: .04, bevelEnabled: false }), st), .3, 0, -.02); g.add(h);
    return lay(g, .06);
  },
  mace(c) {
    const g = new THREE.Group(), w = M('wood', '#5b3b22'), st = M('metal', '#8f959c');
    haft(g, .7, .022, w); sphere(g, .09, st, .38, 0, 0);
    for (let i = 0; i < 6; i++) { const a = i / 6 * 6.28, sp = place(new THREE.Mesh(new THREE.ConeGeometry(.02, .06, 6), st), .38 + Math.cos(a) * .1, Math.sin(a) * .1, 0); sp.rotation.z = a - Math.PI / 2; g.add(sp); }
    return lay(g, .1);
  },
  staff(c) {
    const g = new THREE.Group(), w = M('wood', c.c0);
    haft(g, 1.6, .025, w); sphere(g, .06, M('plain', c.light, { emissive: c.light, ei: .5, rough: .2 }), .82, 0, 0);
    return lay(g, .06);
  },
  bow(c) {
    const g = new THREE.Group(), w = M('wood', c.c0);
    const arc = place(new THREE.Mesh(new THREE.TorusGeometry(.5, .018, 6, 24, Math.PI), w), 0, 0, 0); arc.rotation.z = -Math.PI / 2; arc.position.x = -.0; g.add(arc);
    g.add(place(new THREE.Mesh(new THREE.CylinderGeometry(.004, .004, 1, 3), M('plain', '#e8dcc0')), -.0, 0, 0));
    g.children[1].position.x = 0; g.children[1].rotation.x = 0;
    return lay(g, .5);
  },
  polearm(c) {
    const g = new THREE.Group(); haft(g, 1.7, .02, M('wood', '#6b4a2b'));
    const h = blade(c, .3, .1); h.position.x = .85; g.add(h);
    return lay(g, .06);
  },
  siege(c) {
    const g = new THREE.Group(), w = M('wood', c.c0), st = M('metal', '#3d4045');
    lathe(g, [[.001, 0], [.12, 0], [.14, .2], [.12, .9], [.16, 1], [.001, 1]], st, 0, .18, 0).rotation.x = Math.PI / 2 - .25;
    g.children[0].position.set(0, .35, -.4);
    box(g, .5, .12, 1, w, 0, .12, 0);
    for (const x of [-.3, .3]) { const wh = place(new THREE.Mesh(new THREE.CylinderGeometry(.22, .22, .06, 16), w), x, .22, .2); wh.rotation.z = Math.PI / 2; g.add(wh); }
    return g;
  },
};
const ARMOR = {
  body(c) {
    const g = new THREE.Group(), m = M(has(c.n, /leather|studded/) ? 'leather' : 'metal', c.c0, { rough: .45 });
    const t = place(new THREE.Mesh(new THREE.CapsuleGeometry(.28, .35, 6, 16), m), 0, .5, 0); t.scale.set(1.15, 1, .75); g.add(t);
    for (const s of [-1, 1]) sphere(g, .14, m, s * .33, .75, 0);
    return g;
  },
  helm(c) {
    const g = new THREE.Group(), m = M('metal', c.c0, { rough: .4 });
    const d = place(new THREE.Mesh(new THREE.SphereGeometry(.24, 20, 12, 0, 6.28, 0, 1.9), m), 0, .22, 0); g.add(d);
    box(g, .04, .22, .04, m, 0, .12, .22);
    return g;
  },
  shield(c) {
    const g = new THREE.Group(), m = M(has(c.n, /wood/) ? 'wood' : 'metal', c.c0), tr = M('metal', '#c9a24a');
    const kite = has(c.n, /heater|kite|bronze|order|chaos/);
    let d;
    if (kite) { const s = new THREE.Shape(); s.moveTo(-.3, .4); s.lineTo(.3, .4); s.lineTo(.3, 0); s.quadraticCurveTo(.2, -.35, 0, -.5); s.quadraticCurveTo(-.2, -.35, -.3, 0); s.closePath(); d = new THREE.Mesh(new THREE.ExtrudeGeometry(s, { depth: .05, bevelEnabled: true, bevelSize: .015, bevelThickness: .015, bevelSegments: 1 }), m); }
    else d = new THREE.Mesh(new THREE.CylinderGeometry(.38, .38, .06, 28), m);
    if (!kite) d.rotation.x = Math.PI / 2;
    place(d, 0, .55, 0); g.add(d);
    const b = place(new THREE.Mesh(new THREE.SphereGeometry(.09, 12, 8, 0, 6.28, 0, 1.4), tr), 0, .55, .06); b.rotation.x = Math.PI / 2; g.add(b);
    g.rotation.x = -.3; g.rotation.y = .5;
    return g;
  },
};
const CLOTH = {
  robe(c) {
    const g = new THREE.Group(), m = M('fabric', c.c0);
    lathe(g, [[.001, 0], [.4, 0], [.32, .5], [.22, .9], [.2, 1.05], [.001, 1.05]], m, 0, 0, 0, 22);
    for (const s of [-1, 1]) { const sl = place(new THREE.Mesh(new THREE.CylinderGeometry(.07, .1, .5, 10), m), s * .32, .8, 0); sl.rotation.z = s * .5; g.add(sl); }
    ring(g, .22, .02, M('leather', '#4b2f1c'), 0, .6, 0);
    return g;
  },
};
const JEWEL = {
  ring(c) {
    const g = new THREE.Group(), au = M('metal', '#d4af37', { rough: .25 });
    const r = place(new THREE.Mesh(new THREE.TorusGeometry(.1, .018, 10, 24), au), 0, .11, 0); r.rotation.x = Math.PI / 2; g.add(r);
    sphere(g, .03, M('plain', c.light, { emissive: c.light, ei: .3, rough: .1 }), 0, .21, 0);
    return g;
  },
};

// ferramentas: cabo + cabeca por nome
function tool(c) {
  const g = new THREE.Group(), n = c.n, w = M('wood', '#6b4a2b'), st = M('metal', '#aeb4bb', { rough: .35 });
  if (has(n, /saw/)) { const b = blade(c, .6, .1, .01); g.add(b); box(g, .05, .1, .1, w, -.03, -.05, 0); return lay(g, .05); }
  if (has(n, /hammer|mallet|sledge|maul/)) { haft(g, .55, .02, w); box(g, .12, .12, .2, st, .28, -.06, -.1); return lay(g, .1); }
  if (has(n, /pick|shovel|spade|scythe|hoe|rake|fork/)) { haft(g, .9, .02, w); box(g, .04, .25, .28, st, .45, -.12, -.14); return lay(g, .1); }
  if (has(n, /scissors|shears|tongs|pliers/)) { for (const s of [-1, 1]) { const b = box(g, .35, .02, .03, st, 0, 0, s * .02); b.rotation.y = s * .15; } return lay(g, .05); }
  if (has(n, /pot|pan|cauldron|kettle|bowl|cup|mug|jug|pitcher/)) {
    lathe(g, [[.001, 0], [.15, 0], [.2, .18], [.22, .2], [.2, .2], [.001, .03]], M('metal', c.c0), 0, 0, 0, 20); return g;
  }
  haft(g, .5, .02, w); box(g, .1, .1, .06, st, .28, -.05, -.03);
  return lay(g, .08);
}

// ---------------------------------------------------------------- consumiveis / recursos / luzes / documentos
const CONS = {
  potion(c) {
    const g = new THREE.Group();
    const glass = M('plain', '#cfe6ef', { opacity: .35, rough: .05 });
    lathe(g, [[.001, 0], [.1, 0], [.12, .06], [.1, .2], [.04, .26], [.04, .34], [.001, .34]], glass, 0, 0, 0, 20);
    lathe(g, [[.001, .005], [.09, .005], [.11, .06], [.095, .16], [.001, .16]], M('plain', c.light, { emissive: c.light, ei: .35, rough: .2, opacity: .9 }), 0, 0, 0, 20);
    g.add(place(new THREE.Mesh(new THREE.CylinderGeometry(.045, .04, .07, 10), M('wood', '#8a5a32')), 0, .36, 0));
    return g;
  },
  food(c) {
    const g = new THREE.Group(), n = c.n;
    if (has(n, /bread|loaf/)) { const b = place(new THREE.Mesh(new THREE.SphereGeometry(.17, 14, 8), M('noisy', '#c28a45')), 0, .08, 0); b.scale.set(1.6, .7, 1); g.add(b); }
    else if (has(n, /cheese/)) { g.add(place(new THREE.Mesh(new THREE.CylinderGeometry(.18, .18, .12, 3), M('plain', '#e8c85a', { rough: .5 })), 0, .06, 0)); }
    else if (has(n, /ham|meat|steak|leg|sausage|fish|bacon|rib/)) { const b = place(new THREE.Mesh(new THREE.SphereGeometry(.14, 14, 10), M('plain', c.c0, { rough: .6 })), 0, .1, 0); b.scale.set(1.5, 1, 1); g.add(b); box(g, .05, .05, .05, M('plain', '#eee6d0'), .22, .1, 0); }
    else if (has(n, /apple|peach|pear|orange|lemon|grapes|banana|melon|pumpkin|fruit|pie|egg/)) { for (let i = 0; i < 3; i++) sphere(g, .08, M('plain', c.c0, { rough: .5 }), (i - 1) * .13, .08, (i % 2) * .08); }
    else { sphere(g, .12, M('plain', c.c0), 0, .12, 0); }
    return g;
  },
  reagent(c) {
    const g = new THREE.Group();
    for (let i = 0; i < 5; i++) sphere(g, .06 + c.r() * .03, M('noisy', c.c0, { rough: .7 }), (c.r() - .5) * .25, .07, (c.r() - .5) * .25);
    return g;
  },
};
const RES = {
  ingot(c) {
    const g = new THREE.Group(), m = M('metal', c.c0, { rough: .35 });
    const bar = (x, y, z) => { const geo = new THREE.CylinderGeometry(.08, .11, .5, 4); const b = place(new THREE.Mesh(geo, m), x, y, z); b.rotation.set(0, Math.PI / 4, Math.PI / 2); b.scale.set(1, 1, .8); return g.add(b); };
    bar(-.12, .08, 0); bar(.12, .08, 0); bar(0, .21, 0);
    return g;
  },
};
const LIGHT = {
  torch(c) {
    const g = new THREE.Group();
    g.add(place(new THREE.Mesh(new THREE.CylinderGeometry(.03, .04, .75, 8), M('wood', '#5b3b22')), 0, .37, 0));
    const f = place(new THREE.Mesh(new THREE.ConeGeometry(.09, .28, 10), M('plain', '#ffb030', { emissive: '#ff8a10', ei: 1.4 })), 0, .88, 0); g.add(f);
    g.add(place(new THREE.Mesh(new THREE.CylinderGeometry(.06, .035, .1, 8), M('metal', '#33363a')), 0, .76, 0));
    const pl = new THREE.PointLight(0xffa040, .6, 2); pl.position.set(0, .9, 0); g.add(pl);
    return g;
  },
};
const DOC = {
  book(c) {
    const g = new THREE.Group();
    if (has(c.n, /scroll/)) {
      const s = place(new THREE.Mesh(new THREE.CylinderGeometry(.04, .04, .3, 12), M('fabric', '#e8dcc0')), 0, .05, 0); s.rotation.z = Math.PI / 2; g.add(s);
      return lay(g, .05);
    }
    soft(g, .22, .06, .3, .01, M('leather', c.c0), 0, 0, 0);
    box(g, .2, .045, .27, M('plain', '#efe6d0'), .005, .008, 0);
    return g;
  },
};

// ---------------------------------------------------------------- decoracao
const DECO = {
  vase(c) {
    const g = new THREE.Group(), r = Math.min(.25, Math.max(.1, c.fw * .25));
    lathe(g, [[.001, 0], [r * .7, 0], [r, r * 1.2], [r * .85, r * 2.2], [r * .45, r * 2.6], [r * .6, r * 3], [.001, r * 3]], M('plain', c.c0, { rough: .3 }), 0, 0, 0, 24);
    return g;
  },
  statue(c) {
    const g = new THREE.Group(), st = M('stone', c.c0);
    box(g, .6, .3, .6, st, 0, 0, 0);
    lathe(g, [[.001, .3], [.2, .3], [.14, .8], [.17, 1.1], [.1, 1.2], [.1, 1.3], [.12, 1.4], [.1, 1.55], [.001, 1.6]], st, 0, 0, 0, 16);
    return g;
  },
  rug(c) {
    const g = new THREE.Group();
    box(g, Math.min(1.8, c.fw), .03, Math.min(1.8, c.fw * .7), M('fabric', c.c0), 0, 0, 0);
    box(g, Math.min(1.8, c.fw) - .15, .035, Math.min(1.8, c.fw * .7) - .15, M('fabric', c.c1), 0, 0, 0);
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
function bookshelf(c) {
  const g = new THREE.Group(), wd = M('wood', c.c0), W = .92, D = .32, H = 1.7, rows = 4;
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
function basket(c) {
  const g = new THREE.Group(), m = M('wood', c.c0, { rough: 1 });
  lathe(g, [[.001, 0], [.2, 0], [.27, .22], [.29, .26], [.26, .26], [.19, .03], [.001, .03]], m, 0, 0, 0, 20);
  g.add(place(new THREE.Mesh(new THREE.TorusGeometry(.26, .015, 6, 18, Math.PI), m), 0, .26, 0));
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
function logs(c) {
  const g = new THREE.Group(), m = M('wood', c.c0);
  for (let i = 0; i < 3; i++) { const l = place(new THREE.Mesh(new THREE.CylinderGeometry(.09, .09, .85, 10), m), (i - 1) * .17, .09 + (i === 1 ? .14 : 0), 0); l.rotation.x = 1.57; g.add(l); }
  return g;
}
function ore(c) { const g = new THREE.Group(); for (let i = 0; i < 3; i++) { const b = boulder({ ...c, it: { id: c.it.id + i } }, .22); b.position.set((i - 1) * .22, 0, (c.r() - .5) * .2); g.add(b); } return g; }
function lantern(c) {
  const g = new THREE.Group(), fe = M('metal', '#33363a');
  box(g, .16, .03, .16, fe, 0, 0, 0); box(g, .16, .03, .16, fe, 0, .3, 0);
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) box(g, .015, .3, .015, fe, sx * .07, 0, sz * .07);
  g.add(place(new THREE.Mesh(new THREE.CylinderGeometry(.05, .05, .24, 10), M('plain', '#ffb84a', { emissive: '#ff9a20', ei: 1.2 })), 0, .17, 0));
  return g;
}
function candle(c) {
  const g = new THREE.Group();
  g.add(place(new THREE.Mesh(new THREE.CylinderGeometry(.03, .03, .22, 10), M('plain', '#efe5c8', { rough: .6 })), 0, .11, 0));
  g.add(place(new THREE.Mesh(new THREE.ConeGeometry(.018, .06, 8), M('plain', '#ffb030', { emissive: '#ff8a10', ei: 1.5 })), 0, .25, 0));
  return g;
}
function brazier(c) {
  const g = new THREE.Group();
  lathe(g, [[.001, .3], [.06, .3], [.04, .1], [.14, 0], [.001, 0]], M('metal', '#33363a'), 0, 0, 0, 12);
  lathe(g, [[.001, .5], [.28, .5], [.22, .38], [.001, .36]], M('metal', '#3a3d42'), 0, 0, 0, 20);
  g.add(place(new THREE.Mesh(new THREE.ConeGeometry(.14, .4, 10), M('plain', '#ffb030', { emissive: '#ff7a10', ei: 1.4 })), 0, .65, 0));
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
function boots(c) { const g = new THREE.Group(), m = M('leather', c.c0); for (const s of [-1, 1]) { box(g, .1, .25, .1, m, s * .09, 0, 0); box(g, .1, .08, .2, m, s * .09, 0, .06); } return g; }
function hat(c) { const g = new THREE.Group(); lathe(g, [[.001, 0], [.3, 0], [.3, .03], [.14, .04], [.12, .3], [.001, .38]], M('fabric', c.c0), 0, 0, 0, 20); return g; }
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
  if (/book ?case|book ?shelf/i.test(it.name || '')) return 'bookcase';
  const top = it.cl && it.cl[0], cat = it.cat;
  const p = top ? top[1] : 0, lab = top ? top[0] : null, lc = lab && LABEL_CAT[lab];
  if (lab && p >= .3) {
    if (lc === cat) return lab;                                   // imagem e nome concordam: refina o subtipo
    if (STRUCT.has(cat)) { if (STRUCT.has(lc) && p >= .45) return lab; }       // construcao: so troca por outra construcao
    else if (WEAK.has(cat) || p >= .6) { if (!STRUCT.has(lc) || p >= .6) return lab; }
    else if (lc !== cat && it.sub === 'misc' && p >= .4) return lab;
  }
  // verde dominante na imagem: planta, mesmo que o nome diga outra coisa
  const gr = it.f && it.f.gr;
  if (gr > .45 && cat !== 'vegetation' && cat !== 'terrain' && !NOT_PLANT.test((it.name || '').toLowerCase())) return 'bush';
  if (cat === 'furniture' && lab === 'bookcase' && p >= .2) return lab;
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
  const cat = it.cat, sub = it.sub;
  let g;
  try {
    const lab = pickLabel(it);
    if (lab && FLAT_CARD.has(lab)) {
      const w = Math.max(.2, it.w / 44);
      if (lab === 'fire') { g = new THREE.Group(); g.add(place(new THREE.Mesh(new THREE.ConeGeometry(.2, .6, 10), M('plain', '#ffb030', { emissive: '#ff7a10', ei: 1.4 })), 0, .3, 0)); return g; }
      if (lab === 'painting' || lab === 'sign') return spriteCard(it, spriteTex, w, Math.max(.2, it.hp / 44), .2);
      g = new THREE.Group();
      const fm = new THREE.MeshStandardMaterial({ map: spriteTex, transparent: true, alphaTest: .3, side: THREE.DoubleSide, roughness: 1 });
      const fp = place(new THREE.Mesh(new THREE.PlaneGeometry(w, w * it.hp / it.w), fm), 0, .01, 0); fp.rotation.x = -Math.PI / 2; g.add(fp);
      return g;
    }
    if (lab && BY_LABEL[lab]) return BY_LABEL[lab](c);
    const fn = (TABLE[cat] && TABLE[cat][sub]) || CAT_FALLBACK[cat];
    if (cat !== 'vegetation' && has(c.n, /\bplants?\b|\bgrass\b|\bvines?\b|\bferns?\b|\bweeds?\b/)) g = VEG.bush(c);
    else if (has(c.n, /\b(cannon|iron|stone) ?balls?\b|\bshot\b/)) {
      g = new THREE.Group();
      for (let i = 0; i < 4; i++) sphere(g, .1, M('metal', '#3a3d42', { rough: .5 }), (i % 2 - .5) * .2 + (i > 1 ? .1 : 0), .1 + (i > 1 ? .15 : 0), (i > 1 ? 0 : .05));
    } else if (cat === 'decoration' && (sub === 'painting' || sub === 'web')) g = spriteCard(it, spriteTex, Math.max(.2, it.w / 44), Math.max(.2, it.hp / 44), .2);
    else if (fn) g = fn(c);
    else if (cat === 'effect' || cat === 'unknown') {
      const w = Math.max(.2, it.w / 44), h = Math.max(.2, it.hp / 44);
      if (cat === 'effect' && sub === 'fire') {
        g = new THREE.Group();
        g.add(place(new THREE.Mesh(new THREE.ConeGeometry(.2, .6, 10), M('plain', '#ffb030', { emissive: '#ff7a10', ei: 1.4 })), 0, .3, 0));
      } else if (sub === 'decal' || sub === 'marker' || sub === 'field') {
        g = new THREE.Group();
        const m = new THREE.MeshStandardMaterial({ map: spriteTex, transparent: true, alphaTest: .3, side: THREE.DoubleSide, roughness: 1 });
        const p = place(new THREE.Mesh(new THREE.PlaneGeometry(w, w * it.hp / it.w), m), 0, .01, 0);
        p.rotation.x = -Math.PI / 2; g.add(p);
      } else g = spriteCard(it, spriteTex, w, h);
    } else g = spriteCard(it, spriteTex, Math.max(.2, it.w / 44), Math.max(.2, it.hp / 44));
  } catch (e) {
    console.warn('builder falhou', it.hex, it.name, e);
    g = genericBlock(c);
  }
  return g;
}

// conjunto: pecas lado a lado; cada peca e o modelo automatico dela mesma
export function buildSet(st, itemOf, spriteTexOf) {
  const g = new THREE.Group();
  const xs = st.pieces.map(p => p.dx), ys = st.pieces.map(p => p.dy);
  const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2;
  for (const p of st.pieces) {
    const it = itemOf(p.id);
    const m = buildOne(it, spriteTexOf(it));
    m.position.set(p.dx - cx, p.dz * .144, p.dy - cy);
    g.add(m);
  }
  return g;
}

// ---------------------------------------------------------------- modelo fiel a art (malha do conversor + sprite modernizado)
let MESH = null;
export let MODE = 'fiel';
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
  crate: { make: hmCrate, ref: [44, 60] },
  bench: { make: hmBench, stone: stoneBench, ref: [44, 54] },
  table: { make: tableOne, stone: stoneTable, ref: [66, 61], minW: 56 },
  chair: { make: () => chairOne('chair'), ref: [30, 63] },
  stool: { make: () => chairOne('stool'), ref: [30, 40] },
};
const SUB_TEMPL = { barrel: 'barrel', crate: 'crate', table: 'table' };
function templateKey(it) {
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
  const steel = (f.gy || 0) > .4 || /iron|metal|steel|silver|gargoyle|bronze/.test(n);
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
