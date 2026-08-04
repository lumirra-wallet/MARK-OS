/**
 * MARK Avatar — SVG Layered Component
 * Renders face, eyes, mouth as composable layers with viseme-driven lip-sync
 */

import { motion, AnimatePresence } from 'framer-motion';
import {
  VisemeId,
  MouthShapeKey,
  ExpressionModifiers,
  DEFAULT_EXPRESSION,
  EXPRESSION_PRESETS,
  getMouthShapeForViseme,
  MOUTH_SHAPE_GEOMETRY,
  applyExpressionToGeometry,
  interpolateMouthGeometry,
} from './viseme-map';

export interface MarkAvatarSVGProps {
  /** Current viseme for lip-sync */
  viseme: VisemeId;
  /** Emotional expression state */
  expression?: keyof typeof EXPRESSION_PRESETS | ExpressionModifiers;
  /** Gaze direction (-1 to 1 each axis) */
  gaze?: { x: number; y: number };
  /** Blink state (0-1) */
  blink?: number;
  /** Overall avatar size in pixels */
  size?: number;
  /** Skin tone CSS variable or hex */
  skinTone?: string;
  /** Iris color */
  irisColor?: string;
  /** Accent color for effects */
  accentColor?: string;
  /** Enable thinking pulse animation */
  isThinking?: boolean;
  /** Enable speaking ring animation */
  isSpeaking?: boolean;
  /** Custom className */
  className?: string;
}

/** Predefined mouth shape SVG paths (centered at 0,0, ~30x20 units) */
const MOUTH_SHAPE_PATHS: Record<MouthShapeKey, string> = {
  closed: 'M-15,0 Q0,-2 15,0 Q0,2 -15,0',
  bilabial_closed: 'M-14,0 Q0,-3 14,0 Q0,4 -14,0',
  labiodental: 'M-14,-2 Q0,-6 14,-2 L14,4 Q0,6 -14,4 Z',
  interdental: 'M-12,-1 Q0,-4 12,-1 L12,5 Q0,6 -12,5 Z',
  alveolar: 'M-16,-3 Q0,-8 16,-3 L16,6 Q0,10 -16,6 Z',
  velar: 'M-12,-5 Q0,-12 12,-5 L12,8 Q0,14 -12,8 Z',
  postalveolar: 'M-14,-4 Q0,-10 14,-4 L14,7 Q0,12 -14,7 Z',
  sibilant: 'M-16,-2 Q0,-6 16,-2 L16,5 Q0,7 -16,5 Z',
  nasal: 'M-13,0 Q0,-2 13,0 Q0,3 -13,0',
  approximant: 'M-15,-1 Q0,-5 15,-1 L15,4 Q0,6 -15,4 Z',
  open_front_unrounded: 'M-18,-6 Q0,-18 18,-6 L18,12 Q0,20 -18,12 Z',
  open_front_unrounded_small: 'M-16,-4 Q0,-14 16,-4 L16,10 Q0,16 -16,10 Z',
  open_back_unrounded: 'M-16,-5 Q0,-15 16,-5 L16,11 Q0,17 -16,11 Z',
  open_back_rounded: 'M-14,-4 Q0,-14 14,-4 L14,10 Q0,16 -14,10 Z',
  mid_front_unrounded: 'M-15,-3 Q0,-10 15,-3 L15,8 Q0,12 -15,8 Z',
  close_front_unrounded: 'M-13,-2 Q0,-6 13,-2 L13,5 Q0,7 -13,5 Z',
  near_close_front: 'M-14,-2 Q0,-8 14,-2 L14,6 Q0,9 -14,6 Z',
  mid_back_rounded: 'M-12,-3 Q0,-10 12,-3 L12,7 Q0,11 -12,7 Z',
  diphthong_oh: 'M-14,-3 Q0,-11 14,-3 L14,8 Q0,12 -14,8 Z',
  near_close_back: 'M-11,-2 Q0,-7 11,-2 L11,5 Q0,8 -11,5 Z',
  close_back_rounded: 'M-10,-2 Q0,-6 10,-2 L10,4 Q0,7 -10,4 Z',
  rhotic: 'M-13,-2 Q0,-7 13,-2 L13,6 Q0,9 -13,6 Z',
  schwa: 'M-12,-1 Q0,-4 12,-1 L12,4 Q0,5 -12,4 Z',
  near_close_front_lax: 'M-13,-2 Q0,-6 13,-2 L13,5 Q0,7 -13,5 Z',
};

