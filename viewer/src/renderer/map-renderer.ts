/**
 * WebGL2 Main Scene Renderer.
 */
import { Camera } from '../camera/camera';
import { ChunkLoader } from '../loader/chunk-loader';
import { createProgram } from '../webgl/gl-utils';
import { TERRAIN_VS, TERRAIN_FS } from './terrain-shader';
import { STATICS_VS, STATICS_FS } from './statics-shader';

export class MapRenderer {
  private gl: WebGL2RenderingContext;
  private loader: ChunkLoader;

  private terrainProgram: WebGLProgram;
  private staticsProgram: WebGLProgram;

  // Options
  public renderTerrain = true;
  public renderStatics = true;
  public roofCutZ = 127.0;

  constructor(gl: WebGL2RenderingContext, loader: ChunkLoader) {
    this.gl = gl;
    this.loader = loader;

    this.terrainProgram = createProgram(gl, TERRAIN_VS, TERRAIN_FS);
    this.staticsProgram = createProgram(gl, STATICS_VS, STATICS_FS);
  }

  public render(camera: Camera, time: number) {
    const gl = this.gl;
    const loader = this.loader;
    if (!loader.manifest) return;

    // Viewport
    gl.viewport(0, 0, camera.viewportWidth, camera.viewportHeight);
    gl.clearColor(0.06, 0.08, 0.07, 1.0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

    gl.enable(gl.DEPTH_TEST);
    gl.depthFunc(gl.LEQUAL);

    // Visible chunk range
    const centerChunkX = Math.floor(camera.targetX / 64);
    const centerChunkY = Math.floor(camera.targetY / 64);
    const radius = Math.ceil(camera.viewportWidth / (64 * 22 * camera.zoom)) + 2;

    const minCx = Math.max(0, centerChunkX - radius);
    const maxCx = Math.min(loader.manifest.chunksX - 1, centerChunkX + radius);
    const minCy = Math.max(0, centerChunkY - radius);
    const maxCy = Math.min(loader.manifest.chunksY - 1, centerChunkY + radius);

    // Request visible chunks
    const visibleChunks = [];
    for (let cy = minCy; cy <= maxCy; cy++) {
      for (let cx = minCx; cx <= maxCx; cx++) {
        loader.requestChunk(cx, cy, loader.manifest.map);
        const chunk = loader.getLoadedChunk(cx, cy);
        if (chunk) {
          visibleChunks.push(chunk);
        }
      }
    }

    const isOrbit = camera.mode === 'orbit';
    const matrix3D = isOrbit ? camera.get3DMatrix() : new Float32Array(16);
    const viewBase = camera.getViewBase();

    // -------------------------------------------------------------
    // PASS 1: TERRAIN
    // -------------------------------------------------------------
    if (this.renderTerrain && visibleChunks.length > 0) {
      gl.useProgram(this.terrainProgram);

      // Global uniforms
      gl.uniform2f(gl.getUniformLocation(this.terrainProgram, 'u_camTarget'), camera.targetX, camera.targetY);
      gl.uniform2f(gl.getUniformLocation(this.terrainProgram, 'u_viewport'), camera.viewportWidth, camera.viewportHeight);
      gl.uniform1f(gl.getUniformLocation(this.terrainProgram, 'u_zoom'), camera.zoom);
      gl.uniform1f(gl.getUniformLocation(this.terrainProgram, 'u_viewBase'), viewBase);
      gl.uniform1i(gl.getUniformLocation(this.terrainProgram, 'u_cameraMode'), isOrbit ? 1 : 0);
      gl.uniformMatrix4fv(gl.getUniformLocation(this.terrainProgram, 'u_matrix'), false, matrix3D);
      gl.uniform1f(gl.getUniformLocation(this.terrainProgram, 'u_zScale'), camera.zScale);
      gl.uniform1f(gl.getUniformLocation(this.terrainProgram, 'u_time'), time);

      // Shared textures
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D_ARRAY, loader.land64Tex);
      gl.uniform1i(gl.getUniformLocation(this.terrainProgram, 'u_land64Tex'), 0);

      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D_ARRAY, loader.land128Tex);
      gl.uniform1i(gl.getUniformLocation(this.terrainProgram, 'u_land128Tex'), 1);

      gl.activeTexture(gl.TEXTURE2);
      gl.bindTexture(gl.TEXTURE_2D, loader.matTableTex);
      gl.uniform1i(gl.getUniformLocation(this.terrainProgram, 'u_matTableTex'), 2);

      const enhancedSource = loader.manifest.source === 'enhanced';
      gl.uniform1f(gl.getUniformLocation(this.terrainProgram, 'u_texScale'), enhancedSource ? 4.0 : 1.0);
      gl.uniform1f(gl.getUniformLocation(this.terrainProgram, 'u_blend'), enhancedSource ? 0.35 : 0.0);
      gl.uniform1i(gl.getUniformLocation(this.terrainProgram, 'u_matTableTexF'), 2);
      gl.uniform1i(gl.getUniformLocation(this.terrainProgram, 'u_matTexF'), 4);

      const uChunkCoord = gl.getUniformLocation(this.terrainProgram, 'u_chunkCoord');
      const uHeightTex = gl.getUniformLocation(this.terrainProgram, 'u_heightTex');
      const uMatTex = gl.getUniformLocation(this.terrainProgram, 'u_matTex');

      gl.uniform1i(uHeightTex, 3);
      gl.uniform1i(uMatTex, 4);

      // Render each terrain chunk (no vertex buffer!)
      for (const chunk of visibleChunks) {
        if (!chunk.terrain) continue;

        gl.uniform2i(uChunkCoord, chunk.cx, chunk.cy);

        gl.activeTexture(gl.TEXTURE3);
        gl.bindTexture(gl.TEXTURE_2D, chunk.terrain.heightTex);

        gl.activeTexture(gl.TEXTURE4);
        gl.bindTexture(gl.TEXTURE_2D, chunk.terrain.matTex);

        gl.drawArrays(gl.TRIANGLES, 0, 4096 * 6);
      }
    }

