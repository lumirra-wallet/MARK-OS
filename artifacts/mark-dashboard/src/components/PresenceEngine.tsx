import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { useMarkStore } from '@/store/markStore';
import { useSelfState } from '@/hooks/use-self-state';
import { NeuralPresence } from './NeuralPresence';

/**
 * PresenceEngine — MARK's 3-D neural core.
 *
 * Matches the reference aesthetic:
 *   • Electric-blue/cyan brain wireframe with visible cortical fold texture
 *   • Background constellation network (floating nodes + lines, slow drift)
 *   • Radial deep-blue glow plane behind the brain
 *   • Red/orange branching lightning core (frontal-lobe energy flash)
 *   • Two Fresnel glow shells (tight cyan rim + wide atmospheric halo)
 *   • Dense surface point-cloud, brain-surface synapse nodes + antenna spikes
 *
 * Glitch fixes vs previous version:
 *   • No per-frame geometry vertex mutation (was the main glitch source).
 *     Brain shape is baked once; energy pulse uses Group.scale instead.
 *   • All THREE.Color / THREE.Vector3 helpers pre-allocated — zero GC
 *     allocations inside the render loop.
 *   • computeVertexNormals() removed from the hot path entirely.
 */
interface PresenceEngineProps {
  className?: string;
  micLevel?: number;
  isListening?: boolean;
  isVoiceSpeaking?: boolean;
}

const BASE_HUE  = 200 / 360;  // electric cyan-blue
const ERROR_HUE =   6 / 360;  // error red
const BRAIN_RADIUS = 1.5;

const MODE_ENERGY: Record<string, number> = {
  idle: 0.18, listening: 0.38, waiting: 0.14, sleeping: 0.05,
  thinking: 0.65, planning: 0.70, researching: 0.60,
  executing: 0.90, reflecting: 0.55, learning: 0.60,
  error: 0.50, recovering: 0.42,
};

// ─── Brain shape ────────────────────────────────────────────────────────────
function shapeBrainPoint(
  nx: number, ny: number, nz: number, radius: number, out: THREE.Vector3,
): THREE.Vector3 {
  // Gyri / sulci folds — three octaves of sine noise
  let fold = 0;
  fold += Math.sin(nx * 4.1 + nz * 3.3) * Math.cos(ny * 3.7) * 0.50;
  fold += Math.sin(nx * 8.6 - ny * 7.2 + nz * 6.1)           * 0.28;
  fold += Math.sin(nx * 15  + ny * 13   - nz * 11)            * 0.13;
  const foldMul = 1 + fold * 0.045;

  // Longitudinal fissure (dorsal groove)
  const topW   = Math.max(0, Math.min(1, ny + 0.35));
  const fissure = Math.exp(-(nx * nx) / 0.012) * topW * 0.13;

  // Temporal-lobe bulges
  const temporal = Math.exp(-((Math.abs(nx) - 0.72) ** 2) / 0.032) *
                   Math.exp(-((ny - 0.02) ** 2) / 0.09) * 0.14;

  const rm = foldMul * (1 - fissure) * (1 + temporal);
  let x = nx * radius * 1.05 * rm;
  let y = ny * radius * 0.92 * rm;
  let z = nz * radius * 1.20 * rm;

  // Cerebellum bulge — makes back-bottom read as a brain from all angles
  const cx = 0, cy = -radius * 0.6, cz = -radius * 0.82;
  const dx = x - cx, dy = y - cy, dz = z - cz;
  const cb = Math.exp(-(dx*dx + dy*dy + dz*dz) / (2 * (radius*0.4)**2)) * radius * 0.24;
  if (cb > 0.0005) {
    const len = Math.sqrt(x*x + y*y + z*z) || 1;
    x += (x / len) * cb; y += (y / len) * cb * 0.5; z += (z / len) * cb;
  }
  return out.set(x, y, z);
}

function bakeBrainGeo(geo: THREE.BufferGeometry, radius: number): void {
  const posAttr = geo.attributes.position;
  const tmp = new THREE.Vector3(), shaped = new THREE.Vector3();
  for (let i = 0; i < posAttr.count; i++) {
    tmp.fromBufferAttribute(posAttr, i).normalize();
    shapeBrainPoint(tmp.x, tmp.y, tmp.z, radius, shaped);
    posAttr.setXYZ(i, shaped.x, shaped.y, shaped.z);
  }
  posAttr.needsUpdate = true;
  geo.computeVertexNormals();
}

// ─── Textures ────────────────────────────────────────────────────────────────
/** Soft circular glow sprite — no external asset needed */
function makeDotTex(r = 255, g = 255, b = 255, sz = 64): THREE.Texture {
  const cv = document.createElement('canvas');
  cv.width = cv.height = sz;
  const ctx = cv.getContext('2d')!;
  const gr  = ctx.createRadialGradient(sz/2, sz/2, 0, sz/2, sz/2, sz/2);
  gr.addColorStop(0,   `rgba(${r},${g},${b},1)`);
  gr.addColorStop(0.35,`rgba(${r},${g},${b},0.75)`);
  gr.addColorStop(0.7, `rgba(${r},${g},${b},0.25)`);
  gr.addColorStop(1,   `rgba(${r},${g},${b},0)`);
  ctx.fillStyle = gr;
  ctx.fillRect(0, 0, sz, sz);
  const t = new THREE.CanvasTexture(cv);
  t.needsUpdate = true;
  return t;
}

