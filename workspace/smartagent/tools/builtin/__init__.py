"""
Built-in tools for SmartAgent — Milestone 4, Part 5.

Organised into four sub-packages:
    filesystem/   — FileReadTool, FileWriteTool, DirectoryCreateTool,
                    DirectoryListTool, CopyFileTool, MoveFileTool,
                    DeleteFileTool, SearchFilesTool
    text/         — OpenTextFileTool, ReadMarkdownTool
    system/       — SystemInfoTool, DateTimeTool, EnvironmentTool
    utilities/    — UUIDTool, HashTool

``ToolLoader.discover_tool_classes()`` uses ``pkgutil.walk_packages`` to
auto-discover every ``BaseTool`` subclass in this tree — no hardcoded
imports needed anywhere.
"""