    // -------------------------------------------------------------
    // PASS 2 & 3: STATICS (OPAQUE & TRANSLUCENT)
    // -------------------------------------------------------------
    if (this.renderStatics && visibleChunks.length > 0) {
      gl.useProgram(this.staticsProgram);

      gl.uniform2f(gl.getUniformLocation(this.staticsProgram, 'u_camTarget'), camera.targetX, camera.targetY);
      gl.uniform2f(gl.getUniformLocation(this.staticsProgram, 'u_viewport'), camera.viewportWidth, camera.viewportHeight);
      gl.uniform1f(gl.getUniformLocation(this.staticsProgram, 'u_zoom'), camera.zoom);
      gl.uniform1f(gl.getUniformLocation(this.staticsProgram, 'u_viewBase'), viewBase);
      gl.uniform1i(gl.getUniformLocation(this.staticsProgram, 'u_cameraMode'), isOrbit ? 1 : 0);
      gl.uniformMatrix4fv(gl.getUniformLocation(this.staticsProgram, 'u_matrix'), false, matrix3D);
      gl.uniform1f(gl.getUniformLocation(this.staticsProgram, 'u_zScale'), camera.zScale);
      gl.uniform1f(gl.getUniformLocation(this.staticsProgram, 'u_roofCutZ'), this.roofCutZ);
      gl.uniform1f(gl.getUniformLocation(this.staticsProgram, 'u_yaw'), camera.yaw);

      // Bind Atlas Pages
      for (let p = 0; p < loader.atlasPages.length; p++) {
        gl.activeTexture(gl.TEXTURE0 + p);
        gl.bindTexture(gl.TEXTURE_2D, loader.atlasPages[p]);
      }
      const atlasLocs = [
        gl.getUniformLocation(this.staticsProgram, 'u_atlasPages[0]'),
        gl.getUniformLocation(this.staticsProgram, 'u_atlasPages[1]'),
        gl.getUniformLocation(this.staticsProgram, 'u_atlasPages[2]'),
        gl.getUniformLocation(this.staticsProgram, 'u_atlasPages[3]'),
      ];
      for (let p = 0; p < 4; p++) {
        if (atlasLocs[p]) gl.uniform1i(atlasLocs[p], p);
      }

      // Hues texture
      gl.activeTexture(gl.TEXTURE4);
      gl.bindTexture(gl.TEXTURE_2D, loader.huesTex);
      gl.uniform1i(gl.getUniformLocation(this.staticsProgram, 'u_huesTex'), 4);

      // Sprite Metadata texture
      gl.activeTexture(gl.TEXTURE5);
      gl.bindTexture(gl.TEXTURE_2D, loader.spriteMetaTex);
      gl.uniform1i(gl.getUniformLocation(this.staticsProgram, 'u_spriteMetaTex'), 5);

      const uStaticsChunkCoord = gl.getUniformLocation(this.staticsProgram, 'u_chunkCoord');

      // --- Pass 2: Opaque Statics (Depth Write ON) ---
      gl.depthMask(true);
      gl.disable(gl.BLEND);

      for (const chunk of visibleChunks) {
        if (!chunk.statics || chunk.statics.nOpaque === 0) continue;

        gl.uniform2i(uStaticsChunkCoord, chunk.cx, chunk.cy);
        gl.bindVertexArray(chunk.statics.vaoOpaque);
        gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, chunk.statics.nOpaque);
      }

      // --- Pass 3: Translucent Statics (Depth Write OFF, Blend ON) ---
      gl.depthMask(false);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

      // Render translucent in back-to-front order (chunk x+y ascending)
      const sortedTranslucent = [...visibleChunks].sort((a, b) => (a.cx + a.cy) - (b.cx + b.cy));
      for (const chunk of sortedTranslucent) {
        if (!chunk.statics || chunk.statics.nTransl === 0) continue;

        gl.uniform2i(uStaticsChunkCoord, chunk.cx, chunk.cy);
        gl.bindVertexArray(chunk.statics.vaoTransl);
        gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, chunk.statics.nTransl);
      }

      gl.depthMask(true);
      gl.disable(gl.BLEND);
      gl.bindVertexArray(null);
    }
  }
}
