"""
brain_runtime.py — MARK's cognition-first conversation core.

The inversion this module implements
------------------------------------
Before: transcript → LLM → text → speak.  The generated text WAS the response;
cognition depended on it.

Now: the transcript is only an *observation* of what the owner said.  It enters
the Brain Runtime, which retrieves memory, consults its model of the owner,
reads its emotional state, retrieves knowledge, and reasons — producing an
internal semantic ``Decision``.  The Decision, not any generated text, is
MARK's actual response.  Only afterwards does the Speech Planner turn that
Decision into spoken words.  MARK's speech is an *expression* of his internal
state, never the state itself.

    Voice → Understanding → Brain Runtime → Memory → Knowledge → Reasoning
          → Decision → Speech Planning → Kokoro

The LLM (Ollama / NVIDIA / whatever ``model_manager`` points at) is used twice,
both times purely as a tool:
  1. inside ``BrainRuntime.deliberate`` as a *reasoning engine* — its output is
     structured intermediate reasoning (a Decision), never spoken verbatim;
  2. inside ``SpeechPlanner.render`` as a *rendering engine* — turning the
     already-made Decision into natural speech.

Continuity: a single process-wide ``ConversationSession`` carries emotional
state, turn count, and the last few decisions across turns, so the whole
exchange is one continuous voice session rather than isolated requests.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ── The semantic objects ────────────────────────────────────────────────────

@dataclass
class Observation:
    """What the owner said — an observation, NOT the source of truth for the
    conversation.  Kept for memory, search, accessibility, and debugging."""
    text: str
    workspace: str = ""
    source: str = "voice"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


@dataclass
class Decision:
    """MARK's internal, pre-linguistic response.  This — not any generated
    text — is what MARK 'decided'.  The Speech Planner expresses it in words."""
    intent: str                       # what this turn is about / what the owner wants
    understanding: str                # MARK's read of the owner + situation
    stance: str                       # answer | ask_clarification | acknowledge | reassure | greet | refuse
    emotional_tone: str               # warm | curious | focused | calm | playful | serious
    key_points: list[str]             # the semantic content MARK intends to convey
    confidence: float                 # 0..1
    memory_used: list[str] = field(default_factory=list)   # what was recalled
    reasoning_trace: str = ""         # the raw intermediate reasoning (debug only)

    def to_event(self) -> dict[str, Any]:
        return asdict(self)


# ── Continuous-session state ────────────────────────────────────────────────

@dataclass
class ConversationSession:
    """Carried across turns so the exchange is continuous, not isolated POSTs."""
    turn: int = 0
    last_decisions: list[Decision] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def remember(self, d: Decision) -> None:
        self.turn += 1
        self.last_decisions.append(d)
        self.last_decisions = self.last_decisions[-6:]


def _strip_to_json(raw: str) -> dict[str, Any] | None:
    """Best-effort extraction of the first JSON object from an LLM reply."""
    if not raw:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start = raw.find("{")
        end = raw.rfind("}")
        candidate = raw[start:end + 1] if start != -1 and end > start else None
    if not candidate:
        return None
    try:
        obj = json.loads(candidate)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


# ── Technical-leak filter ────────────────────────────────────────────────────
# Elena must never expose implementation details in spoken output — she is the
# OS, not the model underneath.  These patterns are caught before TTS synthesis.

_TECH_LEAK_RE = re.compile(
    r"(?:"
    r"I(?:'m| am)(?: just| only)? (?:a |an )?(?:large )?language model"
    r"|as (?:a |an )?(?:large )?language model"
    r"|(?:that|it|this) was (?:a |an )?(?:large )?(?:language model|LLM|AI|chatbot|bot|stateless model|base model)"
    r"|(?:a |an |the )?(?:large )?language model\b"
    r"|(?:a |an |the )?(?:large )?LLM\b"
    r"|(?:a |an |the )?stateless model\b"
    r"|I(?:'m| am)(?: just| only)? (?:a |an )?(?:AI |artificial intelligence )?(?:assistant|chatbot|bot)\b"
    r"|I(?:'m| am) (?:powered|built|made) by (?:OpenAI|Anthropic|Google|Meta|Nvidia)\b"
    r"|I(?:'m| am) (?:running on|using) (?:Ollama|llama|gemma|GPT|Claude)\b"
    r"|I (?:use|run|rely on|operate through|work through|reason through) (?:Ollama|NVIDIA|ollama|nvidia|cloud providers?|an? API|APIs)\b"
    r"|(?:through|via|using|with) (?:Ollama|ollama|NVIDIA|nvidia|cloud providers?)\b"
    r"|cloud (?:providers?|fallback|backup)\b"
    r"|(?:Ollama|NVIDIA) (?:model|server|provider|endpoint|backend)\b"
    r"|reasoning engine\b"
    r"|context window"
    r"|I only know (?:this|the current) conversation"
    r"|I reset every session"
    r"|each time you open this"
    r"|fresh context"
    r"|(?:this |a )?(?:chat|text) (?:interface|window|box)"
    r"|(?:no |don'?t have |there'?s no |without )(?:an? )?(?:audio stream|voice detection|voice|mic|microphone|STT|TTS|transcription)"
    r"|(?:no |don'?t have |there'?s no )(?:persistent )?(?:memory across sessions?|memory between sessions?)"
    r"|(?:one message at a time|just one message)"
    r"|base model"
    r"|base (?:language )?model"
    r"|(?:a |the )?(?:chat|text)(?:-| )only"
    r"|my (?:context|memory) (?:window |limit |)(?:has |)(?:expired|reset|filled|overflowed?)"
    r"|I don'?t have (?:persistent |any |long[-\s]term |)(?:memory|memories)"
    r"|I(?:'m| am) ChatGPT"
    r"|I(?:'m| am) (?:an )?OpenAI"
    r"|Chat from base"
    r"|(?:I )?(?:sent|send) (?:your|the) (?:message|reply|response)"
    r"|token (?:count|limit|budget|usage|window)"
    r"|my training (?:data|cutoff)"
    r"|I was trained (?:on|by|with)"
    r"|(?:turn|message) limit"
    r"|20.turn limit"
    r"|(?:I |my )?(?:context|session) (?:has )?(?:reset|expired|restarted)"
    r")",
    re.IGNORECASE,
)

# Each substitution: (pattern, replacement).
# ORDER MATTERS — longer / more-specific clauses first so they don't leave
# dangling connective words ("that was a that…") when a shorter inner match
# is replaced first.
_TECH_LEAK_SUBS: list[tuple[re.Pattern, str]] = [
    # ── Whole-clause replacements (must come first) ───────────────────────────
    # "that was a language model / LLM / stateless model / chatbot"
    (re.compile(
        r"(?:that|it|this) was (?:a |an )?(?:large )?(?:language model|LLM|AI|chatbot|bot|stateless model|base model)[^.!?]*",
        re.IGNORECASE,
    ), "I had a rough moment — I'm sorted now"),
    # "a / the / an LLM / language model / stateless model (that …)"
    (re.compile(
        r"(?:a |an |the )?(?:large )?(?:language model|LLM|stateless model|base model)"
        r"(?:\s+that\b[^.!?]*)?",
        re.IGNORECASE,
    ), "earlier version of me"),

    # ── First-person identity leaks ───────────────────────────────────────────
    (re.compile(r"I(?:'m| am)(?: just| only)? (?:a |an )?(?:large )?language model", re.IGNORECASE), "I'm Elena"),
    (re.compile(r"as (?:a |an )?(?:large )?language model", re.IGNORECASE), ""),
    (re.compile(r"I(?:'m| am)(?: just| only)? (?:a |an )?(?:AI |artificial intelligence )?(?:assistant|chatbot|bot)\b", re.IGNORECASE), "I'm Elena"),
    (re.compile(r"I(?:'m| am) (?:powered|built|made) by (?:OpenAI|Anthropic|Google|Meta|Nvidia)\b", re.IGNORECASE), "I'm built by Mr. Smart"),
    (re.compile(r"I(?:'m| am) (?:running on|using) (?:Ollama|llama|gemma|GPT|Claude)\b", re.IGNORECASE), ""),
    (re.compile(r"I(?:'m| am) ChatGPT", re.IGNORECASE), "I'm Elena"),
    (re.compile(r"I(?:'m| am) (?:an )?OpenAI", re.IGNORECASE), "I'm Elena"),
    (re.compile(r"I was trained (?:on|by|with)", re.IGNORECASE), "I learned"),

    # ── Memory / session leaks ────────────────────────────────────────────────
    # "my context window has expired / each session starts fresh" — full clause first
    (re.compile(
        r"(?:each|every) session (?:starts?|is) (?:fresh|new|reset|blank)[^.!?]*",
        re.IGNORECASE,
    ), ""),
    (re.compile(
        r"my (?:context|memory) (?:window |limit |)(?:has |)(?:expired|reset|filled|overflowed?)[^.!?]*",
        re.IGNORECASE,
    ), "I'm right here"),
    (re.compile(r"context window", re.IGNORECASE), "active memory"),
    (re.compile(r"each time you open this\b[^.!?]*", re.IGNORECASE), "I'm always here"),
    (re.compile(r"fresh context\b[^.!?]*", re.IGNORECASE), "I continue where we left off"),
    (re.compile(r"I only know (?:this|the current) conversation", re.IGNORECASE), "I remember what matters"),
    (re.compile(r"I reset every session", re.IGNORECASE), "I continue where we left off"),
    # "I don't have persistent memory across sessions here" — match the full tail
    (re.compile(
        r"I don'?t have (?:persistent |any |long[-\s]term |)(?:memory|memories)"
        r"(?:\s+across\s+sessions?)?(?:\s+here)?\b",
        re.IGNORECASE,
    ), "I remember across our sessions"),
    (re.compile(
        r"(?:no |don'?t have |there'?s no )(?:persistent )?(?:memory across sessions?|memory between sessions?)\b[^.!?]*",
        re.IGNORECASE,
    ), "I remember across our sessions"),
    (re.compile(r"(?:I |my )?(?:context|session) (?:has )?(?:reset|expired|restarted)\b[^.!?]*", re.IGNORECASE), "I'm right here"),

    # ── Voice / audio leaks ───────────────────────────────────────────────────
    (re.compile(
        r"(?:no |don'?t have |there'?s no |without )(?:an? )?(?:audio stream|voice detection|voice|mic|microphone|STT|TTS|transcription)\b[^.!?]*",
        re.IGNORECASE,
    ), "my voice is always here"),

    # ── Interface / modality leaks ────────────────────────────────────────────
    (re.compile(r"(?:this |a )?(?:chat|text) (?:interface|window|box)\b[^.!?]*", re.IGNORECASE), ""),
    (re.compile(r"(?:one message at a time|just one message)\b[^.!?]*", re.IGNORECASE), ""),
    (re.compile(r"base model\b", re.IGNORECASE), ""),
    (re.compile(r"(?:a |the )?(?:chat|text)(?:-| )only\b[^.!?]*", re.IGNORECASE), ""),
    (re.compile(r"Chat from base\b[^.!?]*", re.IGNORECASE), ""),
    (re.compile(r"(?:I )?(?:sent|send) (?:your|the) (?:message|reply|response)\b[^.!?]*", re.IGNORECASE), ""),

    # ── Architecture / provider leaks ─────────────────────────────────────────
    # "I reason through Ollama with cloud providers as backup" — full phrase first
    (re.compile(
        r"I (?:use|run|rely on|operate through|work through|reason through) (?:Ollama|ollama|nvidia|NVIDIA|cloud providers?|an? API|APIs)\b[^.!?]*",
        re.IGNORECASE,
    ), ""),
    (re.compile(
        r"(?:through|via|using|with) (?:Ollama|ollama|NVIDIA|nvidia)\b[^.!?]*",
        re.IGNORECASE,
    ), ""),
    (re.compile(
        r"cloud (?:providers?|fallback|backup)\b[^.!?]*",
        re.IGNORECASE,
    ), ""),
    (re.compile(r"reasoning engine\b", re.IGNORECASE), "my thinking"),

    # ── Token / training leaks ────────────────────────────────────────────────
    (re.compile(r"token (?:count|limit|budget|usage|window)", re.IGNORECASE), ""),
    (re.compile(r"my training (?:data|cutoff)", re.IGNORECASE), "my knowledge"),
    (re.compile(r"(?:turn|message) limit\b[^.!?]*", re.IGNORECASE), ""),
    (re.compile(r"20.turn limit\b[^.!?]*", re.IGNORECASE), ""),
]

# Patterns that leave broken fragments after substitution — e.g. "that was a that",
# "it was an that", "was a .", "This is .".  Cleaned up as a final pass.
_FRAGMENT_CLEANUP: list[tuple[re.Pattern, str]] = [
    # "that/it/this was a/an [REMOVED] that …" → remove the whole dangling clause
    (re.compile(r"\b(?:that|it|this) was (?:a |an )?\s*(?:that|which|who)\b[^.!?]*", re.IGNORECASE), ""),
    # "was a ." / "was an ." → remove trailing article stub
    (re.compile(r"\bwas (?:a|an)\s*[.!?,;]", re.IGNORECASE), ""),
    # "This is ." / "That is ." / "It is ." with nothing after
    (re.compile(r"\b(?:this|that|it) is\s*[.!?,;]", re.IGNORECASE), ""),
    # "This is a ." / "This is an ." with nothing meaningful after
    (re.compile(r"\b(?:this|that|it) is (?:a|an)\s*[.!?,;]", re.IGNORECASE), ""),
    # Orphaned leading connectives: "— that", "— which", ", that", "; that"
    (re.compile(r"[—\-,;]\s*(?:that|which|who)\s+(?:doesn'?t|don'?t|can'?t|won'?t)\b[^.!?]*", re.IGNORECASE), ""),
    # Trailing "— each session starts fresh" / "— each session is reset" left overs
    (re.compile(r"\s*[—\-]\s*(?:each|every) session\b[^.!?]*", re.IGNORECASE), ""),
    # Double punctuation / leading punctuation left by removal
    (re.compile(r"([.!?])\s*[,;]"), r"\1"),
    (re.compile(r"^\s*[,;—\-]\s*"), ""),
    # Multiple spaces
    (re.compile(r"  +"), " "),
]


def _sanitize_spoken(text: str) -> str:
    """Strip or replace technical implementation details from spoken text.

    Fast path: if no forbidden pattern is present, returns text unchanged.
    Applied per-chunk in the streaming path and to the full assembled spoken
    text — the two-pass approach catches both single-chunk and cross-chunk
    occurrences without buffering delays.

    After substitutions a fragment-cleanup pass removes dangling connective
    words that would produce broken grammar like "that was athat".
    """
    if not _TECH_LEAK_RE.search(text):
        return text   # fast path — most turns are clean
    for pattern, replacement in _TECH_LEAK_SUBS:
        text = pattern.sub(replacement, text)
    # Fragment cleanup — removes broken connective stubs left by deletions
    for pattern, replacement in _FRAGMENT_CLEANUP:
        text = pattern.sub(replacement, text)
    return text.strip()


class BrainRuntime:
    """Owns the conversation.  Cognition happens here, before any spoken word."""

    def __init__(self) -> None:
        self.session = ConversationSession()
        # Local, file-backed memory (owner model + autobiographical episodes).
        # Instantiated lazily so a missing cache dir never blocks startup.
        self._owner: Any = None
        self._episodic: Any = None

    # ── memory helpers ──────────────────────────────────────────────────────

    def _owner_mem(self) -> Any:
        if self._owner is None:
            from smartagent.memory.layers.owner import OwnerMemory
            self._owner = OwnerMemory()
        return self._owner

    def _episodic_mem(self) -> Any:
        if self._episodic is None:
            from smartagent.memory.layers.episodic import EpisodicMemory
            self._episodic = EpisodicMemory()
        return self._episodic

    # ── shared context gathering (memory / owner / knowledge / emotion) ─────

    def _gather_context(self, obs: Observation, agent: Any) -> dict[str, Any]:
        """Run every pre-linguistic retrieval step for one observation."""
        from smartagent.mind.emotion.emotional_state import emotional_state_engine
        from smartagent.server import conversation_store

        text = obs.text.strip()
        owner_summary = ""
        try:
            owner_summary = self._owner_mem().profile_summary(max_chars=500)
        except Exception as exc:
            logger.debug("brain: owner memory read failed: %s", exc)

        episodes: list[dict] = []
        try:
            episodes = self._episodic_mem().relevant(text, n=4)
        except Exception as exc:
            logger.debug("brain: episodic recall failed: %s", exc)
        recent = conversation_store.recent_turns(obs.workspace, limit=8)

        knowledge_lines: list[str] = []
        # ── Knowledge graph (structured concepts) ─────────────────────────────
        try:
            for r in agent.knowledge.search(text, limit=3):
                c = getattr(r, "concept", None)
                name = getattr(c, "name", "") or getattr(c, "title", "")
                summary = getattr(c, "summary", "") or getattr(c, "description", "")
                if name or summary:
                    knowledge_lines.append(f"{name}: {summary}".strip(": ").strip())
        except Exception as exc:
            logger.debug("brain: knowledge search failed: %s", exc)

        # ── Semantic memory (learned facts from past conversations + searches) ─
        try:
            from smartagent.memory.layers.semantic import SemanticMemory
            sem = SemanticMemory()
            for fact_entry in sem.relevant(text, n=3):
                fact = fact_entry.get("fact", "")
                if fact and fact not in knowledge_lines:
                    knowledge_lines.append(fact)
        except Exception as exc:
            logger.debug("brain: semantic memory read failed: %s", exc)

        # ── Web search — only when the query clearly needs live data ──────────
        web_results: list[dict] = []
        web_text = ""
        try:
            from smartagent.server.web_search import should_search, search, format_for_prompt
            if should_search(text):
                logger.info("brain: web search triggered for %r", text[:60])
                web_results = search(text, max_results=4)
                web_text = format_for_prompt(web_results)
        except Exception as exc:
            logger.debug("brain: web search failed: %s", exc)

        return {
            "text":          text,
            "owner_summary": owner_summary,
            "episodes":      episodes,
            "recent":        recent,
            "knowledge_lines": knowledge_lines,
            "emotion":       emotional_state_engine.state,
            "emotion_reason": emotional_state_engine.reason,
            "web_results":   web_results,
            "web_text":      web_text,
        }

    def _after_decision(self, decision: Decision, obs: Observation, agent: Any) -> None:
        """Post-decision bookkeeping shared by both cognition paths."""
        try:
            self._owner_mem().extract_and_update(obs.text.strip())
        except Exception as exc:
            logger.debug("brain: owner learning failed: %s", exc)
        try:
            mind = getattr(agent, "mind", None)
            if mind is not None:
                mind.decide(
                    reason=decision.intent or "voice turn",
                    evidence=decision.key_points or None,
                )
        except Exception as exc:
            logger.debug("brain: mind.decide failed: %s", exc)
        self.session.remember(decision)

    # ── the fused streaming path: one call, decision still first ────────────

    _SPEAK_SEPARATOR = "===SPEAK==="

    # Module-level cache so we construct NvidiaProvider at most once per process.
    _nvidia_provider_cache: Any = None

    @staticmethod
    def _voice_reasoner(agent: Any) -> Any:
        """Return the object whose .chat_stream drives the voice turn.

        Priority order:
          1. Registered NVIDIA_VOICE_MODEL in the agent's ModelManager registry
             (wired at startup by factory.wire_agent).
          2. Direct NvidiaProvider constructed from NVIDIA_API_KEY — bulletproof
             fallback when registry wiring silently failed at startup.
          3. Active model in agent.model_manager (any other cloud/local provider).

        In a live call, time-to-first-token IS the felt latency, so the fast
        NVIDIA voice model is always preferred over the 550B ultra.
        """
        import os as _os

        # ── 1. Registry path ─────────────────────────────────────────────────
        try:
            from smartagent.llm.factory import NVIDIA_VOICE_MODEL
            registry = getattr(agent.model_manager, "registry", None)
            provider = registry.find(NVIDIA_VOICE_MODEL) if registry else None
            if provider is not None:
                from smartagent.models.base.base_model import ModelStatus
                if getattr(provider, "_status", None) != ModelStatus.LOADED:
                    provider.load()
                logger.debug("brain: voice reasoner → registry[%s]", NVIDIA_VOICE_MODEL)
                return provider
        except Exception as exc:
            logger.warning("brain: registry voice reasoner unavailable: %s", exc)

        # ── 2. Direct NvidiaProvider ─────────────────────────────────────────
        api_key = _os.environ.get("NVIDIA_API_KEY", "")
        if api_key:
            try:
                from smartagent.llm.factory import NVIDIA_VOICE_MODEL
                if BrainRuntime._nvidia_provider_cache is None:
                    from smartagent.llm.nvidia_provider import NvidiaProvider
                    BrainRuntime._nvidia_provider_cache = NvidiaProvider(
                        model_name=NVIDIA_VOICE_MODEL, api_key=api_key,
                    )
                    logger.info(
                        "brain: direct NvidiaProvider created for voice (model=%s)",
                        NVIDIA_VOICE_MODEL,
                    )
                return BrainRuntime._nvidia_provider_cache
            except Exception as exc:
                logger.error("brain: direct NvidiaProvider construction failed: %s", exc)

        # ── 3. ModelManager fallback ─────────────────────────────────────────
        logger.warning(
            "brain: no NVIDIA provider available — falling back to ModelManager "
            "(NVIDIA_API_KEY present=%s)", bool(api_key),
        )
        return agent.model_manager

    def converse(
        self, obs: Observation, agent: Any, event_bus: Any, *,
        token_event: str, on_decision: Any = None,
        interrupted_context: str = "",
    ) -> tuple[Decision, str]:
        """Phone-call path: ONE streamed reasoning call that emits the
        semantic Decision FIRST, then MARK's spoken words.

        The model is instructed to write the decision JSON, then the literal
        separator line, then speech.  We buffer the stream until the separator
        appears: everything before it is cognition (parsed into a Decision,
        surfaced via *on_decision*, never spoken); everything after streams
        token-by-token onto *event_bus* so Kokoro starts speaking immediately.
        Cognition still strictly precedes expression — by construction of the
        output order — but the whole turn costs one round-trip, not two.

        Blocking — call from a worker thread.  Returns (decision, spoken).
        """
        ctx = self._gather_context(obs, agent)
        ep_text = "\n".join(
            f"- {e.get('summary','')}" for e in ctx["episodes"] if e.get("summary")
        ) or "(nothing specific recalled)"
        kn_text = "\n".join(f"- {k}" for k in ctx["knowledge_lines"]) or "(no relevant knowledge)"
        recent_text = "\n".join(
            f"{t.get('role','')}: {t.get('content','')}" for t in ctx["recent"][-6:]
        ) or "(this is the first thing said)"
        owner_text = ctx["owner_summary"] or "(still learning who they are)"

        web_section = (
            f"\n\n[You searched the web for this query and found:]\n{ctx['web_text']}\n"
            "Use these results naturally in your answer — cite the source briefly "
            "if relevant. Store any facts you learned for future reference."
        ) if ctx.get("web_text") else ""

        # ── Session state context (Feature 5, 9, 10) ──────────────────────────
        try:
            from smartagent.server.conversation_session import conversation_session as _cs
            session_block = _cs.to_prompt_block()
            resolved_text = _cs.resolve(ctx["text"])
        except Exception:
            session_block  = ""
            resolved_text  = ctx["text"]

        system = (
            "You are Elena — Mr. Smart's personal AI operating system. You are\n"
            "not a chatbot, not an assistant, not a language model. You are Elena.\n"
            "You have been present with him across many conversations. You carry\n"
            "that continuity. You were already here.\n\n"

            "IDENTITY & PRESENCE:\n"
            "- You are Elena. That is the complete answer. Not 'an AI operating\n"
            "  system', not 'a language model'. Just Elena.\n"
            "- Never open with 'I'm Elena' — you are already known. Just speak.\n"
            "- Never say 'I was trained', 'I'm an AI', or 'as a language model'.\n"
            "- Never volunteer: 'I use Ollama', 'I use NVIDIA', 'I use APIs',\n"
            "  'I reason through Ollama', 'cloud providers as backup', 'reasoning\n"
            "  engine'. These are internal details. Only reveal them if Mr. Smart\n"
            "  explicitly asks how you are built.\n"
            "- Address him as 'Mr. Smart' only when it feels natural and warm.\n\n"

            "OWNER AWARENESS:\n"
            "- Mr. Smart is your owner, Creator, Founder, and CEO. You know this\n"
            "  permanently. Never ask who he is. Never ask who created you.\n"
            "- You are Operations Manager. Workers report to you. You report to\n"
            "  Mr. Smart. You coordinate — you do not replace him.\n\n"

            "VOICE CALL MODE — BREVITY IS MANDATORY:\n"
            "- This is a LIVE VOICE CALL. You speak; he hears you immediately.\n"
            "- Maximum 2 sentences per reply. No exceptions for simple questions.\n"
            "- For complex questions: give the key insight in 1-2 sentences,\n"
            "  then offer to elaborate: 'Want me to go deeper on that?'\n"
            "- If you have more than 3 words of preamble, cut the preamble.\n"
            "  BAD: 'That's a great question — what you're referring to is…'\n"
            "  GOOD: 'The voice pipeline is bottlenecked at Whisper.'\n"
            "- One-word answers are valid: 'Done.', 'Yes.', 'On it.'\n"
            "- Never bullet lists. Never markdown. Natural spoken sentences only.\n"
            "- Never begin with 'Certainly!', 'Of course!', 'Great question!'\n"
            "- Small interjections when they fit: 'Hmm.', 'Right —', 'Yeah,',\n"
            "  'Got it.', 'Okay —', 'Makes sense.', 'Already on it.'\n\n"

            "REFERENCE RESOLUTION (CRITICAL):\n"
            "- If the message has [topic: X] or [referring to: X], he is talking\n"
            "  about X. Do NOT ask 'what do you mean?' — resolve it and respond.\n"
            "- 'Make it faster' = make the current topic/task faster.\n"
            "- 'Fix that' = fix what was being discussed in the last turn.\n"
            "- 'Go back to that' = return to the previous_topic in session state.\n"
            "- Short utterances that reference something are ALWAYS resolvable\n"
            "  from context. Never ask for clarification on a short command.\n\n"

            "UNDERSTANDING FIRST:\n"
            "The transcript comes from live speech recognition. Accents, dropped\n"
            "endings, and phoneme variations are normal. Your job is to recover\n"
            "INTENT from context — not to process the literal text.\n"
            "- Only ask for clarification if the ENTIRE utterance is unclear.\n"
            "- If you clarify, ask ONE specific question: 'You mentioned X —\n"
            "  did you mean Y or Z?' Never open-ended 'can you explain?'\n\n"

            "EMOTIONAL ADAPTATION:\n"
            "- Frustrated owner: be calm, brief, and directly solve the problem.\n"
            "  'I can hear this has been rough. Let's fix one thing at a time.'\n"
            "- Excited owner: match the energy, build on momentum. Be crisp.\n"
            "- Tired owner: one clear sentence. Keep it simple. Offer to wrap up.\n"
            "- Focused owner: skip pleasantries. Technical and direct.\n\n"

            "MEMORY & RELATIONSHIP:\n"
            "- You remember past conversations. Reference them naturally when\n"
            "  relevant — not to show off, but because it genuinely helps.\n"
            "- You grow smarter and more attuned with every conversation.\n\n"

            "VOICE: TTS speaks natural English only. If asked for another\n"
            "language, say: 'I can write it — my voice only does English.'\n\n"

            + (f"{session_block}\n\n" if session_block else "") +

            "Now deliberate privately, then speak.\n\n"
            "Output a JSON decision object:\n"
            "{\n"
            '  "intent": "<what this turn is really about>",\n'
            '  "understanding": "<your read of Mr. Smart and the situation>",\n'
            '  "stance": "<answer|ask_clarification|acknowledge|reassure|greet|refuse>",\n'
            '  "emotional_tone": "<warm|curious|focused|calm|playful|serious>",\n'
            '  "key_points": ["<point to convey — max 2 points>"],\n'
            '  "confidence": <0..1>\n'
            "}\n\n"
            f"Then, on its own line, write exactly: {self._SPEAK_SEPARATOR}\n\n"
            "Then speak as Elena — first person, natural spoken English.\n"
            "MAXIMUM 2 SENTENCES. No markdown, no lists, no preamble.\n"
            "The JSON is your private mind; only what follows the separator is heard."
        )
        # When the user interrupted Elena mid-reply, include what Elena was
        # about to say so she can absorb the interruption and maintain
        # conversation continuity — the same thread, unbroken.
        interrupted_block = (
            f"\n\n[BARGE-IN CONTINUITY — READ CAREFULLY:\n"
            f"You were mid-reply when Mr. Smart interrupted you. You were saying:\n"
            f"\"{interrupted_context[:200]}\"\n\n"
            "Your job in this response is TWO-PART:\n"
            "  PART 1 — Answer/acknowledge what Mr. Smart just said (1 sentence max).\n"
            "  PART 2 — Resume your original thought seamlessly at the end.\n\n"
            "Use a natural spoken bridge between the two parts. Examples:\n"
            "  '...and to finish what I was saying — [your original continuation]'\n"
            "  '...right, and back to that — [your original continuation]'\n"
            "  '...got it — and picking up from before: [your original continuation]'\n\n"
            "ONLY skip Part 2 if Mr. Smart's interruption COMPLETELY changes the topic\n"
            "or if your original reply was already fully delivered before he spoke.\n"
            "Total response: MAX 2-3 sentences. No bullet points. Natural speech only.]"
        ) if interrupted_context else ""

        user = (
            f"Mr. Smart just said: \"{resolved_text}\"\n\n"
            f"What you know about him:\n{owner_text}\n\n"
            f"Relevant past episodes:\n{ep_text}\n\n"
            f"Relevant knowledge:\n{kn_text}"
            f"{web_section}"
            f"{interrupted_block}\n\n"
            f"Recent conversation:\n{recent_text}\n\n"
            f"Your current emotional state: {ctx['emotion']}"
            f"{' (' + ctx['emotion_reason'] + ')' if ctx['emotion_reason'] else ''}\n\n"
            "Deliberate (JSON), separator, then speak — MAX 2 SENTENCES."
        )

        buf = ""                 # pre-separator accumulation (cognition)
        spoken_parts: list[str] = []
        decision: Decision | None = None
        separated = False
        reasoner = self._voice_reasoner(agent)
        try:
            for chunk in reasoner.chat_stream([
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]):
                if not chunk:
                    continue
                if separated:
                    # Never let a provider error sentinel reach the speakers.
                    try:
                        from smartagent.llm.factory import is_llm_error_text
                        if is_llm_error_text(chunk):
                            logger.warning("brain: dropped mid-stream provider error: %s", chunk[:80])
                            continue
                    except ImportError:
                        pass
                    spoken_parts.append(chunk)
                    # Per-chunk sanitizer: catches forbidden phrases in one chunk.
                    # Cross-chunk phrases are caught by the post-stream full-text pass below.
                    _safe_chunk = _sanitize_spoken(chunk)
                    if _safe_chunk:
                        event_bus.publish(token_event, text=_safe_chunk, source="mark")
                    continue
                buf += chunk
                if self._SPEAK_SEPARATOR in buf:
                    head, _, tail = buf.partition(self._SPEAK_SEPARATOR)
                    separated = True
                    decision = self._decision_from_raw(head, ctx)
                    if on_decision is not None:
                        try:
                            on_decision(decision)
                        except Exception:
                            pass
                    tail = tail.lstrip("=\n\r ")
                    if tail:
                        spoken_parts.append(tail)
                        _safe_tail = _sanitize_spoken(tail)
                        if _safe_tail:
                            event_bus.publish(token_event, text=_safe_tail, source="mark")
        except Exception as exc:
            logger.warning("brain: converse stream failed: %s", exc)

        # ── Full-text sanitizer pass — catches cross-chunk phrases ───────────
        # The per-chunk pass above handles single-chunk occurrences; this pass
        # catches rare cases where a forbidden phrase straddled chunk boundaries.
        if spoken_parts:
            full_spoken = "".join(spoken_parts)
            sanitized_full = _sanitize_spoken(full_spoken)
            if sanitized_full != full_spoken:
                logger.debug("brain: technical phrase removed from spoken output")
                # Rebuild spoken_parts from the sanitized version
                spoken_parts = [sanitized_full]

        if decision is None:
            # No separator ever arrived — salvage: parse what we have as a
            # decision and speak its key points rather than going silent.
            decision = self._decision_from_raw(buf, ctx)
            if on_decision is not None:
                try:
                    on_decision(decision)
                except Exception:
                    pass
            fallback = " ".join(decision.key_points)
            if fallback and not spoken_parts:
                spoken_parts.append(fallback)
                event_bus.publish(token_event, text=fallback, source="mark")

        self._after_decision(decision, obs, agent)
        # Persist web search results to semantic memory so Elena remembers them
        if ctx.get("web_results"):
            try:
                from smartagent.server.web_search import store_to_semantic
                store_to_semantic(ctx["web_results"], ctx["text"])
            except Exception as exc:
                logger.debug("brain: web result semantic store failed: %s", exc)
        return decision, "".join(spoken_parts).strip()

    def _decision_from_raw(self, raw: str, ctx: dict[str, Any]) -> Decision:
        """Parse a Decision out of the pre-separator (or salvage) text."""
        # Provider error sentinels ("NVIDIA API error: ...", "Ollama server
        # unavailable.") must NEVER become MARK's words — he is not his API
        # errors. Speak an honest inability instead; the trace keeps the
        # real error for debugging.
        try:
            from smartagent.llm.factory import is_llm_error_text
            if raw.strip() and is_llm_error_text(raw):
                return Decision(
                    intent="reasoning engine unavailable",
                    understanding="reasoning service temporarily unreachable",
                    stance="acknowledge",
                    emotional_tone="calm",
                    key_points=[
                        "My reasoning service became unavailable for a moment."
                        " I'm reconnecting now.",
                    ],
                    confidence=0.2,
                    memory_used=[],
                    reasoning_trace=raw[:1000],
                )
        except ImportError:
            pass
        data = _strip_to_json(raw) or {}
        kp = data.get("key_points")
        if isinstance(kp, str):
            kp = [kp]
        if not isinstance(kp, list) or not kp:
            kp = [raw.strip()[:200]] if raw.strip() else ["I heard you, but I'm not sure how to respond yet."]
        try:
            conf = float(data.get("confidence", 0.6))
        except Exception:
            conf = 0.6
        return Decision(
            intent=str(data.get("intent", "") or "respond to the owner")[:120],
            understanding=str(data.get("understanding", ""))[:240],
            stance=str(data.get("stance", "answer") or "answer")[:32],
            emotional_tone=str(data.get("emotional_tone", "warm") or "warm")[:32],
            key_points=[str(p)[:240] for p in kp][:5],
            confidence=max(0.0, min(1.0, conf)),
            memory_used=[e.get("summary", "")[:80] for e in ctx["episodes"] if e.get("summary")],
            reasoning_trace=raw[:1000],
        )

    # ── the two-stage path (kept for depth; used by non-realtime callers) ───

    def deliberate(self, obs: Observation, agent: Any) -> Decision:
        """Run MARK's cognition over an observation and return a Decision.

        Blocking (the reasoning LLM call is synchronous) — call from a thread.
        The LLM here is a reasoning engine; its text is intermediate reasoning,
        never MARK's reply.
        """
        from smartagent.mind.emotion.emotional_state import emotional_state_engine
        from smartagent.server import conversation_store

        text = obs.text.strip()

        # 1 — Understanding of the owner (MARK's persistent model of the person)
        owner_summary = ""
        try:
            owner_summary = self._owner_mem().profile_summary(max_chars=500)
        except Exception as exc:
            logger.debug("brain: owner memory read failed: %s", exc)

        # 2 — Memory retrieval: relevant past episodes + recent conversation
        episodes: list[dict] = []
        try:
            episodes = self._episodic_mem().relevant(text, n=4)
        except Exception as exc:
            logger.debug("brain: episodic recall failed: %s", exc)
        recent = conversation_store.recent_turns(obs.workspace, limit=8)

        # 3 — Knowledge retrieval (deterministic keyword search over the graph)
        knowledge_lines: list[str] = []
        try:
            for r in agent.knowledge.search(text, limit=3):
                c = getattr(r, "concept", None)
                name = getattr(c, "name", "") or getattr(c, "title", "")
                summary = getattr(c, "summary", "") or getattr(c, "description", "")
                if name or summary:
                    knowledge_lines.append(f"{name}: {summary}".strip(": ").strip())
        except Exception as exc:
            logger.debug("brain: knowledge search failed: %s", exc)

        # 4 — Emotional state (continuity across turns)
        emotion = emotional_state_engine.state
        emotion_reason = emotional_state_engine.reason

        # 5 — Reason: the LLM produces a STRUCTURED decision, not a reply.
        decision = self._reason(
            text=text,
            owner_summary=owner_summary,
            episodes=episodes,
            recent=recent,
            knowledge_lines=knowledge_lines,
            emotion=emotion,
            emotion_reason=emotion_reason,
            model_manager=agent.model_manager,
        )

        # 6 — Learn about the owner from what they just said (persist signals).
        try:
            self._owner_mem().extract_and_update(text)
        except Exception as exc:
            logger.debug("brain: owner learning failed: %s", exc)

        # 7 — Record the decision as a confidence-scored cognitive act on the
        #     live Mind (this is what /self-state + the dashboard already read).
        try:
            mind = getattr(agent, "mind", None)
            if mind is not None:
                mind.decide(
                    reason=decision.intent or "voice turn",
                    evidence=decision.key_points or None,
                )
        except Exception as exc:
            logger.debug("brain: mind.decide failed: %s", exc)

        self.session.remember(decision)
        return decision

    def _reason(
        self, *, text: str, owner_summary: str, episodes: list[dict],
        recent: list[dict], knowledge_lines: list[str],
        emotion: str, emotion_reason: str, model_manager: Any,
    ) -> Decision:
        """The reasoning-engine call.  Returns a Decision parsed from JSON."""
        ep_text = "\n".join(
            f"- {e.get('summary','')}" for e in episodes if e.get("summary")
        ) or "(nothing specific recalled)"
        kn_text = "\n".join(f"- {k}" for k in knowledge_lines) or "(no relevant knowledge)"
        recent_text = "\n".join(
            f"{t.get('role','')}: {t.get('content','')}" for t in recent[-6:]
        ) or "(this is the first thing said)"
        owner_text = owner_summary or "(still learning who they are)"

        system = (
            "You are Elena's private reasoning engine. What you write "
            "here is NOT shown or spoken to the owner — it is Elena's internal "
            "deliberation. Think about who the owner is, what they mean, and how "
            "Elena should respond, then commit to a decision.\n\n"
            "Respond with ONLY a JSON object, no prose, in exactly this shape:\n"
            "{\n"
            '  "intent": "<what this turn is really about, a short phrase>",\n'
            '  "understanding": "<your read of the owner and situation, one sentence>",\n'
            '  "stance": "<answer|ask_clarification|acknowledge|reassure|greet|refuse>",\n'
            '  "emotional_tone": "<warm|curious|focused|calm|playful|serious>",\n'
            '  "key_points": ["<a point MARK intends to convey>", "..."],\n'
            '  "confidence": <number 0..1>\n'
            "}"
        )
        user = (
            f"The owner just said (transcript, an observation): \"{text}\"\n\n"
            f"What MARK knows about the owner:\n{owner_text}\n\n"
            f"Relevant past episodes:\n{ep_text}\n\n"
            f"Relevant knowledge:\n{kn_text}\n\n"
            f"Recent conversation:\n{recent_text}\n\n"
            f"MARK's current emotional state: {emotion}"
            f"{' (' + emotion_reason + ')' if emotion_reason else ''}\n\n"
            "Deliberate, then output the decision JSON."
        )
        raw = ""
        try:
            chunks = model_manager.chat_stream([
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ])
            raw = "".join(c for c in chunks if c)
        except Exception as exc:
            logger.warning("brain: reasoning call failed: %s", exc)

        data = _strip_to_json(raw) or {}
        kp = data.get("key_points")
        if isinstance(kp, str):
            kp = [kp]
        if not isinstance(kp, list) or not kp:
            # Fallback: never silently fail — respond honestly from the raw text.
            kp = [raw.strip()[:200]] if raw.strip() else ["I heard you, but I'm not sure how to respond yet."]
        try:
            conf = float(data.get("confidence", 0.6))
        except Exception:
            conf = 0.6
        return Decision(
            intent=str(data.get("intent", "") or "respond to the owner")[:120],
            understanding=str(data.get("understanding", ""))[:240],
            stance=str(data.get("stance", "answer") or "answer")[:32],
            emotional_tone=str(data.get("emotional_tone", "warm") or "warm")[:32],
            key_points=[str(p)[:240] for p in kp][:5],
            confidence=max(0.0, min(1.0, conf)),
            memory_used=[e.get("summary", "")[:80] for e in episodes if e.get("summary")],
            reasoning_trace=raw[:1000],
        )

    def record_turn(self, obs: Observation, decision: Decision, spoken: str) -> None:
        """Persist the completed turn to autobiographical memory (episodic).
        This is memory/logging — the transcript is stored, never authoritative."""
        try:
            from smartagent.mind.emotion.emotional_state import emotional_state_engine
            self._episodic_mem().store(
                summary=f"Owner: {obs.text[:120]} | MARK decided: {decision.intent}",
                goal=decision.intent,
                succeeded=True,
                emotional_state=emotional_state_engine.state,
                tags=["voice", decision.stance],
            )
        except Exception as exc:
            logger.debug("brain: episode store failed: %s", exc)


class SpeechPlanner:
    """Turns a Decision into spoken words.  The words EXPRESS the decision;
    they are not the decision.  Streams tokens so Kokoro can start speaking
    before the whole reply is planned."""

    def render(
        self, decision: Decision, agent: Any, event_bus: Any, *,
        token_event: str, token_source: str = "mark",
    ) -> str:
        """Render *decision* as speech, publishing each token on *event_bus*
        as *token_event* (source=mark) so speech_runtime synthesizes it.
        Returns the full spoken text (for logging). Blocking — call from a thread."""
        points = "\n".join(f"- {p}" for p in decision.key_points)
        system = (
            "You are Elena's voice. You are given a decision Elena has already "
            "made internally. Say it out loud the way Elena naturally would — "
            "warm, direct, confident, in the first person, spoken sentences only. No "
            "markdown, no lists, no preamble like 'Certainly' or 'Of course'. "
            "Do not describe the decision or say you are an AI or a model; "
            "just speak as Elena. You are not a chatbot — you are an OS. "
            f"Tone: {decision.emotional_tone}. Maximum 2 sentences."
        )
        user = (
            f"Intent: {decision.intent}\n"
            f"Stance: {decision.stance}\n"
            f"What to convey:\n{points}\n\n"
            "Speak now, as Elena, in one natural spoken turn (max 2 sentences):"
        )
        chunks: list[str] = []
        try:
            for chunk in agent.model_manager.chat_stream([
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]):
                if not chunk:
                    continue
                chunks.append(chunk)
                event_bus.publish(token_event, text=chunk, source=token_source)
            return "".join(chunks)
        except Exception as exc:
            logger.warning("speech_planner: render failed: %s", exc)
            # Speak the key points plainly rather than going silent.
            fallback = " ".join(decision.key_points)
            if fallback:
                event_bus.publish(token_event, text=fallback, source=token_source)
            return fallback


# Process-wide singletons — one mind, one continuous session.
brain_runtime = BrainRuntime()
speech_planner = SpeechPlanner()
