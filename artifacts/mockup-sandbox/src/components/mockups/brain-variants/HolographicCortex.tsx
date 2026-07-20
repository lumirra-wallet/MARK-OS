/**
 * Holographic Cortex — Cyberpunk AI scanner aesthetic.
 *
 * Concept: A holographic brain being actively scanned by an AI system.
 * Features: animated scan-line dissolve, neon PCB-trace circuit overlay,
 * fiber-optic data streams flowing into the brain, chromatic aberration
 * glow shells (R/G/B offset), HUD overlay with scanning metrics.
 *
 * Palette: deep navy void, electric blue (#0066FF), hot magenta (#FF0088),
 * cyan data (#00FFFF), phosphor white scan-line.
 */
import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';

const R = 1.55;

function shapeBrain(nx: number, ny: number, nz: number, r: number, out: THREE.Vector3) {
  let fold = 0;
  fold += Math.sin(nx * 4.1 + nz * 3.3) * Math.cos(ny * 3.7) * 0.5;
  fold += Math.sin(nx * 8.6 - ny * 7.2 + nz * 6.1) * 0.28;
  fold += Math.sin(nx * 15.0 + ny * 13.0 - nz * 11.0) * 0.13;
  const fm = 1 + fold * 0.045;
  const tw = Math.max(0, Math.min(1, ny + 0.35));
  const fiss = Math.exp(-(nx * nx) / 0.012) * tw * 0.13;
  const temp = Math.exp(-((Math.abs(nx) - 0.72) ** 2) / 0.032) *
    Math.exp(-((ny - 0.02) ** 2) / 0.09) * 0.14;
  const rm = fm * (1 - fiss) * (1 + temp);
  let x = nx * r * 1.05 * rm, y = ny * r * 0.92 * rm, z = nz * r * 1.2 * rm;
  const cx = 0, cy = -r * 0.6, cz = -r * 0.82;
  const dx = x - cx, dy = y - cy, dz = z - cz;
  const sp = r * 0.4;
  const cb = Math.exp(-(dx * dx + dy * dy + dz * dz) / (2 * sp * sp)) * r * 0.24;
  if (cb > 0.0005) {
    const len = Math.sqrt(x * x + y * y + z * z) || 1;
    x += (x / len) * cb; y += (y / len) * cb * 0.5; z += (z / len) * cb;
  }
  return out.set(x, y, z);
}

// Scan-dissolve vertex shader — reveals geometry above the scan-line
const VERT_SCAN = `
  uniform float uScanY;   // world-space Y of scan line (-2 → +2)
  uniform float uTime;
  varying float vReveal;   // 0 = below scan (hidden), 1 = above (solid)
  varying float vY;
  varying vec3  vNormalW;
  void main(){
    vec4 worldPos = modelMatrix * vec4(position, 1.0);
    float above = clamp((worldPos.y - uScanY + 0.18) / 0.18, 0.0, 1.0);
    vReveal  = above;
    vY       = worldPos.y;
    vNormalW = normalize(normalMatrix * normal);
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;
const FRAG_SCAN = `
  uniform float uScanY;
  uniform float uTime;
  uniform vec3  uColor;
  uniform float uOpacity;
  varying float vReveal;
  varying float vY;
  varying vec3  vNormalW;
  void main(){
    if(vReveal < 0.01) discard;
    // Edge brightness near scan line
    float edge = exp(-abs(vY - uScanY) * 18.0) * 2.5;
    // Scan-line flicker
    float scanLine = abs(sin(vY * 42.0 + uTime * 0.5)) * 0.08;
    // Fresnel rim
    float rim = pow(1.0 - abs(dot(normalize(vNormalW), vec3(0,0,1))), 2.5);
    vec3 col = uColor + vec3(1.0,1.0,1.0) * edge + vec3(uColor.r,0,uColor.b) * scanLine;
    float alpha = (uOpacity + rim * 0.18 + edge * 0.12) * vReveal;
    gl_FragColor = vec4(col, clamp(alpha, 0.0, 1.0));
  }
