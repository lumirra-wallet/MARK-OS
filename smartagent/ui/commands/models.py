"""
Model commands — Milestone 9, Ollama Integration.

Commands registered:
    models          — list all registered model providers with status
    model           — subcommand group: use / current / info / list
    chat            — send a message to the active model with full MARK context

Free-text fallback:
    When no command is recognised and a model is active, the REPL routes
    the raw input through ``_send_to_model()``.  This is wired from
    ``Console._register_commands()`` via ``router.set_fallback()``.
    When no model is active the fallback returns the standard
    "Unknown command" message so existing behaviour is preserved.

Coding auto-routing:
    ``_pick_model()`` inspects the message for programming keywords and
    returns the coding model id (default ``qwen2.5-coder:7b``) when it
    detects a coding request, otherwise the active model.

Context assembly:
    ``_send_to_model()`` gathers working-memory snippets, relevant knowledge
    concepts, current Mind state, identity, and active goals, then calls
    ``PromptBuilder.build()`` with the full MARK system prompt before
    forwarding to ``ModelManager.generate()``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.ui.command_router import CommandRouter

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent

# ---------------------------------------------------------------------------
# Coding-request detection
# ---------------------------------------------------------------------------

_CODING_KEYWORDS: frozenset[str] = frozenset(
    {
        "python", "javascript", "typescript", "java", "rust", "golang", "c++",
        "c#", "ruby", "php", "swift", "kotlin", "scala", "haskell",
        "code", "script", "function", "class", "algorithm", "program",
        "implement", "write a", "build a", "debug", "error", "exception",
        "sql", "query", "api", "endpoint", "parser", "scraper", "regex",
        "library", "module", "import", "async", "await", "loop", "recursion",
        "sorting", "data structure", "refactor", "test", "unittest",
    }
)


def _is_coding_request(message: str) -> bool:
    """Return ``True`` when *message* looks like a programming task."""
    lower = message.lower()
    return any(kw in lower for kw in _CODING_KEYWORDS)


def _pick_model(agent: "SmartAgent", message: str) -> str | None:
    """
    Choose which model id to use for *message*.

    Returns:
        The coding model id if the request looks like a programming task
        AND the coding model is registered.  Otherwise the current active
        model id.  ``None`` means no model is active (caller should abort).
    """
    active = agent.model_manager.active_model_id
    if active is None:
        return None
    if _is_coding_request(message):
        coding_model = agent.model_manager.settings.ollama_coding_model
        if agent.model_manager.registry.find(coding_model) is not None:
            if coding_model != active:
                return coding_model
    return active


# ---------------------------------------------------------------------------
# Context assembly helpers
# ---------------------------------------------------------------------------


def _gather_memory(agent: "SmartAgent", message: str) -> list[str]:
    try:
        hits = agent.memory.search(message, limit=3)
        return [h.content for h in hits]
    except Exception:
        return []


def _gather_knowledge(agent: "SmartAgent", message: str) -> list[str]:
    try:
        results = agent.knowledge.search(message, limit=2)
        return [
            f"{r.concept.title}: {r.concept.summary or r.concept.description[:80]}"
            for r in results
        ]
    except Exception:
        return []


def _get_mind_state(agent: "SmartAgent") -> str:
    try:
        return agent.mind.state_machine.current_state.value
    except Exception:
        return ""


def _get_identity(agent: "SmartAgent") -> str:
    try:
        return f"MARK v{agent.mind.identity_engine.version} — {agent.mind.identity_engine.mission}"
    except Exception:
        return "MARK — personal AI assistant for Mr. Smart"


def _get_goals(agent: "SmartAgent") -> list[str]:
    try:
        return [g.name for g in agent.goals.list_goals(status="active")]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Core send-to-model logic
# ---------------------------------------------------------------------------


def _send_to_model(agent: "SmartAgent", message: str) -> str:
    """
    Build a full MARK context prompt and send *message* to the active model.

    Returns the model's text response, or an error string if unavailable.
    """
    model_id = _pick_model(agent, message)
    if model_id is None:
        return "No model is active.  Use 'model use <name>' to select one, then try again."

    # Assemble context
    memory_snippets = _gather_memory(agent, message)
    knowledge_snippets = _gather_knowledge(agent, message)
    mind_state = _get_mind_state(agent)
    identity = _get_identity(agent)
    goals = _get_goals(agent)

    # Note which model is actually being used (may differ from active when coding)
    active_model_id = agent.model_manager.active_model_id
    routed_note = ""
    if model_id != active_model_id:
        routed_note = f"[Routing to {model_id} — coding request detected]\n\n"

    # Build prompt with full MARK context
    from smartagent.models.prompts.mark_system_prompt import MARK_SYSTEM_PROMPT
    from smartagent.models.prompts.prompt_builder import PromptBuilder

    prompt = PromptBuilder().build(
        message,
        system_prompt=MARK_SYSTEM_PROMPT,
        knowledge_snippets=knowledge_snippets,
        mind_state=mind_state,
        identity=identity,
        goals=goals,
    )
    # Inject working-memory refs directly (not via ConversationContext so we
    # don't modify any persistent state from within a console command).
    if memory_snippets:
        from smartagent.models.prompts.prompt_builder import Prompt
        prompt = Prompt(
            system_prompt=prompt.system_prompt,
            user_message=prompt.user_message,
            history_lines=prompt.history_lines,
            memory_context=tuple(memory_snippets),
            skill_context=prompt.skill_context,
            tool_results=prompt.tool_results,
            future_context=prompt.future_context,
            knowledge_context=prompt.knowledge_context,
            mind_state=prompt.mind_state,
            identity=prompt.identity,
            goals=prompt.goals,
        )

    try:
        # Ensure the target model is loaded before generating.
        agent.model_manager.load(model_id)
        response = agent.model_manager.generate(prompt, model_id=model_id)
        text = response.text or ""
        if not text or response.metadata.get("error"):
            return f"{routed_note}Ollama server unavailable."
        return f"{routed_note}{text}"
    except Exception:
        return f"{routed_note}Ollama server unavailable."


# ---------------------------------------------------------------------------
# fallback_chat — wired into CommandRouter.set_fallback() by Console
# ---------------------------------------------------------------------------


def fallback_chat(agent: "SmartAgent", raw: str) -> str:
    """
    Free-text fallback: route *raw* to the active model if one is loaded.

    When no model is active the router's standard "Unknown command" message
    is returned, preserving all pre-Milestone-9 behaviour.
    """
    if agent.model_manager.active_model_id is None:
        first_word = raw.split()[0] if raw.split() else ""
        return f'Unknown command: "{first_word}"\nType "help" for available commands.'
    return _send_to_model(agent, raw)


# ---------------------------------------------------------------------------
# models — list registered providers
# ---------------------------------------------------------------------------


def handle_models(agent: "SmartAgent", args: list[str]) -> str:
    """List every registered model provider with its status."""
    try:
        providers = agent.model_manager.list_models()
        if not providers:
            return "No model providers registered."

        active_id = agent.model_manager.active_model_id
        lines = [f"Models ({len(providers)} registered)", ""]

        for m in providers:
            status = m.status().value
            is_active = "● active  " if m.id == active_id else "          "
            lines.append(f"  {is_active}{m.id}")
            lines.append(f"             provider={m.provider}  status={status}")

        lines.append("")
        if active_id:
            lines.append(f"  Active model : {active_id}")
        else:
            lines.append("  Active model : none  (use 'model use <name>' to select)")

        return "\n".join(lines)
    except Exception as exc:
        return f"[error] Could not list models: {exc}"


# ---------------------------------------------------------------------------
# model — subcommand group: use / current / info / list
# ---------------------------------------------------------------------------


def handle_model(agent: "SmartAgent", args: list[str]) -> str:
    """
    Model subcommands:

        model use <name>    — switch the active model
        model current       — show the active model
        model info          — detailed info about the active model
        model list          — alias for 'models'
    """
    sub = args[0].lower() if args else ""

    if sub == "use":
        return _handle_model_use(agent, args[1:])
    if sub == "current":
        return _handle_model_current(agent)
    if sub == "info":
        return _handle_model_info(agent)
    if sub == "list":
        return handle_models(agent, [])

    return (
        "Model subcommands:\n"
        "  model use <name>   — switch the active model\n"
        "  model current      — show the active model\n"
        "  model info         — info about the active model\n"
        "  model list         — list all registered models"
    )


def _handle_model_use(agent: "SmartAgent", args: list[str]) -> str:
    """Switch the active model to *name*."""
    if not args:
        return "Usage: model use <model-name>  (e.g. model use llama3.1:8b)"
    name = " ".join(args)
    try:
        agent.model_manager.switch_model(name)
        return f"Active model: {name}"
    except KeyError:
        available = agent.model_manager.list_available()
        avail_str = ", ".join(available) if available else "none"
        return (
            f"Model {name!r} is not registered.\n"
            f"Available: {avail_str}\n"
            f"Use 'models' to see the full list."
        )
    except Exception as exc:
        return f"[error] Could not switch to {name!r}: {exc}"


def _handle_model_current(agent: "SmartAgent") -> str:
    """Show the currently active model."""
    active_id = agent.model_manager.active_model_id
    if active_id is None:
        return "No model is active.  Use 'model use <name>' to select one."
    model = agent.model_manager.registry.find(active_id)
    if model is None:
        return f"Active model: {active_id}"
    return (
        f"Active model : {model.id}\n"
        f"Name         : {model.name}\n"
        f"Provider     : {model.provider}\n"
        f"Status       : {model.status().value}"
    )


def _handle_model_info(agent: "SmartAgent") -> str:
    """Detailed information about the active model."""
    active_id = agent.model_manager.active_model_id
    if active_id is None:
        return "No model is active.  Use 'model use <name>' to select one."
    model = agent.model_manager.registry.find(active_id)
    if model is None:
        return f"Active model: {active_id}"

    meta = model.metadata()
    lines = [
        f"Model Information: {meta.id}",
        "",
        f"  Name             : {meta.name}",
        f"  Provider         : {meta.provider}",
        f"  Version          : {meta.version}",
        f"  Status           : {model.status().value}",
        f"  Context window   : {meta.context_window:,} tokens",
        "",
        "  Capabilities:",
        f"    Streaming      : {'yes' if meta.supports_streaming else 'no'}",
        f"    Tool calls     : {'yes' if meta.supports_tools else 'no'}",
        f"    Images         : {'yes' if meta.supports_images else 'no'}",
        f"    Embeddings     : {'yes' if meta.supports_embeddings else 'no'}",
        f"    Functions      : {'yes' if meta.supports_functions else 'no'}",
    ]

    # If it's an OllamaProvider, try to show server-side info.
    try:
        from smartagent.models.providers.ollama_provider import OllamaProvider
        if isinstance(model, OllamaProvider):
            info = model.model_info(timeout=3.0)
            if info:
                lines.append("")
                lines.append("  Ollama details:")
                lines.append(f"    Family         : {info.family}")
                lines.append(f"    Size           : {info.size / 1_000_000_000:.2f} GB")
                lines.append(f"    Modified       : {info.modified_at}")
    except Exception:
        pass

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# chat — explicit chat command
# ---------------------------------------------------------------------------


def handle_chat(agent: "SmartAgent", args: list[str]) -> str:
    """
    Send a message to the active model with full MARK context.

    Usage:  chat <your message>

    MARK automatically routes coding requests to the configured coding model
    (default: qwen2.5-coder:7b).

    Example:
        mark> chat write a python web scraper
    """
    if not args:
        return (
            "Usage: chat <message>\n"
            "Example: chat hello\n"
            "Tip: with a model active, you can also type freely without 'chat'"
        )
    message = " ".join(args)
    return _send_to_model(agent, message)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(router: CommandRouter) -> None:
    """Register model and chat commands with *router*."""
    router.register("models", handle_models, "list registered model providers", "MODELS", 0)
    router.register("model", handle_model, "model use/current/info/list", "MODELS", 1)
    router.register("chat", handle_chat, "chat with the active model", "MODELS", 2)
