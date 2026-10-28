import * as THREE from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { ITEMS } from './models.js';
import { buildOne, buildSet, setMeshes, setMode } from './gen.js';
import { TEX } from './textures.js';

TEX.size = 256;   // texturas dos itens automaticos (cacheadas em cinza e tingidas)

const canvas = document.getElementById('gl');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
renderer.setScissorTest(true);
const env = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), .04).texture;

const grid = document.getElementById('grid');
const $ = id => document.getElementById(id);
let views = [];

// ---------------------------------------------------------------- cena de um card
function makeScene(model) {
  const scene = new THREE.Scene();
  scene.environment = env;
  scene.environmentIntensity = .55;
  const sun = new THREE.DirectionalLight(0xfff1dc, 2.4);
  sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024);
  sun.shadow.bias = -.0004; sun.shadow.normalBias = .02;
  scene.add(sun, new THREE.HemisphereLight(0xcfe0ff, 0x4a3a2a, .5));
  scene.add(model);
  const box = new THREE.Box3().setFromObject(model);
  const sph = box.getBoundingSphere(new THREE.Sphere());
  const R = Math.max(.35, sph.radius);
  sun.position.set(R * 2.2, R * 3.6, R * 1.8);
  Object.assign(sun.shadow.camera, { left: -R * 1.6, right: R * 1.6, top: R * 1.6, bottom: -R * 1.6, near: .1, far: R * 12 });
  const floor = new THREE.Mesh(new THREE.CircleGeometry(R * 3, 48), new THREE.ShadowMaterial({ opacity: .35 }));
  floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);
  const disc = new THREE.Mesh(new THREE.CircleGeometry(Math.max(.8, R * 1.15), 48), new THREE.MeshBasicMaterial({ color: 0x232b2e }));
  disc.rotation.x = -Math.PI / 2; disc.position.y = -.002; scene.add(disc);
  model.traverse(o => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
  const c = box.getCenter(new THREE.Vector3());
  return { scene, R, target: new THREE.Vector3(c.x, Math.max(c.y, .15), c.z) };
}

function disposeView(v) {
  v.scene.traverse(o => {
    if (o.geometry) o.geometry.dispose();
    if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach(m => m.dispose());
  });
}

function addView(el, model, camScale, i) {
  const { scene, R, target } = makeScene(model);
  const v = { el, scene, cam: new THREE.PerspectiveCamera(32, 1, .05, 80), yaw: Math.PI / 4, pitch: Math.atan(.5),
    dist: (camScale ?? 1) * R * 3.9, min: R * 1.2, max: R * 9, target, auto: true };
  views.push(v); window.__views = views;
  let drag = null;
  el.addEventListener('pointerdown', e => { drag = [e.clientX, e.clientY]; v.auto = false; el.setPointerCapture(e.pointerId); });
  el.addEventListener('pointermove', e => {
    if (!drag) return;
    v.yaw -= (e.clientX - drag[0]) * .01;
    v.pitch = Math.max(.05, Math.min(1.45, v.pitch + (e.clientY - drag[1]) * .008));
    drag = [e.clientX, e.clientY];
  });
  el.addEventListener('pointerup', () => { drag = null; });
  el.addEventListener('dblclick', () => { v.auto = true; });
  el.addEventListener('wheel', e => { e.preventDefault(); v.dist = Math.max(v.min, Math.min(v.max, v.dist * (1 + Math.sign(e.deltaY) * .08))); }, { passive: false });
}

