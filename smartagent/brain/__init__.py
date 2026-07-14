"""
Brain subpackage.

Contains the central "brain" of SmartAgent: the orchestration logic that
receives a user request, consults memory, decides whether to invoke
skills/tools, and produces a response. Everything else (voice, vision,
automation, ui) feeds into or is driven by this layer.

(Formerly named `core` — renamed to `brain` as part of the move to a
scalable, production-oriented package layout.)
"""
