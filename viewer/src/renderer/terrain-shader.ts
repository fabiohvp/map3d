/**
 * Terrain WebGL2 shader program.
 */

export const TERRAIN_VS = `#version 300 es
precision highp float;
precision highp int;
precision highp isampler2D;
precision highp usampler2D;

// Uniforms
uniform ivec2 u_chunkCoord;     // (cx, cy)
uniform vec2 u_camTarget;       // (targetX, targetY) in tiles
uniform vec2 u_viewport;        // (width, height) in pixels
uniform float u_zoom;
uniform float u_viewBase;
uniform int u_cameraMode;       // 0 = classic isometric, 1 = 3d orbit
uniform mat4 u_matrix;          // 4x4 matrix for 3d orbit
uniform float u_zScale;
uniform float u_time;

// Textures
uniform isampler2D u_heightTex; // 65x65 R8I
uniform usampler2D u_matTex;    // 64x64 R16UI

// Structured buffer or uniform for materials:
// For simplicity and speed: material entry kind, texArray, texLayer passed via uniform array or UBO
struct MaterialInfo {
  uint kind;      // 0 texmap, 1 art, 2 water, 3 void
  uint texArray;  // 0 land64, 1 land128, 255 none
  uint texLayer;
  uint radar555;
};

// We pass materials as a sampler1D / texelFetch from a texture or uniform buffer
uniform usampler2D u_matTableTex; // 256x256 RGBA16UI: r=kind, g=texArray, b=texLayer, a=flags

// Outputs to Fragment Shader
out vec2 v_uv;
flat out uint v_kind;
flat out uint v_texArray;
flat out uint v_texLayer;
out float v_height;
out vec3 v_worldPos;
out vec2 v_chunkPos;            // position inside the chunk, in tiles (0..64)
flat out ivec2 v_tileXY;        // tile inside the chunk

// 6 vertices of quad (top, right, left, right, bottom, left)
const vec2 CORNERS[6] = vec2[6](
  vec2(0.0, 0.0),
  vec2(1.0, 0.0),
  vec2(0.0, 1.0),
  vec2(1.0, 0.0),
  vec2(1.0, 1.0),
  vec2(0.0, 1.0)
);

void main() {
  int tileIndex = gl_VertexID / 6;
  int cornerIdx = gl_VertexID % 6;
  vec2 corner = CORNERS[cornerIdx];

  int tileX = tileIndex % 64;
  int tileY = tileIndex / 64;

  int vertX = tileX + int(corner.x);
  int vertY = tileY + int(corner.y);

  // Fetch height from R8I
  float h = float(texelFetch(u_heightTex, ivec2(vertX, vertY), 0).r);
  v_height = h;

  // Fetch material index for this tile
  uint matIdx = texelFetch(u_matTex, ivec2(tileX, tileY), 0).r;
  
  // Fetch material attributes from material table texture
  uvec4 matData = texelFetch(u_matTableTex, ivec2(int(matIdx & 255u), int(matIdx >> 8)), 0);
  v_kind = matData.r;
  v_texArray = matData.g;
  v_texLayer = matData.b;

  v_uv = corner;
  v_chunkPos = vec2(float(tileX), float(tileY)) + corner;
  v_tileXY = ivec2(tileX, tileY);

  // World tile coordinates
  float worldX = float(u_chunkCoord.x * 64 + vertX);
  float worldY = float(u_chunkCoord.y * 64 + vertY);
  v_worldPos = vec3(worldX, worldY, h);

  if (u_cameraMode == 0) {
    // --- Classic Isometric Mode ---
    float camSx = (u_camTarget.x - u_camTarget.y) * 22.0;
    float camSy = (u_camTarget.x + u_camTarget.y) * 22.0;

    float sx = (worldX - worldY) * 22.0;
    float sy = (worldX + worldY) * 22.0 - h * 4.0;

    float ndcX = ((sx - camSx) * u_zoom) / (u_viewport.x * 0.5);
    float ndcY = -((sy - camSy) * u_zoom) / (u_viewport.y * 0.5);

    // Depth key: prioZ for terrain is min/corner z - 1
    float prioZ = h - 1.0;
    float tileDepthCoord = (float(u_chunkCoord.x * 64 + tileX) + float(u_chunkCoord.y * 64 + tileY));
    float key = ((tileDepthCoord - u_viewBase) * 512.0 + (prioZ + 256.0)) * 128.0;
    
    // Normalize into [-1.0, 1.0]
    float ndcZ = (key / 33554432.0) * 2.0 - 1.0;

    gl_Position = vec4(ndcX, ndcY, ndcZ, 1.0);
  } else {
    // --- 3D Orbit Mode ---
    vec4 pos3D = vec4(worldX, worldY, h * u_zScale, 1.0);
    gl_Position = u_matrix * pos3D;
  }
}
`;

