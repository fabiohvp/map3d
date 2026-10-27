import './style.css';
import { Camera } from './camera/camera';
import { ChunkLoader } from './loader/chunk-loader';
import { MapRenderer } from './renderer/map-renderer';

async function bootstrap() {
  const canvas = document.getElementById('glcanvas') as HTMLCanvasElement;
  if (!canvas) throw new Error('Canvas not found');

  const gl = canvas.getContext('webgl2', {
    alpha: false,
    antialias: true,
    depth: true,
    premultipliedAlpha: false
  });

  if (!gl) {
    alert('WebGL2 is not supported by your browser or graphics driver.');
    return;
  }

  // Handle Resize
  function resizeCanvas() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    camera.setViewport(canvas.width, canvas.height);
  }

  // Start centered on Tokuno Island city (Zento City: 368, 744)
  const camera = new Camera(368, 744);
  resizeCanvas();
  window.addEventListener('resize', resizeCanvas);

  // Initialize Loader
  const loader = new ChunkLoader(gl);
  await loader.init(4); // Map 4

  // Initialize Renderer
  const renderer = new MapRenderer(gl, loader);

  // --- Input Handling ---
  let isDragging = false;
  let isRightDragging = false;
  let lastMouseX = 0;
  let lastMouseY = 0;

  canvas.addEventListener('mousedown', (e) => {
    if (e.button === 0) {
      isDragging = true;
    } else if (e.button === 2) {
      isRightDragging = true;
    }
    lastMouseX = e.clientX;
    lastMouseY = e.clientY;
  });

  window.addEventListener('mousemove', (e) => {
    if (!isDragging && !isRightDragging) return;

    const dx = e.clientX - lastMouseX;
    const dy = e.clientY - lastMouseY;
    lastMouseX = e.clientX;
    lastMouseY = e.clientY;

    if (isDragging) {
      camera.pan(dx, dy);
    } else if (isRightDragging && camera.mode === 'orbit') {
      camera.rotateOrbit(-dx * 0.008, dy * 0.008);
    }
  });

  window.addEventListener('mouseup', (e) => {
    if (e.button === 0) isDragging = false;
    if (e.button === 2) isRightDragging = false;
  });

  canvas.addEventListener('contextmenu', (e) => e.preventDefault());

  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.15 : 0.87;
    camera.adjustZoom(factor);
    updateZoomSlider();
  }, { passive: false });

  // Keyboard navigation
  const keysDown: { [key: string]: boolean } = {};
  window.addEventListener('keydown', (e) => {
    keysDown[e.code] = true;
  });
  window.addEventListener('keyup', (e) => {
    keysDown[e.code] = false;
  });

  function processKeyboard() {
    const panStep = (12.0 / camera.zoom);
    let dx = 0;
    let dy = 0;
    if (keysDown['KeyW'] || keysDown['ArrowUp']) dy -= panStep;
    if (keysDown['KeyS'] || keysDown['ArrowDown']) dy += panStep;
    if (keysDown['KeyA'] || keysDown['ArrowLeft']) dx -= panStep;
    if (keysDown['KeyD'] || keysDown['ArrowRight']) dx += panStep;

    if (dx !== 0 || dy !== 0) {
      camera.pan(-dx, -dy);
    }
  }

  // --- UI Elements ---
  const fpsVal = document.getElementById('fps-val')!;
  const posVal = document.getElementById('pos-val')!;
  const chunkVal = document.getElementById('chunk-val')!;
  const zoomVal = document.getElementById('zoom-val')!;

  const btnClassic = document.getElementById('btn-mode-classic')!;
  const btnOrbit = document.getElementById('btn-mode-orbit')!;
  const chkTerrain = document.getElementById('chk-terrain') as HTMLInputElement;
  const chkStatics = document.getElementById('chk-statics') as HTMLInputElement;
  const chkRoofs = document.getElementById('chk-roofs') as HTMLInputElement;
  const zoomSlider = document.getElementById('zoom-slider') as HTMLInputElement;
  const btnZoomIn = document.getElementById('btn-zoom-in')!;
  const btnZoomOut = document.getElementById('btn-zoom-out')!;

  const minimapIndicator = document.getElementById('minimap-indicator')!;
  const minimapContainer = document.querySelector('.minimap-container') as HTMLElement;

  btnClassic.addEventListener('click', () => {
    camera.mode = 'classic';
    btnClassic.classList.add('active');
    btnOrbit.classList.remove('active');
  });

  btnOrbit.addEventListener('click', () => {
    camera.mode = 'orbit';
    btnOrbit.classList.add('active');
    btnClassic.classList.remove('active');
  });

  chkTerrain.addEventListener('change', () => {
    renderer.renderTerrain = chkTerrain.checked;
  });

  chkStatics.addEventListener('change', () => {
    renderer.renderStatics = chkStatics.checked;
  });

  chkRoofs.addEventListener('change', () => {
    renderer.roofCutZ = chkRoofs.checked ? 127.0 : 0.0;
  });

  function updateZoomSlider() {
    zoomSlider.value = camera.zoom.toFixed(2);
    zoomVal.textContent = camera.zoom.toFixed(1) + 'x';
  }

  zoomSlider.addEventListener('input', () => {
    camera.zoom = parseFloat(zoomSlider.value);
    zoomVal.textContent = camera.zoom.toFixed(1) + 'x';
  });

  btnZoomIn.addEventListener('click', () => {
    camera.adjustZoom(1.2);
    updateZoomSlider();
  });

  btnZoomOut.addEventListener('click', () => {
    camera.adjustZoom(0.83);
    updateZoomSlider();
  });

  // Teleport presets
  document.querySelectorAll('.preset-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const x = parseFloat(btn.getAttribute('data-x') || '724');
      const y = parseFloat(btn.getAttribute('data-y') || '724');
      camera.targetX = x;
      camera.targetY = y;
    });
  });

  // Minimap click to teleport
  minimapContainer.addEventListener('click', (e) => {
    const rect = minimapContainer.getBoundingClientRect();
    const relX = (e.clientX - rect.left) / rect.width;
    const relY = (e.clientY - rect.top) / rect.height;
    camera.targetX = Math.round(relX * loader.manifest.width);
    camera.targetY = Math.round(relY * loader.manifest.height);
  });

  // --- Render Loop ---
  let frameCount = 0;
  let lastTime = performance.now();
  let lastFpsUpdate = lastTime;

  function loop(now: number) {
    lastTime = now;

    processKeyboard();

    renderer.render(camera, now * 0.001);

    // Update HUD Stats
    frameCount++;
    if (now - lastFpsUpdate >= 500) {
      const fps = Math.round((frameCount * 1000) / (now - lastFpsUpdate));
      fpsVal.textContent = fps.toString();
      frameCount = 0;
      lastFpsUpdate = now;

      const tX = Math.round(camera.targetX);
      const tY = Math.round(camera.targetY);
      posVal.textContent = `${tX}, ${tY}`;

      const cX = Math.floor(camera.targetX / 64);
      const cY = Math.floor(camera.targetY / 64);
      chunkVal.textContent = `${cX}, ${cY}`;

      // Update minimap indicator
      const normX = camera.targetX / loader.manifest.width;
      const normY = camera.targetY / loader.manifest.height;
      minimapIndicator.style.left = `${normX * 100}%`;
      minimapIndicator.style.top = `${normY * 100}%`;
    }

    requestAnimationFrame(loop);
  }

  requestAnimationFrame(loop);
}

bootstrap().catch((err) => {
  console.error('Fatal initialization error:', err);
});
