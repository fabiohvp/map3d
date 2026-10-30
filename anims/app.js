// Visualizador das animacoes: quadro original (2D) ao lado do casco de voxels gerado por anims/extract.py (3D).
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const $ = (id) => document.getElementById(id);
const TYPES = { MONSTER: 'monstro', SEA_MONSTER: 'monstro marinho', ANIMAL: 'animal', HUMAN: 'humano', EQUIPMENT: 'equipamento', '': 'sem tipo' };
// direcao do jogo (0 = N ... 7 = NW) -> [direcao no arquivo, espelhada]; seta = para onde aponta na tela
const DIRS = [[3, true, '↗', 'N'], [2, true, '→', 'NE'], [1, true, '↘', 'E'], [0, false, '↓', 'SE'],
              [1, false, '↙', 'S'], [2, false, '←', 'SW'], [3, false, '↖', 'W'], [4, false, '↑', 'NW']];
const DIR_GRID = [6, 7, 0, 5, -1, 1, 4, 3, 2];   // posicao de cada direcao na grade 3x3 dos botoes
const THUMB = 64, THUMB_COLS = 32;

const S = { index: null, body: null, act: 0, dir: 4, frame: 0, playing: true, fps: 10, t: 0,
            d2: null, imgs: [], d3: null, buf: null, zoom2d: 0, uoCam: false, spin: false, lit: true };

// ---------------------------------------------------------------- lista de corpos

async function boot() {
  try {
    S.index = await (await fetch('data/index.json')).json();
  } catch (e) {
    $('msg').style.display = 'block';
    $('msg').innerHTML = 'Sem dados: rode <code>python -I anims/extract.py</code> na pasta map3d para gerar <code>anims/data/</code>.';
    $('app').style.display = 'none';
    return;
  }
  const types = [...new Set(S.index.bodies.map((b) => b.type))].sort();
  for (const t of types) $('ftype').add(new Option(`${TYPES[t] ?? t} (${S.index.bodies.filter((b) => b.type === t).length})`, t));
  $('q').oninput = $('ftype').onchange = renderList;
  renderList();
  const h = new URLSearchParams(location.hash.slice(1));
  const id = +(h.get('b') ?? 400);
  const b = S.index.bodies.find((x) => x.id === id) ?? S.index.bodies[0];
  await selectBody(b, +(h.get('a') ?? -1), +(h.get('d') ?? 4));
}

function renderList() {
  const q = $('q').value.trim().toLowerCase(), ft = $('ftype').value;
  const qn = q ? (q.startsWith('0x') ? parseInt(q, 16) : +q) : NaN;
  const list = $('list');
  list.textContent = '';
  let n = 0;
  for (const b of S.index.bodies) {
    if (ft && b.type !== ft) continue;
    if (q && !(b.id === qn || String(b.id).startsWith(q) || ('0x' + b.id.toString(16)).startsWith(q))) continue;
    const el = document.createElement('div');
    el.className = 'b' + (S.body && S.body.id === b.id ? ' on' : '');
    el.title = `${b.id} (0x${b.id.toString(16).toUpperCase()}) · ${TYPES[b.type] ?? b.type} · anim${b.file === 1 ? '' : b.file}.mul corpo ${b.fbody}`;
    const t = b.thumb ?? 0;
    el.innerHTML = `<i style="background-position:-${(t % THUMB_COLS) * THUMB}px -${Math.floor(t / THUMB_COLS) * THUMB}px"></i><span>${b.id}</span>`;
    el.onclick = () => selectBody(b, -1, S.dir);
    b.el = el;
    list.append(el);
    n++;
  }
  $('count').textContent = `${n} de ${S.index.bodies.length} corpos`;
}

// ---------------------------------------------------------------- carregar corpo

function loadImage(src) {
  return new Promise((ok, bad) => { const im = new Image(); im.onload = () => ok(im); im.onerror = bad; im.src = src; });
}

async function gunzip(resp) {
  const buf = await resp.arrayBuffer();
  const u = new Uint8Array(buf, 0, 2);
  if (u[0] !== 0x1f || u[1] !== 0x8b) return buf;          // servidor ja descomprimiu (Content-Encoding)
  const ds = new Response(new Blob([buf]).stream().pipeThrough(new DecompressionStream('gzip')));
  return ds.arrayBuffer();
}

let loadSeq = 0;
async function selectBody(b, act, dir) {
  const seq = ++loadSeq;
  $('title').textContent = `Corpo ${b.id} · 0x${b.id.toString(16).toUpperCase()}`;
  $('ttype').textContent = TYPES[b.type] ?? b.type;
  const d2 = await (await fetch(`data/2d/${b.id}.json`)).json();
  const ext = d2.ext ?? 'png';
  const imgs = await Promise.all([...Array(d2.pages).keys()].map((p) => loadImage(`data/2d/${b.id}${p ? '.' + p : ''}.${ext}`)));
  let d3 = null, buf = null;
  if (S.index.has3d !== false) {
    try {
      d3 = await (await fetch(`data/3d/${b.id}.json`)).json();
      // modo malha: modelo 3D com a textura dos sprites; senao voxels
      buf = await gunzip(await fetch(`data/3d/${b.id}.${d3.mode === 'mesh' ? 'mesh' : 'bin'}.gz`));
      // imagens dos angulos que o 2D nao tem, geradas por viewmorph.py (morph entre o anterior e o posterior)
      if (d3.tex) {
        const r = await fetch(`data/3d/${b.id}.morph.json`);
        if (r.ok) {
          const m = await r.json();
          m.imgs = await Promise.all([...Array(m.pages).keys()].map((p) => loadImage(`data/3d/${b.id}.morph${p ? '.' + p : ''}.webp`)));
          d3.morph = m;
        }
      }
    } catch (e) { d3 = null; console.warn('sem 3D', b.id, e); }
  }
  if (seq !== loadSeq) return;
  if (S.body?.el) S.body.el.classList.remove('on');
  S.body = b; S.d2 = d2; S.imgs = imgs; S.d3 = d3; S.buf = buf;
  b.el?.classList.add('on');
  const sel = $('act');
  sel.textContent = '';
  for (const [a, name, nf] of b.act) sel.add(new Option(`${a} · ${name} (${nf})`, a));
  const idle = b.act.find((x) => /^idle/i.test(x[1]));
  if (!b.act.some((x) => x[0] === act)) act = (idle ?? b.act[0])[0];
  sel.value = act;
  S.dir = dir;
  S.world = d3?.mode === 'mesh';
  S.meshBuf = S.world ? buf : null;
  S.lit = !d3?.smooth;                   // voxels com cor suavizada: sem luz, mais perto do sprite
  $('lit').classList.toggle('on', S.lit);
  setVoxelCapacity();
  if (S.world) startWorld();
  $('spin').hidden = S.world;
  $('lit').hidden = S.world || !!d3?.tex;    // faces texturizadas: cor do sprite, sem luz
  $('lbl3d').textContent = S.world ? '3D · modelo com a textura dos sprites' : `3D gerado (voxels${d3?.scan ? ', cor por varredura dos 8 ângulos' : d3?.smooth ? ', cor suavizada' : ''})`;
  selectAction(act);
}

