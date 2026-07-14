"""
Memory entry data model and Markdown (de)serialization.

Each memory is stored as one human-readable Markdown file with a small,
hand-rolled frontmatter block holding structured metadata (id, timestamps,
category, tags) followed by the free-form memory content, e.g.:

    ---
    id: 20260714-153000-a1b2c3d4
    category: Journal
    tags: color, preference
    created_at: 2026-07-14T15:30:00+00:00
    updated_at: 2026-07-14T15:30:00+00:00
    ---

    The user's favorite color is blue.

Keeping the format plain text — no YAML/JSON library, no database — means
every memory file can be opened, read, and edited by a human in any text
editor. That is a deliberate Memory v1 design goal (a readable "vault", not
a black box) and it keeps the on-disk format dependency-free.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MemoryEntry:
    """A single memory: its content plus the metadata MARK tracks about it."""

    id: str
    category: str
    content: str
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    @property
    def filename(self) -> str:
        """The Markdown filename this entry is stored under (id == stem)."""
        return f"{self.id}.md"

    def to_markdown(self) -> str:
        """Render this entry as the contents of its Markdown file."""
        tags_line = ", ".join(self.tags)
        lines = [
            "---",
            f"id: {self.id}",
            f"category: {self.category}",
            f"tags: {tags_line}",
            f"created_at: {self.created_at}",
            f"updated_at: {self.updated_at}",
            "---",
            "",
            self.content.strip(),
            "",
        ]
        return "\n".join(lines)

    @classmethod
    def from_markdown(cls, text: str) -> "MemoryEntry":
        """
        Parse a Markdown memory file back into a `MemoryEntry`.

        This is a small, hand-written parser rather than a full YAML
        parser — the frontmatter schema is tiny, fixed, and fully owned by
        this module, so a real YAML dependency would add complexity without
        real benefit (and Memory v1 is explicitly meant to stay dependency
        free; see SMARTAGENT.md).
        """
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            raise ValueError("Memory file is missing its frontmatter block.")

        metadata: dict[str, str] = {}
        idx = 1
        while idx < len(lines) and lines[idx].strip() != "---":
            line = lines[idx]
            if ":" in line:
                key, _, value = line.partition(":")
                metadata[key.strip()] = value.strip()
            idx += 1

        # Everything after the closing '---' (skipping the blank separator
        # line) is the actual memory content.
        content = "\n".join(lines[idx + 1 :]).strip()

        tags_raw = metadata.get("tags", "")
        tags = [tag.strip() for tag in tags_raw.split(",") if tag.strip()]

        return cls(
            id=metadata.get("id", ""),
            category=metadata.get("category", ""),
            content=content,
            tags=tags,
            created_at=metadata.get("created_at", ""),
            updated_at=metadata.get("updated_at", ""),
        )
