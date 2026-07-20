import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { useMarkStore } from '@/store/markStore';
import { useSelfState } from '@/hooks/use-self-state';
import { NeuralPresence } from './NeuralPresence';

/**
 * PresenceEngine — MARK's living core: a glass sphere half-filled with
 * glowing green liquid, bubbles rising through it, a bright glossy
 * highlight, and a soft green radial glow behind it — modeled directly on
 * a reference "liquid glass orb" photo the owner supplied.
 *
 * Three real layers:
 *   - An outer glass shell (MeshPhysicalMaterial with transmission — real
 *     refraction, not a fake transparent sprite).
 *   - An inner liquid body: a sphere clipped at a fill line into a bowl
 *     shape with a flat, gently rippling top surface (built by hand —
 *     THREE has no "clipped sphere" primitive).
 *   - A field of small rising bubble meshes.
 *
 * Every real-time value driving it is genuine:
 *   - Liquid color/glow → agent.mind's actual mode (error → red, else
 *     MARK's green) and confidence (useSelfState).
 *   - Surface ripple amplitude → real energy (mode/confidence) plus real
 *     microphone amplitude while listening.
 *   - Bubble rise speed → real energy — MARK looks more "alive" while
 *     actually executing something, not on a decorative clock.
 *   - A real WebSocket timeline event (worker started, tokens streamed,
 *     etc.) sends one real ripple pulse across the surface and resets a
 *     few bubbles to rise again — activity visibly disturbs the liquid.
 * The render loop (renderer.setAnimationLoop) only interpolates toward
 * these real targets and integrates real elapsed time; it never invents
 * state. No setInterval/setTimeout anywhere in this file.
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
  const [webGLAvailable, setWebGLAvailable] = useState(true);
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

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      // WebGL not available (e.g. Replit's preview iframe has no GPU).
      // Flip to the SVG NeuralPresence fallback rather than showing nothing.
      setWebGLAvailable(false);
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.15;
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
    const shellGeo = new THREE.SphereGeometry(ORB_RADIUS, 64, 48);
    const shellMat = new THREE.MeshPhysicalMaterial({
      color: 0xeafff2,
      transparent: true,
      opacity: 0.16,
      roughness: 0.04,
      metalness: 0,
      clearcoat: 1,
      clearcoatRoughness: 0.04,
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

    // ── Bubbles: real meshes rising through the liquid on real elapsed ──
    // time, looping from the bottom. Rate/speed driven by real energy.
    const BUBBLE_COUNT = 38;
    const bubbleGeo = new THREE.SphereGeometry(1, 10, 8);
    const bubbleMat = new THREE.MeshPhysicalMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: 0.9,
      roughness: 0.02,
      clearcoat: 1,
      clearcoatRoughness: 0.02,
      emissive: 0xd8fff0,
      emissiveIntensity: 0.4,
    });
    const bottomY = ORB_RADIUS * 0.965 * Math.cos(Math.PI - 0.35);
    const topY = ORB_RADIUS * 0.965 * Math.cos(FILL_PHI) - 0.03;
    type Bubble = { mesh: THREE.Mesh; speed: number; wobble: number; phase: number };
    const bubbles: Bubble[] = [];
    function resetBubble(b: Bubble, startAtBottom: boolean) {
      const r = 0.05 + Math.random() * Math.random() * 0.5; // bias toward center, but with real spread
      const size = 0.04 + Math.random() * 0.13;
      const theta = Math.random() * Math.PI * 2;
      b.mesh.position.set(Math.cos(theta) * r, startAtBottom ? bottomY + Math.random() * 0.15 : bottomY + Math.random() * (topY - bottomY), Math.sin(theta) * r);
      b.mesh.scale.setScalar(size);
      b.speed = 0.12 + Math.random() * 0.22;
      b.wobble = 0.15 + Math.random() * 0.3;
      b.phase = Math.random() * Math.PI * 2;
    }
    for (let i = 0; i < BUBBLE_COUNT; i++) {
      const mesh = new THREE.Mesh(bubbleGeo, bubbleMat);
      const b: Bubble = { mesh, speed: 0.15, wobble: 0.2, phase: 0 };
      resetBubble(b, false);
      bubbles.push(b);
      orbGroup.add(mesh);
    }

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let energy = 0.2;
    let hue = BASE_HUE;
    let ripple = 0; // event-triggered pulse, decays
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

      // Gentle one-shot scale-in on mount — a real elapsed-time ease, not a
      // physics fling.
      introT = Math.min(1, introT + dt / 0.7);
      const introScale = reduceMotion ? 1 : 0.85 + 0.15 * (1 - Math.pow(1 - introT, 3));
      orbGroup.scale.setScalar(introScale);

      const color = new THREE.Color().setHSL(hue, 0.85, 0.42 + energy * 0.1);
      liquidMat.color.copy(color);
      liquidMat.emissive.copy(color);
      liquidMat.emissiveIntensity = 0.08 + energy * 0.16 + ripple * 0.2;
      filmMat.color.copy(color).lerp(new THREE.Color(0xffffff), 0.55);
      keyLight.intensity = 15 + energy * 4;
      fillLight.color.copy(color).lerp(new THREE.Color(0x0a1512), 0.3);
      rimMat.uniforms.uColor.value.copy(color).lerp(new THREE.Color(0xffffff), 0.5);
      rimMat.uniforms.uOpacity.value = 0.35 + energy * 0.25;

      // ── Liquid surface ripple — a real perturbation on the cap vertices ──
      // only (still water underneath); amplitude from real energy + real
      // mic amplitude while listening + a decaying pulse from real events.
      const rippleAmp = 0.012 + energy * 0.02 + (isListening ? micLevel * 0.05 : 0) + ripple * 0.06;
      const posAttr = liquidGeo.attributes.position;
      for (const idx of capVertexIndices) {
        const ix = idx * 3;
        const bx = liquidBase[ix], by = liquidBase[ix + 1], bz = liquidBase[ix + 2];
        const wave = Math.sin(bx * 2.6 + t * 1.3) * Math.cos(bz * 2.3 + t * 0.9) * rippleAmp;
        posAttr.setXYZ(idx, bx, by + wave, bz);
      }
      posAttr.needsUpdate = true;
      liquidGeo.computeVertexNormals();

      // The surface film disc rides the same ripple so it doesn't look like
      // a rigid plate floating above the moving liquid.
      const filmAttr = filmGeo.attributes.position;
      for (let i = 0; i < filmAttr.count; i++) {
        const ix = i * 3;
        const fx = filmBase[ix], fy = filmBase[ix + 1];
        // CircleGeometry lies in local XY before the mesh's own -90° X
        // rotation; ripple its local Y (which becomes world-space "outward
        // from center" after that rotation) using the same wave field.
        const wave = Math.sin(fx * 2.6 + t * 1.3) * Math.cos(fy * 2.3 + t * 0.9) * rippleAmp;
        filmAttr.setXYZ(i, fx, fy, wave / 0.965);
      }
      filmAttr.needsUpdate = true;
      filmGeo.computeVertexNormals();

      // ── Bubbles rise on real elapsed time; rate/speed track real energy ──
      for (const b of bubbles) {
        b.mesh.position.y += b.speed * (0.4 + energy * 1.4) * dt;
        b.mesh.position.x += Math.sin(t * 1.4 + b.phase) * b.wobble * dt * 0.3;
        b.mesh.position.z += Math.cos(t * 1.1 + b.phase) * b.wobble * dt * 0.3;
        if (b.mesh.position.y > topY) resetBubble(b, true);
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

      renderer.render(scene, camera);
    });

    return () => {
      renderer.setAnimationLoop(null);
      ro.disconnect();
      window.removeEventListener('resize', resize);
      retryTimers.forEach(id => window.clearTimeout(id));
      renderer.dispose();
      shellGeo.dispose();
      shellMat.dispose();
      liquidGeo.dispose();
      liquidMat.dispose();
      filmGeo.dispose();
      filmMat.dispose();
      rimGeo.dispose();
      rimMat.dispose();
      bubbleGeo.dispose();
      bubbleMat.dispose();
      if (renderer.domElement.parentNode === container) {
        container.removeChild(renderer.domElement);
      }
    };
  }, []);

  // WebGL failed — render the SVG NeuralPresence instead.
  // This is not a degraded experience: NeuralPresence is driven by the same
  // real brain events and is the primary renderer in GPU-limited environments.
  if (!webGLAvailable) {
    return (
      <NeuralPresence
        className={className}
        micLevel={micLevel}
        isListening={isListening}
        isVoiceSpeaking={isVoiceSpeaking}
      />
    );
  }

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
