---
name: SmartAgent Memory v1 vault design
description: How the SmartAgent project's persistent memory (vault/) is structured and why, for future memory-related work on this project.
---

MemoryManager (smartagent/memory/memory_manager.py) replaced the old in-memory placeholder with a persistent Markdown vault (smartagent/memory/vault.py + entry.py).

- Each memory is one .md file: `---` frontmatter (id, category, tags, created_at, updated_at) then free-text content. Parsed with a small hand-written parser, not PyYAML.
  **Why:** project requirement was "no databases" and to keep memory human-readable/editable; a YAML dep for 5 known fields wasn't worth it.
- Lookup by id scans category folders for a matching filename (id == filename stem) instead of maintaining an index.
  **Why:** zero extra state, acceptable for a personal-scale vault. Revisit if vault grows large.
- search() is case-insensitive substring match over content+tags only — no vector/semantic search yet (explicitly out of scope for Memory v1).
- Settings.vault_path controls vault location; tests must always pass an isolated tmp_path vault_path, never the project's real vault/, to avoid polluting it.
- brain/agent.py's handle_message() checks memory.search() before calling the (still unimplemented) model, and always writes the exchange back to the Journal category.
