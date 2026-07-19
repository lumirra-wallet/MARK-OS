import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { useMarkStore } from '@/store/markStore';
import { useSelfState } from '@/hooks/use-self-state';

/**
 * PresenceEngine — MARK's neural core, in 3D.
 *
 * Not a literal anatomical brain mesh (that would need a licensed 3D
 * asset this project doesn't have) — a stylized neural network: a
 * displaced core, a web of synapse connections, and an orbiting particle
 * field, all real-time-rendered with Three.js. What it shows is real:
 *
 *   - Core displacement, glow radius, pulse speed, particle motion →
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

const MODE_ENERGY: Record<string, number> = {
  idle: 0.16, listening: 0.3, waiting: 0.12, sleeping: 0.05,
  thinking: 0.55, planning: 0.6, researching: 0.55,
  executing: 0.85, reflecting: 0.5, learning: 0.55,
  error: 0.4, recovering: 0.35,
};

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
    camera.position.set(0, 0, 6.2);

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

    // ── Core: an icosphere, vertex-displaced by real energy/jitter ──────
    const coreGeo = new THREE.IcosahedronGeometry(1.5, 5);
    const basePositions = coreGeo.attributes.position.array.slice();
    const coreMat = new THREE.MeshBasicMaterial({
      color: new THREE.Color().setHSL(BASE_HUE, 1, 0.55),
      transparent: true,
      opacity: 0.85,
      wireframe: true,
    });
    const core = new THREE.Mesh(coreGeo, coreMat);
    scene.add(core);

    const glowMat = new THREE.MeshBasicMaterial({
      color: new THREE.Color().setHSL(BASE_HUE, 1, 0.55),
      transparent: true,
      opacity: 0.12,
    });
    const glow = new THREE.Mesh(new THREE.IcosahedronGeometry(1.85, 3), glowMat);
    scene.add(glow);

    // ── Synapse network: fixed points on a larger shell, connected to ───
    // their nearest neighbours. Each line's brightness = ambient (energy)
    // + a real firing pulse triggered by a genuine timeline event.
    const NODE_COUNT = 90;
    const nodePositions: THREE.Vector3[] = [];
    for (let i = 0; i < NODE_COUNT; i++) {
      // Fibonacci sphere distribution — even coverage, no RNG needed.
      const y = 1 - (i / (NODE_COUNT - 1)) * 2;
      const r = Math.sqrt(1 - y * y);
      const theta = Math.PI * (1 + Math.sqrt(5)) * i;
      const radius = 2.3 + (i % 5) * 0.12;
      nodePositions.push(new THREE.Vector3(Math.cos(theta) * r * radius, y * radius, Math.sin(theta) * r * radius));
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
    const synapseMat = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.55 });
    const synapseLines = new THREE.LineSegments(synapseGeo, synapseMat);
    scene.add(synapseLines);

    // ── Particle field — orbit speed tied to real energy ────────────────
    const PARTICLE_COUNT = 260;
    const particleGeo = new THREE.BufferGeometry();
    const particlePos = new Float32Array(PARTICLE_COUNT * 3);
    const particleAngles: { theta: number; phi: number; r: number; speed: number }[] = [];
    for (let i = 0; i < PARTICLE_COUNT; i++) {
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      const r = 2.8 + Math.random() * 1.6;
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

      // Core vertex displacement — real energy/jitter, phased by elapsed
      // time for organic motion (time is the animation clock, not a state
      // source: it only decides *where in the wave* to sample, the wave's
      // amplitude is entirely energy/jitter-driven).
      const posAttr = coreGeo.attributes.position;
      for (let i = 0; i < posAttr.count; i++) {
        const ix = i * 3;
        const bx = basePositions[ix], by = basePositions[ix + 1], bz = basePositions[ix + 2];
        const n = Math.sin(bx * 2.4 + t * (0.6 + energy)) * Math.cos(by * 2.1 + t * 0.4) * Math.sin(bz * 2.7 - t * 0.5);
        const displacement = 1 + n * (0.06 + energy * 0.16) + (Math.random() - 0.5) * jitterAmt;
        posAttr.setXYZ(i, bx * displacement, by * displacement, bz * displacement);
      }
      posAttr.needsUpdate = true;
      coreGeo.computeVertexNormals();

      const color = new THREE.Color().setHSL(hue, 1, 0.5 + energy * 0.15);
      coreMat.color.copy(color);
      glowMat.color.copy(color);
      glowMat.opacity = 0.08 + energy * 0.22;
      coreMat.opacity = 0.7 + energy * 0.25;
      particleMat.color.copy(color);

      core.rotation.y += (reduceMotion ? 0.0006 : 0.0015) + energy * 0.001;
      core.rotation.x += 0.0004;
      glow.rotation.y = -core.rotation.y * 0.6;
      synapseLines.rotation.y += spin * 0.003;
      synapseLines.rotation.x = Math.sin(t * 0.15) * 0.08;
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
      synapseMat.opacity = 0.3 + energy * 0.35;

      // Particles: orbit speed from energy; when listening, drift inward
      // toward the core in proportion to real mic amplitude.
      const posArr = particleGeo.attributes.position.array as Float32Array;
      for (let i = 0; i < PARTICLE_COUNT; i++) {
        const p = particleAngles[i];
        if (!reduceMotion) p.theta += p.speed * 0.012 * (0.3 + energy * 1.3);
        const inward = isListening ? micLevel * 0.9 : 0;
        const r = p.r * (1 - inward * 0.35);
        const ix = i * 3;
        posArr[ix]     = Math.sin(p.phi) * Math.cos(p.theta) * r;
        posArr[ix + 1] = Math.cos(p.phi) * r;
        posArr[ix + 2] = Math.sin(p.phi) * Math.sin(p.theta) * r;
      }
      particleGeo.attributes.position.needsUpdate = true;

      renderer.render(scene, camera);
    });

    return () => {
      renderer.setAnimationLoop(null);
      ro.disconnect();
      renderer.dispose();
      coreGeo.dispose();
      coreMat.dispose();
      glow.geometry.dispose();
      glowMat.dispose();
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
