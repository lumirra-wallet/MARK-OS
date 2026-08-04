/**
 * MARK Avatar — Small Badge Component
 * Simplified version for header badges and chat messages
 */

import { motion } from 'framer-motion';
import { Zap } from 'lucide-react';

export type MarkAvatarSmallState = 'idle' | 'thinking' | 'speaking';

export interface MarkAvatarSmallProps {
  state: MarkAvatarSmallState;
  size?: number;
  className?: string;
  /** Optional viseme for lip-sync when speaking */
  viseme?: string;
  /** Show accent color from theme */
  accentColor?: string;
}

export function MarkAvatarSmall({
  state,
  size = 32,
  className = '',
  viseme = 'sil',
  accentColor = 'var(--accent, #00ff88)',
}: MarkAvatarSmallProps) {
  const iconSize = Math.max(10, Math.round(size * 0.5));
  const isSpeaking = state === 'speaking';

  // Mouth shape based on viseme when speaking
  const mouthHeight = isSpeaking
    ? viseme === 'sil' || viseme === 'PP' || viseme === 'FF' || viseme === 'TH'
      ? '15%' // closed-ish
      : viseme === 'aa' || viseme === 'ah' || viseme === 'ao'
        ? '90%' // wide open
        : viseme === 'ae' || viseme === 'eh' || viseme === 'oh' || viseme === 'ow'
          ? '70%' // medium open
          : '45%' // default speaking
    : '15%';

  return (
    <div
      className={`relative shrink-0 ${className}`}
      style={{ width: size, height: size }}
      role="img"
      aria-label={`MARK avatar, ${state}`}
    >
      {/* Thinking pulse ring */}
      {state === 'thinking' && (
        <motion.div
          className="absolute inset-0 rounded-full border-2"
          style={{ borderColor: accentColor }}
          animate={{ scale: [1, 1.3, 1], opacity: [0.6, 0, 0.6] }}
          transition={{ duration: 1.3, repeat: Infinity, ease: 'easeOut' }}
        />
      )}

      {/* Main avatar circle */}
      <motion.div
        className="relative w-full h-full rounded-full bg-accent/15 border flex items-center justify-center"
        style={{ borderColor: `${accentColor}66` }}
        animate={
          state === 'idle'
            ? { scale: [1, 1.04, 1] }
            : state === 'speaking'
              ? { scale: [1, 1.08, 1] }
              : { scale: 1 }
        }
        transition={{
          duration: state === 'speaking' ? 0.4 : 2.6,
          repeat: Infinity,
          ease: 'easeInOut',
        }}
      >
        <Zap className="text-accent" style={{ width: iconSize, height: iconSize }} />
      </motion.div>

      {/* Speaking indicator — viseme-aware bars */}
      {isSpeaking && (
        <div
          className="absolute -bottom-1 left-1/2 -translate-x-1/2 flex items-end gap-[2px] h-2"
          style={{ width: size * 0.6 }}
        >
          {[0, 1, 2, 3].map((i) => (
            <motion.span
              key={i}
              className="w-[2px] rounded-full"
              style={{ backgroundColor: accentColor }}
              animate={{
                height: [
                  '15%',
                  mouthHeight,
                  '35%',
                  mouthHeight === '90%' ? '80%' : '60%',
                  '15%',
                ],
              }}
              transition={{
                duration: 0.08 + Math.random() * 0.04,
                repeat: Infinity,
                delay: i * 0.1,
                ease: 'easeInOut',
              }}
            />
          ))}
        </div>
      )}

      {/* Thinking dots */}
      {state === 'thinking' && (
        <div className="absolute -bottom-1 left-1/2 -translate-x-1/2 flex items-center gap-1">
          {[0, 1, 2].map((i) => (
            <motion.span
              key={i}
              className="w-1.5 h-1.5 rounded-full"
              style={{ backgroundColor: accentColor }}
              animate={{ opacity: [0.3, 1, 0.3], scale: [0.8, 1.2, 0.8] }}
              transition={{
                duration: 0.6,
                repeat: Infinity,
                delay: i * 0.15,
                ease: 'easeInOut',
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}