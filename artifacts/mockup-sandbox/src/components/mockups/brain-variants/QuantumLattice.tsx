/**
 * Quantum Lattice — Sacred Geometry Particle Mind.
 *
 * Concept: The brain as a quantum entity — simultaneously solid and dissolved.
 * 50k particles morph between brain shape and quantum-dissolved state,
 * driven by a "coherence" oscillation. A sacred-geometry dodecahedron
 * wireframe glows at the core. Aurora nebula fills the void.
 *
 * Palette: Deep purple void (#0D0018), gold (#FFD700), violet (#8B00FF),
 * aurora green (#00FF88), aurora magenta (#FF00AA).
 */
import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';

const R = 1.58;

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
  const cx=0, cy=-r*0.6, cz=-r*0.82;
  const dx=x-cx, dy=y-cy, dz=z-cz; const sp=r*0.4;
  const cb=Math.exp(-(dx*dx+dy*dy+dz*dz)/(2*sp*sp))*r*0.24;
  if(cb>0.0005){ const len=Math.sqrt(x*x+y*y+z*z)||1; x+=(x/len)*cb; y+=(y/len)*cb*0.5; z+=(z/len)*cb; }
  return out.set(x, y, z);
}

// Morphing particle vertex shader
const VERT_MORPH = `
  attribute vec3 aBrainPos;    // target: brain shape
  attribute vec3 aCloudPos;    // source: quantum dissolved sphere
  attribute vec3 aColor;
  attribute float aSpeed;      // individual drift speed
  uniform float uCoherence;    // 0 = fully dissolved, 1 = fully brain
  uniform float uTime;
  varying vec3 vColor;
  varying float vAlpha;
  void main(){
    // Lerp between cloud and brain with per-particle shimmer
    float shimmer = sin(aSpeed * 6.28 + uTime * aSpeed * 4.0) * 0.5 + 0.5;
    float t = clamp(uCoherence + shimmer * 0.08 - 0.04, 0.0, 1.0);
    // Ease in/out
    t = t * t * (3.0 - 2.0 * t);
    vec3 pos = mix(aCloudPos, aBrainPos, t);

    // Subtle drift when dissolved
    float drift = (1.0 - uCoherence);
    pos.x += sin(uTime * aSpeed * 0.7 + aSpeed * 10.0) * drift * 0.12;
    pos.y += cos(uTime * aSpeed * 0.5 + aSpeed * 7.3)  * drift * 0.12;
    pos.z += sin(uTime * aSpeed * 0.6 + aSpeed * 13.0) * drift * 0.10;

    vColor = aColor;
    // Alpha: brighter when coherent, more wispy when dissolved
    vAlpha = 0.4 + t * 0.55 + shimmer * 0.05;

    vec4 mv = modelViewMatrix * vec4(pos, 1.0);
    gl_PointSize = (2.5 + shimmer * 1.5 + t * 1.0) * (300.0 / -mv.z);
    gl_Position = projectionMatrix * mv;
  }
`;
const FRAG_MORPH = `
  varying vec3 vColor;
  varying float vAlpha;
  void main(){
    vec2 uv = gl_PointCoord - 0.5;
    float d = length(uv);
    if(d > 0.5) discard;
    float alpha = vAlpha * smoothstep(0.5, 0.0, d);
    gl_FragColor = vec4(vColor, alpha);
  }
`;

// Aurora ribbon shader (background bands)
const VERT_AURORA = `
  varying vec2 vUv;
  void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }
`;
const FRAG_AURORA = `
  uniform float uTime;
  varying vec2 vUv;
  void main(){
    float y = vUv.y;
    // Three aurora bands
    float g1 = exp(-pow((y - 0.35 + sin(uTime*0.4)*0.08) * 5.0, 2.0));
    float g2 = exp(-pow((y - 0.62 + cos(uTime*0.3)*0.07) * 6.0, 2.0));
    float g3 = exp(-pow((y - 0.8  + sin(uTime*0.5)*0.06) * 7.0, 2.0));
    float wave = sin(vUv.x * 12.0 + uTime * 0.6) * 0.5 + 0.5;
    vec3 col = vec3(0.0,1.0,0.55)*g1*0.28 + vec3(1.0,0.0,0.67)*g2*0.22 + vec3(0.55,0.0,1.0)*g3*0.20;
    col *= (0.7 + wave * 0.3);
    gl_FragColor = vec4(col, (g1+g2+g3) * 0.55);
  }
`;

