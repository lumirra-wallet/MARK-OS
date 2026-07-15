"""
Tools subpackage.

Defines the pluggable "tools" SmartAgent can invoke to take action or
fetch information beyond its own reasoning (e.g. web search, calculators,
file/system access, calendar lookups). Tools share a common interface so
the core agent can discover and call them generically via `ToolRegistry`.
"""
