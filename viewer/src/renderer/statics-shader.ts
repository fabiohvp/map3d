/**
 * Statics WebGL2 instanced shader program.
 */

export const STATICS_VS = `#version 300 es
precision highp float;
precision highp int;
precision highp usampler2D;

// Instanced attributes
layout(location = 0) in uint a_wordA; // bits 0-5 x, 6-11 y, 12-19 z+128, 20-31 flags
layout(location = 1) in uint a_wordB; // bits 0-15 spriteIndex, 16-31 hue

// Uniforms
uniform ivec2 u_chunkCoord;     // (cx, cy)
uniform vec2 u_camTarget;       // (targetX, targetY)
uniform vec2 u_viewport;        // (width, height)
uniform float u_zoom;
uniform float u_viewBase;
uniform int u_cameraMode;       // 0 = classic, 1 = 3d orbit
uniform mat4 u_matrix;
uniform float u_zScale;
uniform float u_roofCutZ;
uniform float u_yaw;

// Sprite metadata texture: 2 texels per sprite (RGBA16UI)
// Texel 0: (ax, ay, w, h)
// Texel 1: (ox, oy, page, tdHeight)
uniform usampler2D u_spriteMetaTex;

// Outputs to Fragment
out vec2 v_uv;
flat out uint v_page;
flat out uint v_hue;
flat out uint v_flags;
out float v_alpha;

// Quad corners for TRIANGLE_STRIP
const vec2 QUAD[4] = vec2[4](
  vec2(0.0, 0.0), // top-left
  vec2(1.0, 0.0), // top-right
  vec2(0.0, 1.0), // bottom-left
  vec2(1.0, 1.0)  // bottom-right
);

void main() {
  vec2 q = QUAD[gl_VertexID];

  // Unpack Word A
  float localX = float(a_wordA & 0x3Fu);
  float localY = float((a_wordA >> 6) & 0x3Fu);
  float rawZ = float((a_wordA >> 12) & 0xFFu) - 128.0;
  uint flags = (a_wordA >> 20) & 0xFFFu;

  // Unpack Word B
  uint spriteIndex = a_wordB & 0xFFFFu;
  uint hue = (a_wordB >> 16) & 0xFFFFu;

  v_hue = hue;
  v_flags = flags;
  v_alpha = 1.0;

  // Fetch sprite metadata (2 texels per sprite)
  int metaX0 = int((spriteIndex * 2u) % 4096u);
  int metaY0 = int((spriteIndex * 2u) / 4096u);
  int metaX1 = int((spriteIndex * 2u + 1u) % 4096u);
  int metaY1 = int((spriteIndex * 2u + 1u) / 4096u);

  uvec4 m0 = texelFetch(u_spriteMetaTex, ivec2(metaX0, metaY0), 0);
  uvec4 m1 = texelFetch(u_spriteMetaTex, ivec2(metaX1, metaY1), 0);

  float ax = float(m0.r);
  float ay = float(m0.g);
  float w  = float(m0.b);
  float h  = float(m0.a);

  // ox, oy are signed 16-bit
  int rawOx = int(m1.r);
  if (rawOx > 32767) rawOx -= 65536;
  int rawOy = int(m1.g);
  if (rawOy > 32767) rawOy -= 65536;
  float ox = float(rawOx);
  float oy = float(rawOy);

  v_page = m1.b & 0xFFu;
  float tdHeight = float((m1.b >> 8) & 0xFFu);

  // UV coordinates in 4096 atlas
  v_uv = (vec2(ax, ay) + q * vec2(w, h)) / 4096.0;

  // World coordinates
  float worldX = float(u_chunkCoord.x * 64) + localX;
  float worldY = float(u_chunkCoord.y * 64) + localY;

  bool isBg = (flags & 1u) != 0u;
  bool isRoof = (flags & (1u << 3)) != 0u;

  // Roof cutoff
  if (isRoof && rawZ > u_roofCutZ) {
    v_alpha = 0.0;
  }

  if (u_cameraMode == 0) {
    // --- Classic Isometric Mode ---
    float camSx = (u_camTarget.x - u_camTarget.y) * 22.0;
    float camSy = (u_camTarget.x + u_camTarget.y) * 22.0;

    // Anchor is base-center of tile: (worldX, worldY)
    float anchorSx = (worldX - worldY) * 22.0 + 22.0;
    float anchorSy = (worldX + worldY) * 22.0 + 44.0 - rawZ * 4.0;

    float drawX = anchorSx + ox + w * q.x;
    float drawY = anchorSy + oy + h * q.y;

    float ndcX = ((drawX - camSx) * u_zoom) / (u_viewport.x * 0.5);
    float ndcY = -((drawY - camSy) * u_zoom) / (u_viewport.y * 0.5);

    // Depth key
    float prioZ = rawZ - (isBg ? 1.0 : 0.0) + (tdHeight > 0.0 ? 1.0 : 0.0);
    float tie = float(gl_InstanceID & 127);
    float key = ((worldX + worldY - u_viewBase) * 512.0 + (prioZ + 256.0)) * 128.0 + tie;

    float ndcZ = (key / 33554432.0) * 2.0 - 1.0;

    gl_Position = vec4(ndcX, ndcY, ndcZ, 1.0);
  } else {
    // --- 3D Orbit Mode (Cylindrical Billboard facing yaw) ---
    float cosY = cos(u_yaw);
    float sinY = sin(u_yaw);
    vec3 right = vec3(-sinY, cosY, 0.0);
    vec3 up = vec3(0.0, 0.0, 1.0);

    float bbW = (w / 44.0) * 1.5;
    float bbH = (h / 44.0) * (44.0 * u_zScale / 4.0) * 1.5;

    vec3 basePos = vec3(worldX + 0.5, worldY + 0.5, rawZ * u_zScale);
    vec3 vertexPos = basePos + right * (q.x - 0.5) * bbW + up * (1.0 - q.y) * bbH;

    gl_Position = u_matrix * vec4(vertexPos, 1.0);
  }
}
`;

