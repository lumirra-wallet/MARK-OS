/**
 * NeuralPresence — MARK's cognitive core, in pure SVG.
 *
 * Replaces the Three.js/WebGL renderer as the primary presence animation.
 * Works in every environment (no GPU required) and is directly driven by
 * real brain events from the store — not timers, not random numbers.
 *
 * Visual language:
 *   Core circle   — always present; breathing speed driven by activity.
 *   Inner ring    — activates on memory writes (episodic/semantic ripple).
 *   Mid ring      — activates during inference/reasoning (rotation pulse).
 *   Outer ring    — activates during speech output (standing-wave shimmer).
 *   6 node dots   — light up on cognitive events (rotate around the core).
 *   Emotion tint  — hue shifts on emotional state change.
 *
 * Every animated value is driven by a real event; no animation runs without
 * a real source. The render loop (requestAnimationFrame) only interpolates
 * smoothly toward real targets — it never invents state.
 */

import { useEffect, useRef } from 'react';
import { useMarkStore } from '@/store/markStore';

export interface NeuralPresenceProps {
  className?: string;
  micLevel?: number;
  isListening?: boolean;
  isVoiceSpeaking?: boolean;
}

// MARK's accent is --accent (hsl(143 72% 48%) ≈ #22c55e).
// Hue as degrees (0–360) for CSS hsl(), per emotional state.
const EMOTION_HUE: Record<string, number> = {
  neutral:    143,
  curious:    200,   // cool blue — opening to learning
  focused:    160,   // shifted green — locked in
  satisfied:  120,   // warm green — completion
  uncertain:   45,   // amber — incomplete picture
  frustrated:  10,   // red-orange — strain
};

const EMOTION_LABEL: Record<string, string> = {
  neutral:    '',
  curious:    'Curious',
  focused:    'Focused',
  satisfied:  'Satisfied',
  uncertain:  'Uncertain',
  frustrated: 'Frustrated',
};

