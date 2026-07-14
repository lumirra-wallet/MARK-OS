"""
Brain subpackage — Brain v2 (Decision Engine).

Contains the central "brain" of SmartAgent: the orchestration logic that
receives a user request, classifies it, decides which module should
handle it, and produces a response. Everything else (memory, voice,
vision, automation, ui) feeds into or is driven by this layer.

Brain v2 pipeline (see each module's docstring for design rationale):

    SmartAgent.handle_message
        -> BrainRouter.route            (router.py)
             -> IntentAnalyzer.analyze  (intent_analyzer.py)
             -> DecisionEngine.decide   (decision_engine.py)
             -> ModuleRegistry.get      (module_registry.py)
             -> <module handler>()      (module_bindings.py)
                  -> ActionResult       (action_result.py)
        -> EventBus.publish             (events.py)

(Formerly named `core` — renamed to `brain` as part of the move to a
scalable, production-oriented package layout.)

Note: this file deliberately imports nothing. Importing `agent.py` here
(to re-export `SmartAgent` for convenience) would create a circular
import, since `agent.py` and `module_bindings.py` both depend on other
`brain` submodules (e.g. `brain.events`), and importing *any* submodule of
`brain` first runs this `__init__.py`.
"""
