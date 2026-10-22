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
ASSET_VERSION = "20261022-v123"


class MarkupInspector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.h1_count = 0
        self.local_references = []
        self.select_values = {}
        self.current_select = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.append(attributes["id"])
        if tag == "h1":
            self.h1_count += 1
        if tag == "select":
            self.current_select = attributes.get("id")
            if self.current_select:
                self.select_values.setdefault(self.current_select, [])
        elif tag == "option" and self.current_select:
            self.select_values[self.current_select].append(attributes.get("value", ""))
        for attribute in ("href", "src"):
            value = attributes.get(attribute, "").strip()
            if value:
                self.local_references.append(value)

    def handle_endtag(self, tag):
        if tag == "select":
            self.current_select = None


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

    def test_filter_dropdowns_and_quick_paths_are_unique(self):
        inspector = MarkupInspector()
        inspector.feed(self.jobs)
        for select_id, values in inspector.select_values.items():
            with self.subTest(select=select_id):
                self.assertEqual(len(values), len(set(values)))

        preset_names = re.findall(r'data-job-preset="([^"]+)"', self.jobs)
        self.assertEqual(len(preset_names), len(set(preset_names)))

        mappings_match = re.search(
            r"function applyQuickJobPreset\(preset\) \{\s*const mappings = \{(.*?)\n  \};",
            self.script,
            re.DOTALL,
        )
        self.assertIsNotNone(mappings_match)
        targets = re.findall(
            r"(?:\"[^\"]+\"|[\w-]+): \[\"([^\"]+)\", \"([^\"]+)\"\]",
            mappings_match.group(1),
        )
        self.assertEqual(len(targets), len(set(targets)))
        self.assertEqual(len(preset_names), len(targets))
        self.assertEqual(self.jobs.count('class="reset-job-filters"'), 1)

    def test_every_visible_job_filter_is_sent_to_server_search(self):
        mappings = {
            "queryModeFilter": "query_mode",
            "locationMatchFilter": "location_mode",
            "categoryFilter": "category",
            "employmentTypeFilter": "employment_type",
            "remoteFilter": "remote",
            "remoteEligibilityFilter": "remote_eligibility",
            "experienceFilter": "experience",
            "ageFitFilter": "age_fit",
            "datePostedFilter": "date_posted",
            "listingQualityFilter": "listing_quality",
            "applicationFeatureFilter": "application_feature",
            "minimumPayFilter": "minimum_pay",
            "excludeTermsFilter": "exclude_terms",
        }
        for control_id, parameter in mappings.items():
            with self.subTest(control=control_id, parameter=parameter):
                self.assertIn(f'id="{control_id}"', self.jobs)
                self.assertRegex(
                    self.script,
                    rf"{parameter}: .*getElementById\(\"{control_id}\"\)",
                )
        self.assertIn('input[name="jobExclusion"]:checked', self.script)
        self.assertIn("exclusions: [...document.querySelectorAll", self.script)

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

    def test_registration_offers_paths_and_login_uses_authenticated_role(self):
        login = (PROJECT_ROOT / "login.html").read_text(encoding="utf-8")
        register = (PROJECT_ROOT / "register.html").read_text(encoding="utf-8")
        self.assertNotIn('data-auth-account=', login)
        self.assertIn('data-auth-account="job_seeker"', register)
        self.assertIn('data-auth-account="employer"', register)
        self.assertIn('role="group"', register)
        self.assertIn('id="loginSubmitButton"', login)
        self.assertIn('id="registerSubmitButton"', register)
        self.assertIn("function initializeAuthAccountChoice()", self.script)
        self.assertIn('if (authenticatedRole === "admin") return "admin-moderation.html";', self.script)
        self.assertIn('if (authenticatedRole === "employer") return "employer.html";', self.script)
        self.assertIn('"login.html?next=employer-access.html"', self.script)
        registration_handler = re.search(
            r'fetch\(apiUrl\("/register"\).*?body: JSON\.stringify\(\{(.*?)\}\)',
            self.script,
            re.DOTALL,
        )
        self.assertIsNotNone(registration_handler)
        self.assertNotIn("role", registration_handler.group(1))

    def test_job_cards_keep_primary_actions_clear_and_secondary_actions_grouped(self):
        card_actions = self.script.index('<div class="job-card-actions">')
        apply_action = self.script.index('class="apply-job-button', card_actions)
        details_action = self.script.index('class="job-details-button"', card_actions)
        more_actions = self.script.index('class="job-secondary-actions"', card_actions)
        compare_action = self.script.index('data-action="compare-job"', more_actions)
        resume_action = self.script.index('class="tailor-resume-button"', more_actions)
        self.assertLess(apply_action, details_action)
        self.assertLess(details_action, more_actions)
        self.assertLess(more_actions, compare_action)
        self.assertLess(compare_action, resume_action)
        self.assertIn('aria-label="More actions for ${escapeEmployerHtml(job.title)}"', self.script)
        self.assertIn("Final job-discovery overrides", self.styles)
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.styles)
        self.assertIn("Listing source &amp; verification", self.script)
        self.assertIn('class="job-evidence-disclosure-state" aria-hidden="true"', self.script)
        self.assertIn('data-action="toggle-job-evidence"', self.script)
        self.assertIn('function toggleJobEvidence(control)', self.script)
        self.assertIn('"toggle-job-evidence": () => toggleJobEvidence(control)', self.script)
        self.assertIn('.job-evidence-toggle[aria-expanded="true"]', self.styles)
        self.assertIn(".job-evidence-content.hidden", self.styles)
        self.assertIn('content: "View details +"', self.styles)
        self.assertIn('content: "Hide details −"', self.styles)
        self.assertIn('id="advancedFilterCount"', self.jobs)
        self.assertIn('`${secondaryCount} filter${secondaryCount === 1 ? "" : "s"} active`', self.script)
        self.assertNotIn('id="locationScopeFilter"', self.jobs)
        self.assertNotIn("Catalog area", self.jobs)
        self.assertIn('const PATHFORGE_CATALOG_SCOPE = "us"', self.script)
        self.assertIn('class="job-loading-state"', self.jobs)
        self.assertIn("buildContentLoadingState", self.script)
        self.assertIn("const JOB_SEARCH_BATCH_SIZE = 100", self.script)
        self.assertIn("const JOB_PAGE_SIZE = 24", self.script)
        self.assertIn("const MAX_SEARCH_BATCHES_PER_LOAD = 8", self.script)
        self.assertIn("requestedDisplayCount", self.script)
        self.assertIn('loadMoreButton.setAttribute("aria-busy", "true")', self.script)
        self.assertIn('loadMoreButton.textContent = "Try loading more jobs"', self.script)
        self.assertIn("const remainingMatchCount", self.script)
        self.assertIn("Load More Jobs (${remainingMatchCount.toLocaleString()} Job", self.script)
        self.assertNotIn("up to ${maximumRemainingCount.toLocaleString()}", self.script)
        self.assertIn('"No more matching listings"', self.script)
        self.assertIn("jobSearchTotal - displayedJobCount", self.script)

        self.assertIn("/jobs/search?", self.script)
        self.assertIn("scheduleServerJobSearch", self.script)
        self.assertIn("fetchWithTimeout", self.script)
        self.assertIn('id="minimumPayFilter"', self.jobs)
        self.assertIn('id="remoteEligibilityFilter"', self.jobs)
        self.assertIn('data-job-preset="age-14"', self.jobs)
        self.assertIn('data-job-preset="age-15"', self.jobs)
        self.assertIn('data-job-preset="teen"', self.jobs)
        self.assertIn("Minimum age 14+", self.jobs)
        self.assertIn("Minimum age 15+", self.jobs)
        self.assertIn("Minimum age 16+", self.jobs)
        self.assertNotIn("Minimum age 16–17+", self.jobs)
        self.assertIn("Older applicants can apply too", self.jobs)
        self.assertIn('15[ -]?year[ -]?old', self.script)
        self.assertIn('id="resetQuickJobPresetsButton"', self.jobs)
        self.assertIn("function resetQuickJobPresets()", self.script)
        self.assertIn("Location and schedule", self.jobs)
        self.assertIn("Role fit", self.jobs)
        self.assertIn("Listing details", self.jobs)
        self.assertIn("Job types to hide", self.jobs)
        self.assertIn('data-job-preset="first-job"', self.jobs)
        self.assertIn('data-job-preset="remote"', self.jobs)
        self.assertIn('data-job-preset="recent"', self.jobs)
        self.assertIn('data-job-preset="accommodation"', self.jobs)
        self.assertIn('data-job-preset="direct-apply"', self.jobs)
        self.assertIn('remote: ["remoteFilter", "remote"]', self.script)
        self.assertIn('recent: ["datePostedFilter", "7"]', self.script)
        self.assertIn('accommodation: ["listingQualityFilter", "accommodation"]', self.script)
        self.assertIn('"direct-apply": ["applicationFeatureFilter", "direct_apply"]', self.script)
        self.assertIn('id="queryModeFilter"', self.jobs)
        self.assertIn('query_mode: document.getElementById("queryModeFilter")', self.script)
        self.assertIn('name="jobExclusion"', self.jobs)
        self.assertIn("buildJobEvidenceDetails", self.script)
        self.assertIn("getTeenEligibilityBadge", self.script)
        self.assertIn("Possible teen fit · Age not stated", self.script)
        self.assertIn("age-confirmed-badge", self.styles)
        self.assertIn("age-estimated-badge", self.styles)
        self.assertIn("age-adult-badge", self.styles)
        self.assertIn("applyQuickJobPreset", self.script)
        self.assertNotIn("function isCanadaJobLocation", self.script)
        self.assertIn("isUnitedStatesJobLocation(job.location)", self.script)
        self.assertNotIn("United States only", self.jobs)
        self.assertNotIn("Country: Any", self.jobs)

    def test_equal_salary_bounds_render_as_one_amount(self):
        self.assertIn("if (minimumSalary === maximumSalary)", self.script)
        self.assertIn("`$${minimumSalary.toLocaleString()}${salarySuffix}`", self.script)

    def test_jobs_page_identifies_itself_before_and_after_scripts_load(self):
        self.assertIn('<body class="jobs-page">', self.jobs)
        self.assertIn('<a href="jobs.html" aria-current="page">Jobs</a>', self.jobs)
        self.assertIn('class="page-breadcrumb" aria-label="Breadcrumb"', self.jobs)
        self.assertIn('<span aria-current="page">Jobs</span>', self.jobs)
        self.assertIn('const pathParts = window.location.pathname.split("/").filter(Boolean);', self.script)
        self.assertIn('.main-nav .nav-links > a[aria-current="page"]', self.styles)

    def test_load_more_reveals_the_first_new_job(self):
        self.assertIn("const previouslyDisplayed = displayedJobCount", self.script)
        self.assertIn('loadMoreButton.textContent = "Finishing the current search…"', self.script)
        self.assertIn("const firstNewJob = filteredJobs[previouslyDisplayed]", self.script)
        self.assertIn('firstNewCard?.scrollIntoView({ behavior: "smooth", block: "start" })', self.script)

    def test_general_jobs_page_starts_at_the_top(self):
        self.assertIn("function initializeJobsPagePosition()", self.script)
        self.assertIn('window.history.scrollRestoration = "manual"', self.script)
        self.assertIn('parameters.has("job") || Boolean(window.location.hash)', self.script)
        self.assertIn('window.scrollTo({ top: 0, left: 0, behavior: "auto" })', self.script)

    def test_reset_job_filters_does_not_reapply_text_filters(self):
        self.assertEqual(self.jobs.count('id="resetJobFiltersButton"'), 1)
        self.assertIn('id="resetJobFiltersButton" class="reset-job-filters"', self.jobs)
        reset_function = re.search(
            r"function resetJobFilters\(\) \{(.*?)\n\}",
            self.script,
            re.DOTALL,
        )
        self.assertIsNotNone(reset_function)
        body = reset_function.group(1)
        select_block = re.search(
            r"const selectFilters = \[(.*?)\];",
            body,
            re.DOTALL,
        )
        self.assertIsNotNone(select_block)
        self.assertNotIn('"excludeTermsFilter"', select_block.group(1))
        self.assertNotIn('"minimumPayFilter"', select_block.group(1))

    def test_server_job_order_is_not_resorted_in_the_browser(self):
        self.assertIn("if (!refreshFromServer) {", self.script)
        self.assertIn(
            "if (!sharedJobLocation) return true;",
            self.script,
        )
        self.assertIn("Precise coordinates never leave the browser", self.script)
        self.assertIn(
            "if (refreshFromServer) filteredJobs = groupDuplicateJobs(filteredJobs);",
            self.script,
        )
        self.assertIn("if (refreshFromServer) {", self.script)
        self.assertIn(
            "filteredJobs = sortJobResults(filteredJobs, selectedSort, jobSearch, locationSearch);",
            self.script,
        )

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

    def test_saved_job_server_fields_are_html_escaped(self):
        self.assertIn("${escapeEmployerHtml(job.schedule)}", self.script)
        self.assertIn("${escapeEmployerHtml(job.experience)}", self.script)
        self.assertIn("${escapeEmployerHtml(error.message)}", self.script)
        self.assertNotIn("${job.schedule}", self.script)
        self.assertNotIn("${job.experience}", self.script)

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
