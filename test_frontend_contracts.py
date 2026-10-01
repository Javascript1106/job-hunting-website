"""Regression contracts for shared PathForge front-end behavior.

These tests intentionally inspect static files without requiring a browser or
running backend, making architectural regressions quick to catch in CI.
"""

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parent
ASSET_VERSION = "20261001-v101"


class MarkupInspector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.h1_count = 0
        self.local_references = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.append(attributes["id"])
        if tag == "h1":
            self.h1_count += 1
        for attribute in ("href", "src"):
            value = attributes.get(attribute, "").strip()
            if value:
                self.local_references.append(value)


class FrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = (PROJECT_ROOT / "script.js").read_text(encoding="utf-8")
        cls.core = (PROJECT_ROOT / "pathforge-core.js").read_text(encoding="utf-8")
        cls.styles = (PROJECT_ROOT / "style.css").read_text(encoding="utf-8")
        cls.jobs = (PROJECT_ROOT / "jobs.html").read_text(encoding="utf-8")
        cls.worker = (PROJECT_ROOT / "service-worker.js").read_text(encoding="utf-8")

    def test_every_page_has_one_primary_heading_and_unique_ids(self):
        for page in PROJECT_ROOT.glob("*.html"):
            inspector = MarkupInspector()
            inspector.feed(page.read_text(encoding="utf-8"))
            with self.subTest(page=page.name):
                self.assertEqual(inspector.h1_count, 1)
                self.assertEqual(len(inspector.ids), len(set(inspector.ids)))

    def test_local_page_links_and_assets_exist(self):
        for page in PROJECT_ROOT.glob("*.html"):
            inspector = MarkupInspector()
            inspector.feed(page.read_text(encoding="utf-8"))
            for reference in inspector.local_references:
                parsed = urlsplit(reference)
                if parsed.scheme or reference.startswith(("//", "#", "/")):
                    continue
                target = PROJECT_ROOT / parsed.path
                with self.subTest(page=page.name, reference=reference):
                    self.assertTrue(target.is_file(), f"Missing local target: {reference}")

    def test_asset_versions_are_consistent(self):
        version_pattern = re.compile(r"(?:style\.css|script\.js)\?v=([^\"']+)")
        versions = set()
        for page in PROJECT_ROOT.glob("*.html"):
            versions.update(version_pattern.findall(page.read_text(encoding="utf-8")))
        self.assertEqual(versions, {ASSET_VERSION})
        self.assertIn(f'pathforge-shell-{ASSET_VERSION}', self.worker)
        self.assertIn(f'const ASSET_VERSION = "{ASSET_VERSION}"', self.worker)
        for page in PROJECT_ROOT.glob("*.html"):
            markup = page.read_text(encoding="utf-8")
            if 'src="script.js' not in markup:
                continue
            with self.subTest(core_order=page.name):
                self.assertIn(f'pathforge-core.js?v={ASSET_VERSION}', markup)
                self.assertLess(
                    markup.index('src="pathforge-core.js'),
                    markup.index('src="script.js'),
                )

    def test_api_calls_use_the_central_origin_helper(self):
        self.assertIn("function apiUrl(path)", self.core)
        self.assertEqual(self.core.count("http://127.0.0.1:8000"), 1)
        self.assertIn('["localhost", "127.0.0.1"]', self.core)
        self.assertIn('global.location.port !== "8000"', self.core)
        self.assertIn("window.PathForgeCore", self.script)
        self.assertNotRegex(
            self.script + self.core,
            r"fetch\(\s*[`\"]http://127\.0\.0\.1:8000",
        )

    def test_inline_javascript_handlers_are_not_used(self):
        inline_handler = re.compile(r"\s(?:on[a-z]+)\s*=", re.IGNORECASE)
        inline_script = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>", re.IGNORECASE)
        for page in PROJECT_ROOT.glob("*.html"):
            markup = page.read_text(encoding="utf-8")
            with self.subTest(page=page.name):
                self.assertNotRegex(markup, inline_handler)
                self.assertNotRegex(markup, inline_script)
        self.assertNotRegex(self.script, inline_handler)
        self.assertIn('data-action="save-job"', self.script)
        self.assertIn("handleDelegatedActionClick", self.script)

    def test_resource_center_is_public_without_progress_tracking(self):
        protected_match = re.search(
            r"const protectedPages = \[(.*?)\];",
            self.script,
            re.DOTALL,
        )
        self.assertIsNotNone(protected_match)
        self.assertNotIn("learning-center.html", protected_match.group(1))
        self.assertNotRegex(self.script, r"(?m)^setupLearningControls\(\);$")
        self.assertNotRegex(self.script, r"(?m)^loadLearningProgress\(\);$")

    def test_resource_center_has_ordered_skills_bank_and_quick_actions(self):
        learning = (PROJECT_ROOT / "learning-center.html").read_text(encoding="utf-8")
        self.assertIn("Research used throughout this Resource Center", learning)
        self.assertIn("independently summarizes and paraphrases", learning)
        self.assertGreaterEqual(learning.count('class="learning-source-note"'), 11)
        ordered_sections = [
            learning.index('id="careerGuidanceLessons"'),
            learning.index('id="resumeGuidanceLessons"'),
            learning.index('id="skillsBankSection"'),
            learning.index('id="jobSearchLessons"'),
            learning.index('id="interviewPreparationLessons"'),
        ]
        self.assertEqual(ordered_sections, sorted(ordered_sections))
        self.assertIn('id="skillsBankJobType"', learning)
        self.assertIn("function initializeSkillsBank()", self.script)
        self.assertIn('id="openMockInterviewButton"', learning)

    def test_resource_center_does_not_initialize_completion_controls(self):
        self.assertNotRegex(self.script, r"(?m)^setupLearningControls\(\);$")
        self.assertNotRegex(self.script, r"(?m)^loadLearningProgress\(\);$")

    def test_role_aware_workspace_and_account_navigation_exists(self):
        self.assertIn('moreSummary.textContent = "Workspace"', self.script)
        self.assertIn('accountMenu.className = "nav-account"', self.script)
        self.assertIn('accountPanel.appendChild(logoutButton)', self.script)
        self.assertIn(".main-nav .nav-account-menu", self.styles)
        self.assertIn("const installPromotionEnabled = false", self.script)

    def test_jobs_page_exposes_accessible_search_and_loading_states(self):
        self.assertIn('id="jobSearchForm"', self.jobs)
        self.assertIn('role="search"', self.jobs)
        self.assertIn('id="jobSearchButton"', self.jobs)
        self.assertIn('id="advancedFilterCount"', self.jobs)
        self.assertIn('class="job-loading-state"', self.jobs)
        self.assertIn("buildContentLoadingState", self.script)
        self.assertIn("const JOB_SEARCH_BATCH_SIZE = 100", self.script)
        self.assertIn("/jobs/search?", self.script)
        self.assertIn("scheduleServerJobSearch", self.script)
        self.assertIn("fetchWithTimeout", self.script)
        self.assertIn('id="minimumPayFilter"', self.jobs)
        self.assertIn('id="remoteEligibilityFilter"', self.jobs)
        self.assertIn('data-job-preset="teen"', self.jobs)
        self.assertIn('data-job-preset="first-job"', self.jobs)
        self.assertIn('name="jobExclusion"', self.jobs)
        self.assertIn("buildJobEvidenceDetails", self.script)
        self.assertIn("getTeenEligibilityBadge", self.script)
        self.assertIn("applyQuickJobPreset", self.script)

    def test_job_bookmark_is_icon_only_and_keeps_accessible_state(self):
        bookmark_markup = re.search(
            r'<button\s+type="button"\s+class="save-job-button.*?</button>',
            self.script,
            re.DOTALL,
        )
        self.assertIsNotNone(bookmark_markup)
        self.assertIn("buildBookmarkIcon(isSaved)", bookmark_markup.group(0))
        self.assertNotIn("<span>", bookmark_markup.group(0))
        self.assertIn('aria-pressed="${isSaved}"', bookmark_markup.group(0))
        self.assertIn('aria-label="${isSaved ? "Remove saved job" : "Save job"}"', bookmark_markup.group(0))

    def test_resume_job_action_is_a_suitability_review(self):
        resume = (PROJECT_ROOT / "resume.html").read_text(encoding="utf-8")
        self.assertIn("Résumé suitability evidence for this job", resume)
        self.assertIn('id="resumeSuitabilitySummary"', resume)
        self.assertIn("Review Résumé for This Job", self.script)
        self.assertIn('const mode = jobDescription.trim().split(/\\s+/).filter(Boolean).length >= 20 ? "JOB_REVIEW" : "GENERAL";', self.script)
        self.assertNotIn("Resume Fit &amp; Tailoring", self.script)
        self.assertNotIn(">Tailor Resume<", self.script)


if __name__ == "__main__":
    unittest.main()
