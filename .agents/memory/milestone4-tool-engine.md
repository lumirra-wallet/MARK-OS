---
name: Milestone 4 Tool Engine v1
description: Architecture decisions, integration patterns, and test lessons for the Tool Engine layer.
---

## Boundary rule
Brain → Skill → ToolEngine → Tool → ActionResult.  
The Brain's `tools` module handler always returns `success=False` (NL routing impossible without AI).  
Skills call tools via `SkillContext.tool_engine.run(tool_id, tool_ctx, **params)`.

## One PermissionManager governs both layers
`agent.permissions` is constructed once and passed to both `SkillEngine` and `ToolEngine`.  
`agent.skill_engine.permissions is agent.tool_engine.permissions` must stay True.

**Why:** granting `READ_FILES` at the settings level should affect both skill-level permission checks and tool-level ones without any synchronization logic.

## Five new Permission enum values (Milestone 4)
READ_FILES, WRITE_FILES, DELETE_FILES, CREATE_DIRECTORIES, READ_SYSTEM_INFO.  
Total permissions: 12 (was 7).  
`test_all_seven_permissions_exist` in test_skills.py was renamed/split into three tests to accommodate the additions — future permission additions should update `test_total_permission_count`.

## ToolLoader uses walk_packages, not iter_modules
Tools live in sub-packages (filesystem/, system/, text/, utilities/).  
`pkgutil.walk_packages` (recursive) is required; `pkgutil.iter_modules` (non-recursive) only finds top-level modules.  
SkillLoader uses `iter_modules` because skills are flat (single `builtin/` level).

## Legacy backward-compat in ToolRegistry
Old `Tool` ABC (with `run()`) and `get(name)` method are kept in `tool_registry.py`.  
Old tools go into `_legacy: dict[str, Tool]`; new `BaseTool` tools go into `_tools`.  
`list_available()` returns both. `get()` checks `_tools` first, then `_legacy`.  
`register()` detects type via `isinstance(tool, BaseTool)` to route to the right store.

**Why:** three placeholder tests from Milestone 1 import `Tool` and use `get()` — they must keep passing per the "no regressions" rule.

## PathValidator safety design
1. `resolve_safe(path)` — resolves path (absolute or workspace-relative), rejects escape via ValueError → SafetyError.
2. `check_not_protected_source(resolved_path)` — checks every path component against `_PROTECTED_SOURCE_DIRS = {"smartagent", "tests"}`. Only called by `DeleteFileTool`.  
Never rely on the workspace boundary alone for destructive ops — always call both for delete.

## ToolContext is lightweight by design
`ToolContext(settings, workspace_path, events)` only — no memory, no goals, no full agent.  
Skills build a ToolContext from their SkillContext before calling `tool_engine.run()`.  
This prevents tools from importing `SmartAgent` or `SkillContext` (avoids circular imports).

## Test count history
- Milestone 1: 21 tests
- Milestone 2: 54 tests  
- Milestone 3: 128 tests (74 new)
- Milestone 4: 276 tests (148 new, in tests/test_tools.py)