function frame() {
  const W = innerWidth, H = innerHeight, pr = renderer.getPixelRatio();
  if (canvas.width !== Math.floor(W * pr) || canvas.height !== Math.floor(H * pr)) renderer.setSize(W, H, false);
  renderer.setScissor(0, 0, W, H); renderer.setViewport(0, 0, W, H);
  renderer.clear();
  for (const v of views) {
    const r = v.el.getBoundingClientRect();
    if (r.bottom < 0 || r.top > H || r.right < 0 || r.left > W) continue;
    if (v.auto) v.yaw += .004;
    const x = r.left, y = H - r.bottom;
    renderer.setViewport(x, y, r.width, r.height);
    renderer.setScissor(x, y, r.width, r.height);
    v.cam.aspect = r.width / r.height; v.cam.updateProjectionMatrix();
    const d = v.dist, cp = Math.cos(v.pitch);
    v.cam.position.set(v.target.x + d * cp * Math.sin(v.yaw), v.target.y + d * Math.sin(v.pitch), v.target.z + d * cp * Math.cos(v.yaw));
    v.cam.lookAt(v.target);
    renderer.render(v.scene, v.cam);
  }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

// ---------------------------------------------------------------- dados
let DATA = null, byHex = {};
const atlasImg = [];
const texCache = {};
function loadAtlas(i) {
  return atlasImg[i] || (atlasImg[i] = new Promise((res, rej) => {
    const im = new Image(); im.onload = () => res(im); im.onerror = rej; im.src = `data/atlas_${i}.png`;
  }));
}
// sprite "modernizado": bordas sangradas (sem halo preto), ampliado 3x com filtro suave, relevo vindo da luminancia
const UP = 3;
function bleed(d, w, h) {
  for (let it = 0; it < 3; it++) {
    const src = new Uint8ClampedArray(d.data);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const o = (y * w + x) * 4;
      if (src[o + 3] > 0) continue;
      let r = 0, g = 0, b = 0, n = 0;
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [-1, -1], [1, -1], [-1, 1]]) {
        const xx = x + dx, yy = y + dy;
        if (xx < 0 || yy < 0 || xx >= w || yy >= h) continue;
        const q = (yy * w + xx) * 4;
        if (src[q + 3] > 0) { r += src[q]; g += src[q + 1]; b += src[q + 2]; n++; }
      }
      if (n) { d.data[o] = r / n; d.data[o + 1] = g / n; d.data[o + 2] = b / n; d.data[o + 3] = 255; }   // so cor; o alfa original volta depois
    }
  }
}
async function spriteTexFor(it) {
  if (texCache[it.id]) return texCache[it.id];
  const im = await loadAtlas(it.atlas);
  const c = document.createElement('canvas'); c.width = it.w; c.height = it.hp;
  const cx = c.getContext('2d', { willReadFrequently: true });
  cx.drawImage(im, it.ax, it.ay, it.w, it.hp, 0, 0, it.w, it.hp);
  const raw = new THREE.CanvasTexture(c); raw.colorSpace = THREE.SRGBColorSpace;
  // versao modernizada para as malhas fieis
  const d = cx.getImageData(0, 0, it.w, it.hp);
  const alpha = new Uint8ClampedArray(it.w * it.hp);
  for (let i = 0; i < alpha.length; i++) alpha[i] = d.data[i * 4 + 3];
  bleed(d, it.w, it.hp);
  const c1 = document.createElement('canvas'); c1.width = it.w; c1.height = it.hp;
  c1.getContext('2d').putImageData(d, 0, 0);
  const big = document.createElement('canvas'); big.width = it.w * UP; big.height = it.hp * UP;
  const bx = big.getContext('2d'); bx.imageSmoothingEnabled = true; bx.imageSmoothingQuality = 'high';
  bx.drawImage(c1, 0, 0, big.width, big.height);
  const bd = bx.getImageData(0, 0, big.width, big.height);
  for (let y = 0; y < big.height; y++) for (let x = 0; x < big.width; x++) {   // alfa original ampliado (borda nitida)
    const a = alpha[Math.min(it.hp - 1, y / UP | 0) * it.w + Math.min(it.w - 1, x / UP | 0)];
    bd.data[(y * big.width + x) * 4 + 3] = a ? 255 : 0;
  }
  bx.putImageData(bd, 0, 0);
  const mapT = new THREE.CanvasTexture(big); mapT.colorSpace = THREE.SRGBColorSpace; mapT.anisotropy = 8;
  const bc = document.createElement('canvas'); bc.width = big.width; bc.height = big.height;
  const bcx = bc.getContext('2d'); bcx.fillStyle = '#808080'; bcx.fillRect(0, 0, bc.width, bc.height);
  bcx.filter = 'grayscale(1) blur(1.1px) contrast(1.5)'; bcx.drawImage(big, 0, 0);
  const bump = new THREE.CanvasTexture(bc);
  mapT.userData.bump = bump; mapT.userData.raw = raw;
  return (texCache[it.id] = mapT);
}
const thumb = (it, k = 1.5) => `<div class="thumb" title="0x${it.hex}" style="width:${it.w * k}px;height:${it.hp * k}px;background-image:url(data/atlas_${it.atlas}.png);background-position:-${it.ax * k}px -${it.ay * k}px;background-size:${2048 * k}px ${2048 * k}px"></div>`;
const palHtml = it => `<span class="pal">${it.pal.map(c => `<i style="background:${c}"></i>`).join('')}</span>`;

