---
name: Elena Rebrand & Voice Pipeline Upgrade
description: Full rename from MARK→Elena, female personality, voice/STT improvements
---

## What changed

**Identity rename (MARK → Elena, she/her):**
- `smartagent/identity/mark_identity.py` — complete rewrite of all system prompts; Elena is a sharp, warm, 35-year-old American woman who uses natural slang, keeps replies short (1-3 sentences), and responds conversationally
- `smartagent/mind/identity/identity_model.py` — default name changed to "Elena"
- `smartagent/mind/identity/identity_engine.py` — default_identity() uses "Elena", updated personality description
- `docs/canonical/MARK_PERSONALITY.json` — updated to Elena, added gender/age/slang fields
- `docs/canonical/MARK_CONSTITUTION.md`, `MARK_OPERATING_PRINCIPLES.md`, `SMARTAGENT.md` — sed replaced MARK→Elena

**Frontend UI (user-visible labels):**
- `MarkHome.tsx` — "MARK" heading → "ELENA", chat button title updated
- `MarkPresence.tsx` — "MARK" badge → "Elena"
- `ChatView.tsx` — sender label "MARK"→"Elena", placeholder, approval block, connecting screen
- `Dashboard.tsx` — back button label updated
- `smartagent/server/app.py` — API title updated to "Elena AI OS"

**Voice/STT improvements:**
- `voice_pipeline.py` — default Whisper model upgraded `base.en` → `small.en` (env override: `MARK_WHISPER_MODEL`), beam_size 2→3, added `temperature=0.0` and `condition_on_previous_text=False` to reduce hallucination, raised no_speech_prob threshold to 0.65
- `tts_engine.py` — voice changed from `af_bella` to `af_sky` (more natural American female), speed 1.0→1.05

**Why:**
- User reported voice wasn't transcribing accurately → `small.en` is 2x better than `base.en` with temperature=0 reducing hallucination
- User wanted natural conversational AI persona with American slang, short responses
- All internal state keys (`role: 'mark'`, `isMarkSpeaking`, `markStore`, etc.) left unchanged — only user-visible labels updated

**How to apply:**
- Backend restart required to pick up identity/voice changes (server restarted after changes)
- Frontend applied via Vite HMR instantly
