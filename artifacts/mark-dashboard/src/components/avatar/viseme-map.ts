/**
 * MARK Avatar — Viseme to Mouth Shape Mapping
 * Based on standard viseme sets (SAPI, Polly, Google TTS)
 */

export type VisemeId =
  | 'sil'      // Silence
  | 'PP'       // P, B, M (bilabial)
  | 'FF'       // F, V (labiodental)
  | 'TH'       // TH (interdental)
  | 'DD'       // T, D, N, S, Z (alveolar)
  | 'kk'       // K, G, NG (velar)
  | 'CH'       // CH, J, SH, ZH (postalveolar)
  | 'SS'       // S, Z (sibilant)
  | 'nn'       // N, M, NG (nasal)
  | 'RR'       // R, L (approximant)
  | 'aa'       // A (father) - open front unrounded
  | 'ae'       // AE (cat) - open front unrounded small
  | 'ah'       // AH (father US) - open back unrounded
  | 'ao'       // AW (law) - open back rounded
  | 'eh'       // EH (bed) - mid front unrounded
  | 'ey'       // IY (see) - close front unrounded
  | 'ih'       // IH (sit) - near-close front
  | 'oh'       // OH (go) - mid back rounded
  | 'ow'       // OW (boat) - diphthong
  | 'uh'       // UH (book) - near-close back
  | 'uw'       // UW (food) - close back rounded
  | 'er'       // ER (bird) - rhotic
  | 'ax'       // Schwa (about)
  | 'ix';      // IX (roses) - near-close front lax

/** Mouth shape keys — correspond to SVG path IDs in the avatar */
export type MouthShapeKey =
  | 'closed'
  | 'bilabial_closed'
  | 'labiodental'
  | 'interdental'
  | 'alveolar'
  | 'velar'
  | 'postalveolar'
  | 'sibilant'
  | 'nasal'
  | 'approximant'
  | 'open_front_unrounded'
  | 'open_front_unrounded_small'
  | 'open_back_unrounded'
  | 'open_back_rounded'
  | 'mid_front_unrounded'
  | 'close_front_unrounded'
  | 'near_close_front'
  | 'mid_back_rounded'
  | 'diphthong_oh'
  | 'near_close_back'
  | 'close_back_rounded'
  | 'rhotic'
  | 'schwa'
  | 'near_close_front_lax';

/**
 * Primary viseme → mouth shape mapping
 * One viseme maps to one canonical mouth shape
 */
export const VISEME_TO_MOUTH_SHAPE: Record<VisemeId, MouthShapeKey> = {
  sil: 'closed',
  PP: 'bilabial_closed',
  FF: 'labiodental',
  TH: 'interdental',
  DD: 'alveolar',
  kk: 'velar',
  CH: 'postalveolar',
  SS: 'sibilant',
  nn: 'nasal',
  RR: 'approximant',
  aa: 'open_front_unrounded',
  ae: 'open_front_unrounded_small',
  ah: 'open_back_unrounded',
  ao: 'open_back_rounded',
  eh: 'mid_front_unrounded',
  ey: 'close_front_unrounded',
  ih: 'near_close_front',
  oh: 'mid_back_rounded',
  ow: 'diphthong_oh',
  uh: 'near_close_back',
  uw: 'close_back_rounded',
  er: 'rhotic',
  ax: 'schwa',
  ix: 'near_close_front_lax',
};

/**
 * Viseme groups for coarticulation smoothing
 * Visemes in the same group share similar mouth configurations
 */
export const VISEME_GROUPS: Record<string, VisemeId[]> = {
  bilabial: ['PP'],
  labiodental: ['FF'],
  interdental: ['TH'],
  alveolar: ['DD', 'SS'],
  postalveolar: ['CH'],
  velar: ['kk'],
  nasal: ['nn'],
  approximant: ['RR'],
  vowel_open_front: ['aa', 'ae'],
  vowel_open_back: ['ah', 'ao'],
  vowel_mid_front: ['eh', 'ey', 'ih', 'ix'],
  vowel_mid_back: ['oh', 'ow'],
  vowel_close_back: ['uh', 'uw'],
  vowel_rhotic: ['er'],
  vowel_schwa: ['ax'],
  silence: ['sil'],
};

/**
 * Reverse mapping: mouth shape → visemes that use it
 */
export const MOUTH_SHAPE_TO_VISEMES: Record<MouthShapeKey, VisemeId[]> = (() => {
  const reverse: Record<MouthShapeKey, VisemeId[]> = {} as Record<MouthShapeKey, VisemeId[]>;
  for (const [viseme, shape] of Object.entries(VISEME_TO_MOUTH_SHAPE)) {
    if (!reverse[shape]) reverse[shape] = [];
    reverse[shape].push(viseme as VisemeId);
  }
  return reverse;
})();

/**
 * Mouth shape geometry parameters for procedural generation
 * Used when SVG paths aren't available (Canvas fallback)
 */
