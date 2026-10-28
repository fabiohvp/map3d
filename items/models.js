// Modelos 3D procedurais dos itens. Unidades: 1 tile = 1; y para cima; origem no centro da pegada, no chao.
// Eixo x = dx do conjunto no mapa, eixo z = dy.
import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { wood, fabric, stone, iron, gold } from './textures.js';

const DEN = 1.1;   // repeticoes de textura por unidade de mundo

// caixa com UV proporcional ao tamanho real de cada face (veio nao estica)
function boxGeo(w, h, d, den = DEN, off = Math.random()) {
  const g = new THREE.BoxGeometry(w, h, d);
  const uv = g.attributes.uv, dims = [[d, h], [d, h], [w, d], [w, d], [w, h], [w, h]];
  for (let f = 0; f < 6; f++) for (let i = 0; i < 4; i++) {
    const k = f * 4 + i;
    uv.setXY(k, uv.getX(k) * dims[f][0] * den + off, uv.getY(k) * dims[f][1] * den + off);
  }
  return g;
}

function place(m, x, y, z) { m.position.set(x, y, z); m.castShadow = m.receiveShadow = true; return m; }
function box(g, w, h, d, mat, x, y, z) { return g.add(place(new THREE.Mesh(boxGeo(w, h, d), mat), x, y + h / 2, z)); }
function soft(g, w, h, d, r, mat, x, y, z) {
  return g.add(place(new THREE.Mesh(new RoundedBoxGeometry(w, h, d, 4, r), mat), x, y + h / 2, z));
}
// peca torneada (perna, coluna): perfil [raio, y]
function lathe(g, prof, mat, x, y, z, seg = 20) {
  const geo = new THREE.LatheGeometry(prof.map(([r, yy]) => new THREE.Vector2(r, yy)), seg);
  return g.add(place(new THREE.Mesh(geo, mat), x, y, z));
}
function sphere(g, r, mat, x, y, z) { return g.add(place(new THREE.Mesh(new THREE.SphereGeometry(r, 20, 14), mat), x, y, z)); }
function ring(g, R, t, mat, x, y, z) {
  const m = place(new THREE.Mesh(new THREE.TorusGeometry(R, t, 8, 40), mat), x, y, z);
  m.rotation.x = Math.PI / 2;
  return g.add(m);
}

const turnedLeg = h => [[.0, 0], [.05, 0], [.05, h * .06], [.035, h * .1], [.04, h * .2], [.065, h * .3], [.04, h * .4],
  [.04, h * .75], [.06, h * .8], [.06, h * .92], [.05, h]].map(([r, y]) => [Math.max(r, .001), y]);

// ---------------------------------------------------------------- barril / barrica
function barrel(r, h, { staves = 12, hoops, spigot = false } = {}) {
  const g = new THREE.Group();
  const w = wood({ base: 0x7a4c27, dark: 0x3d2412, planks: staves, seed: 5, rough: .7 });
  const fe = iron({ base: 0x3d4045, seed: 3 });
  const prof = [], N = 14, bulge = 1.14;
  for (let i = 0; i <= N; i++) {
    const t = i / N, y = t * h, rr = r * (1 + (bulge - 1) * (1 - Math.pow(2 * t - 1, 2)));
    prof.push([rr, y]);
  }
  const radiusAt = y => { const t = y / h; return r * (1 + (bulge - 1) * (1 - Math.pow(2 * t - 1, 2))); };
  const body = new THREE.Mesh(new THREE.LatheGeometry(prof.map(([a, b]) => new THREE.Vector2(a, b)), 36), w);
  const uv = body.geometry.attributes.uv;
  for (let i = 0; i < uv.count; i++) uv.setXY(i, uv.getX(i), uv.getY(i) * 1.5);
  body.castShadow = body.receiveShadow = true;
  g.add(body);
  // tampo e fundo (ligeiramente afundado) com tabuas
  const lid = place(new THREE.Mesh(new THREE.CylinderGeometry(r * .93, r * .93, .035, 36), w), 0, h - .02, 0);
  g.add(lid);
  const rim = place(new THREE.Mesh(new THREE.TorusGeometry(r * .93, .018, 6, 36), w), 0, h - .005, 0);
  rim.rotation.x = Math.PI / 2; g.add(rim);
  const bottom = place(new THREE.Mesh(new THREE.CylinderGeometry(r * .93, r * .93, .03, 24), w), 0, .015, 0);
  g.add(bottom);
  for (const y of (hoops || [.1, .3, .7, .9]).map(k => k * h)) {
    ring(g, radiusAt(y) + .006, .016, fe, 0, y, 0);
  }
  if (spigot) {
    const s = place(new THREE.Mesh(new THREE.CylinderGeometry(.022, .022, .12, 10), gold()), 0, h * .32, r * 1.1);
    s.rotation.x = Math.PI / 2; g.add(s);
    g.add(place(new THREE.Mesh(new THREE.BoxGeometry(.1, .018, .02), gold()), 0, h * .32 + .04, r * 1.17));
  }
  return g;
}

