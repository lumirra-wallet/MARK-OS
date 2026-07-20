"""
MARK's layered memory system.

Three persistent layers, each with a distinct purpose:

  EpisodicMemory  — events: conversations, decisions, mistakes, successes.
  SemanticMemory  — permanent facts and knowledge about the world.
  OwnerMemory     — everything MARK learns about the owner over time.

All three are backed by simple JSON files in ~/.cache/mark/memory/.
No database dependency — consistent with the rest of the project.
"""

from .episodic import EpisodicMemory
from .semantic import SemanticMemory
from .owner import OwnerMemory

__all__ = ["EpisodicMemory", "SemanticMemory", "OwnerMemory"]