export interface MouthShapeGeometry {
  width: number;      // Horizontal span (units)
  height: number;     // Vertical span (units)
  upperLipCurve: number;  // -1 to 1 (negative = upward curve)
  lowerLipCurve: number;  // -1 to 1 (positive = downward curve)
  cornerPull: number;     // 0 to 1 (0 = neutral, 1 = pulled back)
  aperture: number;       // 0 to 1 (0 = closed, 1 = max open)
  rounding: number;       // 0 to 1 (0 = spread, 1 = rounded)
}

export const MOUTH_SHAPE_GEOMETRY: Record<MouthShapeKey, MouthShapeGeometry> = {
  closed: { width: 30, height: 4, upperLipCurve: 0.1, lowerLipCurve: 0.1, cornerPull: 0, aperture: 0, rounding: 0.3 },
  bilabial_closed: { width: 28, height: 6, upperLipCurve: 0.2, lowerLipCurve: 0.2, cornerPull: 0.1, aperture: 0, rounding: 0.4 },
  labiodental: { width: 28, height: 8, upperLipCurve: 0.05, lowerLipCurve: 0.4, cornerPull: 0.05, aperture: 0.2, rounding: 0.2 },
  interdental: { width: 24, height: 10, upperLipCurve: -0.1, lowerLipCurve: 0.3, cornerPull: 0, aperture: 0.3, rounding: 0.1 },
  alveolar: { width: 32, height: 14, upperLipCurve: 0, lowerLipCurve: 0.35, cornerPull: 0.1, aperture: 0.5, rounding: 0.1 },
  velar: { width: 24, height: 18, upperLipCurve: -0.15, lowerLipCurve: 0.5, cornerPull: -0.05, aperture: 0.7, rounding: 0.1 },
  postalveolar: { width: 28, height: 15, upperLipCurve: -0.1, lowerLipCurve: 0.45, cornerPull: 0.05, aperture: 0.6, rounding: 0.2 },
  sibilant: { width: 32, height: 10, upperLipCurve: 0.05, lowerLipCurve: 0.3, cornerPull: 0.2, aperture: 0.35, rounding: 0.05 },
  nasal: { width: 26, height: 6, upperLipCurve: 0.1, lowerLipCurve: 0.15, cornerPull: 0.05, aperture: 0.1, rounding: 0.3 },
  approximant: { width: 30, height: 10, upperLipCurve: 0, lowerLipCurve: 0.3, cornerPull: 0.05, aperture: 0.4, rounding: 0.2 },
  open_front_unrounded: { width: 36, height: 24, upperLipCurve: -0.2, lowerLipCurve: 0.6, cornerPull: 0.3, aperture: 1.0, rounding: 0 },
  open_front_unrounded_small: { width: 32, height: 18, upperLipCurve: -0.15, lowerLipCurve: 0.5, cornerPull: 0.25, aperture: 0.8, rounding: 0.05 },
  open_back_unrounded: { width: 32, height: 20, upperLipCurve: -0.15, lowerLipCurve: 0.55, cornerPull: 0.15, aperture: 0.85, rounding: 0.1 },
  open_back_rounded: { width: 28, height: 18, upperLipCurve: -0.1, lowerLipCurve: 0.5, cornerPull: 0, aperture: 0.8, rounding: 0.7 },
  mid_front_unrounded: { width: 30, height: 14, upperLipCurve: -0.1, lowerLipCurve: 0.4, cornerPull: 0.2, aperture: 0.55, rounding: 0.1 },
  close_front_unrounded: { width: 26, height: 10, upperLipCurve: 0, lowerLipCurve: 0.25, cornerPull: 0.4, aperture: 0.3, rounding: 0 },
  near_close_front: { width: 28, height: 12, upperLipCurve: -0.05, lowerLipCurve: 0.35, cornerPull: 0.3, aperture: 0.45, rounding: 0.05 },
  mid_back_rounded: { width: 24, height: 14, upperLipCurve: -0.1, lowerLipCurve: 0.4, cornerPull: -0.05, aperture: 0.55, rounding: 0.6 },
  diphthong_oh: { width: 28, height: 16, upperLipCurve: -0.1, lowerLipCurve: 0.45, cornerPull: 0.05, aperture: 0.65, rounding: 0.5 },
  near_close_back: { width: 22, height: 10, upperLipCurve: -0.05, lowerLipCurve: 0.3, cornerPull: -0.1, aperture: 0.35, rounding: 0.6 },
  close_back_rounded: { width: 20, height: 8, upperLipCurve: 0, lowerLipCurve: 0.25, cornerPull: -0.15, aperture: 0.25, rounding: 0.8 },
  rhotic: { width: 26, height: 12, upperLipCurve: -0.05, lowerLipCurve: 0.35, cornerPull: 0.05, aperture: 0.45, rounding: 0.4 },
  schwa: { width: 24, height: 8, upperLipCurve: 0.05, lowerLipCurve: 0.2, cornerPull: 0, aperture: 0.3, rounding: 0.3 },
  near_close_front_lax: { width: 26, height: 10, upperLipCurve: 0, lowerLipCurve: 0.3, cornerPull: 0.25, aperture: 0.35, rounding: 0.1 },
};