// cor do tecido de destaque (colcha, cortinado) e o tom claro da trama
const lighter = (c, k = 1.25) => new THREE.Color(c).multiplyScalar(k).getHex();

// ---------------------------------------------------------------- cama simples (2 pecas: 1x2 tiles)
// W x L = pegada (cabeceira em -z); quilt = cor da colcha; cot = catre, sem cabeceira nem peseira
function bed({ W = .96, L = 1.92, quilt = 0x8f2b38, cot = false } = {}) {
  const g = new THREE.Group();
  const wd = wood({ base: 0x8b5a2b, dark: 0x4a2a12, planks: 3, seed: 3 });
  const linen = fabric({ base: 0xdcd6c8, alt: 0xf2eee4, weave: 140, seed: 2 });
  const qa = quilt === 0x8f2b38 ? 0xb04755 : lighter(quilt);
  const quiltM = fabric({ base: quilt, alt: qa, weave: 70, seed: 6 });
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
    box(g, .09, .3, .09, wd, sx * (W / 2 - .045), 0, sz * (L / 2 - .045));
  }
  box(g, W, .12, .06, wd, 0, .24, L / 2 - .03);
  for (const sx of [-1, 1]) box(g, .06, .1, L, wd, sx * (W / 2 - .03), .26, 0);
  // estrado e colchao
  box(g, W - .1, .03, L - .06, wd, 0, .3, 0);
  soft(g, W - .1, .2, L - .12, .06, linen, 0, .33, 0);
  if (!cot) {
    // cabeceira alta com topo curvo + pes
    box(g, W, .75, .08, wd, 0, .2, -L / 2 + .04);
    const ar = Math.min(W / 2, .55);
    const arch = place(new THREE.Mesh(new THREE.CylinderGeometry(ar, ar, .08, 24, 1, false, Math.PI / 2, Math.PI), wd), 0, .95, -L / 2 + .04);
    arch.rotation.x = Math.PI / 2;
    g.add(arch);
    sphere(g, .05, gold(), -W / 2 + .045, .98, -L / 2 + .04);
    sphere(g, .05, gold(), W / 2 - .045, .98, -L / 2 + .04);
    // peseira baixa
    box(g, W, .35, .07, wd, 0, .2, L / 2 - .035);
  }
  // cobertor com dobra caindo dos lados + travesseiros (cama de casal: um por lado)
  const qz = .3 * L / 1.92;
  soft(g, W - .02, .07, L * .62, .03, quiltM, 0, .5, qz);
  for (const sx of [-1, 1]) soft(g, .04, .26, L * .62, .015, quiltM, sx * (W / 2 - .01), .3, qz);
  soft(g, W - .02, .27, .05, .02, quiltM, 0, .3, qz + L * .31);
  if (W > 1.4) for (const sx of [-1, 1]) soft(g, W * .4, .09, .34, .045, linen, sx * W * .22, .52, -L / 2 + .3);
  else soft(g, W * .62, .09, .34, .045, linen, 0, .52, -L / 2 + .3);
  return g;
}

