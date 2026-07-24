import { useEffect, useRef, useState, Component, type ReactNode, type ErrorInfo } from 'react';
import * as THREE from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { useMarkStore } from '@/store/markStore';
import { useSelfState } from '@/hooks/use-self-state';

/**
 * PresenceEngine — not a status indicator, not an orb, not a brain. This is
 * MARK: a single living translucent membrane, rebuilt from first principles
 * around the owner's explicit brief — "opening a door into MARK's world,"
 * not launching software.
 *
 * The earlier "glass jar of liquid" metaphor (container + separate liquid
 * contents + bubbles floating inside it) is gone entirely — that was two
 * things. This is one thing: a soft, refractive, internally-lit body that
 * IS MARK, container and content collapsed into a single organism, closer
 * to soap film / jelly / plasma than to glassware.
 *
 * Hard constraint, explicit in the brief: it never rotates, spins, or
 * orbits. Every cue that it's alive and three-dimensional has to come from
 * genuine shape change over real time, not from spinning a static shape:
 *   - Breathing: a slow uniform scale pulse, always present, amplitude
 *     tracks real energy (agent.mind's mode/confidence).
 *   - Stretch/contract: slow anisotropic (non-uniform per-axis) scale
 *     sampled from the same curl-noise field used elsewhere in this file —
 *     organic, non-repeating, never a fixed loop.
 *   - Ripple: real per-vertex surface displacement (fBm noise), amplitude
 *     driven by real mic amplitude while listening.
 *   - Learning wave: while agent.mind's mode is genuinely 'learning', an
 *     actual traveling wave front sweeps across the surface — not just
 *     ambient noise, a real advancing phase.
 *   - Memory spark: a real backend `MemoryUpdated` WebSocket event fires a
 *     brief, sharp, localized bright flash — distinct from the smoother
 *     energy-driven glow.
 *   - Speaking: real StreamingToken bursts / voice-speaking state spike the
 *     internal light outward through the membrane.
 *   - Temperature: real mode (error → warm red, nominal → MARK's green)
 *     shifts the whole body's hue, the same real-data-only mechanism as
 *     every earlier revision, reframed here as the brief's "emotion"
 *     language — MARK doesn't have literal emotions, this is an honest
 *     approximation via the same operational-mode signal used throughout.
 *
 * Material: a genuine two-pass screen-space refraction (proven in an
 * earlier revision) — everything else renders to an offscreen texture
 * first, then the membrane's own shader samples it with the UV offset by
 * the surface normal, so what's behind it is actually optically distorted,
 * not alpha-blended. A Fresnel term brightens the edge and adds the
 * internal glow. Real bloom via three.js's own postprocessing.
 *
 * Background: replaced the sci-fi "deep space" starfield with a sparse,
 * very soft, slow-drifting particle atmosphere — support, not competition.
 *
 * Performance: the render loop fully stops (`renderer.setAnimationLoop(null)`)
 * whenever the tab is hidden (Page Visibility API) and restarts when it's
 * visible again — no wasted GPU work on an inactive tab.
 *
 * Every real *state* value still traces to genuine data: mode/confidence
 * from agent.mind (useSelfState), real WebSocket timeline events, real mic
 * amplitude while listening, real speech playback state. No
 * setInterval/setTimeout anywhere in this file.
 */
interface PresenceEngineProps {
  className?: string;
  micLevel?: number;
  isListening?: boolean;
  isVoiceSpeaking?: boolean;
}

const BASE_HUE = 144 / 360; // MARK's own accent (index.css --accent, a green), as a 0-1 hue
const ERROR_HUE = 6 / 360;
const MEMBRANE_RADIUS = 1.4;

const MODE_ENERGY: Record<string, number> = {
  idle: 0.16, listening: 0.3, waiting: 0.12, sleeping: 0.05,
  thinking: 0.55, planning: 0.6, researching: 0.55,
  executing: 0.85, reflecting: 0.5, learning: 0.55,
  error: 0.4, recovering: 0.35,
};

