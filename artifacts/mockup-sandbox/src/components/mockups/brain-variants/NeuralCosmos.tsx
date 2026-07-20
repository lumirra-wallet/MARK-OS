/**
 * Neural Cosmos — A bioluminescent AI brain floating in deep space.
 *
 * Concept: The brain as a cosmic entity — 60k dense glowing neuron-matter
 * point cloud, electric synapse lightning arcs, an orbiting nebula particle
 * field, and three layered Fresnel glow shells (cyan inner / indigo mid /
 * violet outer). Everything lives in a star-field void.
 *
 * Pure Three.js, zero external assets. Runs standalone in the mockup sandbox.
 */
import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';

const BRAIN_R = 1.6;

// Anatomically-shaped brain displacement (hemisphere fissure, temporal lobes, cerebellum)
function shapeBrain(nx: number, ny: number, nz: number, r: number, out: THREE.Vector3) {
  let fold = 0;
  fold += Math.sin(nx * 4.1 + nz * 3.3) * Math.cos(ny * 3.7) * 0.5;
  fold += Math.sin(nx * 8.6 - ny * 7.2 + nz * 6.1) * 0.28;
  fold += Math.sin(nx * 15.0 + ny * 13.0 - nz * 11.0) * 0.13;
  const foldMul = 1 + fold * 0.045;
  const topW = Math.max(0, Math.min(1, ny + 0.35));
  const fissure = Math.exp(-(nx * nx) / 0.012) * topW * 0.13;
  const temporal = Math.exp(-((Math.abs(nx) - 0.72) ** 2) / 0.032) *
    Math.exp(-((ny - 0.02) ** 2) / 0.09) * 0.14;
  const rm = foldMul * (1 - fissure) * (1 + temporal);
  let x = nx * r * 1.05 * rm, y = ny * r * 0.92 * rm, z = nz * r * 1.2 * rm;
  const cx = 0, cy = -r * 0.6, cz = -r * 0.82;
  const dx = x - cx, dy = y - cy, dz = z - cz;
  const spread = r * 0.4;
  const cb = Math.exp(-(dx * dx + dy * dy + dz * dz) / (2 * spread * spread)) * r * 0.24;
  if (cb > 0.0005) {
    const len = Math.sqrt(x * x + y * y + z * z) || 1;
    x += (x / len) * cb; y += (y / len) * cb * 0.5; z += (z / len) * cb;
  }
  return out.set(x, y, z);
}

function makeGlowSprite(r: number, g: number, b: number): THREE.Texture {
  const sz = 96;
  const c = document.createElement('canvas');
  c.width = c.height = sz;
  const ctx = c.getContext('2d')!;
  const grad = ctx.createRadialGradient(sz / 2, sz / 2, 0, sz / 2, sz / 2, sz / 2);
  grad.addColorStop(0, `rgba(${r},${g},${b},1)`);
  grad.addColorStop(0.35, `rgba(${r},${g},${b},0.65)`);
  grad.addColorStop(0.7, `rgba(${r},${g},${b},0.18)`);
  grad.addColorStop(1, `rgba(${r},${g},${b},0)`);
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, sz, sz);
  const t = new THREE.CanvasTexture(c);
  t.needsUpdate = true;
  return t;
}

const FRAG_FRESNEL = `
  uniform vec3 uColor;
  uniform float uOpacity;
  uniform float uPower;
  varying vec3 vN;
  varying vec3 vV;
  void main(){
    float f = pow(1.0 - max(dot(normalize(vN),normalize(vV)),0.0), uPower);
    gl_FragColor = vec4(uColor, f * uOpacity);
  }
`;
const VERT_FRESNEL = `
  varying vec3 vN;
  varying vec3 vV;
  void main(){
    vN = normalize(normalMatrix * normal);
    vec4 mv = modelViewMatrix * vec4(position,1.0);
    vV = normalize(-mv.xyz);
    gl_Position = projectionMatrix * mv;
  }
`;

