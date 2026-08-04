# MARK Avatar Specification

## Overview

A layered SVG avatar system with distinct anatomical layers for face, eyes, and mouth, enabling expressive viseme-based lip-sync and emotional states.

---

## Layer Architecture (Bottom → Top)

```
┌─────────────────────────────────────────────┐
│ Layer 7: Accent Glow / Effects              │  (optional: thinking pulse, speaking ring)
├─────────────────────────────────────────────┤
│ Layer 6: Eyebrows                           │  (emotional expression)
├─────────────────────────────────────────────┤
│ Layer 5: Eyes (Whites + Irises + Pupils)    │  (gaze direction, blink, squint)
├─────────────────────────────────────────────┤
│ Layer 4: Mouth (Viseme Shapes)              │  (lip-sync primary)
├─────────────────────────────────────────────┤
│ Layer 3: Nose                               │  (static)
├─────────────────────────────────────────────┤
│ Layer 2: Face Base (Shape + Skin Tone)      │  (base geometry)
├─────────────────────────────────────────────┤
│ Layer 1: Background / Container             │  (clipping, shadow)
└─────────────────────────────────────────────┘
```

### Coordinate System

- **ViewBox**: `0 0 100 100` (100×100 unit square)
- **Origin**: Top-left
- **Face Center**: `(50, 50)`
- **All layers share the same coordinate space**

---

## Layer Specifications

### Layer 1: Background Container
```svg
<g id="avatar-bg">
  <circle cx="50" cy="50" r="50" fill="var(--avatar-bg, transparent)" />
  <circle cx="50" cy="50" r="48" fill="none" stroke="var(--avatar-border, currentColor)" stroke-width="2" opacity="0.2" />
</g>
```

### Layer 2: Face Base
```svg
<g id="face-base">
  <!-- Head shape: rounded rectangle / ellipse blend -->
  <path
    id="face-shape"
    d="M50 8
       C76 8  92 24  92 50
       C92 76  76 92  50 92
       C24 92   8 76   8 50
       C8  24  24 8   50 8 Z"
    fill="var(--skin-tone, #e8d5c4)"
  />
  <!-- Optional: subtle cheek highlights -->
  <ellipse cx="20" cy="60" rx="8" ry="4" fill="var(--cheek-color, #d4a59a)" opacity="0.3" />
  <ellipse cx="80" cy="60" rx="8" ry="4" fill="var(--cheek-color, #d4a59a)" opacity="0.3" />
</g>
```

### Layer 3: Nose
```svg
<g id="nose">
  <!-- Minimal nose bridge + tip -->
  <path
    d="M50 42 Q50 48 50 54"
    stroke="var(--nose-color, #c9b8a8)"
    stroke-width="1.5"
    fill="none"
    stroke-linecap="round"
  />
  <circle cx="50" cy="54" r="2" fill="var(--nose-tip-color, #b8a595)" />
</g>
```

### Layer 4: Mouth (Viseme Layer)
**Critical for lip-sync** — swapped per viseme.

```svg
<g id="mouth-layer" transform="translate(50, 68)">
  <!-- Mouth shapes referenced by viseme ID -->
  <!-- Each shape centered at (0,0), scaled to fit ~30×20 units -->
</g>
```

#### Mouth Shape Definitions (Viseme Targets)