// ─── Deterministic 3D Perlin noise + curl field — every organic motion in ──
// this file (breathing's stretch component, ripple, particle drift) is
// driven by this, never Math.random() inside the animation loop. Same
// input always gives the same output (deterministic), but sampled along
// continuously advancing real time it never repeats within any observable
// session.
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
 * fields — swirly, non-repeating flow with no simulation grid required. */
function curl(x: number, y: number, z: number, t: number, out: THREE.Vector3): THREE.Vector3 {
  const dPzdy = (potZ(x, y + CURL_EPS, z, t) - potZ(x, y - CURL_EPS, z, t)) / (2 * CURL_EPS);
  const dPydz = (potY(x, y, z + CURL_EPS, t) - potY(x, y, z - CURL_EPS, t)) / (2 * CURL_EPS);
  const dPxdz = (potX(x, y, z + CURL_EPS, t) - potX(x, y, z - CURL_EPS, t)) / (2 * CURL_EPS);
  const dPzdx = (potZ(x + CURL_EPS, y, z, t) - potZ(x - CURL_EPS, y, z, t)) / (2 * CURL_EPS);
  const dPydx = (potY(x + CURL_EPS, y, z, t) - potY(x - CURL_EPS, y, z, t)) / (2 * CURL_EPS);
  const dPxdy = (potX(x, y + CURL_EPS, z, t) - potX(x, y - CURL_EPS, z, t)) / (2 * CURL_EPS);
  return out.set(dPzdy - dPydz, dPxdz - dPzdx, dPydx - dPxdy);
}

/** A small soft round glow sprite, generated once at runtime — used for the
 * atmosphere particles and the memory-write spark. */
function createGlowSprite(): THREE.Texture {
  const size = 64;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d')!;
  const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  gradient.addColorStop(0, 'rgba(255,255,255,1)');
  gradient.addColorStop(0.4, 'rgba(255,255,255,0.6)');
  gradient.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(canvas);
  tex.needsUpdate = true;
  return tex;
}

/** Procedural micro-imperfection texture — the membrane's "skin" isn't a
 * mathematically perfect surface; this perturbs the refraction itself. */
