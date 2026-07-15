"""
Skills command: skills.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.ui.command_router import CommandRouter

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent


def handle_skills(agent: "SmartAgent", args: list[str]) -> str:
    """List all loaded skills with id, version, status, and permissions."""
    try:
        skills = agent.skill_engine.list_available()
        if not skills:
            return "No skills loaded."
        lines = [f"Skills ({len(skills)} loaded)", ""]
        header = f"  {'ID':<22} {'Version':<8} {'Status':<10} Permissions"
        lines.append(header)
        lines.append("  " + "-" * 58)
        for s in skills:
            sid = str(s.get("id", s.get("name", "?")))[:22]
            ver = str(s.get("version", "?"))[:8]
            status = str(s.get("status", "active"))[:10]
            perms = s.get("permissions", [])
            if isinstance(perms, (list, tuple)):
                perm_str = ", ".join(str(p) for p in perms[:4])
                if len(perms) > 4:
                    perm_str += f" (+{len(perms) - 4})"
            else:
                perm_str = str(perms)
            lines.append(f"  {sid:<22} {ver:<8} {status:<10} {perm_str}")
        return "\n".join(lines)
    except Exception as exc:
        return f"[error] Could not list skills: {exc}"


def register(router: CommandRouter) -> None:
    """Register the skills command with *router*."""
    router.register("skills", handle_skills, "list loaded skills", "SKILLS", 0)
