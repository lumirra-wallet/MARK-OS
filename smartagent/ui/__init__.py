"""
UI subpackage.

Holds the front-ends users interact with SmartAgent through (starting
with a simple CLI). Keeping ui separate from `brain` means new front-ends
(a web dashboard, a chat widget, etc.) can be added later without touching
the orchestration logic — they just call into `SmartAgent`.
"""