// ---------------------------------------------------------------- cama de dossel (4 pecas: 2x2 tiles)
function canopyBed({ W = 1.6, L = 1.92, quilt = 0x6a727c } = {}) {
  const g = new THREE.Group();
  const H = 2.05;
  const wd = wood({ base: 0x9a6733, dark: 0x4f2e14, planks: 3, seed: 8 });
  const cloth = fabric({ base: quilt, alt: quilt === 0x6a727c ? 0x8e97a2 : lighter(quilt), weave: 80, seed: 12, rough: .9 });
  const lin = fabric({ base: 0xe9e4d8, alt: 0xfaf6ee, weave: 150, seed: 14 });
  box(g, W, .14, L, wd, 0, .22, 0);
  // base e pes
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
    const x = sx * (W / 2 - .06), z = sz * (L / 2 - .06);
    lathe(g, turnedLeg(H), wd, x, 0, z);
    sphere(g, .07, gold(), x, H + .05, z);
  }
  // cabeceira entalhada
  box(g, W - .1, .85, .07, wd, 0, .3, -L / 2 + .06);
  box(g, W - .22, .5, .02, wd, 0, .5, -L / 2 + .1);
  const crest = place(new THREE.Mesh(new THREE.CylinderGeometry(.34, .34, .07, 24, 1, false, Math.PI / 2, Math.PI), wd), 0, 1.15, -L / 2 + .06);
  crest.rotation.x = Math.PI / 2; g.add(crest);
  box(g, W - .1, .3, .06, wd, 0, .3, L / 2 - .06);                        // peseira
  // colchao, travesseiros, colcha
  soft(g, W - .14, .24, L - .2, .07, lin, 0, .36, 0);
  soft(g, W * .4, .11, .36, .05, lin, -W * .22, .6, -L / 2 + .33);
  soft(g, W * .4, .11, .36, .05, lin, W * .22, .6, -L / 2 + .33);
  soft(g, W - .1, .08, L * .62, .035, cloth, 0, .6, .26);
  for (const sx of [-1, 1]) soft(g, .05, .3, L * .62, .02, cloth, sx * (W / 2 - .07), .35, .26);
  soft(g, W - .1, .32, .05, .02, cloth, 0, .35, L / 2 - .16);
  // saia branca do colchao caindo ate o estrado
  const skirt = fabric({ base: 0xe9e4d8, alt: 0xfaf6ee, weave: 150, seed: 15 });
  for (const sx of [-1, 1]) soft(g, .03, .3, L - .3, .012, skirt, sx * (W / 2 - .09), .26, .04);
  soft(g, W - .3, .3, .03, .012, skirt, 0, .26, L / 2 - .1);
  return g;
}

// posicoes das pernas ao longo de um comprimento: so nas pontas ate ~3 tiles, depois um par a cada ~2 tiles
function legStops(L, inset) {
  const n = Math.max(1, Math.round((L - 2 * inset) / 2.2)), out = [];
  for (let i = 0; i <= n; i++) out.push(-L / 2 + inset + i * (L - 2 * inset) / n);
  return out;
}

// ---------------------------------------------------------------- balcao (3 pecas: 3x1 tiles)
// L = comprimento (eixo x), D = profundidade
function counter({ L = 2.96, D = .86 } = {}) {
  const g = new THREE.Group();
  const H = .98;
  const top = wood({ base: 0x7b4a24, dark: 0x3e2210, planks: 5, seed: 22, rough: .4 });
  const leg = wood({ base: 0x6b4020, dark: 0x30190a, planks: 1, seed: 23 });
  box(g, L, .1, D, top, 0, H - .1, 0);                                             // tampo grosso
  box(g, L + .03, .025, D + .03, top, 0, H - .015, 0);
  box(g, L - .2, .08, D - .2, leg, 0, H - .18, 0);                                 // avental
  for (const x of legStops(L, .1)) for (const sz of [-1, 1])                      // pernas nas pontas (e no meio se for comprido)
    lathe(g, turnedLeg(H - .1), leg, x, 0, sz * (D / 2 - .1));
  for (const x of legStops(L, .1)) box(g, .04, .04, D - .24, leg, x, .22, 0);
  return g;
}

// ---------------------------------------------------------------- mesa longa (3 pecas: 1x3 tiles)
// W = largura (eixo x), L = comprimento (eixo z)
function longTable({ W = .96, L = 2.94 } = {}) {
  const g = new THREE.Group();
  const H = .78;
  const wd = wood({ base: 0x9b6a38, dark: 0x4d2e15, planks: 5, seed: 31, rough: .5 });
  const leg = wood({ base: 0x7a4c25, dark: 0x3d2310, planks: 1, seed: 32 });
  box(g, W, .07, L, wd, 0, H - .07, 0);
  box(g, W - .16, .1, L - .16, leg, 0, H - .17, 0);                                // avental
  for (const sx of [-1, 1]) for (const z of legStops(L, .09)) lathe(g, turnedLeg(H - .17), leg, sx * (W / 2 - .09), 0, z);
  for (const sx of [-1, 1]) box(g, .045, .045, L - .3, leg, sx * (W / 2 - .09), .2, 0);
  box(g, W - .2, .045, .045, leg, 0, .2, 0);
  return g;
}

