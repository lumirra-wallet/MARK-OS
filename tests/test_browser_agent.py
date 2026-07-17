"""
Tests for smartagent.preview.browser_agent — Playwright-based self-inspection.

Playwright itself is never actually launched here — sync_playwright and the
browser/page chain are mocked, matching this project's "no network calls in
tests" convention (see CONTRIBUTING.md).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from smartagent.preview.browser_agent import (
    BrowserAgent,
    InspectionFinding,
    InspectionReport,
    DEVICE_VIEWPORTS,
    _safe_name,
)


# ── available ──────────────────────────────────────────────────────────────────

class TestAvailable:
    def test_unavailable_when_no_chromium_executable(self):
        with patch("shutil.which", return_value=None):
            agent = BrowserAgent(screenshot_dir="/tmp/does-not-matter")
        assert agent.available is False

    def test_available_when_chromium_and_playwright_present(self, tmp_path):
        with patch("shutil.which", return_value="/usr/bin/chromium"):
            agent = BrowserAgent(screenshot_dir=tmp_path)
        assert agent.available is True


# ── inspect() — graceful degradation ────────────────────────────────────────────

class TestInspectUnavailable:
    def test_returns_failed_report_when_unavailable(self, tmp_path):
        with patch("shutil.which", return_value=None):
            agent = BrowserAgent(screenshot_dir=tmp_path)
        report = agent.inspect("http://localhost:3000")
        assert report.success is False
        assert "not available" in report.error
        assert report.screenshot_path is None


# ── inspect() — happy path (Playwright fully mocked) ───────────────────────────

class TestInspectHappyPath:
    def _make_agent(self, tmp_path) -> BrowserAgent:
        with patch("shutil.which", return_value="/usr/bin/chromium"):
            return BrowserAgent(screenshot_dir=tmp_path)

    def _mock_playwright(self, page: MagicMock):
        browser = MagicMock()
        browser.new_page.return_value = page
        chromium = MagicMock()
        chromium.launch.return_value = browser
        pw_ctx = MagicMock()
        pw_ctx.chromium = chromium
        pw_cm = MagicMock()
        pw_cm.__enter__.return_value = pw_ctx
        pw_cm.__exit__.return_value = False
        return pw_cm, browser

    def test_navigates_and_screenshots(self, tmp_path):
        agent = self._make_agent(tmp_path)
        page = MagicMock()
        page.eval_on_selector_all.return_value = 0
        pw_cm, browser = self._mock_playwright(page)

        with patch("playwright.sync_api.sync_playwright", return_value=pw_cm):
            report = agent.inspect("http://localhost:3000")

        page.goto.assert_called_once_with("http://localhost:3000", timeout=15_000, wait_until="load")
        page.screenshot.assert_called_once()
        browser.close.assert_called_once()
        assert report.success is True
        assert report.screenshot_path is not None

    def test_console_errors_collected(self, tmp_path):
        agent = self._make_agent(tmp_path)
        page = MagicMock()
        page.eval_on_selector_all.return_value = 0
        captured_handlers = {}

        def _on(event_name, handler):
            captured_handlers[event_name] = handler
        page.on.side_effect = _on
        pw_cm, _ = self._mock_playwright(page)

        with patch("playwright.sync_api.sync_playwright", return_value=pw_cm):
            def _goto(*a, **kw):
                # Simulate a console error firing during page load.
                msg = MagicMock(type="error", text="Uncaught TypeError: x is not a function")
                captured_handlers["console"](msg)
            page.goto.side_effect = _goto
            report = agent.inspect("http://localhost:3000")

        assert "Uncaught TypeError: x is not a function" in report.console_errors
        assert any(f.kind == "console_error" for f in report.findings)

    def test_accessibility_findings_included(self, tmp_path):
        agent = self._make_agent(tmp_path)
        page = MagicMock()
        page.eval_on_selector_all.side_effect = [2, 1]  # 2 missing alt, 1 unlabeled field
        pw_cm, _ = self._mock_playwright(page)

        with patch("playwright.sync_api.sync_playwright", return_value=pw_cm):
            report = agent.inspect("http://localhost:3000", check_accessibility=True)

        messages = [f.message for f in report.findings if f.kind == "accessibility"]
        assert any("2 image" in m for m in messages)
        assert any("1 form field" in m for m in messages)

    def test_responsiveness_screenshots_per_device(self, tmp_path):
        agent = self._make_agent(tmp_path)
        page = MagicMock()
        page.eval_on_selector_all.return_value = 0
        pw_cm, _ = self._mock_playwright(page)

        with patch("playwright.sync_api.sync_playwright", return_value=pw_cm):
            report = agent.inspect("http://localhost:3000", check_responsiveness=True)

        expected_devices = set(DEVICE_VIEWPORTS) - {"desktop"}
        assert set(report.responsive_screenshots) == expected_devices
        assert page.set_viewport_size.call_count == len(expected_devices)

    def test_actions_performed_before_screenshot(self, tmp_path):
        agent = self._make_agent(tmp_path)
        page = MagicMock()
        page.eval_on_selector_all.return_value = 0
        pw_cm, _ = self._mock_playwright(page)

        actions = [
            {"type": "click", "selector": "#submit"},
            {"type": "fill", "selector": "#email", "value": "a@b.com"},
        ]
        with patch("playwright.sync_api.sync_playwright", return_value=pw_cm):
            agent.inspect("http://localhost:3000", actions=actions)

        page.click.assert_called_once_with("#submit", timeout=5_000)
        page.fill.assert_called_once_with("#email", "a@b.com", timeout=5_000)

    def test_exception_produces_failed_report(self, tmp_path):
        agent = self._make_agent(tmp_path)
        page = MagicMock()
        page.goto.side_effect = RuntimeError("net::ERR_CONNECTION_REFUSED")
        pw_cm, browser = self._mock_playwright(page)

        with patch("playwright.sync_api.sync_playwright", return_value=pw_cm):
            report = agent.inspect("http://localhost:9999")

        assert report.success is False
        assert "ERR_CONNECTION_REFUSED" in report.error
        browser.close.assert_called_once()  # still cleaned up


# ── InspectionReport.summary_text ───────────────────────────────────────────────

class TestSummaryText:
    def test_failed_report(self):
        report = InspectionReport(url="http://x", success=False, error="timeout")
        assert "Could not inspect" in report.summary_text()
        assert "timeout" in report.summary_text()

    def test_clean_report(self):
        report = InspectionReport(url="http://x", success=True)
        text = report.summary_text()
        assert "No console errors" in text

    def test_report_with_errors_and_a11y(self):
        report = InspectionReport(
            url="http://x", success=True,
            findings=[
                InspectionFinding(kind="console_error", message="boom", severity="error"),
                InspectionFinding(kind="accessibility", message="1 image missing alt text", severity="warning"),
            ],
        )
        text = report.summary_text()
        assert "1 console error" in text
        assert "1 image missing alt text" in text


# ── _safe_name ───────────────────────────────────────────────────────────────────

class TestSafeName:
    def test_strips_non_alnum(self):
        assert _safe_name("http://localhost:3000/foo") == "http___localhost_3000_foo"

    def test_truncates_long_urls(self):
        assert len(_safe_name("http://" + "a" * 200)) == 80
