"""
Research subpackage.

Defines MARK's research capability: searching trusted sources, summarizing
findings, and presenting them to the owner (Mr. Smart) for approval before
anything is committed to long-term memory. See `SMARTAGENT.md` for the
safety rationale — MARK never "teaches itself" from the internet
unsupervised.

No internet browsing is implemented yet. This subpackage currently only
defines the placeholder shape of `ResearchManager` so later work (search
backends, source trust lists, summarization) has a stable contract to
build against.
"""