// ---------------------------------------------------------------- destaques (modelados a mao)
function renderHero() {
  clearViews();
  ITEMS.forEach((item, i) => {
    const card = document.createElement('section');
    card.className = 'card';
    const pieces = item.pieces.map(([id, dx, dy]) =>
      `<figure><img src="sprites/${id}.png" alt="${id}"><figcaption>0x${id}${item.pieces.length > 1 ? ` (${dx},${dy})` : ''}</figcaption></figure>`).join('');
    card.innerHTML = `<div class="view"></div>
      <div class="info"><h2>${item.name} <span class="tag ${item.kind === 'conjunto' ? 'set' : ''}">${item.kind === 'conjunto' ? item.pieces.length + ' peças → 1' : 'peça única'}</span></h2>
      <div class="note">${item.note}</div>
      <div class="lbl">Sprite original</div><div class="orig">${pieces}</div></div>`;
    grid.appendChild(card);
    addView(card.querySelector('.view'), item.build(), 1.0, i);
  });
}

// ---------------------------------------------------------------- todos
const PAGE = 24;
let page = 0, list = [];
const curatedKeys = new Map(ITEMS.map(it => [it.pieces.map(p => p[0]).sort().join('|'), it]));

function clearViews() {
  views.forEach(disposeView);
  views = [];
  grid.innerHTML = '';
}

function applyFilters() {
  setMode($('f-mode').value);
  const cat = $('f-cat').value, kind = $('f-kind').value, q = $('f-q').value.trim().toLowerCase(), hideAbs = $('f-abs').checked;
  const out = [];
  if (kind !== 'single') for (const s of DATA.sets) out.push({ type: 'set', st: s, cat: s.cat, name: s.name, uses: s.uses, hex: s.pieces.map(p => p.id).join(' ') });
  if (kind !== 'set') for (const it of DATA.items) if (!(hideAbs && it.absorbed)) out.push({ type: 'single', it, cat: it.cat, name: it.name, uses: it.uses, hex: it.hex });
  list = out.filter(e => (!cat || e.cat === cat) && (!q || e.name.toLowerCase().includes(q) || e.hex.toLowerCase().includes(q)))
    .sort((a, b) => a.cat.localeCompare(b.cat) || b.uses - a.uses);
  page = 0;
  renderPage();
}

