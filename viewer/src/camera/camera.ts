/**
 * Camera system supporting both Classic Ultima Online Isometric view and Free 3D Orbit view.
 */

export type CameraMode = 'classic' | 'orbit';

export class Camera {
  public mode: CameraMode = 'classic';

  // Target in world tile coordinates
  public targetX: number = 724; // Default center of Map 4 (1448 / 2)
  public targetY: number = 724;
  public targetZ: number = 0;

  // Zoom factor
  public zoom: number = 1.0;

  // 3D Orbit parameters
  public yaw: number = -Math.PI / 4; // -45 deg default isometric angle
  public pitch: number = 0.6;        // ~35 degrees
  public distance: number = 80;

  // Viewport dimensions
  public viewportWidth: number = window.innerWidth;
  public viewportHeight: number = window.innerHeight;

  public zScale: number = 0.12856;

  constructor(targetX = 724, targetY = 724) {
    this.targetX = targetX;
    this.targetY = targetY;
  }

  public setViewport(w: number, h: number) {
    this.viewportWidth = w;
    this.viewportHeight = h;
  }

  public pan(dxPixels: number, dyPixels: number) {
    if (this.mode === 'classic') {
      // In isometric:
      // sx = (x - y) * 22 * zoom
      // sy = (x + y) * 22 * zoom
      // Inverting:
      // dx_tile = (dx / 22 + dy / 22) / (2 * zoom)
      // dy_tile = (dy / 22 - dx / 22) / (2 * zoom)
      const scale = 22.0 * this.zoom;
      const dTileX = (dxPixels + dyPixels) / (2.0 * scale);
      const dTileY = (dyPixels - dxPixels) / (2.0 * scale);
      this.targetX -= dTileX;
      this.targetY -= dTileY;
    } else {
      // Orbit pan along camera right/up vectors
      const cosY = Math.cos(this.yaw);
      const sinY = Math.sin(this.yaw);
      const panSpeed = (this.distance / this.viewportHeight) * 1.5;
      this.targetX += (-sinY * dxPixels - cosY * dyPixels) * panSpeed;
      this.targetY += (cosY * dxPixels - sinY * dyPixels) * panSpeed;
    }
  }

  public rotateOrbit(deltaYaw: number, deltaPitch: number) {
    this.yaw += deltaYaw;
    this.pitch = Math.max(0.1, Math.min(Math.PI / 2 - 0.05, this.pitch + deltaPitch));
  }

  public adjustZoom(factor: number) {
    if (this.mode === 'classic') {
      this.zoom = Math.max(0.25, Math.min(4.0, this.zoom * factor));
    } else {
      this.distance = Math.max(10, Math.min(400, this.distance / factor));
    }
  }

  public getViewBase(): number {
    return Math.floor(this.targetX + this.targetY - 128);
  }

  /**
   * Computes 4x4 View-Projection matrix for 3D Orbit mode.
   */
  public get3DMatrix(): Float32Array {
    const eyeX = this.targetX + this.distance * Math.cos(this.pitch) * Math.sin(this.yaw);
    const eyeY = this.targetY + this.distance * Math.cos(this.pitch) * Math.cos(this.yaw);
    const eyeZ = (this.targetZ * this.zScale) + this.distance * Math.sin(this.pitch);

    const targetZScaled = this.targetZ * this.zScale;

    // View matrix (LookAt)
    const forward = normalize([this.targetX - eyeX, this.targetY - eyeY, targetZScaled - eyeZ]);
    const upRef = [0, 0, 1];
    const right = normalize(cross(forward, upRef));
    const up = cross(right, forward);

    const view = new Float32Array([
      right[0], up[0], -forward[0], 0,
      right[1], up[1], -forward[1], 0,
      right[2], up[2], -forward[2], 0,
      -dot(right, [eyeX, eyeY, eyeZ]),
      -dot(up, [eyeX, eyeY, eyeZ]),
      dot(forward, [eyeX, eyeY, eyeZ]),
      1
    ]);

    // Perspective projection matrix
    const aspect = this.viewportWidth / this.viewportHeight;
    const fov = (45 * Math.PI) / 180;
    const near = 0.5;
    const far = 2000.0;
    const f = 1.0 / Math.tan(fov / 2);

    const proj = new Float32Array([
      f / aspect, 0, 0, 0,
      0, f, 0, 0,
      0, 0, (far + near) / (near - far), -1,
      0, 0, (2 * far * near) / (near - far), 0
    ]);

    return multiplyMatrices(proj, view);
  }
}

// Vector math helpers
function normalize(v: number[]): number[] {
  const len = Math.hypot(v[0], v[1], v[2]);
  return len > 0 ? [v[0] / len, v[1] / len, v[2] / len] : [0, 0, 0];
}

function cross(a: number[], b: number[]): number[] {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0]
  ];
}

function dot(a: number[], b: number[]): number {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

function multiplyMatrices(a: Float32Array, b: Float32Array): Float32Array {
  const out = new Float32Array(16);
  for (let i = 0; i < 4; ++i) {
    for (let j = 0; j < 4; ++j) {
      let sum = 0;
      for (let k = 0; k < 4; ++k) {
        sum += a[k * 4 + i] * b[j * 4 + k];
      }
      out[j * 4 + i] = sum;
    }
  }
  return out;
}
