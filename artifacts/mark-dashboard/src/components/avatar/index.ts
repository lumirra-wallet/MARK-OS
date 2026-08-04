/**
 * MARK Avatar — Main Export
 * Unified avatar system with SVG and small badge variants
 */

export * from './avatar-spec';
export * from './viseme-map';
export * from './MarkAvatarSVG';
export * from './MarkAvatarSmall';

// Re-export types for convenience
export type {
  VisemeId,
  MouthShapeKey,
  ExpressionModifiers,
  MouthShapeGeometry,
  MarkAvatarSVGProps,
  MarkAvatarSmallProps,
  MarkAvatarSmallState,
} from './viseme-map';
export type { MarkAvatarSVGProps } from './MarkAvatarSVG';
export type { MarkAvatarSmallProps, MarkAvatarSmallState } from './MarkAvatarSmall';