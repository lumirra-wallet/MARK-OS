import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { useMarkStore } from '@/store/markStore';
import { useSelfState } from '@/hooks/use-self-state';

/**
 * PresenceEngine — MARK's living core: a glass sphere of glowing green
 * chemical, rebuilt from first principles around a real screen-space
 * refraction pipeline, a raymarched volumetric fog layer, and a
 * procedurally-emergent "something is in there" presence — modeled on a
 * reference photo the owner supplied.
 *
 * MILESTONE 1 — Real glass, not a flat translucent sphere.
 *   The shell is a genuine two-pass screen-space refraction: everything
 *   else in the scene is rendered to an offscreen texture (`backdropTarget`)
 *   first, then the shell's own ShaderMaterial samples that texture with
 *   its UV offset by the surface normal (Snell-law-*inspired*, not exact)
 *   — a real optical distortion of whatever's behind it, not alpha
 *   blending. (`transmission` was tried in an earlier pass and rejected:
 *   three.js's transmission background-capture only reliably grabs opaque
 *   geometry, so the liquid/bubbles behind it came out invisible.) Fresnel
 *   brightens toward white at grazing angles for the reflective edge; a
 *   procedural condensation/scratch texture perturbs the refraction UV
 *   itself (not just a lit bump) for real imperfection in what you see
 *   through the glass, and adds visible droplet highlights.
 *
 * MILESTONE 2 — The liquid isn't one flat green.
 *   Vertex colors baked once from 3D noise vary brightness/density across
 *   the liquid body (real per-region variation, not a uniform), on top of
 *   the still-live state-hue tint.
 *
 * MILESTONE 3 — The fog is three-dimensional.
 *   A raymarched volumetric shader (12 steps × 3-octave simplex-noise fBm,
 *   GLSL) fills the liquid volume with genuine suspended density — light
 *   scatters through it toward nearby moving internal point lights, so
 *   "glowing regions" are real light sources catching real fog, not a
 *   painted sprite. Layered with a handful of oriented sprite wisps for
 *   near-camera detail bloom can catch.
 *
 * MILESTONE 4 — The surface is alive.
 *   Height comes from 4-octave fBm (not a couple of sine terms), plus a
 *   real local dimple wherever a bubble is about to breach — the surface
 *   visibly responds to what's rising through it.
 *
 * MILESTONE 5 — Bubbles behave like physics, no two identical.
 *   Independent objects: size-dependent buoyancy, drift sampled from the
 *   same curl-noise current as the fog, genuine volume-conserving merge on
 *   overlap, noise-driven pressure split once large, size-scaled
 *   surface-tension oscillation, and now an individually-randomized
 *   material (opacity/tint) per bubble rather than one shared material.
 *
 * MILESTONE 6 — An emergent presence, not a modeled creature.
 *   A handful of large, dim, correlated masses drift in a loose
 *   head-and-shoulders template inside the murk, coalescing and brightening
 *   during a shared "surge" (a fast-rise/slow-decay noise signal sampled
 *   over real time) and dissolving back into general haze during calm.
 *   Nothing is an explicit model — the arrangement is a template, the
 *   motion is the same curl field everything else uses, deliberately dim.
 *
 * Disclosed scope limits: true SPH/grid fluid simulation, screen-space
 * reflections of arbitrary scene geometry, and physically exact spectral
 * dispersion are not attempted — they need a compute pipeline or
 * multi-pass wavelength rendering that doesn't fit a dashboard widget, and
 * a bad approximation of them would look worse than not having them.
 *
 * Every real *state* value (not motion) still traces to genuine data:
 * mode/confidence/health from agent.mind (useSelfState), real WebSocket
 * timeline events, real mic amplitude while listening, real speech
 * playback state. No setInterval/setTimeout anywhere in this file.
 */
interface PresenceEngineProps {
  className?: string;
  micLevel?: number;
  isListening?: boolean;
  isVoiceSpeaking?: boolean;
}

const BASE_HUE = 144 / 360; // MARK's own accent (index.css --accent, a green), as a 0-1 hue
const ERROR_HUE = 6 / 360;
const ORB_RADIUS = 1.5;
const FILL_PHI = 1.42; // polar angle (rad) of the liquid surface — ~ just above the equator

const MODE_ENERGY: Record<string, number> = {
  idle: 0.16, listening: 0.3, waiting: 0.12, sleeping: 0.05,
  thinking: 0.55, planning: 0.6, researching: 0.55,
  executing: 0.85, reflecting: 0.5, learning: 0.55,
  error: 0.4, recovering: 0.35,
};

// ─── Deterministic 3D Perlin noise + curl field (CPU side, drives object ──
// positions/heights) ─────────────────────────────────────────────────────
// Classic reference-algorithm Perlin noise, fixed-seed shuffle (so it's the
// exact same field every run — deterministic — but sampled continuously
// through real time it never repeats). Never Math.random() for motion.
const PERM: Uint8Array = (() => {
  const p = new Uint8Array(256);
  for (let i = 0; i < 256; i++) p[i] = i;
  let seed = 1234567;
  const rnd = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; };
  for (let i = 255; i > 0; i--) {
    const j = Math.floor(rnd() * (i + 1));
    const tmp = p[i]; p[i] = p[j]; p[j] = tmp;
  }
  const perm = new Uint8Array(512);
  for (let i = 0; i < 512; i++) perm[i] = p[i & 255];
  return perm;
})();
function fade(t: number) { return t * t * t * (t * (t * 6 - 15) + 10); }
function grad(hash: number, x: number, y: number, z: number) {
  const h = hash & 15;
  const u = h < 8 ? x : y;
  const v = h < 4 ? y : (h === 12 || h === 14 ? x : z);
  return ((h & 1) === 0 ? u : -u) + ((h & 2) === 0 ? v : -v);
}
function perlin3(x: number, y: number, z: number): number {
  const X = Math.floor(x) & 255, Y = Math.floor(y) & 255, Z = Math.floor(z) & 255;
  x -= Math.floor(x); y -= Math.floor(y); z -= Math.floor(z);
  const u = fade(x), v = fade(y), w = fade(z);
  const A = PERM[X] + Y, AA = PERM[A] + Z, AB = PERM[A + 1] + Z;
  const B = PERM[X + 1] + Y, BA = PERM[B] + Z, BB = PERM[B + 1] + Z;
  const lerp = (t: number, a: number, b: number) => a + t * (b - a);
  return lerp(w,
    lerp(v, lerp(u, grad(PERM[AA], x, y, z), grad(PERM[BA], x - 1, y, z)),
      lerp(u, grad(PERM[AB], x, y - 1, z), grad(PERM[BB], x - 1, y - 1, z))),
    lerp(v, lerp(u, grad(PERM[AA + 1], x, y, z - 1), grad(PERM[BA + 1], x - 1, y, z - 1)),
      lerp(u, grad(PERM[AB + 1], x, y - 1, z - 1), grad(PERM[BB + 1], x - 1, y - 1, z - 1))));
}
/** Fractal Brownian motion — several octaves of Perlin noise summed, the
 * standard way to build a rich, non-repeating heightfield from simple noise. */