// ---------------------------------------------------------------- caixote
function crate() {
  const g = new THREE.Group();
  const S = .9, h = .86;
  const pl = wood({ base: 0xa07038, dark: 0x4d2e15, planks: 1, seed: 41, rough: .75 });
  const fr = wood({ base: 0x7a4e26, dark: 0x3a2210, planks: 1, seed: 42 });
  box(g, S - .1, h - .1, S - .1, fr, 0, .05, 0);
  for (const [nx, nz] of [[0, 1], [0, -1], [1, 0], [-1, 0]]) {
    for (let i = 0; i < 4; i++) {
      const y = .08 + i * (h - .2) / 4;
      const w = S - .22, th = .03, hh = (h - .2) / 4 - .02;
      if (nz) box(g, w, hh, th, pl, 0, y, nz * (S / 2 - .035));
      else box(g, th, hh, w, pl, nx * (S / 2 - .035), y, 0);
    }
  }
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) box(g, .1, h, .1, fr, sx * (S / 2 - .05), 0, sz * (S / 2 - .05));
  for (const y of [0, h - .1]) {                                                   // cintas de topo e base
    box(g, S, .1, .06, fr, 0, y, S / 2 - .03); box(g, S, .1, .06, fr, 0, y, -S / 2 + .03);
    box(g, .06, .1, S - .12, fr, S / 2 - .03, y, 0); box(g, .06, .1, S - .12, fr, -S / 2 + .03, y, 0);
  }
  for (let i = 0; i < 5; i++) box(g, S - .1, .02, .16, pl, 0, h - .02, -S / 2 + .15 + i * .15);   // tampa
  return g;
}

// ---------------------------------------------------------------- banco de madeira
// L = comprimento (eixo x); bancos compridos ganham cavaletes no meio
function bench({ L = .94 } = {}) {
  const g = new THREE.Group();
  const wd = wood({ base: 0x9d6c3a, dark: 0x52331a, planks: 2, seed: 51, rough: .55 });
  const leg = wood({ base: 0x75492a, dark: 0x38200f, planks: 1, seed: 52 });
  const W = .46, H = .44;
  box(g, L, .05, W, wd, 0, H - .05, 0);
  for (const x of legStops(L, .1)) {
    box(g, .07, H - .05, W - .08, leg, x, 0, 0);
    box(g, .12, .04, W, leg, x, H - .09, 0);
    box(g, .12, .03, W - .02, leg, x, 0, 0);
  }
  box(g, L - .3, .05, .05, leg, 0, .2, 0);
  return g;
}

// ---------------------------------------------------------------- mesa de pedra e banco de pedra
// W x L = pegada (comprimento no eixo z); mesas compridas ficam com uma coluna em cada ponta
function stoneTable({ W = .96, L = .96 } = {}) {
  const g = new THREE.Group();
  const st = stone({ base: 0xa3a39c, dark: 0x66665f, seed: 61 });
  const dk = stone({ base: 0x8c8c85, dark: 0x4f4f4a, seed: 62 });
  const cols = L > 1.5 ? legStops(L, .48) : [0];
  for (const z of cols) {
    box(g, .96, .12, .96, dk, 0, 0, z);                                            // base
    box(g, .6, .62, .6, st, 0, .12, z);                                            // coluna
    box(g, .8, .08, .8, dk, 0, .66, z);                                            // capitel
  }
  const slab = new THREE.Mesh(new RoundedBoxGeometry(W + .02, .1, L + .02, 3, .02), st);
  place(slab, 0, .78 + .05, 0); g.add(slab);
  return g;
}
// L = comprimento (eixo x)
function stoneBench({ L = .94 } = {}) {
  const g = new THREE.Group();
  const st = stone({ base: 0xa3a39c, dark: 0x66665f, seed: 71 });
  const dk = stone({ base: 0x8c8c85, dark: 0x4f4f4a, seed: 72 });
  for (const x of legStops(L, .17)) {
    box(g, .24, .3, .4, dk, x, 0, 0);
  }
  const slab = new THREE.Mesh(new RoundedBoxGeometry(L, .12, .46, 3, .02), st);
  place(slab, 0, .3 + .06, 0); g.add(slab);
  return g;
}