`;

// PCB circuit trace (procedural line network on brain surface)
const VERT_CIRCUIT = `
  uniform float uScanY;
  varying float vReveal;
  varying float vY;
  void main(){
    vec4 wp = modelMatrix * vec4(position, 1.0);
    vReveal = clamp((wp.y - uScanY + 0.18) / 0.18, 0.0, 1.0);
    vY = wp.y;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;
const FRAG_CIRCUIT = `
  uniform vec3 uColor;
  uniform float uOpacity;
  varying float vReveal;
  varying float vY;
  void main(){
    if(vReveal < 0.01) discard;
    float scanLine = abs(sin(vY * 42.0)) * 0.12;
    gl_FragColor = vec4(uColor + vec3(0,0,scanLine * 0.5), uOpacity * vReveal);
  }
`;

// Fresnel glow with chromatic aberration (color shift)
const VERT_FRESNEL = `
  varying vec3 vN; varying vec3 vV;
  void main(){
    vN = normalize(normalMatrix * normal);
    vec4 mv = modelViewMatrix * vec4(position,1.0);
    vV = normalize(-mv.xyz);
    gl_Position = projectionMatrix * mv;
  }
`;
const FRAG_FRESNEL = `
  uniform vec3 uColor; uniform float uOpacity; uniform float uPower;
  varying vec3 vN; varying vec3 vV;
  void main(){
    float f = pow(1.0 - max(dot(normalize(vN),normalize(vV)),0.0), uPower);
    gl_FragColor = vec4(uColor, f * uOpacity);
  }
`;

function makeGlowTex(r: number, g: number, b: number) {
  const sz = 64, c = document.createElement('canvas');
  c.width = c.height = sz;
  const ctx = c.getContext('2d')!;
  const gr = ctx.createRadialGradient(sz/2,sz/2,0,sz/2,sz/2,sz/2);
  gr.addColorStop(0, `rgba(${r},${g},${b},1)`);
  gr.addColorStop(0.4, `rgba(${r},${g},${b},0.6)`);
  gr.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = gr;
  ctx.fillRect(0,0,sz,sz);
  const t = new THREE.CanvasTexture(c);
  t.needsUpdate = true;
  return t;
}

// ── Canvas 2D fallback ───────────────────────────────────────────────────────
function HolographicCortex2D() {
  const c2ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const cv = c2ref.current!;
    const ctx = cv.getContext('2d')!;
    let af: number;
    const resize = () => { cv.width = cv.offsetWidth * devicePixelRatio; cv.height = cv.offsetHeight * devicePixelRatio; };
    resize();
    window.addEventListener('resize', resize);
    const tmp = new THREE.Vector3(), sh = new THREE.Vector3();
    const N = 2800;
    const pts: { x: number; y: number }[] = [];
    for (let i = 0; i < N; i++) {
      const yy = 1 - (i/(N-1))*2, rr = Math.sqrt(Math.max(0,1-yy*yy)), th = Math.PI*(1+Math.sqrt(5))*i;
      tmp.set(Math.cos(th)*rr, yy, Math.sin(th)*rr);
      shapeBrain(tmp.x, tmp.y, tmp.z, 1, sh);
      pts.push({ x: sh.x, y: sh.y });
    }
    let t = 0;
    const draw = () => {
      t += 0.014;
      const W = cv.width, H = cv.height;
      ctx.fillStyle = 'rgba(2,8,20,0.2)';
      ctx.fillRect(0,0,W,H);
      // Scan line
      const scanY = H * (0.1 + 0.85 * ((t * 0.22) % 1));
      ctx.fillStyle = 'rgba(0,200,255,0.06)';
      ctx.fillRect(0, scanY - 2, W, 4);
      const cx = W/2, cy = H/2, sc = Math.min(W,H)*0.32;
      const angle = t * 0.05;
      for (const p of pts) {
        const rx = p.x * Math.cos(angle);
        const ry = p.y;
        const sx = cx + rx * sc, sy = cy - ry * sc * 0.88;
        const revealed = sy > scanY;
        if (!revealed) continue;
        const scanEdge = Math.max(0, 1 - (sy - scanY) / (H * 0.4));
        const alpha = 0.5 + scanEdge * 0.5;
        ctx.beginPath();
        ctx.arc(sx, sy, 0.8 * devicePixelRatio, 0, Math.PI*2);
        ctx.fillStyle = `rgba(0,${Math.round(100+scanEdge*155)},255,${alpha})`;
        ctx.fill();
      }
      af = requestAnimationFrame(draw);
    };
    draw();
    return () => { cancelAnimationFrame(af); window.removeEventListener('resize', resize); };
  }, []);
  const mono = { fontFamily:'monospace', fontSize:10, letterSpacing:2 };
  return (
    <div style={{ width:'100%',height:'100%',background:'#020814',position:'relative' }}>
      <canvas ref={c2ref} style={{ width:'100%',height:'100%',display:'block' }} />
      <div style={{ position:'absolute',bottom:16,left:0,right:0,textAlign:'center',...mono,color:'rgba(0,100,200,0.5)',textTransform:'uppercase',fontSize:10,letterSpacing:4,pointerEvents:'none' }}>HOLOGRAPHIC&nbsp;&nbsp;CORTEX</div>
    </div>
  );
}

