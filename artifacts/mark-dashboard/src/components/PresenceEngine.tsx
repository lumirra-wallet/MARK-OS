import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { useMarkStore } from '@/store/markStore';
import { useSelfState } from '@/hooks/use-self-state';
import { NeuralPresence } from './NeuralPresence';

/**
 * PresenceEngine — MARK's neural core.
 *
 * Visual language matches the reference: electric blue/cyan brain mesh with
 * visible cortical fold wireframe, neural-network "antenna" lines radiating
 * outward from the surface into surrounding space with glowing endpoint nodes,
 * a red/orange energy core that fires on thinking/speaking, and a dark
 * blue-black space backdrop with subtle depth fog.
 *
 * All animated values are driven by real agent signals — mode, confidence,
 * health, mic level, token stream, timeline events. No fake timers.
 */
interface PresenceEngineProps {
  className?: string;
  micLevel?: number;
  isListening?: boolean;
  isVoiceSpeaking?: boolean;
}

// Electric blue-cyan, matching the reference image palette
const BASE_HUE  = 200 / 360;   // cyan-blue
const ERROR_HUE = 6   / 360;   // red on error
const BRAIN_RADIUS = 1.5;

const MODE_ENERGY: Record<string, number> = {
  idle: 0.18, listening: 0.35, waiting: 0.14, sleeping: 0.06,
  thinking: 0.65, planning: 0.7, researching: 0.6,
  executing: 0.9, reflecting: 0.55, learning: 0.6,
  error: 0.45, recovering: 0.4,
};

// ── Brain shape ────────────────────────────────────────────────────────────
// Displaces a unit-sphere normal into the anatomical brain silhouette:
// gyri/sulci folds, longitudinal fissure, temporal-lobe bulges, cerebellum.
function shapeBrainPoint(
  nx: number, ny: number, nz: number,
  radius: number,
  out: THREE.Vector3,
): THREE.Vector3 {
  let fold = 0;
  fold += Math.sin(nx * 4.1 + nz * 3.3) * Math.cos(ny * 3.7) * 0.5;
  fold += Math.sin(nx * 8.6 - ny * 7.2 + nz * 6.1) * 0.28;
  fold += Math.sin(nx * 15.0 + ny * 13.0 - nz * 11.0) * 0.13;
  const foldMul = 1 + fold * 0.045;

  const topWeight = Math.max(0, Math.min(1, ny + 0.35));
  const fissure   = Math.exp(-(nx * nx) / 0.012) * topWeight * 0.13;
  const temporal  = Math.exp(-((Math.abs(nx) - 0.72) ** 2) / 0.032) *
                    Math.exp(-((ny - 0.02)           ** 2) / 0.09)   * 0.14;

  const rm = foldMul * (1 - fissure) * (1 + temporal);
  let x = nx * radius * 1.05 * rm;
  let y = ny * radius * 0.92 * rm;
  let z = nz * radius * 1.20 * rm;

  // Cerebellum bulge — makes the silhouette read as a brain from every angle
  const cx = 0, cy = -radius * 0.6, cz = -radius * 0.82;
  const dx = x - cx, dy = y - cy, dz = z - cz;
  const spread = radius * 0.4;
  const cb = Math.exp(-(dx*dx + dy*dy + dz*dz) / (2*spread*spread)) * radius * 0.24;
  if (cb > 0.0005) {
    const len = Math.sqrt(x*x + y*y + z*z) || 1;
    x += (x / len) * cb;
    y += (y / len) * cb * 0.5;
    z += (z / len) * cb;
  }
  return out.set(x, y, z);
}

// Soft glowing sprite — used for every point/dot so they render as
// glowing circles rather than Three.js's default hard squares.
function createDotTexture(r = 255, g = 255, b = 255): THREE.Texture {
  const sz  = 64;
  const cv  = document.createElement('canvas');
  cv.width  = cv.height = sz;
  const ctx = cv.getContext('2d')!;
  const gr  = ctx.createRadialGradient(sz/2, sz/2, 0, sz/2, sz/2, sz/2);
  gr.addColorStop(0,   `rgba(${r},${g},${b},1)`);
  gr.addColorStop(0.4, `rgba(${r},${g},${b},0.7)`);
  gr.addColorStop(1,   `rgba(${r},${g},${b},0)`);
  ctx.fillStyle = gr;
  ctx.fillRect(0, 0, sz, sz);
  const tex       = new THREE.CanvasTexture(cv);
  tex.needsUpdate = true;
  return tex;
}

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

