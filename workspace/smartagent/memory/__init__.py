"""
Memory subpackage — Memory v1: a persistent Markdown vault.

Responsible for storing and retrieving everything SmartAgent needs to
remember: conversation history, learned facts, user preferences, etc.
Memory v1 stores every memory as a human-readable Markdown file inside a
configurable `vault/` directory, organized into category folders (see
`smartagent.memory.vault.Vault`). No database and no vector/semantic
search yet — those remain possible future backends behind the same
`MemoryManager` interface (remember/recall/search/update/delete/
list_categories) that the rest of the codebase depends on.
"""