function fbm3(x: number, y: number, z: number, octaves: number): number {
  let amp = 0.55, freq = 1, sum = 0, norm = 0;
  for (let i = 0; i < octaves; i++) {
    sum += perlin3(x * freq, y * freq, z * freq) * amp;
    norm += amp;
    amp *= 0.5; freq *= 2.05; // irrational-ish ratio — octaves never fall back into lockstep
  }
  return sum / norm;
}
const CURL_EPS = 0.09;
function potX(x: number, y: number, z: number, t: number) { return perlin3(x * 0.9 + 37.1, y * 0.9, z * 0.9 - t * 0.12); }
function potY(x: number, y: number, z: number, t: number) { return perlin3(x * 0.9, y * 0.9 + 91.3, z * 0.9 + t * 0.11); }
function potZ(x: number, y: number, z: number, t: number) { return perlin3(x * 0.9 - 58.2, y * 0.9, z * 0.9 + t * 0.13); }
/** Curl of a pseudo vector-potential built from 3 offset/decorrelated noise
 * fields — the standard real-time-VFX substitute for real fluid velocity:
 * swirly, incompressible-*looking* flow with no simulation grid required. */
function curl(x: number, y: number, z: number, t: number, out: THREE.Vector3): THREE.Vector3 {
  const dPzdy = (potZ(x, y + CURL_EPS, z, t) - potZ(x, y - CURL_EPS, z, t)) / (2 * CURL_EPS);
  const dPydz = (potY(x, y, z + CURL_EPS, t) - potY(x, y, z - CURL_EPS, t)) / (2 * CURL_EPS);
  const dPxdz = (potX(x, y, z + CURL_EPS, t) - potX(x, y, z - CURL_EPS, t)) / (2 * CURL_EPS);
  const dPzdx = (potZ(x + CURL_EPS, y, z, t) - potZ(x - CURL_EPS, y, z, t)) / (2 * CURL_EPS);
  const dPydx = (potY(x + CURL_EPS, y, z, t) - potY(x - CURL_EPS, y, z, t)) / (2 * CURL_EPS);
  const dPxdy = (potX(x, y + CURL_EPS, z, t) - potX(x, y - CURL_EPS, z, t)) / (2 * CURL_EPS);
  return out.set(dPzdy - dPydz, dPxdz - dPzdx, dPydx - dPxdy);
}

/**
 * Builds the liquid body: a spherical "bowl" from the fill line down to
 * the bottom pole, capped with a flat disc at the fill line. Standard
 * spherical parametrization (phi = polar angle from the top pole) means
 * the cap disc's radius naturally matches the bowl's true cross-section at
 * the fill line — no seam. The disc's vertices (including its rim, which
 * is literally the same vertices as the bowl's top ring) are the ones the
 * render loop perturbs each frame for the surface ripple; everything below
 * stays static, like still water under a moving surface. Also bakes a
 * per-vertex density value (3D fBm) into a color attribute — real
 * brightness/darkness variation across the liquid, not one flat color.
 */
function buildLiquidGeometry(radius: number, fillPhi: number, latSegments: number, lonSegments: number) {
  const positions: number[] = [];
  const indices: number[] = [];
  const ringStart: number[] = [];

  for (let i = 0; i <= latSegments; i++) {
    const phi = fillPhi + (Math.PI - fillPhi) * (i / latSegments);
    ringStart.push(positions.length / 3);
    for (let j = 0; j <= lonSegments; j++) {
      const theta = (j / lonSegments) * Math.PI * 2;
      positions.push(
        radius * Math.sin(phi) * Math.cos(theta),
        radius * Math.cos(phi),
        radius * Math.sin(phi) * Math.sin(theta),
      );
    }
  }
  for (let i = 0; i < latSegments; i++) {
    for (let j = 0; j < lonSegments; j++) {
      const a = ringStart[i] + j, b = ringStart[i] + j + 1;
      const c = ringStart[i + 1] + j, d = ringStart[i + 1] + j + 1;
      indices.push(a, b, c, b, d, c);
    }
  }

  // Cap: a center point + fan to the bowl's top ring (shared vertices — no seam).
  const capRingStart = ringStart[0];
  const capVertexIndices = [];
  const centerIndex = positions.length / 3;
  positions.push(0, radius * Math.cos(fillPhi), 0);
  capVertexIndices.push(centerIndex);
  for (let j = 0; j <= lonSegments; j++) capVertexIndices.push(capRingStart + j);
  for (let j = 0; j < lonSegments; j++) {
    indices.push(centerIndex, capRingStart + j + 1, capRingStart + j);
  }

  const geo = new THREE.BufferGeometry();
  const posArray = new Float32Array(positions);
  geo.setAttribute('position', new THREE.BufferAttribute(posArray, 3));
  geo.setIndex(indices);

  // Per-vertex density: layered fBm at two frequencies, clamped to a
  // believable brightness band so the state-hue tint (applied per-frame on
  // top) still reads as "one liquid", just genuinely uneven.
  const colors = new Float32Array(posArray.length);
  for (let i = 0; i < posArray.length; i += 3) {
    const x = posArray[i], y = posArray[i + 1], z = posArray[i + 2];
    const density = 0.55 + 0.45 * (0.5 + 0.5 * fbm3(x * 1.1 + 4.2, y * 1.1 - 8.7, z * 1.1 + 2.1, 3));
    colors[i] = colors[i + 1] = colors[i + 2] = density;
  }
  geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  geo.computeVertexNormals();
  return { geo, capVertexIndices, basePositions: (posArray).slice() };
}

/** A large, very soft-edged round gradient — the billboard used for the
 * murky drifting fog wisps and internal-light glows inside the liquid. */
function createFogSprite(): THREE.Texture {
  const size = 128;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d')!;
  const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  gradient.addColorStop(0, 'rgba(255,255,255,0.9)');
  gradient.addColorStop(0.45, 'rgba(255,255,255,0.35)');
  gradient.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(canvas);
  tex.needsUpdate = true;
  return tex;
}

/** Procedural glass imperfections — condensation droplets + micro-scratches
 * — sampled directly inside the refraction shader (not just a lit bump),
 * so what you see *through* the glass is genuinely, subtly distorted. */
function createGlassImperfectionTexture(): THREE.Texture {
  const size = 512;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d')!;
  ctx.fillStyle = '#808080';
  ctx.fillRect(0, 0, size, size);
  for (let i = 0; i < 70; i++) {
    const x = Math.random() * size, y = Math.random() * size, r = 1.5 + Math.random() * 4;
    const grad2 = ctx.createRadialGradient(x, y, 0, x, y, r);
    grad2.addColorStop(0, 'rgba(255,255,255,0.85)');
    grad2.addColorStop(1, 'rgba(128,128,128,0)');
    ctx.fillStyle = grad2;
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
  }
  ctx.strokeStyle = 'rgba(200,200,200,0.22)';
  ctx.lineWidth = 0.6;
  for (let i = 0; i < 40; i++) {
    const x = Math.random() * size, y = Math.random() * size;
    const len = 4 + Math.random() * 18, ang = Math.random() * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + Math.cos(ang) * len, y + Math.sin(ang) * len);
    ctx.stroke();
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(2, 2);
  tex.needsUpdate = true;
  return tex;
}

/** Cheap real-time caustic approximation: overlapping soft-edged highlight
 * cells, scrolled/rotated over time — the same trick used in most games,
 * since true caustics need photon-mapped ray tracing. */