export function HolographicCortex() {
  const mountRef  = useRef<HTMLDivElement>(null);
  const scanRef   = useRef(0);
  const hudRef    = useRef({ signal: 0, neurons: 0, sync: 0, frame: 0 });
  const [hasWebGL, setHasWebGL] = useState(true);

  useEffect(() => {
    if (!hasWebGL) return;
    const el = mountRef.current!;
    const scene = new THREE.Scene();

    const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 80);
    camera.position.set(0, 0.1, 7.2);
    camera.lookAt(0, -0.1, 0);

    let renderer!: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    } catch {
      setHasWebGL(false);
      return;
    }
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setClearColor(0x020814, 1);
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

    // ── Grid floor ─────────────────────────────────────────────────────
    const gridHelper = new THREE.GridHelper(20, 24, 0x001133, 0x001133);
    gridHelper.position.y = -3.2;
    gridHelper.material.transparent = true;
    gridHelper.material.opacity = 0.7;
    scene.add(gridHelper);

    // ── Lights ─────────────────────────────────────────────────────────
    scene.add(new THREE.AmbientLight(0x050a18, 0.8));
    const key = new THREE.DirectionalLight(0x2266ff, 0.9);
    key.position.set(2, 3, 5);
    scene.add(key);
    const magRim = new THREE.PointLight(0xff0088, 2.0, 14, 2);
    magRim.position.set(-3, 1, 2.5);
    scene.add(magRim);
    const cyanTop = new THREE.PointLight(0x00ffff, 1.4, 12, 2);
    cyanTop.position.set(0, 4, 1);
    scene.add(cyanTop);
    const scanLight = new THREE.PointLight(0xffffff, 0.8, 6, 2);
    scene.add(scanLight);

    const brainGroup = new THREE.Group();
    scene.add(brainGroup);

    // ── Brain hull geometry ────────────────────────────────────────────
    const coreGeo = new THREE.IcosahedronGeometry(1, 6);
    const posAttr = coreGeo.attributes.position;
    const tmp = new THREE.Vector3(), sh = new THREE.Vector3();
    const basePos = new Float32Array(posAttr.count * 3);
    for (let i = 0; i < posAttr.count; i++) {
      tmp.fromBufferAttribute(posAttr, i).normalize();
      shapeBrain(tmp.x, tmp.y, tmp.z, R, sh);
      posAttr.setXYZ(i, sh.x, sh.y, sh.z);
      basePos[i*3]=sh.x; basePos[i*3+1]=sh.y; basePos[i*3+2]=sh.z;
    }
    posAttr.needsUpdate = true;
    coreGeo.computeVertexNormals();

    // Scanline-reveal hull
    const hullMat = new THREE.ShaderMaterial({
      uniforms: {
        uScanY: { value: -3.0 },
        uTime: { value: 0 },
        uColor: { value: new THREE.Color(0x0044aa) },
        uOpacity: { value: 0.18 },
      },
      vertexShader: VERT_SCAN,
      fragmentShader: FRAG_SCAN,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      side: THREE.FrontSide,
    });
    brainGroup.add(new THREE.Mesh(coreGeo, hullMat));

    // ── PCB circuit trace wireframe ────────────────────────────────────
    const circuitGeo = new THREE.IcosahedronGeometry(1, 7);
    const cPos = circuitGeo.attributes.position;
    for (let i = 0; i < cPos.count; i++) {
      tmp.fromBufferAttribute(cPos, i).normalize();
      shapeBrain(tmp.x, tmp.y, tmp.z, R * 1.006, sh);
      cPos.setXYZ(i, sh.x, sh.y, sh.z);
    }
    cPos.needsUpdate = true; circuitGeo.computeVertexNormals();
    const circuitMat = new THREE.ShaderMaterial({
      uniforms: { uScanY: { value: -3.0 }, uColor: { value: new THREE.Color(0x0088ff) }, uOpacity: { value: 0.28 } },
      vertexShader: VERT_CIRCUIT, fragmentShader: FRAG_CIRCUIT,
      transparent: true, wireframe: true,
      blending: THREE.AdditiveBlending, depthWrite: false,
    });
    brainGroup.add(new THREE.Mesh(circuitGeo, circuitMat));

    // ── Magenta outer wireframe (denser, different hue) ───────────────
    const magWireGeo = new THREE.IcosahedronGeometry(1, 5);
    const mPos = magWireGeo.attributes.position;
    for (let i = 0; i < mPos.count; i++) {
      tmp.fromBufferAttribute(mPos, i).normalize();
      shapeBrain(tmp.x, tmp.y, tmp.z, R * 1.014, sh);
      mPos.setXYZ(i, sh.x, sh.y, sh.z);
    }
    mPos.needsUpdate = true; magWireGeo.computeVertexNormals();
    const magWireMat = new THREE.ShaderMaterial({
      uniforms: { uScanY: { value: -3.0 }, uColor: { value: new THREE.Color(0xff0088) }, uOpacity: { value: 0.12 } },
      vertexShader: VERT_CIRCUIT, fragmentShader: FRAG_CIRCUIT,
      transparent: true, wireframe: true,
      blending: THREE.AdditiveBlending, depthWrite: false,
    });
    brainGroup.add(new THREE.Mesh(magWireGeo, magWireMat));

    // ── Brainstem ─────────────────────────────────────────────────────
    const stemGeo = new THREE.CylinderGeometry(R*0.14, R*0.22, R*0.55, 10);
    const stemMat = new THREE.ShaderMaterial({
      uniforms: { uScanY: { value: -3.0 }, uTime: { value: 0 }, uColor: { value: new THREE.Color(0x0044aa) }, uOpacity: { value: 0.14 } },
      vertexShader: VERT_SCAN, fragmentShader: FRAG_SCAN,
      transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
    });
    const stem = new THREE.Mesh(stemGeo, stemMat);
    stem.position.set(0, -R*1.0, -R*0.48);
    stem.rotation.x = 0.4;
    brainGroup.add(stem);

    // ── 3 Chromatic-aberration Fresnel shells (R, G, B offset) ────────
    function makeFresnelShell(radius: number, color: THREE.Color, opacity: number, power: number, offsetX: number, offsetY: number) {
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
      const mesh = new THREE.Mesh(g, m);
      mesh.position.set(offsetX, offsetY, 0);
      return mesh;
    }
    // Chromatic aberration: R shell offset left, G center, B offset right
    const shellR = makeFresnelShell(R * 1.12, new THREE.Color(0xff0044), 0.22, 2.0, -0.03, 0.01);
    const shellG = makeFresnelShell(R * 1.13, new THREE.Color(0x00ff88), 0.20, 2.2, 0, 0);
    const shellB = makeFresnelShell(R * 1.14, new THREE.Color(0x0088ff), 0.28, 2.0, 0.03, -0.01);
    const shellOuter = makeFresnelShell(R * 1.32, new THREE.Color(0x0044ff), 0.14, 3.5, 0, 0);
    brainGroup.add(shellR, shellG, shellB, shellOuter);

    // ── Data stream particles (fibers flowing INTO the brain) ──────────
    const NS = 600;
    const streamGeo = new THREE.BufferGeometry();
    const sPos = new Float32Array(NS * 3);
    const sCol = new Float32Array(NS * 3);
    // Stream particles start at random outer positions and orbit inward
    type StreamP = { theta: number; phi: number; r: number; speed: number; phase: number };
    const streams: StreamP[] = [];
    for (let i = 0; i < NS; i++) {
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      streams.push({ theta, phi, r: 3.5 + Math.random() * 1.5, speed: 0.3 + Math.random() * 0.5, phase: Math.random() * Math.PI * 2 });
      sCol[i*3]=0; sCol[i*3+1]=0.8+Math.random()*0.2; sCol[i*3+2]=1;
    }
    streamGeo.setAttribute('position', new THREE.BufferAttribute(sPos, 3));
    streamGeo.setAttribute('color', new THREE.BufferAttribute(sCol, 3));
    const streamTex = makeGlowTex(0, 180, 255);
    const streamMat = new THREE.PointsMaterial({
      vertexColors: true, size: 0.04, map: streamTex,
      transparent: true, opacity: 0.85,
      blending: THREE.AdditiveBlending, depthWrite: false,
    });
    const streamPoints = new THREE.Points(streamGeo, streamMat);
    scene.add(streamPoints);

    // ── Synapse network ────────────────────────────────────────────────
    const NN = 90;
    const nodes: THREE.Vector3[] = [];
    for (let i = 0; i < NN; i++) {
      const y = 1 - (i/(NN-1))*2;
      const rr = Math.sqrt(Math.max(0,1-y*y));
      const th = Math.PI*(1+Math.sqrt(5))*i;
      const d = new THREE.Vector3(Math.cos(th)*rr,y,Math.sin(th)*rr).normalize();
      const s = new THREE.Vector3();
      shapeBrain(d.x,d.y,d.z,R*1.01,s);
      nodes.push(s);
    }
    type Arc = { a: THREE.Vector3; b: THREE.Vector3; fire: number };
    const arcs: Arc[] = [];
    for (let i=0;i<NN;i++){
      const sorted=[...Array(NN).keys()].filter(j=>j!==i).sort((a,b)=>nodes[i].distanceTo(nodes[a])-nodes[i].distanceTo(nodes[b]));
      for(const j of sorted.slice(0,2)) if(i<j) arcs.push({a:nodes[i],b:nodes[j],fire:0});
    }
    const arcGeo2 = new THREE.BufferGeometry();
    const arcPos2 = new Float32Array(arcs.length*6);
    arcs.forEach((a,i)=>arcPos2.set([a.a.x,a.a.y,a.a.z,a.b.x,a.b.y,a.b.z],i*6));
    arcGeo2.setAttribute('position',new THREE.BufferAttribute(arcPos2,3));
    const arcCol2 = new Float32Array(arcs.length*6);
    arcGeo2.setAttribute('color',new THREE.BufferAttribute(arcCol2,3));
    const arcMat2=new THREE.LineBasicMaterial({vertexColors:true,transparent:true,opacity:0.75,blending:THREE.AdditiveBlending,depthWrite:false});
    const arcLines=new THREE.LineSegments(arcGeo2,arcMat2);
    scene.add(arcLines);

    // HUD state
    const hud = hudRef.current;
    const clock = new THREE.Clock();
    let frame = 0;

    renderer.setAnimationLoop(() => {
      const t = clock.getElapsedTime();
      frame++;
      hud.frame = frame;

      // Scan-line sweeps bottom→top over 4 seconds, then resets
      const scanPeriod = 4.5;
      const scanT = (t % scanPeriod) / scanPeriod;
      const scanY = -2.5 + scanT * 5.8; // world-space Y sweep
      scanRef.current = scanY;

      // Update all scan uniforms
      const updateScan = (m: THREE.ShaderMaterial) => {
        m.uniforms.uScanY.value = scanY;
        if (m.uniforms.uTime) m.uniforms.uTime.value = t;
      };
      updateScan(hullMat);
      updateScan(circuitMat);
      updateScan(magWireMat);
      updateScan(stemMat);

      scanLight.position.set(0, scanY, 3);
      scanLight.intensity = 0.6 + Math.sin(t * 8) * 0.2;

      // Brain rotation (slow Y + Z wobble)
      brainGroup.rotation.y = t * 0.12;
      brainGroup.rotation.z = Math.sin(t * 0.25) * 0.04;
      brainGroup.position.y = Math.sin(t * 0.38) * 0.05;

      // Hull ripple
      const energy = 0.55 + Math.sin(t * 0.8) * 0.18;
      const pa = coreGeo.attributes.position;
      for (let i = 0; i < pa.count; i++) {
        const ix = i*3;
        const bx=basePos[ix], by=basePos[ix+1], bz=basePos[ix+2];
        const n = Math.sin(bx*3+t*0.9)*Math.cos(by*2.7+t*0.4)*Math.sin(bz*3.1-t*0.5);
        const mul = 1 + n * (0.035 + energy * 0.055);
        pa.setXYZ(i, bx*mul, by*mul, bz*mul);
      }
      pa.needsUpdate=true; coreGeo.computeVertexNormals();

      // Chromatic aberration pulse
      const ca = Math.sin(t * 1.5) * 0.012 + 0.015;
      shellR.position.set(-ca, ca*0.5, 0);
      shellB.position.set(ca, -ca*0.5, 0);

      // Glow shells pulse
      [(shellR.material as THREE.ShaderMaterial),(shellG.material as THREE.ShaderMaterial),(shellB.material as THREE.ShaderMaterial)].forEach(m => {
        m.uniforms.uOpacity.value = 0.18 + Math.sin(t * 1.8) * 0.06;
      });
      (shellOuter.material as THREE.ShaderMaterial).uniforms.uOpacity.value = 0.10 + Math.sin(t * 0.9) * 0.04;

      // Data streams — particles pulse toward brain, then reset
      const sArr = streamGeo.attributes.position.array as Float32Array;
      for (let i=0;i<NS;i++){
        const p = streams[i];
        const phase = (t * p.speed + p.phase) % (Math.PI * 2);
        // r pulses: 3.5 → 1.2 over half cycle, then jumps back
        const halfPhase = phase % Math.PI;
        const inward = halfPhase < Math.PI ? halfPhase / Math.PI : 1;
        const r = p.r * (1 - inward * 0.68);
        sArr[i*3]   = Math.sin(p.phi)*Math.cos(p.theta)*r*1.08;
        sArr[i*3+1] = Math.cos(p.phi)*r*0.88;
        sArr[i*3+2] = Math.sin(p.phi)*Math.sin(p.theta)*r*1.18;
      }
      streamGeo.attributes.position.needsUpdate=true;
      streamPoints.rotation.y = brainGroup.rotation.y;

      // Synapse fire
      if(frame % 45===0){
        for(let k=0;k<3+Math.floor(Math.random()*4);k++)
          arcs[Math.floor(Math.random()*arcs.length)].fire=1;
      }
      const ac=arcGeo2.attributes.color;
      const blueColor = new THREE.Color(0x0088ff);
      const cyanColor = new THREE.Color(0x00ffff);
      arcs.forEach((a,i)=>{
        if(a.fire>0) a.fire=Math.max(0,a.fire-0.045);
        const amb=0.05+energy*0.2; const b=Math.min(1,amb+a.fire);
        const c = a.fire > 0.3 ? cyanColor.clone().multiplyScalar(b) : blueColor.clone().multiplyScalar(b);
        ac.setXYZ(i*2,c.r,c.g,c.b); ac.setXYZ(i*2+1,c.r,c.g,c.b);
      });
      ac.needsUpdate=true;
      arcLines.rotation.y=brainGroup.rotation.y;
      arcLines.rotation.z=brainGroup.rotation.z;
      arcLines.position.copy(brainGroup.position);

      // HUD values
      hud.signal = Math.round(85 + Math.sin(t * 0.7) * 12);
      hud.neurons = Math.round(scanT * 847000);
      hud.sync = Math.round(92 + Math.sin(t * 1.3) * 7);

      magRim.intensity = 1.6 + Math.sin(t * 2.3) * 0.5;
      cyanTop.intensity = 1.2 + Math.sin(t * 1.7) * 0.3;

      renderer.render(scene, camera);
    });

    return () => {
      renderer.setAnimationLoop(null);
      ro.disconnect();
      renderer.dispose();
    };
  }, []);

  // HUD overlay state — we update via ref every frame to avoid React re-renders
  const signalBarRef = useRef<HTMLDivElement>(null);
  const neuronsRef   = useRef<HTMLSpanElement>(null);
  const syncRef2     = useRef<HTMLSpanElement>(null);
  const scanBarRef   = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let af: number;
    const tick = () => {
      if (signalBarRef.current) signalBarRef.current.style.width = `${hudRef.current.signal}%`;
      if (neuronsRef.current)   neuronsRef.current.textContent  = hudRef.current.neurons.toLocaleString();
      if (syncRef2.current)     syncRef2.current.textContent    = `${hudRef.current.sync}%`;
      const scanPct = ((scanRef.current + 2.5) / 5.8) * 100;
      if (scanBarRef.current) scanBarRef.current.style.height = `${Math.max(0, Math.min(100, scanPct))}%`;
      af = requestAnimationFrame(tick);
    };
    af = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(af);
  }, []);

  if (!hasWebGL) return <HolographicCortex2D />;

  const mono = { fontFamily: 'monospace', fontSize: 10, letterSpacing: 2 };
  const blue = 'rgba(0,136,255,0.85)';
  const cyan = 'rgba(0,220,255,0.7)';
  const dim  = 'rgba(0,80,160,0.6)';

  return (
    <div style={{ width:'100%',height:'100%',background:'#020814',position:'relative',overflow:'hidden' }}>
      <div ref={mountRef} style={{ width:'100%',height:'100%' }} />

      {/* Top-left HUD panel */}
      <div style={{ position:'absolute',top:16,left:16,pointerEvents:'none' }}>
        <div style={{ ...mono, color: blue, marginBottom:6, fontSize:9 }}>◈ NEURAL SCAN IN PROGRESS</div>
        <div style={{ ...mono, color: dim, fontSize:9 }}>SIGNAL INTEGRITY</div>
        <div style={{ width:120,height:3,background:'rgba(0,80,160,0.3)',marginBottom:6,borderRadius:2 }}>
          <div ref={signalBarRef} style={{ height:'100%',background:'linear-gradient(to right,#0066ff,#00ffff)',borderRadius:2,transition:'width 0.3s ease' }} />
        </div>
        <div style={{ ...mono, color: dim, fontSize:9 }}>NEURONS MAPPED</div>
        <div style={{ ...mono, color: blue, marginBottom:6 }}><span ref={neuronsRef}>0</span></div>
        <div style={{ ...mono, color: dim, fontSize:9 }}>SYNC RATE</div>
        <div style={{ ...mono, color: cyan }}><span ref={syncRef2}>—</span></div>
      </div>

      {/* Right scan bar indicator */}
      <div style={{ position:'absolute',top:16,right:16,bottom:16,width:4,background:'rgba(0,60,140,0.3)',borderRadius:2,pointerEvents:'none' }}>
        <div ref={scanBarRef} style={{ width:'100%',height:'0%',background:'linear-gradient(to bottom,rgba(0,200,255,0),rgba(0,200,255,1))',borderRadius:2,position:'absolute',bottom:0 }} />
      </div>

      {/* Bottom label */}
      <div style={{
        position:'absolute',bottom:16,left:0,right:0,textAlign:'center',
        ...mono, color:'rgba(0,100,200,0.5)',textTransform:'uppercase',fontSize:10,letterSpacing:4,pointerEvents:'none',
      }}>
        HOLOGRAPHIC&nbsp;&nbsp;CORTEX
      </div>

      {/* Corner brackets */}
      {[['top:8px','left:8px','border-top:1px solid','border-left:1px solid'],
        ['top:8px','right:8px','border-top:1px solid','border-right:1px solid'],
        ['bottom:8px','left:8px','border-bottom:1px solid','border-left:1px solid'],
        ['bottom:8px','right:8px','border-bottom:1px solid','border-right:1px solid'],
      ].map((corner, i) => (
        <div key={i} style={{
          position:'absolute',
          ...(Object.fromEntries(corner.slice(0,2).map(s => { const [k,v]=s.split(':'); return [k,v]; }))),
          width:18,height:18,
          borderTop: i<2 ? '1px solid rgba(0,136,255,0.5)' : undefined,
          borderBottom: i>=2 ? '1px solid rgba(0,136,255,0.5)' : undefined,
          borderLeft: i%2===0 ? '1px solid rgba(0,136,255,0.5)' : undefined,
          borderRight: i%2===1 ? '1px solid rgba(0,136,255,0.5)' : undefined,
          pointerEvents:'none',
        }} />
      ))}
    </div>
  );
}
