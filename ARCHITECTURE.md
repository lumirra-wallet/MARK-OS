# SmartAgent Architecture

This file collects the diagrams referenced from `README.md` and
`ROADMAP.md`. It focuses on the two layers most useful to see visually:
Brain v2's routing pipeline (Milestone 2) and MARK Mind OS v1
(Milestone 6). See `ROADMAP.md`'s Architecture table for the full
package-by-package dependency list.

---

## 1. System overview

```
                         ┌───────────────────────────────────────────┐
                         │              SmartAgent (agent.py)          │
                         │         composition root — wires             │
                         │      everything below together at init       │
                         └───────────────────────────────────────────┘
                                            │
             ┌──────────────────────────────┼───────────────────────────────┐
             │                              │                               │
             ▼                              ▼                               ▼
   ┌───────────────────┐        ┌───────────────────────┐        ┌────────────────────┐
   │   BrainRouter       │        │   ExecutiveController   │        │  Memory / Skills /   │
   │  (decides & acts)   │◄──────►│      (mind/)             │        │  Tools / Models /    │
   │                     │ read-  │  observes, never drives │        │  Planning / Research │
   └───────────────────┘  only   └───────────────────────┘        └────────────────────┘
             │              (MindProviders)         │
             ▼                                      ▼
      handle_message()                     self.mind.describe()
      returns unchanged                    "what is MARK doing / how
      response text                         confident / how healthy"
```

The Mind is deliberately a **sibling observer**, not a layer in the
request path: `BrainRouter` decides what happens; `ExecutiveController`
only watches, via read-only `MindProviders` callables, and via a guarded
post-hoc hook in `handle_message()`.

---

## 2. Brain v2 — the decision pipeline (Milestone 2)

```
                 ┌────────────────────┐
 User message -> │   BrainRouter      │
                 │  (router.py)       │
                 └─────────┬──────────┘
                           │
                           ▼
                 ┌────────────────────┐
                 │  IntentAnalyzer     │  rule-based classification:
                 │ (intent_analyzer.py)│  MEMORY / RESEARCH / TOOL / SKILL /
                 └─────────┬──────────┘  VISION / VOICE / PLANNING / MODEL /
                           │             AUTOMATION / UNKNOWN
                           ▼
                 ┌────────────────────┐
                 │  DecisionEngine     │  orders candidate modules:
                 │ (decision_engine.py)│  Memory > Skills > Tools > Planning
                 └─────────┬──────────┘  > Research > Model > Unknown
                           │
                           ▼
                 ┌────────────────────┐
                 │  ModuleRegistry     │  looks modules up **by name only**
                 │ (module_registry.py)│  — the Brain never hardcodes them
                 └─────────┬──────────┘
                           │
                           ▼
                 ┌────────────────────┐
                 │  Execute            │  the registry's handler runs and
                 │ (module_bindings.py)│  returns a standardized ActionResult
                 └─────────┬──────────┘
                           │
                           ▼
                 ┌────────────────────┐
                 │  Return Response    │  first module to report success
                 │                     │  wins; EventBus is notified either
                 └────────────────────┘  way
```

---

## 3. `handle_message()` data flow, including the Mind observation hook (Milestone 6)

```
SmartAgent.handle_message(message)
  │
  ├─ history_before = len(events.history())
  │
  ├─ mind.state_machine.transition(THINKING)              ─┐
  │                                                          │ Milestone 6
  ├─ result = router.route(message)   <-- UNCHANGED           │ additions —
  │       (Brain v2 pipeline, section 2 above)                │ wrapped in
  │                                                          │ try/except,
  ├─ if no MemorySaved event fired during routing:             never able
  │      memory.remember(message, category="Journal")          to change
  │                                                          │ `result`
  ├─ try:                                                     │
  │     mind.reflection_engine.reflect(outcome of result)      │
  │     mind.state_machine.transition(IDLE)                    │
  │     mind.sync_self_model()                                │
  │  except Exception:                                        │
  │     log a warning, continue                              ─┘
  │
  └─ return result.message   # byte-for-byte identical to pre-Milestone-6 behavior
```

**Why a `try/except` around the whole Mind hook?** The milestone's hard
requirement is that `handle_message()`'s behavior must not change. Wrapping
the observation call means a defect in any Mind engine degrades to "MARK's
self-awareness didn't update this turn" — never "MARK failed to respond."

---

## 4. MARK Mind OS v1 overview (Milestone 6)