function selectAction(a) {
  S.act = +a;
  S.frame = 0;
  S.t = 0;
  const rows = S.d2.act[S.act];
  // limites da acao em torno da ancora, iguais para as 8 direcoes (o quadro nao pula ao trocar de direcao)
  let half = 1, up = 1, dn = 0, nf = 0;
  for (const fr of rows) {
    nf = Math.max(nf, fr.length);
    for (const [, , , w, h, cx, cy] of fr) {
      half = Math.max(half, cx, w - cx);
      up = Math.max(up, cy + h);
      dn = Math.max(dn, -cy);
    }
  }
  S.bounds = { half, up, dn };
  S.nframes = nf;
  $('frame').max = Math.max(0, nf - 1);
  prepAction3d();
  fit3d();
  updateHash();
  draw();
}

function updateHash() {
  history.replaceState(null, '', `#b=${S.body.id}&a=${S.act}&d=${S.dir}`);
}

// ---------------------------------------------------------------- 2D

const c2d = $('c2d'), g2d = c2d.getContext('2d');

function zoom2d() {
  const r = c2d.getBoundingClientRect(), { half, up, dn } = S.bounds;
  if (S.zoom2d) return S.zoom2d;
  const z = Math.min((r.width - 24) / (2 * half), (r.height - 40) / (up + dn));
  return z >= 1 ? Math.floor(z) : z;
}

// posicao da ancora (pe do mobile) no canvas, em px CSS; a vista UO do 3D usa a mesma
function anchor2d() {
  const r = c2d.getBoundingClientRect(), { up, dn } = S.bounds, z = zoom2d();
  return [Math.round(r.width / 2), Math.round((r.height - (up + dn) * z) / 2 + up * z + 8)];
}

function draw2d() {
  const r = c2d.getBoundingClientRect(), dpr = devicePixelRatio || 1;
  const W = Math.round(r.width * dpr), H = Math.round(r.height * dpr);
  if (c2d.width !== W || c2d.height !== H) { c2d.width = W; c2d.height = H; }
  g2d.setTransform(1, 0, 0, 1, 0, 0);
  g2d.clearRect(0, 0, W, H);
  const [fdir, mirror] = DIRS[S.dir];
  const fr = S.d2.act[S.act][fdir];
  if (!fr || !fr.length) { $('i2d').textContent = 'sem quadros nessa direção'; return; }
  const [p, x, y, w, h, cx, cy] = fr[S.frame % fr.length];
  const z = zoom2d(), [ax, ay] = anchor2d();
  g2d.imageSmoothingEnabled = false;      // pixel a pixel tambem abaixo de 1x: a vista UO do 3D amostra igual
  g2d.setTransform(dpr * (mirror ? -1 : 1), 0, 0, dpr, ax * dpr, ay * dpr);
  // sombra da ancora
  g2d.fillStyle = 'rgba(0,0,0,.25)';
  g2d.beginPath(); g2d.ellipse(0, 0, 14 * z, 7 * z, 0, 0, Math.PI * 2); g2d.fill();
  g2d.drawImage(S.imgs[p], x, y, w, h, -cx * z, -(cy + h) * z, w * z, h * z);
  $('i2d').textContent = `dir ${DIRS[S.dir][3]} = arquivo ${fdir}${mirror ? ' espelhado' : ''} · ${w}×${h} px · centro ${cx},${cy} · ×${+z.toFixed(2)}`;
}

// ---------------------------------------------------------------- 3D

const c3d = $('c3d');
const renderer = new THREE.WebGLRenderer({ canvas: c3d, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1c2225);
const persp = new THREE.PerspectiveCamera(35, 1, 1, 20000);
const ortho = new THREE.OrthographicCamera(-1, 1, 1, -1, -20000, 20000);
const controls = new OrbitControls(persp, c3d);
controls.enableDamping = true;
scene.add(new THREE.HemisphereLight(0xffffff, 0x445048, 1.6));
const sun = new THREE.DirectionalLight(0xffffff, 1.5);
sun.position.set(-1, 2, 1.5);
scene.add(sun);
const ground = new THREE.Mesh(new THREE.CircleGeometry(1, 64), new THREE.MeshBasicMaterial({ color: 0x2a3330 }));
ground.rotation.x = -Math.PI / 2;
scene.add(ground);
const grid = new THREE.PolarGridHelper(1, 8, 4, 64, 0x3d4a46, 0x33403c);
scene.add(grid);
const model = new THREE.Group();          // gira com a direcao
scene.add(model);
const matLit = new THREE.MeshLambertMaterial();
const matFlat = new THREE.MeshBasicMaterial();
let vox = null;                            // InstancedMesh do quadro atual
const SRGB = new Float32Array(256).map((_, i) => { const c = i / 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; });

function setVoxelCapacity() {
  if (vox) {
    model.remove(vox);
    vox.geometry.dispose();
    if (vox.isInstancedMesh) vox.dispose();
    else faceMat.uniforms.map.value?.dispose();
    vox = null;
  }
  if (!S.d3 || S.world) return;
  if (S.d3.tex) {
    // faces texturizadas (extract.py --scan): mesma forma dos cubos, TEX x TEX texels por face
    vox = new THREE.Mesh(new THREE.BufferGeometry(), faceMat);
    vox.frustumCulled = false;
    model.add(vox);
    return;
  }
  let max = 1;
  for (const rows of Object.values(S.d3.act)) for (const [, n] of rows) max = Math.max(max, n);
  const s = S.d3.s;
  vox = new THREE.InstancedMesh(new THREE.BoxGeometry(s, s, s), S.lit ? matLit : matFlat, max);
  vox.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(max * 3), 3);
  vox.frustumCulled = false;
  const m = vox.instanceMatrix.array;
  for (let i = 0; i < max; i++) m.set([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1], i * 16);
  vox.count = 0;
  model.add(vox);
}

function frameVoxels(i) {
  const row = S.d3?.act[S.act]?.[i];
  if (!row || !row[1]) return null;
  const [off, n] = row;
  const xyz = new Uint8Array(S.buf, off, n * 3);
  const co = off + n * 3 + ((n * 3) & 1);
  return { n, xyz, col: new Uint16Array(S.buf, co, n) };
}

// chao (menor z da acao) e altura, para apoiar o modelo e enquadrar a camera
function prepAction3d() {
  S.a3 = null;
  if (S.world) { mob.base = S.act; if (!mob.moving && !mob.once) setMobAct(S.act); }
  if (!S.d3 || S.world) return;
  let zmin = 255, zmax = 0, x0 = 255, x1 = 0, y0 = 255, y1 = 0;
  const rows = S.d3.act[S.act] ?? [], frames = [];
  for (let i = 0; i < rows.length; i++) {
    const f = frameVoxels(i);
    if (!f) continue;
    frames.push(f);
    for (let k = 0; k < f.n; k++) {
      const x = f.xyz[k * 3], y = f.xyz[k * 3 + 1], z = f.xyz[k * 3 + 2];
      if (z < zmin) zmin = z;
      if (z > zmax) zmax = z;
      if (x < x0) x0 = x;
      if (x > x1) x1 = x;
      if (y < y0) y0 = y;
      if (y > y1) y1 = y;
    }
  }
  const s = S.d3.s, [ox, oy, oz] = S.d3.o;
  // centro horizontal da acao (o modelo gira em torno dele na orbita livre; na vista UO gira na ancora)
  const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
  let rmax = 1;
  for (const f of frames) for (let k = 0; k < f.n; k++) rmax = Math.max(rmax, Math.hypot(f.xyz[k * 3] - cx, f.xyz[k * 3 + 1] - cy));
  S.a3 = { ground: (zmin + oz) * s - s / 2, top: (zmax + oz) * s + s / 2, r: rmax * s + s, cx: (cx + ox) * s, cy: (cy + oy) * s };
}

