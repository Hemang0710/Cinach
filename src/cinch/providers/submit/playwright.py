"""Playwright-based assisted submission (Phase 6, optional; needs the ``submit`` extra).

⚠️  Auto-submitting to job sites may violate their Terms of Service. This adapter runs
only when ``SUBMISSION_ENABLED=true`` and only for applications the user has already
Approved. It **never** bypasses a login or CAPTCHA — those are handed back to the user
(``NEEDS_HUMAN``) — and it submits only a form it can confidently recognize. The resume
PDF is produced by Chromium's own ``page.pdf()``, so no extra dependency is required.

``playwright`` is imported lazily inside methods so importing this module (and the whole
codebase) never requires the optional extra. This adapter drives a real browser and is
therefore exercised only in integration runs, not unit tests.
"""

from __future__ import annotations

import contextlib
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from cinch.core.config import Settings
from cinch.core.logging import get_logger
from cinch.providers.submit.base import Applicant, SubmissionOutcome, SubmissionResult

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page

logger = get_logger(__name__)

# If any of these appear on the page, we must NOT proceed automatically — hand back.
_CAPTCHA_MARKERS = ("captcha", "recaptcha", "hcaptcha", "i'm not a robot", "are you human")
_LOGIN_MARKERS = ("sign in", "log in", "login", "create an account", "enter your password")

# Best-effort field selectors (case-insensitive attribute match). Order = preference.
_EMAIL_SELECTORS = ('input[type="email"]', 'input[name*="email" i]', 'input[id*="email" i]')
_NAME_SELECTORS = ('input[name*="name" i]', 'input[id*="name" i]', 'input[autocomplete="name"]')
_PHONE_SELECTORS = ('input[type="tel"]', 'input[name*="phone" i]', 'input[id*="phone" i]')
_SUBMIT_SELECTORS = (
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("Submit application")',
    'button:has-text("Submit")',
    'button:has-text("Apply")',
)


class PlaywrightSubmitter:
    """Assisted submitter that drives a headless Chromium, safely by default."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def submit(
        self, *, apply_url: str, applicant: Applicant, resume_html: str
    ) -> SubmissionResult:
        """Attempt to submit one application; hand back to the user when unsafe."""
        from playwright.async_api import Error as PlaywrightError
        from playwright.async_api import TimeoutError as PlaywrightTimeout
        from playwright.async_api import async_playwright

        timeout_ms = self._settings.submission_timeout_seconds * 1000
        workdir = Path(tempfile.mkdtemp(prefix="cinch-submit-"))
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=self._settings.submission_headless)
                try:
                    context = await browser.new_context()
                    context.set_default_timeout(timeout_ms)
                    pdf_path = await self._render_pdf(context, resume_html, workdir)

                    page = await context.new_page()
                    await page.goto(apply_url, wait_until="domcontentloaded", timeout=timeout_ms)
                    return await self._attempt(page, applicant, pdf_path)
                finally:
                    await browser.close()
        except PlaywrightTimeout:
            logger.warning("submission_timeout")  # deliberately no URL/PII in the log
            return SubmissionResult(SubmissionOutcome.FAILED, "timed out loading the page")
        except PlaywrightError as exc:
            logger.warning("submission_error", error_type=type(exc).__name__)
            return SubmissionResult(SubmissionOutcome.FAILED, "browser automation error")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    async def _attempt(self, page: Page, applicant: Applicant, pdf_path: Path) -> SubmissionResult:
        """Safety-gate, fill, and submit — or return a ``NEEDS_HUMAN`` handoff."""
        body_text = (await page.inner_text("body")).lower()
        if any(marker in body_text for marker in _CAPTCHA_MARKERS):
            return SubmissionResult(SubmissionOutcome.NEEDS_HUMAN, "CAPTCHA present")
        if any(marker in body_text for marker in _LOGIN_MARKERS):
            return SubmissionResult(SubmissionOutcome.NEEDS_HUMAN, "sign-in required")

        if not await self._fill_form(page, applicant, pdf_path):
            return SubmissionResult(
                SubmissionOutcome.NEEDS_HUMAN, "no recognizable application form"
            )

        if not await self._click_submit(page):
            return SubmissionResult(SubmissionOutcome.NEEDS_HUMAN, "no submit control found")

        return SubmissionResult(SubmissionOutcome.SUBMITTED, "submitted")

    async def _render_pdf(self, context: BrowserContext, resume_html: str, workdir: Path) -> Path:
        """Render the resume HTML to a PDF using Chromium itself (no extra dependency)."""
        page = await context.new_page()
        try:
            await page.set_content(resume_html, wait_until="load")
            pdf_path = workdir / "resume.pdf"
            await page.pdf(path=str(pdf_path), format="A4", print_background=True)
            return pdf_path
        finally:
            await page.close()

    async def _fill_form(self, page: Page, applicant: Applicant, pdf_path: Path) -> bool:
        """Fill known fields + attach the resume. Returns ``False`` if unrecognizable.

        A form counts as recognizable only when it has a file upload (for the resume)
        and an email field — otherwise we refuse to submit and hand back to the user.
        """
        file_input = await page.query_selector('input[type="file"]')
        if file_input is None:
            return False
        if not await self._fill_first(page, _EMAIL_SELECTORS, applicant.email):
            return False
        await file_input.set_input_files(str(pdf_path))
        await self._fill_first(page, _NAME_SELECTORS, applicant.name)
        if applicant.phone:
            await self._fill_first(page, _PHONE_SELECTORS, applicant.phone)
        return True

    async def _fill_first(self, page: Page, selectors: tuple[str, ...], value: str) -> bool:
        """Fill the first matching selector with ``value``; return whether one matched."""
        for selector in selectors:
            element = await page.query_selector(selector)
            if element is not None:
                await element.fill(value)
                return True
        return False

    async def _click_submit(self, page: Page) -> bool:
        """Click the first recognizable submit control; return whether one was found."""
        for selector in _SUBMIT_SELECTORS:
            element = await page.query_selector(selector)
            if element is not None:
                await element.click()
                # Settling is best-effort — the submit was already clicked.
                with contextlib.suppress(Exception):
                    await page.wait_for_load_state("networkidle")
                return True
        return False
