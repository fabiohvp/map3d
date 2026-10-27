/**
 * WebGL2 utility functions for shader compilation, buffer and texture management.
 */

export function createShader(gl: WebGL2RenderingContext, type: number, source: string): WebGLShader {
  const shader = gl.createShader(type);
  if (!shader) throw new Error('Failed to create shader');
  gl.shaderSource(shader, source.trim());
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const info = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error(`Shader compilation error:\n${info}\nSource:\n${source}`);
  }
  return shader;
}

export function createProgram(gl: WebGL2RenderingContext, vsSource: string, fsSource: string): WebGLProgram {
  const vs = createShader(gl, gl.VERTEX_SHADER, vsSource);
  const fs = createShader(gl, gl.FRAGMENT_SHADER, fsSource);
  const program = gl.createProgram();
  if (!program) throw new Error('Failed to create program');
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    const info = gl.getProgramInfoLog(program);
    gl.deleteProgram(program);
    throw new Error(`Program link error:\n${info}`);
  }
  return program;
}

export function createTexture2D(
  gl: WebGL2RenderingContext,
  width: number,
  height: number,
  internalFormat: number,
  format: number,
  type: number,
  data: ArrayBufferView | null,
  minFilter: number = gl.NEAREST,
  magFilter: number = gl.NEAREST
): WebGLTexture {
  const tex = gl.createTexture();
  if (!tex) throw new Error('Failed to create texture');
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, minFilter);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, magFilter);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texImage2D(gl.TEXTURE_2D, 0, internalFormat, width, height, 0, format, type, data);
  gl.bindTexture(gl.TEXTURE_2D, null);
  return tex;
}

export function createTexture2DArray(
  gl: WebGL2RenderingContext,
  width: number,
  height: number,
  depth: number,
  internalFormat: number,
  format: number,
  type: number,
  data: ArrayBufferView | null,
  generateMipmaps: boolean = false,
  smooth: boolean = false
): WebGLTexture {
  const tex = gl.createTexture();
  if (!tex) throw new Error('Failed to create 2D array texture');
  gl.bindTexture(gl.TEXTURE_2D_ARRAY, tex);
  gl.texParameteri(gl.TEXTURE_2D_ARRAY, gl.TEXTURE_WRAP_S, gl.REPEAT);
  gl.texParameteri(gl.TEXTURE_2D_ARRAY, gl.TEXTURE_WRAP_T, gl.REPEAT);
  const minFilter = smooth
    ? (generateMipmaps ? gl.LINEAR_MIPMAP_LINEAR : gl.LINEAR)
    : (generateMipmaps ? gl.NEAREST_MIPMAP_LINEAR : gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D_ARRAY, gl.TEXTURE_MIN_FILTER, minFilter);
  gl.texParameteri(gl.TEXTURE_2D_ARRAY, gl.TEXTURE_MAG_FILTER, smooth ? gl.LINEAR : gl.NEAREST);

  gl.texImage3D(gl.TEXTURE_2D_ARRAY, 0, internalFormat, width, height, depth, 0, format, type, data);
  if (generateMipmaps && depth > 0) {
    gl.generateMipmap(gl.TEXTURE_2D_ARRAY);
  }
  gl.bindTexture(gl.TEXTURE_2D_ARRAY, null);
  return tex;
}