// faces do cubo (eixo, sinal) e cantos P0 + u*E1 + v*E2, E1/E2 nos outros dois eixos em ordem (igual a extract.py)
const FACE_DIRS = [[0, 1], [0, -1], [1, 1], [1, -1], [2, 1], [2, -1]];
const TILE_COLS = 256;

// textura por vista: camada L = angulo (L*45 - 135) do 2D, camada 8 = base. Alfa: 1 = cor, 0,5 = transparente (fora
// do sprite nesse angulo), 0 = a vista nao ve. No angulo exato usa so a camada dele e descarta o transparente (o
// contorno e o do sprite); entre dois, mistura as duas mascaras e as cores; o que nenhuma das duas ve vem da base.
const faceMat = new THREE.ShaderMaterial({
  uniforms: { map: { value: null }, la: { value: 0 }, lb: { value: 0 }, wB: { value: 0 }, nl: { value: 9 }, band: { value: 0.1 }, cut: { value: 1 },
              size: { value: new THREE.Vector2(1, 1) }, T: { value: 4 } },
  side: THREE.DoubleSide,
  vertexShader: `
    attribute vec2 tile;
    varying vec2 vUv, vTile;
    void main() { vUv = uv; vTile = tile; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  fragmentShader: `
    uniform sampler2D map;
    uniform float la, lb, wB, nl, T, band, cut;
    uniform vec2 size;
    varying vec2 vUv, vTile;
    // texel dentro do quadrado da propria face (na borda a interpolacao vazava para a face vizinha no atlas)
    vec4 lay(float L) {
      vec2 t = vTile + clamp(floor(vUv * size - vTile), 0.0, T - 1.0) + 0.5;
      return texture2D(map, vec2(t.x / size.x, (t.y / size.y + L) / nl));
    }
    void main() {
      vec4 a = lay(la), base = lay(nl - 1.0);
      // cor / transparente; o corte de contorno so vale perto de um angulo do 2D (cut): fora dele o texel marcado
      // e superficie de verdade vista de lado, e cortar deixava o modelo oco
      float ca = step(0.75, a.a), ta = (step(0.25, a.a) - ca) * cut;
      if (wB <= 0.0) {
        if (ta > 0.5) discard;
        gl_FragColor = vec4(ca > 0.5 ? a.rgb : base.rgb, 1.0);
        return;
      }
      vec4 b = lay(lb);
      float cb = step(0.75, b.a), tb = (step(0.25, b.a) - cb) * cut;
      // cada camada vale sozinha ate perto do meio do caminho; troca numa faixa curta (band) em volta de 0,5.
      // Misturar ao longo dos 45 graus duplica o rosto: as duas projecoes nao se alinham na forma de voxels
      float w = smoothstep(0.5 - band, 0.5 + band, wB);
      if ((1.0 - w) * (1.0 - ta) + w * (1.0 - tb) < 0.5) discard;
      float ka = (1.0 - w) * ca, kb = w * cb;
      gl_FragColor = vec4(ka + kb > 0.0 ? (a.rgb * ka + b.rgb * kb) / (ka + kb) : base.rgb, 1.0);
    }`,
});

// imagem do angulo (sprite do 2D ou intermediaria gerada) projetada no modelo como o UO projetou o sprite: no angulo
// da imagem o que aparece e a propria imagem (transparente descartado). A camera fica entre duas imagens vizinhas
// (no maximo 45/steps graus): vale a mais perto, com troca curta no meio.
const morphMat = new THREE.ShaderMaterial({
  uniforms: {
    atlas: { value: null }, size: { value: new THREE.Vector2(1, 1) },
    rectA: { value: new THREE.Vector4() }, rectB: { value: new THREE.Vector4() },
    ancA: { value: new THREE.Vector2() }, ancB: { value: new THREE.Vector2() },
    phiA: { value: 0 }, phiB: { value: 0 }, wB: { value: 0 }, cosT: { value: 1 }, sinT: { value: 0 },
  },
  side: THREE.DoubleSide,
  vertexShader: `
    varying vec3 vPos;
    void main() { vPos = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  fragmentShader: `
    uniform sampler2D atlas;
    uniform vec2 size, ancA, ancB;
    uniform vec4 rectA, rectB;
    uniform float phiA, phiB, wB, cosT, sinT;
    varying vec3 vPos;
    vec4 view(vec4 rect, vec2 anc, float phi) {
      float c = cos(phi), s = sin(phi);
      vec2 p = anc + vec2(vPos.x * c - vPos.z * s, -vPos.y * cosT + (vPos.x * s + vPos.z * c) * sinT);
      if (p.x < 0.0 || p.y < 0.0 || p.x >= rect.z || p.y >= rect.w) return vec4(0.0);
      vec2 uv = (rect.xy + p) / size;
      return texture2D(atlas, vec2(uv.x, 1.0 - uv.y));
    }
    void main() {
      vec4 a = view(rectA, ancA, phiA);
      if (wB <= 0.0) { if (a.a < 0.5) discard; gl_FragColor = vec4(a.rgb, 1.0); return; }
      vec4 b = view(rectB, ancB, phiB);
      float w = smoothstep(0.35, 0.65, wB);
      float ha = step(0.5, a.a), hb = step(0.5, b.a);
      if ((1.0 - w) * ha + w * hb < 0.5) discard;
      float ka = (1.0 - w) * ha, kb = w * hb;
      gl_FragColor = vec4((a.rgb * ka + b.rgb * kb) / max(ka + kb, 1e-4), 1.0);
    }`,
});
let morphTex = null;

function morphView(phi) {
  const m = S.d3.morph, U = morphMat.uniforms, step = 45 / m.steps, n = 8 * m.steps;
  const imgs = m.act[S.act]?.[Math.min(S.frame, (m.act[S.act]?.length ?? 1) - 1)];
  if (!imgs) return;
  let f = (phi - m.angles[0]) / step;
  f = ((f % n) + n) % n;
  let ia = Math.floor(f), w = f - ia;
  if (w < 1e-3) w = 0;
  else if (w > 1 - 1e-3) { ia = (ia + 1) % n; w = 0; }
  const ib = (ia + 1) % n;
  const set = (s, i) => {
    const [p, x, y, wd, h, cx, cy] = imgs[i];
    U['rect' + s].value = new THREE.Vector4(x, y, wd, h);
    U['anc' + s].value = new THREE.Vector2(cx, cy + h);
    U['phi' + s].value = THREE.MathUtils.degToRad(m.angles[0] + i * step);
  };
  set('A', ia);
  set('B', ib);
  U.wB.value = w;
  if (morphTex?.image !== m.imgs[0]) {
    morphTex?.dispose();
    morphTex = new THREE.Texture(m.imgs[0]);
    morphTex.magFilter = morphTex.minFilter = THREE.NearestFilter;
    morphTex.generateMipmaps = false;
    morphTex.needsUpdate = true;          // sem conversao de cor: o shader devolve o pixel como esta
  }
  U.atlas.value = morphTex;
  U.size.value = new THREE.Vector2(m.imgs[0].width, m.imgs[0].height);
  const th = THREE.MathUtils.degToRad(S.d3.theta);
  U.cosT.value = Math.cos(th);
  U.sinT.value = Math.sin(th);
  vox.material = morphMat;
  const exact = w === 0 && ia % m.steps === 0;
  $('i3d').textContent = `câmera ${phi.toFixed(1)}° · imagem ${(m.angles[0] + ia * step).toFixed(1)}°` +
    (exact ? ' (sprite do 2D)' : w ? ` → ${(m.angles[0] + ib * step).toFixed(1)}° (${Math.round(w * 100)}%)` : ' (gerada)');
}

// angulo da camera em volta do modelo -> camadas e peso
function faceView(cam) {
  if (!vox || !S.d3?.tex) return;
  model.updateMatrixWorld(true);
  const dir = S.uoCam ? cam.getWorldDirection(new THREE.Vector3()).negate()
                      : cam.position.clone().sub(vox.getWorldPosition(new THREE.Vector3()));
  const local = dir.transformDirection(new THREE.Matrix4().copy(vox.matrixWorld).invert());
  const phi = Math.atan2(local.x, local.z) * 180 / Math.PI;     // 0 = vista do arquivo 0
  if (S.d3.morph) return morphView(phi);
  const L = S.d3.layers, n = L.length;
  let f = (phi - L[0]) / 45, la, w;
  if (f < 0) { la = n - 1; w = (phi + 180) / 45; } else { la = Math.min(Math.floor(f), n - 1); w = f - la; }
  let lb = (la + 1) % n;
  if (w < 1e-3) w = 0;
  else if (w > 1 - 1e-3) { la = lb; w = 0; }
  const U = faceMat.uniforms;
  U.la.value = la; U.lb.value = lb; U.wB.value = w; U.nl.value = n + 1;
  U.cut.value = Math.min(w, 1 - w) * 45 < 3 ? 1 : 0;    // ate 3 graus de um angulo do 2D: contorno do sprite
}

function faceGeometry(i) {
  const row = S.d3.act[S.act]?.[i];
  if (!row || !row[3]) return null;
  const [, , off, n] = row, T = S.d3.tex, s = S.d3.s, h = s / 2, NL = S.d3.layers.length + 1;
  const ijk = new Uint8Array(S.buf, off, n * 3), dir = new Uint8Array(S.buf, off + n * 3, n);
  const to = off + n * 4 + ((n * 4) & 1), t565 = new Uint16Array(S.buf, to, NL * n * T * T);
  const rows = Math.ceil(n / TILE_COLS), Wt = TILE_COLS * T, Ht = rows * T;
  const img = new Uint8Array(Wt * Ht * NL * 4);
  const pos = new Float32Array(n * 12), uv = new Float32Array(n * 8), tile = new Float32Array(n * 8), idx = new Uint32Array(n * 6);
  const c = [0, 0, 0], P = [0, 0, 0];
  for (let f = 0; f < n; f++) {
    const [ax, sg] = FACE_DIRS[dir[f]], [b, cc] = [0, 1, 2].filter((k) => k !== ax);
    for (let k = 0; k < 3; k++) c[k] = (ijk[f * 3 + k] + S.d3.o[k]) * s;
    const tx = (f % TILE_COLS) * T, ty = Math.floor(f / TILE_COLS) * T;
    let q = 0;
    for (const [u, v] of [[0, 0], [1, 0], [0, 1], [1, 1]]) {
      P[0] = c[0]; P[1] = c[1]; P[2] = c[2];
      P[ax] += sg * h;
      P[b] += -h + u * s;
      P[cc] += -h + v * s;
      // modelo: x direita, y para a camera, z para cima  ->  three: (x, z, y)
      pos.set([P[0], P[2], P[1]], f * 12 + q * 3);
      uv.set([(tx + u * T) / Wt, (ty + v * T) / Ht], f * 8 + q * 2);
      tile.set([tx, ty], f * 8 + q * 2);
      q++;
    }
    idx.set([0, 1, 3, 0, 3, 2].map((k) => f * 4 + k), f * 6);
    for (let L = 0; L < NL; L++) for (let tu = 0; tu < T; tu++) for (let tv = 0; tv < T; tv++) {
      const val = t565[((L * n + f) * T + tu) * T + tv], p = ((L * Ht + ty + tv) * Wt + tx + tu) * 4;
      img[p] = ((val >> 11) & 31) * 255 / 31; img[p + 1] = ((val >> 5) & 63) * 255 / 63; img[p + 2] = (val & 31) * 255 / 31;
      img[p + 3] = val > 1 ? 255 : val ? 128 : 0;
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
  g.setAttribute('tile', new THREE.BufferAttribute(tile, 2));
  g.setIndex(new THREE.BufferAttribute(idx, 1));
  const tex = new THREE.DataTexture(img, Wt, Ht * NL);
  tex.magFilter = tex.minFilter = THREE.NearestFilter;
  tex.needsUpdate = true;                  // sem conversao de cor: o shader devolve o pixel do sprite como esta
  return { g, tex, n, size: new THREE.Vector2(Wt, Ht) };
}

function draw3d() {
  if (!vox) return;
  if (S.d3.tex) {
    const r = faceGeometry(S.frame);
    vox.geometry.dispose();
    faceMat.uniforms.map.value?.dispose();
    vox.visible = !!r;
    if (!r) { $('i3d').textContent = 'sem voxels nesse quadro'; return; }
    vox.geometry = r.g;
    faceMat.uniforms.map.value = r.tex;
    faceMat.uniforms.size.value = r.size;
    faceMat.uniforms.T.value = S.d3.tex;
    $('i3d').textContent = `${r.n} faces com ${S.d3.tex}×${S.d3.tex} texels (varredura dos 8 ângulos) · voxel = ${S.d3.s.toFixed(2)} px`;
    return;
  }
  const f = frameVoxels(S.frame);
  const [ox, oy, oz] = S.d3.o, s = S.d3.s;
  if (!f) { vox.count = 0; $('i3d').textContent = 'sem voxels nesse quadro'; return; }
  const m = vox.instanceMatrix.array, c = vox.instanceColor.array;
  for (let k = 0; k < f.n; k++) {
    const j = k * 16;
    // modelo: x direita, y para a camera, z para cima  ->  three: (x, z, y)
    m[j + 12] = (f.xyz[k * 3] + ox) * s;
    m[j + 13] = (f.xyz[k * 3 + 2] + oz) * s;
    m[j + 14] = (f.xyz[k * 3 + 1] + oy) * s;
    const v = f.col[k];
    c[k * 3] = SRGB[((v >> 11) & 31) * 255 / 31 | 0];
    c[k * 3 + 1] = SRGB[((v >> 5) & 63) * 255 / 63 | 0];
    c[k * 3 + 2] = SRGB[(v & 31) * 255 / 31 | 0];
  }
  vox.count = f.n;
  vox.instanceMatrix.needsUpdate = true;
  vox.instanceColor.needsUpdate = true;
  $('i3d').textContent = `${f.n} voxels de superfície · voxel = ${s.toFixed(2)} px · grid ${S.d3.n.join('×')}`;
}

function yaw() { return (S.dir - 3) * Math.PI / 4; }   // direcao do arquivo k = modelo girado +45k graus

function fit3d() {
  if (!S.a3) return;
  const { ground: g, top, r } = S.a3;
  model.position.y = -g;
  ground.scale.setScalar(r * 1.25);
  grid.scale.setScalar(r * 1.25);
  const h = top - g, cy = h / 2;
  controls.target.set(0, cy, 0);
  const rc = c3d.getBoundingClientRect(), aspect = rc.width / Math.max(rc.height, 1);
  // distancia para caber a altura e o diametro (no eixo mais estreito do painel)
  const half = Math.max(h / 2, r * 1.15 / Math.max(aspect, 0.1)) * 1.5;
  const d = half / Math.tan(THREE.MathUtils.degToRad(persp.fov / 2));
  const th = THREE.MathUtils.degToRad(S.d3.theta);
  const dir = new THREE.Vector3(0.45, Math.sin(th), Math.cos(th)).normalize();
  persp.position.set(dir.x * d, cy + dir.y * d, dir.z * d);
  persp.near = d / 100; persp.far = d * 20;
  persp.updateProjectionMatrix();
  controls.update();
}

// camera ortografica da vista dos sprites: olha de (0, sen t, cos t), mesmo zoom e ancora do 2D
function placeOrtho() {
  const r = c3d.getBoundingClientRect(), r2 = c2d.getBoundingClientRect();
  const z = zoom2d(), [ax, ay2] = anchor2d();
  const ay = ay2 * r.height / r2.height;   // mesmas proporcoes se os paineis tiverem alturas diferentes
  const th = THREE.MathUtils.degToRad(S.d3?.theta ?? 26.565);
  ortho.position.set(0, Math.sin(th) * 5000, Math.cos(th) * 5000);
  ortho.up.set(0, 1, 0);
  ortho.lookAt(0, 0, 0);
  ortho.left = -ax * r.width / r2.width / z;
  ortho.right = (r.width - ax * r.width / r2.width) / z;
  ortho.top = ay / z;
  ortho.bottom = -(r.height - ay) / z;
  ortho.updateProjectionMatrix();
}

function render3d(dt) {
  const r = c3d.getBoundingClientRect();
  renderer.setSize(r.width, r.height, false);
  persp.aspect = r.width / Math.max(r.height, 1);
  persp.updateProjectionMatrix();
  model.visible = !S.world;
  world.visible = !!S.world;
  ground.visible = grid.visible = !S.world;
  if (S.world) return renderWorld(dt);
  if (S.spin && !S.uoCam) S.spinA = (S.spinA ?? 0) + dt * 0.6;
  model.rotation.y = -yaw() + (S.uoCam ? 0 : S.spinA ?? 0);
  if (vox && S.a3) vox.position.set(S.uoCam ? 0 : -S.a3.cx, 0, S.uoCam ? 0 : -S.a3.cy);
  if (S.uoCam) {
    // na vista UO a ancora do sprite fica na altura do chao do arquivo, nao no chao calculado
    model.position.y = 0;
    ground.position.y = grid.position.y = S.a3 ? S.a3.ground : 0;
    placeOrtho();
    faceView(ortho);
    renderer.render(scene, ortho);
  } else {
    model.position.y = S.a3 ? -S.a3.ground : 0;
    ground.position.y = grid.position.y = 0;
    controls.update();
    faceView(persp);
    renderer.render(scene, persp);
  }
}

// ---------------------------------------------------------------- modelo 3D com a textura dos sprites
// Malha do quadro (sprite3d.py) em px do modelo: x direita, y cima, z para a camera da vista 0 (arquivo 0). A cor de
// cada ponto vem do sprite das duas vistas gravadas mais perto da camera (0..4 = 45k graus), projetando o ponto como
// o UO projetou o modelo (ortografica, elevacao theta). No angulo exato de uma vista so ela conta e o transparente e
// descartado: a imagem e o proprio sprite. Camera do lado que o UO espelha: a malha e refletida em x, como o 2D.
// Mundo em px do sprite; 1 tile = px_tile px. Angulos no chao: atan2(z, x), z = sul; camera do UO fica a SE.

const WORLD = 40;
const world = new THREE.Group();
world.visible = false;
scene.add(world);
const floor = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ color: 0x26302d }));
floor.rotation.x = -Math.PI / 2;
world.add(floor);
const tiles = new THREE.GridHelper(WORLD, WORLD, 0x4a5a55, 0x34403c);
world.add(tiles);
const shadowMesh = new THREE.Mesh(new THREE.CircleGeometry(1, 40),
  new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.35, depthWrite: false }));