async function renderPage() {
  const gen = ++renderPage.gen;
  const n = Math.ceil(list.length / PAGE) || 1;
  $('count').textContent = `${list.length} itens`;
  $('pg').textContent = `${page + 1} / ${n}`;
  $('prev').disabled = page === 0; $('next').disabled = page >= n - 1;
  const slice = list.slice(page * PAGE, page * PAGE + PAGE);
  // sprites necessarios para efeitos/desconhecidos/quadros
  const need = new Set();
  for (const e of slice) for (const it of (e.type === 'set' ? e.st.pieces.map(p => byHex[p.id]) : [e.it])) need.add(it);
  await Promise.all([...need].map(spriteTexFor));
  if (gen !== renderPage.gen) return;
  clearViews();
  slice.forEach((e, i) => {
    const card = document.createElement('section');
    card.className = 'card';
    let model, thumbs, meta, title, tag;
    const texOf = it => texCache[it.id];
    if (e.type === 'set') {
      const ids = e.st.pieces.map(p => p.id);
      const cur = curatedKeys.get([...ids].sort().join('|'));
      model = cur ? cur.build() : buildSet(e.st, id => byHex[id], it => texOf(it));
      const ps = e.st.pieces.map(p => byHex[p.id]);
      thumbs = ps.map(p => `<figure>${thumb(p)}<figcaption>0x${p.hex}</figcaption></figure>`).join('');
      title = cur ? cur.name : e.st.name; tag = `<span class="tag set">${ids.length} peças → 1</span>`;
      meta = `${e.st.cat}/${e.st.sub} · ${e.st.uses}× no mapa${cur ? ' · modelado à mão' : model.userData.templ ? ` · modelo à mão (${model.userData.templ})` : ''}`;
    } else {
      const it = e.it;
      const cur = curatedKeys.get(it.hex);
      model = cur ? cur.build() : buildOne(it, texOf(it));
      thumbs = `<figure>${thumb(it)}<figcaption>0x${it.hex}</figcaption></figure>`;
      title = it.name || '(sem nome)'; tag = '<span class="tag">peça única</span>';
      meta = `${it.cat}/${it.sub} · ${it.uses}× no mapa · h=${it.h}${it.flags.length ? ' · ' + it.flags.join(', ') : ''}`;
    }
    const pal = e.type === 'single' ? palHtml(e.it) : '';
    card.innerHTML = `<div class="view"></div>
      <div class="info"><h2>${title} ${tag}<span class="tag cat">${e.cat}</span></h2>
      <div class="meta">${meta}${pal}</div>
      <div class="lbl">Sprite original</div><div class="orig">${thumbs}</div></div>`;
    grid.appendChild(card);
    addView(card.querySelector('.view'), model, 1.0, i);
  });
  scrollTo({ top: 0 });
}
renderPage.gen = 0;

// ---------------------------------------------------------------- abas
async function showAll() {
  $('tab-all').classList.add('on'); $('tab-hero').classList.remove('on'); $('filters').hidden = false;
  if (!DATA) {
    grid.innerHTML = '<p style="grid-column:1/-1;color:var(--muted)">carregando itens…</p>';
    DATA = await (await fetch('data/items.json')).json();
    DATA.items.forEach(it => byHex[it.hex] = it);
    setMeshes(await (await fetch('data/meshes.json')).json(), await (await fetch('data/meshes.bin')).arrayBuffer());
    const cats = Object.entries(DATA.cats).sort((a, b) => b[1] - a[1]);
    $('f-cat').innerHTML = '<option value="">todas as categorias</option>' + cats.map(([c, n]) => `<option value="${c}">${c} (${n})</option>`).join('');
    ['f-cat', 'f-kind', 'f-abs', 'f-mode'].forEach(id => $(id).addEventListener('change', applyFilters));
    $('f-q').addEventListener('input', () => { clearTimeout(showAll.t); showAll.t = setTimeout(applyFilters, 250); });
    $('prev').onclick = () => { page--; renderPage(); };
    $('next').onclick = () => { page++; renderPage(); };
  }
  applyFilters();
}
$('tab-all').onclick = showAll;
$('tab-hero').onclick = () => {
  $('tab-hero').classList.add('on'); $('tab-all').classList.remove('on'); $('filters').hidden = true;
  renderPage.gen++;
  renderHero();
};
renderHero();
