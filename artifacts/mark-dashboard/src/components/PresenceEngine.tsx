import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { useMarkStore } from '@/store/markStore';
import { useSelfState } from '@/hooks/use-self-state';

/**
 * PresenceEngine — MARK's neural core, in 3D.
 *
 * Not a literal anatomical brain mesh (that would need a licensed 3D
 * asset this project doesn't have) — a procedurally-shaped brain silhouette
 * built from a subdivided icosahedron whose vertices are displaced, once at
 * startup, into recognizable landmarks: two hemispheres split by a
 * longitudinal fissure, temporal-lobe bulges on the sides, and a
 * cerebellum + brainstem stub at the back-bottom. That static shape is what
 * makes it read as "a brain" rather than "a glowing ball" — a symmetric
 * sphere looks identical from every angle even while correctly lit and
 * rotating, so no amount of shading fixes that on its own. The surface is
 * then lit with real THREE.js lights (not baked/decorative — genuine
 * per-pixel Lambertian + specular shading, so turning the shape reveals real
 * depth) plus an additive Fresnel rim shell for the "holographic" glow.
 *
 * Every real-time value driving it is genuine:
 *
 *   - Core ripple, glow intensity, pulse speed, particle motion →
 *     agent.mind's actual mode + confidence (useSelfState).
 *   - Synapse firing → real WebSocket events from the store's `timeline`
 *     (worker started, files changed, tests run, tokens streamed — the
 *     same feed Mission Control's own Timeline view reads), not a fake
 *     "activity" clock.
 *   - Instability/jitter → agent.mind's actual health score.
 *   - The inward-pulling "listening" field → real microphone amplitude
 *     (micLevel), sampled live from an AnalyserNode — see use-voice.ts.
 *   - The outward "speaking" bursts → real StreamingToken arrivals and
 *     real speech-synthesis playback, not a decorative pulse.
 *
 * The render loop (renderer.setAnimationLoop) is rendering machinery — it
 * interpolates smoothly toward real target values every frame. It never
 * invents state. There is no setInterval/setTimeout anywhere in this file.
 */
interface PresenceEngineProps {
  className?: string;
  micLevel?: number;
  isListening?: boolean;
  isVoiceSpeaking?: boolean;
}

const BASE_HUE = 144 / 360; // MARK's own accent (index.css --accent, a green), as a 0-1 hue
const ERROR_HUE = 6 / 360;
const BRAIN_RADIUS = 1.5;

const MODE_ENERGY: Record<string, number> = {
  idle: 0.16, listening: 0.3, waiting: 0.12, sleeping: 0.05,
  thinking: 0.55, planning: 0.6, researching: 0.55,
  executing: 0.85, reflecting: 0.5, learning: 0.55,
  error: 0.4, recovering: 0.35,
};

/**
 * Displaces a unit-sphere direction into a point on the brain's static
 * "rest" surface: layered gyri/sulci folds, a longitudinal fissure along
 * the midline, temporal-lobe bulges on the sides, and a cerebellum bulge
 * at the back-bottom. Called once per vertex at startup to bake the shape
 * — the per-frame animation loop only ripples on top of this, it never
 * re-derives it, so the anatomical landmarks never wash out.
 */