shadowMesh.rotation.x = -Math.PI / 2;
world.add(shadowMesh);
const mobGroup = new THREE.Group();        // gira com a direcao do mobile
world.add(mobGroup);

const meshMat = new THREE.ShaderMaterial({
  uniforms: {
    atlasA: { value: null }, atlasB: { value: null }, cleanA: { value: null }, cleanB: { value: null },
    depthA: { value: null }, depthB: { value: null },
    sizeA: { value: new THREE.Vector2(1, 1) }, sizeB: { value: new THREE.Vector2(1, 1) },
    ancA: { value: new THREE.Vector2() }, ancB: { value: new THREE.Vector2() },
    rectA: { value: new THREE.Vector4() }, rectB: { value: new THREE.Vector4() },
    phiA: { value: 0 }, phiB: { value: 0 }, wB: { value: 0 }, cosT: { value: 1 }, sinT: { value: 0 }, smoothTex: { value: 0 },
    vpA: { value: new THREE.Matrix4() }, vpB: { value: new THREE.Matrix4() },
  },
  side: THREE.DoubleSide,
  vertexShader: `
    varying vec3 vPos;
    void main() { vPos = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  fragmentShader: `
    uniform sampler2D atlasA, atlasB, cleanA, cleanB, depthA, depthB;
    uniform vec2 sizeA, sizeB, ancA, ancB;
    uniform vec4 rectA, rectB;
    uniform float phiA, phiB, wB, cosT, sinT, smoothTex;
    uniform mat4 vpA, vpB;
    varying vec3 vPos;
    // uv do ponto no atlas pela projecao da vista; z = 0 fora do retangulo do quadro
    vec3 uvOf(vec2 size, vec4 rect, vec2 anc, float phi) {
      float c = cos(phi), s = sin(phi);
      vec2 p = anc + vec2(vPos.x * c - vPos.z * s, -vPos.y * cosT + (vPos.x * s + vPos.z * c) * sinT);
      if (p.x < 0.0 || p.y < 0.0 || p.x >= rect.z || p.y >= rect.w) return vec3(0.0);
      vec2 uv = (rect.xy + p) / size;
      return vec3(uv.x, 1.0 - uv.y, 1.0);
    }
    vec4 view(sampler2D atlas, vec3 uv) {
      if (uv.z == 0.0) return vec4(0.0);
      vec4 t = texture2D(atlas, uv.xy);
      if (smoothTex > 0.5 && t.a > 0.0) t.rgb /= t.a;     // texel transparente e preto: filtro linear escurece a borda
      return t;
    }
    float seen(sampler2D dep, mat4 vp) {
      vec4 c = vp * vec4(vPos, 1.0);
      vec3 n = c.xyz / c.w;
      return n.z * 0.5 + 0.5 <= texture2D(dep, n.xy * 0.5 + 0.5).r + 0.003 ? 1.0 : 0.0;
    }
    void main() {
      vec3 ua = uvOf(sizeA, rectA, ancA, phiA);
      vec4 a = view(atlasA, ua);
      if (wB <= 0.0) {                      // angulo exato da vista: o sprite como esta
        if (a.a < 0.5) discard;
        gl_FragColor = vec4(a.rgb, 1.0);
        return;
      }
      vec3 ub = uvOf(sizeB, rectB, ancB, phiB);
      float ha = step(0.5, view(atlasA, ua).a), hb = step(0.5, view(atlasB, ub).a);
      // silhueta: mistura das duas mascaras pelo angulo (o vao que o casco fecha entre as pernas some)
      if ((1.0 - wB) * ha + wB * hb < 0.5) discard;
      // cor: atlas sem o contorno escuro do sprite, que no meio do corpo vira listra
      vec3 ca = ua.z > 0.0 ? texture2D(cleanA, ua.xy).rgb : vec3(0.0);
      vec3 cb = ub.z > 0.0 ? texture2D(cleanB, ub.xy).rgb : vec3(0.0);
      float ka = (1.0 - wB) * ha * seen(depthA, vpA), kb = wB * hb * seen(depthB, vpB);
      if (ka + kb <= 0.0) { ka = (1.0 - wB) * ha; kb = wB * hb; }   // nenhuma vista enxerga: a que tiver cor
      gl_FragColor = vec4((ca * ka + cb * kb) / (ka + kb), 1.0);
    }`,
});
const mobMesh = new THREE.Mesh(new THREE.BufferGeometry(), meshMat);
mobMesh.frustumCulled = false;
mobGroup.add(mobMesh);

// profundidade de cada vista (para saber se a vista enxerga o ponto), refeita quando o quadro muda
const depthScene = new THREE.Scene();
const depthMesh = new THREE.Mesh(mobMesh.geometry, new THREE.MeshBasicMaterial({ side: THREE.DoubleSide }));
depthScene.add(depthMesh);
const depthViews = [...Array(5)].map(() => {
  const rt = new THREE.WebGLRenderTarget(512, 512);
  rt.depthTexture = new THREE.DepthTexture(512, 512);
  return { rt, cam: new THREE.OrthographicCamera(), key: null, vp: new THREE.Matrix4() };
});

let textures = [];
const geoms = new Map();                   // "acao/quadro" -> BufferGeometry
const mob = { pos: new THREE.Vector3(), yaw: Math.PI / 4, act: 0, base: 0, frame: 0, t: 0, once: false, held: false,
              moving: false, run: false, goal: null };
const keys = new Set();

// atlas para angulos entre vistas: o contorno escuro de 1 px do sprite (borda com o transparente) pega a cor media
// dos vizinhos de dentro, e a cor tambem vaza 2 px para o transparente (alfa 0) para o filtro linear nao escurecer
function cleanAtlas(im) {
  const W = im.width, H = im.height, cv = document.createElement('canvas');
  cv.width = W; cv.height = H;
  const g = cv.getContext('2d');
  g.drawImage(im, 0, 0);
  const d = g.getImageData(0, 0, W, H), px = d.data;
  const op = new Uint8Array(W * H);
  for (let i = 0; i < W * H; i++) op[i] = px[i * 4 + 3] > 127 ? 1 : 0;
  // 1 = dentro, 2 = contorno, 0 = transparente
  const kind = new Uint8Array(W * H);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const i = y * W + x;
    if (!op[i]) continue;
    const edge = x === 0 || y === 0 || x === W - 1 || y === H - 1 || !op[i - 1] || !op[i + 1] || !op[i - W] || !op[i + W];
    kind[i] = edge ? 2 : 1;
  }
  const fill = (want, from) => {
    const out = [];
    for (let y = 1; y < H - 1; y++) for (let x = 1; x < W - 1; x++) {
      const i = y * W + x;
      if (kind[i] !== want) continue;
      let r = 0, gg = 0, b = 0, n = 0;
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
        const j = i + dy * W + dx;
        if (from.includes(kind[j])) { r += px[j * 4]; gg += px[j * 4 + 1]; b += px[j * 4 + 2]; n++; }
      }
      if (n) out.push(i, r / n, gg / n, b / n);
    }
    for (let k = 0; k < out.length; k += 4) {
      const i = out[k];
      px[i * 4] = out[k + 1]; px[i * 4 + 1] = out[k + 2]; px[i * 4 + 2] = out[k + 3];
      if (want === 0) kind[i] = 3;
    }
  };
  fill(2, [1]);                 // contorno <- dentro
  fill(0, [1, 2]);              // 1o anel de fora
  fill(0, [3]);                 // 2o anel de fora
  g.putImageData(d, 0, 0);
  return cv;
}

function startWorld() {
  for (const t of textures) { t.orig.dispose(); t.clean.dispose(); }
  for (const g of geoms.values()) g.dispose();
  geoms.clear();
  // textura de profundidade so existe na GPU depois do primeiro uso do alvo; sem isso o desenho falha inteiro
  for (const v of depthViews) {
    v.key = null;
    renderer.setRenderTarget(v.rt);
    renderer.clear();
  }
  renderer.setRenderTarget(null);
  const lin = S.d3.smooth ? THREE.LinearFilter : THREE.NearestFilter;
  const tex = (src, filter) => {
    const t = new THREE.Texture(src);
    t.magFilter = t.minFilter = filter;
    t.generateMipmaps = false;
    t.needsUpdate = true;                  // sem conversao de cor: o shader devolve o pixel do sprite como esta
    return t;
  };
  textures = S.imgs.map((im) => ({ orig: tex(im, lin), clean: tex(cleanAtlas(im), THREE.LinearFilter) }));
  const T = S.d3.px_tile;
  floor.scale.set(WORLD * T, WORLD * T, 1);
  tiles.scale.setScalar(T);
  const [sw, sl] = S.d3.shadow;
  shadowMesh.scale.set(sl * T, sw * T, 1);
  Object.assign(mob, { goal: null, once: false, held: false, moving: false });
  mob.pos.set(0, 0, 0);
  mob.yaw = S.dir * Math.PI / 4 - Math.PI / 2;
  const th = THREE.MathUtils.degToRad(S.d3.theta);
  meshMat.uniforms.cosT.value = Math.cos(th);
  meshMat.uniforms.sinT.value = Math.sin(th);
  meshMat.uniforms.smoothTex.value = S.d3.smooth ? 1 : 0;
  resetWorldCam();
}

function frameGeom(a, i) {
  const k = `${a}/${i}`;
  if (geoms.has(k)) return geoms.get(k);
  const row = S.d3.mesh[a]?.[i];
  if (!row || !row[1]) return null;
  const [off, nv, ni] = row;
  const q = new Int16Array(S.meshBuf, off, nv * 3), pos = new Float32Array(nv * 3);
  let r = 0;
  for (let j = 0; j < q.length; j++) { pos[j] = q[j] / 4; r = Math.max(r, Math.abs(pos[j])); }
  const io = off + nv * 6 + ((4 - (nv * 6) % 4) % 4);
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setIndex(new THREE.BufferAttribute(nv < 65536 ? new Uint16Array(S.meshBuf, io, ni) : new Uint32Array(S.meshBuf, io, ni), 1));
  g.userData.r = r;
  geoms.set(k, g);
  return g;
}

function resetWorldCam() {
  const T = S.d3.px_tile, th = THREE.MathUtils.degToRad(S.d3.theta), d = 9 * T, hy = 1.2 * T;
  controls.target.set(mob.pos.x, hy, mob.pos.z);
  persp.position.set(mob.pos.x + d * Math.cos(th) * Math.SQRT1_2, hy + d * Math.sin(th), mob.pos.z + d * Math.cos(th) * Math.SQRT1_2);
  persp.near = T * 0.05; persp.far = T * 400;
  persp.updateProjectionMatrix();
  controls.update();
}

function setMobAct(a, once = false) {
  if (S.d2.act[a] === undefined) return;
  mob.act = a; mob.frame = 0; mob.t = 0; mob.once = once; mob.held = false;
}

function actFps(a) {
  const m = S.d3.act[a];
  if (a === S.d3.roles.walk && m?.stride) return m.fps * (mob.run ? 2 : 1);
  return S.fps;
}

function tickWorld(dt) {
  const R = S.d3.roles, walk = S.d3.act[R.walk], T = S.d3.px_tile;
  const fwd = new THREE.Vector3().subVectors(controls.target, persp.position).setY(0).normalize();
  const right = new THREE.Vector3(-fwd.z, 0, fwd.x);
  const mv = new THREE.Vector3();
  if (keys.has('w')) mv.add(fwd);
  if (keys.has('s')) mv.sub(fwd);
  if (keys.has('d')) mv.add(right);
  if (keys.has('a')) mv.sub(right);
  if (mv.lengthSq() > 0) mob.goal = null;
  else if (mob.goal) {
    mv.subVectors(mob.goal, mob.pos).setY(0);
    if (mv.length() < 0.05 * T) { mob.goal = null; mv.set(0, 0, 0); }
  }
  mob.run = keys.has('shift') || !!mob.goal?.run;
  const moving = mv.lengthSq() > 0 && R.walk !== null;
  if (moving) {
    mv.normalize();
    const want = Math.atan2(mv.z, mv.x);
    const dy = ((want - mob.yaw + Math.PI * 3) % (Math.PI * 2)) - Math.PI;
    mob.yaw += Math.sign(dy) * Math.min(Math.abs(dy), dt * 12);
    const step = mv.multiplyScalar((walk?.speed ?? 2.5) * (mob.run ? 2 : 1) * T * dt);
    if (mob.goal) step.clampLength(0, mob.pos.distanceTo(mob.goal));
    const before = mob.pos.clone();
    mob.pos.add(step);
    const lim = (WORLD / 2 - 1) * T;
    mob.pos.x = THREE.MathUtils.clamp(mob.pos.x, -lim, lim);
    mob.pos.z = THREE.MathUtils.clamp(mob.pos.z, -lim, lim);
    const d = mob.pos.clone().sub(before);    // camera acompanha
    persp.position.add(d);
    controls.target.add(d);
    if (!mob.moving || mob.act !== R.walk) setMobAct(R.walk);
  } else if (mob.moving) setMobAct(mob.base);
  mob.moving = moving;
  const nf = S.d2.act[mob.act]?.[0]?.length || 1;
  if (!mob.held) {
    mob.t += dt * actFps(mob.act);
    while (mob.t >= 1) {
      mob.t -= 1;
      if (mob.frame + 1 < nf) mob.frame++;
      else if (mob.once) {
        if ((R.die ?? []).includes(mob.act)) { mob.held = true; break; }   // morto fica no chao
        setMobAct(mob.base);
      } else mob.frame = 0;
    }
  }
  const g = (((Math.round((mob.yaw + Math.PI / 2) / (Math.PI / 4))) % 8) + 8) % 8;
  if (g !== S.dir) { S.dir = g; updateHash(); draw(); }
}

// mapa de profundidade da vista k (camera ortografica no espaco da malha, mesma projecao do sprite)
function depthView(k, g, key) {
  const v = depthViews[k];
  if (v.key !== key) {
    const th = THREE.MathUtils.degToRad(S.d3.theta), ph = k * Math.PI / 4, r = g.userData.r * 1.05 + 2;
    v.cam.left = -r; v.cam.right = r; v.cam.top = r; v.cam.bottom = -r; v.cam.near = 0.1; v.cam.far = r * 4;
    v.cam.position.set(Math.sin(ph) * Math.cos(th), Math.sin(th), Math.cos(ph) * Math.cos(th)).multiplyScalar(r * 2);
    v.cam.up.set(0, 1, 0);
    v.cam.lookAt(0, 0, 0);
    v.cam.updateProjectionMatrix();
    v.cam.updateMatrixWorld();
    v.vp.multiplyMatrices(v.cam.projectionMatrix, v.cam.matrixWorldInverse);
    depthMesh.geometry = g;
    renderer.setRenderTarget(v.rt);
    renderer.clear();
    renderer.render(depthScene, v.cam);
    renderer.setRenderTarget(null);
    v.key = key;
  }
  return v;
}

// acao/quadro/direcao: na vista UO segue o 2D; no mundo, o mobile
function placeMob(cam) {
  const d3 = S.d3, uo = S.uoCam;
  const act = uo ? S.act : mob.act, fi = uo ? S.frame : mob.frame;
  const yaw = uo ? S.dir * Math.PI / 4 - Math.PI / 2 : mob.yaw;
  mobGroup.position.set(uo ? 0 : mob.pos.x, -d3.ground, uo ? 0 : mob.pos.z);
  mobGroup.rotation.y = Math.PI / 2 - yaw;     // frente da malha (+z) aponta para yaw
  shadowMesh.position.set(mobGroup.position.x, 0.5, mobGroup.position.z);
  shadowMesh.rotation.z = -yaw;
  const g = frameGeom(act, fi);
  mobMesh.visible = !!g;
  if (!g) return;
  mobMesh.geometry = g;
  // angulo da camera em volta da malha (sem reflexo): de que lado do modelo ela esta
  mobMesh.scale.x = 1;
  mobGroup.updateMatrixWorld(true);
  const dir = uo ? cam.getWorldDirection(new THREE.Vector3()).negate()
                 : cam.position.clone().sub(mobMesh.getWorldPosition(new THREE.Vector3()));
  const local = dir.transformDirection(new THREE.Matrix4().copy(mobMesh.matrixWorld).invert());
  let phi = Math.atan2(local.x, local.z);
  const mirror = phi < -1e-4;
  if (mirror) phi = -phi;
  mobMesh.scale.x = mirror ? -1 : 1;
  const q = Math.PI / 4;
  let ka = Math.min(Math.floor(phi / q), 4), w = phi / q - ka;
  if (w < 1e-3) w = 0;
  else if (w > 1 - 1e-3) { ka = Math.min(ka + 1, 4); w = 0; }
  const kb = Math.min(ka + 1, 4);
  const U = meshMat.uniforms, key = `${act}/${fi}`;
  const set = (s, k) => {
    const fr = S.d2.act[act]?.[k];
    const r = fr?.[Math.min(fi, fr.length - 1)];
    if (!r) {
      U['rect' + s].value = new THREE.Vector4(0, 0, 0, 0);
      U['atlas' + s].value = textures[0].orig;
      U['clean' + s].value = textures[0].clean;
      return;
    }
    const [p, x, y, wd, h, cx, cy] = r, im = S.imgs[p];
    U['atlas' + s].value = textures[p].orig;
    U['clean' + s].value = textures[p].clean;
    U['size' + s].value = new THREE.Vector2(im.width, im.height);
    U['rect' + s].value = new THREE.Vector4(x, y, wd, h);
    U['anc' + s].value = new THREE.Vector2(cx, cy + h);
    U['phi' + s].value = k * q;
    if (w > 0) {
      const v = depthView(k, g, key);
      U['depth' + s].value = v.rt.depthTexture;
      U['vp' + s].value = v.vp;
    }
  };
  set('A', ka);
  U.wB.value = w;
  if (w > 0) set('B', kb);
  else {
    U.atlasB.value = U.atlasA.value;
    U.cleanB.value = U.cleanA.value;
    U.depthA.value = U.depthB.value = depthViews[0].rt.depthTexture;
    U.vpA.value = U.vpB.value = depthViews[0].vp;
  }
  const nm = S.body.act.find((r) => r[0] === act)?.[1] ?? '';
  const vw = (k) => `arquivo ${k}${mirror ? ' espelhado' : ''}`;
  $('i3d').textContent = `${nm} ${fi + 1} · câmera ${(phi * 180 / Math.PI * (mirror ? -1 : 1)).toFixed(1)}° = ` +
    (w ? `${vw(ka)} ${Math.round((1 - w) * 100)}% + ${vw(kb)} ${Math.round(w * 100)}%` : `${vw(ka)} exato`) +
    (uo ? '' : ' · WASD anda, Shift corre, clique no chão vai, F ataca, H apanha, K morre, R distrai');
}

// camera ortografica a SE, mesma escala e ancora do 2D: o print bate com o sprite
function placeOrthoWorld() {
  // em px do buffer / dpr, como o 2D desenha (largura CSS fracionaria nao desalinha um do outro)
  const dpr = devicePixelRatio || 1;
  const r = { width: c3d.width / dpr, height: c3d.height / dpr }, r2 = { width: c2d.width / dpr, height: c2d.height / dpr };
  const z = zoom2d(), [ax2, ay2] = anchor2d();
  const ax = Math.round(ax2 * r.width / r2.width), ay = Math.round(ay2 * r.height / r2.height);
  const th = THREE.MathUtils.degToRad(S.d3.theta), o = mobGroup.position, D = 5000;
  ortho.position.set(o.x + Math.SQRT1_2 * Math.cos(th) * D, o.y + Math.sin(th) * D, o.z + Math.SQRT1_2 * Math.cos(th) * D);
  ortho.up.set(0, 1, 0);
  ortho.lookAt(o);
  ortho.left = -ax / z; ortho.right = (r.width - ax) / z; ortho.top = ay / z; ortho.bottom = -(r.height - ay) / z;
  ortho.near = 1; ortho.far = D * 2;
  ortho.updateProjectionMatrix();
  ortho.updateMatrixWorld();
}

function renderWorld(dt) {
  if (!S.uoCam) tickWorld(dt);
  controls.update();
  const cam = S.uoCam ? ortho : persp;
  if (S.uoCam) { mobGroup.position.set(0, -S.d3.ground, 0); placeOrthoWorld(); }
  placeMob(cam);
  shadowMesh.visible = !S.uoCam;
  renderer.render(scene, cam);
}

// clique (sem arrastar) no chao: anda ate o ponto; com Shift, corre
{
  let down = null;
  c3d.addEventListener('pointerdown', (e) => { down = [e.clientX, e.clientY]; });
  c3d.addEventListener('pointerup', (e) => {
    if (!S.world || S.uoCam || !down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
    const r = c3d.getBoundingClientRect();
    const ray = new THREE.Raycaster();
    ray.setFromCamera(new THREE.Vector2((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1), persp);
    const hit = ray.intersectObject(floor)[0];
    if (hit) { mob.goal = hit.point.setY(0); mob.goal.run = e.shiftKey; }
  });
}

// ---------------------------------------------------------------- controles e laco

function draw() {
  if (!S.body) return;
  $('frame').value = S.frame;
  $('flbl').textContent = `${S.frame + 1}/${S.nframes}`;
  for (const b of $('dirs').children) b.classList.toggle('on', +b.dataset.d === S.dir);
  draw2d();
  draw3d();
}

for (const d of DIR_GRID) {
  const b = document.createElement('button');
  if (d < 0) { b.disabled = true; b.style.visibility = 'hidden'; } else {
    b.textContent = DIRS[d][2];
    b.title = `${DIRS[d][3]} (direção ${d})`;
    b.dataset.d = d;
    b.onclick = () => { S.dir = d; if (S.world) mob.yaw = d * Math.PI / 4 - Math.PI / 2; updateHash(); draw(); };
  }
  $('dirs').append(b);
}
$('act').onchange = (e) => selectAction(e.target.value);
$('frame').oninput = (e) => { S.frame = +e.target.value; S.playing = false; $('play').textContent = '▶'; draw(); };
$('fps').oninput = (e) => { S.fps = +e.target.value; };
$('zoom2d').onchange = (e) => { S.zoom2d = +e.target.value; draw(); };
const togglePlay = () => { S.playing = !S.playing; $('play').textContent = S.playing ? '❚❚' : '▶'; };
$('play').onclick = togglePlay;
const step = (k) => { S.frame = (S.frame + k + S.nframes) % S.nframes; draw(); };
$('step').onclick = () => step(1);
$('cam').onclick = () => { S.uoCam = !S.uoCam; $('cam').classList.toggle('on', S.uoCam); controls.enabled = !S.uoCam; };
$('spin').onclick =() => { S.spin = !S.spin; $('spin').classList.toggle('on', S.spin); };
$('lit').onclick = () => { S.lit = !S.lit; $('lit').classList.toggle('on', S.lit); if (vox) vox.material = S.lit ? matLit : matFlat; };
addEventListener('keyup', (e) => keys.delete(e.key.toLowerCase()));
addEventListener('blur', () => keys.clear());
addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT' && e.target.type !== 'range') return;
  const k = e.key.toLowerCase();
  if (S.world && 'wasd'.includes(k) && k.length === 1 || k === 'shift') { keys.add(k); e.preventDefault(); return; }
  if (S.world && !e.repeat) {
    const R = S.d3.roles, one = (list) => list?.length && setMobAct(list[Math.floor(Math.random() * list.length)], true);
    if (k === 'f') return one(R.attack);
    if (k === 'h') return R.hit !== null && setMobAct(R.hit, true);
    if (k === 'k') return one(R.die);
    if (k === 'r') return one(R.fidget);
  }
  if (e.key === ' ') { togglePlay(); e.preventDefault(); }
  else if (e.key === 'ArrowRight') { S.playing && togglePlay(); step(1); e.preventDefault(); }
  else if (e.key === 'ArrowLeft') { S.playing && togglePlay(); step(-1); e.preventDefault(); }
  else if (e.key === 'q' || e.key === 'e') {
    S.dir = (S.dir + (e.key === 'e' ? 1 : 7)) % 8;
    if (S.world) mob.yaw = S.dir * Math.PI / 4 - Math.PI / 2;
    updateHash(); draw();
  }
});
addEventListener('resize', () => S.body && draw2d());

let last = performance.now();
function loop(now) {
  const dt = Math.min(0.1, (now - last) / 1000);
  last = now;
  if (S.body) {
    if (S.playing && S.nframes > 1) {
      S.t += dt * S.fps;
      if (S.t >= 1) { S.frame = (S.frame + Math.floor(S.t)) % S.nframes; S.t %= 1; draw(); }
    }
    render3d(dt);
  }
  requestAnimationFrame(loop);
}
requestAnimationFrame(loop);
boot();