export const TERRAIN_FS = `#version 300 es
precision highp float;
precision highp int;
precision highp sampler2DArray;
precision highp usampler2D;

in vec2 v_uv;
flat in uint v_kind;
flat in uint v_texArray;
flat in uint v_texLayer;
in float v_height;
in vec3 v_worldPos;
in vec2 v_chunkPos;
flat in ivec2 v_tileXY;

uniform sampler2DArray u_land64Tex;
uniform sampler2DArray u_land128Tex;
uniform highp usampler2D u_matTexF;       // 64x64 R16UI (same texture as the vertex stage)
uniform highp usampler2D u_matTableTexF;  // material table (same texture as the vertex stage)
uniform float u_time;
uniform int u_cameraMode;
uniform float u_texScale;                 // tiles covered by one repeat of a land texture
uniform float u_blend;                    // 0 = hard tile edges, >0 = smooth transitions between land materials

out vec4 fragColor;

// Samples a textured land material (kind 0/1); returns alpha 0 for water/void or missing data.
vec4 sampleLand(uint kind, uint texArray, uint texLayer, vec2 uv) {
  if (kind > 1u) return vec4(0.0);
  if (texArray == 0u) return texture(u_land64Tex, vec3(uv, float(texLayer)));
  if (texArray == 1u) return texture(u_land128Tex, vec3(uv, float(texLayer)));
  return vec4(0.0);
}

vec4 sampleNeighbour(ivec2 t, vec2 uv) {
  t = clamp(t, ivec2(0), ivec2(63));
  uint m = texelFetch(u_matTexF, t, 0).r;
  uvec4 d = texelFetch(u_matTableTexF, ivec2(int(m & 255u), int(m >> 8)), 0);
  return sampleLand(d.r, d.g, d.b, uv);
}

void main() {
  if (v_kind == 3u) {
    // Void tile: discard
    discard;
  }

  vec4 col = vec4(0.2, 0.45, 0.2, 1.0); // fallback green

  if (v_kind == 2u) {
    // Water shader
    vec2 animatedUV = v_uv + vec2(sin(u_time * 1.5 + v_worldPos.x * 0.2) * 0.05, cos(u_time * 1.2 + v_worldPos.y * 0.2) * 0.05);
    vec4 waterBase = vec4(0.12, 0.35, 0.65, 0.85);
    float wave = sin(v_worldPos.x * 0.5 + v_worldPos.y * 0.5 + u_time * 3.0) * 0.08;
    col = waterBase + vec4(wave, wave * 1.2, wave * 1.5, 0.0);
  } else {
    // Continuous world-space UVs so large (Enhanced) textures do not repeat per tile
    vec2 uv = v_worldPos.xy / u_texScale;
    col = sampleLand(v_kind, v_texArray, v_texLayer, uv);

    if (u_blend > 0.0 && col.a > 0.0) {
      // Smooth the seam to the 4 neighbouring tiles when their material differs
      vec2 f = clamp(v_chunkPos - vec2(v_tileXY), 0.0, 1.0);
      float wx1 = smoothstep(1.0 - u_blend, 1.0, f.x) * 0.5;
      float wx0 = smoothstep(u_blend, 0.0, f.x) * 0.5;
      float wy1 = smoothstep(1.0 - u_blend, 1.0, f.y) * 0.5;
      float wy0 = smoothstep(u_blend, 0.0, f.y) * 0.5;
      vec4 n;
      if (wx1 > 0.0) { n = sampleNeighbour(v_tileXY + ivec2(1, 0), uv); if (n.a > 0.0) col.rgb = mix(col.rgb, n.rgb, wx1); }
      if (wx0 > 0.0) { n = sampleNeighbour(v_tileXY + ivec2(-1, 0), uv); if (n.a > 0.0) col.rgb = mix(col.rgb, n.rgb, wx0); }
      if (wy1 > 0.0) { n = sampleNeighbour(v_tileXY + ivec2(0, 1), uv); if (n.a > 0.0) col.rgb = mix(col.rgb, n.rgb, wy1); }
      if (wy0 > 0.0) { n = sampleNeighbour(v_tileXY + ivec2(0, -1), uv); if (n.a > 0.0) col.rgb = mix(col.rgb, n.rgb, wy0); }
    }
  }

  if (col.a < 0.1) {
    discard;
  }

  // Subtle directional shade in 3D orbit mode
  if (u_cameraMode == 1) {
    vec3 dx = dFdx(v_worldPos);
    vec3 dy = dFdy(v_worldPos);
    vec3 normal = normalize(cross(dx, dy));
    vec3 lightDir = normalize(vec3(-0.5, -0.7, 1.0));
    float diff = max(0.4, dot(normal, lightDir));
    col.rgb *= diff;
  }

  fragColor = col;
}
`;