| Viseme | Shape Name | SVG Path (centered at 0,0) | Description |
|--------|------------|----------------------------|-------------|
| `sil` | `closed` | `M-15,0 Q0,-2 15,0 Q0,2 -15,0` | Neutral closed lips |
| `PP` | `bilabial_closed` | `M-14,0 Q0,-3 14,0 Q0,4 -14,0` | P, B, M — lips pressed |
| `FF` | `labiodental` | `M-14,-2 Q0,-6 14,-2 L14,4 Q0,6 -14,4 Z` | F, V — lower lip to teeth |
| `TH` | `interdental` | `M-12,-1 Q0,-4 12,-1 L12,5 Q0,6 -12,5 Z` | TH — tongue between teeth |
| `DD` | `alveolar` | `M-16,-3 Q0,-8 16,-3 L16,6 Q0,10 -16,6 Z` | T, D, N, S, Z — tongue behind teeth |
| `kk` | `velar` | `M-12,-5 Q0,-12 12,-5 L12,8 Q0,14 -12,8 Z` | K, G, NG — back of tongue |
| `CH` | `postalveolar` | `M-14,-4 Q0,-10 14,-4 L14,7 Q0,12 -14,7 Z` | CH, J, SH, ZH |
| `SS` | `sibilant` | `M-16,-2 Q0,-6 16,-2 L16,5 Q0,7 -16,5 Z` | S, Z — narrow groove |
| `nn` | `nasal` | `M-13,0 Q0,-2 13,0 Q0,3 -13,0` | N, M, NG — like closed but wider |
| `RR` | `approximant` | `M-15,-1 Q0,-5 15,-1 L15,4 Q0,6 -15,4 Z` | R, L — relaxed open |
| `aa` | `open_front_unrounded` | `M-18,-6 Q0,-18 18,-6 L18,12 Q0,20 -18,12 Z` | A (father) — wide open |
| `ae` | `open_front_unrounded_small` | `M-16,-4 Q0,-14 16,-4 L16,10 Q0,16 -16,10 Z` | AE (cat) — medium open |
| `ah` | `open_back_unrounded` | `M-16,-5 Q0,-15 16,-5 L16,11 Q0,17 -16,11 Z` | AH (father, US) |
| `ao` | `open_back_rounded` | `M-14,-4 Q0,-14 14,-4 L14,10 Q0,16 -14,10 Z` | AW (law) — rounded |
| `eh` | `mid_front_unrounded` | `M-15,-3 Q0,-10 15,-3 L15,8 Q0,12 -15,8 Z` | EH (bed) |
| `ey` | `close_front_unrounded` | `M-13,-2 Q0,-6 13,-2 L13,5 Q0,7 -13,5 Z` | IY (see) — spread |
| `ih` | `near_close_front` | `M-14,-2 Q0,-8 14,-2 L14,6 Q0,9 -14,6 Z` | IH (sit) |
| `oh` | `mid_back_rounded` | `M-12,-3 Q0,-10 12,-3 L12,7 Q0,11 -12,7 Z` | OH (go) — rounded |
| `ow` | `diphthong_oh` | `M-14,-3 Q0,-11 14,-3 L14,8 Q0,12 -14,8 Z` | OW (boat) |
| `uh` | `near_close_back` | `M-11,-2 Q0,-7 11,-2 L11,5 Q0,8 -11,5 Z` | UH (book) |
| `uw` | `close_back_rounded` | `M-10,-2 Q0,-6 10,-2 L10,4 Q0,7 -10,4 Z` | UW (food) — small round |
| `er` | `rhotic` | `M-13,-2 Q0,-7 13,-2 L13,6 Q0,9 -13,6 Z` | ER (bird) — like uh but tense |
| `ax` | `schwa` | `M-12,-1 Q0,-4 12,-1 L12,4 Q0,5 -12,4 Z` | Schwa (about) — neutral mid |
| `ix` | `near_close_front_lax` | `M-13,-2 Q0,-6 13,-2 L13,5 Q0,7 -13,5 Z` | IX (roses) — like iy but lax |

**Note**: Paths are designed for a 30×20 unit mouth area centered at origin. Scale factor applied at render: `scale(1, 1)` for neutral, adjust vertically for expression.

### Layer 5: Eyes
```svg
<g id="eyes-layer">
  <!-- Left Eye -->
  <g id="eye-left" transform="translate(30, 42)">
    <!-- Eye white -->
    <ellipse id="eye-white-l" cx="0" cy="0" rx="12" ry="8" fill="#fff" />
    <!-- Iris -->
    <circle id="iris-l" cx="0" cy="0" r="5" fill="var(--iris-color, #4a90d9)" />
    <!-- Pupil -->
    <circle id="pupil-l" cx="0" cy="0" r="2.5" fill="#1a1a2e" />
    <!-- Highlight -->
    <circle id="highlight-l" cx="-3" cy="-3" r="1.5" fill="#fff" opacity="0.8" />
    <!-- Eyelid (for blink/squint) - clipPath or path morph -->
    <path id="eyelid-l" d="M-12,0 Q0,-10 12,0" fill="none" stroke="var(--skin-tone)" stroke-width="3" stroke-linecap="round" />
  </g>

  <!-- Right Eye -->
  <g id="eye-right" transform="translate(70, 42)">
    <ellipse id="eye-white-r" cx="0" cy="0" rx="12" ry="8" fill="#fff" />
    <circle id="iris-r" cx="0" cy="0" r="5" fill="var(--iris-color, #4a90d9)" />
    <circle id="pupil-r" cx="0" cy="0" r="2.5" fill="#1a1a2e" />
    <circle id="highlight-r" cx="-3" cy="-3" r="1.5" fill="#fff" opacity="0.8" />
    <path id="eyelid-r" d="M-12,0 Q0,-10 12,0" fill="none" stroke="var(--skin-tone)" stroke-width="3" stroke-linecap="round" />
  </g>
</g>
```