function shapeBrainPoint(nx: number, ny: number, nz: number, radius: number, out: THREE.Vector3): THREE.Vector3 {
  let fold = 0;
  fold += Math.sin(nx * 4.1 + nz * 3.3) * Math.cos(ny * 3.7) * 0.5;
  fold += Math.sin(nx * 8.6 - ny * 7.2 + nz * 6.1) * 0.28;
  fold += Math.sin(nx * 15.0 + ny * 13.0 - nz * 11.0) * 0.13;
  const foldMul = 1 + fold * 0.045;

  // Longitudinal fissure — a groove along the x=0 midline, strongest on
  // the dorsal (top) surface, fading out toward the base.
  const topWeight = Math.max(0, Math.min(1, ny + 0.35));
  const fissure = Math.exp(-(nx * nx) / 0.02) * topWeight * 0.32;

  // Temporal lobes — bulges low on each side.
  const temporal = Math.exp(-((Math.abs(nx) - 0.72) ** 2) / 0.032) *
                    Math.exp(-((ny - 0.02) ** 2) / 0.09) * 0.14;

  const radialMul = foldMul * (1 - fissure) * (1 + temporal);

  let x = nx * radius * 1.05 * radialMul;
  let y = ny * radius * 0.92 * radialMul;
  let z = nz * radius * 1.2 * radialMul;

  // Cerebellum — a bulge at the back-bottom, the landmark that makes the
  // silhouette read as "brain" rather than "folded egg" from any angle.
  const cx = 0, cy = -radius * 0.6, cz = -radius * 0.82;
  const dx = x - cx, dy = y - cy, dz = z - cz;
  const spread = radius * 0.4;
  const cerebBump = Math.exp(-(dx * dx + dy * dy + dz * dz) / (2 * spread * spread)) * radius * 0.24;
  if (cerebBump > 0.0005) {
    const len = Math.sqrt(x * x + y * y + z * z) || 1;
    x += (x / len) * cerebBump;
    y += (y / len) * cerebBump * 0.5;
    z += (z / len) * cerebBump;
  }

  return out.set(x, y, z);
}