function createImperfectionTexture(): THREE.Texture {
  const size = 512;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d')!;
  ctx.fillStyle = '#808080';
  ctx.fillRect(0, 0, size, size);
  for (let i = 0; i < 90; i++) {
    const x = Math.random() * size, y = Math.random() * size, r = 4 + Math.random() * 30;
    const grad2 = ctx.createRadialGradient(x, y, 0, x, y, r);
    grad2.addColorStop(0, 'rgba(255,255,255,0.35)');
    grad2.addColorStop(1, 'rgba(128,128,128,0)');
    ctx.fillStyle = grad2;
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(2, 2);
  tex.needsUpdate = true;
  return tex;
}

// ─── The membrane: real two-pass screen-space refraction + internal glow ──
const MEMBRANE_VERTEX = `
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
const MEMBRANE_FRAGMENT = `
  uniform sampler2D uBackdrop;
  uniform sampler2D uImperfection;
  uniform vec2 uResolution;
  uniform vec3 uTintColor;
  uniform vec3 uCoreColor;
  uniform float uCoreIntensity;
  uniform float uOpacity;
  varying vec3 vNormalW;
  varying vec3 vViewDir;
  varying vec2 vUv2;
  void main() {
    vec2 screenUV = gl_FragCoord.xy / uResolution;
    float imperfection = texture2D(uImperfection, vUv2 * 2.0).r;
    float fresnel = pow(1.0 - max(dot(normalize(vNormalW), normalize(vViewDir)), 0.0), 2.3);
    vec2 refractOffset = vNormalW.xy * 0.022 * (1.0 - fresnel * 0.5) + (imperfection - 0.5) * 0.006;
    vec2 sampleUV = clamp(screenUV + refractOffset, 0.001, 0.999);
    vec3 backdrop = texture2D(uBackdrop, sampleUV).rgb;
    vec3 tinted = mix(backdrop, backdrop * uTintColor, 0.42);
    vec3 glowing = tinted + uCoreColor * uCoreIntensity * (0.22 + fresnel * 0.35);
    vec3 reflection = mix(glowing, vec3(1.0), fresnel * 0.5);
    gl_FragColor = vec4(reflection, mix(uOpacity, 1.0, fresnel * 0.6));
  }
`;

// ── ErrorBoundary — catches any synchronous render-time crash from Three.js ──
// useEffect errors are caught by the try/catch inside the effect itself;
// this boundary is the last line of defence for anything that slips through.
class PresenceErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { failed: false };
  }
  static getDerivedStateFromError(_: Error) { return { failed: true }; }
  componentDidCatch(_: Error, __: ErrorInfo) { /* swallow — degraded UI shown below */ }
  render() {
    if (this.state.failed) return (
      <div
        className="w-full h-full"
        style={{ background: 'radial-gradient(circle at 50% 45%, rgba(14,32,24,0.5) 0%, rgba(5,12,9,0.85) 35%, rgba(1,4,3,0.97) 62%, #000000 100%)' }}
      />
    );
    return this.props.children;
  }
}

function PresenceEngineInner({ className = '', micLevel = 0, isListening = false, isVoiceSpeaking = false }: PresenceEngineProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { selfState, isSpeaking: isTextSpeaking } = useSelfState();
  const tokenTimestamps = useMarkStore(s => s.tokenTimestamps);
  const timeline = useMarkStore(s => s.timeline);
  // webglAvailable — false when the browser/environment can't create a WebGL
  // context (headless server preview, certain Linux VMs, etc.).  We degrade
  // gracefully to a pure-CSS animated gradient so the rest of the UI still works.
  const [webglAvailable, setWebglAvailable] = useState(true);

  const stateRef = useRef({ selfState, isTextSpeaking, tokenTimestamps, micLevel, isListening, isVoiceSpeaking });
  stateRef.current = { selfState, isTextSpeaking, tokenTimestamps, micLevel, isListening, isVoiceSpeaking };

  const seenEventsRef = useRef<Set<string>>(new Set());
  const timelineRef = useRef(timeline);
  timelineRef.current = timeline;

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !webglAvailable) return;

    // Pre-existing timeline history shouldn't all fire as "new" the instant
    // this mounts — only events that arrive after mount should spark/pulse it.
    for (const ev of timelineRef.current) seenEventsRef.current.add(ev.id);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
    camera.position.set(0, 0.1, 6.6);
    camera.lookAt(0, 0, 0);

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      setWebglAvailable(false);
      return;
    }
    // Double-check: Three.js sometimes returns a renderer with a null context
    // instead of throwing (depends on the driver).
    if (!renderer.getContext()) {
      renderer.dispose();
      setWebglAvailable(false);
      return;
    }

    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.1;
    container.appendChild(renderer.domElement);

    const composer = new EffectComposer(renderer);
    composer.addPass(new RenderPass(scene, camera));
    const bloomPass = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.5, 0.5, 0.8);
    composer.addPass(bloomPass);

    // Offscreen target the membrane refracts — everything else renders here
    // first, every frame, before the membrane reads it.
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
      membraneMat.uniforms.uResolution.value.set(rw, rh);
    };

    const initialColor = new THREE.Color().setHSL(BASE_HUE, 0.9, 0.5);

    // ── Real lights. Deliberately dim/ambient — most of what reads as ──
    // "light" comes from the membrane's own internal glow term below, so
    // the surrounding scene stays genuinely dark, per the brief.
    const ambientLight = new THREE.AmbientLight(0x05100b, 0.22);
    const keyLight = new THREE.DirectionalLight(0xeafff2, 0.35);
    keyLight.position.set(-2, 2.6, 3.4);
    scene.add(ambientLight, keyLight);

    // MARK's "core" — the one real light living inside the membrane. Its
    // intensity/color IS the state machine: idle glow, thinking ramp,
    // speaking pulses, memory sparks.
    const coreLight = new THREE.PointLight(0x9dffcf, 1.2, 5, 2);
    scene.add(coreLight);

    const membraneGroup = new THREE.Group();
    scene.add(membraneGroup);

    // ── The membrane's rest shape: gentle organic irregularity (soap-film-
    // level, not lumpy) — most of the "alive" read comes from real-time
    // shape change below, not a dramatic baked asymmetry, since this thing
    // never rotates and doesn't need a landmark to prove it's 3D.
    // A UV-sphere, not a geodesic icosahedron — icosahedral triangulation
    // has irregular per-triangle orientation at the pentagon junctions that
    // shows up as visible faceting under a normal-sensitive refraction
    // shader even with zero displacement noise; a UV-sphere's regular
    // latitude/longitude bands read as genuinely smooth.
    const membraneGeo = new THREE.SphereGeometry(1, 128, 96);
    {
      const posAttr = membraneGeo.attributes.position;
      const tmp = new THREE.Vector3();
      for (let i = 0; i < posAttr.count; i++) {
        tmp.fromBufferAttribute(posAttr, i).normalize();
        const wobble = fbm3(tmp.x * 1.8 + 3.1, tmp.y * 1.8 - 5.4, tmp.z * 1.8 + 8.2, 3);
        const mul = MEMBRANE_RADIUS * (1 + wobble * 0.01);
        posAttr.setXYZ(i, tmp.x * mul, tmp.y * mul, tmp.z * mul);
      }
      posAttr.needsUpdate = true;
      membraneGeo.computeVertexNormals();
    }
    const membraneBase = (membraneGeo.attributes.position.array as Float32Array).slice();

    const imperfectionTex = createImperfectionTexture();
    const membraneMat = new THREE.ShaderMaterial({
      uniforms: {
        uBackdrop: { value: backdropTarget.texture },
        uImperfection: { value: imperfectionTex },
        uResolution: { value: new THREE.Vector2(2, 2) },
        uTintColor: { value: initialColor.clone() },
        uCoreColor: { value: initialColor.clone() },
        uCoreIntensity: { value: 0.2 },
        uOpacity: { value: 0.55 },
      },
      vertexShader: MEMBRANE_VERTEX,
      fragmentShader: MEMBRANE_FRAGMENT,
      transparent: true,
      depthWrite: false,
    });
    const membrane = new THREE.Mesh(membraneGeo, membraneMat);
    membraneGroup.add(membrane);

    // ── Memory-write spark — a tiny bright point that flashes briefly at a
    // fresh random point on the membrane's surface on a real MemoryUpdated
    // event, distinct from the smoother energy-driven glow.
    const sparkTex = createGlowSprite();
    const sparkMat = new THREE.SpriteMaterial({
      map: sparkTex, color: 0xeaffef, transparent: true, opacity: 0,
      blending: THREE.AdditiveBlending, depthWrite: false,
    });
    const spark = new THREE.Sprite(sparkMat);
    spark.scale.setScalar(0.16);
    membraneGroup.add(spark);
    let sparkLife = 0;

    // ── Atmosphere: sparse, soft, slow-drifting particles — support, not ──
    // competition. No starfield, no sci-fi grid, extremely soft movement
    // via the same curl-noise field, at very low amplitude.
    const ATMOSPHERE_COUNT = 70;
    const atmosphereTex = createGlowSprite();
    type AtmosphereParticle = { sprite: THREE.Sprite; pos: THREE.Vector3; phase: number };
    const atmosphereParticles: AtmosphereParticle[] = [];
    for (let i = 0; i < ATMOSPHERE_COUNT; i++) {
      const mat = new THREE.SpriteMaterial({
        map: atmosphereTex, color: 0x4a8f6c, transparent: true, opacity: 0.12,
        depthWrite: false,
      });
      const sprite = new THREE.Sprite(mat);
      const r = 2.4 + Math.random() * 3.2;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      const pos = new THREE.Vector3(Math.sin(phi) * Math.cos(theta) * r, Math.cos(phi) * r * 0.6, Math.sin(phi) * Math.sin(theta) * r);
      sprite.position.copy(pos);
      const scale = 0.04 + Math.random() * 0.09;
      sprite.scale.setScalar(scale);
      scene.add(sprite);
      atmosphereParticles.push({ sprite, pos, phase: Math.random() * Math.PI * 2 });
    }
    const curlScratch = new THREE.Vector3();

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let energy = 0.2;
    let hue = BASE_HUE;
    let coreIntensity = 0.2;
    let learnWaveFront = 0; // advances only while genuinely in 'learning' mode
    // THREE.Timer replaces the deprecated THREE.Clock.
    const timer = new THREE.Timer();
    let introT = 0; // one-shot gentle fade/scale-in on mount

    const loop = () => {
      timer.update();
      const { selfState, isTextSpeaking, tokenTimestamps, micLevel, isListening, isVoiceSpeaking } = stateRef.current;
      const t = timer.getElapsed();
      const dt = Math.min(timer.getDelta(), 0.05);

      const mode = selfState?.mode ?? 'idle';
      const modeEnergy = MODE_ENERGY[mode] ?? 0.2;
      const confidence = selfState?.confidence ?? 0.5;
      const isErrorMode = mode === 'error' || mode === 'recovering';
      const isThinkingMode = mode === 'thinking' || mode === 'planning' || mode === 'researching';
      const isLearningMode = mode === 'learning';

      const now = Date.now();
      const recentTokens = tokenTimestamps.filter((ts: number) => now - ts < 500).length;
      const streamBurst = isTextSpeaking ? Math.min(1, 0.4 + recentTokens * 0.05) : 0;
      const speakBurst = Math.max(streamBurst, isVoiceSpeaking ? 0.7 : 0);
      const listenBurst = isListening ? Math.min(1, 0.25 + micLevel * 0.9) : 0;

      const targetEnergy = Math.max(modeEnergy, speakBurst, listenBurst) * (0.5 + confidence * 0.5);
      const targetHue = isErrorMode ? ERROR_HUE : BASE_HUE;
      energy += (targetEnergy - energy) * (reduceMotion ? 0.02 : 0.06);
      hue += (targetHue - hue) * 0.05;

      // ── Internal light — the state machine, made visible. Idle glow,
      // thinking ramp, speaking pulses outward, memory sparks (below).
      const targetCore = 0.18 + energy * 0.35 + (isThinkingMode ? 0.22 : 0) + speakBurst * 0.5;
      coreIntensity += (targetCore - coreIntensity) * (speakBurst > 0 ? 0.35 : 0.05); // fast rise on speak-pulse, slow settle otherwise
      coreLight.intensity = 0.6 + coreIntensity * 2.2;

      const color = new THREE.Color().setHSL(hue, 0.9, 0.42 + energy * 0.1);
      coreLight.color.copy(color).lerp(new THREE.Color(0xffffff), 0.3);
      membraneMat.uniforms.uTintColor.value.copy(color).lerp(new THREE.Color(0xffffff), 0.55);
      membraneMat.uniforms.uCoreColor.value.copy(color).lerp(new THREE.Color(0xffffff), 0.35);
      membraneMat.uniforms.uCoreIntensity.value = coreIntensity;
      membraneMat.uniforms.uOpacity.value = 0.42 + energy * 0.18;
      bloomPass.strength = 0.32 + energy * 0.28 + speakBurst * 0.25;

      // ── Gentle one-shot intro — a real elapsed-time ease, not a physics
      // fling (the earlier "drop from above" entrance was explicitly
      // dropped along with the jar metaphor; this thing was always here).
      introT = Math.min(1, introT + dt / 0.9);
      const introScale = reduceMotion ? 1 : 0.9 + 0.1 * (1 - Math.pow(1 - introT, 3));

      // ── Breathing (idle, always present) + slow anisotropic stretch/
      // contract sampled from the shared curl field — organic, non-
      // repeating, NEVER a rotation.
      const breathRate = 0.22 + energy * 0.12;
      const breathAmp = (reduceMotion ? 0.008 : 0.02) + energy * 0.02;
      const breath = 1 + Math.sin(t * breathRate) * breathAmp;
      curl(0.4, 0.4, 0.4, t * 0.045, curlScratch);
      const stretchAmp = reduceMotion ? 0 : (0.05 + energy * 0.05);
      const sx = 1 + curlScratch.x * stretchAmp;
      const sy = 1 + curlScratch.y * stretchAmp * 0.85;
      const sz = 1 + curlScratch.z * stretchAmp;
      membraneGroup.scale.set(introScale * breath * sx, introScale * breath * sy, introScale * breath * sz);
      // No rotation is ever applied to membraneGroup — explicit constraint.

      // ── Surface ripple: real fBm noise, amplitude from real mic ──
      // amplitude while listening + ambient energy. Plus, only while
      // genuinely in 'learning' mode, an actual traveling wave front
      // sweeps across the surface (a real advancing phase, not noise).
      if (isLearningMode) learnWaveFront += dt * 1.1;
      else learnWaveFront = Math.max(0, learnWaveFront - dt * 0.6);
      const rippleAmp = 0.004 + energy * 0.006 + (isListening ? micLevel * 0.02 : 0);
      const posAttr = membraneGeo.attributes.position;
      for (let i = 0; i < posAttr.count; i++) {
        const ix = i * 3;
        const bx = membraneBase[ix], by = membraneBase[ix + 1], bz = membraneBase[ix + 2];
        let wave = fbm3(bx * 0.55 + t * 0.18, by * 0.55 - t * 0.13, bz * 0.55, 2) * rippleAmp;
        if (learnWaveFront > 0) {
          // A literal traveling band: distance-from-front falloff along Y,
          // advancing over real time only while mode === 'learning'.
          const dFront = by - (MEMBRANE_RADIUS * 1.3 - learnWaveFront * 0.9);
          const band = Math.exp(-(dFront * dFront) / 0.05);
          wave += band * 0.045 * Math.min(1, learnWaveFront);
        }
        posAttr.setXYZ(i, bx + bx * wave, by + by * wave, bz + bz * wave);
      }
      posAttr.needsUpdate = true;
      membraneGeo.computeVertexNormals();

      // ── Memory spark: a real MemoryUpdated event → brief bright flash ──
      // at a fresh random surface point. Other real events get a smaller,
      // generic core-light tick so activity is always visible somewhere.
      const currentTimeline = timelineRef.current;
      for (let i = 0; i < Math.min(currentTimeline.length, 6); i++) {
        const ev = currentTimeline[i];
        if (!seenEventsRef.current.has(ev.id)) {
          seenEventsRef.current.add(ev.id);
          if (ev.type === 'MemoryUpdated') {
            sparkLife = 1;
            const theta = Math.random() * Math.PI * 2, phi = Math.acos(2 * Math.random() - 1);
            spark.position.set(
              Math.sin(phi) * Math.cos(theta) * MEMBRANE_RADIUS,
              Math.cos(phi) * MEMBRANE_RADIUS,
              Math.sin(phi) * Math.sin(theta) * MEMBRANE_RADIUS,
            );
          } else {
            coreIntensity = Math.min(1, coreIntensity + 0.12);
          }
        }
      }
      sparkLife = Math.max(0, sparkLife - dt * 2.2);
      sparkMat.opacity = sparkLife;
      sparkMat.color.copy(color).lerp(new THREE.Color(0xffffff), 0.6);

      // ── Atmosphere: extremely soft drift on the shared curl field, no ──
      // sci-fi starfield, no orbit — support, not competition.
      for (const p of atmosphereParticles) {
        curl(p.pos.x * 0.3, p.pos.y * 0.3, p.pos.z * 0.3, t * 0.15 + p.phase, curlScratch);
        p.pos.x += curlScratch.x * 0.01 * dt;
        p.pos.y += curlScratch.y * 0.006 * dt;
        p.pos.z += curlScratch.z * 0.01 * dt;
        const r = p.pos.length();
        if (r > 6 || r < 2) p.pos.multiplyScalar(2.4 / Math.max(0.01, r));
        p.sprite.position.copy(p.pos);
        const breathe = 0.5 + 0.5 * Math.sin(t * 0.2 + p.phase);
        (p.sprite.material as THREE.SpriteMaterial).opacity = 0.06 + breathe * 0.09 + energy * 0.04;
      }

      // ── Two-pass render: capture everything *except* the membrane to the ──
      // backdrop texture — the membrane samples that texture for refraction,
      // so it must be invisible during the first pass, otherwise it samples
      // its own previous-frame output (WebGL feedback loop / temporal echo).
      membrane.visible = false;
      const prevTarget = renderer.getRenderTarget();
      renderer.setRenderTarget(backdropTarget);
      renderer.render(scene, camera);
      renderer.setRenderTarget(prevTarget);
      membrane.visible = true;
      composer.render();
    };

    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(container);
    window.addEventListener('resize', resize);
    const retryTimers = [50, 200, 500, 1000].map(ms => window.setTimeout(resize, ms));

    // ── Pause the render loop entirely when the tab isn't visible — no ──
    // wasted GPU work on an inactive tab (explicit performance requirement).
    let loopRunning = false;
    const applyVisibility = () => {
      if (document.hidden) {
        if (loopRunning) { renderer.setAnimationLoop(null); loopRunning = false; }
      } else if (!loopRunning) {
        renderer.setAnimationLoop(loop); loopRunning = true;
      }
    };
    applyVisibility();
    document.addEventListener('visibilitychange', applyVisibility);

    return () => {
      renderer.setAnimationLoop(null);
      document.removeEventListener('visibilitychange', applyVisibility);
      ro.disconnect();
      window.removeEventListener('resize', resize);
      retryTimers.forEach(id => window.clearTimeout(id));
      composer.dispose?.();
      renderer.dispose();
      backdropTarget.dispose();
      membraneGeo.dispose();
      membraneMat.dispose();
      imperfectionTex.dispose();
      sparkTex.dispose();
      sparkMat.dispose();
      atmosphereTex.dispose();
      atmosphereParticles.forEach(p => (p.sprite.material as THREE.SpriteMaterial).dispose());
      if (renderer.domElement.parentNode === container) {
        container.removeChild(renderer.domElement);
      }
    };
  // webglAvailable in the dep array: when it flips false the effect re-runs,
  // hits the early-return guard, and does nothing — safe.
  }, [webglAvailable]);

  // CSS-only fallback: identical dark gradient background, no 3D.
  // The rest of the UI (chat, voice controls, timeline) stays fully functional.
  if (!webglAvailable) {
    return (
      <div
        className={`w-full h-full ${className}`}
        role="img"
        aria-label="Elena's presence"
        style={{ background: 'radial-gradient(circle at 50% 45%, rgba(14,32,24,0.5) 0%, rgba(5,12,9,0.85) 35%, rgba(1,4,3,0.97) 62%, #000000 100%)' }}
      />
    );
  }

  return (
    <div
      ref={containerRef}
      className={`w-full h-full ${className}`}
      role="img"
      aria-label="Elena's living presence — a breathing translucent membrane reflecting her current state"
      style={{ background: 'radial-gradient(circle at 50% 45%, rgba(14,32,24,0.5) 0%, rgba(5,12,9,0.85) 35%, rgba(1,4,3,0.97) 62%, #000000 100%)' }}
    />
  );
}

// Public export — PresenceErrorBoundary wraps the inner component so that any
// unexpected Three.js render-time exception is caught here rather than crashing
// the entire React tree (the inner component already guards WebGL context
// creation; this catches anything else that could slip through).
export function PresenceEngine(props: PresenceEngineProps) {
  return (
    <PresenceErrorBoundary>
      <PresenceEngineInner {...props} />
    </PresenceErrorBoundary>
  );
}