/**
 * Emotional expression modifiers — applied on top of viseme shape
 */
export interface ExpressionModifiers {
  smile: number;        // -1 (frown) to 1 (smile) — pulls corners
  frown: number;        // 0 to 1 — lowers corners, raises center
  jawDrop: number;      // 0 to 1 — additional vertical opening
  lipPucker: number;    // 0 to 1 — pushes lips forward (rounding)
  lipPress: number;     // 0 to 1 — presses lips together (tension)
  browRaise: number;    // -1 to 1 — eyebrow position
  browFurrow: number;   // 0 to 1 — brow angle
  squint: number;       // 0 to 1 — eye narrowing
  gazeX: number;        // -1 to 1 — horizontal gaze
  gazeY: number;        // -1 to 1 — vertical gaze
}

export const DEFAULT_EXPRESSION: ExpressionModifiers = {
  smile: 0,
  frown: 0,
  jawDrop: 0,
  lipPucker: 0,
  lipPress: 0,
  browRaise: 0,
  browFurrow: 0,
  squint: 0,
  gazeX: 0,
  gazeY: 0,
};

/**
 * Preset emotional states
 */
export const EXPRESSION_PRESETS: Record<string, ExpressionModifiers> = {
  neutral: { ...DEFAULT_EXPRESSION },
  happy: { ...DEFAULT_EXPRESSION, smile: 0.7, browRaise: 0.2, squint: 0.15 },
  sad: { ...DEFAULT_EXPRESSION, frown: 0.6, browRaise: -0.3, jawDrop: 0.1 },
  angry: { ...DEFAULT_EXPRESSION, frown: 0.4, browFurrow: 0.8, lipPress: 0.5, squint: 0.3 },
  surprised: { ...DEFAULT_EXPRESSION, browRaise: 1, jawDrop: 0.5, smile: -0.2 },
  thinking: { ...DEFAULT_EXPRESSION, browFurrow: 0.4, gazeY: -0.2, lipPress: 0.2 },
  confused: { ...DEFAULT_EXPRESSION, browRaise: 0.5, browFurrow: 0.3, gazeX: 0.2 },
  skeptical: { ...DEFAULT_EXPRESSION, browRaise: 0.4, smile: -0.2, squint: 0.2 },
  concentrating: { ...DEFAULT_EXPRESSION, browFurrow: 0.6, squint: 0.2, lipPress: 0.3 },
  speaking: { ...DEFAULT_EXPRESSION, jawDrop: 0.1 },
};

/**
 * Interpolate between two mouth shape geometries
 */
export function interpolateMouthGeometry(
  a: MouthShapeGeometry,
  b: MouthShapeGeometry,
  t: number
): MouthShapeGeometry {
  const lerp = (x: number, y: number) => x + (y - x) * t;
  return {
    width: lerp(a.width, b.width),
    height: lerp(a.height, b.height),
    upperLipCurve: lerp(a.upperLipCurve, b.upperLipCurve),
    lowerLipCurve: lerp(a.lowerLipCurve, b.lowerLipCurve),
    cornerPull: lerp(a.cornerPull, b.cornerPull),
    aperture: lerp(a.aperture, b.aperture),
    rounding: lerp(a.rounding, b.rounding),
  };
}

/**
 * Apply expression modifiers to a base mouth geometry
 */
export function applyExpressionToGeometry(
  base: MouthShapeGeometry,
  expr: ExpressionModifiers
): MouthShapeGeometry {
  return {
    width: base.width * (1 + expr.smile * 0.15 - expr.frown * 0.1),
    height: base.height * (1 + expr.jawDrop * 0.5 + expr.lipPucker * 0.2),
    upperLipCurve: base.upperLipCurve + expr.lipPress * 0.2 - expr.smile * 0.1,
    lowerLipCurve: base.lowerLipCurve + expr.jawDrop * 0.4 + expr.lipPucker * 0.15,
    cornerPull: base.cornerPull + expr.smile * 0.5 - expr.frown * 0.3,
    aperture: Math.min(1, base.aperture + expr.jawDrop * 0.3),
    rounding: Math.min(1, Math.max(0, base.rounding + expr.lipPucker * 0.4 - expr.smile * 0.2)),
  };
}

/**
 * Get mouth shape key for a viseme, with fallback
 */
export function getMouthShapeForViseme(viseme: string): MouthShapeKey {
  return VISEME_TO_MOUTH_SHAPE[viseme as VisemeId] ?? 'closed';
}

/**
 * Check if a viseme represents silence/pause
 */
export function isSilenceViseme(viseme: string): boolean {
  return viseme === 'sil';