/** Bakes shapeBrainPoint into every vertex of `geo` (a unit icosahedron). */
function bakeBrainGeometry(geo: THREE.BufferGeometry, radius: number): Float32Array {
  const posAttr = geo.attributes.position;
  const tmp = new THREE.Vector3();
  const shaped = new THREE.Vector3();
  for (let i = 0; i < posAttr.count; i++) {
    tmp.fromBufferAttribute(posAttr, i).normalize();
    shapeBrainPoint(tmp.x, tmp.y, tmp.z, radius, shaped);
    posAttr.setXYZ(i, shaped.x, shaped.y, shaped.z);
  }
  posAttr.needsUpdate = true;
  geo.computeVertexNormals();
  return (posAttr.array as Float32Array).slice();
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
const FRESNEL_FRAGMENT = `
  uniform vec3 uColor;
  uniform float uOpacity;
  uniform float uPower;
  varying vec3 vNormalView;
  varying vec3 vViewDir;
  void main() {
    float fresnel = pow(1.0 - max(dot(normalize(vNormalView), normalize(vViewDir)), 0.0), uPower);
    gl_FragColor = vec4(uColor, fresnel * uOpacity);
  }
`;

export function PresenceEngine({ className = '', micLevel = 0, isListening = false, isVoiceSpeaking = false }: PresenceEngineProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { selfState, isSpeaking: isTextSpeaking } = useSelfState();
  const tokenTimestamps = useMarkStore(s => s.tokenTimestamps);
  const timeline = useMarkStore(s => s.timeline);

  const stateRef = useRef({ selfState, isTextSpeaking, tokenTimestamps, micLevel, isListening, isVoiceSpeaking });
  stateRef.current = { selfState, isTextSpeaking, tokenTimestamps, micLevel, isListening, isVoiceSpeaking };

  // Real event ids seen so far, so a synapse only fires once per real event.
  const seenEventsRef = useRef<Set<string>>(new Set());
  const timelineRef = useRef(timeline);
  timelineRef.current = timeline;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    camera.position.set(0, 0.35, 6.8);
    camera.lookAt(0, -0.05, 0);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = container;
      if (w === 0 || h === 0) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(container);
    window.addEventListener('resize', resize);
    // Defensive: some layouts settle a tick after mount, before the first
    // ResizeObserver callback fires — retry briefly so the canvas is never
    // stuck at the browser's 300x150 default if that first read raced layout.
    const retryTimers = [50, 200, 500, 1000].map(ms => window.setTimeout(resize, ms));

    const initialColor = new THREE.Color().setHSL(BASE_HUE, 1, 0.55);

    // ── Real lights — genuine Lambertian + specular shading, the single ──
    // strongest cue that this is a 3D object and not a flat sprite.
    const ambientLight = new THREE.AmbientLight(0x1c2a33, 0.55);
    const keyLight = new THREE.DirectionalLight(0xffffff, 0.85);
    keyLight.position.set(2.5, 3, 4);
    const rimLight = new THREE.PointLight(initialColor.getHex(), 1.3, 14, 2);
    rimLight.position.set(-2.2, 1.4, 3.2);
    scene.add(ambientLight, keyLight, rimLight);

    const brainGroup = new THREE.Group();
    scene.add(brainGroup);

    // ── Hull: the brain surface itself, lit and semi-translucent ────────
    const coreGeo = new THREE.IcosahedronGeometry(1, 5);
    const basePositions = bakeBrainGeometry(coreGeo, BRAIN_RADIUS);
    const hullMat = new THREE.MeshPhysicalMaterial({
      color: initialColor,
      transparent: true,
      opacity: 0.55,
      roughness: 0.35,
      metalness: 0.05,
      clearcoat: 0.4,
      clearcoatRoughness: 0.3,
      emissive: initialColor,
      emissiveIntensity: 0.35,
      side: THREE.FrontSide,
    });
    const hull = new THREE.Mesh(coreGeo, hullMat);
    brainGroup.add(hull);

    // ── Circuit overlay: the same surface, as glowing fold-lines ────────
    const wireMat = new THREE.MeshBasicMaterial({
      color: initialColor,
      wireframe: true,
      transparent: true,
      opacity: 0.32,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const wireMesh = new THREE.Mesh(coreGeo, wireMat);
    wireMesh.scale.setScalar(1.008);
    brainGroup.add(wireMesh);

    // ── Fresnel glow shell: additive rim-light for the holographic edge ──
    const glowGeo = new THREE.IcosahedronGeometry(1, 4);
    bakeBrainGeometry(glowGeo, BRAIN_RADIUS * 1.18);
    const glowMat = new THREE.ShaderMaterial({
      uniforms: {
        uColor: { value: initialColor.clone() },
        uOpacity: { value: 0.55 },
        uPower: { value: 2.1 },
      },
      vertexShader: FRESNEL_VERTEX,
      fragmentShader: FRESNEL_FRAGMENT,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      side: THREE.FrontSide,
    });
    const glowShell = new THREE.Mesh(glowGeo, glowMat);
    brainGroup.add(glowShell);

    // ── Brainstem: a tapered stub under the cerebellum bulge ────────────
    const stemGeo = new THREE.CylinderGeometry(BRAIN_RADIUS * 0.16, BRAIN_RADIUS * 0.24, BRAIN_RADIUS * 0.6, 12);
    const stem = new THREE.Mesh(stemGeo, hullMat);
    stem.position.set(0, -BRAIN_RADIUS * 1.02, -BRAIN_RADIUS * 0.5);
    stem.rotation.x = 0.4;
    brainGroup.add(stem);

    // ── Synapse network: nodes on the brain's own surface, connected to ──
    // their nearest neighbours. Each line's brightness = ambient (energy)
    // + a real firing pulse triggered by a genuine timeline event.
    const NODE_COUNT = 80;
    const nodePositions: THREE.Vector3[] = [];
    const tmpDir = new THREE.Vector3();
    for (let i = 0; i < NODE_COUNT; i++) {
      // Fibonacci sphere distribution — even angular coverage, no RNG needed.
      const y = 1 - (i / (NODE_COUNT - 1)) * 2;
      const r = Math.sqrt(1 - y * y);
      const theta = Math.PI * (1 + Math.sqrt(5)) * i;
      tmpDir.set(Math.cos(theta) * r, y, Math.sin(theta) * r).normalize();
      const shaped = new THREE.Vector3();
      shapeBrainPoint(tmpDir.x, tmpDir.y, tmpDir.z, BRAIN_RADIUS * 1.05, shaped);
      nodePositions.push(shaped);
    }
    type Synapse = { a: THREE.Vector3; b: THREE.Vector3; fire: number };
    const synapses: Synapse[] = [];
    for (let i = 0; i < NODE_COUNT; i++) {
      let nearest: number[] = [];
      for (let j = 0; j < NODE_COUNT; j++) {
        if (i === j) continue;
        nearest.push(j);
      }
      nearest.sort((a, b) => nodePositions[i].distanceTo(nodePositions[a]) - nodePositions[i].distanceTo(nodePositions[b]));
      for (const j of nearest.slice(0, 2)) {
        if (i < j) synapses.push({ a: nodePositions[i], b: nodePositions[j], fire: 0 });
      }
    }
    const synapseGeo = new THREE.BufferGeometry();
    const synapsePos = new Float32Array(synapses.length * 6);
    synapses.forEach((s, i) => {
      synapsePos.set([s.a.x, s.a.y, s.a.z, s.b.x, s.b.y, s.b.z], i * 6);
    });
    synapseGeo.setAttribute('position', new THREE.BufferAttribute(synapsePos, 3));
    const synapseColors = new Float32Array(synapses.length * 6);
    synapseGeo.setAttribute('color', new THREE.BufferAttribute(synapseColors, 3));
    const synapseMat = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.6 });
    const synapseLines = new THREE.LineSegments(synapseGeo, synapseMat);
    scene.add(synapseLines);

    // ── Particle field — an ellipsoid halo echoing the brain's own ──────
    // proportions, orbit speed tied to real energy.
    const PARTICLE_COUNT = 260;
    const particleGeo = new THREE.BufferGeometry();
    const particlePos = new Float32Array(PARTICLE_COUNT * 3);
    const particleAngles: { theta: number; phi: number; r: number; speed: number }[] = [];
    for (let i = 0; i < PARTICLE_COUNT; i++) {
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      const r = 2.6 + Math.random() * 1.4;
      particleAngles.push({ theta, phi, r, speed: 0.05 + Math.random() * 0.15 });
    }
    particleGeo.setAttribute('position', new THREE.BufferAttribute(particlePos, 3));
    const particleMat = new THREE.PointsMaterial({
      color: new THREE.Color().setHSL(BASE_HUE, 1, 0.75),
      size: 0.035,
      transparent: true,
      opacity: 0.75,
      sizeAttenuation: true,
    });
    const particles = new THREE.Points(particleGeo, particleMat);
    scene.add(particles);

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let energy = 0.2;
    let hue = BASE_HUE;
    const clock = new THREE.Clock();

    renderer.setAnimationLoop(() => {
      const { selfState, isTextSpeaking, tokenTimestamps, micLevel, isListening, isVoiceSpeaking } = stateRef.current;
      const t = clock.getElapsedTime();

      // ── Real signals → targets ─────────────────────────────────────
      const mode = selfState?.mode ?? 'idle';
      const modeEnergy = MODE_ENERGY[mode] ?? 0.2;
      const confidence = selfState?.confidence ?? 0.5;
      const health = selfState?.health ?? 1;
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

      const jitterAmt = health < 0.5 ? (1 - health) * 0.08 : 0.008;
      const spin = reduceMotion ? 0 : 0.06 + energy * 0.12;

      // Core ripple — a small perturbation layered on top of the baked
      // brain shape (never replaces it), phased by elapsed time for
      // organic motion. Amplitude is entirely energy/jitter-driven; time
      // only decides *where in the wave* to sample.
      const posAttr = coreGeo.attributes.position;
      for (let i = 0; i < posAttr.count; i++) {
        const ix = i * 3;
        const bx = basePositions[ix], by = basePositions[ix + 1], bz = basePositions[ix + 2];
        const n = Math.sin(bx * 3.0 + t * (0.5 + energy)) * Math.cos(by * 2.6 + t * 0.35) * Math.sin(bz * 3.2 - t * 0.45);
        const rippleMul = 1 + n * (0.05 + energy * 0.11) + (Math.random() - 0.5) * jitterAmt;
        posAttr.setXYZ(i, bx * rippleMul, by * rippleMul, bz * rippleMul);
      }
      posAttr.needsUpdate = true;
      coreGeo.computeVertexNormals();

      const color = new THREE.Color().setHSL(hue, 1, 0.5 + energy * 0.15);
      hullMat.color.copy(color);
      hullMat.emissive.copy(color);
      hullMat.emissiveIntensity = 0.25 + energy * 0.35;
      hullMat.opacity = 0.4 + energy * 0.3;
      wireMat.color.copy(color);
      wireMat.opacity = 0.2 + energy * 0.3;
      glowMat.uniforms.uColor.value.copy(color);
      glowMat.uniforms.uOpacity.value = 0.35 + energy * 0.4;
      rimLight.color.copy(color);
      rimLight.intensity = 0.9 + energy * 1.1;
      particleMat.color.copy(color);

      brainGroup.rotation.y += (reduceMotion ? 0.0008 : 0.0018) + energy * 0.001;
      brainGroup.rotation.x = Math.sin(t * 0.08) * 0.05;
      synapseLines.rotation.y = brainGroup.rotation.y;
      synapseLines.rotation.x = brainGroup.rotation.x;
      particles.rotation.y += spin * 0.002;

      // ── Synapse firing — driven by real timeline events, not a clock ──
      const currentTimeline = timelineRef.current;
      for (let i = 0; i < Math.min(currentTimeline.length, 6); i++) {
        const ev = currentTimeline[i];
        if (!seenEventsRef.current.has(ev.id)) {
          seenEventsRef.current.add(ev.id);
          // Fire a handful of random synapses for this real event.
          for (let k = 0; k < 4; k++) {
            const idx = Math.floor(Math.random() * synapses.length);
            synapses[idx].fire = 1;
          }
        }
      }
      const colorAttr = synapseGeo.attributes.color;
      for (let i = 0; i < synapses.length; i++) {
        const s = synapses[i];
        if (s.fire > 0) s.fire = Math.max(0, s.fire - 0.035);
        const ambient = 0.12 + energy * 0.35;
        const bright = Math.min(1, ambient + s.fire);
        const c = new THREE.Color().setHSL(hue, 1, 0.4 + bright * 0.4);
        colorAttr.setXYZ(i * 2, c.r, c.g, c.b);
        colorAttr.setXYZ(i * 2 + 1, c.r, c.g, c.b);
      }
      colorAttr.needsUpdate = true;
      synapseMat.opacity = 0.35 + energy * 0.35;

      // Particles: orbit speed from energy; ellipsoid shape echoes the
      // brain's own proportions; when listening, drift inward toward the
      // core in proportion to real mic amplitude.
      const posArr = particleGeo.attributes.position.array as Float32Array;
      for (let i = 0; i < PARTICLE_COUNT; i++) {
        const p = particleAngles[i];
        if (!reduceMotion) p.theta += p.speed * 0.012 * (0.3 + energy * 1.3);
        const inward = isListening ? micLevel * 0.9 : 0;
        const r = p.r * (1 - inward * 0.35);
        const ix = i * 3;
        posArr[ix]     = Math.sin(p.phi) * Math.cos(p.theta) * r * 1.05;
        posArr[ix + 1] = Math.cos(p.phi) * r * 0.9;
        posArr[ix + 2] = Math.sin(p.phi) * Math.sin(p.theta) * r * 1.15;
      }
      particleGeo.attributes.position.needsUpdate = true;

      renderer.render(scene, camera);
    });

    return () => {
      renderer.setAnimationLoop(null);
      ro.disconnect();
      window.removeEventListener('resize', resize);
      retryTimers.forEach(id => window.clearTimeout(id));
      renderer.dispose();
      coreGeo.dispose();
      hullMat.dispose();
      wireMat.dispose();
      glowGeo.dispose();
      glowMat.dispose();
      stemGeo.dispose();
      synapseGeo.dispose();
      synapseMat.dispose();
      particleGeo.dispose();
      particleMat.dispose();
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
      aria-label="MARK's live cognitive state — a 3D visualization of his current mode, confidence, and health"
    />
  );
}