// Dodecahedron sacred geometry wireframe shader
const VERT_SACRED = `
  varying vec3 vPos;
  void main(){ vPos=position; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }
`;
const FRAG_SACRED = `
  uniform float uTime; uniform float uOpacity;
  varying vec3 vPos;
  void main(){
    float glow = 0.5+0.5*sin(uTime*1.4+vPos.x*3.0+vPos.y*2.0+vPos.z*2.5);
    vec3 gold = vec3(1.0, 0.82, 0.1);
    gl_FragColor = vec4(gold, uOpacity * glow);
  }
`;

function makeGlowTex() {
  const sz=80, c=document.createElement('canvas');
  c.width=c.height=sz;
  const ctx=c.getContext('2d')!;
  const gr=ctx.createRadialGradient(sz/2,sz/2,0,sz/2,sz/2,sz/2);
  gr.addColorStop(0,'rgba(255,255,255,1)');
  gr.addColorStop(0.4,'rgba(255,255,255,0.5)');
  gr.addColorStop(1,'rgba(0,0,0,0)');
  ctx.fillStyle=gr; ctx.fillRect(0,0,sz,sz);
  const t=new THREE.CanvasTexture(c); t.needsUpdate=true; return t;
}

// Seeded deterministic pseudo-random (avoid Math.random for reproducibility)
function seededRand(seed: number): () => number {
  let s = seed;
  return () => {
    s = (s * 1664525 + 1013904223) & 0xffffffff;
    return (s >>> 0) / 0xffffffff;
  };
}

// ── Canvas 2D fallback ───────────────────────────────────────────────────────
function QuantumLattice2D() {
  const c2ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const cv = c2ref.current!;
    const ctx = cv.getContext('2d')!;
    let af: number;
    const resize = () => { cv.width = cv.offsetWidth * devicePixelRatio; cv.height = cv.offsetHeight * devicePixelRatio; };
    resize();
    window.addEventListener('resize', resize);
    const rand = seededRand(42);
    const tmp = new THREE.Vector3(), sh = new THREE.Vector3();
    const N = 3000;
    const palette = [[255,215,0],[0,255,136],[255,0,170],[140,0,255],[255,140,0]];
    const pts: { bx:number; by:number; cx:number; cy:number; col:number[]; spd:number }[] = [];
    for (let i = 0; i < N; i++) {
      const yy=1-(i/(N-1))*2, rr=Math.sqrt(Math.max(0,1-yy*yy)), th=Math.PI*(1+Math.sqrt(5))*i;
      tmp.set(Math.cos(th)*rr,yy,Math.sin(th)*rr);
      shapeBrain(tmp.x,tmp.y,tmp.z,1,sh);
      pts.push({ bx:sh.x, by:sh.y, cx:(rand()-0.5)*2.8, cy:(rand()-0.5)*2.8, col:palette[Math.floor(rand()*palette.length)], spd:0.3+rand()*0.7 });
    }
    let t = 0;
    const draw = () => {
      t += 0.012;
      const W = cv.width, H = cv.height;
      ctx.fillStyle = 'rgba(13,0,24,0.18)';
      ctx.fillRect(0,0,W,H);
      const coherence = 0.5 + 0.45*Math.sin(t*0.28)*Math.cos(t*0.07);
      const smooth = coherence*coherence*(3-2*coherence);
      const cx2=W/2, cy2=H/2, sc=Math.min(W,H)*0.3;
      const angle = t*0.05;
      for (const p of pts) {
        const shimmer = Math.sin(p.spd*6.28+t*p.spd*4)*0.5+0.5;
        const tt = Math.max(0,Math.min(1, smooth+shimmer*0.08-0.04));
        const px = p.cx + (p.bx - p.cx)*tt;
        const py = p.cy + (p.by - p.cy)*tt;
        const rx = px*Math.cos(angle), ry = py;
        const sx = cx2+rx*sc, sy = cy2-ry*sc*0.88;
        const alpha = 0.35 + tt*0.55 + shimmer*0.05;
        const [r,g,b] = p.col;
        ctx.beginPath();
        ctx.arc(sx,sy,0.85*devicePixelRatio,0,Math.PI*2);
        ctx.fillStyle = `rgba(${r},${g},${b},${alpha})`;
        ctx.fill();
      }
      af = requestAnimationFrame(draw);
    };
    draw();
    return () => { cancelAnimationFrame(af); window.removeEventListener('resize', resize); };
  }, []);
  return (
    <div style={{ width:'100%',height:'100%',background:'#0d0018',position:'relative' }}>
      <canvas ref={c2ref} style={{ width:'100%',height:'100%',display:'block' }} />
      <div style={{ position:'absolute',top:18,left:0,right:0,textAlign:'center',fontFamily:'monospace',fontSize:9,letterSpacing:5,color:'rgba(180,80,255,0.45)',textTransform:'uppercase',pointerEvents:'none' }}>QUANTUM&nbsp;&nbsp;LATTICE&nbsp;&nbsp;⊗&nbsp;&nbsp;MIND</div>
      <div style={{ position:'absolute',bottom:18,left:0,right:0,textAlign:'center',fontFamily:'monospace',fontSize:9,letterSpacing:5,color:'rgba(255,180,0,0.4)',textTransform:'uppercase',pointerEvents:'none' }}>COHERENCE&nbsp;&nbsp;FIELD&nbsp;&nbsp;ACTIVE</div>
    </div>
  );
}

