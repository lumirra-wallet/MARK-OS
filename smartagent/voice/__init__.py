"""
Voice subpackage.

Handles converting between speech and text so SmartAgent can be used
hands-free: `speech_to_text` for capturing/transcribing user audio, and
`text_to_speech` for speaking responses back. Kept separate from
`core` so voice can remain fully optional (text-only usage should always
work without this subpackage doing anything).
"""
