import type { Manifest, LoadedChunk, TerrainChunkGPU, StaticsChunkGPU } from '../types';
import { createTexture2D, createTexture2DArray } from '../webgl/gl-utils';

export class ChunkLoader {
  private gl: WebGL2RenderingContext;
  public manifest!: Manifest;

  // Shared GPU resources
  public matTableTex!: WebGLTexture;
  public land64Tex!: WebGLTexture;
  public land128Tex!: WebGLTexture;
  public spriteMetaTex!: WebGLTexture;
  public atlasPages: WebGLTexture[] = [];
  public huesTex!: WebGLTexture;

  // LRU Chunk cache
  private cache: Map<string, LoadedChunk> = new Map();
  private maxCacheSize = 150;
  private pendingFetches: Set<string> = new Set();

  constructor(gl: WebGL2RenderingContext) {
    this.gl = gl;
  }

  public async init(mapId: number = 4): Promise<void> {
    const gl = this.gl;

    // 1. Fetch manifest
    const manifestRes = await fetch(`/out/map${mapId}/manifest.json`);
    this.manifest = await manifestRes.json();

    // 2. Fetch shared hues.bin
    const huesRes = await fetch('/out/shared/hues.bin');
    const huesBuf = await huesRes.arrayBuffer();
    // 32x3000 RGB5_A1
    this.huesTex = createTexture2D(
      gl,
      32,
      3000,
      gl.RGB5_A1,
      gl.RGBA,
      gl.UNSIGNED_SHORT_5_5_5_1,
      new Uint16Array(huesBuf)
    );

    // 3. Fetch shared materials.bin
    const matRes = await fetch('/out/shared/materials.bin');
    const matBuf = await matRes.arrayBuffer();
    const matDataView = new DataView(matBuf);
    // Header 'MAT1', LUT 16384 * 2 = 32768, nMat (u32)
    const nMat = matDataView.getUint32(32772, true);

    // Build 256x256 RGBA16UI table for materials: r=kind, g=texArray, b=texLayer, a=flags
    const matTableArray = new Uint16Array(256 * 256 * 4);
    let offset = 32776;
    for (let i = 0; i < nMat; i++) {
      const kind = matDataView.getUint8(offset);
      const texArray = matDataView.getUint8(offset + 1);
      const texLayer = matDataView.getUint16(offset + 2, true);
      const flags = matDataView.getUint32(offset + 8, true);
      offset += 12;

      const idx = i * 4;
      matTableArray[idx] = kind;
      matTableArray[idx + 1] = texArray;
      matTableArray[idx + 2] = texLayer;
      matTableArray[idx + 3] = flags & 0xFFFF;
    }

    this.matTableTex = createTexture2D(
      gl,
      256,
      256,
      gl.RGBA16UI,
      gl.RGBA_INTEGER,
      gl.UNSIGNED_SHORT,
      matTableArray
    );

    // 4. Fetch land64.bin & land128.bin (Enhanced textures are filtered smoothly, classic ones stay pixel-exact)
    const smoothLand = this.manifest.source === 'enhanced';
    if (this.manifest.landLayers['64'] > 0) {
      const land64Res = await fetch('/out/shared/land64.bin');
      const land64Buf = await land64Res.arrayBuffer();
      this.land64Tex = createTexture2DArray(
        gl,
        64,
        64,
        this.manifest.landLayers['64'],
        gl.RGB5_A1,
        gl.RGBA,
        gl.UNSIGNED_SHORT_5_5_5_1,
        new Uint16Array(land64Buf),
        true,
        smoothLand
      );
    }

    if (this.manifest.landLayers['128'] > 0) {
      const land128Res = await fetch('/out/shared/land128.bin');
      const land128Buf = await land128Res.arrayBuffer();
      this.land128Tex = createTexture2DArray(
        gl,
        128,
        128,
        this.manifest.landLayers['128'],
        gl.RGB5_A1,
        gl.RGBA,
        gl.UNSIGNED_SHORT_5_5_5_1,
        new Uint16Array(land128Buf),
        true,
        smoothLand
      );
    }

    // 5. Fetch sprites metadata (sprites.bin)
    const sprRes = await fetch('/out/shared/sprites.bin');
    const sprBuf = await sprRes.arrayBuffer();
    const sprView = new DataView(sprBuf);
    const sprCount = sprView.getUint32(4, true);

    // RGBA16UI texture: 2 texels per sprite (4096 width, height = ceil(count*2 / 4096))
    const totalTexels = sprCount * 2;
    const metaTexH = Math.ceil(totalTexels / 4096);
    const metaArray = new Uint16Array(4096 * metaTexH * 4);

    let sprOff = 8;
    for (let i = 0; i < sprCount; i++) {
      const ax = sprView.getUint16(sprOff, true);
      const ay = sprView.getUint16(sprOff + 2, true);
      const w = sprView.getUint16(sprOff + 4, true);
      const h = sprView.getUint16(sprOff + 6, true);
      const ox = sprView.getInt16(sprOff + 8, true);
      const oy = sprView.getInt16(sprOff + 10, true);
      const page = sprView.getUint8(sprOff + 12);
      const tdHeight = sprView.getUint8(sprOff + 13);
      sprOff += 16;

      // Texel 0: (ax, ay, w, h)
      const t0 = (i * 2) * 4;
      metaArray[t0] = ax;
      metaArray[t0 + 1] = ay;
      metaArray[t0 + 2] = w;
      metaArray[t0 + 3] = h;

      // Texel 1: (ox as u16, oy as u16, page | (tdHeight << 8), 0)
      const t1 = (i * 2 + 1) * 4;
      metaArray[t1] = ox & 0xFFFF;
      metaArray[t1 + 1] = oy & 0xFFFF;
      metaArray[t1 + 2] = page | (tdHeight << 8);
      metaArray[t1 + 3] = 0;
    }

    this.spriteMetaTex = createTexture2D(
      gl,
      4096,
      metaTexH,
      gl.RGBA16UI,
      gl.RGBA_INTEGER,
      gl.UNSIGNED_SHORT,
      metaArray
    );

    // 6. Fetch Atlas pages
    for (let p = 0; p < this.manifest.atlasPages; p++) {
      const pageRes = await fetch(`/out/shared/sprites_${p}.bin`);
      const pageBuf = await pageRes.arrayBuffer();
      const pageTex = createTexture2D(
        gl,
        4096,
        4096,
        gl.RGB5_A1,
        gl.RGBA,
        gl.UNSIGNED_SHORT_5_5_5_1,
        new Uint16Array(pageBuf)
      );
      this.atlasPages.push(pageTex);
    }
  }

