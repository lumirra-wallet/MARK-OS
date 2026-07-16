"""Tests for smartagent.performance.complexity — v2.0 Phase 1."""

import pytest
from smartagent.performance.complexity import TaskComplexity, classify_complexity


class TestTaskComplexity:
    def test_enum_values(self):
        assert TaskComplexity.TRIVIAL.value == "trivial"
        assert TaskComplexity.SMALL.value == "small"
        assert TaskComplexity.MEDIUM.value == "medium"
        assert TaskComplexity.LARGE.value == "large"
        assert TaskComplexity.ENTERPRISE.value == "enterprise"

    def test_skip_research_trivial(self):
        assert TaskComplexity.TRIVIAL.skip_research is True

    def test_skip_research_small(self):
        assert TaskComplexity.SMALL.skip_research is True

    def test_skip_research_medium(self):
        assert TaskComplexity.MEDIUM.skip_research is False

    def test_skip_review_trivial(self):
        assert TaskComplexity.TRIVIAL.skip_review is True

    def test_skip_documentation_medium(self):
        assert TaskComplexity.MEDIUM.skip_documentation is True

    def test_skip_documentation_large(self):
        assert TaskComplexity.LARGE.skip_documentation is False

    def test_max_prior_chars_trivial(self):
        assert TaskComplexity.TRIVIAL.max_prior_chars == 200

    def test_max_prior_chars_large(self):
        assert TaskComplexity.LARGE.max_prior_chars == 800


class TestClassifyComplexity:
    # --- Trivial ---
    def test_hello_world(self):
        assert classify_complexity("Create hello.py") == TaskComplexity.TRIVIAL

    def test_hello_world_variant(self):
        assert classify_complexity("Write a hello world script") == TaskComplexity.TRIVIAL

    def test_calculator(self):
        assert classify_complexity("Build a calculator CLI") == TaskComplexity.TRIVIAL

    def test_calculator_simple(self):
        assert classify_complexity("Write a calculator") == TaskComplexity.TRIVIAL

    def test_calculator_program(self):
        assert classify_complexity("Write a simple calculator program") == TaskComplexity.TRIVIAL

    def test_fibonacci(self):
        assert classify_complexity("Write a fibonacci function") == TaskComplexity.TRIVIAL

    def test_factorial(self):
        assert classify_complexity("Write a factorial function") == TaskComplexity.TRIVIAL

    def test_reverse_string(self):
        assert classify_complexity("Write a function to reverse a string") == TaskComplexity.TRIVIAL

    def test_add_function(self):
        assert classify_complexity("Add a function to calculate area") == TaskComplexity.TRIVIAL

    def test_requirements_txt(self):
        assert classify_complexity("Create a requirements.txt") == TaskComplexity.TRIVIAL

    def test_readme(self):
        assert classify_complexity("Add a README") == TaskComplexity.TRIVIAL

    def test_bug_fix_single(self):
        assert classify_complexity("Fix a single bug") == TaskComplexity.TRIVIAL

    # --- Enterprise ---
    def test_crm(self):
        assert classify_complexity("Build a CRM platform") == TaskComplexity.ENTERPRISE

    def test_erp(self):
        assert classify_complexity("Create an ERP system for manufacturing") == TaskComplexity.ENTERPRISE

    def test_enterprise_keyword(self):
        assert classify_complexity("Build an enterprise data platform") == TaskComplexity.ENTERPRISE

    def test_multi_tenant(self):
        assert classify_complexity("Build a multi-tenant SaaS") == TaskComplexity.ENTERPRISE

    # --- Large ---
    def test_saas(self):
        assert classify_complexity("Build a SaaS billing platform") == TaskComplexity.LARGE

    def test_full_stack(self):
        assert classify_complexity("Build a full-stack web application") == TaskComplexity.LARGE

    def test_payment_system(self):
        assert classify_complexity("Build a payment processing system") == TaskComplexity.LARGE

    # --- Medium ---
    def test_todo_app(self):
        assert classify_complexity("Build a todo app with user accounts") == TaskComplexity.MEDIUM

    def test_blog(self):
        assert classify_complexity("Create a blog with posts and comments") == TaskComplexity.MEDIUM

    def test_chat_app(self):
        assert classify_complexity("Build a chat app") == TaskComplexity.MEDIUM

    # --- Small ---
    def test_rest_api_short(self):
        result = classify_complexity("REST API")
        assert result in (TaskComplexity.SMALL, TaskComplexity.TRIVIAL)

    def test_short_goal(self):
        result = classify_complexity("Build a CLI tool")
        assert result in (TaskComplexity.SMALL, TaskComplexity.TRIVIAL)

    # --- Edge cases ---
    def test_empty_string(self):
        result = classify_complexity("")
        assert isinstance(result, TaskComplexity)

    def test_none_like_whitespace(self):
        result = classify_complexity("   ")
        assert isinstance(result, TaskComplexity)

    def test_returns_enum(self):
        result = classify_complexity("Build something")
        assert isinstance(result, TaskComplexity)