/** Generate mouth path with expression applied */
function generateMouthPath(
  shapeKey: MouthShapeKey,
  expression: ExpressionModifiers
): string {
  const baseGeo = MOUTH_SHAPE_GEOMETRY[shapeKey];
  const geo = applyExpressionToGeometry(baseGeo, expression);

  // Use predefined path as base, scale by geometry
  const basePath = MOUTH_SHAPE_PATHS[shapeKey];

  // For simplicity, return the base path — in production you'd morph
  // or use the geometry to procedurally generate the path
  return basePath;
}

/** Resolve expression to modifiers object */
function resolveExpression(
  expr: MarkAvatarSVGProps['expression']
): ExpressionModifiers {
  if (!expr) return DEFAULT_EXPRESSION;
  if (typeof expr === 'string') return EXPRESSION_PRESETS[expr] ?? DEFAULT_EXPRESSION;
  return { ...DEFAULT_EXPRESSION, ...expr };
}

export function MarkAvatarSVG({
  viseme = 'sil',
  expression = 'neutral',
  gaze = { x: 0, y: 0 },
  blink = 0,
  size = 100,
  skinTone = '#e8d5c4',
  irisColor = '#4a90d9',
  accentColor = '#00ff88',
  isThinking = false,
  isSpeaking = false,
  className = '',
}: MarkAvatarSVGProps) {
  const exprMods = resolveExpression(expression);
  const mouthShape = getMouthShapeForViseme(viseme);
  const mouthPath = generateMouthPath(mouthShape, exprMods);

  // Eye calculations
  const pupilOffsetX = gaze.x * 3;
  const pupilOffsetY = gaze.y * 3;
  const irisOffsetX = gaze.x * 1.5;
  const irisOffsetY = gaze.y * 1.5;
  const eyelidHeight = 8 * blink; // 0 to 8 (full close)

  // Brow calculations
  const browRaise = exprMods.browRaise * 6; // px
  const browFurrow = exprMods.browFurrow * 8; // deg
  const browY = 32 - browRaise;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      className={`mark-avatar-svg ${className}`}
      style={{
        width: size,
        height: size,
        display: 'block',
      }}
      role="img"
      aria-label={`MARK avatar, ${viseme !== 'sil' ? 'speaking' : 'idle'}`}
    >
      <defs>
        <filter id="blur" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="8" />
        </filter>
        <filter id="inner-shadow" x="-50%" y="-50%" width="200%" height="200%">
          <feOffset dx="0" dy="2" />
          <feGaussianBlur stdDeviation="2" result="offset-blur" />
          <feComposite in="SourceGraphic" in2="offset-blur" operator="over" />
        </filter>
        {/* Eye clip path for blink */}
        <clipPath id="eye-clip-left">
          <rect x="18" y={34 - eyelidHeight} width="24" height={16 - eyelidHeight} />
        </clipPath>
        <clipPath id="eye-clip-right">
          <rect x="58" y={34 - eyelidHeight} width="24" height={16 - eyelidHeight} />
        </clipPath>
      </defs>

      {/* Layer 1: Background */}
      <g id="avatar-bg">
        <circle cx="50" cy="50" r="50" fill="transparent" />
        <circle cx="50" cy="50" r="48" fill="none" stroke="currentColor" strokeWidth="2" opacity="0.15" />
      </g>

      {/* Layer 7: Effects (backmost for glow behind head) */}
      <g id="effects-layer">
        <AnimatePresence mode="wait">
          {isThinking && (
            <motion.circle
              key="think-ring"
              cx="50"
              cy="50"
              r="55"
              fill="none"
              stroke={accentColor}
              strokeWidth="2"
              initial={{ opacity: 0.6, r: 48 }}
              animate={{ opacity: 0, r: 60 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 1.5, repeat: Infinity, ease: 'easeOut' }}
            />
          )}
        </AnimatePresence>
        <AnimatePresence mode="wait">
          {isSpeaking && (
            <motion.circle
              key="speak-ring"
              cx="50"
              cy="50"
              r="52"
              fill="none"
              stroke={accentColor}
              strokeWidth="1.5"
              initial={{ opacity: 0.4, r: 48 }}
              animate={{ opacity: 0, r: 58 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.8, repeat: Infinity, ease: 'easeOut' }}
            />
          )}
        </AnimatePresence>
        <circle
          id="head-glow"
          cx="50"
          cy="50"
          r="45"
          fill={accentColor}
          opacity={isThinking ? 0.08 : isSpeaking ? 0.05 : 0}
          filter="url(#blur)"
        />
      </g>

      {/* Layer 2: Face Base */}
      <g id="face-base" filter="url(#inner-shadow)">
        <path
          id="face-shape"
          d="M50 8 C76 8 92 24 92 50 C92 76 76 92 50 92 C24 92 8 76 8 50 C8 24 24 8 50 8 Z"
          fill={skinTone}
        />
        <ellipse cx="20" cy="60" rx="8" ry="4" fill="#d4a59a" opacity="0.25" />
        <ellipse cx="80" cy="60" rx="8" ry="4" fill="#d4a59a" opacity="0.25" />
      </g>

      {/* Layer 3: Nose */}
      <g id="nose">
        <path
          d="M50 42 Q50 48 50 54"
          stroke="#c9b8a8"
          strokeWidth="1.5"
          fill="none"
          strokeLinecap="round"
        />
        <circle cx="50" cy="54" r="2" fill="#b8a595" />
      </g>

      {/* Layer 4: Mouth */}
      <g id="mouth-layer" transform="translate(50, 68)">
        <AnimatePresence mode="wait">
          <motion.path
            key={mouthShape}
            d={mouthPath}
            fill="none"
            stroke="#3d2d24"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            initial={{ path: MOUTH_SHAPE_PATHS.closed }}
            animate={{ path: mouthPath }}
            exit={{ path: MOUTH_SHAPE_PATHS.closed }}
            transition={{ duration: 0.08, ease: 'easeOut' }}
          />
        </AnimatePresence>
        {/* Inner mouth shadow for open shapes */}
        {mouthShape !== 'closed' && mouthShape !== 'bilabial_closed' && mouthShape !== 'nasal' && (
          <path
            d={mouthPath}
            fill="#1a1008"
            opacity="0.3"
          />
        )}
      </g>

      {/* Layer 5: Eyes */}
      <g id="eyes-layer">
        {/* Left Eye */}
        <g id="eye-left" clipPath="url(#eye-clip-left)">
          <ellipse cx="30" cy="42" rx="12" ry="8" fill="#fff" />
          <circle
            cx={30 + irisOffsetX}
            cy={42 + irisOffsetY}
            r="5"
            fill={irisColor}
          />
          <circle
            cx={30 + pupilOffsetX}
            cy={42 + pupilOffsetY}
            r="2.5"
            fill="#1a1a2e"
          />
          <circle cx="27" cy="39" r="1.5" fill="#fff" opacity="0.9" />
          <circle cx="25" cy="37" r="0.6" fill="#fff" opacity="0.5" />
        </g>

        {/* Right Eye */}
        <g id="eye-right" clipPath="url(#eye-clip-right)">
          <ellipse cx="70" cy="42" rx="12" ry="8" fill="#fff" />
          <circle
            cx={70 + irisOffsetX}
            cy={42 + irisOffsetY}
            r="5"
            fill={irisColor}
          />
          <circle
            cx={70 + pupilOffsetX}
            cy={42 + pupilOffsetY}
            r="2.5"
            fill="#1a1a2e"
          />
          <circle cx="67" cy="39" r="1.5" fill="#fff" opacity="0.9" />
          <circle cx="65" cy="37" r="0.6" fill="#fff" opacity="0.5" />
        </g>

        {/* Lower lid hint (squint) */}
        {exprMods.squint > 0 && (
          <>
            <path
              d="M20,48 Q30,46.5 40,48"
              stroke={skinTone}
              strokeWidth={1.5 + exprMods.squint * 2}
              fill="none"
              opacity={exprMods.squint * 0.6}
            />
            <path
              d="M60,48 Q70,46.5 80,48"
              stroke={skinTone}
              strokeWidth={1.5 + exprMods.squint * 2}
              fill="none"
              opacity={exprMods.squint * 0.6}
            />
          </>
        )}
      </g>

      {/* Layer 6: Eyebrows */}
      <g id="eyebrows-layer">
        <motion.path
          id="brow-left"
          d={`M18,${browY} Q30,${browY - 4 - browFurrow} 42,${browY}`}
          stroke="#3d3d3d"
          strokeWidth="3"
          fill="none"
          strokeLinecap="round"
          animate={{
            d: `M18,${browY} Q30,${browY - 4 - browFurrow} 42,${browY}`,
          }}
          transition={{ duration: 0.3, ease: 'easeOut' }}
        />
        <motion.path
          id="brow-right"
          d={`M58,${browY} Q70,${browY - 4 + browFurrow} 82,${browY}`}
          stroke="#3d3d3d"
          strokeWidth="3"
          fill="none"
          strokeLinecap="round"
          animate={{
            d: `M58,${browY} Q70,${browY - 4 + browFurrow} 82,${browY}`,
          }}
          transition={{ duration: 0.3, ease: 'easeOut' }}
        />
      </g>
    </svg>
  );
}