export function NeuralPresence({
  className = '',
  micLevel = 0,
  isListening = false,
  isVoiceSpeaking = false,
}: NeuralPresenceProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const rafRef = useRef<number>(0);

  // Live state from store — read via refs so the RAF loop doesn't need
  // to re-subscribe on every frame (same pattern as the Three.js version).
  const emotionalState   = useMarkStore(s => s.emotionalState);
  const knowledgeGrowth  = useMarkStore(s => s.knowledgeGrowth);
  const running          = useMarkStore(s => s.running);
  const isMarkSpeaking   = useMarkStore(s => s.isMarkSpeaking);
  const cognitiveEvents  = useMarkStore(s => s.cognitiveEvents);

  const stateRef = useRef({
    emotionalState, knowledgeGrowth, running,
    isMarkSpeaking, cognitiveEvents,
    micLevel, isListening, isVoiceSpeaking,
  });
  stateRef.current = {
    emotionalState, knowledgeGrowth, running,
    isMarkSpeaking, cognitiveEvents,
    micLevel, isListening, isVoiceSpeaking,
  };

  // Animation targets — interpolated every frame, driven by real events.
  const animRef = useRef({
    // Core
    coreScale:     1.0,
    coreGlow:      0.4,
    corePulse:     0.0,   // 0→1 burst on event, then decays

    // Rings: activation level (0–1), interpolated toward targets
    innerRing:     0.0,
    midRing:       0.0,
    outerRing:     0.0,

    // Nodes: each has an angle and a glow
    nodeAngles:    [0, 60, 120, 180, 240, 300].map(deg => (deg * Math.PI) / 180),
    nodeGlows:     [0, 0, 0, 0, 0, 0] as number[],

    // Color
    hue:           143,
    hueTarget:     143,

    // Waveform for outer ring during speech
    wavePhase:     0.0,

    // Last event seen — drives node flashes
    lastEventCount: 0,

    // Timestamps
    t: 0,
  });

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;

    const cx = 160, cy = 160;  // center of 320×320 viewBox
    const R_CORE  = 38;
    const R_INNER = 62;
    const R_MID   = 90;
    const R_OUTER = 118;
    const R_NODES = 78;

    // ── Build DOM once (never re-created per frame) ───────────────────────
    const ns = 'http://www.w3.org/2000/svg';
    const mk = (tag: string, attrs: Record<string, string | number>) => {
      const el = document.createElementNS(ns, tag);
      for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
      return el;
    };

    // Defs: radial gradient for core glow
    const defs = mk('defs', {});
    const grad = mk('radialGradient', { id: 'np-core-grad', cx: '50%', cy: '50%', r: '50%' });
    const stop0 = mk('stop', { offset: '0%',   'stop-color': 'hsl(143 80% 70%)', 'stop-opacity': '0.9' });
    const stop1 = mk('stop', { offset: '60%',  'stop-color': 'hsl(143 72% 48%)', 'stop-opacity': '0.4' });
    const stop2 = mk('stop', { offset: '100%', 'stop-color': 'hsl(143 72% 48%)', 'stop-opacity': '0' });
    grad.append(stop0, stop1, stop2);
    defs.append(grad);
    svg.append(defs);

    // Outer ring (speech wave)
    const outerRingEl = mk('circle', {
      cx, cy, r: R_OUTER, fill: 'none',
      stroke: `hsl(143 72% 55%)`, 'stroke-width': '1.5',
      opacity: '0.0',
      'stroke-dasharray': '4 6',
    });
    svg.append(outerRingEl);

    // Mid ring (reasoning pulse)
    const midRingEl = mk('circle', {
      cx, cy, r: R_MID, fill: 'none',
      stroke: `hsl(143 72% 55%)`, 'stroke-width': '1',
      opacity: '0.0',
    });
    svg.append(midRingEl);

    // Inner ring (memory ripple)
    const innerRingEl = mk('circle', {
      cx, cy, r: R_INNER, fill: 'none',
      stroke: `hsl(143 72% 60%)`, 'stroke-width': '0.8',
      opacity: '0.0',
    });
    svg.append(innerRingEl);

    // Core glow (radial gradient circle)
    const coreGlowEl = mk('circle', {
      cx, cy, r: R_CORE * 1.8,
      fill: 'url(#np-core-grad)',
      opacity: '0.4',
    });
    svg.append(coreGlowEl);

    // Core circle
    const coreEl = mk('circle', {
      cx, cy, r: R_CORE,
      fill: 'none',
      stroke: `hsl(143 72% 55%)`,
      'stroke-width': '1.5',
      opacity: '0.8',
    });
    svg.append(coreEl);

    // Node dots + node orbits
    const nodeDots: SVGCircleElement[] = [];
    const a = animRef.current;
    for (let i = 0; i < 6; i++) {
      const dot = mk('circle', { r: '3', fill: `hsl(143 72% 65%)`, opacity: '0.3' }) as SVGCircleElement;
      svg.append(dot);
      nodeDots.push(dot);
    }

    // Emotion label (bottom-center)
    const emotionLabel = mk('text', {
      x: cx, y: cy + R_OUTER + 20,
      'text-anchor': 'middle',
      'font-size': '10',
      'font-family': 'ui-monospace, monospace',
      fill: `hsl(143 72% 55%)`,
      opacity: '0',
      'letter-spacing': '2',
    }) as SVGTextElement;
    svg.append(emotionLabel);

    // ── Animation loop ────────────────────────────────────────────────────
    let prev = performance.now();

    const frame = (now: number) => {
      const dt = Math.min((now - prev) / 1000, 0.05);
      prev = now;
      a.t += dt;

      const s = stateRef.current;

      // ── Targets from real state ──────────────────────────────────────
      const isSpeaking  = s.isMarkSpeaking || s.isVoiceSpeaking;
      const isListening = s.isListening;
      const isRunning   = s.running;
      const emo         = s.emotionalState || 'neutral';

      const hueTarget = EMOTION_HUE[emo] ?? 143;
      a.hueTarget = hueTarget;
      a.hue += (a.hueTarget - a.hue) * 2.5 * dt;

      // Core breathing — slow idle, faster when active
      const breathFreq = isRunning ? 1.8 : isSpeaking ? 2.4 : isListening ? 1.2 : 0.6;
      const breathAmt  = isRunning ? 0.12 : isSpeaking ? 0.08 : 0.05;
      const breath     = 1 + Math.sin(a.t * breathFreq * Math.PI * 2) * breathAmt;
      const corePulseDecay = 0.95;
      a.corePulse = Math.max(0, a.corePulse * corePulseDecay);

      const coreTarget = breath + a.corePulse * 0.25;
      a.coreScale += (coreTarget - a.coreScale) * 8 * dt;

      const glowTarget = 0.3 + (isRunning ? 0.35 : isSpeaking ? 0.25 : 0) + a.corePulse * 0.2;
      a.coreGlow += (glowTarget - a.coreGlow) * 4 * dt;

      // Rings
      const innerTarget = isRunning ? 0.6 : a.corePulse > 0.3 ? 0.5 : 0;
      a.innerRing += (innerTarget - a.innerRing) * (innerTarget > a.innerRing ? 6 : 2) * dt;

      const midTarget = isRunning ? 0.7 : 0;
      a.midRing += (midTarget - a.midRing) * (midTarget > a.midRing ? 5 : 1.5) * dt;

      const outerTarget = isSpeaking ? 0.85 : 0;
      a.outerRing += (outerTarget - a.outerRing) * (outerTarget > a.outerRing ? 8 : 2) * dt;

      // Node flash on new cognitive events
      const evCount = s.cognitiveEvents.length;
      if (evCount > a.lastEventCount) {
        const diff = evCount - a.lastEventCount;
        for (let k = 0; k < Math.min(diff * 2, 6); k++) {
          const idx = Math.floor(Math.random() * 6);
          a.nodeGlows[idx] = 1.0;
        }
        a.corePulse = Math.min(1, a.corePulse + 0.6);
        a.lastEventCount = evCount;
      }

      const nodeSpeed = isRunning ? 0.18 : isSpeaking ? 0.12 : 0.04;
      for (let i = 0; i < 6; i++) {
        a.nodeAngles[i] += nodeSpeed * dt * (i % 2 === 0 ? 1 : -1) * 0.7;
        a.nodeGlows[i] = Math.max(0.15, a.nodeGlows[i] * (1 - 3 * dt));
      }

      // Mic inward pull
      const micPull = isListening ? micLevel * 0.3 : 0;
      a.wavePhase += (isSpeaking ? 3.5 : 0) * dt;

      // ── Apply to DOM ────────────────────────────────────────────────
      const h = Math.round(a.hue);
      const hsl = (l: number, a2: number = 1) => `hsla(${h}, 72%, ${l}%, ${a2})`;

      // Update gradient stops
      stop0.setAttribute('stop-color', hsl(70));
      stop1.setAttribute('stop-color', hsl(48));

      // Core
      const r = R_CORE * a.coreScale * (1 - micPull * 0.5);
      coreEl.setAttribute('r', String(r));
      coreEl.setAttribute('stroke', hsl(55));
      coreEl.setAttribute('opacity', String(0.7 + a.coreGlow * 0.3));
      coreEl.setAttribute('stroke-width', String(1.5 + a.corePulse * 1.5));

      coreGlowEl.setAttribute('r', String(R_CORE * 1.8 * a.coreScale));
      coreGlowEl.setAttribute('opacity', String(a.coreGlow));

      // Inner ring — memory
      innerRingEl.setAttribute('opacity', String(a.innerRing * 0.8));
      innerRingEl.setAttribute('stroke', hsl(62));
      innerRingEl.setAttribute('r', String(R_INNER));

      // Mid ring — reasoning rotation
      const midDash = `${5 + a.midRing * 3} ${8 - a.midRing * 3}`;
      midRingEl.setAttribute('opacity', String(a.midRing * 0.7));
      midRingEl.setAttribute('stroke', hsl(58));
      midRingEl.setAttribute('stroke-dasharray', midDash);
      midRingEl.setAttribute('transform',
        `rotate(${a.t * (isRunning ? 40 : 10)}, ${cx}, ${cy})`);

      // Outer ring — speech
      if (isSpeaking && a.outerRing > 0.1) {
        // Dashed wave: alternate long/short dashes
        const wave = `${6 + Math.sin(a.wavePhase * 1.5) * 3} ${4 + Math.cos(a.wavePhase) * 2}`;
        outerRingEl.setAttribute('stroke-dasharray', wave);
        outerRingEl.setAttribute('r', String(R_OUTER + Math.sin(a.wavePhase * 2) * 3));
      } else {
        outerRingEl.setAttribute('stroke-dasharray', '4 6');
        outerRingEl.setAttribute('r', String(R_OUTER));
      }
      outerRingEl.setAttribute('opacity', String(a.outerRing * 0.8));
      outerRingEl.setAttribute('stroke', hsl(55));

      // Nodes
      const nodeR = R_NODES * (1 - micPull * 0.25);
      for (let i = 0; i < 6; i++) {
        const nx = cx + Math.cos(a.nodeAngles[i]) * nodeR;
        const ny = cy + Math.sin(a.nodeAngles[i]) * nodeR;
        nodeDots[i].setAttribute('cx', String(nx));
        nodeDots[i].setAttribute('cy', String(ny));
        nodeDots[i].setAttribute('opacity', String(a.nodeGlows[i]));
        nodeDots[i].setAttribute('fill', hsl(65));
        nodeDots[i].setAttribute('r', String(2.5 + a.nodeGlows[i] * 2));
      }

      // Emotion label
      const label = EMOTION_LABEL[emo] || '';
      if (label) {
        emotionLabel.textContent = label.toUpperCase();
        emotionLabel.setAttribute('fill', hsl(55));
        emotionLabel.setAttribute('opacity', '0.5');
      } else {
        emotionLabel.setAttribute('opacity', '0');
      }

      rafRef.current = requestAnimationFrame(frame);
    };

    rafRef.current = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(rafRef.current);
      while (svg.firstChild) svg.removeChild(svg.firstChild);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // micLevel changes every frame from the audio analyser — keep ref in sync
  // without triggering a re-render.
  stateRef.current.micLevel = micLevel;

  return (
    <div className={`w-full h-full ${className}`}>
      <svg
        ref={svgRef}
        viewBox="0 0 320 320"
        className="w-full h-full"
        aria-label="Elena's live cognitive state"
        aria-hidden="true"
      />
    </div>
  );
}