```
                              ┌─────────────────────────────┐
                              │      ExecutiveController       │
                              │         (executive/)           │
                              │  the sole coordinator — Part 1  │
                              └───────────────┬─────────────┘
                                               │ owns & coordinates
        ┌───────────────┬───────────────┬─────┼─────┬───────────────┬───────────────┐
        ▼               ▼               ▼     ▼     ▼               ▼               ▼
 ┌─────────────┐ ┌─────────────┐ ┌───────────┐ ┌───────────┐ ┌─────────────┐ ┌─────────────┐
 │ SelfModel     │ │ Identity      │ │ Working    │ │ Attention  │ │ Context       │ │ Confidence    │
 │ Engine        │ │ Engine        │ │ Memory     │ │ Manager    │ │ Manager       │ │ Engine        │
 │ (self_model/) │ │ (identity/)   │ │(working_   │ │(attention/)│ │ (context/)    │ │ (confidence/) │
 │               │ │ round-trips   │ │ memory/)   │ │            │ │               │ │               │
 │ who am I /    │ │ SMARTAGENT.md │ │ short-term,│ │ ranked     │ │ assembles a   │ │ transparent,  │
 │ what am I     │ │               │ │ TTL scratch│ │ focus +    │ │ bounded       │ │ evidence-     │
 │ doing         │ │               │ │ space      │ │ interrupt/ │ │ context blob  │ │ based scoring │
 │               │ │               │ │            │ │ resume     │ │               │ │               │
 └─────────────┘ └─────────────┘ └───────────┘ └───────────┘ └─────────────┘ └─────────────┘
        ▲                                                                              │
        │                                                                              │
        │               ┌─────────────┐               ┌───────────────────────────────┘
        └───────────────┤ StateMachine │               │
                         │  (state/)    │               ▼
                         │ 12 internal  │       ┌─────────────┐        ┌───────────────────────────┐
                         │ states       │       │ Reflection    │        │ Homeostasis (homeostasis/)   │
                         └─────────────┘       │ Engine        │        │ HealthMetrics -> Homeostasis │
                                                │ (reflection/) │        │ Engine -> band (healthy/     │
                                                │ post-task     │        │ degraded/critical)           │
                                                │ self-review   │        │   + DigitalSensorySystem      │
                                                └─────────────┘        │     (10 named signals)         │
                                                                        │   + DigitalHomeostasisLoop      │
                                                                        │     .tick() -> healthy?          │
                                                                        │     overloaded? progress?         │
                                                                        │     goals match mission?           │
                                                                        │     failing? notify owner?          │
                                                                        └───────────────────────────┘

All engines publish onto the same shared EventBus (smartagent.brain.events) —
there is no separate Mind event bus. See events/mind_events.py.
```

**Read-only providers, not hard dependencies:** `ExecutiveController` never
imports `smartagent.brain.agent.SmartAgent`. Instead, `SmartAgent` builds a
`MindProviders` — a bag of zero-argument callables closing over its own
live state — and passes it in at construction time:

```
SmartAgent.__init__()
  ...builds self.goals, self.skill_engine, self.tool_engine, self.model_manager...
  self.mind = ExecutiveController(
      providers=MindProviders(
          active_goal=lambda: ...,
          goals=lambda: [g.name for g in self.goals.list_goals()],
          skills=lambda: self.skill_engine.list_available(),
          tools=lambda: self.tool_engine.list_available(),
          active_model=lambda: self.model_manager.active_model_id,
      ),
      event_bus=self.events,
  )
```

This keeps the dependency arrow pointing one way (`agent.py -> mind`,
never `mind -> agent.py`), so there's no circular import, and every Mind
engine stays independently constructible and testable with zero providers
bound (`MindProviders()` defaults to empty/neutral data).

---

## 5. Homeostasis subsystem detail (Parts 8, 12, 13)

```
HealthMetrics (memory_usage, task_load, errors, queue_length,
               response_latency_ms, model/tool/skill availability)
       │
       │ .score()  — transparent weighted-penalty heuristic, clamped [0,1]
       ▼
HomeostasisEngine.check(metrics) -> HealthReport(metrics, score, band)
       │
       │ band = healthy | degraded | critical
       │ publishes HealthChanged ONLY when the band actually changes
       ▼
DigitalHomeostasisLoop.tick(metrics, progress_made, goals, mission_keywords, recent_failures)
       │
       ▼
HomeostasisTickResult:
  - is_healthy               (band == "healthy")
  - is_overloaded             (band == "critical" or task_load/queue too high)
  - is_making_progress        (caller-reported)
  - goals_match_mission       (best-effort keyword match against mission)
  - anything_failing          (errors, recent_failures, model unavailable)
  - should_notify_owner       (overloaded, critical, or repeated failures)
  - notes                     (human-readable explanations)

DigitalSensorySystem.detect(signal, detail, **payload)
  -> records a SensoryEvent, publishes SensorySignalDetected
  signals: memory_changed, high_cpu_load, low_confidence, knowledge_conflict,
           new_goal, task_delay, module_failure, research_completed,
           tool_failure, permission_denied
```

