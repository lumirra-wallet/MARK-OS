---
name: Voice Pipeline 12-Feature Fix
description: Two critical bugs left by a previous session that ran out of quota mid-implementation; both fixed.
---

## Bug 1 — `_spectral_subtract_noise` called but never defined

In `smartagent/server/voice_pipeline.py`, the `transcribe()` function (Feature 7 - Noise Separation)
calls `_spectral_subtract_noise(audio)` on every final-pass transcription, but the function was never
implemented. This caused a `NameError` on every user utterance, making the `except Exception: pass`
block silently swallow the error and fall through to the original audio — meaning spectral subtraction
never ran.

**Fix:** Added a pure-numpy spectral subtraction implementation directly above the turn-taking states
section in `voice_pipeline.py`. Uses first 100ms as noise floor estimate, over-subtraction (α=2.0),
spectral flooring (β=0.01), and overlap-add synthesis — no extra dependencies.

## Bug 2 — `on_utterance` never called before brain inference

In `smartagent/server/api.py`, `_voice_chat_response()` dispatches `brain_runtime.converse()`,
which calls `conversation_session.to_prompt_block()` and `.resolve()` to inject session state
(emotion/topic/entities) into Elena's system prompt. BUT `conversation_session.on_utterance(text)`
was never called, so the session state was always stale/empty — emotion detection, topic extraction,
and entity tracking never ran before the LLM received the prompt.

Similarly, `on_user_answered()` (which clears open questions when the owner responds) was never called.

**Fix:** Added both calls in `_voice_chat_response()` immediately after the `Observation` is created
and before `_brain.thinking_started(text)`:

```python
_cvs_pre.on_user_answered()   # clear open questions — owner just spoke
_cvs_pre.on_utterance(text)   # detect emotion, extract topic/entities
```

This ensures `brain_runtime.converse()` sees fresh session context on every turn.

## How to apply
- Any time voice responses seem emotionally flat or Elena asks "what are you referring to?" on short
  commands — check that `on_utterance` is being called before `brain_runtime.converse()`.
- If transcription silently fails with no noise reduction — check that `_spectral_subtract_noise`
  is defined above where it's called in `transcribe()`.