// ---------------------------------------------------------------- mesa de 1 tile e cadeira (modelos-modelo para itens soltos)
function tableOne() {
  const g = new THREE.Group();
  const wd = wood({ base: 0x9b6a38, dark: 0x4d2e15, planks: 4, seed: 31, rough: .5 });
  const leg = wood({ base: 0x7a4c25, dark: 0x3d2310, planks: 1, seed: 32 });
  const W = 1, H = .76;
  box(g, W, .07, W, wd, 0, H - .07, 0);
  box(g, W - .16, .09, W - .16, leg, 0, H - .16, 0);
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) lathe(g, turnedLeg(H - .16), leg, sx * (W / 2 - .09), 0, sz * (W / 2 - .09));
  return g;
}
function chairOne(kind = 'chair') {
  const g = new THREE.Group();
  const wd = wood({ base: 0x9d6c3a, dark: 0x52331a, planks: 2, seed: 51, rough: .55 });
  const leg = wood({ base: 0x75492a, dark: 0x38200f, planks: 1, seed: 52 });
  const W = .44, H = .46;
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
    const back = sz < 0;
    box(g, .05, back ? H + .55 : H - .05, .05, leg, sx * (W / 2 - .03), 0, sz * (W / 2 - .03));
  }
  box(g, W, .05, W, wd, 0, H - .05, 0);
  for (const y of [.12, .24]) { box(g, .035, .035, W - .06, leg, -(W / 2 - .03), y, 0); box(g, .035, .035, W - .06, leg, W / 2 - .03, y, 0); }
  if (kind !== 'stool') {
    box(g, W, .06, .04, wd, 0, H + .5, -(W / 2 - .03));
    for (let i = 0; i < 4; i++) box(g, .035, .38, .03, leg, -W / 2 + .1 + i * (W - .2) / 3, H + .1, -(W / 2 - .03));
  }
  return g;
}

export { barrel, crate, bench, bed, canopyBed, counter, longTable, stoneTable, stoneBench, tableOne, chairOne };

export { boxGeo, place, box, soft, lathe, sphere, ring, turnedLeg };

// ---------------------------------------------------------------- catalogo
// pecas: ids do jogo que viram este unico item (dx, dy = posicao no mapa)
export const ITEMS = [
  { name: 'Cama', kind: 'conjunto', build: bed, cam: 1,
    pieces: [['0A63', 0, 0], ['0A5C', 0, 1]], note: 'cabeceira + peseira → 1 cama' },
  { name: 'Cama de dossel', kind: 'conjunto', build: canopyBed, cam: 1.55,
    pieces: [['0A83', 0, 0], ['0A7F', 0, 1], ['0A82', 1, 0], ['0A7E', 1, 1]], note: '4 pecas 2×2 → 1 cama' },
  { name: 'Balcão', kind: 'conjunto', build: counter, cam: 1.7,
    pieces: [['0B3F', 0, 0], ['0B3D', 0, 1], ['0B3F', 0, 2]], note: 'pernas nas pontas + tampo' },
  { name: 'Mesa longa', kind: 'conjunto', build: longTable, cam: 1.7,
    pieces: [['0B6C', 0, 0], ['0B6D', 0, 1], ['0B6B', 0, 2]], note: '3 pecas → 1 mesa' },
  { name: 'Barril', kind: 'simples', build: () => barrel(.36, .98), cam: .95,
    pieces: [['0FAE', 0, 0]], note: 'aros de ferro, tampo de tabuas' },
  { name: 'Caixote', kind: 'simples', build: crate, cam: .95,
    pieces: [['0E3C', 0, 0]], note: 'ripas, quinas e tampa' },
  { name: 'Barrica', kind: 'simples', build: () => barrel(.2, .52, { staves: 9, hoops: [.14, .5, .86], spigot: true }), cam: .6,
    pieces: [['1AD7', 0, 0]], note: 'com torneira de bronze' },
  { name: 'Banco de madeira', kind: 'simples', build: bench, cam: .8,
    pieces: [['0B2C', 0, 0]], note: 'assento e pernas em tábua' },
  { name: 'Mesa de pedra', kind: 'simples', build: stoneTable, cam: 1.1,
    pieces: [['1206', 0, 0]], note: 'tampo, coluna e base' },
  { name: 'Banco de pedra', kind: 'simples', build: stoneBench, cam: .8,
    pieces: [['1209', 0, 0]], note: 'laje sobre dois blocos' },
];
