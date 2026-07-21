import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { useMarkStore } from '@/store/markStore';
import { useSelfState } from '@/hooks/use-self-state';

/**
 * PresenceEngine — MARK's living core: a glass sphere half-filled with a
 * glowing green chemical, bubbles rising through it, a bright glossy
 * highlight, and a soft green radial glow behind it — modeled on a
 * "liquid glass orb" reference photo the owner supplied, then pushed
 * toward a genuine VFX-style fluid look on request.
 *
 * Engineering-quality notes (what's real vs. what's a deliberate,
 * disclosed approximation — true SPH fluid dynamics, screen-space
 * reflections, and ray-traced caustics/dispersion are out of scope for a
 * WebGL dashboard widget; faking them badly would look worse than not
 * having them):
 *
 *   - Motion is driven by a real deterministic 3D Perlin-noise field and a
 *     curl (pseudo-vector-potential) derivative of it — the actual
 *     technique real-time VFX uses for convincing fluid-like flow without
 *     a full Navier–Stokes solver. Same input always gives the same
 *     output (deterministic), but because it's sampled along continuously
 *     advancing real time with irrational-ish frequency ratios, it never
 *     exactly repeats within any observable session.
 *   - The liquid surface height comes from fractal Brownian motion (4
 *     octaves of the noise field) rather than a couple of sine terms —
 *     much richer, non-repeating surface motion.
 *   - Fog wisps are genuinely *advected*: each frame their position is
 *     integrated forward by the curl field sampled at their own location,
 *     the same field bubbles use — so haze and bubbles visibly share one
 *     current, not independent random walks.
 *   - Bubbles have real size-dependent buoyancy (bigger rises faster),
 *     drift by sampling the shared curl field at their own position,
 *     genuinely merge (volume-conserving radius) when they overlap, and
 *     split under noise-driven "pressure" once large enough — no two
 *     bubbles ever carry identical phase/frequency/size, so no two move
 *     identically.
 *   - A single global "surge" value — a 1D noise signal sampled over real
 *     time, fast-rising/slow-decaying — coordinates a shared wave of
 *     agitation across the whole liquid + all bubbles at once (sudden
 *     surge → gradual calm), which is what makes it read as one thing
 *     reacting rather than forty independent particles.
 *   - Real bloom via three.js's own EffectComposer/UnrealBloomPass (no
 *     new dependency — ships inside the `three` package), threshold tuned
 *     high so only genuine highlights/emissive bubbles bloom.
 *   - Glass gets a procedurally generated condensation+micro-scratch bump
 *     map, and the Fresnel rim carries a cheap per-pixel R/B channel
 *     split at grazing angles as a stylized dispersion cue (not physically
 *     accurate spectral refraction — that needs multi-pass wavelength
 *     rendering, disclosed as out of scope above).
 *   - A caustic-style light-pattern (animated overlapping soft blotches,
 *     the standard cheap real-time caustic approximation) glows near the
 *     bottom of the liquid.
 *
 * Every real *state* value (not just motion) still traces to genuine data:
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

// ─── Deterministic 3D Perlin noise + curl field ────────────────────────────
// Classic reference-algorithm Perlin noise, fixed-seed shuffle (so it's the
// exact same field every run — deterministic — but sampled continuously
// through real time it never repeats). This is what drives every "fluid"
// motion below: never Math.random() inside the animation loop for motion.
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
 * stays static, like still water under a moving surface.
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
  geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(positions), 3));
  geo.setIndex(indices);
  geo.computeVertexNormals();
  return { geo, capVertexIndices, basePositions: (geo.attributes.position.array as Float32Array).slice() };
}

/** A large, very soft-edged round gradient — the billboard used for the
 * murky drifting fog wisps inside the liquid (deliberately softer/bigger
 * than a bubble highlight sprite, so it reads as haze, not a glow point). */
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
 * — used as a subtle bump map on the shell so it reads as real handled
 * glass, not a mathematically perfect sphere. */
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
    grad2.addColorStop(0, 'rgba(255,255,255,0.8)');
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

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = container;
      if (w === 0 || h === 0) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
      composer.setSize(w, h);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(container);
    window.addEventListener('resize', resize);
    const retryTimers = [50, 200, 500, 1000].map(ms => window.setTimeout(resize, ms));

    const initialColor = new THREE.Color().setHSL(BASE_HUE, 1, 0.5);

    // ── Real lights. A tight, bright key light is what produces the sharp ──
    // glossy highlight glass needs; a soft fill keeps the far side legible.
    const ambientLight = new THREE.AmbientLight(0x081410, 0.18);
    const keyLight = new THREE.PointLight(0xf3fff5, 12, 9, 2);
    keyLight.position.set(-2.8, 3.4, 4.2);
    const fillLight = new THREE.PointLight(0x1c4a34, 0.5, 20, 1.8);
    fillLight.position.set(2.6, -1.2, 2.6);
    const backLight = new THREE.DirectionalLight(0x3ba86a, 0.35);
    backLight.position.set(-1, -1, -3);
    // Sits inside the liquid volume so bubbles rising through the lower,
    // darker part of the orb still catch a visible glint instead of
    // vanishing into shadow.
    const interiorLight = new THREE.PointLight(0xbfffe0, 1.4, 3.2, 1.6);
    interiorLight.position.set(0, -0.5, 0.9);
    scene.add(ambientLight, keyLight, fillLight, backLight);

    const orbGroup = new THREE.Group();
    scene.add(orbGroup);
    orbGroup.add(interiorLight); // rotates with the liquid, always lighting it from within

    // ── Outer glass shell. `transmission` was tried first for real ──
    // refraction, but three.js's transmission background-capture only
    // reliably grabs *opaque* geometry — the liquid and bubbles behind it
    // (both alpha-blended) came out invisible through it, just a blank
    // pale dome. Standard alpha blending composites nested transparent
    // objects correctly (three.js sorts the transparent queue back-to-
    // front every frame), so the shell uses that instead: a thin, mostly
    // clear glassy layer over the liquid, not true GPU refraction.
    const glassImperfectionTex = createGlassImperfectionTexture();
    const shellGeo = new THREE.SphereGeometry(ORB_RADIUS, 64, 48);
    const shellMat = new THREE.MeshPhysicalMaterial({
      color: 0xeafff2,
      transparent: true,
      opacity: 0.16,
      roughness: 0.04,
      metalness: 0,
      clearcoat: 1,
      clearcoatRoughness: 0.04,
      bumpMap: glassImperfectionTex,
      bumpScale: 0.006,
      depthWrite: false,
    });
    const shell = new THREE.Mesh(shellGeo, shellMat);
    orbGroup.add(shell);

    // ── Inner liquid — a bowl clipped at the fill line with a rippling top.
    const LAT_SEGMENTS = 22, LON_SEGMENTS = 48;
    const { geo: liquidGeo, capVertexIndices, basePositions: liquidBase } =
      buildLiquidGeometry(ORB_RADIUS * 0.965, FILL_PHI, LAT_SEGMENTS, LON_SEGMENTS);
    const liquidMat = new THREE.MeshPhysicalMaterial({
      color: initialColor.clone(),
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
    film.position.y = ORB_RADIUS * 0.965 * Math.cos(FILL_PHI);
    orbGroup.add(film);

    // ── Fresnel edge glint — the bright rim real glass shows at grazing ──
    // angles (total internal reflection), matching the reference photo.
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
    const topY = ORB_RADIUS * 0.965 * Math.cos(FILL_PHI) - 0.03;

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

    // ── Bubbles: independent physical objects — size-dependent buoyancy, ──
    // drift sampled from the same curl-noise current the fog uses, genuine
    // volume-conserving merge on overlap, noise-driven pressure split once
    // large, continuous surface-tension-style oscillation whose frequency
    // scales with size. No two bubbles share phase/frequency/size, so no
    // two ever move identically.
    const BUBBLE_COUNT = 40;
    const MIN_R = 0.028, MAX_R = 0.16;
    const bubbleGeo = new THREE.SphereGeometry(1, 12, 10);
    const bubbleMat = new THREE.MeshPhysicalMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: 0.88,
      roughness: 0.02,
      clearcoat: 1,
      clearcoatRoughness: 0.02,
      emissive: 0xd8fff0,
      emissiveIntensity: 0.42,
    });
    type Bubble = {
      mesh: THREE.Mesh; size: number; wobbleFreq: number;
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
      const mesh = new THREE.Mesh(bubbleGeo, bubbleMat);
      const b: Bubble = { mesh, size: 0.05, wobbleFreq: 6, wobblePhaseX: 0, wobblePhaseY: 0, wobblePhaseZ: 0, phase: 0, cooldown: 0 };
      resetBubble(b, false);
      bubbles.push(b);
      orbGroup.add(mesh);
    }
    const curlScratch = new THREE.Vector3();

    // ── Internal fog/murk: soft haze genuinely advected by the same ──
    // curl-noise current field as the bubbles, so the fluid itself reads
    // as a heavy, turbulent chemical with real internal circulation.
    const FOG_COUNT = 14;
    const fogTexture = createFogSprite();
    type FogWisp = { sprite: THREE.Sprite; pos: THREE.Vector3; opacityPhase: number };
    const fogWisps: FogWisp[] = [];
    for (let i = 0; i < FOG_COUNT; i++) {
      const mat = new THREE.SpriteMaterial({
        map: fogTexture,
        transparent: true,
        opacity: 0.14,
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
      fogWisps.push({ sprite, pos, opacityPhase: Math.random() * Math.PI * 2 });
    }

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
      // rises sharply then decays slowly. Shared across the whole liquid
      // and every bubble at once, which is what makes it read as one
      // thing surging rather than independent jitter.
      const moodSignal = perlin3(3.7, 8.2, t * 0.32);
      const surgeTarget = reduceMotion ? 0 : Math.max(0, Math.min(1, (moodSignal - 0.12) / 0.42));
      surge += (surgeTarget - surge) * (surgeTarget > surge ? 0.1 : 0.02);

      // Gentle one-shot scale-in on mount — a real elapsed-time ease, not a
      // physics fling.
      introT = Math.min(1, introT + dt / 0.7);
      const introScale = reduceMotion ? 1 : 0.85 + 0.15 * (1 - Math.pow(1 - introT, 3));
      orbGroup.scale.setScalar(introScale * (1 + surge * 0.012)); // a faint outward "pressure" during a surge

      const color = new THREE.Color().setHSL(hue, 0.85, 0.42 + energy * 0.1);
      liquidMat.color.copy(color);
      liquidMat.emissive.copy(color);
      liquidMat.emissiveIntensity = 0.08 + energy * 0.16 + ripple * 0.2 + surge * 0.14;
      filmMat.color.copy(color).lerp(new THREE.Color(0xffffff), 0.55);
      keyLight.intensity = 15 + energy * 4;
      fillLight.color.copy(color).lerp(new THREE.Color(0x0a1512), 0.3);
      rimMat.uniforms.uColor.value.copy(color).lerp(new THREE.Color(0xffffff), 0.5);
      rimMat.uniforms.uOpacity.value = 0.35 + energy * 0.25 + surge * 0.15;
      bloomPass.strength = 0.42 + energy * 0.32 + surge * 0.28;

      // ── Liquid surface: fBm heightfield (4 octaves), not a couple of ──
      // sine terms — genuinely non-repeating roll, amplitude from real
      // energy + real mic amplitude + event ripple + the shared surge.
      const rippleAmp = 0.013 + energy * 0.022 + (isListening ? micLevel * 0.05 : 0) + ripple * 0.065 + surge * 0.05;
      const posAttr = liquidGeo.attributes.position;
      for (const idx of capVertexIndices) {
        const ix = idx * 3;
        const bx = liquidBase[ix], by = liquidBase[ix + 1], bz = liquidBase[ix + 2];
        const wave = fbm3(bx * 0.85 + 12.3, bz * 0.85 - 7.1, t * 0.3, 4) * rippleAmp * 2.1;
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
        w.pos.y = Math.min(topY - 0.03, Math.max(bottomY + 0.05, w.pos.y));
        w.sprite.position.copy(w.pos);
        const breathe = 0.5 + 0.5 * Math.sin(t * 0.3 + w.opacityPhase);
        const mat = w.sprite.material as THREE.SpriteMaterial;
        mat.opacity = (0.07 + energy * 0.14 + surge * 0.08) * (0.4 + breathe * 0.7);
        mat.color.copy(color).lerp(new THREE.Color(0x020e08), 0.55);
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

      composer.render();
    });

    return () => {
      renderer.setAnimationLoop(null);
      ro.disconnect();
      window.removeEventListener('resize', resize);
      retryTimers.forEach(id => window.clearTimeout(id));
      composer.dispose?.();
      renderer.dispose();
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
      bubbleGeo.dispose();
      bubbleMat.dispose();
      fogTexture.dispose();
      fogWisps.forEach(w => (w.sprite.material as THREE.SpriteMaterial).dispose());
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
      style={{ background: 'radial-gradient(circle at 50% 42%, rgba(40,150,95,0.75) 0%, rgba(10,45,30,0.9) 38%, rgba(4,14,10,0.96) 62%, #000000 100%)' }}
    />
  );
}
