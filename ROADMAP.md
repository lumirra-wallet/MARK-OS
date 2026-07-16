# MARK Roadmap

## Completed

### Phase 1 — Foundation (Milestones 1–10)
- ✅ M1  Brain & EventBus
- ✅ M2  Memory Manager (persistent vault)
- ✅ M3  Knowledge Manager (graph, search, ontology)
- ✅ M4  Tool Engine (permission model, builtin tools)
- ✅ M5  Model Manager (ModelRegistry, BaseModel)
- ✅ M6  Mind OS (MindProviders, homeostasis, IdentityEngine)
- ✅ M7  Knowledge Graph
- ✅ M8  Console OS (command framework, REPL)
- ✅ M9  Ollama Integration (OllamaProvider, streaming, health)
- ✅ M10 Streaming Upgrade (generate_stream, spinner, stats)

### Phase 2 — Intelligence (Milestones 11–17)
- ✅ M11 Executive Framework (planner, tasks, workers, scheduler)
- ✅ M14 Learning & Reflection (ReflectionEngine, LearningStore)
- ✅ M15 Workspace Manager (project isolation, scoped services)
- ✅ M17 Multi-Agent Collaboration (CEOAgent, TeamPlanner, TeamRunner)

### Phase 3 — Execution OS (Milestones 18–25)
- ✅ M18 Workspace Intelligence (ProjectScanner, file graph, import graph)
- ✅ M19 File Editing Engine (FileEditor, FileEditMixin, workers write files)
- ✅ M20 Self Debugging (DebugLoop, TracebackParser, run→parse→fix→retry)
- ✅ M21 Git Engine (GitClient, PRBuilder, git commands in console)
- ✅ M22 Project Memory (ProjectProfile, per-project tech-stack)
- ✅ M23 Long Running Execution (LongRunningEngine, CompletionReport)
- ✅ M24 Autonomous Development Loop (DevLoop, plan→test→debug→reflect)
- ✅ M25 Full Software Engineer (SoftwareEngineer, RequirementAnalyzer, ClarificationEngine)

### v2.0 — Production Grade
- ✅ Phase 1  Audit & cleanup (no duplication, no parallel implementations)
- ✅ Phase 2  End-to-end execution wiring (workspace scan integrated into pipeline)
- ✅ Phase 3  Real file operations (FileEditor v2: preview, diff, snapshot, restore, move, rename, audit log JSON)
- ✅ Phase 4  Production debug loop (subprocess, traceback, fix, patch, retry)
- ✅ Phase 5  Code quality (QualityRunner: pytest, ruff, black, mypy — graceful if not installed)
- ✅ Phase 6  Execution dashboard (ExecutionDashboard — live text UI, works in CI)
- ✅ Phase 7  Performance (DevLoop integrates QualityRunner, quality only after tests pass)
- ✅ Phase 8  Reliability (global exception handler in REPL — no uncaught exception terminates MARK)
- ✅ Phase 9  Validation (validate command — 5 standard engineering scenarios)

---

## Next

### Near-term
- [ ] Real AI code generation (connect CodingWorker to Ollama for actual code output)
- [ ] Streaming output during long engineer runs (live token display)
- [ ] Web UI / REST API for remote engineer invocations
- [ ] Persistent conversation context across REPL sessions
- [ ] GitHub integration (open real PRs via GitHub API)

### Medium-term
- [ ] Multi-project workspace (MARK aware of several projects simultaneously)
- [ ] Plugin system (custom workers, tools, and commands via drop-in packages)
- [ ] Agent marketplace (share and reuse worker configurations)
- [ ] Evaluation harness (benchmark MARK against standard coding tasks)
- [ ] Docker sandbox for safe code execution in isolated containers

### Long-term
- [ ] MARK as a GitHub App (receive issues → fix → open PR)
- [ ] Continuous monitoring mode (watch test failures, auto-fix, notify)
- [ ] Multi-model routing (choose model by task type: coding, testing, docs)
- [ ] Self-improving MARK (uses DevLoop on its own codebase)
