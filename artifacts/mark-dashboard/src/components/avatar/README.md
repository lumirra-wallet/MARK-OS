# MARK Avatar Component System

A layered, expressive avatar system for MARK with viseme-driven lip-sync and emotional expression support.

## Architecture

```
src/components/avatar/
├── avatar-spec.md          # Full specification document
├── viseme-map.ts           # Viseme→mouth shape mapping + geometry
├── MarkAvatarSVG.tsx       # Full SVG layered avatar component
├── MarkAvatarSmall.tsx     # Simplified badge for headers/chat
└── index.ts                # Main exports
```

## Quick Start

### Small Badge (Header/Chat)
```tsx
import { MarkAvatarSmall } from '@/components/avatar';

<MarkAvatarSmall
  state="speaking"
  size={32}
  viseme="aa"  // current viseme for lip-sync
/>
```

### Full SVG Avatar (Home/Presence)
```tsx
import { MarkAvatarSVG } from '@/components/avatar';

<MarkAvatarSVG
  viseme="aa"
  expression="happy"
  gaze={{ x: 0.2, y: -0.1 }}
  blink={0}
  size={200}
  isSpeaking={true}
  isThinking={false}
/>
```

## Viseme System

### Supported Visemes (23 total)

| Viseme | Phonemes | Example | Mouth Shape |
|--------|----------|---------|-------------|
| `sil` | — | (silence) | closed |
| `PP` | /p, b, m/ | put, book, man | bilabial_closed |
| `FF` | /f, v/ | five, voice | labiodental |
| `TH` | /θ, ð/ | think, this | interdental |
| `DD` | /t, d, n, s, z/ | two, do, no, see, zoo | alveolar |
| `kk` | /k, g, ŋ/ | key, go, sing | velar |
| `CH` | /tʃ, dʒ, ʃ, ʒ/ | cheese, jump, shoe, measure | postalveolar |
| `SS` | /s, z/ | see, zoo | sibilant |
| `nn` | /n, m, ŋ/ | no, man, sing | nasal |
| `RR` | /r, l/ | red, love | approximant |
| `aa` | /ɑ/ | father | open_front_unrounded |
| `ae` | /æ/ | cat | open_front_unrounded_small |
| `ah` | /ʌ/ | father (US) | open_back_unrounded |
| `ao` | /ɔ/ | law | open_back_rounded |
| `eh` | /ɛ/ | bed | mid_front_unrounded |
| `ey` | /i/ | see | close_front_unrounded |
| `ih` | /ɪ/ | sit | near_close_front |
| `oh` | /o/ | go | mid_back_rounded |
| `ow` | /oʊ/ | boat | diphthong_oh |
| `uh` | /ʊ/ | book | near_close_back |
| `uw` | /u/ | food | close_back_rounded |
| `er` | /ɝ/ | bird | rhotic |
| `ax` | /ə/ | about | schwa |
| `ix` | /ɪ/ | roses | near_close_front_lax |

### Mapping Source
Based on standard viseme sets from:
- Microsoft SAPI 5.1
- Amazon Polly
- Google Cloud Text-to-Speech

## Expression System

### Preset Expressions
```tsx
// String presets
expression="neutral" | "happy" | "sad" | "angry" | "surprised" | "thinking" | "confused" | "skeptical" | "concentrating" | "speaking"

// Or custom modifiers
expression={{
  smile: 0.5,
  browRaise: 0.2,
  squint: 0.1,
  gazeX: 0.1,
}}
```

### Expression Modifiers
| Property | Range | Effect |
|----------|-------|--------|
| `smile` | -1 to 1 | Corner pull (smile/frown) |
| `frown` | 0 to 1 | Lower corners, raise center |
| `jawDrop` | 0 to 1 | Additional mouth opening |
| `lipPucker` | 0 to 1 | Lip rounding/protrusion |
| `lipPress` | 0 to 1 | Lip compression |
| `browRaise` | -1 to 1 | Eyebrow elevation |
| `browFurrow` | 0 to 1 | Brow angle (concern) |
| `squint` | 0 to 1 | Eye narrowing |
| `gazeX` | -1 to 1 | Horizontal gaze |
| `gazeY` | -1 to 1 | Vertical gaze |

## Layer Architecture (SVG)

```
Layer 7: Effects (glow rings, thinking pulse)
Layer 6: Eyebrows (expression)
Layer 5: Eyes (gaze, blink, squint)
Layer 4: Mouth (viseme-driven, expression-modified)
Layer 3: Nose (static)
Layer 2: Face Base (skin, cheeks)
Layer 1: Background (container, border)
```

All layers share viewBox `0 0 100 100` with origin at top-left.

## Integration with Speech

### From TTS Viseme Events
```tsx
// Example: LiveKit/Azure/Google TTS viseme events
function useVisemeSync() {
  const [viseme, setViseme] = useState<VisemeId>('sil');

  useEffect(() => {
    const handleViseme = (event: VisemeEvent) => {
      // Map provider viseme to our standard set
      setViseme(mapProviderViseme(event.viseme));
    };
    tts.on('viseme', handleViseme);
    return () => tts.off('viseme', handleViseme);
  }, []);

  return viseme;
}

// In component
<MarkAvatarSVG viseme={viseme} isSpeaking={isSpeaking} />
```

### Coarticulation Smoothing
The `viseme-map.ts` exports `VISEME_GROUPS` for smoothing transitions between visemes in the same articulatory group.

## Customization

### Theming via CSS Variables
```css
:root {
  --avatar-skin-tone: #e8d5c4;
  --avatar-iris-color: #4a90d9;
  --avatar-accent: #00ff88;
  --avatar-bg: transparent;
}
```

### Props
```tsx
<MarkAvatarSVG
  skinTone="#custom"
  irisColor="#custom"
  accentColor="#custom"
  size={200}
/>
```

## Animation Performance

- **Mouth morph**: 80ms Framer Motion transition
- **Blink**: CSS clipPath (GPU accelerated)
- **Gaze**: Transform-only (no layout thrash)
- **Expression**: 300ms transition on brows
- **Thinking/Speaking rings**: CSS keyframes via Framer Motion

## Browser Support

- Modern browsers with SVG + CSS Filters + ClipPath
- Framer Motion 10+ required
- React 18+

## Extending

### Add New Viseme
1. Add to `VisemeId` type in `viseme-map.ts`
2. Add mapping in `VISEME_TO_MOUTH_SHAPE`
3. Add geometry in `MOUTH_SHAPE_GEOMETRY`
4. Add SVG path in `MOUTH_SHAPE_PATHS` (MarkAvatarSVG.tsx)

### Add New Expression
1. Add to `EXPRESSION_PRESETS` in `viseme-map.ts`
2. Or pass custom `ExpressionModifiers` object directly

### Canvas/WebGL Fallback
The `MOUTH_SHAPE_GEOMETRY` parameters enable procedural rendering for Canvas/WebGL implementations.