export const STATICS_FS = `#version 300 es
precision highp float;
precision highp int;
precision highp usampler2D;

in vec2 v_uv;
flat in uint v_page;
flat in uint v_hue;
flat in uint v_flags;
in float v_alpha;

uniform sampler2D u_atlasPages[4]; // Support up to 4 atlas pages
uniform sampler2D u_huesTex;       // 32x3000 RGB5_A1 LUT

out vec4 fragColor;

void main() {
  if (v_alpha <= 0.0) {
    discard;
  }

  // Sample page
  vec4 col = vec4(0.0);
  if (v_page == 0u) {
    col = texture(u_atlasPages[0], v_uv);
  } else if (v_page == 1u) {
    col = texture(u_atlasPages[1], v_uv);
  } else if (v_page == 2u) {
    col = texture(u_atlasPages[2], v_uv);
  } else {
    col = texture(u_atlasPages[3], v_uv);
  }

  // Alpha test
  if (col.a < 0.5) {
    discard;
  }

  // Hue replacement
  if (v_hue > 0u) {
    int red5 = int(round(col.r * 31.0));
    int hueIdx = int(v_hue - 1u);
    vec4 hueCol = texelFetch(u_huesTex, ivec2(red5, hueIdx), 0);

    bool isPartial = (v_flags & (1u << 7)) != 0u;
    if (isPartial) {
      // Apply only if r == g == b (greyscale)
      if (abs(col.r - col.g) < 0.05 && abs(col.g - col.b) < 0.05) {
        col.rgb = hueCol.rgb;
      }
    } else {
      col.rgb = hueCol.rgb;
    }
  }

  // Translucent flag
  bool isTransl = (v_flags & (1u << 5)) != 0u;
  if (isTransl) {
    col.a = 0.65;
  }

  fragColor = col;
}
`;