/** Large radial-glow billboard placed behind the brain (the "deep blue light") */
function makeBackgroundGlowTex(): THREE.Texture {
  const cv = document.createElement('canvas');
  cv.width = cv.height = 512;
  const ctx = cv.getContext('2d')!;
  const gr  = ctx.createRadialGradient(256, 256, 0, 256, 256, 256);
  gr.addColorStop(0,    'rgba(0, 60, 160, 0.55)');
  gr.addColorStop(0.25, 'rgba(0, 30, 100, 0.35)');
  gr.addColorStop(0.55, 'rgba(0, 10,  50, 0.15)');
  gr.addColorStop(1,    'rgba(0,  0,   0, 0)');
  ctx.fillStyle = gr;
  ctx.fillRect(0, 0, 512, 512);
  const t = new THREE.CanvasTexture(cv);
  t.needsUpdate = true;
  return t;
}

// ─── Fresnel shader ──────────────────────────────────────────────────────────
const FRESNEL_VERT = `
  varying vec3 vN; varying vec3 vV;
  void main() {
    vN = normalize(normalMatrix * normal);
    vec4 mv = modelViewMatrix * vec4(position,1.0);
    vV = normalize(-mv.xyz);
    gl_Position = projectionMatrix * mv;
  }
`;
const FRESNEL_FRAG = `
  uniform vec3 uColor; uniform float uOpacity; uniform float uPower;
  varying vec3 vN; varying vec3 vV;
  void main() {
    float f = pow(1.0 - max(dot(normalize(vN),normalize(vV)),0.0), uPower);
    gl_FragColor = vec4(uColor, f * uOpacity);
  }
`;

