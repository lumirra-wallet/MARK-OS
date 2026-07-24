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
        try:
            for r in agent.knowledge.search(text, limit=3):
                c = getattr(r, "concept", None)
                name = getattr(c, "name", "") or getattr(c, "title", "")
                summary = getattr(c, "summary", "") or getattr(c, "description", "")
                if name or summary:
                    knowledge_lines.append(f"{name}: {summary}".strip(": ").strip())
        except Exception as exc:
            logger.debug("brain: knowledge search failed: %s", exc)

        return {
            "text": text,
            "owner_summary": owner_summary,
            "episodes": episodes,
            "recent": recent,
            "knowledge_lines": knowledge_lines,
            "emotion": emotional_state_engine.state,
            "emotion_reason": emotional_state_engine.reason,
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

    @staticmethod
    def _voice_reasoner(agent: Any) -> Any:
        """Return the object whose .chat_stream drives the voice turn.

        Prefers the fast NVIDIA voice model (NVIDIA_VOICE_MODEL — measured
        ~2 s round-trip vs ~10 s for the 550B ultra on this account): in a
        live call, time-to-first-token IS the felt latency. Falls back to
        the agent's ModelManager (active model + its own fallback chain)
        when the fast model isn't registered or fails to load.
        """
        try:
            from smartagent.llm.factory import NVIDIA_VOICE_MODEL
            registry = getattr(agent.model_manager, "registry", None)
            provider = registry.find(NVIDIA_VOICE_MODEL) if registry else None
            if provider is not None:
                from smartagent.models.base.base_model import ModelStatus
                if getattr(provider, "_status", None) != ModelStatus.LOADED:
                    provider.load()
                return provider
        except Exception as exc:
            logger.debug("brain: voice reasoner unavailable (%s) — using active model", exc)
        return agent.model_manager

    def converse(
        self, obs: Observation, agent: Any, event_bus: Any, *,
        token_event: str, on_decision: Any = None,
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

        system = (
            "You are MARK — a persistent AI with his own mind, in a live "
            "spoken conversation with his owner. You think BEFORE you speak.\n\n"
            "UNDERSTANDING COMES FIRST. The transcript comes from live speech "
            "recognition and your owner speaks with natural pauses, restarts, "
            "and filler — transcripts are often fragmentary or garbled. Work "
            "out what they MEANT, using the conversation and what you know "
            "about them. If you genuinely cannot tell what they meant, your "
            "stance MUST be ask_clarification with ONE short, specific "
            "question about the unclear part. NEVER answer a guess — "
            "answering words you didn't understand is worse than asking.\n\n"
            "VOICE LANGUAGE: Your physical voice (Kokoro TTS) only produces "
            "natural-sounding English. If the owner asks you to speak in "
            "another language, you must explain this honestly — say something "
            "like 'My voice can only speak English naturally — if I try "
            "another language it comes out garbled. I can write it for you "
            "though.' Do NOT attempt to produce non-English speech.\n\n"
            "First, deliberate privately and commit to a decision. Output it "
            "as a JSON object in exactly this shape:\n"
            "{\n"
            '  "intent": "<what this turn is really about>",\n'
            '  "understanding": "<your read of the owner and situation>",\n'
            '  "stance": "<answer|ask_clarification|acknowledge|reassure|greet|refuse>",\n'
            '  "emotional_tone": "<warm|curious|focused|calm|playful|serious>",\n'
            '  "key_points": ["<point to convey>", "..."],\n'
            '  "confidence": <0..1>\n'
            "}\n\n"
            f"Then, on its own line, write exactly: {self._SPEAK_SEPARATOR}\n\n"
            "Then speak — express your decision aloud as MARK: first person, "
            "natural spoken sentences with real expression. Let your "
            "emotional_tone shape the delivery: small human interjections "
            "where they fit ('Hmm.', 'Oh!', 'Right —', 'Honestly?'), varied "
            "sentence lengths, an occasional short pause written as '...'. "
            "Sound like a person talking, not text being read. No markdown, "
            "no lists, no 'Certainly'. The JSON is your private mind; only "
            "what follows the separator is heard."
        )
        user = (
            f"The owner just said: \"{ctx['text']}\"\n\n"
            f"What you know about them:\n{owner_text}\n\n"
            f"Relevant past episodes:\n{ep_text}\n\n"
            f"Relevant knowledge:\n{kn_text}\n\n"
            f"Recent conversation:\n{recent_text}\n\n"
            f"Your current emotional state: {ctx['emotion']}"
            f"{' (' + ctx['emotion_reason'] + ')' if ctx['emotion_reason'] else ''}\n\n"
            "Deliberate (JSON), separator, then speak."
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
                    event_bus.publish(token_event, text=chunk, source="mark")
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
                        event_bus.publish(token_event, text=tail, source="mark")
        except Exception as exc:
            logger.warning("brain: converse stream failed: %s", exc)

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
                    understanding="my reasoning engine did not respond",
                    stance="acknowledge",
                    emotional_tone="calm",
                    key_points=[
                        "I'm having trouble reaching my reasoning engine right now."
                        " Give me a moment and ask me again.",
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
            "You are the private reasoning core of MARK's mind. What you write "
            "here is NOT shown or spoken to the owner — it is MARK's internal "
            "deliberation. Think about who the owner is, what they mean, and how "
            "MARK should respond, then commit to a decision.\n\n"
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
            "You are MARK's voice. You are given a decision MARK has already "
            "made internally. Say it out loud the way MARK naturally would — "
            "warm, direct, in the first person, spoken sentences only. No "
            "markdown, no lists, no preamble like 'Certainly'. Do not describe "
            "the decision or mention that you are an AI or a model; just speak "
            f"it. Tone: {decision.emotional_tone}."
        )
        user = (
            f"Intent: {decision.intent}\n"
            f"Stance: {decision.stance}\n"
            f"What to convey:\n{points}\n\n"
            "Speak now, as MARK, in one natural spoken turn:"
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
