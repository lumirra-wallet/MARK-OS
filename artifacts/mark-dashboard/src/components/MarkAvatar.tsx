import { motion } from 'framer-motion';
import { Zap } from 'lucide-react';

export type MarkAvatarState = 'idle' | 'thinking' | 'speaking';

interface MarkAvatarProps {
  state: MarkAvatarState;
  size?: number;
  className?: string;
}

/**
 * MARK's visual presence — a single persistent badge (header) and a smaller
 * copy next to each chat message, both driven by the same three states so
 * MARK always visibly "is" something rather than sitting static.
 */
export function MarkAvatar({ state, size = 32, className = '' }: MarkAvatarProps) {
  const iconSize = Math.max(10, Math.round(size * 0.5));

  return (
    <div className={`relative shrink-0 ${className}`} style={{ width: size, height: size }}>
      {state === 'thinking' && (
        <motion.div
          className="absolute inset-0 rounded-full border-2 border-accent/60"
          animate={{ scale: [1, 1.3, 1], opacity: [0.7, 0, 0.7] }}
          transition={{ duration: 1.3, repeat: Infinity, ease: 'easeOut' }}
        />
      )}

      <motion.div
        className="relative w-full h-full rounded-full bg-accent/20 border border-accent/40 flex items-center justify-center"
        animate={
          state === 'idle'
            ? { scale: [1, 1.04, 1] }
            : state === 'speaking'
              ? { scale: [1, 1.1, 1] }
              : { scale: 1 }
        }
        transition={{
          duration: state === 'speaking' ? 0.5 : 2.6,
          repeat: Infinity,
          ease: 'easeInOut',
        }}
      >
        <Zap className="text-accent" style={{ width: iconSize, height: iconSize }} />
      </motion.div>

      {state === 'speaking' && (
        <div className="absolute -bottom-1 left-1/2 -translate-x-1/2 flex items-end gap-[2px] h-2">
          {[0, 1, 2, 3].map(i => (
            <motion.span
              key={i}
              className="w-[2px] rounded-full bg-accent"
              animate={{ height: ['15%', '100%', '35%', '90%', '15%'] }}
              transition={{ duration: 0.9, repeat: Infinity, delay: i * 0.12, ease: 'easeInOut' }}
            />
          ))}
        </div>
      )}
    </div>
  );
}