#### Eye Animation Parameters

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| `gazeX` | -1 to 1 | 0 | Horizontal gaze offset (pupil + iris) |
| `gazeY` | -1 to 1 | 0 | Vertical gaze offset |
| `blink` | 0 to 1 | 0 | Eyelid closure (0=open, 1=closed) |
| `squint` | 0 to 1 | 0 | Lower lid raise (narrows eye vertically) |
| `browRaise` | -1 to 1 | 0 | Eyebrow position (inner/outer) |
| `browFurrow` | 0 to 1 | 0 | Brow angle (concern/anger) |

### Layer 6: Eyebrows
```svg
<g id="eyebrows-layer">
  <!-- Left Brow -->
  <path
    id="brow-left"
    d="M18,32 Q30,28 42,32"
    stroke="var(--brow-color, #3d3d3d)"
    stroke-width="3"
    fill="none"
    stroke-linecap="round"
    transform-origin="30,32"
  />
  <!-- Right Brow -->
  <path
    id="brow-right"
    d="M58,32 Q70,28 82,32"
    stroke="var(--brow-color, #3d3d3d)"
    stroke-width="3"
    fill="none"
    stroke-linecap="round"
    transform-origin="70,32"
  />
</g>
```

#### Brow Morph Targets
| Expression | Left Brow Transform | Right Brow Transform |
|------------|---------------------|----------------------|
| Neutral | `translate(0,0) rotate(0)` | `translate(0,0) rotate(0)` |
| Raise (surprise) | `translate(0,-6) rotate(-10deg)` | `translate(0,-6) rotate(10deg)` |
| Furrow (anger/concentration) | `translate(0,2) rotate(8deg)` | `translate(0,2) rotate(-8deg)` |
| Sad (inner up) | `translate(0,-4) rotate(-15deg)` | `translate(0,0) rotate(0)` |
| Skeptical (one up) | `translate(0,-5) rotate(-12deg)` | `translate(0,1) rotate(3deg)` |

### Layer 7: Effects (Optional)
```svg
<g id="effects-layer">
  <!-- Thinking pulse ring -->
  <circle id="think-ring" cx="50" cy="50" r="55" fill="none" stroke="var(--accent)" stroke-width="2" opacity="0" />
  <!-- Speaking ring -->
  <circle id="speak-ring" cx="50" cy="50" r="52" fill="none" stroke="var(--accent)" stroke-width="1.5" opacity="0" />
  <!-- Glow behind head -->
  <circle id="head-glow" cx="50" cy="50" r="45" fill="var(--accent)" opacity="0" filter="url(#blur)" />
</g>
```

---

## Viseme-to-Mouth-Shape Mapping Table

### Standard Viseme Set (Based on Microsoft SAPI / Amazon Polly / Google Cloud TTS)

| Viseme ID | Phonemes (IPA) | Example Words | Mouth Shape Key | Morph Weight |
|-----------|----------------|---------------|-----------------|--------------|
| `sil` | — | (silence/pause) | `closed` | 1.0 |
| `PP` | /p/, /b/, /m/ | **p**ut, **b**ook, **m**an | `bilabial_closed` | 1.0 |
| `FF` | /f/, /v/ | **f**ive, **v**oice | `labiodental` | 1.0 |
| `TH` | /θ/, /ð/ | **th**ink, **th**is | `interdental` | 1.0 |
| `DD` | /t/, /d/, /n/, /s/, /z/ | **t**wo, **d**o, **n**o, **s**ee, **z**oo | `alveolar` | 1.0 |
| `kk` | /k/, /g/, /ŋ/ | **k**ey, **g**o, si**ng** | `velar` | 1.0 |
| `CH` | /tʃ/, /dʒ/, /ʃ/, /ʒ/ | **ch**eese, **j**ump, **sh**oe, mea**s**ure | `postalveolar` |