// Synapse lightning shader — draws a jagged electric arc
const VERT_ARC = `
  attribute float aT;
  uniform float uTime;
  varying float vFire;
  uniform float uFire;
  varying vec3 vPos;
  void main(){
    vFire = uFire;
    vPos = position;
    float jitter = sin(aT * 47.3 + uTime * 8.2) * 0.04 * uFire;
    vec3 p = position + normal * jitter;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
  }
`;
const FRAG_ARC = `
  uniform vec3 uColor;
  uniform float uFire;
  varying float vFire;
  void main(){
    float alpha = vFire * 0.9;
    gl_FragColor = vec4(uColor, alpha);
  }
`;

// ── Canvas 2D fallback (no WebGL) ─────────────────────────────────────────
function NeuralCosmos2D() {
  const c2ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const cv = c2ref.current!;
    const ctx = cv.getContext('2d')!;
    let af: number;
    const resize = () => { cv.width = cv.offsetWidth * devicePixelRatio; cv.height = cv.offsetHeight * devicePixelRatio; };
    resize();
    window.addEventListener('resize', resize);
    const N = 3000;
    const tmp = new THREE.Vector3(), sh = new THREE.Vector3();
    const pts: { x: number; y: number; hue: number }[] = [];
    for (let i = 0; i < N; i++) {
      const yy = 1 - (i / (N - 1)) * 2;
      const rr = Math.sqrt(Math.max(0, 1 - yy * yy));
      const th = Math.PI * (1 + Math.sqrt(5)) * i;
      tmp.set(Math.cos(th) * rr, yy, Math.sin(th) * rr);
      shapeBrain(tmp.x, tmp.y, tmp.z, 1, sh);
      pts.push({ x: sh.x, y: sh.y, hue: Math.random() < 0.1 ? 45 : Math.random() < 0.15 ? 270 : 185 });
    }
    let t = 0;
    const draw = () => {
      t += 0.012;
      const W = cv.width, H = cv.height;
      ctx.fillStyle = 'rgba(0,5,16,0.18)';
      ctx.fillRect(0, 0, W, H);
      const cx = W / 2, cy = H / 2;
      const sc = Math.min(W, H) * 0.34;
      const angle = t * 0.04;
      for (const p of pts) {
        const rx = p.x * Math.cos(angle) - p.y * Math.sin(angle) * 0.25;
        const ry = p.x * Math.sin(angle) * 0.15 + p.y;
        const sx = cx + rx * sc;
        const sy = cy - ry * sc * 0.85;
        const pulse = 0.7 + Math.sin(t * 1.2 + p.x * 3 + p.y * 2) * 0.3;
        const alpha = (0.5 + pulse * 0.5) * 0.9;
        ctx.beginPath();
        ctx.arc(sx, sy, 0.9 * devicePixelRatio, 0, Math.PI * 2);
        ctx.fillStyle = `hsla(${p.hue},100%,${55 + pulse * 20}%,${alpha})`;
        ctx.fill();
      }
      af = requestAnimationFrame(draw);
    };
    draw();
    return () => { cancelAnimationFrame(af); window.removeEventListener('resize', resize); };
  }, []);
  return (
    <div style={{ width:'100%',height:'100%',background:'#000510',position:'relative' }}>
      <canvas ref={c2ref} style={{ width:'100%',height:'100%',display:'block' }} />
      <div style={{ position:'absolute',bottom:24,left:0,right:0,textAlign:'center',fontFamily:'monospace',fontSize:11,letterSpacing:4,color:'rgba(0,220,255,0.5)',textTransform:'uppercase',pointerEvents:'none' }}>NEURAL&nbsp;&nbsp;COSMOS</div>
    </div>
  );
}

