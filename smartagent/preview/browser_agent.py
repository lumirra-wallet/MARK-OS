"""
BrowserAgent — Playwright-based self-inspection of MARK's own live previews.

MARK can navigate, click, fill forms, capture screenshots, read console
errors, and run basic accessibility checks against any detected preview —
like a QA engineer reviewing its own team's work, rather than the user
having to open a separate browser to check.

Design decisions
-----------------
- Uses the *system* Chromium already installed on the host (found via
  ``shutil.which``), not Playwright's own bundled-browser download — this
  project runs local-first (Ollama, faster-whisper, Piper all work the same
  way) and a multi-hundred-MB browser download isn't warranted when a real
  browser is already on the machine.
- Best-effort subsystem, matching the rest of the codebase: if Playwright
  isn't installed or no Chromium executable can be found, ``available`` is
  False and callers degrade gracefully (no exception, no crash) — the same
  pattern as ``OllamaProvider``/``GitClient``/etc.
- The accessibility check is a small, dependency-free floor (missing `alt`
  text, unlabeled form fields) — not a full axe-core audit. Good enough to
  catch obvious regressions without adding a JS dependency to inject.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

DEFAULT_SCREENSHOT_DIR = Path(".mark_storage") / "screenshots"

#: Mirrors PreviewWorkspace.tsx's DEVICES map so responsiveness screenshots
#: line up with what the user can already toggle to in the Live Preview panel.
DEVICE_VIEWPORTS: dict[str, dict[str, int]] = {
    "desktop":   {"width": 1280, "height": 800},
    "tablet":    {"width": 768,  "height": 1024},
    "mobile":    {"width": 390,  "height": 844},
    "landscape": {"width": 844,  "height": 390},
}


def _find_chromium_executable() -> str | None:
    """Prefer the system-installed Chromium over downloading Playwright's own."""
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _safe_name(url: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in url)[:80]


@dataclass
class InspectionFinding:
    kind:     str  # "console_error" | "accessibility"
    message:  str
    severity: str = "info"  # "info" | "warning" | "error"


@dataclass
class InspectionReport:
    url:                     str
    screenshot_path:         str | None = None
    console_errors:          list[str] = field(default_factory=list)
    findings:                list[InspectionFinding] = field(default_factory=list)
    responsive_screenshots:  dict[str, str] = field(default_factory=dict)  # device -> path
    success:                 bool = True
    error:                   str | None = None

    def summary_text(self) -> str:
        """Plain-English one-paragraph summary — fed into MARK's executive
        synthesis prompt rather than dumping raw findings at the user."""
        if not self.success:
            return f"Could not inspect {self.url}: {self.error}"
        parts = [f"Inspected {self.url}."]
        errors = [f for f in self.findings if f.kind == "console_error"]
        a11y   = [f for f in self.findings if f.kind == "accessibility"]
        if errors:
            parts.append(f"Found {len(errors)} console error(s).")
        else:
            parts.append("No console errors.")
        if a11y:
            parts.append(f"{len(a11y)} accessibility issue(s): " + "; ".join(f.message for f in a11y) + ".")
        return " ".join(parts)


class BrowserAgent:
    """Best-effort Playwright wrapper for self-inspecting live previews."""

    def __init__(self, screenshot_dir: str | Path = DEFAULT_SCREENSHOT_DIR) -> None:
        self._screenshot_dir = Path(screenshot_dir)
        self._executable = _find_chromium_executable()

    @property
    def available(self) -> bool:
        try:
            import playwright.sync_api  # noqa: F401
        except ImportError:
            return False
        return self._executable is not None

    def inspect(
        self,
        url: str,
        actions: list[dict[str, Any]] | None = None,
        check_accessibility: bool = True,
        check_responsiveness: bool = False,
    ) -> InspectionReport:
        """
        Navigate to *url*, optionally perform *actions*, capture a screenshot,
        collect console errors, and run the accessibility floor check.

        ``actions`` is a list of ``{"type": "click"|"fill"|"navigate",
        "selector"?: str, "value"?: str}`` — applied in order before the
        screenshot is taken.
        """
        report = InspectionReport(url=url)
        if not self.available:
            report.success = False
            report.error = "Playwright or a Chromium executable is not available."
            return report

        from playwright.sync_api import sync_playwright

        self._screenshot_dir.mkdir(parents=True, exist_ok=True)
        console_errors: list[str] = []

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=self._executable, headless=True)
                try:
                    page = browser.new_page(viewport=DEVICE_VIEWPORTS["desktop"])
                    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
                    page.on("pageerror", lambda exc: console_errors.append(str(exc)))

                    page.goto(url, timeout=15_000, wait_until="load")

                    for action in actions or []:
                        self._perform_action(page, action)

                    name = _safe_name(url)
                    screenshot_path = self._screenshot_dir / f"{name}.png"
                    page.screenshot(path=str(screenshot_path))
                    report.screenshot_path = str(screenshot_path)

                    if check_accessibility:
                        report.findings.extend(self._accessibility_check(page))

                    if check_responsiveness:
                        for device, viewport in DEVICE_VIEWPORTS.items():
                            if device == "desktop":
                                continue
                            page.set_viewport_size(viewport)
                            device_path = self._screenshot_dir / f"{name}-{device}.png"
                            page.screenshot(path=str(device_path))
                            report.responsive_screenshots[device] = str(device_path)
                finally:
                    browser.close()
        except Exception as exc:
            logger.warning("BrowserAgent.inspect failed for %r: %s", url, exc)
            report.success = False
            report.error = str(exc)

        report.console_errors = console_errors
        for err in console_errors:
            report.findings.append(InspectionFinding(kind="console_error", message=err, severity="error"))

        return report

    @staticmethod
    def _perform_action(page: Any, action: dict[str, Any]) -> None:
        kind = action.get("type")
        if kind == "click":
            page.click(action.get("selector", ""), timeout=5_000)
        elif kind == "fill":
            page.fill(action.get("selector", ""), action.get("value", ""), timeout=5_000)
        elif kind == "navigate":
            page.goto(action.get("value", ""), timeout=15_000)

    @staticmethod
    def _accessibility_check(page: Any) -> list[InspectionFinding]:
        """Dependency-free accessibility floor: images without alt text and
        form fields without an associated label. Not a full axe-core audit —
        a lightweight, always-available baseline."""
        findings: list[InspectionFinding] = []
        try:
            missing_alt = page.eval_on_selector_all(
                "img", "els => els.filter(e => !e.alt).length",
            )
            if missing_alt:
                findings.append(InspectionFinding(
                    kind="accessibility",
                    message=f"{missing_alt} image(s) missing alt text",
                    severity="warning",
                ))
            unlabeled = page.eval_on_selector_all(
                "input, textarea, select",
                "els => els.filter(e => !e.labels?.length && !e.getAttribute('aria-label')).length",
            )
            if unlabeled:
                findings.append(InspectionFinding(
                    kind="accessibility",
                    message=f"{unlabeled} form field(s) without a label",
                    severity="warning",
                ))
        except Exception as exc:
            logger.debug("BrowserAgent accessibility check skipped: %s", exc)
        return findings


browser_agent = BrowserAgent()
