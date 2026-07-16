"""Tests for smartagent.performance.prompt_auditor — v2.0 Phase 2."""

import pytest
from smartagent.performance.prompt_auditor import PromptAudit, measure_prompt


class TestPromptAudit:
    def _audit(self, **kwargs):
        return PromptAudit(**kwargs)

    def test_total_chars(self):
        a = self._audit(system_chars=100, goal_chars=50, prior_chars=0,
                        task_chars=0, knowledge_chars=0, memory_chars=0)
        assert a.total_chars == 150

    def test_total_tokens(self):
        a = self._audit(system_chars=400, goal_chars=0, prior_chars=0,
                        task_chars=0, knowledge_chars=0, memory_chars=0)
        assert a.total_tokens == 100

    def test_system_tokens(self):
        a = self._audit(system_chars=800, goal_chars=0, prior_chars=0,
                        task_chars=0, knowledge_chars=0, memory_chars=0)
        assert a.system_tokens == 200

    def test_prior_tokens(self):
        a = self._audit(system_chars=0, goal_chars=0, prior_chars=400,
                        task_chars=0, knowledge_chars=0, memory_chars=0)
        assert a.prior_tokens == 100

    def test_knowledge_tokens(self):
        a = self._audit(system_chars=0, goal_chars=0, prior_chars=0,
                        task_chars=0, knowledge_chars=400, memory_chars=0)
        assert a.knowledge_tokens == 100

    def test_memory_tokens(self):
        a = self._audit(system_chars=0, goal_chars=0, prior_chars=0,
                        task_chars=0, knowledge_chars=0, memory_chars=400)
        assert a.memory_tokens == 100

    def test_as_display_lines_list(self):
        a = self._audit(system_chars=200, goal_chars=100, prior_chars=0,
                        task_chars=0, knowledge_chars=0, memory_chars=0)
        lines = a.as_display_lines()
        assert isinstance(lines, list)
        assert len(lines) >= 3

    def test_as_display_lines_all_zero(self):
        a = self._audit(system_chars=0, goal_chars=0, prior_chars=0,
                        task_chars=0, knowledge_chars=0, memory_chars=0)
        lines = a.as_display_lines()
        assert "no prompt data" in "\n".join(lines).lower()

    def test_large_section_flagged(self):
        # system > 400 tokens (1600 chars) should be flagged
        a = self._audit(system_chars=2000, goal_chars=0, prior_chars=0,
                        task_chars=0, knowledge_chars=0, memory_chars=0)
        flagged = a.flagged_sections()
        assert "System Prompt" in flagged

    def test_small_section_not_flagged(self):
        a = self._audit(system_chars=100, goal_chars=0, prior_chars=0,
                        task_chars=0, knowledge_chars=0, memory_chars=0)
        flagged = a.flagged_sections()
        assert "System Prompt" not in flagged

    def test_flagged_prior_results(self):
        a = self._audit(system_chars=0, goal_chars=0, prior_chars=2000,
                        task_chars=0, knowledge_chars=0, memory_chars=0)
        assert "Prior Results" in a.flagged_sections()

    def test_total_in_display_lines(self):
        a = self._audit(system_chars=400, goal_chars=200, prior_chars=0,
                        task_chars=0, knowledge_chars=0, memory_chars=0)
        text = "\n".join(a.as_display_lines())
        assert "TOTAL" in text


class TestMeasurePrompt:
    def test_returns_audit(self):
        a = measure_prompt(system="hello" * 20)
        assert isinstance(a, PromptAudit)

    def test_empty_call(self):
        a = measure_prompt()
        assert a.total_chars == 0
        assert a.total_tokens == 0

    def test_system_measured(self):
        text = "x" * 100
        a = measure_prompt(system=text)
        assert a.system_chars == 100

    def test_prior_measured(self):
        a = measure_prompt(prior_results="y" * 200)
        assert a.prior_chars == 200

    def test_goal_measured(self):
        a = measure_prompt(goal="Build a thing")
        assert a.goal_chars == len("Build a thing")

    def test_knowledge_measured(self):
        a = measure_prompt(knowledge="k" * 50)
        assert a.knowledge_chars == 50

    def test_memory_measured(self):
        a = measure_prompt(memory="m" * 75)
        assert a.memory_chars == 75

    def test_all_sections(self):
        a = measure_prompt(
            system="s" * 400,
            prior_results="p" * 500,
            goal="g" * 100,
            task_desc="t" * 80,
            knowledge="k" * 120,
            memory="m" * 60,
        )
        expected = 400 + 500 + 100 + 80 + 120 + 60
        assert a.total_chars == expected