export function NeuralCosmos() {
  const ref = useRef<HTMLDivElement>(null);
  const [hasWebGL, setHasWebGL] = useState(true);

  useEffect(() => {
    const el = ref.current!;
    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x000510, 0.055);

    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 120);
    camera.position.set(0, 0, 7.8);
    camera.lookAt(0, -0.2, 0);

    let renderer!: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    } catch {
      setHasWebGL(false);
      return;
    }
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setClearColor(0x000510, 1);
    el.appendChild(renderer.domElement);

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = el;
      if (!w || !h) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(el);

    // ── Star field ────────────────────────────────────────────────────
    const starGeo = new THREE.BufferGeometry();
    const starPos = new Float32Array(3000 * 3);
    const starCol = new Float32Array(3000 * 3);
    for (let i = 0; i < 3000; i++) {
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      const r = 30 + Math.random() * 60;
      starPos[i * 3] = Math.sin(phi) * Math.cos(theta) * r;
      starPos[i * 3 + 1] = Math.cos(phi) * r;
      starPos[i * 3 + 2] = Math.sin(phi) * Math.sin(theta) * r;
      // Star colors: mostly white-blue, occasional warm
      const warm = Math.random() < 0.12;
      starCol[i * 3] = warm ? 1 : 0.8 + Math.random() * 0.2;
      starCol[i * 3 + 1] = warm ? 0.6 + Math.random() * 0.2 : 0.85 + Math.random() * 0.15;
      starCol[i * 3 + 2] = warm ? 0.2 : 0.95 + Math.random() * 0.05;
    }
    starGeo.setAttribute('position', new THREE.BufferAttribute(starPos, 3));
    starGeo.setAttribute('color', new THREE.BufferAttribute(starCol, 3));
    const starMat = new THREE.PointsMaterial({
      vertexColors: true, size: 0.08, transparent: true, opacity: 0.9,
      blending: THREE.AdditiveBlending, depthWrite: false, sizeAttenuation: true,
    });
    scene.add(new THREE.Points(starGeo, starMat));

    // ── Nebula cloud (large soft billboard behind brain) ───────────────
    const nbCanvas = document.createElement('canvas');
    nbCanvas.width = nbCanvas.height = 512;
    const nbCtx = nbCanvas.getContext('2d')!;
    // deep space nebula gradient
    const nbGrad = nbCtx.createRadialGradient(256, 256, 0, 256, 256, 256);
    nbGrad.addColorStop(0,   'rgba(10,30,80,0.55)');
    nbGrad.addColorStop(0.3, 'rgba(20,10,60,0.35)');
    nbGrad.addColorStop(0.6, 'rgba(5,2,20,0.18)');
    nbGrad.addColorStop(1,   'rgba(0,0,0,0)');
    nbCtx.fillStyle = nbGrad;
    nbCtx.fillRect(0, 0, 512, 512);
    const nbTex = new THREE.CanvasTexture(nbCanvas);
    const nbMat = new THREE.SpriteMaterial({ map: nbTex, transparent: true, opacity: 0.9, blending: THREE.AdditiveBlending, depthWrite: false });
    const nebula = new THREE.Sprite(nbMat);
    nebula.scale.set(16, 16, 1);
    nebula.position.set(0, 0, -4);
    scene.add(nebula);

    // ── Lights ─────────────────────────────────────────────────────────
    scene.add(new THREE.AmbientLight(0x0a1520, 0.6));
    const key = new THREE.DirectionalLight(0xffffff, 0.7);
    key.position.set(3, 4, 5);
    scene.add(key);
    const cyanRim = new THREE.PointLight(0x00eeff, 2.2, 18, 2);
    cyanRim.position.set(-3, 1.5, 3);
    scene.add(cyanRim);
    const violetFill = new THREE.PointLight(0x8833ff, 1.4, 16, 2);
    violetFill.position.set(3, -1, -2);
    scene.add(violetFill);
    const goldAccent = new THREE.PointLight(0xffaa00, 0.8, 12, 2);
    goldAccent.position.set(0, 3, 1);
    scene.add(goldAccent);

    const brainGroup = new THREE.Group();
    scene.add(brainGroup);

    // ── Brain geometry (hull) ──────────────────────────────────────────
    const coreGeo = new THREE.IcosahedronGeometry(1, 6);
    const posAttr = coreGeo.attributes.position;
    const tmp = new THREE.Vector3(), shaped = new THREE.Vector3();
    const basePos = new Float32Array(posAttr.count * 3);
    for (let i = 0; i < posAttr.count; i++) {
      tmp.fromBufferAttribute(posAttr, i).normalize();
      shapeBrain(tmp.x, tmp.y, tmp.z, BRAIN_R, shaped);
      posAttr.setXYZ(i, shaped.x, shaped.y, shaped.z);
      basePos[i * 3] = shaped.x; basePos[i * 3 + 1] = shaped.y; basePos[i * 3 + 2] = shaped.z;
    }
    posAttr.needsUpdate = true;
    coreGeo.computeVertexNormals();

    const hullMat = new THREE.MeshPhysicalMaterial({
      color: 0x003344, transparent: true, opacity: 0.15,
      roughness: 0.2, metalness: 0.05, clearcoat: 0.6, clearcoatRoughness: 0.2,
      emissive: new THREE.Color(0x004455), emissiveIntensity: 0.5,
    });
    brainGroup.add(new THREE.Mesh(coreGeo, hullMat));

    // ── Dense surface point cloud (60k dots, per-vertex hue variation) ──
    const dotTex = makeGlowSprite(0, 220, 255);
    const dotGoldTex = makeGlowSprite(255, 180, 0);
    const N_DOTS = 60000;
    const dPos = new Float32Array(N_DOTS * 3);
    const dCol = new Float32Array(N_DOTS * 3);
    const dir2 = new THREE.Vector3(), sh2 = new THREE.Vector3();
    for (let i = 0; i < N_DOTS; i++) {
      const yy = 1 - (i / (N_DOTS - 1)) * 2;
      const rr = Math.sqrt(Math.max(0, 1 - yy * yy));
      const th = Math.PI * (1 + Math.sqrt(5)) * i;
      dir2.set(Math.cos(th) * rr, yy, Math.sin(th) * rr);
      shapeBrain(dir2.x, dir2.y, dir2.z, BRAIN_R * 1.008, sh2);
      dPos[i * 3] = sh2.x; dPos[i * 3 + 1] = sh2.y; dPos[i * 3 + 2] = sh2.z;
      // Per-dot color: mostly cyan-teal, sprinkle of gold/violet
      const rnd = Math.random();
      if (rnd < 0.08) { dCol[i*3]=1; dCol[i*3+1]=0.7; dCol[i*3+2]=0; } // gold
      else if (rnd < 0.15) { dCol[i*3]=0.6; dCol[i*3+1]=0; dCol[i*3+2]=1; } // violet
      else { // cyan-teal spectrum
        const t = Math.random();
        dCol[i*3]   = 0 + t * 0.1;
        dCol[i*3+1] = 0.75 + t * 0.25;
        dCol[i*3+2] = 0.85 + t * 0.15;
      }
    }
    const dotGeo = new THREE.BufferGeometry();
    dotGeo.setAttribute('position', new THREE.BufferAttribute(dPos, 3));
    dotGeo.setAttribute('color', new THREE.BufferAttribute(dCol, 3));
    const dotMat = new THREE.PointsMaterial({
      vertexColors: true, size: 0.022, map: dotTex,
      transparent: true, opacity: 0.92,
      blending: THREE.AdditiveBlending, depthWrite: false, sizeAttenuation: true,
    });
    brainGroup.add(new THREE.Points(dotGeo, dotMat));

    // ── Fine wireframe (baked at startup, static, high detail) ───────
    const wireGeo = new THREE.IcosahedronGeometry(1, 7);
    const wPos = wireGeo.attributes.position;
    for (let i = 0; i < wPos.count; i++) {
      tmp.fromBufferAttribute(wPos, i).normalize();
      shapeBrain(tmp.x, tmp.y, tmp.z, BRAIN_R * 1.005, shaped);
      wPos.setXYZ(i, shaped.x, shaped.y, shaped.z);
    }
    wPos.needsUpdate = true; wireGeo.computeVertexNormals();
    brainGroup.add(new THREE.Mesh(wireGeo, new THREE.MeshBasicMaterial({
      color: 0x00ddff, wireframe: true, transparent: true, opacity: 0.08,
      blending: THREE.AdditiveBlending, depthWrite: false,
    })));

    // ── Brainstem ─────────────────────────────────────────────────────
    const stemGeo = new THREE.CylinderGeometry(BRAIN_R * 0.14, BRAIN_R * 0.22, BRAIN_R * 0.55, 10);
    const stem = new THREE.Mesh(stemGeo, hullMat);
    stem.position.set(0, -BRAIN_R * 1.0, -BRAIN_R * 0.48);
    stem.rotation.x = 0.4;
    brainGroup.add(stem);

    // ── 3 Fresnel glow shells: inner cyan, mid blue, outer violet ─────
    function makeFresnelShell(radius: number, color: THREE.Color, opacity: number, power: number) {
      const g = new THREE.IcosahedronGeometry(1, 5);
      const pa = g.attributes.position;
      const tv = new THREE.Vector3(), sv = new THREE.Vector3();
      for (let i = 0; i < pa.count; i++) {
        tv.fromBufferAttribute(pa, i).normalize();
        shapeBrain(tv.x, tv.y, tv.z, radius, sv);
        pa.setXYZ(i, sv.x, sv.y, sv.z);
      }
      pa.needsUpdate = true; g.computeVertexNormals();
      const m = new THREE.ShaderMaterial({
        uniforms: { uColor: { value: color.clone() }, uOpacity: { value: opacity }, uPower: { value: power } },
        vertexShader: VERT_FRESNEL, fragmentShader: FRAG_FRESNEL,
        transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.FrontSide,
      });
      return new THREE.Mesh(g, m);
    }
    const shell1 = makeFresnelShell(BRAIN_R * 1.10, new THREE.Color(0x00ffff), 0.45, 1.8);
    const shell2 = makeFresnelShell(BRAIN_R * 1.22, new THREE.Color(0x2244ff), 0.30, 2.4);
    const shell3 = makeFresnelShell(BRAIN_R * 1.38, new THREE.Color(0x8800ff), 0.18, 3.2);
    brainGroup.add(shell1, shell2, shell3);

    // ── Synapse network (nodes + firing arcs) ─────────────────────────
    const NN = 100;
    const nodes: THREE.Vector3[] = [];
    for (let i = 0; i < NN; i++) {
      const y = 1 - (i / (NN - 1)) * 2;
      const r = Math.sqrt(Math.max(0, 1 - y * y));
      const th = Math.PI * (1 + Math.sqrt(5)) * i;
      const d = new THREE.Vector3(Math.cos(th) * r, y, Math.sin(th) * r).normalize();
      const s = new THREE.Vector3();
      shapeBrain(d.x, d.y, d.z, BRAIN_R * 1.02, s);
      nodes.push(s);
    }
    type Arc = { a: THREE.Vector3; b: THREE.Vector3; fire: number; color: number };
    const arcs: Arc[] = [];
    for (let i = 0; i < NN; i++) {
      const sorted = [...Array(NN).keys()].filter(j => j !== i)
        .sort((a, b) => nodes[i].distanceTo(nodes[a]) - nodes[i].distanceTo(nodes[b]));
      for (const j of sorted.slice(0, 2)) {
        if (i < j) {
          // Alternate synapse colors: cyan, gold, violet
          const colors = [0x00ffff, 0xffd700, 0xaa44ff];
          arcs.push({ a: nodes[i], b: nodes[j], fire: 0, color: colors[Math.floor(Math.random() * colors.length)] });
        }
      }
    }
    const arcGeo = new THREE.BufferGeometry();
    const arcPos = new Float32Array(arcs.length * 6);
    const arcNorm = new Float32Array(arcs.length * 6); // reuse as jitter t values
    const arcT = new Float32Array(arcs.length * 2);
    arcs.forEach((a, i) => {
      arcPos.set([a.a.x, a.a.y, a.a.z, a.b.x, a.b.y, a.b.z], i * 6);
      arcT[i * 2] = Math.random(); arcT[i * 2 + 1] = Math.random();
    });
    arcGeo.setAttribute('position', new THREE.BufferAttribute(arcPos, 3));
    arcGeo.setAttribute('aT', new THREE.BufferAttribute(arcT, 1));
    arcGeo.setAttribute('normal', new THREE.BufferAttribute(arcNorm, 3));
    // We'll use a simple color-vertex approach instead of the custom shader to keep it simple
    const arcCol = new Float32Array(arcs.length * 6);
    arcGeo.setAttribute('color', new THREE.BufferAttribute(arcCol, 3));
    const arcMat = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.7, blending: THREE.AdditiveBlending, depthWrite: false });
    const arcLines = new THREE.LineSegments(arcGeo, arcMat);
    scene.add(arcLines);

    // ── Nebula particle halo (800 particles orbiting) ─────────────────
    const NP = 800;
    const pGeo = new THREE.BufferGeometry();
    const pPos = new Float32Array(NP * 3);
    const pCol2 = new Float32Array(NP * 3);
    const pAngle: { th: number; phi: number; r: number; spd: number; phiSpd: number }[] = [];
    for (let i = 0; i < NP; i++) {
      const th = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      const r = 2.8 + Math.random() * 2.2;
      pAngle.push({ th, phi, r, spd: (Math.random() < 0.5 ? -1 : 1) * (0.04 + Math.random() * 0.18), phiSpd: (Math.random() - 0.5) * 0.02 });
      // Nebula colors: cyan, teal, violet, gold
      const c = Math.floor(Math.random() * 4);
      const cols = [[0,0.9,1],[0,1,0.7],[0.6,0,1],[1,0.7,0]];
      pCol2[i*3]=cols[c][0]; pCol2[i*3+1]=cols[c][1]; pCol2[i*3+2]=cols[c][2];
    }
    pGeo.setAttribute('position', new THREE.BufferAttribute(pPos, 3));
    pGeo.setAttribute('color', new THREE.BufferAttribute(pCol2, 3));
    const pMat = new THREE.PointsMaterial({
      vertexColors: true, size: 0.055, map: dotTex,
      transparent: true, opacity: 0.75,
      blending: THREE.AdditiveBlending, depthWrite: false, sizeAttenuation: true,
    });
    const particles = new THREE.Points(pGeo, pMat);
    scene.add(particles);

    // ── Slow camera orbit ─────────────────────────────────────────────
    let camAngle = 0;

    const clock = new THREE.Clock();
    let frame = 0;

    renderer.setAnimationLoop(() => {
      const t = clock.getElapsedTime();
      frame++;

      // Camera orbit (slow, majestic)
      camAngle += 0.0018;
      camera.position.x = Math.sin(camAngle) * 7.8;
      camera.position.z = Math.cos(camAngle) * 7.8;
      camera.position.y = Math.sin(camAngle * 0.3) * 0.8 - 0.2;
      camera.lookAt(0, -0.2, 0);

      // Brain rotation + subtle bob
      brainGroup.rotation.y = t * 0.08;
      brainGroup.rotation.x = Math.sin(t * 0.15) * 0.05;
      brainGroup.position.y = Math.sin(t * 0.4) * 0.06;

      // Hull ripple (energy-driven)
      const energy = 0.5 + Math.sin(t * 0.7) * 0.2;
      const pa2 = coreGeo.attributes.position;
      for (let i = 0; i < pa2.count; i++) {
        const ix = i * 3;
        const bx = basePos[ix], by = basePos[ix+1], bz = basePos[ix+2];
        const n = Math.sin(bx * 3.0 + t * 0.9) * Math.cos(by * 2.6 + t * 0.4) * Math.sin(bz * 3.2 - t * 0.5);
        const mul = 1 + n * (0.04 + energy * 0.07);
        pa2.setXYZ(i, bx * mul, by * mul, bz * mul);
      }
      pa2.needsUpdate = true;
      coreGeo.computeVertexNormals();

      // Pulse glow shells
      const pulse = 0.7 + Math.sin(t * 1.2) * 0.3;
      (shell1.material as THREE.ShaderMaterial).uniforms.uOpacity.value = 0.35 + energy * 0.18 * pulse;
      (shell2.material as THREE.ShaderMaterial).uniforms.uOpacity.value = 0.22 + energy * 0.12 * pulse;
      (shell3.material as THREE.ShaderMaterial).uniforms.uOpacity.value = 0.12 + energy * 0.08 * pulse;
      cyanRim.intensity = 1.8 + energy * 0.8 + Math.sin(t * 2.1) * 0.4;
      violetFill.intensity = 1.0 + energy * 0.6;

      // Synapse firing (random sparks every ~60 frames)
      if (frame % 55 === 0) {
        const count = 2 + Math.floor(Math.random() * 4);
        for (let k = 0; k < count; k++) {
          arcs[Math.floor(Math.random() * arcs.length)].fire = 1.0;
        }
      }
      const acol = arcGeo.attributes.color;
      arcs.forEach((a, i) => {
        if (a.fire > 0) a.fire = Math.max(0, a.fire - 0.04);
        const ambient = 0.08 + energy * 0.25;
        const bright = Math.min(1, ambient + a.fire);
        const c = new THREE.Color(a.color).multiplyScalar(bright);
        acol.setXYZ(i*2,   c.r, c.g, c.b);
        acol.setXYZ(i*2+1, c.r, c.g, c.b);
      });
      acol.needsUpdate = true;
      arcLines.rotation.y = brainGroup.rotation.y;
      arcLines.rotation.x = brainGroup.rotation.x;
      arcLines.position.copy(brainGroup.position);

      // Particle orbit update
      const pArr = pGeo.attributes.position.array as Float32Array;
      for (let i = 0; i < NP; i++) {
        const p = pAngle[i];
        p.th += p.spd * 0.013 * (0.5 + energy);
        p.phi += p.phiSpd * 0.008;
        const r = p.r + Math.sin(t * 0.5 + i * 0.1) * 0.3;
        pArr[i*3]   = Math.sin(p.phi) * Math.cos(p.th) * r * 1.05;
        pArr[i*3+1] = Math.cos(p.phi) * r * 0.85;
        pArr[i*3+2] = Math.sin(p.phi) * Math.sin(p.th) * r * 1.15;
      }
      pGeo.attributes.position.needsUpdate = true;
      particles.rotation.y += 0.0006;

      renderer.render(scene, camera);
    });

    return () => {
      renderer.setAnimationLoop(null);
      ro.disconnect();
      renderer.dispose();
    };
  }, []);

  if (!hasWebGL) return <NeuralCosmos2D />;

  return (
    <div style={{ width: '100%', height: '100%', background: '#000510', position: 'relative' }}>
      <div ref={ref} style={{ width: '100%', height: '100%' }} />
      <div style={{
        position: 'absolute', bottom: 24, left: 0, right: 0, textAlign: 'center',
        fontFamily: 'monospace', fontSize: 11, letterSpacing: 4,
        color: 'rgba(0,220,255,0.5)', textTransform: 'uppercase', pointerEvents: 'none',
      }}>
        NEURAL&nbsp;&nbsp;COSMOS
      </div>
    </div>
  );
}