`tick()` is an explicit, synchronous method a caller invokes — there is no
background thread or timer. Real periodic scheduling is left to
`smartagent.automation` (not wired up yet; tracked in `ROADMAP.md`'s TODO
tracker), which keeps this subsystem deterministic and directly testable.

---

## 6. Knowledge Engine v1 overview (Milestone 7)

```
                    KnowledgeManager (knowledge_manager.py)
                       the sole entry point — Brain never
                       imports sub-engines directly
                              │
    ┌──────────┬─────────────┬┴────────────┬──────────────┬──────────────┐
    ▼          ▼             ▼             ▼              ▼              ▼
┌────────┐ ┌────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│Knowledge│ │Ontology│ │Knowledge │ │  Query   │ │Knowledge │ │Knowledge │
│ Graph   │ │ Engine │ │  Inbox   │ │  Engine  │ │  Search  │ │  Stats   │
│(graph/) │ │(ontol/)│ │ (inbox/) │ │(queries/)│ │(search/) │ │(stats/)  │
│directed │ │hierarch│ │ approval │ │find_*    │ │determin. │ │live +    │
│graph,   │ │category│ │  gate,   │ │12 query  │ │full-text,│ │history   │
│BFS/DFS/ │ │tree,   │ │ persist  │ │types     │ │no embed. │ │snapshots │
│shortest │ │inherit-│ │ queue    │ │          │ │          │ │          │
│path,    │ │ance,   │ │          │ │          │ │          │ │          │
│merge/   │ │ensure_ │ │          │ │          │ │          │ │          │
│split    │ │path()  │ │          │ │          │ │          │ │          │
└────────┘ └────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘
    │                       │
    ▼                       ▼
┌────────────────┐   ┌──────────────────────────────────────────────────┐
│KnowledgeStorage│   │  KnowledgeInbox pipeline (propose → commit):     │
│  (storage/)    │   │                                                  │
│ concepts/      │   │  propose_concept()                               │
│ relationships/ │   │    ↓ ConceptValidator (hard errors + warnings)   │
│ sources/       │   │    ↓ Conflict Detection (contradiction_ids cross- │
│ evidence/      │   │      reference against existing concepts)        │
│ inbox/         │   │    ↓ ConfidenceEngine (initial score)            │
│ (JSON files)   │   │    → InboxItem (pending / conflict / rejected)   │
└────────────────┘   │                                                  │
                     │  approve_concept(item_id)                        │
                     │    ↓ _commit_concept() → storage + graph         │
                     └──────────────────────────────────────────────────┘
```

Knowledge engine sub-models:

```
Concept (concepts/)
  id, title, description, summary, category, tags, aliases, examples,
  difficulty, status, confidence, importance, created_at, updated_at,
  author, owner, source_ids, evidence_ids, relationship_ids,
  dependency_ids, contradiction_ids, verification_status, revision_history

Relationship (relationships/)
  id, from_concept_id, to_concept_id, relation_type (15 types),
  direction, strength, confidence, source, created_at, notes

Source (sources/)
  id, source_type (11 types), author, url, publication, date,
  reliability_score, citation, notes

Evidence (evidence/)
  id, concept_id, description, source_id, evidence_type (5 types),
  strength, confidence, timestamp, verification_status, notes

ConfidenceFactors (computed, not stored)
  evidence_score (40%), source_score (30%), source_count_bonus,
  verification_bonus, age_penalty, contradiction_penalty,
  manual_adjustment → final_score [0.0, 1.0]
```

Brain integration — module handler:

```
BrainRouter.route()
  ...
  → knowledge_handler(message)
      agent.knowledge.search(message, limit=3)
      → if hits: return concept summaries (confidence=0.6)
      → if miss:  return knowledge stats  (success=False)
```

**Brain isolation:** `module_bindings.knowledge_handler` closes over
`agent.knowledge` (a `KnowledgeManager`). The Brain never imports
`KnowledgeGraph`, `KnowledgeStorage`, `KnowledgeInbox`, or any other
sub-engine — all access goes through `KnowledgeManager`.

## 7. What's still design-only

Per milestone specs, these are intentionally **not** implemented:

- Learning Engine, Curiosity Engine, Discovery Engine, Wisdom Engine,
  Cybersecurity Engine
- Voice, Vision, Browser, and Automation integration *into the Mind*
- Ollama/model-provider integration triggered by the Mind or Knowledge Engine
- Internet access, vector databases, embeddings, AI reasoning in Knowledge

See `ROADMAP.md` for what's next.