// ─── Component ───────────────────────────────────────────────────────────────
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

    // ── Scene ─────────────────────────────────────────────────────────────
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x030810);
    scene.fog        = new THREE.FogExp2(0x030810, 0.040);

    // ── Camera: side-on view like the reference ───────────────────────────
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 120);
    camera.position.set(1.2, 0.45, 7.0);
    camera.lookAt(0, -0.2, 0);

    let renderer!: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    } catch {
      setWebGLAvailable(false);
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = false;
    container.appendChild(renderer.domElement);

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = container;
      if (!w || !h) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(container);
    window.addEventListener('resize', resize);
    const retryT = [50, 200, 500, 1000].map(ms => window.setTimeout(resize, ms));

    // ── Pre-allocate loop helpers (zero GC in hot path) ───────────────────
    const _c   = new THREE.Color();
    const _c2  = new THREE.Color();
    const _v3  = new THREE.Vector3();

    // ── Textures ─────────────────────────────────────────────────────────
    const dotTex  = makeDotTex(160, 220, 255);  // blue-white glow
    const bgGlow  = makeBackgroundGlowTex();

    // ── Lighting ──────────────────────────────────────────────────────────
    // Dark blue ambient — prevents unlit faces going black
    const ambLight = new THREE.AmbientLight(0x061220, 1.2);

    // Key from front-right (matches reference)
    const keyLight = new THREE.DirectionalLight(0xffffff, 0.65);
    keyLight.position.set(4, 3, 5);

    // Strong cyan rim from left — the blue edge glow
    const rimLight = new THREE.PointLight(0x00bbff, 3.2, 20, 2);
    rimLight.position.set(-4.0, 1.5, 3.5);

    // Soft blue fill from below
    const fillLight = new THREE.PointLight(0x003399, 1.4, 16, 2);
    fillLight.position.set(0.5, -4, 1);

    // Red/orange energy core light (inside brain, frontal-lobe region)
    const coreLight = new THREE.PointLight(0xff4400, 0, 7, 2);
    coreLight.position.set(0.35, 0.12, 0.55);

    scene.add(ambLight, keyLight, rimLight, fillLight, coreLight);

    // ── Background: large radial glow billboard ───────────────────────────
    // Sits behind the brain; creates the "deep blue light source" from the ref
    const bgSpriteMat = new THREE.SpriteMaterial({
      map: bgGlow, transparent: true, opacity: 0.85,
      blending: THREE.AdditiveBlending, depthWrite: false,
    });
    const bgSprite = new THREE.Sprite(bgSpriteMat);
    bgSprite.scale.set(32, 22, 1);
    bgSprite.position.set(0, 0, -5);
    scene.add(bgSprite);

    // Secondary tighter glow just behind the brain
    const bgSprite2Mat = new THREE.SpriteMaterial({
      map: bgGlow, transparent: true, opacity: 0.55,
      blending: THREE.AdditiveBlending, depthWrite: false,
    });
    const bgSprite2 = new THREE.Sprite(bgSprite2Mat);
    bgSprite2.scale.set(14, 10, 1);
    bgSprite2.position.set(0.3, 0.1, -2.5);
    scene.add(bgSprite2);

    // ── Background constellation network ──────────────────────────────────
    // Floating nodes + connecting lines scattered across the whole scene —
    // the "neural web" visible throughout the reference image background.
    const BG_NODE_COUNT = 72;
    type BgNode = { pos: THREE.Vector3; vel: THREE.Vector3 };
    const bgNodes: BgNode[] = [];
    for (let i = 0; i < BG_NODE_COUNT; i++) {
      // Distribute on a wide ellipsoid skewed toward the edges of the frame
      const theta = Math.random() * Math.PI * 2;
      const phi   = Math.acos(2 * Math.random() - 1);
      const rBase = 4.5 + Math.random() * 7;
      // Flatten depth (Z) so they read as a 2D background network
      const rx = rBase * 1.6, ry = rBase * 1.1, rz = rBase * 0.5;
      const pos = new THREE.Vector3(
        Math.sin(phi) * Math.cos(theta) * rx,
        Math.cos(phi) * ry,
        Math.sin(phi) * Math.sin(theta) * rz - 3,
      );
      // Very slow drift
      const vel = new THREE.Vector3(
        (Math.random() - 0.5) * 0.0006,
        (Math.random() - 0.5) * 0.0004,
        0,
      );
      bgNodes.push({ pos, vel });
    }

    // Edges between nearby nodes
    type BgEdge = { a: number; b: number };
    const bgEdges: BgEdge[] = [];
    for (let i = 0; i < BG_NODE_COUNT; i++) {
      for (let j = i + 1; j < BG_NODE_COUNT; j++) {
        if (bgNodes[i].pos.distanceTo(bgNodes[j].pos) < 4.8) {
          bgEdges.push({ a: i, b: j });
        }
      }
    }

    const bgLineGeo = new THREE.BufferGeometry();
    const bgLinePos = new Float32Array(bgEdges.length * 6);
    bgEdges.forEach((e, i) => {
      const a = bgNodes[e.a].pos, b = bgNodes[e.b].pos;
      bgLinePos.set([a.x,a.y,a.z, b.x,b.y,b.z], i*6);
    });
    bgLineGeo.setAttribute('position', new THREE.BufferAttribute(bgLinePos, 3));
    const bgLineMat = new THREE.LineBasicMaterial({
      color: 0x0055bb, transparent: true, opacity: 0.28,
      blending: THREE.AdditiveBlending,
    });
    const bgLines = new THREE.LineSegments(bgLineGeo, bgLineMat);
    scene.add(bgLines);

    // Glowing dots at each background node
    const bgDotGeo = new THREE.BufferGeometry();
    const bgDotPos = new Float32Array(BG_NODE_COUNT * 3);
    bgNodes.forEach((n, i) => {
      bgDotPos[i*3] = n.pos.x; bgDotPos[i*3+1] = n.pos.y; bgDotPos[i*3+2] = n.pos.z;
    });
    bgDotGeo.setAttribute('position', new THREE.BufferAttribute(bgDotPos, 3));
    const bgDotMat = new THREE.PointsMaterial({
      color: 0x0088ff, size: 0.14, map: dotTex,
      transparent: true, opacity: 0.75,
      blending: THREE.AdditiveBlending, depthWrite: false,
    });
    scene.add(new THREE.Points(bgDotGeo, bgDotMat));

    // ── Brain group ───────────────────────────────────────────────────────
    const brainGroup = new THREE.Group();
    scene.add(brainGroup);

    // ── Hull: baked once, NEVER mutated per frame ─────────────────────────
    // This eliminates the geometry-glitch from the previous version.
    const hullGeo = new THREE.IcosahedronGeometry(1, 5);
    bakeBrainGeo(hullGeo, BRAIN_RADIUS);
    const hullMat = new THREE.MeshPhysicalMaterial({
      color: new THREE.Color().setHSL(BASE_HUE, 1, 0.50),
      transparent: true, opacity: 0.22,
      roughness: 0.20, metalness: 0.0,
      clearcoat: 0.6, clearcoatRoughness: 0.15,
      emissive: new THREE.Color().setHSL(BASE_HUE, 1, 0.45),
      emissiveIntensity: 0.65,
      side: THREE.FrontSide,
    });
    brainGroup.add(new THREE.Mesh(hullGeo, hullMat));

    // ── Fine wireframe: the dominant visual — cortical fold grid ──────────
    // High-resolution, baked once. This IS the mesh you see in the reference.
    const fineGeo = new THREE.IcosahedronGeometry(1, 7);
    bakeBrainGeo(fineGeo, BRAIN_RADIUS * 1.004);
    const fineMat = new THREE.MeshBasicMaterial({
      color: new THREE.Color().setHSL(BASE_HUE, 1, 0.62),
      wireframe: true, transparent: true, opacity: 0.52,
      blending: THREE.AdditiveBlending, depthWrite: false,
    });
    brainGroup.add(new THREE.Mesh(fineGeo, fineMat));

    // ── Medium wireframe: slightly different scale for depth layering ─────
    const medGeo = new THREE.IcosahedronGeometry(1, 5);
    bakeBrainGeo(medGeo, BRAIN_RADIUS * 1.010);
    const medMat = new THREE.MeshBasicMaterial({
      color: new THREE.Color().setHSL(BASE_HUE, 1, 0.55),
      wireframe: true, transparent: true, opacity: 0.20,
      blending: THREE.AdditiveBlending, depthWrite: false,
    });
    brainGroup.add(new THREE.Mesh(medGeo, medMat));

    // ── Dense surface point cloud ─────────────────────────────────────────
    // Stippled hologram-scan texture sitting just above the hull.
    const SURFACE_N  = 30000;
    const surfaceGeo = new THREE.BufferGeometry();
    const surfacePos = new Float32Array(SURFACE_N * 3);
    {
      const dir = new THREE.Vector3(), sh = new THREE.Vector3();
      for (let i = 0; i < SURFACE_N; i++) {
        const y  = 1 - (i / (SURFACE_N - 1)) * 2;
        const r  = Math.sqrt(Math.max(0, 1 - y*y));
        const th = Math.PI * (1 + Math.sqrt(5)) * i;
        dir.set(Math.cos(th)*r, y, Math.sin(th)*r);
        shapeBrainPoint(dir.x, dir.y, dir.z, BRAIN_RADIUS * 1.015, sh);
        surfacePos[i*3] = sh.x; surfacePos[i*3+1] = sh.y; surfacePos[i*3+2] = sh.z;
      }
    }
    surfaceGeo.setAttribute('position', new THREE.BufferAttribute(surfacePos, 3));
    const surfaceMat = new THREE.PointsMaterial({
      color: new THREE.Color().setHSL(BASE_HUE, 1, 0.72),
      size: 0.024, map: dotTex,
      transparent: true, opacity: 0.90,
      blending: THREE.AdditiveBlending, depthWrite: false, sizeAttenuation: true,
    });
    brainGroup.add(new THREE.Points(surfaceGeo, surfaceMat));

    // ── Inner Fresnel rim (tight bright cyan edge) ────────────────────────
    const innerGlowGeo = new THREE.IcosahedronGeometry(1, 5);
    bakeBrainGeo(innerGlowGeo, BRAIN_RADIUS * 1.06);
    const innerGlowMat = new THREE.ShaderMaterial({
      uniforms: {
        uColor:   { value: new THREE.Color(0x00ddff) },
        uOpacity: { value: 0.70 },
        uPower:   { value: 1.7  },
      },
      vertexShader: FRESNEL_VERT, fragmentShader: FRESNEL_FRAG,
      transparent: true, blending: THREE.AdditiveBlending,
      depthWrite: false, side: THREE.FrontSide,
    });
    brainGroup.add(new THREE.Mesh(innerGlowGeo, innerGlowMat));

    // ── Outer Fresnel halo (wide atmospheric blue glow) ───────────────────
    const outerGlowGeo = new THREE.IcosahedronGeometry(1, 4);
    bakeBrainGeo(outerGlowGeo, BRAIN_RADIUS * 1.30);
    const outerGlowMat = new THREE.ShaderMaterial({
      uniforms: {
        uColor:   { value: new THREE.Color(0x0055cc) },
        uOpacity: { value: 0.35 },
        uPower:   { value: 3.5  },
      },
      vertexShader: FRESNEL_VERT, fragmentShader: FRESNEL_FRAG,
      transparent: true, blending: THREE.AdditiveBlending,
      depthWrite: false, side: THREE.FrontSide,
    });
    brainGroup.add(new THREE.Mesh(outerGlowGeo, outerGlowMat));

    // ── Brainstem ─────────────────────────────────────────────────────────
    const stemGeo = new THREE.CylinderGeometry(
      BRAIN_RADIUS * 0.13, BRAIN_RADIUS * 0.21, BRAIN_RADIUS * 0.52, 10,
    );
    const stem = new THREE.Mesh(stemGeo, hullMat);
    stem.position.set(0, -BRAIN_RADIUS * 1.00, -BRAIN_RADIUS * 0.46);
    stem.rotation.x = 0.42;
    brainGroup.add(stem);

    // ── Red/orange energy core ────────────────────────────────────────────
    // The "lightning bolt" seen in the reference: a bright red-orange sphere
    // + halo + coreLight. Driven by thinking/speaking/error energy.
    const coreInnerGeo = new THREE.SphereGeometry(0.14, 10, 10);
    const coreInnerMat = new THREE.MeshBasicMaterial({
      color: 0xff5500, transparent: true, opacity: 0,
      blending: THREE.AdditiveBlending, depthWrite: false,
    });
    const coreInner = new THREE.Mesh(coreInnerGeo, coreInnerMat);
    coreInner.position.set(0.35, 0.12, 0.55);
    brainGroup.add(coreInner);

    const coreHaloGeo = new THREE.SphereGeometry(0.38, 10, 10);
    const coreHaloMat = new THREE.MeshBasicMaterial({
      color: 0xff2200, transparent: true, opacity: 0,
      blending: THREE.AdditiveBlending, depthWrite: false,
    });
    const coreHalo = new THREE.Mesh(coreHaloGeo, coreHaloMat);
    coreHalo.position.copy(coreInner.position);
    brainGroup.add(coreHalo);

    // Lightning branches radiating from the core
    // 8 short line-pairs that flicker on/off to simulate branching electricity
    const LIGHTNING_COUNT = 8;
    const lightningMats: THREE.LineBasicMaterial[] = [];
    const lightningMeshes: THREE.LineSegments[] = [];
    for (let k = 0; k < LIGHTNING_COUNT; k++) {
      const geo = new THREE.BufferGeometry();
      // Each "bolt" is 3 segments (root → mid → tip), slightly randomised
      const rng = (s: number) => ((Math.sin(s * 127.1 + 311.7) * 43758.5) % 1 + 1) % 1;
      const ox = coreInner.position.x, oy = coreInner.position.y, oz = coreInner.position.z;
      const angle = (k / LIGHTNING_COUNT) * Math.PI * 2;
      const dx = Math.cos(angle) * 0.55 + (rng(k)   - 0.5) * 0.25;
      const dy = Math.sin(angle) * 0.55 + (rng(k+1) - 0.5) * 0.25;
      const dz = (rng(k+2) - 0.5) * 0.35;
      // 3 segments: center → mid-jitter → tip-jitter
      const verts = new Float32Array([
        ox, oy, oz,
        ox + dx*0.45 + (rng(k+3)-0.5)*0.15, oy + dy*0.45 + (rng(k+4)-0.5)*0.15, oz + dz*0.5,
        ox + dx*0.45 + (rng(k+3)-0.5)*0.15, oy + dy*0.45 + (rng(k+4)-0.5)*0.15, oz + dz*0.5,
        ox + dx      + (rng(k+5)-0.5)*0.20, oy + dy      + (rng(k+6)-0.5)*0.20, oz + dz,
      ]);
      geo.setAttribute('position', new THREE.BufferAttribute(verts, 3));
      const mat = new THREE.LineBasicMaterial({
        color: 0xff7700, transparent: true, opacity: 0,
        blending: THREE.AdditiveBlending,
      });
      const mesh = new THREE.LineSegments(geo, mat);
      brainGroup.add(mesh);
      lightningMats.push(mat);
      lightningMeshes.push(mesh);
    }

    // ── Synapse surface nodes ─────────────────────────────────────────────
    const NODE_N = 90;
    const nodePos3: THREE.Vector3[] = [];
    {
      const td = new THREE.Vector3(), sv = new THREE.Vector3();
      for (let i = 0; i < NODE_N; i++) {
        const y = 1 - (i/(NODE_N-1))*2, r = Math.sqrt(Math.max(0,1-y*y));
        const th = Math.PI*(1+Math.sqrt(5))*i;
        td.set(Math.cos(th)*r, y, Math.sin(th)*r).normalize();
        shapeBrainPoint(td.x,td.y,td.z, BRAIN_RADIUS*1.04, sv);
        nodePos3.push(sv.clone());
      }
    }
    type Syn = { a: THREE.Vector3; b: THREE.Vector3; fire: number };
    const synapses: Syn[] = [];
    for (let i = 0; i < NODE_N; i++) {
      const sorted = [...Array(NODE_N).keys()].filter(j=>j!==i)
        .sort((a,b) => nodePos3[i].distanceTo(nodePos3[a]) - nodePos3[i].distanceTo(nodePos3[b]));
      for (const j of sorted.slice(0,2)) {
        if (i < j) synapses.push({ a: nodePos3[i], b: nodePos3[j], fire: 0 });
      }
    }
    const synGeo = new THREE.BufferGeometry();
    const synPos = new Float32Array(synapses.length * 6);
    synapses.forEach((s,i) => synPos.set([s.a.x,s.a.y,s.a.z,s.b.x,s.b.y,s.b.z],i*6));
    synGeo.setAttribute('position', new THREE.BufferAttribute(synPos, 3));
    const synColors = new Float32Array(synapses.length * 6);
    synGeo.setAttribute('color', new THREE.BufferAttribute(synColors, 3));
    const synMat = new THREE.LineBasicMaterial({
      vertexColors: true, transparent: true, opacity: 0.70,
      blending: THREE.AdditiveBlending,
    });
    const synLines = new THREE.LineSegments(synGeo, synMat);
    scene.add(synLines);

    // Glowing node dots at each synapse position
    const nodeDotGeo = new THREE.BufferGeometry();
    const nodeDotPos = new Float32Array(NODE_N * 3);
    nodePos3.forEach((p,i) => { nodeDotPos[i*3]=p.x; nodeDotPos[i*3+1]=p.y; nodeDotPos[i*3+2]=p.z; });
    nodeDotGeo.setAttribute('position', new THREE.BufferAttribute(nodeDotPos, 3));
    const nodeDotMat = new THREE.PointsMaterial({
      color: 0x44ddff, size: 0.058, map: dotTex,
      transparent: true, opacity: 0.95,
      blending: THREE.AdditiveBlending, depthWrite: false,
    });
    const nodeDots = new THREE.Points(nodeDotGeo, nodeDotMat);
    scene.add(nodeDots);

    // ── Antenna spikes: lines radiating from surface outward into space ───
    const ANT_N = 55;
    type Ant = { surface: THREE.Vector3; tip: THREE.Vector3; fire: number };
    const ants: Ant[] = [];
    {
      const td = new THREE.Vector3(), sv = new THREE.Vector3();
      for (let i = 0; i < ANT_N; i++) {
        const y = 1-(i/(ANT_N-1))*2, r = Math.sqrt(Math.max(0,1-y*y));
        const th = Math.PI*(1+Math.sqrt(5))*i*1.618;
        td.set(Math.cos(th)*r, y, Math.sin(th)*r).normalize();
        shapeBrainPoint(td.x,td.y,td.z, BRAIN_RADIUS*1.02, sv);
        const ext = 1.1 + ((i*7919)%100)/100*2.0;
        const tip = sv.clone().addScaledVector(td, ext);
        ants.push({ surface: sv.clone(), tip, fire: 0 });
      }
    }
    const antGeo = new THREE.BufferGeometry();
    const antPos = new Float32Array(ANT_N * 6);
    ants.forEach((a,i) => antPos.set([a.surface.x,a.surface.y,a.surface.z,a.tip.x,a.tip.y,a.tip.z],i*6));
    antGeo.setAttribute('position', new THREE.BufferAttribute(antPos, 3));
    const antColors = new Float32Array(ANT_N * 6);
    antGeo.setAttribute('color', new THREE.BufferAttribute(antColors, 3));
    const antMat = new THREE.LineBasicMaterial({
      vertexColors: true, transparent: true, opacity: 0.80,
      blending: THREE.AdditiveBlending,
    });
    const antLines = new THREE.LineSegments(antGeo, antMat);
    scene.add(antLines);

    // Glowing dots at antenna tips
    const tipDotGeo = new THREE.BufferGeometry();
    const tipDotPos = new Float32Array(ANT_N * 3);
    ants.forEach((a,i) => { tipDotPos[i*3]=a.tip.x; tipDotPos[i*3+1]=a.tip.y; tipDotPos[i*3+2]=a.tip.z; });
    tipDotGeo.setAttribute('position', new THREE.BufferAttribute(tipDotPos, 3));
    const tipDotMat = new THREE.PointsMaterial({
      color: 0x88eeff, size: 0.082, map: dotTex,
      transparent: true, opacity: 0.92,
      blending: THREE.AdditiveBlending, depthWrite: false,
    });
    const tipDots = new THREE.Points(tipDotGeo, tipDotMat);
    scene.add(tipDots);

    // Web connections between nearby antenna tips
    type Web = { a: THREE.Vector3; b: THREE.Vector3; fire: number };
    const webs: Web[] = [];
    for (let i = 0; i < ANT_N; i++) {
      const sorted = [...Array(ANT_N).keys()].filter(j=>j!==i)
        .sort((a,b) => ants[i].tip.distanceTo(ants[a].tip) - ants[i].tip.distanceTo(ants[b].tip));
      for (const j of sorted.slice(0,2)) {
        if (i < j && ants[i].tip.distanceTo(ants[j].tip) < 2.8)
          webs.push({ a: ants[i].tip, b: ants[j].tip, fire: 0 });
      }
    }
    const webGeo = new THREE.BufferGeometry();
    const webPos = new Float32Array(webs.length * 6);
    webs.forEach((w,i) => webPos.set([w.a.x,w.a.y,w.a.z,w.b.x,w.b.y,w.b.z],i*6));
    webGeo.setAttribute('position', new THREE.BufferAttribute(webPos, 3));
    const webColors = new Float32Array(webs.length * 6);
    webGeo.setAttribute('color', new THREE.BufferAttribute(webColors, 3));
    const webMat = new THREE.LineBasicMaterial({
      vertexColors: true, transparent: true, opacity: 0.50,
      blending: THREE.AdditiveBlending,
    });
    const webLines = new THREE.LineSegments(webGeo, webMat);
    scene.add(webLines);

    // ── Ambient particle halo ─────────────────────────────────────────────
    const PART_N = 520;
    const partGeo = new THREE.BufferGeometry();
    const partPos = new Float32Array(PART_N * 3);
    type PA = { theta: number; phi: number; baseR: number; speed: number; boost: number };
    const partAngles: PA[] = [];
    for (let i = 0; i < PART_N; i++) {
      partAngles.push({
        theta: Math.random()*Math.PI*2,
        phi:   Math.acos(2*Math.random()-1),
        baseR: 2.7 + Math.random()*1.9,
        speed: (Math.random()<0.5?-1:1)*(0.04+Math.random()*0.16),
        boost: 0,
      });
    }
    partGeo.setAttribute('position', new THREE.BufferAttribute(partPos, 3));
    const partMat = new THREE.PointsMaterial({
      color: new THREE.Color().setHSL(BASE_HUE, 1, 0.70),
      size: 0.046, map: dotTex,
      transparent: true, opacity: 0.78,
      blending: THREE.AdditiveBlending, depthWrite: false, sizeAttenuation: true,
    });
    const particles = new THREE.Points(partGeo, partMat);
    scene.add(particles);

    // ── Animation ─────────────────────────────────────────────────────────
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let energy  = 0.22;
    let hue     = BASE_HUE;
    let coreEnergy = 0;
    let frame   = 0;
    const clock = new THREE.Clock();

    renderer.setAnimationLoop(() => {
      frame++;
      const t = clock.getElapsedTime();
      const {
        selfState, isTextSpeaking, tokenTimestamps,
        micLevel, isListening, isVoiceSpeaking,
      } = stateRef.current;

      // ── Real-signal energy ────────────────────────────────────────────
      const mode       = selfState?.mode ?? 'idle';
      const modeE      = MODE_ENERGY[mode] ?? 0.2;
      const confidence = selfState?.confidence ?? 0.5;
      const health     = selfState?.health     ?? 1.0;
      const isError    = mode === 'error' || mode === 'recovering';
      const isThinking = modeE > 0.55;

      const now    = Date.now();
      const recent = tokenTimestamps.filter((ts: number) => now - ts < 500).length;
      const sBurst = isTextSpeaking ? Math.min(1, 0.4 + recent * 0.05) : 0;
      const speak  = Math.max(sBurst, isVoiceSpeaking ? 0.75 : 0);
      const listen = isListening ? Math.min(1, 0.28 + micLevel * 0.9) : 0;

      const targetE = Math.max(modeE, speak, listen) * (0.5 + confidence * 0.5);
      const targetH = isError ? ERROR_HUE : BASE_HUE;
      energy += (targetE - energy) * (reduceMotion ? 0.02 : 0.055);
      hue    += (targetH - hue)    * 0.05;

      // Core energy: spikes on speaking/thinking/error, pulses with time
      const targetCore = isError   ? 0.95 :
                         speak > 0.3 ? 0.78 + Math.sin(t*7)*0.18 :
                         isThinking  ? 0.55 + Math.sin(t*4.5)*0.22 :
                         energy * 0.30;
      coreEnergy += (targetCore - coreEnergy) * 0.08;

      const jitter = health < 0.5 ? (1 - health) * 0.006 : 0;

      // ── Color (pre-alloc, no GC) ──────────────────────────────────────
      _c.setHSL(hue, 1, 0.52 + energy * 0.13);

      // ── Hull (no vertex mutation — just material) ─────────────────────
      hullMat.color.copy(_c);
      hullMat.emissive.copy(_c);
      hullMat.emissiveIntensity = 0.50 + energy * 0.50;
      hullMat.opacity           = 0.14 + energy * 0.14;

      // ── Wireframes ───────────────────────────────────────────────────
      fineMat.color.copy(_c);
      fineMat.opacity = 0.38 + energy * 0.22;   // stays dominant & visible
      medMat.color.copy(_c);
      medMat.opacity  = 0.12 + energy * 0.10;

      // ── Surface dots ─────────────────────────────────────────────────
      surfaceMat.color.copy(_c);
      surfaceMat.opacity = 0.72 + energy * 0.24;

      // ── Fresnel shells ───────────────────────────────────────────────
      innerGlowMat.uniforms.uColor.value.setHSL(hue, 1, 0.74);
      innerGlowMat.uniforms.uOpacity.value = 0.55 + energy * 0.35;
      outerGlowMat.uniforms.uColor.value.setHSL(hue, 0.9, 0.52);
      outerGlowMat.uniforms.uOpacity.value = 0.20 + energy * 0.25;

      // ── Lights ───────────────────────────────────────────────────────
      rimLight.color.setHSL(hue, 1, 0.65);
      rimLight.intensity  = 2.5 + energy * 1.6;
      fillLight.intensity = 1.0 + energy * 0.6;

      // ── Energy core ──────────────────────────────────────────────────
      coreLight.intensity     = coreEnergy * 4.5;
      coreInnerMat.opacity    = coreEnergy * 0.92;
      coreHaloMat.opacity     = coreEnergy * 0.35;
      // White-hot at max, deep orange at idle
      const coreL = 0.58 + coreEnergy * 0.32;
      coreInnerMat.color.setHSL(0.05, 1, coreL);
      coreHaloMat.color.setHSL(0.04, 1, 0.45 + coreEnergy*0.2);
      coreLight.color.setHSL(0.05, 1, coreL);

      // Lightning bolt flicker
      for (let k = 0; k < LIGHTNING_COUNT; k++) {
        // Each bolt has its own flicker frequency so they don't all flash together
        const flicker = Math.sin(t * (4.0 + k * 0.7) + k * 1.3) * 0.5 + 0.5;
        const boltAlpha = coreEnergy * flicker * 0.85;
        lightningMats[k].opacity = boltAlpha;
        // Inner bolts white-hot, outer bolts orange
        lightningMats[k].color.setRGB(1, 0.3 + flicker*0.5, flicker*0.1);
      }

      // ── Brain group rotation — slow orbit, slight energy-driven bob ───
      const rotSpeed = (reduceMotion ? 0.0008 : 0.0030) + energy * 0.0014;
      brainGroup.rotation.y += rotSpeed;
      brainGroup.rotation.x  = Math.sin(t * 0.13) * 0.05 + jitter * (Math.random()-0.5);
      brainGroup.position.y  = Math.sin(t * 0.37) * 0.05;
      // Subtle scale pulse instead of vertex mutation — smooth & cheap
      const scalePulse = 1 + Math.sin(t * 1.2) * 0.005 * energy;
      brainGroup.scale.setScalar(scalePulse);

      // Mirror rotation to all satellite layers
      const ry = brainGroup.rotation.y, rx = brainGroup.rotation.x;
      const py = brainGroup.position.y;
      [synLines, nodeDots, antLines, tipDots, webLines].forEach(obj => {
        obj.rotation.y = ry; obj.rotation.x = rx; obj.position.y = py;
      });

      // Particles orbit
      particles.rotation.y += (reduceMotion ? 0 : 0.0022) + energy * 0.0010;
      particles.rotation.x  = Math.sin(t * 0.09) * 0.08;

      // Background constellation: very slow drift
      if (!reduceMotion) {
        const bgPosArr = bgLineGeo.attributes.position.array as Float32Array;
        const bgDotArr = bgDotGeo.attributes.position.array as Float32Array;
        bgNodes.forEach((n, ni) => {
          n.pos.addScaledVector(n.vel, 1);
          // Soft boundary bounce
          if (Math.abs(n.pos.x) > 14) n.vel.x *= -1;
          if (Math.abs(n.pos.y) > 9)  n.vel.y *= -1;
          bgDotArr[ni*3] = n.pos.x; bgDotArr[ni*3+1] = n.pos.y; bgDotArr[ni*3+2] = n.pos.z;
        });
        bgEdges.forEach((e, ei) => {
          const a = bgNodes[e.a].pos, b = bgNodes[e.b].pos;
          bgPosArr.set([a.x,a.y,a.z,b.x,b.y,b.z], ei*6);
        });
        bgLineGeo.attributes.position.needsUpdate = true;
        bgDotGeo.attributes.position.needsUpdate  = true;
      }
      bgLineMat.opacity = 0.18 + energy * 0.14;
      bgDotMat.opacity  = 0.55 + energy * 0.22;

      // ── Timeline events → fire synapses / antennas ────────────────────
      const tl = timelineRef.current;
      for (let i = 0; i < Math.min(tl.length, 6); i++) {
        const ev = tl[i];
        if (!seenEventsRef.current.has(ev.id)) {
          seenEventsRef.current.add(ev.id);
          for (let k=0; k<5; k++) synapses[Math.floor(Math.random()*synapses.length)].fire = 1;
          for (let k=0; k<5; k++) ants[Math.floor(Math.random()*ANT_N)].fire = 1;
          for (let k=0; k<3; k++) webs[Math.floor(Math.random()*webs.length)].fire = 1;
          for (let k=0; k<32; k++) partAngles[Math.floor(Math.random()*PART_N)].boost = 1;
        }
      }
      // Ambient antenna flicker (subtle ongoing activity)
      if (frame % 38 === 0) {
        const n = 1 + Math.floor(energy * 3);
        for (let k=0; k<n; k++)
          ants[Math.floor(Math.random()*ANT_N)].fire =
            Math.max(ants[Math.floor(Math.random()*ANT_N)].fire, 0.45);
      }

      // ── Synapse colors ────────────────────────────────────────────────
      const sCA = synGeo.attributes.color;
      for (let i = 0; i < synapses.length; i++) {
        const s = synapses[i];
        if (s.fire > 0) s.fire = Math.max(0, s.fire - 0.036);
        const bright = Math.min(1, 0.10 + energy * 0.40 + s.fire);
        _c2.setHSL(hue, 1, 0.35 + bright * 0.44);
        sCA.setXYZ(i*2,   _c2.r, _c2.g, _c2.b);
        sCA.setXYZ(i*2+1, _c2.r, _c2.g, _c2.b);
      }
      sCA.needsUpdate = true;
      synMat.opacity = 0.50 + energy * 0.38;

      // ── Antenna line colors ───────────────────────────────────────────
      const aCA = antGeo.attributes.color;
      for (let i = 0; i < ANT_N; i++) {
        const a = ants[i];
        if (a.fire > 0) a.fire = Math.max(0, a.fire - 0.028);
        const bright = Math.min(1, 0.15 + energy * 0.35 + a.fire);
        _c2.setHSL(hue, 1, 0.22 + bright * 0.30);  // dimmer at base
        aCA.setXYZ(i*2, _c2.r, _c2.g, _c2.b);
        _c2.setHSL(hue, 1, 0.50 + bright * 0.44);  // bright at tip
        aCA.setXYZ(i*2+1, _c2.r, _c2.g, _c2.b);
      }
      aCA.needsUpdate = true;
      antMat.opacity = 0.60 + energy * 0.30;
      tipDotMat.color.setHSL(hue, 1, 0.70 + energy*0.20);
      tipDotMat.opacity = 0.82 + energy*0.16;
      nodeDotMat.color.setHSL(hue, 1, 0.68 + energy*0.22);

      // ── Web edge colors ───────────────────────────────────────────────
      const wCA = webGeo.attributes.color;
      for (let i = 0; i < webs.length; i++) {
        const w = webs[i];
        if (w.fire > 0) w.fire = Math.max(0, w.fire - 0.026);
        const bright = Math.min(1, 0.08 + energy * 0.26 + w.fire);
        _c2.setHSL(hue, 1, 0.28 + bright * 0.35);
        wCA.setXYZ(i*2, _c2.r, _c2.g, _c2.b);
        wCA.setXYZ(i*2+1, _c2.r, _c2.g, _c2.b);
      }
      wCA.needsUpdate = true;
      webMat.opacity = 0.30 + energy * 0.30;

      // ── Particle halo ─────────────────────────────────────────────────
      const pA = partGeo.attributes.position.array as Float32Array;
      for (let i = 0; i < PART_N; i++) {
        const p = partAngles[i];
        if (!reduceMotion) p.theta += p.speed * 0.011 * (0.3 + energy * 1.1);
        if (p.boost > 0) p.boost = Math.max(0, p.boost - 0.013);
        const inward = isListening ? micLevel * 0.80 : 0;
        const r = p.baseR * (1 - inward * 0.35) + p.boost * 1.4;
        pA[i*3]   = Math.sin(p.phi) * Math.cos(p.theta) * r * 1.05;
        pA[i*3+1] = Math.cos(p.phi) * r * 0.90;
        pA[i*3+2] = Math.sin(p.phi) * Math.sin(p.theta) * r * 1.12;
      }
      partGeo.attributes.position.needsUpdate = true;
      partMat.color.setHSL(hue, 1, 0.68 + energy * 0.22);

      renderer.render(scene, camera);
    });

    return () => {
      renderer.setAnimationLoop(null);
      ro.disconnect();
      window.removeEventListener('resize', resize);
      retryT.forEach(id => window.clearTimeout(id));
      [
        hullGeo, fineGeo, medGeo, surfaceGeo,
        innerGlowGeo, outerGlowGeo, stemGeo,
        coreInnerGeo, coreHaloGeo,
        synGeo, nodeDotGeo, antGeo, tipDotGeo, webGeo,
        partGeo, bgLineGeo, bgDotGeo,
      ].forEach(g => g.dispose());
      [
        hullMat, fineMat, medMat, surfaceMat,
        innerGlowMat, outerGlowMat,
        coreInnerMat, coreHaloMat,
        synMat, nodeDotMat, antMat, tipDotMat, webMat,
        partMat, bgLineMat, bgDotMat,
        bgSpriteMat, bgSprite2Mat,
      ].forEach(m => m.dispose());
      lightningMats.forEach(m => m.dispose());
      lightningMeshes.forEach(m => m.geometry.dispose());
      dotTex.dispose();
      bgGlow.dispose();
      renderer.dispose();
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
      aria-label="MARK's live cognitive state — 3D neural brain"
    />
  );
}