export function QuantumLattice() {
  const ref = useRef<HTMLDivElement>(null);
  const [hasWebGL, setHasWebGL] = useState(true);

  useEffect(() => {
    if (!hasWebGL) return;
    const el = ref.current!;
    const scene = new THREE.Scene();

    const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 80);
    camera.position.set(0, 0.2, 7.5);
    camera.lookAt(0, -0.15, 0);

    let renderer!: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    } catch {
      setHasWebGL(false);
      return;
    }
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setClearColor(0x0d0018, 1);
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

    // ── Aurora background plane ────────────────────────────────────────
    const auroraGeo = new THREE.PlaneGeometry(22, 18);
    const auroraMat = new THREE.ShaderMaterial({
      uniforms: { uTime: { value: 0 } },
      vertexShader: VERT_AURORA, fragmentShader: FRAG_AURORA,
      transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide,
    });
    const auroraMesh = new THREE.Mesh(auroraGeo, auroraMat);
    auroraMesh.position.z = -7;
    auroraMesh.rotation.z = 0.1;
    scene.add(auroraMesh);

    // Second aurora layer (offset)
    const aurora2Geo = new THREE.PlaneGeometry(20, 16);
    const aurora2Mat = new THREE.ShaderMaterial({
      uniforms: { uTime: { value: 0 } },
      vertexShader: VERT_AURORA, fragmentShader: FRAG_AURORA,
      transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide,
    });
    const aurora2 = new THREE.Mesh(aurora2Geo, aurora2Mat);
    aurora2.position.set(2, -1, -6);
    aurora2.rotation.z = -0.2;
    scene.add(aurora2);

    // ── Star field ─────────────────────────────────────────────────────
    const sGeo = new THREE.BufferGeometry();
    const sPos = new Float32Array(2000 * 3);
    const rand0 = seededRand(42);
    for (let i = 0; i < 2000; i++) {
      const th = rand0() * Math.PI * 2;
      const phi = Math.acos(2 * rand0() - 1);
      const r = 25 + rand0() * 40;
      sPos[i*3]=Math.sin(phi)*Math.cos(th)*r;
      sPos[i*3+1]=Math.cos(phi)*r;
      sPos[i*3+2]=Math.sin(phi)*Math.sin(th)*r;
    }
    sGeo.setAttribute('position', new THREE.BufferAttribute(sPos, 3));
    scene.add(new THREE.Points(sGeo, new THREE.PointsMaterial({ color:0xddbbff, size:0.06, transparent:true, opacity:0.6, blending:THREE.AdditiveBlending, depthWrite:false })));

    // ── Sacred geometry: dodecahedron + icosahedron wireframes ─────────
    const sacredMat = new THREE.ShaderMaterial({
      uniforms: { uTime: { value: 0 }, uOpacity: { value: 0.35 } },
      vertexShader: VERT_SACRED, fragmentShader: FRAG_SACRED,
      transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, wireframe: true,
    });
    const dodecGeo = new THREE.DodecahedronGeometry(R * 0.72, 0);
    const dodecMesh = new THREE.Mesh(dodecGeo, sacredMat);
    scene.add(dodecMesh);

    const icoGeo = new THREE.IcosahedronGeometry(R * 0.88, 0);
    const icoMat = new THREE.ShaderMaterial({
      uniforms: { uTime: { value: 0 }, uOpacity: { value: 0.18 } },
      vertexShader: VERT_SACRED, fragmentShader: FRAG_SACRED,
      transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, wireframe: true,
    });
    scene.add(new THREE.Mesh(icoGeo, icoMat));

    // ── Lights ─────────────────────────────────────────────────────────
    scene.add(new THREE.AmbientLight(0x110022, 0.8));
    const goldLight = new THREE.PointLight(0xffcc44, 1.8, 14, 2);
    goldLight.position.set(2, 2, 3);
    scene.add(goldLight);
    const auroraLight = new THREE.PointLight(0x00ff88, 1.2, 12, 2);
    auroraLight.position.set(-2, 1, 2);
    scene.add(auroraLight);
    const voidLight = new THREE.PointLight(0x8800ff, 1.0, 10, 2);
    voidLight.position.set(0, -2, -1);
    scene.add(voidLight);

    const brainGroup = new THREE.Group();
    scene.add(brainGroup);

    // ── 50k Morphing particles ─────────────────────────────────────────
    const NP = 50000;
    const brainPositions = new Float32Array(NP * 3);
    const cloudPositions = new Float32Array(NP * 3);
    const pColors       = new Float32Array(NP * 3);
    const pSpeeds       = new Float32Array(NP);

    const rand1 = seededRand(137);
    const tmp = new THREE.Vector3(), sh = new THREE.Vector3();

    // Aurora color palette for particles
    const palette = [
      [1.0, 0.84, 0.0],   // gold
      [0.0, 1.0, 0.53],   // aurora green
      [1.0, 0.0, 0.67],   // aurora magenta
      [0.55, 0.0, 1.0],   // violet
      [1.0, 0.55, 0.0],   // amber
      [0.8, 0.9, 1.0],    // ice white
    ];

    for (let i = 0; i < NP; i++) {
      // Brain position (target)
      const yy = 1 - (i / (NP - 1)) * 2;
      const rr = Math.sqrt(Math.max(0, 1 - yy * yy));
      const th = Math.PI * (1 + Math.sqrt(5)) * i;
      tmp.set(Math.cos(th) * rr, yy, Math.sin(th) * rr);
      shapeBrain(tmp.x, tmp.y, tmp.z, R, sh);
      brainPositions[i*3]=sh.x; brainPositions[i*3+1]=sh.y; brainPositions[i*3+2]=sh.z;

      // Cloud position (dissolved quantum foam — ellipsoid with noise)
      const th2 = rand1() * Math.PI * 2;
      const phi2 = Math.acos(2 * rand1() - 1);
      const cr = 2.2 + rand1() * 1.8;
      cloudPositions[i*3]   = Math.sin(phi2) * Math.cos(th2) * cr * 1.2;
      cloudPositions[i*3+1] = Math.cos(phi2) * cr * 1.0;
      cloudPositions[i*3+2] = Math.sin(phi2) * Math.sin(th2) * cr * 1.3;

      // Per-particle speed
      pSpeeds[i] = 0.3 + rand1() * 0.7;

      // Color — mostly gold/violet, with aurora accents
      const palIdx = Math.floor(rand1() * palette.length);
      pColors[i*3]=palette[palIdx][0]; pColors[i*3+1]=palette[palIdx][1]; pColors[i*3+2]=palette[palIdx][2];
    }

    const pGeo = new THREE.BufferGeometry();
    pGeo.setAttribute('position',  new THREE.BufferAttribute(new Float32Array(NP * 3), 3)); // current (unused, GPU does morph)
    pGeo.setAttribute('aBrainPos', new THREE.BufferAttribute(brainPositions, 3));
    pGeo.setAttribute('aCloudPos', new THREE.BufferAttribute(cloudPositions, 3));
    pGeo.setAttribute('aColor',    new THREE.BufferAttribute(pColors, 3));
    pGeo.setAttribute('aSpeed',    new THREE.BufferAttribute(pSpeeds, 1));

    const morphMat = new THREE.ShaderMaterial({
      uniforms: {
        uCoherence: { value: 0.5 },
        uTime: { value: 0 },
      },
      vertexShader: VERT_MORPH,
      fragmentShader: FRAG_MORPH,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const particles = new THREE.Points(pGeo, morphMat);
    brainGroup.add(particles);

    // ── Outer golden ring (torus) ──────────────────────────────────────
    const torusGeo = new THREE.TorusGeometry(R * 1.65, 0.015, 8, 100);
    const torusMat = new THREE.ShaderMaterial({
      uniforms: { uTime: { value: 0 }, uOpacity: { value: 0.5 } },
      vertexShader: VERT_SACRED, fragmentShader: FRAG_SACRED,
      transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
    });
    const torus = new THREE.Mesh(torusGeo, torusMat);
    torus.rotation.x = Math.PI / 2.2;
    brainGroup.add(torus);

    // Second tilted ring
    const torus2 = new THREE.Mesh(
      new THREE.TorusGeometry(R * 1.75, 0.010, 8, 100),
      new THREE.ShaderMaterial({
        uniforms: { uTime: { value: 0 }, uOpacity: { value: 0.3 } },
        vertexShader: VERT_SACRED, fragmentShader: FRAG_SACRED,
        transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
      })
    );
    torus2.rotation.x = Math.PI / 3.5;
    torus2.rotation.y = Math.PI / 6;
    brainGroup.add(torus2);

    // ── Slow camera orbit ─────────────────────────────────────────────
    let camAngle = 0;
    const clock = new THREE.Clock();

    renderer.setAnimationLoop(() => {
      const t = clock.getElapsedTime();

      // Camera orbit
      camAngle += 0.0014;
      camera.position.x = Math.sin(camAngle) * 7.5;
      camera.position.z = Math.cos(camAngle) * 7.5;
      camera.position.y = Math.sin(camAngle * 0.4) * 0.6 + 0.2;
      camera.lookAt(0, -0.15, 0);

      // Coherence oscillation: brain forms ↔ dissolves
      // Pattern: slow sine with faster micro-wobble, range [0.05, 0.95]
      const cohere = 0.5 + 0.45 * Math.sin(t * 0.28) * Math.cos(t * 0.07);
      morphMat.uniforms.uCoherence.value = Math.max(0.05, Math.min(0.95, cohere));
      morphMat.uniforms.uTime.value = t;

      // Brain group rotation
      brainGroup.rotation.y = t * 0.07;
      brainGroup.rotation.x = Math.sin(t * 0.18) * 0.04;
      brainGroup.position.y = Math.sin(t * 0.45) * 0.07;

      // Sacred geometry counter-rotates slowly
      dodecMesh.rotation.y = -t * 0.055;
      dodecMesh.rotation.x = t * 0.03;
      dodecMesh.position.copy(brainGroup.position);
      sacredMat.uniforms.uTime.value = t;
      icoMat.uniforms.uTime.value = t;
      sacredMat.uniforms.uOpacity.value = 0.20 + cohere * 0.22;
      icoMat.uniforms.uOpacity.value = 0.10 + (1 - cohere) * 0.18;

      // Torus rings
      torus.rotation.z = t * 0.09;
      torus2.rotation.z = -t * 0.07;
      (torus.material as THREE.ShaderMaterial).uniforms.uTime.value = t;
      (torus2.material as THREE.ShaderMaterial).uniforms.uTime.value = t;
      (torus.material as THREE.ShaderMaterial).uniforms.uOpacity.value = 0.3 + cohere * 0.35;
      (torus2.material as THREE.ShaderMaterial).uniforms.uOpacity.value = 0.2 + cohere * 0.25;

      // Aurora
      auroraMat.uniforms.uTime.value = t;
      aurora2Mat.uniforms.uTime.value = t * 1.3 + 1.2;

      // Lights pulse with coherence
      goldLight.intensity = 1.4 + cohere * 0.8 + Math.sin(t * 2.5) * 0.3;
      auroraLight.intensity = 0.8 + (1 - cohere) * 0.8 + Math.sin(t * 1.8) * 0.2;
      voidLight.intensity = 0.7 + (1 - cohere) * 0.5;

      renderer.render(scene, camera);
    });

    return () => {
      renderer.setAnimationLoop(null);
      ro.disconnect();
      renderer.dispose();
    };
  }, []);

  if (!hasWebGL) return <QuantumLattice2D />;

  return (
    <div style={{ width:'100%', height:'100%', background:'#0d0018', position:'relative' }}>
      <div ref={ref} style={{ width:'100%', height:'100%' }} />

      {/* Coherence label — top center */}
      <div style={{
        position:'absolute', top:18, left:0, right:0, textAlign:'center',
        fontFamily:'monospace', fontSize:9, letterSpacing:5, color:'rgba(180,80,255,0.45)',
        textTransform:'uppercase', pointerEvents:'none',
      }}>
        QUANTUM&nbsp;&nbsp;LATTICE&nbsp;&nbsp;⊗&nbsp;&nbsp;MIND
      </div>

      {/* Bottom label */}
      <div style={{
        position:'absolute', bottom:18, left:0, right:0, textAlign:'center',
        fontFamily:'monospace', fontSize:9, letterSpacing:5,
        color:'rgba(255,180,0,0.4)', textTransform:'uppercase', pointerEvents:'none',
      }}>
        COHERENCE&nbsp;&nbsp;FIELD&nbsp;&nbsp;ACTIVE
      </div>
    </div>
  );
}