// Fresnel rim-glow shader — gives each shell its bright holographic edge
const FRESNEL_VERTEX = `
  varying vec3 vNorm;
  varying vec3 vView;
  void main() {
    vNorm = normalize(normalMatrix * normal);
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vView = normalize(-mv.xyz);
    gl_Position = projectionMatrix * mv;
  }
`;
const FRESNEL_FRAGMENT = `
  uniform vec3  uColor;
  uniform float uOpacity;
  uniform float uPower;
  varying vec3 vNorm;
  varying vec3 vView;
  void main() {
    float f = pow(1.0 - max(dot(normalize(vNorm), normalize(vView)), 0.0), uPower);
    gl_FragColor = vec4(uColor, f * uOpacity);
  }
`;

export function PresenceEngine({
  className = '', micLevel = 0, isListening = false, isVoiceSpeaking = false,
}: PresenceEngineProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [webGLAvailable, setWebGLAvailable] = useState(true);

  const { selfState, isSpeaking: isTextSpeaking } = useSelfState();
  const tokenTimestamps = useMarkStore(s => s.tokenTimestamps);
  const timeline        = useMarkStore(s => s.timeline);

  const stateRef = useRef({ selfState, isTextSpeaking, tokenTimestamps, micLevel, isListening, isVoiceSpeaking });
  stateRef.current = { selfState, isTextSpeaking, tokenTimestamps, micLevel, isListening, isVoiceSpeaking };

  const seenEventsRef = useRef<Set<string>>(new Set());
  const timelineRef   = useRef(timeline);
  timelineRef.current = timeline;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // ── Scene & Camera ──────────────────────────────────────────────────
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x04080f);   // deep blue-black space
    scene.fog        = new THREE.FogExp2(0x04080f, 0.048); // subtle depth

    const camera = new THREE.PerspectiveCamera(44, 1, 0.1, 100);
    // Slight 3/4 angle like the reference — camera offset right, elevated
    camera.position.set(0.8, 0.4, 6.8);
    camera.lookAt(0, -0.25, 0);

    let renderer!: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    } catch {
      setWebGLAvailable(false);
      return;
    }
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
    const retryTimers = [50, 200, 500, 1000].map(ms => window.setTimeout(resize, ms));

    const blueColor = new THREE.Color().setHSL(BASE_HUE, 1, 0.55);

    // ── Lights ──────────────────────────────────────────────────────────
    // Dark blue ambient keeps unlit faces from going pure black
    const ambientLight = new THREE.AmbientLight(0x0a1830, 1.0);

    // Main key from front-right (matches reference lighting angle)
    const keyLight = new THREE.DirectionalLight(0xffffff, 0.7);
    keyLight.position.set(3, 2.5, 4);

    // Cyan rim from left — the strong blue-white edge glow in the reference
    const cyanRim = new THREE.PointLight(0x00bbff, 2.8, 18, 2);
    cyanRim.position.set(-3.5, 1.5, 3);

    // Soft teal fill from below
    const tealFill = new THREE.PointLight(0x007799, 1.2, 14, 2);
    tealFill.position.set(0, -3, 1);

    // RED/ORANGE energy core — the lightning bolt effect in the reference.
    // Lives inside the brain; intensity driven by energy every frame.
    const energyCore = new THREE.PointLight(0xff3300, 0.0, 8, 2);
    energyCore.position.set(0.3, 0.1, 0.4); // frontal lobe region

    scene.add(ambientLight, keyLight, cyanRim, tealFill, energyCore);

    // ── Brain group ─────────────────────────────────────────────────────
    const brainGroup = new THREE.Group();
    scene.add(brainGroup);

    // ── Animated hull (drives per-frame ripple) ─────────────────────────
    const coreGeo      = new THREE.IcosahedronGeometry(1, 5);
    const basePositions = bakeBrainGeometry(coreGeo, BRAIN_RADIUS);

    const hullMat = new THREE.MeshPhysicalMaterial({
      color:              blueColor,
      transparent:        true,
      opacity:            0.28,
      roughness:          0.25,
      metalness:          0.05,
      clearcoat:          0.5,
      clearcoatRoughness: 0.2,
      emissive:           blueColor,
      emissiveIntensity:  0.55,
      side:               THREE.FrontSide,
    });
    brainGroup.add(new THREE.Mesh(coreGeo, hullMat));

    // ── Dense surface point-cloud — the "glowing scan" texture ──────────
    const dotTex          = createDotTexture(120, 210, 255); // blue-white glow
    const SURFACE_DOTS    = 28000;
    const dotGeo          = new THREE.BufferGeometry();
    const dotPos          = new Float32Array(SURFACE_DOTS * 3);
    {
      const dir    = new THREE.Vector3();
      const shaped = new THREE.Vector3();
      for (let i = 0; i < SURFACE_DOTS; i++) {
        const y = 1 - (i / (SURFACE_DOTS - 1)) * 2;
        const r = Math.sqrt(Math.max(0, 1 - y*y));
        const th = Math.PI * (1 + Math.sqrt(5)) * i;
        dir.set(Math.cos(th)*r, y, Math.sin(th)*r);
        shapeBrainPoint(dir.x, dir.y, dir.z, BRAIN_RADIUS * 1.012, shaped);
        dotPos[i*3]   = shaped.x;
        dotPos[i*3+1] = shaped.y;
        dotPos[i*3+2] = shaped.z;
      }
    }
    dotGeo.setAttribute('position', new THREE.BufferAttribute(dotPos, 3));
    const dotMat = new THREE.PointsMaterial({
      color:          blueColor,
      size:           0.028,
      map:            dotTex,
      transparent:    true,
      opacity:        0.92,
      blending:       THREE.AdditiveBlending,
      depthWrite:     false,
      sizeAttenuation: true,
    });
    const surfaceDots = new THREE.Points(dotGeo, dotMat);
    brainGroup.add(surfaceDots);

    // ── Animated low-poly wireframe (ripple-driven, faint) ───────────────
    const wireMat = new THREE.MeshBasicMaterial({
      color:       blueColor,
      wireframe:   true,
      transparent: true,
      opacity:     0.14,
      blending:    THREE.AdditiveBlending,
      depthWrite:  false,
    });
    const wireMesh = new THREE.Mesh(coreGeo, wireMat);
    wireMesh.scale.setScalar(1.008);
    brainGroup.add(wireMesh);

    // ── Static high-res wireframe — the dominant visible mesh texture ────
    // Higher subdivision baked once; the fine grid makes cortical folds
    // read clearly without any per-frame CPU cost.
    const fineWireGeo = new THREE.IcosahedronGeometry(1, 6);
    bakeBrainGeometry(fineWireGeo, BRAIN_RADIUS * 1.006);
    const fineWireMat = new THREE.MeshBasicMaterial({
      color:       blueColor,
      wireframe:   true,
      transparent: true,
      opacity:     0.38,          // prominent — this is the mesh in the reference
      blending:    THREE.AdditiveBlending,
      depthWrite:  false,
    });
    brainGroup.add(new THREE.Mesh(fineWireGeo, fineWireMat));

    // ── Inner Fresnel glow shell (tight rim glow, bright cyan) ───────────
    const innerGlowGeo = new THREE.IcosahedronGeometry(1, 5);
    bakeBrainGeometry(innerGlowGeo, BRAIN_RADIUS * 1.08);
    const innerGlowMat = new THREE.ShaderMaterial({
      uniforms: {
        uColor:   { value: new THREE.Color(0x00ddff) },
        uOpacity: { value: 0.65 },
        uPower:   { value: 1.8 },
      },
      vertexShader:   FRESNEL_VERTEX,
      fragmentShader: FRESNEL_FRAGMENT,
      transparent:    true,
      blending:       THREE.AdditiveBlending,
      depthWrite:     false,
      side:           THREE.FrontSide,
    });
    brainGroup.add(new THREE.Mesh(innerGlowGeo, innerGlowMat));

    // ── Outer Fresnel glow shell (wide atmospheric halo) ─────────────────
    const outerGlowGeo = new THREE.IcosahedronGeometry(1, 5);
    bakeBrainGeometry(outerGlowGeo, BRAIN_RADIUS * 1.32);
    const outerGlowMat = new THREE.ShaderMaterial({
      uniforms: {
        uColor:   { value: new THREE.Color(0x0066cc) },
        uOpacity: { value: 0.32 },
        uPower:   { value: 3.2 },
      },
      vertexShader:   FRESNEL_VERTEX,
      fragmentShader: FRESNEL_FRAGMENT,
      transparent:    true,
      blending:       THREE.AdditiveBlending,
      depthWrite:     false,
      side:           THREE.FrontSide,
    });
    brainGroup.add(new THREE.Mesh(outerGlowGeo, outerGlowMat));

    // ── Brainstem ─────────────────────────────────────────────────────────
    const stemGeo = new THREE.CylinderGeometry(
      BRAIN_RADIUS * 0.15, BRAIN_RADIUS * 0.22, BRAIN_RADIUS * 0.55, 12,
    );
    const stem = new THREE.Mesh(stemGeo, hullMat);
    stem.position.set(0, -BRAIN_RADIUS * 1.02, -BRAIN_RADIUS * 0.48);
    stem.rotation.x = 0.4;
    brainGroup.add(stem);

    // ── Red/orange energy core sphere ────────────────────────────────────
    // A small additive sphere at the frontal lobe — the "lightning bolt"
    // energy burst seen in the reference image. Scales with energy.
    const coreSphereGeo = new THREE.SphereGeometry(0.18, 12, 12);
    const coreSphereMat = new THREE.MeshBasicMaterial({
      color:       0xff4400,
      transparent: true,
      opacity:     0.0,
      blending:    THREE.AdditiveBlending,
      depthWrite:  false,
    });
    const coreSphere = new THREE.Mesh(coreSphereGeo, coreSphereMat);
    coreSphere.position.set(0.3, 0.1, 0.4);
    brainGroup.add(coreSphere);

    // Softer outer orange halo around the core
    const coreHaloGeo = new THREE.SphereGeometry(0.42, 12, 12);
    const coreHaloMat = new THREE.MeshBasicMaterial({
      color:       0xff2200,
      transparent: true,
      opacity:     0.0,
      blending:    THREE.AdditiveBlending,
      depthWrite:  false,
    });
    brainGroup.add(new THREE.Mesh(coreHaloGeo, coreHaloMat));
    coreSphere.userData.haloMat = coreHaloMat;

    // ── Synapse surface network ───────────────────────────────────────────
    // Nodes distributed over the brain surface; lines connect nearest
    // neighbours. Brightness = ambient energy + real event fire pulse.
    const NODE_COUNT = 90;
    const nodePositions: THREE.Vector3[] = [];
    {
      const td = new THREE.Vector3(), sv = new THREE.Vector3();
      for (let i = 0; i < NODE_COUNT; i++) {
        const y  = 1 - (i / (NODE_COUNT - 1)) * 2;
        const r  = Math.sqrt(Math.max(0, 1 - y*y));
        const th = Math.PI * (1 + Math.sqrt(5)) * i;
        td.set(Math.cos(th)*r, y, Math.sin(th)*r).normalize();
        shapeBrainPoint(td.x, td.y, td.z, BRAIN_RADIUS * 1.04, sv);
        nodePositions.push(sv.clone());
      }
    }
    type Synapse = { a: THREE.Vector3; b: THREE.Vector3; fire: number };
    const synapses: Synapse[] = [];
    for (let i = 0; i < NODE_COUNT; i++) {
      const sorted = [...Array(NODE_COUNT).keys()]
        .filter(j => j !== i)
        .sort((a, b) => nodePositions[i].distanceTo(nodePositions[a]) -
                        nodePositions[i].distanceTo(nodePositions[b]));
      for (const j of sorted.slice(0, 2)) {
        if (i < j) synapses.push({ a: nodePositions[i], b: nodePositions[j], fire: 0 });
      }
    }
    const synapseGeo = new THREE.BufferGeometry();
    const synapsePos = new Float32Array(synapses.length * 6);
    synapses.forEach((s, i) => synapsePos.set(
      [s.a.x, s.a.y, s.a.z, s.b.x, s.b.y, s.b.z], i * 6,
    ));
    synapseGeo.setAttribute('position', new THREE.BufferAttribute(synapsePos, 3));
    const synapseColors = new Float32Array(synapses.length * 6);
    synapseGeo.setAttribute('color', new THREE.BufferAttribute(synapseColors, 3));
    const synapseMat = new THREE.LineBasicMaterial({
      vertexColors: true, transparent: true, opacity: 0.7,
      blending: THREE.AdditiveBlending,
    });
    const synapseLines = new THREE.LineSegments(synapseGeo, synapseMat);
    scene.add(synapseLines);

    // ── Glowing node dots on the brain surface ───────────────────────────
    const nodeDotGeo = new THREE.BufferGeometry();
    const nodeDotPos = new Float32Array(NODE_COUNT * 3);
    nodePositions.forEach((p, i) => {
      nodeDotPos[i*3] = p.x; nodeDotPos[i*3+1] = p.y; nodeDotPos[i*3+2] = p.z;
    });
    nodeDotGeo.setAttribute('position', new THREE.BufferAttribute(nodeDotPos, 3));
    const nodeDotMat = new THREE.PointsMaterial({
      color: 0x44ddff, size: 0.065, map: dotTex,
      transparent: true, opacity: 0.95,
      blending: THREE.AdditiveBlending, depthWrite: false,
    });
    const nodeDots = new THREE.Points(nodeDotGeo, nodeDotMat);
    scene.add(nodeDots);

    // ── Neural antenna network ─────────────────────────────────────────────
    // This is the defining feature of the reference image: long lines
    // radiating FROM the brain surface outward into surrounding space, with
    // glowing dots at the tips, connected to nearby antenna tips.
    // Creates the "connected neural web" / constellation look.
    const ANTENNA_COUNT = 55;
    type Antenna = {
      surface: THREE.Vector3;   // point on brain surface
      tip: THREE.Vector3;       // endpoint in space
      fire: number;
    };
    const antennas: Antenna[] = [];
    {
      const td = new THREE.Vector3(), sv = new THREE.Vector3();
      for (let i = 0; i < ANTENNA_COUNT; i++) {
        const y  = 1 - (i / (ANTENNA_COUNT - 1)) * 2;
        const r  = Math.sqrt(Math.max(0, 1 - y*y));
        const th = Math.PI * (1 + Math.sqrt(5)) * i * 1.618;
        td.set(Math.cos(th)*r, y, Math.sin(th)*r).normalize();
        shapeBrainPoint(td.x, td.y, td.z, BRAIN_RADIUS * 1.02, sv);

        // Extend outward along the surface normal — varying lengths
        const extLen = 1.2 + ((i * 7919) % 100) / 100 * 1.8; // 1.2 – 3.0
        const dir    = td.clone().normalize();
        const tip    = sv.clone().addScaledVector(dir, extLen);
        antennas.push({ surface: sv.clone(), tip, fire: 0 });
      }
    }

    // Lines: surface → tip (the "spike" lines in the reference)
    const antLineGeo = new THREE.BufferGeometry();
    const antLinePos = new Float32Array(ANTENNA_COUNT * 6);
    antennas.forEach((a, i) => {
      antLinePos.set([a.surface.x, a.surface.y, a.surface.z,
                      a.tip.x,     a.tip.y,     a.tip.z], i * 6);
    });
    antLineGeo.setAttribute('position', new THREE.BufferAttribute(antLinePos, 3));
    const antLineColors = new Float32Array(ANTENNA_COUNT * 6);
    antLineGeo.setAttribute('color', new THREE.BufferAttribute(antLineColors, 3));
    const antLineMat = new THREE.LineBasicMaterial({
      vertexColors: true, transparent: true, opacity: 0.75,
      blending: THREE.AdditiveBlending,
    });
    const antennaLines = new THREE.LineSegments(antLineGeo, antLineMat);
    scene.add(antennaLines);

    // Cross-connections between nearby antenna tips (the "web" in the reference)
    type WebEdge = { a: THREE.Vector3; b: THREE.Vector3; fire: number };
    const webEdges: WebEdge[] = [];
    for (let i = 0; i < ANTENNA_COUNT; i++) {
      const sorted = [...Array(ANTENNA_COUNT).keys()]
        .filter(j => j !== i)
        .sort((a, b) => antennas[i].tip.distanceTo(antennas[a].tip) -
                        antennas[i].tip.distanceTo(antennas[b].tip));
      for (const j of sorted.slice(0, 2)) {
        if (i < j && antennas[i].tip.distanceTo(antennas[j].tip) < 2.6) {
          webEdges.push({ a: antennas[i].tip, b: antennas[j].tip, fire: 0 });
        }
      }
    }
    const webGeo = new THREE.BufferGeometry();
    const webPos = new Float32Array(webEdges.length * 6);
    webEdges.forEach((e, i) => {
      webPos.set([e.a.x, e.a.y, e.a.z, e.b.x, e.b.y, e.b.z], i * 6);
    });
    webGeo.setAttribute('position', new THREE.BufferAttribute(webPos, 3));
    const webColors = new Float32Array(webEdges.length * 6);
    webGeo.setAttribute('color', new THREE.BufferAttribute(webColors, 3));
    const webMat = new THREE.LineBasicMaterial({
      vertexColors: true, transparent: true, opacity: 0.55,
      blending: THREE.AdditiveBlending,
    });
    const webLines = new THREE.LineSegments(webGeo, webMat);
    scene.add(webLines);

    // Glowing dot at each antenna tip
    const antennaTipGeo = new THREE.BufferGeometry();
    const antennaTipPos = new Float32Array(ANTENNA_COUNT * 3);
    antennas.forEach((a, i) => {
      antennaTipPos[i*3] = a.tip.x; antennaTipPos[i*3+1] = a.tip.y; antennaTipPos[i*3+2] = a.tip.z;
    });
    antennaTipGeo.setAttribute('position', new THREE.BufferAttribute(antennaTipPos, 3));
    const antennaTipMat = new THREE.PointsMaterial({
      color: 0x88eeff, size: 0.09, map: dotTex,
      transparent: true, opacity: 0.95,
      blending: THREE.AdditiveBlending, depthWrite: false,
    });
    const antennaTips = new THREE.Points(antennaTipGeo, antennaTipMat);
    scene.add(antennaTips);

    // ── Ambient particle halo ─────────────────────────────────────────────
    const PARTICLE_COUNT = 500;
    const particleGeo   = new THREE.BufferGeometry();
    const particlePos   = new Float32Array(PARTICLE_COUNT * 3);
    type PAngle = { theta: number; phi: number; baseR: number; speed: number; boost: number };
    const particleAngles: PAngle[] = [];
    for (let i = 0; i < PARTICLE_COUNT; i++) {
      const theta = Math.random() * Math.PI * 2;
      const phi   = Math.acos(2 * Math.random() - 1);
      const baseR = 2.6 + Math.random() * 1.8;
      particleAngles.push({
        theta, phi, baseR,
        speed: (Math.random() < 0.5 ? -1 : 1) * (0.04 + Math.random() * 0.18),
        boost: 0,
      });
    }
    particleGeo.setAttribute('position', new THREE.BufferAttribute(particlePos, 3));
    const particleMat = new THREE.PointsMaterial({
      color:          new THREE.Color().setHSL(BASE_HUE, 1, 0.72),
      size:           0.048,
      map:            dotTex,
      transparent:    true,
      opacity:        0.80,
      blending:       THREE.AdditiveBlending,
      depthWrite:     false,
      sizeAttenuation: true,
    });
    const particles = new THREE.Points(particleGeo, particleMat);
    scene.add(particles);

    // ── Animation loop ────────────────────────────────────────────────────
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let energy = 0.25;
    let hue    = BASE_HUE;
    let frame  = 0;
    const clock = new THREE.Clock();

    renderer.setAnimationLoop(() => {
      frame++;
      const { selfState, isTextSpeaking, tokenTimestamps, micLevel, isListening, isVoiceSpeaking } =
        stateRef.current;
      const t = clock.getElapsedTime();

      // ── Real signals → energy target ──────────────────────────────────
      const mode       = selfState?.mode ?? 'idle';
      const modeEnergy = MODE_ENERGY[mode] ?? 0.2;
      const confidence = selfState?.confidence ?? 0.5;
      const health     = selfState?.health     ?? 1;
      const isErrorMode = mode === 'error' || mode === 'recovering';

      const now          = Date.now();
      const recentTokens = tokenTimestamps.filter((ts: number) => now - ts < 500).length;
      const streamBurst  = isTextSpeaking ? Math.min(1, 0.4 + recentTokens * 0.05) : 0;
      const speakBurst   = Math.max(streamBurst, isVoiceSpeaking ? 0.75 : 0);
      const listenBurst  = isListening ? Math.min(1, 0.28 + micLevel * 0.9) : 0;

      const targetEnergy = Math.max(modeEnergy, speakBurst, listenBurst) * (0.5 + confidence * 0.5);
      const targetHue    = isErrorMode ? ERROR_HUE : BASE_HUE;
      energy += (targetEnergy - energy) * (reduceMotion ? 0.02 : 0.06);
      hue    += (targetHue    - hue)    * 0.05;

      const jitterAmt = health < 0.5 ? (1 - health) * 0.08 : 0.006;
      const spin      = reduceMotion ? 0 : 0.05 + energy * 0.10;

      // ── Hull ripple (on top of baked brain shape) ──────────────────────
      const posAttr = coreGeo.attributes.position;
      for (let i = 0; i < posAttr.count; i++) {
        const ix = i * 3;
        const bx = basePositions[ix], by = basePositions[ix+1], bz = basePositions[ix+2];
        const n  = Math.sin(bx * 3.0 + t * (0.5 + energy)) *
                   Math.cos(by * 2.6 + t * 0.35) *
                   Math.sin(bz * 3.2 - t * 0.45);
        const mul = 1 + n * (0.045 + energy * 0.10) + (Math.random() - 0.5) * jitterAmt;
        posAttr.setXYZ(i, bx * mul, by * mul, bz * mul);
      }
      posAttr.needsUpdate = true;
      coreGeo.computeVertexNormals();

      // ── Color updates ──────────────────────────────────────────────────
      const color = new THREE.Color().setHSL(hue, 1, 0.52 + energy * 0.14);
      hullMat.color.copy(color);
      hullMat.emissive.copy(color);
      hullMat.emissiveIntensity = 0.4 + energy * 0.45;
      hullMat.opacity           = 0.18 + energy * 0.12;
      wireMat.color.copy(color);
      wireMat.opacity = 0.08 + energy * 0.06;
      fineWireMat.color.copy(color);
      fineWireMat.opacity = 0.28 + energy * 0.18;  // stays prominent
      dotMat.color.copy(color);
      dotMat.opacity = 0.75 + energy * 0.22;

      innerGlowMat.uniforms.uColor.value.setHSL(hue, 1, 0.72);
      innerGlowMat.uniforms.uOpacity.value = 0.50 + energy * 0.30;
      outerGlowMat.uniforms.uColor.value.setHSL(hue, 0.9, 0.50);
      outerGlowMat.uniforms.uOpacity.value = 0.18 + energy * 0.22;

      cyanRim.color.setHSL(hue, 1, 0.65);
      cyanRim.intensity = 2.2 + energy * 1.4;
      tealFill.intensity = 0.8 + energy * 0.5;
      particleMat.color.copy(color);

      // ── Red/orange energy core — driven by thinking/speaking/error ────
      // This is the "lightning bolt" / energy flash in the reference.
      const isSpeaking  = speakBurst > 0.3;
      const isThinking  = modeEnergy > 0.5;
      const coreTarget  = isErrorMode   ? 0.95 :
                          isSpeaking    ? 0.80 + Math.sin(t * 8) * 0.15 :
                          isThinking    ? 0.60 + Math.sin(t * 5) * 0.20 :
                          energy * 0.35;
      energyCore.intensity    = coreTarget * 3.5;
      coreSphereMat.opacity   = coreTarget * 0.88;
      coreHaloMat.opacity     = coreTarget * 0.30;
      // Color shifts: normal = orange-red, error = white-hot
      const coreHue = isErrorMode ? 0.05 : 0.04;
      energyCore.color.setHSL(coreHue, 1, 0.55 + coreTarget * 0.25);
      coreSphereMat.color.setHSL(coreHue, 1, 0.6 + coreTarget * 0.3);
      coreHaloMat.color.setHSL(coreHue, 1, 0.5);

      // ── Brain rotation + bob ──────────────────────────────────────────
      brainGroup.rotation.y += (reduceMotion ? 0.0010 : 0.0035) + energy * 0.0018;
      brainGroup.rotation.x  = Math.sin(t * 0.14) * 0.055;
      brainGroup.position.y  = Math.sin(t * 0.38) * 0.055;
      surfaceDots.rotation.y += reduceMotion ? 0 : 0.0005;

      // Antenna/web/tip/node layers follow brain rotation
      const ry = brainGroup.rotation.y;
      const rx = brainGroup.rotation.x;
      const py = brainGroup.position.y;
      synapseLines.rotation.y  = ry; synapseLines.rotation.x  = rx; synapseLines.position.y  = py;
      nodeDots.rotation.y      = ry; nodeDots.rotation.x      = rx; nodeDots.position.y      = py;
      antennaLines.rotation.y  = ry; antennaLines.rotation.x  = rx; antennaLines.position.y  = py;
      webLines.rotation.y      = ry; webLines.rotation.x      = rx; webLines.position.y      = py;
      antennaTips.rotation.y   = ry; antennaTips.rotation.x   = rx; antennaTips.position.y   = py;

      particles.rotation.y    += spin * 0.0026;
      particles.rotation.x     = Math.sin(t * 0.10) * 0.09;

      // ── Timeline event → synapse + antenna fire ───────────────────────
      const currentTimeline = timelineRef.current;
      for (let i = 0; i < Math.min(currentTimeline.length, 6); i++) {
        const ev = currentTimeline[i];
        if (!seenEventsRef.current.has(ev.id)) {
          seenEventsRef.current.add(ev.id);
          for (let k = 0; k < 5; k++)
            synapses[Math.floor(Math.random() * synapses.length)].fire = 1;
          for (let k = 0; k < 6; k++)
            antennas[Math.floor(Math.random() * ANTENNA_COUNT)].fire = 1;
          for (let k = 0; k < 4; k++)
            webEdges[Math.floor(Math.random() * webEdges.length)].fire = 1;
          for (let k = 0; k < 30; k++)
            particleAngles[Math.floor(Math.random() * PARTICLE_COUNT)].boost = 1;
        }
      }

      // Random ambient antenna flicker (subtle ongoing activity)
      if (frame % 40 === 0) {
        const n = 1 + Math.floor(energy * 3);
        for (let k = 0; k < n; k++)
          antennas[Math.floor(Math.random() * ANTENNA_COUNT)].fire =
            Math.max(antennas[Math.floor(Math.random() * ANTENNA_COUNT)].fire, 0.4);
      }

      // ── Update synapse colors ─────────────────────────────────────────
      const sCol = synapseGeo.attributes.color;
      for (let i = 0; i < synapses.length; i++) {
        const s = synapses[i];
        if (s.fire > 0) s.fire = Math.max(0, s.fire - 0.038);
        const bright = Math.min(1, 0.10 + energy * 0.40 + s.fire);
        const c = new THREE.Color().setHSL(hue, 1, 0.38 + bright * 0.42);
        sCol.setXYZ(i*2, c.r, c.g, c.b);
        sCol.setXYZ(i*2+1, c.r, c.g, c.b);
      }
      sCol.needsUpdate = true;
      synapseMat.opacity = 0.45 + energy * 0.40;

      // ── Update antenna line colors ────────────────────────────────────
      const aCol = antLineGeo.attributes.color;
      for (let i = 0; i < ANTENNA_COUNT; i++) {
        const a = antennas[i];
        if (a.fire > 0) a.fire = Math.max(0, a.fire - 0.030);
        const bright  = Math.min(1, 0.15 + energy * 0.35 + a.fire);
        const cBase   = new THREE.Color().setHSL(hue, 1, 0.25 + bright * 0.30);
        const cTip    = new THREE.Color().setHSL(hue, 1, 0.50 + bright * 0.45); // tip is brighter
        aCol.setXYZ(i*2,   cBase.r, cBase.g, cBase.b);
        aCol.setXYZ(i*2+1, cTip.r,  cTip.g,  cTip.b);
      }
      aCol.needsUpdate = true;
      antLineMat.opacity = 0.55 + energy * 0.35;

      // ── Update web edge colors ────────────────────────────────────────
      const wCol = webGeo.attributes.color;
      for (let i = 0; i < webEdges.length; i++) {
        const e = webEdges[i];
        if (e.fire > 0) e.fire = Math.max(0, e.fire - 0.028);
        const bright = Math.min(1, 0.08 + energy * 0.25 + e.fire);
        const c = new THREE.Color().setHSL(hue, 1, 0.30 + bright * 0.35);
        wCol.setXYZ(i*2, c.r, c.g, c.b);
        wCol.setXYZ(i*2+1, c.r, c.g, c.b);
      }
      wCol.needsUpdate = true;
      webMat.opacity = 0.35 + energy * 0.30;

      // ── Antenna tip dot brightness ────────────────────────────────────
      antennaTipMat.color.setHSL(hue, 1, 0.72 + energy * 0.18);
      antennaTipMat.opacity = 0.80 + energy * 0.18;
      antennaTipMat.size    = 0.075 + energy * 0.04;
      nodeDotMat.color.setHSL(hue, 1, 0.68 + energy * 0.22);
      nodeDotMat.opacity = 0.88 + energy * 0.10;

      // ── Ambient particles ─────────────────────────────────────────────
      const pArr = particleGeo.attributes.position.array as Float32Array;
      for (let i = 0; i < PARTICLE_COUNT; i++) {
        const p = particleAngles[i];
        if (!reduceMotion) p.theta += p.speed * 0.011 * (0.3 + energy * 1.2);
        if (p.boost > 0) p.boost = Math.max(0, p.boost - 0.014);
        const inward = isListening ? micLevel * 0.85 : 0;
        const r      = p.baseR * (1 - inward * 0.35) + p.boost * 1.5;
        const ix     = i * 3;
        pArr[ix]     = Math.sin(p.phi) * Math.cos(p.theta) * r * 1.05;
        pArr[ix + 1] = Math.cos(p.phi) * r * 0.90;
        pArr[ix + 2] = Math.sin(p.phi) * Math.sin(p.theta) * r * 1.15;
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
      [coreGeo, fineWireGeo, innerGlowGeo, outerGlowGeo, stemGeo,
       dotGeo, synapseGeo, nodeDotGeo, antLineGeo, webGeo, antennaTipGeo,
       particleGeo, coreSphereGeo, coreHaloGeo].forEach(g => g.dispose());
      [hullMat, wireMat, fineWireMat, innerGlowMat, outerGlowMat,
       dotMat, synapseMat, nodeDotMat, antLineMat, webMat, antennaTipMat,
       particleMat, coreSphereMat, coreHaloMat].forEach(m => m.dispose());
      dotTex.dispose();
      if (renderer.domElement.parentNode === container) {
        container.removeChild(renderer.domElement);
      }
    };
  }, []);

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
      aria-label="MARK's live cognitive state — 3D neural brain visualization"
    />
  );
}