  public getLoadedChunk(cx: number, cy: number): LoadedChunk | undefined {
    const key = `${cx}_${cy}`;
    const chunk = this.cache.get(key);
    if (chunk) {
      chunk.lastUsed = performance.now();
    }
    return chunk;
  }

  public requestChunk(cx: number, cy: number, mapId: number = 4) {
    if (cx < 0 || cy < 0 || cx >= this.manifest.chunksX || cy >= this.manifest.chunksY) {
      return;
    }

    const key = `${cx}_${cy}`;
    if (this.cache.has(key) || this.pendingFetches.has(key)) {
      return;
    }

    this.pendingFetches.add(key);
    this.loadChunk(cx, cy, mapId).then((chunk) => {
      this.pendingFetches.delete(key);
      if (chunk) {
        this.cache.set(key, chunk);
        this.pruneCache();
      }
    }).catch(() => {
      this.pendingFetches.delete(key);
    });
  }

  private async loadChunk(cx: number, cy: number, mapId: number): Promise<LoadedChunk | null> {
    const gl = this.gl;

    try {
      // Fetch terrain and statics in parallel
      const [trnRes, staRes] = await Promise.all([
        fetch(`/out/map${mapId}/terrain/${cx}_${cy}.bin`),
        fetch(`/out/map${mapId}/statics/${cx}_${cy}.bin`)
      ]);

      if (!trnRes.ok) return null;

      const trnBuf = await trnRes.arrayBuffer();
      const trnView = new DataView(trnBuf);

      // TRN1 Header: u32 magic, u16 cx, cy, i8 zMin, zMax, u16 flags, u32 reserved (16 bytes)
      const zMin = trnView.getInt8(8);
      const zMax = trnView.getInt8(9);
      const flags = trnView.getUint16(10, true);

      const hasWater = (flags & 1) !== 0;
      const allFlat = (flags & 2) !== 0;
      const hasVoid = (flags & 4) !== 0;

      // 64x64 material R16UI (offset 16, 8192 bytes)
      const matData = new Uint16Array(trnBuf, 16, 4096);
      const matTex = createTexture2D(gl, 64, 64, gl.R16UI, gl.RED_INTEGER, gl.UNSIGNED_SHORT, matData);

      // Height texture R8I
      let heightTex: WebGLTexture;
      let curOff = 16 + 8192;
      if (allFlat) {
        const flatHeight = new Int8Array(65 * 65).fill(zMin);
        heightTex = createTexture2D(gl, 65, 65, gl.R8I, gl.RED_INTEGER, gl.BYTE, flatHeight);
        curOff += 4;
      } else {
        const heightData = new Int8Array(trnBuf, curOff, 65 * 65);
        heightTex = createTexture2D(gl, 65, 65, gl.R8I, gl.RED_INTEGER, gl.BYTE, heightData);
        curOff += 65 * 65 + 3;
      }

      const terrainGPU: TerrainChunkGPU = {
        cx,
        cy,
        zMin,
        zMax,
        flags,
        hasWater,
        allFlat,
        hasVoid,
        matTex,
        heightTex
      };

      // Statics GPU parsing
      let staticsGPU: StaticsChunkGPU | undefined;
      if (staRes.ok) {
        const staBuf = await staRes.arrayBuffer();
        const staView = new DataView(staBuf);

        // Header: u32 'STA1', u16 cx, cy, u32 count, nOpaque, nTransl, nAnim, nLight, reserved (24 bytes)
        const count = staView.getUint32(8, true);
        const nOpaque = staView.getUint32(12, true);
        const nTransl = staView.getUint32(16, true);

        if (count > 0) {
          const wordsA = new Uint32Array(staBuf, 24, count);
          const wordsB = new Uint32Array(staBuf, 24 + count * 4, count);

          const bufferA = gl.createBuffer()!;
          gl.bindBuffer(gl.ARRAY_BUFFER, bufferA);
          gl.bufferData(gl.ARRAY_BUFFER, wordsA, gl.STATIC_DRAW);

          const bufferB = gl.createBuffer()!;
          gl.bindBuffer(gl.ARRAY_BUFFER, bufferB);
          gl.bufferData(gl.ARRAY_BUFFER, wordsB, gl.STATIC_DRAW);

          // VAO for opaque
          const vaoOpaque = gl.createVertexArray()!;
          gl.bindVertexArray(vaoOpaque);

          gl.bindBuffer(gl.ARRAY_BUFFER, bufferA);
          gl.enableVertexAttribArray(0);
          gl.vertexAttribIPointer(0, 1, gl.UNSIGNED_INT, 4, 0);
          gl.vertexAttribDivisor(0, 1);

          gl.bindBuffer(gl.ARRAY_BUFFER, bufferB);
          gl.enableVertexAttribArray(1);
          gl.vertexAttribIPointer(1, 1, gl.UNSIGNED_INT, 4, 0);
          gl.vertexAttribDivisor(1, 1);

          // VAO for translucent
          const vaoTransl = gl.createVertexArray()!;
          gl.bindVertexArray(vaoTransl);

          gl.bindBuffer(gl.ARRAY_BUFFER, bufferA);
          gl.enableVertexAttribArray(0);
          gl.vertexAttribIPointer(0, 1, gl.UNSIGNED_INT, 4, nOpaque * 4);
          gl.vertexAttribDivisor(0, 1);

          gl.bindBuffer(gl.ARRAY_BUFFER, bufferB);
          gl.enableVertexAttribArray(1);
          gl.vertexAttribIPointer(1, 1, gl.UNSIGNED_INT, 4, nOpaque * 4);
          gl.vertexAttribDivisor(1, 1);

          gl.bindVertexArray(null);

          staticsGPU = {
            cx,
            cy,
            count,
            nOpaque,
            nTransl,
            bufferA,
            bufferB,
            vaoOpaque,
            vaoTransl
          };
        }
      }

      return {
        cx,
        cy,
        terrain: terrainGPU,
        statics: staticsGPU,
        lastUsed: performance.now()
      };
    } catch (e) {
      console.error(`Error loading chunk ${cx}_${cy}:`, e);
      return null;
    }
  }

  private pruneCache() {
    if (this.cache.size <= this.maxCacheSize) return;

    // Sort by lastUsed ascending
    const entries = Array.from(this.cache.entries()).sort((a, b) => a[1].lastUsed - b[1].lastUsed);
    const toRemove = entries.slice(0, this.cache.size - this.maxCacheSize);

    const gl = this.gl;
    for (const [key, chunk] of toRemove) {
      if (chunk.terrain) {
        gl.deleteTexture(chunk.terrain.matTex);
        gl.deleteTexture(chunk.terrain.heightTex);
      }
      if (chunk.statics) {
        gl.deleteBuffer(chunk.statics.bufferA);
        gl.deleteBuffer(chunk.statics.bufferB);
        gl.deleteVertexArray(chunk.statics.vaoOpaque);
        gl.deleteVertexArray(chunk.statics.vaoTransl);
      }
      this.cache.delete(key);
    }
  }
}
