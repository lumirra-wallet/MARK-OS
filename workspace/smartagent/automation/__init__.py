"""
Automation subpackage.

Handles anything that runs on a schedule or reacts to an external trigger
without a user actively chatting with the agent (e.g. periodic reminders,
scheduled checks, event-driven workflows). Kept separate from `core` so
the interactive agent logic and background job logic can evolve
independently.
"""
