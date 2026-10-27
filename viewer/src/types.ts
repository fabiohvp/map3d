export interface Manifest {
  map: number;
  source?: 'enhanced' | 'classic';
  width: number;
  height: number;
  chunk: number;
  chunksX: number;
  chunksY: number;
  zScale: number;
  chunks: string;
  chunkMeta: string;
  atlasPages: number;
  sprites: number;
  landLayers: {
    '64': number;
    '128': number;
  };
}

export interface MaterialEntry {
  kind: number;      // 0 texmap, 1 art, 2 water, 3 void
  texArray: number;  // 0 land64, 1 land128, 255 none
  texLayer: number;
  artLayer: number;
  radar555: number;
  flags: number;
}

export interface TerrainChunkGPU {
  cx: number;
  cy: number;
  zMin: number;
  zMax: number;
  flags: number;
  hasWater: boolean;
  allFlat: boolean;
  hasVoid: boolean;
  matTex: WebGLTexture;
  heightTex: WebGLTexture;
  waterZTex?: WebGLTexture;
  waterKindTex?: WebGLTexture;
}

export interface StaticsChunkGPU {
  cx: number;
  cy: number;
  count: number;
  nOpaque: number;
  nTransl: number;
  bufferA: WebGLBuffer;
  bufferB: WebGLBuffer;
  vaoOpaque: WebGLVertexArrayObject;
  vaoTransl: WebGLVertexArrayObject;
}

export interface LoadedChunk {
  cx: number;
  cy: number;
  terrain?: TerrainChunkGPU;
  statics?: StaticsChunkGPU;
  lastUsed: number;
}