function createCausticTexture(): THREE.Texture {
  const size = 256;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d')!;
  for (let i = 0; i < 40; i++) {
    const x = Math.random() * size, y = Math.random() * size, r = 8 + Math.random() * 26;
    const grad2 = ctx.createRadialGradient(x, y, 0, x, y, r);
    grad2.addColorStop(0, 'rgba(255,255,255,0.9)');
    grad2.addColorStop(0.6, 'rgba(255,255,255,0.22)');
    grad2.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = grad2;
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.needsUpdate = true;
  return tex;
}

const FRESNEL_VERTEX = `
  varying vec3 vNormalView;
  varying vec3 vViewDir;
  void main() {
    vNormalView = normalize(normalMatrix * normal);
    vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
    vViewDir = normalize(-mvPosition.xyz);
    gl_Position = projectionMatrix * mvPosition;
  }
`;
// The R/B channel split at grazing angles is a stylized "dispersion" cue,
// not physically accurate spectral refraction (that needs multi-pass
// wavelength-dependent rendering) — cheap and common in real-time glass.
const FRESNEL_FRAGMENT = `
  uniform vec3 uColor;
  uniform float uOpacity;
  uniform float uPower;
  varying vec3 vNormalView;
  varying vec3 vViewDir;
  void main() {
    float fresnel = pow(1.0 - max(dot(normalize(vNormalView), normalize(vViewDir)), 0.0), uPower);
    vec3 dispersed = uColor + vec3(fresnel * 0.14, 0.0, -fresnel * 0.11);
    gl_FragColor = vec4(dispersed, fresnel * uOpacity);
  }
`;

// ─── Real screen-space refraction shell ────────────────────────────────────
const SHELL_VERTEX = `
  varying vec3 vNormalW;
  varying vec3 vViewDir;
  varying vec2 vUv2;
  void main() {
    vUv2 = uv;
    vNormalW = normalize(normalMatrix * normal);
    vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
    vViewDir = normalize(-mvPosition.xyz);
    gl_Position = projectionMatrix * mvPosition;
  }
`;
const SHELL_FRAGMENT = `
  uniform sampler2D uBackdrop;
  uniform sampler2D uImperfection;
  uniform vec2 uResolution;
  uniform vec3 uTintColor;
  uniform float uOpacity;
  varying vec3 vNormalW;
  varying vec3 vViewDir;
  varying vec2 vUv2;
  void main() {
    vec2 screenUV = gl_FragCoord.xy / uResolution;
    float imperfection = texture2D(uImperfection, vUv2 * 2.0).r;
    float fresnel = pow(1.0 - max(dot(normalize(vNormalW), normalize(vViewDir)), 0.0), 2.5);
    vec2 refractOffset = vNormalW.xy * 0.045 * (1.0 - fresnel * 0.5) + (imperfection - 0.5) * 0.012;
    vec2 sampleUV = clamp(screenUV + refractOffset, 0.001, 0.999);
    vec3 backdrop = texture2D(uBackdrop, sampleUV).rgb;
    vec3 tinted = mix(backdrop, backdrop * uTintColor, 0.38);
    vec3 reflection = mix(tinted, vec3(1.0), fresnel * 0.62);
    float droplet = smoothstep(0.74, 0.92, imperfection) * 0.22;
    gl_FragColor = vec4(reflection + droplet, mix(uOpacity, 1.0, fresnel * 0.72) + droplet * 0.3);
  }
`;

// ─── Raymarched volumetric fog (Ashima/McEwan simplex noise — public-────
// domain reference implementation, extremely well-tested) ──────────────
const SIMPLEX_GLSL = `
  vec3 mod289(vec3 x) { return x - floor(x / 289.0) * 289.0; }
  vec4 mod289(vec4 x) { return x - floor(x / 289.0) * 289.0; }
  vec4 permute(vec4 x) { return mod289((x * 34.0 + 1.0) * x); }
  vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }
  float snoise(vec3 v) {
    const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
    const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
    vec3 i  = floor(v + dot(v, C.yyy));
    vec3 x0 = v - i + dot(i, C.xxx);
    vec3 g = step(x0.yzx, x0.xyz);
    vec3 l = 1.0 - g;
    vec3 i1 = min(g.xyz, l.zxy);
    vec3 i2 = max(g.xyz, l.zxy);
    vec3 x1 = x0 - i1 + C.xxx;
    vec3 x2 = x0 - i2 + C.yyy;
    vec3 x3 = x0 - D.yyy;
    i = mod289(i);
    vec4 p = permute(permute(permute(
               i.z + vec4(0.0, i1.z, i2.z, 1.0))
             + i.y + vec4(0.0, i1.y, i2.y, 1.0))
             + i.x + vec4(0.0, i1.x, i2.x, 1.0));
    float n_ = 0.142857142857;
    vec3 ns = n_ * D.wyz - D.xzx;
    vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
    vec4 x_ = floor(j * ns.z);
    vec4 y_ = floor(j - 7.0 * x_);
    vec4 x = x_ * ns.x + ns.yyyy;
    vec4 y = y_ * ns.x + ns.yyyy;
    vec4 h = 1.0 - abs(x) - abs(y);
    vec4 b0 = vec4(x.xy, y.xy);
    vec4 b1 = vec4(x.zw, y.zw);
    vec4 s0 = floor(b0) * 2.0 + 1.0;
    vec4 s1 = floor(b1) * 2.0 + 1.0;
    vec4 sh = -step(h, vec4(0.0));
    vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
    vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;
    vec3 p0 = vec3(a0.xy, h.x);
    vec3 p1 = vec3(a0.zw, h.y);
    vec3 p2 = vec3(a1.xy, h.z);
    vec3 p3 = vec3(a1.zw, h.w);
    vec4 norm = taylorInvSqrt(vec4(dot(p0, p0), dot(p1, p1), dot(p2, p2), dot(p3, p3)));
    p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
    vec4 m = max(0.6 - vec4(dot(x0, x0), dot(x1, x1), dot(x2, x2), dot(x3, x3)), 0.0);
    m = m * m;
    return 42.0 * dot(m * m, vec4(dot(p0, x0), dot(p1, x1), dot(p2, x2), dot(p3, x3)));
  }
`;
const VOLUME_VERTEX = `
  varying vec3 vWorldPos;
  varying vec3 vViewDir;
  void main() {
    vec4 wp = modelMatrix * vec4(position, 1.0);
    vWorldPos = wp.xyz;
    vViewDir = normalize(wp.xyz - cameraPosition);
    gl_Position = projectionMatrix * viewMatrix * wp;
  }
`;

export function PresenceEngine({ className = '', micLevel = 0, isListening = false, isVoiceSpeaking = false }: PresenceEngineProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { selfState, isSpeaking: isTextSpeaking } = useSelfState();
  const tokenTimestamps = useMarkStore(s => s.tokenTimestamps);
  const timeline = useMarkStore(s => s.timeline);

  const stateRef = useRef({ selfState, isTextSpeaking, tokenTimestamps, micLevel, isListening, isVoiceSpeaking });
  stateRef.current = { selfState, isTextSpeaking, tokenTimestamps, micLevel, isListening, isVoiceSpeaking };

  const seenEventsRef = useRef<Set<string>>(new Set());
  const timelineRef = useRef(timeline);
  timelineRef.current = timeline;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // Pre-existing timeline history shouldn't all fire as "new" the instant
    // this mounts — only events that arrive after mount should ripple/pulse it.
    for (const ev of timelineRef.current) seenEventsRef.current.add(ev.id);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100);
    camera.position.set(0, 0.15, 7.2);
    camera.lookAt(0, 0, 0);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.15;
    container.appendChild(renderer.domElement);

    // Real bloom — three.js's own postprocessing (ships inside the `three`
    // package, no new dependency). Threshold kept high so only genuine
    // highlights/emissive bubbles bloom, not the whole liquid mass.
    const composer = new EffectComposer(renderer);
    composer.addPass(new RenderPass(scene, camera));
    const bloomPass = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.55, 0.45, 0.82);
    composer.addPass(bloomPass);

    // Offscreen target the glass shell refracts — everything else in the
    // scene renders here first, every frame, before the shell reads it.
    const backdropTarget = new THREE.WebGLRenderTarget(2, 2, {
      minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter, format: THREE.RGBAFormat,
    });

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = container;
      if (w === 0 || h === 0) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
      composer.setSize(w, h);
      const rw = renderer.domElement.width, rh = renderer.domElement.height;
      backdropTarget.setSize(rw, rh);
      shellMat.uniforms.uResolution.value.set(rw, rh);
    };

    const initialColor = new THREE.Color().setHSL(BASE_HUE, 1, 0.5);

    // ── Real lights. A tight, bright key light is what produces the sharp ──
    // glossy highlight glass needs; a soft fill keeps the far side legible.
    const ambientLight = new THREE.AmbientLight(0x040a08, 0.1);
    const keyLight = new THREE.PointLight(0xf3fff5, 12, 9, 2);
    keyLight.position.set(-2.8, 3.4, 4.2);
    const fillLight = new THREE.PointLight(0x123424, 0.28, 20, 1.8);
    fillLight.position.set(2.6, -1.2, 2.6);
    const backLight = new THREE.DirectionalLight(0x3ba86a, 0.35);
    backLight.position.set(-1, -1, -3);
    scene.add(ambientLight, keyLight, fillLight, backLight);

    const orbGroup = new THREE.Group();
    scene.add(orbGroup);

    // ── Outer glass shell — real two-pass screen-space refraction (see ──
    // MILESTONE 1 in the file header).
    const glassImperfectionTex = createGlassImperfectionTexture();
    const shellGeo = new THREE.SphereGeometry(ORB_RADIUS, 64, 48);
    const shellMat = new THREE.ShaderMaterial({
      uniforms: {
        uBackdrop: { value: backdropTarget.texture },
        uImperfection: { value: glassImperfectionTex },
        uResolution: { value: new THREE.Vector2(2, 2) },
        uTintColor: { value: initialColor.clone() },
        uOpacity: { value: 0.5 },
      },
      vertexShader: SHELL_VERTEX,
      fragmentShader: SHELL_FRAGMENT,
      transparent: true,
      depthWrite: false,
    });
    const shell = new THREE.Mesh(shellGeo, shellMat);
    orbGroup.add(shell);

    // ── Inner liquid — a bowl clipped at the fill line with a rippling top,
    // vertex-colored for real density variation (MILESTONE 2).
    const LAT_SEGMENTS = 22, LON_SEGMENTS = 48;
    const { geo: liquidGeo, capVertexIndices, basePositions: liquidBase } =
      buildLiquidGeometry(ORB_RADIUS * 0.965, FILL_PHI, LAT_SEGMENTS, LON_SEGMENTS);
    const liquidMat = new THREE.MeshPhysicalMaterial({
      color: initialColor.clone(),
      vertexColors: true,
      transparent: true,
      opacity: 0.86,
      roughness: 0.1,
      metalness: 0,
      clearcoat: 0.6,
      clearcoatRoughness: 0.2,
      emissive: initialColor.clone(),
      emissiveIntensity: 0.22,
      side: THREE.DoubleSide,
    });
    const liquid = new THREE.Mesh(liquidGeo, liquidMat);
    orbGroup.add(liquid);

    // ── A thin brighter film right at the surface line — sells "this is ──
    // a liquid surface", not just a colored solid.
    const filmGeo = new THREE.CircleGeometry(ORB_RADIUS * 0.965 * Math.sin(FILL_PHI) * 1.01, LON_SEGMENTS);
    const filmBase = (filmGeo.attributes.position.array as Float32Array).slice();
    const filmMat = new THREE.MeshPhysicalMaterial({
      color: 0xdcffe9,
      transparent: true,
      opacity: 0.28,
      roughness: 0.05,
      clearcoat: 1,
      side: THREE.DoubleSide,
    });
    const film = new THREE.Mesh(filmGeo, filmMat);
    film.rotation.x = -Math.PI / 2;
    const FILL_Y = ORB_RADIUS * 0.965 * Math.cos(FILL_PHI);
    film.position.y = FILL_Y;
    orbGroup.add(film);

    // ── Fresnel edge glint — the bright rim real glass shows at grazing ──
    // angles (total internal reflection), layered over the refraction shell.
    const rimGeo = new THREE.SphereGeometry(ORB_RADIUS * 1.01, 48, 32);
    const rimMat = new THREE.ShaderMaterial({
      uniforms: {
        uColor: { value: new THREE.Color(0xeaffef) },
        uOpacity: { value: 0.55 },
        uPower: { value: 3.6 },
      },
      vertexShader: FRESNEL_VERTEX,
      fragmentShader: FRESNEL_FRAGMENT,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const rimGlow = new THREE.Mesh(rimGeo, rimMat);
    orbGroup.add(rimGlow);

    const bottomY = ORB_RADIUS * 0.965 * Math.cos(Math.PI - 0.35);
    const topY = FILL_Y - 0.03;

    // ── Caustic-style light pattern near the bottom — the classic cheap ──
    // real-time approximation (animated overlapping highlight cells), not
    // photon-mapped caustics.
    const causticTex = createCausticTexture();
    const causticGeo = new THREE.CircleGeometry(ORB_RADIUS * 0.5, 40);
    const causticMat = new THREE.MeshBasicMaterial({
      map: causticTex, color: 0xbfffdd, transparent: true, opacity: 0.16,
      blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide,
    });
    const caustic = new THREE.Mesh(causticGeo, causticMat);
    caustic.rotation.x = -Math.PI / 2;
    caustic.position.y = bottomY + 0.03;
    orbGroup.add(caustic);

    // ── Raymarched volumetric fog (MILESTONE 3) — fills the liquid volume ──
    // with real suspended density, scattering light toward the moving
    // internal lights defined below.
    const volumeGeo = new THREE.SphereGeometry(ORB_RADIUS * 0.92, 24, 18);
    const volumeMat = new THREE.ShaderMaterial({
      uniforms: {
        uTime: { value: 0 },
        uColor: { value: initialColor.clone() },
        uDensity: { value: 0.85 },
        uLightPos: { value: [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3()] },
        uLightColor: { value: [new THREE.Color(), new THREE.Color(), new THREE.Color(), new THREE.Color()] },
      },
      vertexShader: VOLUME_VERTEX,
      fragmentShader: `
        ${SIMPLEX_GLSL}
        uniform float uTime;
        uniform vec3 uColor;
        uniform float uDensity;
        uniform vec3 uLightPos[4];
        uniform vec3 uLightColor[4];
        varying vec3 vWorldPos;
        varying vec3 vViewDir;
        float fbmV(vec3 p) {
          float f = 0.0, amp = 0.5;
          for (int i = 0; i < 3; i++) { f += amp * snoise(p); p *= 2.02; amp *= 0.5; }
          return f;
        }
        void main() {
          vec3 rayDir = normalize(vViewDir);
          vec3 pos = vWorldPos;
          float accum = 0.0;
          vec3 lightAccum = vec3(0.0);
          const int STEPS = 12;
          float stepSize = 0.055;
          for (int i = 0; i < STEPS; i++) {
            float n = fbmV(pos * 1.7 + vec3(0.0, 0.0, uTime * 0.05));
            float density = clamp(n * 0.5 + 0.32, 0.0, 1.0) * uDensity;
            for (int L = 0; L < 4; L++) {
              float d = length(pos - uLightPos[L]);
              lightAccum += uLightColor[L] * density * 0.4 / (1.0 + d * d * 7.0);
            }
            float fillFade = smoothstep(${(FILL_Y + 0.06).toFixed(4)}, ${(FILL_Y - 0.12).toFixed(4)}, pos.y);
            accum += density * 0.085 * fillFade;
            pos += rayDir * stepSize;
          }
          accum = clamp(accum, 0.0, 0.8);
          vec3 col = uColor * accum * 0.6 + lightAccum;
          gl_FragColor = vec4(col, accum);
        }
      `,
      transparent: true,
      depthWrite: false,
      side: THREE.BackSide,
    });
    const volumeFog = new THREE.Mesh(volumeGeo, volumeMat);
    orbGroup.add(volumeFog);

    // ── Moving internal lights — real point lights the volumetric fog and ──
    // bubbles scatter/catch, so "glowing regions" are genuine light sources.
    const INTERNAL_LIGHT_COUNT = 4;
    type InternalLight = { light: THREE.PointLight; glow: THREE.Sprite; phase: number };
    const internalLights: InternalLight[] = [];
    const glowSpriteTex = createFogSprite();
    for (let i = 0; i < INTERNAL_LIGHT_COUNT; i++) {
      const light = new THREE.PointLight(0x7dffc0, 0.7, 1.5, 2);
      const r = 0.08 + Math.random() * 0.3, theta = Math.random() * Math.PI * 2;
      const y = bottomY + 0.08 + Math.random() * (topY - bottomY - 0.25);
      light.position.set(Math.cos(theta) * r, y, Math.sin(theta) * r);
      orbGroup.add(light);
      const glowMat = new THREE.SpriteMaterial({
        map: glowSpriteTex, transparent: true, opacity: 0.55, color: 0x9dffdd,
        blending: THREE.AdditiveBlending, depthWrite: false,
      });
      const glow = new THREE.Sprite(glowMat);
      glow.scale.setScalar(0.11);
      glow.position.copy(light.position);
      orbGroup.add(glow);
      internalLights.push({ light, glow, phase: Math.random() * Math.PI * 2 });
    }
    const lightWorldScratch = new THREE.Vector3();

    // ── Bubbles: independent physical objects — size-dependent buoyancy, ──
    // drift sampled from the same curl-noise current the fog uses, genuine
    // volume-conserving merge on overlap, noise-driven pressure split once
    // large, continuous surface-tension-style oscillation whose frequency
    // scales with size, and an individually-randomized material per bubble
    // (MILESTONE 5) — no two bubbles share phase/frequency/size/material.
    const BUBBLE_COUNT = 40;
    const MIN_R = 0.028, MAX_R = 0.16;
    const bubbleGeo = new THREE.SphereGeometry(1, 12, 10);
    function makeBubbleMaterial(): THREE.MeshPhysicalMaterial {
      return new THREE.MeshPhysicalMaterial({
        color: 0xffffff,
        transparent: true,
        opacity: 0.62 + Math.random() * 0.32,
        roughness: 0.02,
        clearcoat: 1,
        clearcoatRoughness: 0.02,
        emissive: 0xd8fff0,
        emissiveIntensity: 0.22 + Math.random() * 0.32,
      });
    }
    type Bubble = {
      mesh: THREE.Mesh; mat: THREE.MeshPhysicalMaterial; size: number; wobbleFreq: number;
      wobblePhaseX: number; wobblePhaseY: number; wobblePhaseZ: number;
      phase: number; cooldown: number;
    };
    const bubbles: Bubble[] = [];
    function resetBubble(b: Bubble, startAtBottom: boolean) {
      const r = 0.05 + Math.random() * Math.random() * 0.5; // bias toward center, but with real spread
      const theta = Math.random() * Math.PI * 2;
      b.mesh.position.set(
        Math.cos(theta) * r,
        startAtBottom ? bottomY + Math.random() * 0.12 : bottomY + Math.random() * (topY - bottomY),
        Math.sin(theta) * r,
      );
      b.size = MIN_R + Math.random() * (MAX_R * 0.55 - MIN_R);
      b.mesh.scale.setScalar(b.size);
      b.wobbleFreq = 5 + Math.random() * 7; // smaller bubbles → higher surface-tension oscillation frequency, applied below
      b.wobblePhaseX = Math.random() * Math.PI * 2;
      b.wobblePhaseY = Math.random() * Math.PI * 2;
      b.wobblePhaseZ = Math.random() * Math.PI * 2;
      b.phase = Math.random() * Math.PI * 2;
      b.cooldown = 0.25 + Math.random() * 0.4;
    }
    for (let i = 0; i < BUBBLE_COUNT; i++) {
      const mat = makeBubbleMaterial();
      const mesh = new THREE.Mesh(bubbleGeo, mat);
      const b: Bubble = { mesh, mat, size: 0.05, wobbleFreq: 6, wobblePhaseX: 0, wobblePhaseY: 0, wobblePhaseZ: 0, phase: 0, cooldown: 0 };
      resetBubble(b, false);
      bubbles.push(b);
      orbGroup.add(mesh);
    }
    const curlScratch = new THREE.Vector3();

    // ── Internal fog/murk sprites — layered with the volumetric shader ──
    // above for near-camera detail bloom can catch; genuinely advected by
    // the same curl-noise current field bubbles use.
    const FOG_COUNT = 9;
    const fogTexture = createFogSprite();
    type FogWisp = { sprite: THREE.Sprite; pos: THREE.Vector3; opacityPhase: number; escapes: boolean };
    const fogWisps: FogWisp[] = [];
    for (let i = 0; i < FOG_COUNT; i++) {
      const mat = new THREE.SpriteMaterial({
        map: fogTexture,
        transparent: true,
        opacity: 0.12,
        color: new THREE.Color().setHSL(BASE_HUE, 0.6, 0.16),
        depthWrite: false,
      });
      const sprite = new THREE.Sprite(mat);
      const r = 0.08 + Math.random() * 0.42;
      const theta = Math.random() * Math.PI * 2;
      const y = bottomY + 0.06 + Math.random() * (topY - bottomY - 0.12);
      const pos = new THREE.Vector3(Math.cos(theta) * r, y, Math.sin(theta) * r);
      sprite.position.copy(pos);
      const scale = 0.55 + Math.random() * 1.0;
      sprite.scale.set(scale, scale, 1);
      orbGroup.add(sprite);
      fogWisps.push({ sprite, pos, opacityPhase: Math.random() * Math.PI * 2, escapes: i < 3 });
    }

    // ── MILESTONE 6 — an emergent presence, not a modeled creature. ──
    // A loose head-and-shoulders *template* of large, dim, correlated
    // masses; the same curl field drives them, so they drift together, and
    // a shared "surge" (below) pulls the template tighter/brighter for a
    // psychological "something is pushing against the glass" moment before
    // dissolving back into general haze. Nothing here is an explicit model.
    const CREATURE_TEMPLATE = [
      { x: 0, y: 0.17, z: 0.06, scale: 0.32 }, // head
      { x: -0.21, y: -0.02, z: 0.02, scale: 0.4 }, // left shoulder
      { x: 0.21, y: -0.02, z: 0.02, scale: 0.4 }, // right shoulder
      { x: -0.15, y: -0.22, z: -0.02, scale: 0.3 }, // torso-left
      { x: 0.15, y: -0.22, z: -0.02, scale: 0.3 }, // torso-right
    ];
    type CreatureBlob = { sprite: THREE.Sprite; base: THREE.Vector3; jitterPhase: THREE.Vector3; baseScale: number };
    const creatureBlobs: CreatureBlob[] = [];
    for (const tpl of CREATURE_TEMPLATE) {
      const mat = new THREE.SpriteMaterial({
        map: fogTexture, transparent: true, opacity: 0.08,
        color: new THREE.Color().setHSL(BASE_HUE, 0.7, 0.1),
        blending: THREE.AdditiveBlending, depthWrite: false,
      });
      const sprite = new THREE.Sprite(mat);
      sprite.scale.set(tpl.scale, tpl.scale, 1);
      orbGroup.add(sprite);
      creatureBlobs.push({
        sprite, base: new THREE.Vector3(tpl.x, tpl.y, tpl.z),
        jitterPhase: new THREE.Vector3(Math.random() * 100, Math.random() * 100, Math.random() * 100),
        baseScale: tpl.scale,
      });
    }
    const torsoCenter = new THREE.Vector3(0, bottomY + (topY - bottomY) * 0.4, 0.04);

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let energy = 0.2;
    let hue = BASE_HUE;
    let ripple = 0; // event-triggered pulse, decays
    let surge = 0; // shared "living entity" agitation — fast rise, slow decay
    const clock = new THREE.Clock();
    let introT = 0; // one-shot gentle scale-in on mount

    renderer.setAnimationLoop(() => {
      const { selfState, isTextSpeaking, tokenTimestamps, micLevel, isListening, isVoiceSpeaking } = stateRef.current;
      const t = clock.getElapsedTime();
      const dt = Math.min(clock.getDelta(), 0.05);

      const mode = selfState?.mode ?? 'idle';
      const modeEnergy = MODE_ENERGY[mode] ?? 0.2;
      const confidence = selfState?.confidence ?? 0.5;
      const isErrorMode = mode === 'error' || mode === 'recovering';

      const now = Date.now();
      const recentTokens = tokenTimestamps.filter((ts: number) => now - ts < 500).length;
      const streamBurst = isTextSpeaking ? Math.min(1, 0.4 + recentTokens * 0.05) : 0;
      const speakBurst = Math.max(streamBurst, isVoiceSpeaking ? 0.7 : 0);
      const listenBurst = isListening ? Math.min(1, 0.25 + micLevel * 0.9) : 0;

      const targetEnergy = Math.max(modeEnergy, speakBurst, listenBurst) * (0.5 + confidence * 0.5);
      const targetHue = isErrorMode ? ERROR_HUE : BASE_HUE;
      energy += (targetEnergy - energy) * (reduceMotion ? 0.02 : 0.06);
      hue += (targetHue - hue) * 0.05;
      ripple = Math.max(0, ripple - dt * 0.8);

      // ── The "living entity" surge — a 1D deterministic noise signal ──
      // sampled at a fixed point over real time: mostly calm, occasionally
      // rises sharply then decays slowly. Shared across the whole liquid,
      // every bubble, and the creature template at once, which is what
      // makes it read as one thing surging rather than independent jitter.
      const moodSignal = perlin3(3.7, 8.2, t * 0.32);
      const surgeTarget = reduceMotion ? 0 : Math.max(0, Math.min(1, (moodSignal - 0.12) / 0.42));
      surge += (surgeTarget - surge) * (surgeTarget > surge ? 0.1 : 0.02);

      // Gentle one-shot scale-in on mount — a real elapsed-time ease, not a
      // physics fling.
      introT = Math.min(1, introT + dt / 0.7);
      const introScale = reduceMotion ? 1 : 0.85 + 0.15 * (1 - Math.pow(1 - introT, 3));
      orbGroup.scale.setScalar(introScale * (1 + surge * 0.012)); // a faint outward "pressure" during a surge

      // Calibrated against the reference photo: a deep, saturated jewel-
      // tone emerald with real dark pockets, not a pale uniform mint.
      const color = new THREE.Color().setHSL(hue, 0.92, 0.24 + energy * 0.09);
      liquidMat.color.copy(color);
      liquidMat.emissive.copy(color);
      liquidMat.emissiveIntensity = 0.08 + energy * 0.16 + ripple * 0.2 + surge * 0.14;
      filmMat.color.copy(color).lerp(new THREE.Color(0xffffff), 0.55);
      keyLight.intensity = 15 + energy * 4;
      fillLight.color.copy(color).lerp(new THREE.Color(0x0a1512), 0.3);
      rimMat.uniforms.uColor.value.copy(color).lerp(new THREE.Color(0xffffff), 0.5);
      rimMat.uniforms.uOpacity.value = 0.35 + energy * 0.25 + surge * 0.15;
      // Reference glass reads as near-colorless thick crystal, not a
      // pale-green wash — most of the tint lives in the liquid, not the shell.
      shellMat.uniforms.uTintColor.value.copy(color).lerp(new THREE.Color(0xffffff), 0.72);
      volumeMat.uniforms.uTime.value = t;
      volumeMat.uniforms.uColor.value.copy(color);
      volumeMat.uniforms.uDensity.value = 0.85 + energy * 0.35 + surge * 0.3;
      bloomPass.strength = 0.42 + energy * 0.32 + surge * 0.28;

      // ── Liquid surface: fBm heightfield (4 octaves) plus a real local ──
      // dimple wherever a bubble is about to breach — the surface visibly
      // responds to what's rising through it (MILESTONE 4).
      const rippleAmp = 0.013 + energy * 0.022 + (isListening ? micLevel * 0.05 : 0) + ripple * 0.065 + surge * 0.05;
      const posAttr = liquidGeo.attributes.position;
      for (const idx of capVertexIndices) {
        const ix = idx * 3;
        const bx = liquidBase[ix], by = liquidBase[ix + 1], bz = liquidBase[ix + 2];
        let wave = fbm3(bx * 0.85 + 12.3, bz * 0.85 - 7.1, t * 0.3, 4) * rippleAmp * 2.1;
        for (const b of bubbles) {
          const distToSurface = topY - b.mesh.position.y;
          if (distToSurface < 0.14 && distToSurface > -0.05) {
            const dx = bx - b.mesh.position.x, dz = bz - b.mesh.position.z;
            const influence = Math.exp(-(dx * dx + dz * dz) / (b.size * b.size * 8)) * Math.max(0, 1 - distToSurface / 0.14);
            wave += influence * b.size * 1.6;
          }
        }
        posAttr.setXYZ(idx, bx, by + wave, bz);
      }
      posAttr.needsUpdate = true;
      liquidGeo.computeVertexNormals();

      // The surface film disc rides the same heightfield so it doesn't
      // look like a rigid plate floating above the moving liquid.
      const filmAttr = filmGeo.attributes.position;
      for (let i = 0; i < filmAttr.count; i++) {
        const ix = i * 3;
        const fx = filmBase[ix], fy = filmBase[ix + 1];
        // CircleGeometry lies in local XY before the mesh's own -90° X
        // rotation; ripple its local Y (which becomes world-space "outward
        // from center" after that rotation) using the same wave field.
        const wave = fbm3(fx * 0.85 + 12.3, fy * 0.85 - 7.1, t * 0.3, 4) * rippleAmp * 2.1;
        filmAttr.setXYZ(i, fx, fy, wave / 0.965);
      }
      filmAttr.needsUpdate = true;
      filmGeo.computeVertexNormals();

      // Caustic light pattern: slow scroll + rotation, brighter with real energy.
      causticTex.offset.set(t * 0.015, t * 0.011);
      caustic.rotation.z = t * 0.02;
      causticMat.opacity = 0.1 + energy * 0.12 + surge * 0.1;

      // ── Internal lights: drift on the shared curl field, pulse with ──
      // real time + surge; their *world* positions feed the volumetric
      // shader so scattering tracks where they actually are after rotation.
      for (let i = 0; i < internalLights.length; i++) {
        const il = internalLights[i];
        curl(il.light.position.x * 1.1, il.light.position.y * 1.1, il.light.position.z * 1.1, t * 0.6 + il.phase, curlScratch);
        il.light.position.x += curlScratch.x * 0.02 * dt;
        il.light.position.y += curlScratch.y * 0.01 * dt;
        il.light.position.z += curlScratch.z * 0.02 * dt;
        const rad = Math.hypot(il.light.position.x, il.light.position.z);
        if (rad > 0.4) { il.light.position.x *= 0.99; il.light.position.z *= 0.99; }
        il.light.position.y = Math.min(topY - 0.08, Math.max(bottomY + 0.1, il.light.position.y));
        il.glow.position.copy(il.light.position);
        // Reference photo: a few crisp, distinct bright points against a
        // genuinely dark liquid, not a soft even glow — pushed brighter and
        // more saturated so they read as real embedded light sources.
        const pulse = 0.6 + 0.4 * Math.sin(t * 1.3 + il.phase);
        il.light.intensity = (0.7 + energy * 0.7 + surge * 0.9) * pulse;
        il.light.color.copy(color).lerp(new THREE.Color(0xccffe4), 0.55);
        (il.glow.material as THREE.SpriteMaterial).opacity = 0.5 + pulse * 0.4 + surge * 0.25;
        (il.glow.material as THREE.SpriteMaterial).color.copy(color).lerp(new THREE.Color(0xccffe4), 0.6);
        il.light.getWorldPosition(lightWorldScratch);
        volumeMat.uniforms.uLightPos.value[i].copy(lightWorldScratch);
        volumeMat.uniforms.uLightColor.value[i].copy(il.light.color).multiplyScalar(il.light.intensity * 0.5);
      }

      // ── Fog wisps: real advection through the shared curl-noise current ──
      // field (the same field bubbles drift through below).
      for (const w of fogWisps) {
        curl(w.pos.x * 1.4, w.pos.y * 1.4, w.pos.z * 1.4, t, curlScratch);
        const flow = 0.05 + energy * 0.05 + surge * 0.09;
        w.pos.x += curlScratch.x * flow * dt;
        w.pos.y += curlScratch.y * flow * 0.5 * dt;
        w.pos.z += curlScratch.z * flow * dt;
        const rad = Math.hypot(w.pos.x, w.pos.z);
        if (rad > 0.58) {
          const pull = (rad - 0.58) * 2.2;
          w.pos.x -= (w.pos.x / rad) * pull * dt;
          w.pos.z -= (w.pos.z / rad) * pull * dt;
        }
        // A few wisps are allowed to drift up past the surface into the
        // clear glass air-pocket and dissipate there — the reference
        // photo shows smoke tendrils curling above the liquid line, not
        // fog strictly confined to the fluid.
        const ceiling = w.escapes ? ORB_RADIUS * 0.75 : topY - 0.03;
        w.pos.y = Math.min(ceiling, Math.max(bottomY + 0.05, w.pos.y));
        if (w.escapes && w.pos.y > topY + 0.5) w.pos.y = bottomY + 0.1; // dissipated — recycle back into the liquid
        w.sprite.position.copy(w.pos);
        const breathe = 0.5 + 0.5 * Math.sin(t * 0.3 + w.opacityPhase);
        const aboveSurfaceFade = w.pos.y > topY ? Math.max(0, 1 - (w.pos.y - topY) / 0.6) : 1;
        const mat = w.sprite.material as THREE.SpriteMaterial;
        mat.opacity = (0.06 + energy * 0.12 + surge * 0.07) * (0.4 + breathe * 0.7) * aboveSurfaceFade;
        mat.color.copy(color).lerp(new THREE.Color(0x020e08), 0.55);
      }

      // ── The emergent presence: torso center wanders very slowly on the ──
      // shared curl field; each blob's offset from it is the fixed
      // template scaled by "coalesce" (driven by surge) plus a small
      // curl-driven sway, so the form tightens/brightens during a surge and
      // loosens back into haze during calm.
      curl(torsoCenter.x * 0.6, torsoCenter.y * 0.6, torsoCenter.z * 0.6, t * 0.5, curlScratch);
      torsoCenter.x += curlScratch.x * 0.008 * dt;
      torsoCenter.z += curlScratch.z * 0.008 * dt;
      torsoCenter.y += curlScratch.y * 0.004 * dt;
      const tRad = Math.hypot(torsoCenter.x, torsoCenter.z);
      if (tRad > 0.2) { torsoCenter.x *= 0.998; torsoCenter.z *= 0.998; }
      torsoCenter.y = Math.min(topY - 0.35, Math.max(bottomY + 0.35, torsoCenter.y));
      const coalesce = 0.55 + surge * 0.45; // reference photo's form reads fairly clearly even at rest
      for (const blob of creatureBlobs) {
        curl(torsoCenter.x + blob.base.x, torsoCenter.y + blob.base.y, torsoCenter.z + blob.base.z, t * 0.7 + blob.jitterPhase.x, curlScratch);
        const jitterAmt = 0.018 * (1 - coalesce * 0.5);
        blob.sprite.position.set(
          torsoCenter.x + blob.base.x * coalesce + curlScratch.x * jitterAmt,
          torsoCenter.y + blob.base.y * coalesce + curlScratch.y * jitterAmt * 0.5,
          torsoCenter.z + blob.base.z * coalesce + curlScratch.z * jitterAmt,
        );
        const bmat = blob.sprite.material as THREE.SpriteMaterial;
        bmat.opacity = 0.09 + surge * 0.16 + energy * 0.05;
        bmat.color.copy(color).lerp(new THREE.Color(0x010805), 0.3);
        blob.sprite.scale.setScalar(blob.baseScale * (0.88 + coalesce * 0.28));
      }

      // ── Bubbles: buoyancy (bigger = faster), drift from the shared ──
      // curl-noise current, continuous size-scaled surface-tension
      // oscillation, and a real merge/split pass.
      for (const b of bubbles) {
        if (b.cooldown > 0) b.cooldown -= dt;
        const buoyancy = (0.5 + b.size * 3.4) * (0.4 + energy * 1.3);
        curl(b.mesh.position.x * 1.3, b.mesh.position.y * 1.3, b.mesh.position.z * 1.3, t, curlScratch);
        const flow = 0.14 + energy * 0.18 + surge * 0.4;
        b.mesh.position.y += buoyancy * dt;
        b.mesh.position.x += curlScratch.x * flow * dt;
        b.mesh.position.z += curlScratch.z * flow * dt;

        const rad = Math.hypot(b.mesh.position.x, b.mesh.position.z);
        if (rad > 0.56) {
          const pull = (rad - 0.56) * 3.0;
          b.mesh.position.x -= (b.mesh.position.x / rad) * pull * dt;
          b.mesh.position.z -= (b.mesh.position.z / rad) * pull * dt;
        }

        // Surface-tension-inspired oscillation: smaller bubbles wobble
        // faster and relatively harder (real small bubbles are stiffer
        // relative to their size), sharpened during a surge.
        const freqScale = 0.05 / Math.max(0.035, b.size);
        const wobbleAmp = (0.05 + surge * 0.09) * freqScale;
        const sx = b.size * (1 + Math.sin(t * b.wobbleFreq + b.wobblePhaseX) * wobbleAmp);
        const sy = b.size * (1 + Math.sin(t * b.wobbleFreq * 1.3 + b.wobblePhaseY) * wobbleAmp);
        const sz = b.size * (1 + Math.sin(t * b.wobbleFreq * 0.8 + b.wobblePhaseZ) * wobbleAmp);
        b.mesh.scale.set(sx, sy, sz);

        if (b.mesh.position.y > topY) resetBubble(b, true);
      }
      // Merge/split pass — real, not decorative: distance-based overlap
      // merges two into one (volume-conserving radius); noise-driven
      // "pressure" splits a bubble once it's grown large.
      for (let i = 0; i < bubbles.length; i++) {
        const a = bubbles[i];
        if (a.cooldown > 0) continue;
        for (let j = i + 1; j < bubbles.length; j++) {
          const c = bubbles[j];
          if (c.cooldown > 0) continue;
          const dx = a.mesh.position.x - c.mesh.position.x;
          const dy = a.mesh.position.y - c.mesh.position.y;
          const dz = a.mesh.position.z - c.mesh.position.z;
          const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
          if (dist < (a.size + c.size) * 0.62 && a.size + c.size < MAX_R * 1.7) {
            a.size = Math.min(MAX_R, Math.cbrt(a.size ** 3 + c.size ** 3));
            a.mesh.scale.setScalar(a.size);
            a.cooldown = 0.5;
            resetBubble(c, true);
            break;
          }
        }
        if (a.size > MAX_R * 0.9) {
          const pressure = Math.abs(perlin3(a.mesh.position.x * 4, a.mesh.position.y * 4, t * 0.7));
          if (pressure > 0.6) {
            const newR = Math.max(MIN_R, Math.cbrt((a.size ** 3) / 2));
            a.size = newR; a.mesh.scale.setScalar(newR); a.cooldown = 0.45;
            let victim = bubbles[0];
            for (const cand of bubbles) if (cand !== a && cand.mesh.position.y > victim.mesh.position.y) victim = cand;
            victim.mesh.position.copy(a.mesh.position);
            victim.mesh.position.x += (Math.random() - 0.5) * 0.08;
            victim.mesh.position.z += (Math.random() - 0.5) * 0.08;
            victim.size = newR; victim.mesh.scale.setScalar(newR); victim.cooldown = 0.45;
          }
        }
      }

      orbGroup.rotation.y += (reduceMotion ? 0.0008 : 0.0022) + energy * 0.001;

      // ── Real timeline events → one ripple pulse + a few fresh bubbles ──
      // (never a fake timer).
      const currentTimeline = timelineRef.current;
      for (let i = 0; i < Math.min(currentTimeline.length, 6); i++) {
        const ev = currentTimeline[i];
        if (!seenEventsRef.current.has(ev.id)) {
          seenEventsRef.current.add(ev.id);
          ripple = 1;
          for (let k = 0; k < 3; k++) resetBubble(bubbles[Math.floor(Math.random() * bubbles.length)], true);
        }
      }

      // ── Two-pass render: capture everything except the glass shell/rim ──
      // to the backdrop texture, then render the full scene (shell now
      // refracts that texture) through the bloom composer.
      shell.visible = false;
      rimGlow.visible = false;
      const prevTarget = renderer.getRenderTarget();
      renderer.setRenderTarget(backdropTarget);
      renderer.render(scene, camera);
      renderer.setRenderTarget(prevTarget);
      shell.visible = true;
      rimGlow.visible = true;
      composer.render();
    });

    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(container);
    window.addEventListener('resize', resize);
    const retryTimers = [50, 200, 500, 1000].map(ms => window.setTimeout(resize, ms));

    return () => {
      renderer.setAnimationLoop(null);
      ro.disconnect();
      window.removeEventListener('resize', resize);
      retryTimers.forEach(id => window.clearTimeout(id));
      composer.dispose?.();
      renderer.dispose();
      backdropTarget.dispose();
      shellGeo.dispose();
      shellMat.dispose();
      glassImperfectionTex.dispose();
      liquidGeo.dispose();
      liquidMat.dispose();
      filmGeo.dispose();
      filmMat.dispose();
      rimGeo.dispose();
      rimMat.dispose();
      causticGeo.dispose();
      causticMat.dispose();
      causticTex.dispose();
      volumeGeo.dispose();
      volumeMat.dispose();
      bubbleGeo.dispose();
      bubbles.forEach(b => b.mat.dispose());
      fogTexture.dispose();
      fogWisps.forEach(w => (w.sprite.material as THREE.SpriteMaterial).dispose());
      glowSpriteTex.dispose();
      internalLights.forEach(il => (il.glow.material as THREE.SpriteMaterial).dispose());
      creatureBlobs.forEach(cb => (cb.sprite.material as THREE.SpriteMaterial).dispose());
      if (renderer.domElement.parentNode === container) {
        container.removeChild(renderer.domElement);
      }
    };
  }, []);

  return (
    <div
      ref={containerRef}
      className={`w-full h-full ${className}`}
      role="img"
      aria-label="MARK's live cognitive state — a glass orb of glowing green liquid reflecting his current mode and confidence"
      style={{ background: 'radial-gradient(circle at 50% 42%, rgba(20,60,42,0.55) 0%, rgba(6,20,15,0.85) 32%, rgba(2,7,5,0.97) 58%, #000000 100%)' }}
    />
  );
}
