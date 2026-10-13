// Shared browser behavior for every PathForge page: navigation, jobs, accounts,
// dashboards, learning tools, employer workflows, accessibility, and feedback.
let allJobs = [];
const JOB_SEARCH_BATCH_SIZE = 100;
let jobCatalogLoading = false;
let jobSearchTotal = 0;
let jobSearchHasMore = false;
let jobSearchTimer = null;
let jobSearchRequestId = 0;
const { apiUrl, fetchWithTimeout, getSessionStatus } = window.PathForgeCore;

let savedJobIds = new Set();
let trackedJobIds = new Set();
let reportedJobIds = new Set();
let activeApplicationJob = null;
let activeReportJobId = null;
let activeReportTrigger = null;
let filteredJobs = [];
let displayedJobCount = 0;
const JOB_PAGE_SIZE = 12;
let jobChatAuthenticated = false;
let opportunityFitProfile = null;
let sharedJobLocation = null;
let usPlaceIndex = null;
let usPlaceLookup = null;
let savedSearches = [];
let connectedGuidanceLoaded = false;
let selectedResumeJobRequirements = "";
let comparedJobIds = new Set();
function readHiddenJobIds() {
  try {
    const stored = JSON.parse(localStorage.getItem("pathforgeHiddenJobs") || "[]");
    return new Set((Array.isArray(stored) ? stored : []).map(Number).filter(Number.isFinite));
  } catch (error) {
    return new Set();
  }
}
let hiddenJobIds = readHiddenJobIds();
const MAX_COMPARED_JOBS = 4;
const careerStageLabels = {
  first_time: "First-time job seeker", student: "Student",
  recent_graduate: "Recent graduate", career_changer: "Career changer",
  returning_worker: "Returning to work", experienced: "Experienced professional"
};

function waitForMinimumAssistantReview(
  startedAt,
  minimumMilliseconds
) {
  const remainingTime = Math.max(
    0,
    minimumMilliseconds - (Date.now() - startedAt)
  );

  return new Promise(resolve => {
    window.setTimeout(resolve, remainingTime);
  });
}

function buildContentLoadingState(label, cardCount = 2) {
  return `
    <div class="content-loading-state" role="status" aria-live="polite">
      <span class="visually-hidden">${escapeEmployerHtml(label)}</span>
      ${Array.from({ length: cardCount }, () => `
        <div class="content-loading-card" aria-hidden="true"></div>
      `).join("")}
    </div>
  `;
}

function quickMessage(message) {
  const input = document.getElementById("chatInput");

  if (!input) {
    return;
  }

  input.value = message;
  sendMessage();
}

async function loadConnectedGuidance() {
  const panel = document.getElementById("connectedGuidancePanel");
  const status = document.getElementById("connectedGuidanceStatus");
  const actionContainer = document.getElementById("connectedGuidanceAction");
  const evidenceList = document.getElementById("connectedGuidanceEvidenceList");
  if (!panel || !status || !actionContainer || !evidenceList || connectedGuidanceLoaded) return;
  try {
    const response = await fetch(apiUrl("/connected-guidance"), { credentials: "include" });
    if (!response.ok) {
      if (response.status === 401 || response.status === 403) panel.hidden = true;
      return;
    }
    const data = await response.json();
    const action = data.primary_action;
    actionContainer.innerHTML = `<strong>${escapeEmployerHtml(action.title)}</strong><p>${escapeEmployerHtml(action.reason)}</p><a href="${escapeEmployerHtml(action.href)}">${escapeEmployerHtml(action.action_label)}</a>`;
    evidenceList.innerHTML = (data.career_stage ? `<div class="career-stage-evidence"><strong>${escapeEmployerHtml(careerStageLabels[data.career_stage] || data.career_stage)}</strong><span>${escapeEmployerHtml(data.career_stage_guidance)}</span></div>` : "") + data.evidence.map(item => `<a href="${escapeEmployerHtml(item.href)}"><strong>${escapeEmployerHtml(item.label)}</strong><span>${escapeEmployerHtml(item.summary)}</span></a>`).join("") + `<p>${escapeEmployerHtml(data.explanation)}</p>`;
    status.textContent = "Suggested from your current PathForge activity.";
    connectedGuidanceLoaded = true;
  } catch (error) {
    status.textContent = "Connected guidance is temporarily unavailable.";
  }
}

async function loadCareerStagePersonalization() {
  const anchor = document.querySelector(
    ".resume-privacy-note, .learning-center-hero, .dashboard-welcome"
  );
  if (!anchor || document.querySelector(".career-stage-guidance-banner")) return;
  try {
    const sessionStatus = await getSessionStatus();
    if (!sessionStatus.authenticated) return;
    const response = await fetch(apiUrl("/connected-guidance"), { credentials: "include" });
    if (!response.ok) return;
    const data = await response.json();
    if (!data.career_stage) return;
    const banner = document.createElement("aside");
    banner.className = "career-stage-guidance-banner";
    banner.setAttribute("aria-label", "Career-stage guidance");
    banner.innerHTML = `<div><strong>Guidance for: ${escapeEmployerHtml(careerStageLabels[data.career_stage] || data.career_stage)}</strong><p>${escapeEmployerHtml(data.career_stage_guidance)}</p></div><a href="profile.html#profileCareerStage">Change</a>`;
    anchor.insertAdjacentElement("afterend", banner);
  } catch (error) {
    console.error("Career-stage guidance could not be loaded:", error);
  }
}

async function sendMessage() {
  const input = document.getElementById("chatInput");
  const chatBox = document.getElementById("chatBox");

  if (!input || !chatBox) return;

  const userText = input.value.trim();

  if (userText === "") return;

  addMessage(userText, "user-message");
  input.value = "";

  const typingMessage = addMessage(
    "PathForge AI is typing while reviewing your question...",
    "bot-message typing"
  );
  const reviewStartedAt = Date.now();

  try {
    const response = await fetch(apiUrl("/chat"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      credentials: "include",
      body: JSON.stringify({ message: userText })
    });

    const data = await response.json();

    if (response.status === 401) {
      jobChatAuthenticated = false;
      setJobChatVisibility(false);
      typingMessage.remove();
      return;
    }

    if (!response.ok) {
      throw new Error(
        data.detail ||
        "Job-search help is unavailable right now."
      );
    }

    await waitForMinimumAssistantReview(
      reviewStartedAt,
      1800
    );

    typingMessage.className = "bot-message";
    typingMessage.textContent = data.reply;
    if (data.safety_notice) {
      typingMessage.classList.add("assistant-safety-message");
      if (data.safety_level === "urgent") {
        typingMessage.classList.add("assistant-safety-urgent");
      }
    }
    if (Array.isArray(data.job_results) && data.job_results.length) {
      const jobList = document.createElement("ul");
      jobList.className = "chat-job-result-list";
      data.job_results.forEach(job => {
        const item = document.createElement("li");
        const link = document.createElement("a");
        link.href = job.href;
        link.textContent = `${job.title} at ${job.company} — ${job.location}`;
        item.appendChild(link);
        jobList.appendChild(item);
      });
      typingMessage.appendChild(jobList);
    }
    scrollChatToBottom();

  } catch (error) {
  console.error("Chat connection error:", error);

  typingMessage.className = "bot-message";
  typingMessage.textContent =
    "I could not connect to PathForge AI. Please try again.";
}
  scrollChatToBottom();
}

function addMessage(text, className) {
  const chatBox = document.getElementById("chatBox");

  const message = document.createElement("div");
  message.className = className;
  message.textContent = text;

  chatBox.appendChild(message);
  scrollChatToBottom();

  return message;
}

function toggleChat() {
  const chatWindow = document.getElementById("chatbotWindow");

  if (!chatWindow || !jobChatAuthenticated) {
    return;
  }

  chatWindow.classList.toggle("hidden-chat");

  const toggleButton =
    document.getElementById("chatToggleButton");

  toggleButton?.setAttribute(
    "aria-expanded",
    String(
      !chatWindow.classList.contains("hidden-chat")
    )
  );
}

function setJobChatVisibility(isVisible) {
  const currentPage =
    window.location.pathname.split("/").pop() ||
    "index.html";

  const shouldShow =
    isVisible && currentPage === "jobs.html";

  const toggleButton =
    document.getElementById("chatToggleButton");

  const chatWindow =
    document.getElementById("chatbotWindow");

  if (toggleButton) {
    toggleButton.style.display =
      shouldShow ? "inline-block" : "none";
  }

  if (!shouldShow) {
    chatWindow?.classList.add("hidden-chat");
    toggleButton?.setAttribute(
      "aria-expanded",
      "false"
    );
  }
}

function scrollChatToBottom() {
  const chatBox = document.getElementById("chatBox");

  if (chatBox) {
    chatBox.scrollTop = chatBox.scrollHeight;
  }
}

// Job discovery loads public listings first, then merges account-specific
// bookmark and tracking state when a session is available.
async function loadJobs() {
  const jobListings = document.getElementById("jobListings");

  if (!jobListings) {
    return;
  }

  try {
    jobCatalogLoading = true;
    const jobsResponse = await fetch(
      apiUrl(`/jobs/search?limit=${JOB_SEARCH_BATCH_SIZE}&offset=0`)
    );

    if (!jobsResponse.ok) {
      throw new Error("Jobs could not be loaded.");
    }

    const initialSearch = await jobsResponse.json();
    allJobs = initialSearch.jobs;
    jobSearchTotal = initialSearch.total;
    jobSearchHasMore = initialSearch.has_more;
    populateJobCategories(initialSearch.categories || []);

    const sessionStatus = await getSessionStatus();
    if (sessionStatus.authenticated) {

    try {
      const profileResponse = await fetch(
        apiUrl("/profile"),
        {
          credentials: "include"
        }
      );

      if (profileResponse.ok) {
        const profileData = await profileResponse.json();
        opportunityFitProfile = profileData.profile || null;

        const preferredLocation = String(
          opportunityFitProfile?.preferred_location || ""
        ).trim();
        const locationInput =
          document.getElementById("locationSearchInput");
        if (preferredLocation && locationInput && !locationInput.value) {
          locationInput.value = preferredLocation;
          updateJobLocationStatus(
            `Automatically using your saved preferred location: `
            + `${preferredLocation}.`
          );
        }
      }
    } catch (profileError) {
      console.error(
        "Opportunity Fit preferences could not be loaded:",
        profileError
      );
    }

        try {
      const savedResponse = await fetch(
        apiUrl("/saved-jobs"),
        {
          credentials: "include"
        }
      );

      if (savedResponse.ok) {
        const savedData = await savedResponse.json();

        savedJobIds = new Set(
          savedData.saved_jobs.map(job => job.id)
        );
      }
    } catch (savedError) {
      console.error(
        "Saved job status could not be loaded:",
        savedError
      );
    }

    try {
      const applicationsResponse = await fetch(
        apiUrl("/applications"),
        {
          credentials: "include"
        }
      );

      if (applicationsResponse.ok) {
        const applicationsData =
          await applicationsResponse.json();

        trackedJobIds = new Set(
          applicationsData.applications.map(
            application => application.job_id
          )
        );
      }
    } catch (applicationsError) {
      console.error(
        "Application status could not be loaded:",
        applicationsError
      );
    }

    try {
      const reportsResponse = await fetch(
        apiUrl("/job-reports/mine"),
        { credentials: "include" }
      );

      if (reportsResponse.ok) {
        const reportsData = await reportsResponse.json();
        reportedJobIds = new Set(
          (reportsData.reports || []).map(report => report.job_id)
        );
      }
    } catch (reportsError) {
      console.error("Listing report status could not be loaded:", reportsError);
    }
    }

    applyJobSearchHistoryParameters();
    const selectedJobId = Number(
      new URLSearchParams(window.location.search).get("job")
    );

    if (
      Number.isInteger(selectedJobId)
      && selectedJobId > 0
      && !allJobs.some(job => Number(job.id) === selectedJobId)
    ) {
      const selectedResponse = await fetch(apiUrl(`/jobs/${selectedJobId}`));
      if (selectedResponse.ok) allJobs.unshift(await selectedResponse.json());
    }

    if (Number.isInteger(selectedJobId) && selectedJobId > 0) {
      filteredJobs = allJobs.filter(job => job.id === selectedJobId);
      displayJobs(filteredJobs);
      window.requestAnimationFrame(() => {
        const selectedCard = document.getElementById(`job-${selectedJobId}`);
        selectedCard?.classList.add("alert-target-job");
        selectedCard?.focus({ preventScroll: true });
        selectedCard?.scrollIntoView({ block: "start" });
      });
    } else {
      await runJobSearch(0);
    }
    jobCatalogLoading = false;

  } catch (error) {
    console.error("Failed to load jobs:", error);

    jobListings.innerHTML = `
      <p class="error-message">
        Job listings could not be loaded. Please try again.
      </p>
    `;
  }
}

function formatJobSalary(job) {
  if (
    job.salary_min == null
    || job.salary_max == null
    || !job.salary_period
  ) {
    const employerPay = String(job.pay || "").trim();

    return employerPay && employerPay !== "Not listed"
      ? employerPay
      : "Not listed";
  }

  return (
    `$${Number(job.salary_min).toLocaleString()}`
    + `–$${Number(job.salary_max).toLocaleString()}`
    + `/${job.salary_period}`
  );
}

function getJobPayLabel(job) {
  const salaryPeriod = String(
    job.salary_period || ""
  ).toLowerCase();

  const payText = String(job.pay || "").toLowerCase();

  const isAnnualSalary =
    salaryPeriod === "year"
    || salaryPeriod === "annual"
    || payText.includes("per year")
    || payText.includes("/year")
    || payText.includes("annual")
    || payText.includes("salary");

  return isAnnualSalary ? "Salary" : "Pay";
}

function formatApplicationDeadline(deadline) {
  if (!deadline) {
    return "";
  }

  const parsedDate = new Date(`${deadline}T00:00:00`);

  if (Number.isNaN(parsedDate.getTime())) {
    return deadline;
  }

  return parsedDate.toLocaleDateString(
    undefined,
    {
      year: "numeric",
      month: "long",
      day: "numeric"
    }
  );
}


function applicationDeadlineHasPassed(deadline) {
  if (!deadline) {
    return false;
  }

  const deadlineDate = new Date(`${deadline}T23:59:59`);
  return deadlineDate.getTime() < Date.now();
}

function normalizeFitText(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function splitFitPreferences(value) {
  return String(value || "")
    .split(/[,;\n]/)
    .map(item => normalizeFitText(item))
    .filter(item => item.length >= 2);
}

function normalizePayPeriod(value) {
  const period = normalizeFitText(value);

  if (period.includes("hour") || period === "hr") {
    return "hour";
  }

  if (period.includes("year") || period.includes("annual")) {
    return "year";
  }

  return "";
}

function getComparableJobPay(job) {
  if (job.salary_min != null && job.salary_max != null) {
    return {
      minimum: Number(job.salary_min),
      maximum: Number(job.salary_max),
      period: normalizePayPeriod(job.salary_period)
    };
  }

  const payText = String(job.pay || "");
  const amounts = [...payText.matchAll(/\$?([\d,]+(?:\.\d+)?)/g)]
    .map(match => Number(match[1].replace(/,/g, "")))
    .filter(Number.isFinite);

  if (amounts.length === 0) {
    return null;
  }

  return {
    minimum: Math.min(...amounts),
    maximum: Math.max(...amounts),
    period: normalizePayPeriod(payText)
  };
}

function buildOpportunityFitSnapshot(job) {
  const profile = opportunityFitProfile;

  if (!profile) {
    return "";
  }

  const insights = [];
  const jobText = normalizeFitText(
    [
      job.title,
      job.category,
      job.description,
      job.requirements,
      job.preferred_qualifications,
      job.experience
    ].join(" ")
  );

  const preferredPay = Number(profile.minimum_base_pay);
  const preferredPeriod = normalizePayPeriod(profile.pay_period);
  const jobPay = getComparableJobPay(job);

  if (preferredPay > 0 && preferredPeriod && jobPay?.period) {
    if (jobPay.period !== preferredPeriod) {
      insights.push({
        type: "review",
        text: "Pay uses a different period than your preference"
      });
    } else if (jobPay.minimum >= preferredPay) {
      insights.push({
        type: "match",
        text: "Listed base pay meets your minimum"
      });
    } else if (jobPay.maximum >= preferredPay) {
      insights.push({
        type: "review",
        text: "The pay range reaches your minimum"
      });
    } else {
      insights.push({
        type: "difference",
        text: "Listed pay is below your minimum"
      });
    }
  }

  const schedulePreferences = splitFitPreferences(
    profile.schedule_preference
  );
  const jobSchedule = normalizeFitText(
    job.employment_type || job.schedule
  );

  if (schedulePreferences.length > 0 && jobSchedule) {
    const matchingSchedule = schedulePreferences.find(preference =>
      jobSchedule.includes(preference)
      || preference.includes(jobSchedule)
    );

    insights.push({
      type: matchingSchedule ? "match" : "review",
      text: matchingSchedule
        ? "Schedule matches your preference"
        : "Review the schedule against your preference"
    });
  }

  const workPreference = normalizeFitText(profile.work_preference);

  if (workPreference && workPreference !== "no preference") {
    if (job.is_remote === 1) {
      insights.push({
        type: workPreference === "remote" ? "match" : "review",
        text: workPreference === "remote"
          ? "Remote setting matches your preference"
          : "This role is listed as remote"
      });
    } else if (job.is_remote === 0 && workPreference === "remote") {
      insights.push({
        type: "difference",
        text: "This role is not listed as remote"
      });
    }
  }

  const preferredLocation = normalizeFitText(profile.preferred_location);
  const jobLocation = normalizeFitText(job.location);

  if (preferredLocation && jobLocation) {
    const locationMatches =
      jobLocation.includes(preferredLocation)
      || preferredLocation.includes(jobLocation);

    insights.push({
      type: locationMatches ? "match" : "review",
      text: locationMatches
        ? "Location matches your preference"
        : "Review this location and commute"
    });
  }

  const industries = splitFitPreferences(profile.preferred_industries);
  const matchingIndustry = industries.find(industry =>
    jobText.includes(industry)
  );

  if (matchingIndustry) {
    insights.push({
      type: "match",
      text: "Matches a preferred industry"
    });
  }

  const skills = splitFitPreferences(profile.skills);
  const matchingSkills = skills
    .filter(skill => jobText.includes(skill))
    .slice(0, 3);

  if (matchingSkills.length > 0) {
    insights.push({
      type: "match",
      text: `Skills mentioned: ${matchingSkills.join(", ")}`
    });
  }

  const additionalPayPreferences = splitFitPreferences(
    profile.desired_pay
  );
  const additionalPayKeywords = {
    "tips": ["tip", "tips"],
    "commission": ["commission"],
    "performance bonuses": ["bonus", "bonuses", "incentive"],
    "signing bonus": ["signing bonus", "sign on bonus"],
    "overtime pay": ["overtime"],
    "shift differential": ["shift differential"],
    "equity or stock": ["equity", "stock"],
    "negotiable pay": ["negotiable"]
  };
  const matchingAdditionalPay = additionalPayPreferences.filter(
    preference => (
      additionalPayKeywords[preference] || [preference]
    ).some(keyword => jobText.includes(keyword))
  );

  if (matchingAdditionalPay.length > 0) {
    insights.push({
      type: "match",
      text: `Additional pay mentioned: ${matchingAdditionalPay.join(", ")}`
    });
  }

  if (insights.length === 0) {
    return `
      <div class="opportunity-fit-snapshot incomplete">
        <strong>Opportunity Fit</strong>
        <span>
          <a href="profile.html">Complete your preferences</a>
          to see an explained fit snapshot.
        </span>
      </div>
    `;
  }

  const matchCount = insights.filter(
    insight => insight.type === "match"
  ).length;

  return `
    <details class="opportunity-fit-snapshot">
      <summary>
        <span>Opportunity Fit</span>
        <strong>
          ${matchCount} ${matchCount === 1 ? "match" : "matches"}
          identified
        </strong>
      </summary>

      <ul>
        ${insights.map(insight => `
          <li class="fit-${insight.type}">
            ${escapeEmployerHtml(insight.text)}
          </li>
        `).join("")}
      </ul>

      <p>
        Based on your saved preferences and the information in this listing.
        This does not predict hiring decisions.
      </p>
    </details>
  `;
}

function jobWasRecentlyPosted(job) {
  const postedValue = job.posted_at || job.created_at;

  if (!postedValue) {
    return false;
  }

  const postedDate = new Date(postedValue);

  if (Number.isNaN(postedDate.getTime())) {
    return false;
  }

  const ageInDays = (
    Date.now() - postedDate.getTime()
  ) / (1000 * 60 * 60 * 24);

  return ageInDays >= 0 && ageInDays <= 7;
}

function getEmployerResponseDays(job) {
  const responseDays = Number(
    job.typical_response_days
    ?? job.response_time_days
  );

  return Number.isInteger(responseDays) && responseDays > 0
    ? responseDays
    : null;
}

function formatJobCardDate(value) {
  if (!value) return "Not listed";

  const rawValue = String(value).trim();
  const dateOnlyMatch = rawValue.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  const parsedDate = dateOnlyMatch
    ? new Date(
        Number(dateOnlyMatch[1]),
        Number(dateOnlyMatch[2]) - 1,
        Number(dateOnlyMatch[3])
      )
    : new Date(rawValue);
  if (Number.isNaN(parsedDate.getTime())) return "Not listed";

  return parsedDate.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric"
  });
}

function getJobWorkSetting(job) {
  const text = [job.title, job.location, job.description, job.requirements]
    .map(value => String(value || "").toLowerCase())
    .join(" ");
  if (/\bhybrid\b|partly remote|remote and (?:in[- ]?office|on[- ]?site)/i.test(text)) {
    return "Hybrid";
  }
  if (Number(job.is_remote) === 1) return "Remote";
  if (Number(job.is_remote) === 0) return "On-site";
  return "Not specified";
}

function getJobApplicationMethod(job) {
  return job.application_method === "pathforge"
    ? "Apply through PathForge"
    : "Apply on employer website";
}

function buildQualificationPreview(job) {
  const rawSource = job.requirements
    || job.preferred_qualifications;
  const content = document.createElement("template");
  content.innerHTML = String(rawSource || "")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p>|<\/li>/gi, "\n");
  let sourceText = String(content.content.textContent || "")
    .replace(/\r/g, "")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{2,}/g, "\n")
    .trim()
    .replace(
      /^(?:requirements?|qualifications?)\s*(?:\(if applicable\))?\s*:?\s*/i,
      ""
    );

  if (!sourceText) {
    return {
      items: ["Qualifications are not listed in PathForge. Review the official employer listing before applying."],
      hasMore: false
    };
  }

  const parts = sourceText
    .split(/\n+|\s*[•▪◦]\s*|(?<=[.!?;])\s+(?=[A-Z0-9])/)
    .map(part => part.replace(/^[\s*\-–—]+/, "").trim())
    .filter(part => part.length >= 12)
    .filter(part => !/^[,.;:]|^[a-z]/.test(part))
    .filter(part => !/^(?:company|job|position) description\b|\blooking to provide opportunity\b|\byou got (?:game|spring)\b/i.test(part));
  const seenMinimumAges = new Set();
  const ageDeduplicatedParts = parts.map(part => {
    const ageMatch = part.match(
      /\b(?:minimum age(?: stated by employer)?\s*(?:is|:)?\s*|(?:you\s+are\s+)?at least\s+|(?:you\s+)?must be\s+)?(1[4-9]|2[01])\+?\s*(?:years? old|years?(?: of)? age)?\b/i
    );
    if (!ageMatch) return part;
    const age = ageMatch[1];
    if (!seenMinimumAges.has(age)) {
      seenMinimumAges.add(age);
      return part;
    }
    return part
      .replace(
        /^\s*(?:minimum age(?: stated by employer)?\s*(?:is|:)?\s*|(?:you\s+are\s+)?at least\s+|(?:you\s+)?must be\s+)?1[4-9]\+?\s*(?:years? old|years?(?: of)? age)?\s*[,.;:–—-]*\s*/i,
        ""
      )
      .trim();
  }).filter(part => part.length >= 12);

  const selectedParts = ageDeduplicatedParts;
  const distinctParts = [];
  (selectedParts.length ? selectedParts : [sourceText]).forEach(part => {
    const fingerprint = part.toLowerCase()
      .replace(/\b(?:the|a|an)\b/g, " ")
      .replace(/[^a-z0-9]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    if (!fingerprint) return;
    const duplicateIndex = distinctParts.findIndex(existing => {
      const existingFingerprint = existing.toLowerCase()
        .replace(/\b(?:the|a|an)\b/g, " ")
        .replace(/[^a-z0-9]+/g, " ")
        .replace(/\s+/g, " ")
        .trim();
      return existingFingerprint === fingerprint
        || (fingerprint.length >= 30 && existingFingerprint.includes(fingerprint))
        || (existingFingerprint.length >= 30 && fingerprint.includes(existingFingerprint));
    });
    if (duplicateIndex === -1) {
      distinctParts.push(part);
    } else if (part.length > distinctParts[duplicateIndex].length) {
      distinctParts[duplicateIndex] = part;
    }
  });
  const visibleDistinctParts = distinctParts
    .filter(part => !/^see (?:the )?official posting for complete qualifications?\.?$/i.test(part));

  if (!visibleDistinctParts.length) {
    return {
      items: ["This source did not provide detailed qualifications. Check Full Details and the official listing before applying."],
      hasMore: false
    };
  }

  const maximumPreviewLength = 180;
  const previewItems = visibleDistinctParts.slice(0, 1).map(part => {
    if (part.length <= maximumPreviewLength) return part;
    const shortened = part.slice(0, maximumPreviewLength + 1);
    const lastSpace = shortened.lastIndexOf(" ");
    return shortened.slice(0, Math.max(lastSpace, 120)).trimEnd() + "…";
  });

  return {
    items: previewItems,
    hasMore: visibleDistinctParts.length > previewItems.length
      || visibleDistinctParts.some(part => part.length > maximumPreviewLength)
  };
}

function getJobLocationParts(location) {
  const rawLocation = String(location || "").trim();
  if (!rawLocation) return [];

  let locations = [];
  if (rawLocation.includes(";")) {
    locations = rawLocation.split(";");
  } else {
    const countryMatches = rawLocation.match(/,\s*United States\b/gi) || [];
    if (countryMatches.length > 1) {
      locations = rawLocation
        .split(/,\s*United States\s*,?/i)
        .map(value => value.trim())
        .filter(Boolean)
        .map(value => `${value}, United States`);
    }
  }

  return locations
    .map(value => value.trim().replace(/^,|,$/g, "").trim())
    .filter(Boolean);
}

function getGeographicJobLocation(location, job = null) {
  const rawLocation = String(location || "").trim();
  if (!rawLocation) {
    return Number(job?.is_remote) === 1
      ? "United States"
      : "Location not listed";
  }

  let geographicLocation = rawLocation
    .replace(
      /(^|[,;|])\s*(?:remote|hybrid|on[- ]?site)(?:\s*[-–—]\s*(?:us|usa|united states)|\s*\((?:us|usa|united states)\))?\s*(?=$|[,;|])/gi,
      "$1"
    )
    .replace(
      /^\s*(?:remote|hybrid|on[- ]?site)\s*[-–—,:|]+\s*/i,
      ""
    )
    .replace(
      /\s*(?:[-–—,;|]|\()\s*(?:remote|hybrid|on[- ]?site)\s*\)?\s*$/i,
      ""
    )
    .replace(/\s*([,;|])(?:\s*\1)+/g, "$1")
    .replace(/^[\s,;|]+|[\s,;|]+$/g, "")
    .trim();

  if (!geographicLocation) {
    geographicLocation = /\b(?:us|usa|united states)\b/i.test(rawLocation)
      || Number(job?.is_remote) === 1
      ? "United States"
      : "Location not listed";
  }

  return geographicLocation;
}

function formatJobLocationDisplay(location, job = null) {
  const rawLocation = getGeographicJobLocation(location, job);
  if (!rawLocation) return "Location not listed";
  const locations = getJobLocationParts(rawLocation);

  if (locations.length <= 1) return rawLocation;

  const firstLocation = locations[0].replace(/,\s*United States$/i, "");
  const remainingCount = locations.length - 1;
  return `${firstLocation} + ${remainingCount} more ${remainingCount === 1 ? "location" : "locations"}`;
}

function buildJobLocationMarkup(location, job = null) {
  const rawLocation = getGeographicJobLocation(location, job);
  const locations = getJobLocationParts(rawLocation);
  if (locations.length <= 1) {
    return escapeEmployerHtml(formatJobLocationDisplay(rawLocation, job));
  }

  const firstLocation = locations[0].replace(/,\s*United States$/i, "");
  const remainingCount = locations.length - 1;
  return `<details class="job-location-details">
    <summary>
      <span class="job-location-primary">${escapeEmployerHtml(firstLocation)}</span>
      <span class="job-location-more job-location-more-open">View ${remainingCount} more</span>
      <span class="job-location-more job-location-more-close">Hide locations</span>
      <span class="job-location-chevron" aria-hidden="true"></span>
    </summary>
    <ul aria-label="All available job locations">
      ${locations.map(item => `<li>${escapeEmployerHtml(item)}</li>`).join("")}
    </ul>
  </details>`;
}

function formatJobTypeDisplay(value) {
  const rawValue = String(value || "").trim();
  if (!rawValue || /^not listed$/i.test(rawValue)) return "Not listed";

  const normalized = rawValue.toLowerCase().replace(/[\s_-]+/g, "");
  const labels = {
    fulltime: "Full-time",
    parttime: "Part-time",
    internship: "Internship",
    intern: "Internship",
    contract: "Contract",
    contractor: "Contract",
    temporary: "Temporary",
    seasonal: "Seasonal",
    volunteer: "Volunteer",
    perdiem: "Per diem"
  };
  return labels[normalized] || rawValue;
}

function getJobTrustBadgeClass(job) {
  if (job.trust_level === "official_source") return "trust-official";
  if (job.trust_level === "pathforge_access") return "trust-pathforge";
  return "trust-limited";
}

function buildJobSafetySignals(job) {
  const signals = Array.isArray(job.safety_signals)
    ? job.safety_signals
    : [];

  if (!signals.length) return "";

  return `
    <aside class="job-safety-warning" aria-label="Job safety notice">
      <strong>Review these safety signals</strong>
      <ul>
        ${signals.map(signal => `
          <li>
            <span>${escapeEmployerHtml(signal.label)}</span>
            ${escapeEmployerHtml(signal.explanation)}
          </li>
        `).join("")}
      </ul>
      <p>
        These text signals are cautions, not proof that a listing is fraudulent.
        Verify the employer independently before sharing sensitive information.
      </p>
    </aside>
  `;
}

function buildJobTrustDetails(job) {
  const checkedDate = job.last_link_checked_at || job.last_verified_at;

  return `
    <details class="job-trust-details">
      <summary>Why this trust label appears</summary>
      <p>${escapeEmployerHtml(
        job.trust_explanation
        || "Confirm this listing and employer independently before applying."
      )}</p>
      ${checkedDate ? `
        <p>Source checked: ${formatJobCardDate(checkedDate)}</p>
      ` : ""}
    </details>
  `;
}

function buildJobEvidenceDetails(job) {
  const sourceName = job.source || (job.application_method === "pathforge" ? "PathForge employer posting" : "Employer website");
  const sourceUrl = job.source_url || job.application_url;
  const evidence = [
    ["Listing source", sourceName],
    ["Source status", job.verification_status === "verified" ? "Verified source" : "Not independently verified"],
    ["First posted", formatJobCardDate(job.posted_at || job.created_at)],
    ["Last source check", formatJobCardDate(job.last_verified_at || job.last_link_checked_at)],
    ["Official link", sourceUrl ? "Available" : "Not provided"],
    ["Job details", job.details_truncated ? "Preview shown; full details load on request" : "Complete PathForge record shown"]
  ];
  return `<details class="job-evidence-details"><summary>Source and evidence</summary><dl>${evidence.map(([label, value]) => `<div><dt>${escapeEmployerHtml(label)}</dt><dd>${escapeEmployerHtml(value || "Not listed")}</dd></div>`).join("")}</dl>${sourceUrl ? `<a href="${escapeEmployerHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">Open the source listing</a>` : ""}<p>PathForge separates information supplied by the listing from its own verification and completeness checks.</p></details>`;
}

function normalizeJobIdentity(value) {
  return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function getJobDuplicateKey(job) {
  return [job.title, job.company, job.location].map(normalizeJobIdentity).join("|");
}

function groupDuplicateJobs(jobs) {
  const groups = new Map();
  jobs.forEach(job => {
    const key = getJobDuplicateKey(job);
    const existing = groups.get(key);
    if (!existing) {
      groups.set(key, { ...job, duplicate_count: 1, alternate_sources: [] });
      return;
    }
    existing.duplicate_count += 1;
    const source = job.source || job.company;
    if (source && !existing.alternate_sources.includes(source)) {
      existing.alternate_sources.push(source);
    }
    const existingOfficial = Boolean(existing.source_url);
    const candidateOfficial = Boolean(job.source_url);
    if (!existingOfficial && candidateOfficial) {
      Object.assign(existing, job, {
        duplicate_count: existing.duplicate_count,
        alternate_sources: existing.alternate_sources
      });
    }
  });
  return [...groups.values()];
}

function buildJobQualityReview(job) {
  const checks = [
    [formatJobSalary(job) !== "Not listed", "Pay is listed", "Pay is not listed"],
    [Boolean(normalizeEmploymentSchedule(job.employment_type || job.schedule)), "Full-time or part-time is stated", "Full-time or part-time is not listed"],
    [job.is_remote === 0 || job.is_remote === 1, "Work setting is stated", "Work setting is not listed"],
    [Boolean(cleanJobPostingText(job.requirements)), "Requirements are provided", "Requirements are not listed"],
    [Boolean(job.application_deadline || job.expires_at), "An application deadline is provided", "Application deadline is not listed"],
    [Boolean(job.source_url || job.application_url), "An application source is provided", "Application source is not listed"],
    [Boolean(job.last_verified_at), "The source has a verification date", "Source verification date is not listed"]
  ];
  const confirmed = checks.filter(([passed]) => passed).length;
  const label = confirmed >= 6 ? "Well documented" : confirmed >= 4 ? "Some details missing" : "Limited details";
  return { checks, confirmed, label };
}

function hasJobAccommodationInformation(job) {
  if (job?.accommodation_info === true) return true;
  const details = [
    job?.description,
    job?.requirements,
    job?.preferred_qualifications
  ].map(value => String(value || "")).join(" ");
  return /\b(?:reasonable\s+accommodations?|disability\s+accommodations?|accommodations?\s+(?:during|for|throughout|in)\s+(?:the\s+)?(?:application|interview|hiring|recruit(?:ing|ment)|selection)\s+process|request\s+(?:an?\s+)?accommodations?|need\s+(?:an?\s+)?accommodations?\s+to\s+(?:apply|participate|complete)|alternative\s+(?:method|way)\s+(?:of|to)\s+appl(?:y|ication))\b/i.test(details);
}

function getJobApplicationFeatures(job) {
  const details = [job?.description, job?.requirements, job?.preferred_qualifications]
    .map(value => String(value || "")).join(" ");
  return {
    direct_apply: job?.direct_apply === true || job?.application_method === "pathforge",
    no_cover_letter: job?.no_cover_letter === true || /\b(?:no\s+cover\s+letter\s+(?:is\s+)?required|cover\s+letter\s+(?:is\s+)?(?:not\s+required|optional)|do\s+not\s+(?:include|submit|send)\s+(?:a\s+)?cover\s+letter|resume\s+only)\b/i.test(details),
    accommodation_contact: job?.accommodation_contact === true || (hasJobAccommodationInformation(job) && /\b(?:contact|email|call|reach\s+out|notify|let\s+us\s+know)\b/i.test(details)),
    additional_steps: job?.additional_steps === true || /\b(?:skills?\s+assessment|written\s+assessment|coding\s+exercise|take[- ]home\s+(?:test|exercise|assignment)|work\s+sample|portfolio\s+(?:is\s+)?required|professional\s+references?\s+required|background\s+check|drug\s+(?:test|screen))\b/i.test(details)
  };
}

function buildJobQualityDetails(job) {
  const quality = buildJobQualityReview(job);
  return `<details class="job-quality-details"><summary><span>Posting quality</span><strong>${quality.confirmed} of ${quality.checks.length} details confirmed · ${quality.label}</strong></summary><ul>${quality.checks.map(([passed, availableLabel, missingLabel]) => `<li class="${passed ? "quality-present" : "quality-missing"}"><span aria-hidden="true">${passed ? "✓" : "–"}</span>${escapeEmployerHtml(passed ? availableLabel : missingLabel)}</li>`).join("")}</ul><p>This reviews the completeness of the posting, not your likelihood of being hired.</p></details>`;
}

function getJobViewState(job) {
  const viewed = JSON.parse(localStorage.getItem("pathforgeViewedJobs") || "{}");
  const fingerprint = [job.title, job.company, job.location, job.pay, job.salary_min, job.salary_max, job.requirements, job.application_deadline, job.updated_at].map(value => String(value || "")).join("|");
  const previous = viewed[job.id];
  return { fingerprint, viewed: Boolean(previous), changed: Boolean(previous && previous.fingerprint !== fingerprint) };
}

function markJobViewed(jobId) {
  const job = allJobs.find(item => Number(item.id) === Number(jobId));
  if (!job) return;
  const state = getJobViewState(job);
  const viewed = JSON.parse(localStorage.getItem("pathforgeViewedJobs") || "{}");
  viewed[job.id] = { fingerprint: state.fingerprint, viewedAt: new Date().toISOString() };
  localStorage.setItem("pathforgeViewedJobs", JSON.stringify(viewed));
}

function buildWhyThisResult(job) {
  const reasons = [...(job._relevanceReasons || [])];
  const query = document.getElementById("jobSearchInput")?.value.trim();
  const category = document.getElementById("categoryFilter")?.value;
  const schedule = document.getElementById("employmentTypeFilter")?.value;
  const remote = document.getElementById("remoteFilter")?.value;
  const location = document.getElementById("locationSearchInput")?.value.trim();
  if (query) reasons.push(`Its title or employer matches “${query}”.`);
  if (category && category !== "all") reasons.push(`It is classified as ${category} from the job title.`);
  if (schedule && schedule !== "all") reasons.push(`The posting states ${schedule.replace("-", " ")}.`);
  if (remote && remote !== "all") reasons.push(`Its work setting matches ${remote === "onsite" ? "on-site" : remote}.`);
  if (location) reasons.push(`Its listed location matches the location search.`);
  if (!reasons.length) reasons.push("It is an active listing that matches the filters currently selected.");
  return `<details class="why-job-result"><summary>Why this result?</summary><ul>${[...new Set(reasons)].map(reason => `<li>${escapeEmployerHtml(reason)}</li>`).join("")}</ul><p>Best Match prioritizes title and location matches, then freshness and listing completeness. It does not predict whether you will be hired.</p></details>`;
}

function updateJobComparisonBar() {
  const bar = document.getElementById("jobComparisonBar");
  const count = document.getElementById("jobComparisonCount");
  if (!bar || !count) return;
  count.textContent = `${comparedJobIds.size} job${comparedJobIds.size === 1 ? "" : "s"} selected`;
  bar.classList.toggle("hidden", comparedJobIds.size === 0);
  const openButton = document.getElementById("openJobComparisonButton");
  if (openButton) openButton.disabled = comparedJobIds.size < 2;
}

function toggleJobComparison(jobId, checkbox) {
  if (checkbox.checked && comparedJobIds.size >= MAX_COMPARED_JOBS) {
    checkbox.checked = false;
    showJobSaveToast("You can compare up to 4 jobs at a time.", "error");
    return;
  }
  checkbox.checked ? comparedJobIds.add(Number(jobId)) : comparedJobIds.delete(Number(jobId));
  updateJobComparisonBar();
}

function openJobComparison() {
  const dialog = document.getElementById("jobComparisonDialog");
  const table = document.getElementById("jobComparisonTable");
  if (!dialog || !table || comparedJobIds.size < 2) return;
  const jobs = [...comparedJobIds].map(id => allJobs.find(job => Number(job.id) === id)).filter(Boolean);
  const rows = [
    ["Employer", job => job.company],
    ["Location", job => getGeographicJobLocation(job.location, job)],
    ["Work setting", getJobWorkSetting],
    ["Schedule", job => formatJobTypeDisplay(job.employment_type || job.schedule)],
    ["Pay", formatJobSalary], ["Experience", job => job.experience || "Not listed"],
    ["Deadline", job => formatApplicationDeadline(job.application_deadline || job.expires_at) || "Not listed"],
    ["Posting quality", job => { const q = buildJobQualityReview(job); return `${q.confirmed}/${q.checks.length} · ${q.label}`; }],
    ["Verification", job => job.trust_label || "Limited Verification"]
  ];
  table.innerHTML = `<table><thead><tr><th scope="col">Detail</th>${jobs.map(job => `<th scope="col">${escapeEmployerHtml(job.title)}</th>`).join("")}</tr></thead><tbody>${rows.map(([label, getter]) => `<tr><th scope="row">${label}</th>${jobs.map(job => `<td>${escapeEmployerHtml(getter(job) || "Not listed")}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  dialog.showModal();
}


function displayJobs(jobs, append = false) {
  const jobListings = document.getElementById("jobListings");
  const resultCount = document.getElementById("jobResultCount");
  const loadMoreButton = document.getElementById("loadMoreJobsButton");
  const endMessage = document.getElementById("jobResultsEndMessage");

  if (!jobListings) {
    return;
  }

  if (!append) {
    jobListings.innerHTML = "";
    displayedJobCount = 0;
  }

  if (jobs.length === 0) {
    jobListings.innerHTML = `
      <div class="empty-state">
        <h3>${jobCatalogLoading ? "Searching the remaining listings…" : "No jobs found"}</h3>
        <p>${jobCatalogLoading ? "More catalog results are still loading." : "Try broadening your search or clearing the current filters."}</p>
        <button type="button" data-action="reset-job-filters">Clear Search and Filters</button>
      </div>
    `;

    if (resultCount) {
      resultCount.textContent = jobCatalogLoading
        ? "No matches in the first results · loading remaining listings…"
        : "0 jobs found";
    }
    if (loadMoreButton) {
      loadMoreButton.classList.add("hidden");
      loadMoreButton.classList.remove("results-complete");
      loadMoreButton.disabled = false;
      loadMoreButton.textContent = "Load more jobs";
    }
    if (endMessage) endMessage.classList.add("hidden");
    return;
  }

  // Render a small page at a time so large result sets remain responsive.
  const nextJobs = jobs.slice(
    displayedJobCount,
    displayedJobCount + JOB_PAGE_SIZE
  );

  nextJobs.forEach(job => {
    const jobCard = document.createElement("article");
    jobCard.className = "job-card";
    jobCard.id = `job-${job.id}`;
    jobCard.tabIndex = -1;
    jobCard.dataset.jobId = job.id;

    const isSaved = savedJobIds.has(job.id);
    const isTracked = trackedJobIds.has(job.id);
    const applicationDeadline =
      job.application_deadline
      || (
        job.expires_at
          ? String(job.expires_at).slice(0, 10)
          : null
      );
    const deadlinePassed =
      applicationDeadlineHasPassed(applicationDeadline);
    const responseDays = getEmployerResponseDays(job);
    const isReported = reportedJobIds.has(job.id);
    const linkUnavailable = job.link_status === "unavailable";
    const viewState = getJobViewState(job);

    const officialListingUrl = job.source_url || job.application_url;
    const detailsId = `job-details-${job.id}`;

    jobCard.innerHTML = `
      <div class="job-card-heading">
        <div class="job-card-title-group">
          <h3>${escapeEmployerHtml(job.title)}</h3>
          <p class="job-card-company"><a href="company.html?name=${encodeURIComponent(job.company)}">${escapeEmployerHtml(job.company)}</a></p>
        </div>

        <div class="job-card-heading-controls">
          ${(() => {
            const eligibility = getTeenEligibilityBadge(job);
            return eligibility ? `<span class="job-highlight-badge teen-friendly-badge ${escapeEmployerHtml(eligibility.className || "")}" title="${escapeEmployerHtml(eligibility.title)}">${escapeEmployerHtml(eligibility.label)}</span>` : "";
          })()}
          ${viewState.changed ? `<span class="job-highlight-badge changed-job-badge">Changed since viewed</span>` : viewState.viewed ? `<span class="job-highlight-badge viewed-job-badge">Viewed</span>` : ""}
          ${jobWasRecentlyPosted(job) ? `
            <span class="job-highlight-badge new-job-badge">New</span>
          ` : ""}
          ${job.application_method === "pathforge" ? `
            <span class="job-highlight-badge easy-apply-badge">
              Easily Apply
            </span>
          ` : ""}
          ${hasJobAccommodationInformation(job) ? `
            <span class="job-highlight-badge accommodation-info-badge" title="The employer posting mentions application or hiring accommodations.">
              Accommodation Info
            </span>
          ` : ""}
          ${getJobApplicationFeatures(job).no_cover_letter ? `
            <span class="job-highlight-badge no-cover-letter-badge">No Cover Letter Required</span>
          ` : ""}
          ${getJobApplicationFeatures(job).accommodation_contact ? `
            <span class="job-highlight-badge accommodation-contact-badge">Accommodation Contact Mentioned</span>
          ` : ""}
          ${getJobApplicationFeatures(job).additional_steps ? `
            <span class="job-highlight-badge application-steps-badge" title="The posting mentions an assessment, work sample, background check, or similar step.">Additional Steps Mentioned</span>
          ` : ""}
          ${responseDays ? `
            <span class="job-highlight-badge response-time-badge">
              Often replies in ${responseDays}
              ${responseDays === 1 ? "day" : "days"}
            </span>
          ` : ""}
          ${job.application_method === "employer_website" ? `
            <span class="external-job-badge">Employer Website</span>
          ` : ""}
          <span class="job-trust-badge ${getJobTrustBadgeClass(job)}">
            ${escapeEmployerHtml(job.trust_label || "Limited Verification")}
          </span>
          ${job.duplicate_count > 1 ? `<span class="job-highlight-badge duplicate-job-badge">${job.duplicate_count} matching listings grouped</span>` : ""}

          <button
            type="button"
            class="save-job-button ${isSaved ? "saved" : ""}"
            data-action="save-job"
            data-job-id="${job.id}"
            aria-pressed="${isSaved}"
            aria-label="${isSaved ? "Remove saved job" : "Save job"}"
            title="${isSaved ? "Remove saved job" : "Save job"}"
          >
            ${buildBookmarkIcon(isSaved)}
          </button>
        </div>
      </div>

      <dl class="job-card-metadata">
        <div>
          <dt>Location</dt>
          <dd>${buildJobLocationMarkup(job.location, job)}</dd>
        </div>
        <div>
          <dt>Work setting</dt>
          <dd>${getJobWorkSetting(job)}</dd>
        </div>
        <div>
          <dt>Job type</dt>
          <dd>${escapeEmployerHtml(formatJobTypeDisplay(job.employment_type || job.schedule))}</dd>
        </div>
        <div>
          <dt>${getJobPayLabel(job)}</dt>
          <dd>${escapeEmployerHtml(formatJobSalary(job))}</dd>
        </div>
      </dl>

      ${(() => {
        const qualificationPreview = buildQualificationPreview(job);
        return `<div class="job-qualification-preview">
          <strong>Key qualifications</strong>
          <ul>${qualificationPreview.items.map(item => `<li>${escapeEmployerHtml(item)}</li>`).join("")}</ul>
          ${qualificationPreview.hasMore ? `<p>Additional requirements are in the full details.</p>` : ""}
        </div>`;
      })()}

      ${linkUnavailable ? `
        <div class="job-link-warning" role="status">
          The official application link was marked unavailable during its
          latest check. Confirm the role on the employer's careers page.
        </div>
      ` : ""}

      ${buildJobSafetySignals(job)}

      <details class="job-understanding-details">
        <summary>Understand this job</summary>
        <p class="job-understanding-introduction">Review why this job appeared, what information is available, and how it compares with your preferences.</p>
        ${buildOpportunityFitSnapshot(job)}
        ${buildWhyThisResult(job)}
        ${buildJobQualityDetails(job)}
        ${buildJobTrustDetails(job)}
        ${buildJobEvidenceDetails(job)}
      </details>

      ${applicationDeadline ? `
        <p class="job-application-deadline">
          <strong>Apply by:</strong>
          ${escapeEmployerHtml(
            formatApplicationDeadline(applicationDeadline)
          )}
        </p>
      ` : ""}

      <div id="${detailsId}" class="job-details hidden">
        <section>
          <h4>Description</h4>
          <p>${escapeEmployerHtml(cleanJobPostingText(job.description))}</p>
        </section>

        <section>
          <h4>Requirements</h4>
          <p>${escapeEmployerHtml(
            cleanJobPostingText(job.requirements)
            || (
              job.application_method === "employer_website"
                ? "Review the official employer posting for complete required qualifications."
                : "No additional requirements were provided."
            )
          )}</p>
        </section>

        <section>
          <h4>Preferred qualifications</h4>
          <p>${escapeEmployerHtml(
            cleanJobPostingText(job.preferred_qualifications)
            || "No preferred qualifications were provided."
          )}</p>
        </section>

        <div class="job-details-secondary">
          <p><strong>Experience:</strong> ${escapeEmployerHtml(job.experience)}</p>
          <p><strong>Category:</strong> ${escapeEmployerHtml(job.category)}</p>
          <p><strong>Application:</strong> ${getJobApplicationMethod(job)}</p>
          <p><strong>Posted:</strong> ${formatJobCardDate(job.posted_at || job.created_at)}</p>
          ${job.last_verified_at ? `<p class="job-verification-date"><strong>Source checked:</strong> ${formatJobCardDate(job.last_verified_at)}. Confirm availability before applying.</p>` : ""}
        </div>

        ${job.application_method === "employer_website" && officialListingUrl ? `
          <a
            class="official-listing-link"
            href="${escapeEmployerHtml(officialListingUrl)}"
            target="_blank"
            rel="noopener noreferrer"
          >
            View Official Listing
          </a>
        ` : ""}
      </div>

      <div class="job-card-actions">
        <button
          type="button"
          class="apply-job-button ${isTracked ? "tracked" : ""}"
          data-action="begin-application"
          data-job-id="${job.id}"
          ${isTracked || deadlinePassed || linkUnavailable ? "disabled" : ""}
        >
          ${
            isTracked
              ? "In Tracker"
              : deadlinePassed
                ? "Deadline Passed"
                : linkUnavailable
                  ? "Link Unavailable"
                : "Apply"
          }
        </button>

        <button
          type="button"
          class="job-details-button"
          data-action="toggle-job-details"
          aria-expanded="false"
          aria-controls="${detailsId}"
        >
          View Details
        </button>

        <details class="job-secondary-actions">
          <summary aria-label="More actions for ${escapeEmployerHtml(job.title)}">More</summary>
          <div class="job-secondary-actions-menu">
            <label class="compare-job-control"><input type="checkbox" data-action="compare-job" data-job-id="${job.id}" ${comparedJobIds.has(Number(job.id)) ? "checked" : ""}><span>Compare job</span></label>
            <a class="tailor-resume-button" href="resume.html?job=${job.id}">Review résumé</a>
            <button
              type="button"
              class="report-job-button ${isReported ? "reported" : ""}"
              data-action="report-job"
              data-job-id="${job.id}"
              ${isReported ? "disabled" : ""}
            >
              ${isReported ? "Reported" : "Report Listing"}
            </button>
            <button
              type="button"
              class="not-interested-job-button"
              data-action="hide-job"
              data-job-id="${job.id}"
              aria-label="Hide ${escapeEmployerHtml(job.title)} from your results"
            >
              Not Interested
            </button>
          </div>
        </details>
      </div>

    `;

    jobListings.appendChild(jobCard);
  });

  displayedJobCount += nextJobs.length;
  if (resultCount) {
    resultCount.textContent =
      `${jobSearchTotal} job${jobSearchTotal === 1 ? "" : "s"} found`
      + (jobCatalogLoading ? " · refreshing…" : "");
  }
  if (loadMoreButton) {
    const reachedEnd = displayedJobCount >= jobs.length && !jobSearchHasMore;
    const remainingCount = Math.max(0, jobSearchTotal - displayedJobCount);
    const nextBatchCount = Math.min(JOB_PAGE_SIZE, remainingCount);
    loadMoreButton.classList.remove("hidden");
    loadMoreButton.classList.toggle("results-complete", reachedEnd);
    loadMoreButton.disabled = reachedEnd;
    loadMoreButton.removeAttribute("aria-busy");
    loadMoreButton.textContent = reachedEnd
      ? `No more listings — all ${jobSearchTotal} shown`
      : `Load ${nextBatchCount} more job${nextBatchCount === 1 ? "" : "s"} (${remainingCount} remaining)`;
    if (endMessage) {
      endMessage.classList.add("hidden");
    }
  }
}

function populateSelect(selectId, jobs, field, label) {
  const select = document.getElementById(selectId);
  if (!select) return;
  select.innerHTML = `<option value="all">${label}</option>`;
  const values = [...new Set(
    jobs.map(job => job[field]).filter(Boolean)
  )].sort();
  values.forEach(value => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  });
}

function populateJobFilters(jobs) {
  populateSelect("categoryFilter", jobs, "category", "All Job Fields");
}

function populateJobCategories(categories) {
  const select = document.getElementById("categoryFilter");
  if (!select) return;
  const selected = select.value;
  select.innerHTML = '<option value="all">All Job Fields</option>';
  categories.forEach(value => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  });
  if ([...select.options].some(option => option.value === selected)) {
    select.value = selected;
  }
}

function normalizeEmploymentSchedule(value) {
  const normalized = String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[\s_]+/g, "-");
  if (["full-time", "fulltime"].includes(normalized)) return "full-time";
  if (["part-time", "parttime", "12-39-hours-per-week"].includes(normalized)) {
    return "part-time";
  }
  return "";
}

function normalizeExperienceLevel(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (/entry|no experience/.test(normalized)) return "entry-level";
  if (/experienced/.test(normalized)) return "experienced";
  return "";
}

function getJobExperienceGroup(job) {
  const statedLevel = normalizeExperienceLevel(job.experience);
  if (statedLevel) return statedLevel;
  const title = String(job.title || "").toLowerCase();
  const details = [job.title, job.experience, job.requirements, job.description]
    .map(value => String(value || "").toLowerCase())
    .join(" ");
  if (/\b(?:intern(?:ship)?|apprentice|trainee|junior|entry[ -]?level|student|no experience|crew member|team member|cashier|customer service rep(?:resentative)?|pizza maker)\b/i.test(details)) {
    return "entry-level";
  }
  if (/\b(?:senior|sr\.?|manager|supervisor|director|lead|principal|chief|engineer|analyst|specialist|consultant|architect|attorney|counsel|accountant|registered|licensed|certification required|bachelor'?s|master'?s|doctorate|[1-9]\+? years?|one or more years|two or more years)\b/i.test(details)) {
    return "experienced";
  }
  if (/see (?:published|official) (?:qualifications|eligibility requirements)/i.test(String(job.experience || "")) && !/\b(?:assistant|associate|aide|support|representative|coordinator)\b/i.test(title)) {
    return "experienced";
  }
  return "";
}

function balanceStarterAndExperiencedJobs(jobs, experienceFilter, ageFilter) {
  if (experienceFilter !== "all" || ageFilter !== "all") return jobs;
  const starter = [];
  const experienced = [];
  const other = [];
  jobs.forEach(job => {
    const group = getJobExperienceGroup(job);
    if (group === "entry-level") starter.push(job);
    else if (group === "experienced") experienced.push(job);
    else other.push(job);
  });
  const balanced = [];
  const longest = Math.max(starter.length, experienced.length);
  for (let index = 0; index < longest; index += 1) {
    if (starter[index]) balanced.push(starter[index]);
    if (experienced[index]) balanced.push(experienced[index]);
  }
  return balanced.concat(other);
}

async function loadCompleteJobDetails(jobCard, button) {
  const jobId = Number(jobCard.dataset.jobId);
  const job = allJobs.find(item => Number(item.id) === jobId);
  if (!job?.details_truncated) return true;

  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "Loading Details…";
  try {
    const response = await fetch(apiUrl(`/jobs/${jobId}`));
    if (!response.ok) throw new Error("Complete job details could not be loaded.");
    const completeJob = await response.json();
    Object.assign(job, completeJob, { details_truncated: false });
    const detailParagraphs = jobCard.querySelectorAll(".job-details > section > p");
    if (detailParagraphs[0]) {
      detailParagraphs[0].textContent = cleanJobPostingText(job.description);
    }
    if (detailParagraphs[1]) {
      detailParagraphs[1].textContent = cleanJobPostingText(job.requirements)
        || (job.application_method === "employer_website"
          ? "Review the official employer posting for complete required qualifications."
          : "No additional requirements were provided.");
    }
    if (detailParagraphs[2]) {
      detailParagraphs[2].textContent = cleanJobPostingText(job.preferred_qualifications)
        || "No preferred qualifications were provided.";
    }
    return true;
  } catch (error) {
    showJobSaveToast(error.message, "error");
    return false;
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

async function toggleDetails(button) {
  const jobCard = button.closest(".job-card");
  const details = jobCard.querySelector(".job-details");

  if (details.classList.contains("hidden")) {
    const loaded = await loadCompleteJobDetails(jobCard, button);
    if (!loaded) return;
  }

  details.classList.toggle("hidden");

  if (details.classList.contains("hidden")) {
    button.textContent = "View Details";
    button.setAttribute("aria-expanded", "false");
  } else {
    markJobViewed(jobCard.dataset.jobId);
    button.textContent = "Hide Details";
    button.setAttribute("aria-expanded", "true");
  }
}

function buildBookmarkIcon(isSaved) {
  // The visible control is icon-only; its button supplies the accessible label and pressed state.
  return `
    <svg
      class="bookmark-icon"
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M6 3.75A1.75 1.75 0 0 1 7.75 2h8.5A1.75 1.75 0 0 1 18 3.75v17.1a.65.65 0 0 1-1.04.52L12 17.65l-4.96 3.72A.65.65 0 0 1 6 20.85V3.75Z"
        ${isSaved ? 'fill="currentColor"' : 'fill="none"'}
        stroke="currentColor"
        stroke-width="2.2"
        stroke-linejoin="round"
      />
    </svg>
  `;
}

function updateBookmarkButton(button, isSaved) {
  button.classList.toggle("saved", isSaved);
  button.setAttribute("aria-pressed", String(isSaved));
  button.setAttribute(
    "aria-label",
    isSaved ? "Remove saved job" : "Save job"
  );
  button.title = isSaved ? "Remove saved job" : "Save job";
  button.innerHTML = buildBookmarkIcon(isSaved);
}

let jobSaveToastTimer = null;

function showJobSaveToast(text, type = "success") {
  let toast = document.getElementById("jobSaveToast");

  if (!toast) {
    toast = document.createElement("div");
    toast.id = "jobSaveToast";
    toast.className = "job-save-toast";
    toast.setAttribute("role", "status");
    toast.setAttribute("aria-live", "polite");
    document.body.appendChild(toast);
  }

  window.clearTimeout(jobSaveToastTimer);
  toast.textContent = text;
  toast.className = `job-save-toast ${type} visible`;

  jobSaveToastTimer = window.setTimeout(() => {
    toast.classList.remove("visible");
  }, 2400);
}

// Bookmark state changes only after the API confirms the account mutation.
async function saveJob(jobId, button) {
  const isSaved = savedJobIds.has(jobId);

  button.disabled = true;
  button.classList.add("loading");
  button.setAttribute(
    "aria-label",
    isSaved ? "Removing saved job" : "Saving job"
  );

  try {
    const response = await fetch(
      apiUrl(`/saved-jobs/${jobId}`),
      {
        method: isSaved ? "DELETE" : "POST",
        credentials: "include"
      }
    );

    if (response.status === 401) {
      window.location.href = "login.html";
      return;
    }

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        data.detail || (
          isSaved
            ? "The job could not be removed from saved jobs."
            : "The job could not be saved."
        )
      );
    }

    if (isSaved) {
      savedJobIds.delete(jobId);
      updateBookmarkButton(button, false);
      showJobSaveToast("Job removed from saved jobs.");
    } else {
      savedJobIds.add(jobId);
      updateBookmarkButton(button, true);
      showJobSaveToast("Job saved.");
    }

    button.classList.remove("loading");
    button.disabled = false;

  } catch (error) {
    console.error("Save job failed:", error);

    updateBookmarkButton(button, isSaved);
    button.classList.remove("loading");
    button.disabled = false;
    showJobSaveToast(error.message, "error");
  }
}

const ApplicationService = {
  begin(jobId) {
    const job = allJobs.find(
      currentJob => currentJob.id === jobId
    );

    if (!job) {
      return;
    }

    activeApplicationJob = job;

    if (
      job.application_method === "employer_website"
    ) {
      this.showEmployerWebsiteDialog(job);
      return;
    }

    this.showPathForgeDialog(job);
  },

    async showPathForgeDialog(job) {
    if (job.employer_id == null) {
      this.showLegacyPathForgeDialog(job);
      return;
    }

    openApplicationDialog(
      `Apply to ${job.company}`,
      "Loading the employer's application form...",
      ""
    );

    try {
      const response = await fetch(
        apiUrl(`/jobs/${job.id}/application-form`),
        {
          credentials: "include"
        }
      );

      if (response.status === 401) {
        window.location.href = "login.html";
        return;
      }

      const data = await response.json();

      if (!response.ok) {
        let errorMessage =
          "The application form could not be loaded.";

        if (typeof data.detail === "string") {
          errorMessage = data.detail;
        } else if (Array.isArray(data.detail)) {
          errorMessage = data.detail
            .map(error => {
              return error.msg || "Invalid request.";
            })
            .join(" ");
        }

        throw new Error(errorMessage);
      }

      this.renderInternalApplicationForm(
        data.questions || []
      );

    } catch (error) {
      console.error(
        "Internal application form load failed:",
        error
      );

      showApplicationDialogMessage(
        error.message,
        "error"
      );
    }
  },


  showLegacyPathForgeDialog(job) {
    openApplicationDialog(
      `Track ${job.title}`,
      `
        This is a legacy PathForge listing without an
        employer-created application form.

        You can add it to your Application Tracker so you
        do not lose your place.
      `,
      `
        <button
          type="button"
          data-action="track-application-interest"
        >
          Add to Tracker
        </button>

        <button
          type="button"
          class="secondary-dialog-button"
          data-action="close-application-dialog"
        >
          Not Now
        </button>
      `
    );
  },


  renderInternalApplicationForm(questions) {
    const dialogText =
      document.getElementById(
        "applicationDialogText"
      );

    const actions =
      document.getElementById(
        "applicationDialogActions"
      );

    const form =
      document.getElementById(
        "internalApplicationForm"
      );

    const questionContainer =
      document.getElementById(
        "internalApplicationQuestions"
      );

    if (
      !dialogText
      || !actions
      || !form
      || !questionContainer
    ) {
      return;
    }

    dialogText.textContent =
      "Complete the employer's application questions below.";

    actions.innerHTML = "";
    questionContainer.innerHTML = "";

    if (questions.length === 0) {
      questionContainer.innerHTML = `
        <div class="internal-application-empty">
          <p>
            This employer does not require any additional
            application questions.
          </p>
        </div>
      `;
    }

    questions.forEach((question, index) => {
      const field = document.createElement("div");

      field.className =
        "internal-application-field";

      const requiredText = question.is_required
        ? '<span class="required-indicator">*</span>'
        : '<span class="optional-indicator">Optional</span>';

      let inputMarkup = "";

      if (question.field_type === "long_text") {
        inputMarkup = `
          <textarea
            id="internal-answer-${question.id}"
            class="internal-application-answer"
            data-question-id="${question.id}"
            rows="5"
            maxlength="5000"
            ${question.is_required ? "required" : ""}
          ></textarea>
        `;
      } else if (question.field_type === "yes_no") {
        inputMarkup = `
          <select
            id="internal-answer-${question.id}"
            class="internal-application-answer"
            data-question-id="${question.id}"
            ${question.is_required ? "required" : ""}
          >
            <option value="">
              Select an answer
            </option>

            <option value="Yes">
              Yes
            </option>

            <option value="No">
              No
            </option>
          </select>
        `;
      } else {
        inputMarkup = `
          <input
            type="text"
            id="internal-answer-${question.id}"
            class="internal-application-answer"
            data-question-id="${question.id}"
            maxlength="5000"
            ${question.is_required ? "required" : ""}
          >
        `;
      }

      field.innerHTML = `
        <label for="internal-answer-${question.id}">
          <span class="internal-question-number">
            ${index + 1}.
          </span>

          ${escapeEmployerHtml(question.question_text)}
          ${requiredText}
        </label>

        ${inputMarkup}
      `;

      questionContainer.appendChild(field);
    });

    form.classList.remove("hidden");

    const firstAnswer = form.querySelector(
      ".internal-application-answer"
    );

    if (firstAnswer) {
      firstAnswer.focus();
    }
  },


  async submitInternalApplication(event) {
    event.preventDefault();

    if (!activeApplicationJob) {
      return;
    }

    const form =
      document.getElementById(
        "internalApplicationForm"
      );

    const submitButton =
      document.getElementById(
        "internalApplicationSubmitButton"
      );

    if (!form || !submitButton) {
      return;
    }

    const answerElements = form.querySelectorAll(
      ".internal-application-answer"
    );

    const answers = Array
      .from(answerElements)
      .map(element => {
        return {
          question_id:
            Number(element.dataset.questionId),

          answer_text:
            element.value.trim()
        };
      });

    submitButton.disabled = true;
    submitButton.textContent = "Submitting...";

    showApplicationDialogMessage(
      "Submitting your application...",
      ""
    );

    try {
      const response = await fetch(
        (
          apiUrl(`/jobs/`)
          + `${activeApplicationJob.id}/apply-internally`
        ),
        {
          method: "POST",

          headers: {
            "Content-Type": "application/json"
          },

          credentials: "include",

          body: JSON.stringify({
            answers: answers
          })
        }
      );

      if (response.status === 401) {
        window.location.href = "login.html";
        return;
      }

      const data = await response.json();

      if (!response.ok) {
        let errorMessage =
          "Your application could not be submitted.";

        if (typeof data.detail === "string") {
          errorMessage = data.detail;
        } else if (Array.isArray(data.detail)) {
          errorMessage = data.detail
            .map(error => {
              return error.msg || "Invalid answer.";
            })
            .join(" ");
        }

        throw new Error(errorMessage);
      }

      const submittedJobId =
        activeApplicationJob.id;

      trackedJobIds.add(submittedJobId);

      updateTrackedJobButton(
        submittedJobId
      );

      form.classList.add("hidden");

      const actions =
        document.getElementById(
          "applicationDialogActions"
        );

      if (actions) {
        actions.innerHTML = `
          <a
            href="applications.html"
            class="dialog-link-button"
          >
            View Application Tracker
          </a>

          <button
            type="button"
            class="secondary-dialog-button"
            data-action="close-application-dialog"
          >
            Close
          </button>
        `;
      }

      showApplicationDialogMessage(
        data.message
          || "Your application was submitted successfully.",
        "success"
      );

    } catch (error) {
      console.error(
        "Internal application submission failed:",
        error
      );

      showApplicationDialogMessage(
        error.message,
        "error"
      );

    } finally {
      submitButton.disabled = false;
      submitButton.textContent =
        "Submit Application";
    }
  },

  showEmployerWebsiteDialog(job) {
    openApplicationDialog(
      `Continue to ${job.company}`,
      `
        You are opening the employer's application page for
        ${job.title}.

        Some employer career sites begin with a large company banner,
        photo, or job-search header. If the job details are not visible
        right away, scroll down to reach the actual posting.

        The page will open in a new tab. PathForge can still track this
        application even though you apply on the employer's website.
        Return here afterward and tell us whether you completed it.
      `,
      `
        <button
          type="button"
          data-action="open-employer-website"
        >
          Open Employer Job Posting
        </button>

        <button
          type="button"
          class="secondary-dialog-button"
          data-action="close-application-dialog"
        >
          Cancel
        </button>
      `
    );
  },


  openEmployerWebsite() {
    if (
      !activeApplicationJob ||
      !isSafeExternalUrl(activeApplicationJob.application_url)
    ) {
      showApplicationDialogMessage(
        "This employer has not provided a valid application link.",
        "error"
      );

      return;
    }

    window.open(
      activeApplicationJob.application_url,
      "_blank",
      "noopener,noreferrer"
    );

    openApplicationDialog(
      "Did you finish applying?",
      `
        If you initially see a company banner or general careers header,
        scroll down on the employer's page to find the job posting.

        When you return, choose Yes, I Applied if you submitted the
        employer's application. PathForge will add it to Applications,
        where you can manage its status, interviews, notes, follow-ups,
        and history. If you are not finished, you can save it as Interested.
      `,
      `
        <button
          type="button"
          data-action="confirm-external-application"
        >
          Yes, I Applied
        </button>

        <button
          type="button"
          class="secondary-dialog-button"
          data-action="track-application-interest"
        >
          Not Yet, Save in Tracker
        </button>

        <button
          type="button"
          class="secondary-dialog-button"
          data-action="close-application-dialog"
        >
          Do Not Track
        </button>
      `
    );
  },


  async trackInterest() {
    await this.createTrackerEntry(
      "Interested",
      null
    );
  },


  async confirmExternalApplication() {
    const today = new Date()
      .toISOString()
      .slice(0, 10);

    await this.createTrackerEntry(
      "Applied",
      today
    );
  },


  async createTrackerEntry(status, appliedAt) {
    if (!activeApplicationJob) {
      return;
    }

    const message =
      document.getElementById(
        "applicationDialogMessage"
      );

    const actionButtons =
      document.querySelectorAll(
        "#applicationDialogActions button"
      );

    actionButtons.forEach(button => {
      button.disabled = true;
    });

    message.textContent = "Adding to tracker...";
    message.className = "application-dialog-message";

    const applicationMethod =
      activeApplicationJob.application_method ===
      "employer_website"
        ? "employer_website"
        : "pathforge";

    try {
      const response = await fetch(
        apiUrl("/applications"),
        {
          method: "POST",

          headers: {
            "Content-Type": "application/json"
          },

          credentials: "include",

          body: JSON.stringify({
            job_id: activeApplicationJob.id,
            application_method: applicationMethod,
            status: status,
            applied_at: appliedAt,
            interview_date: null,
            follow_up_date: null,
            notes: null
          })
        }
      );

      if (response.status === 401) {
        window.location.href = "login.html";
        return;
      }

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail ||
          "The application could not be tracked."
        );
      }

      trackedJobIds.add(activeApplicationJob.id);

      updateTrackedJobButton(
        activeApplicationJob.id
      );

      message.textContent = data.message;
      message.classList.add("success-message");

      setTimeout(() => {
        window.location.href =
          "applications.html";
      }, 900);

    } catch (error) {
      console.error(
        "Application tracking failed:",
        error
      );

      message.textContent = error.message;
      message.classList.add("error-message");

      actionButtons.forEach(button => {
        button.disabled = false;
      });
    }
  }
};

function isSafeExternalUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:";
  } catch (error) {
    return false;
  }
}

// One dialog supports PathForge-managed applications and recording applications
// completed on an employer's own website.
function openApplicationDialog(
  title,
  text,
  actions
) {
  const dialog =
    document.getElementById("applicationDialog");

  const titleElement =
    document.getElementById(
      "applicationDialogTitle"
    );

  const textElement =
    document.getElementById(
      "applicationDialogText"
    );

  const actionsElement =
    document.getElementById(
      "applicationDialogActions"
    );

  const message =
    document.getElementById(
      "applicationDialogMessage"
    );

  if (
    !dialog ||
    !titleElement ||
    !textElement ||
    !actionsElement ||
    !message
  ) {
    return;
  }

  titleElement.textContent = title;
  textElement.textContent = text.trim();
  actionsElement.innerHTML = actions;

  message.textContent = "";
  message.className =
    "application-dialog-message";

  dialog.classList.remove("hidden");
  dialog.setAttribute("aria-hidden", "false");
}


function closeApplicationDialog() {
  const dialog =
    document.getElementById("applicationDialog");

  if (!dialog) {
    return;
  }

  dialog.classList.add("hidden");
  dialog.setAttribute("aria-hidden", "true");

  activeApplicationJob = null;
}


function showApplicationDialogMessage(
  text,
  type
) {
  const message =
    document.getElementById(
      "applicationDialogMessage"
    );

  if (!message) {
    return;
  }

  message.textContent = text;

  message.classList.remove(
    "success-message",
    "error-message"
  );

  message.classList.add(
    type === "error"
      ? "error-message"
      : "success-message"
  );
}


function updateTrackedJobButton(jobId) {
  const jobCard = document.querySelector(
    `.job-card[data-job-id="${jobId}"]`
  );

  if (!jobCard) {
    return;
  }

  const applyButton =
    jobCard.querySelector(".apply-job-button");

  if (!applyButton) {
    return;
  }

  applyButton.textContent = "In Tracker";
  applyButton.classList.add("tracked");
  applyButton.disabled = true;
}

const US_STATE_CODE_TO_NAME = {
  AL: "alabama", AK: "alaska", AZ: "arizona", AR: "arkansas",
  CA: "california", CO: "colorado", CT: "connecticut", DE: "delaware",
  FL: "florida", GA: "georgia", HI: "hawaii", ID: "idaho",
  IL: "illinois", IN: "indiana", IA: "iowa", KS: "kansas",
  KY: "kentucky", LA: "louisiana", ME: "maine", MD: "maryland",
  MA: "massachusetts", MI: "michigan", MN: "minnesota",
  MS: "mississippi", MO: "missouri", MT: "montana", NE: "nebraska",
  NV: "nevada", NH: "new hampshire", NJ: "new jersey",
  NM: "new mexico", NY: "new york", NC: "north carolina",
  ND: "north dakota", OH: "ohio", OK: "oklahoma", OR: "oregon",
  PA: "pennsylvania", RI: "rhode island", SC: "south carolina",
  SD: "south dakota", TN: "tennessee", TX: "texas", UT: "utah",
  VT: "vermont", VA: "virginia", WA: "washington",
  WV: "west virginia", WI: "wisconsin", WY: "wyoming",
  DC: "district of columbia"
};

const NON_US_LOCATION_MARKERS = [
  "australia", "austria", "belgium", "brazil", "canada", "colombia",
  "denmark", "finland", "france", "germany", "india", "ireland",
  "israel", "italy", "japan", "mexico", "netherlands", "norway",
  "philippines", "poland", "portugal", "romania", "singapore", "spain",
  "sweden", "switzerland", "united kingdom"
];

function normalizeUnitedStatesLocation(location) {
  let normalizedLocation = String(location || "").trim().toLowerCase();

  Object.entries(US_STATE_CODE_TO_NAME).forEach(([code, stateName]) => {
    const stateCodePattern = new RegExp(
      `(^|[,;/]\\s*)${code.toLowerCase()}`
      + `(?=\\s+\\d{5}(?:-\\d{4})?\\b|\\s*(?:$|[,;/]))`,
      "g"
    );
    normalizedLocation = normalizedLocation.replace(
      stateCodePattern,
      `$1${stateName}`
    );
  });

  return normalizedLocation;
}

function normalizePlaceName(placeName) {
  return String(placeName || "")
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

async function loadUnitedStatesPlaceIndex() {
  if (usPlaceIndex && usPlaceLookup) return;

  const response = await fetch("us-places.json");

  if (!response.ok) {
    throw new Error("The nearby-location reference could not be loaded.");
  }

  const data = await response.json();
  usPlaceIndex = Array.isArray(data.places) ? data.places : [];
  usPlaceLookup = new Map();

  usPlaceIndex.forEach(([stateCode, placeName, latitude, longitude]) => {
    const key = `${stateCode}|${normalizePlaceName(placeName)}`;

    if (!usPlaceLookup.has(key)) {
      usPlaceLookup.set(key, {
        stateCode,
        placeName,
        latitude: Number(latitude),
        longitude: Number(longitude)
      });
    }
  });
}

function calculateMilesBetween(latitudeA, longitudeA, latitudeB, longitudeB) {
  const toRadians = degrees => degrees * Math.PI / 180;
  const earthRadiusMiles = 3958.8;
  const latitudeDelta = toRadians(latitudeB - latitudeA);
  const longitudeDelta = toRadians(longitudeB - longitudeA);
  const startLatitude = toRadians(latitudeA);
  const endLatitude = toRadians(latitudeB);
  const haversine =
    Math.sin(latitudeDelta / 2) ** 2
    + Math.cos(startLatitude)
      * Math.cos(endLatitude)
      * Math.sin(longitudeDelta / 2) ** 2;

  return 2 * earthRadiusMiles * Math.asin(Math.sqrt(haversine));
}

function findNearestUnitedStatesPlace(latitude, longitude) {
  let nearestPlace = null;
  let nearestDistance = Number.POSITIVE_INFINITY;

  usPlaceIndex.forEach(([stateCode, placeName, placeLatitude, placeLongitude]) => {
    const distance = calculateMilesBetween(
      latitude,
      longitude,
      Number(placeLatitude),
      Number(placeLongitude)
    );

    if (distance < nearestDistance) {
      nearestDistance = distance;
      nearestPlace = {
        stateCode,
        placeName,
        latitude: Number(placeLatitude),
        longitude: Number(placeLongitude)
      };
    }
  });

  return nearestPlace;
}

function findJobPlaceCoordinates(location) {
  const rawLocation = String(location || "").trim();
  const normalizedLocation = rawLocation.toLowerCase();
  let stateCode = "";

  Object.entries(US_STATE_CODE_TO_NAME).some(([code, stateName]) => {
    const codePattern = new RegExp(
      `(?:^|[,;/]\\s*)${code}`
      + `(?=\\s+\\d{5}(?:-\\d{4})?\\b|\\s*(?:$|[,;/]))`,
      "i"
    );

    if (codePattern.test(rawLocation) || normalizedLocation.includes(stateName)) {
      stateCode = code;
      return true;
    }

    return false;
  });

  if (!stateCode) return null;

  const placeName = normalizePlaceName(rawLocation.split(",")[0]);
  return usPlaceLookup?.get(`${stateCode}|${placeName}`) || null;
}

function getNearbyDistanceMiles() {
  const savedDistance = Number(
    opportunityFitProfile?.maximum_commute_distance
  );

  return savedDistance > 0 ? savedDistance : 25;
}

function updateJobLocationStatus(message, isError = false) {
  const status = document.getElementById("jobLocationStatus");

  if (!status) return;

  status.textContent = message;
  status.classList.toggle("location-error", isError);
}

function requestCurrentPosition(timeout = 30000, maximumAge = 300000) {
  return new Promise((resolve, reject) => {
    navigator.geolocation.getCurrentPosition(resolve, reject, {
      enableHighAccuracy: false,
      timeout,
      maximumAge
    });
  });
}

async function requestCurrentPositionWithRetry() {
  try {
    return await requestCurrentPosition();
  } catch (error) {
    if (error?.code === 1) {
      throw error;
    }

    updateJobLocationStatus(
      "Location received. Updating job results..."
    );
    return requestCurrentPosition(20000, 0);
  }
}

async function useCurrentJobLocation() {
  const button = document.getElementById("useCurrentLocationButton");
  const locationInput = document.getElementById("locationSearchInput");

  if (!button || !locationInput) return;

  if (!navigator.geolocation) {
    updateJobLocationStatus(
      "Location sharing is not supported by this browser.",
      true
    );
    return;
  }

  button.disabled = true;
  button.textContent = "Finding location...";
  updateJobLocationStatus(
    "Waiting for location permission. Your coordinates stay on this device."
  );

  try {
    await loadUnitedStatesPlaceIndex();
    const position = await requestCurrentPositionWithRetry();
    const latitude = position.coords.latitude;
    const longitude = position.coords.longitude;
    const nearestPlace = findNearestUnitedStatesPlace(latitude, longitude);

    if (!nearestPlace) {
      throw new Error("Your nearest U.S. area could not be identified.");
    }

    sharedJobLocation = { latitude, longitude };
    locationInput.value =
      `${nearestPlace.placeName}, ${nearestPlace.stateCode}`;

    const locationScope = document.getElementById("locationScopeFilter");
    if (locationScope) locationScope.value = "us";

    filterJobs();
    updateJobLocationStatus("");
  } catch (error) {
    sharedJobLocation = null;
    const permissionDenied = error?.code === 1;
    updateJobLocationStatus(
      permissionDenied
        ? "Location access was not allowed. Enter a city, state, or ZIP code instead."
        : "Your location could not be detected. Enter a city, state, or ZIP code instead.",
      true
    );
  } finally {
    button.disabled = false;
    button.textContent = "Use My Location";
  }
}

function isUnitedStatesJobLocation(location) {
  const normalizedLocation = String(location || "")
    .trim()
    .toLowerCase();

  if (!normalizedLocation) return false;

  if (
    /\b(united states|united states of america|usa|u\.s\.a\.?|u\.s\.)\b/i
      .test(normalizedLocation)
  ) {
    return true;
  }

  if (normalizedLocation.includes("canada")) {
    return false;
  }

  const stateCodes = Object.keys(US_STATE_CODE_TO_NAME);
  const stateCodePattern = new RegExp(
    `(?:^|[,;/]\\s*)(${stateCodes.join("|")})`
    + `(?=\\s+\\d{5}(?:-\\d{4})?\\b|\\s*(?:$|[,;/]))`,
    "i"
  );

  if (stateCodePattern.test(String(location || ""))) {
    return true;
  }

  if (
    NON_US_LOCATION_MARKERS.some(countryName =>
      normalizedLocation.includes(countryName)
    )
  ) {
    return false;
  }

  const stateNames = Object.values(US_STATE_CODE_TO_NAME);

  return stateNames.some(stateName =>
    normalizedLocation.includes(stateName)
  );
}

function isTeenFriendlyJob(job) {
  const title = String(job.title || "").toLowerCase();
  const details = [job.title, job.description, job.requirements, job.experience]
    .map(value => String(value || "").toLowerCase())
    .join(" ");
  const clearlyAllowsTeens = /\b(?:age 14|age 15|age 16|age 17|14 years old|15 years old|16 years old|17 years old|teen(?:ager)?s? welcome|high school student)\b/i.test(details);
  const commonStarterRole = /\b(?:cashier|crew member|team member|counter attendant|food service|host|hostess|busser|dishwasher|barista|ice cream|grocery|cart attendant|store associate|retail associate|sales associate|stock(?:er|ing)?|guest advocate|park attendant|recreation aide|lifeguard|camp counselor|tutor|pet sitter|dog walker|babysitter)\b/i.test(title);
  const adultOnlyRequirement = /\b(?:must be (?:18|19|20|21)|(?:18|19|20|21)\+|at least (?:18|19|20|21)|bachelor'?s|master'?s|doctorate|professional license|driver'?s license|cdl|security clearance|armed|alcohol|bartender|forklift|heavy machinery|[2-9]\+? years?|two or more years|three or more years)\b/i.test(details);
  const seniorRole = /\b(?:senior|sr\.?|manager|supervisor|director|engineer|registered|licensed|lead|principal|specialist|executive|accountant|analyst|technician)\b/i.test(title);
  const entryLevel = getJobExperienceGroup(job) === "entry-level";
  return !adultOnlyRequirement && !seniorRole && (getJobMinimumAge(job) <= 17 || clearlyAllowsTeens || (commonStarterRole && entryLevel));
}

function getJobMinimumAge(job) {
  const details = [job.description, job.requirements]
    .map(value => String(value || ""))
    .join(" ");
  const matches = [...details.matchAll(/\b(?:minimum age stated by employer:|at least|minimum age(?: is|:)?|must be)\s*(1[4-9]|2[01])\b/gi)];
  if (!matches.length) return Number.POSITIVE_INFINITY;
  return Math.min(...matches.map(match => Number(match[1])));
}

function getTeenEligibilityBadge(job) {
  if (job.age_label) {
    const confirmed = String(job.age_eligibility || "").startsWith("confirmed_");
    const adultOnly = job.age_eligibility === "confirmed_18_plus";
    return {
      label: job.age_label,
      className: adultOnly
        ? "age-adult-badge"
        : confirmed ? "age-confirmed-badge" : "age-estimated-badge",
      title: adultOnly
        ? "The official employer posting states that applicants must be at least 18."
        : confirmed
          ? "The official employer posting states this minimum age. Local work-hour and permit rules may still apply."
        : "The role appears suitable for a first job, but the employer did not state a minimum age. Confirm eligibility before applying."
    };
  }
  const minimumAge = getJobMinimumAge(job);
  if (minimumAge <= 17) {
    return {
      label: `Minimum age ${minimumAge}+`,
      className: "age-confirmed-badge",
      title: `The employer posting states a minimum age of ${minimumAge}. Confirm current requirements before applying.`
    };
  }
  if (!isTeenFriendlyJob(job)) return null;
  return {
    label: "Possible teen fit · Age not stated",
    className: "age-estimated-badge",
    title: "This appears to be a starter role, but the posting does not state a minimum age. Confirm eligibility with the employer."
  };
}

function jobMatchesApplicantAge(job, selectedAge) {
  if (selectedAge === "all" || selectedAge === "age-18-plus") return true;
  const statedMinimumAge = getJobMinimumAge(job);
  if (selectedAge === "age-14") return statedMinimumAge <= 14;
  if (selectedAge === "age-15") return statedMinimumAge <= 15;
  return statedMinimumAge <= 17 || isTeenFriendlyJob(job);
}

function clearDirectJobFocus() {
  const currentUrl = new URL(window.location.href);

  if (!currentUrl.searchParams.has("job")) return;

  currentUrl.searchParams.delete("job");
  window.history.replaceState(
    {},
    "",
    `${currentUrl.pathname}${currentUrl.search}${currentUrl.hash}`
  );
  document.querySelector(".alert-target-job")?.classList.remove(
    "alert-target-job"
  );
}

const JOB_SEARCH_SYNONYMS = {
  developer: ["developer", "engineer", "programmer", "software"],
  programmer: ["programmer", "developer", "engineer", "software"],
  cashier: ["cashier", "checkout", "front end", "guest advocate"],
  restaurant: ["restaurant", "food service", "crew member", "team member", "server", "cook", "barista"],
  warehouse: ["warehouse", "fulfillment", "picker", "packer", "material handler", "stocking"],
  remote: ["remote", "work from home"],
  receptionist: ["receptionist", "front desk", "administrative assistant"],
  support: ["support", "customer service", "customer care", "help desk"],
  sales: ["sales", "account executive", "business development"],
  healthcare: ["healthcare", "medical", "clinical", "patient care"],
  marketing: ["marketing", "content", "brand", "communications"]
};

function getJobSearchConcepts(query) {
  return String(query || "")
    .toLowerCase()
    .replace(/[^a-z0-9+#.-]+/g, " ")
    .split(/\s+/)
    .filter(term => term && !["job", "jobs", "role", "roles", "position", "positions", "work"].includes(term))
    .map(term => JOB_SEARCH_SYNONYMS[term] || [term]);
}

function getJobSearchText(job) {
  return {
    title: String(job.title || "").toLowerCase(),
    company: String(job.company || "").toLowerCase(),
    category: String(job.category || "").toLowerCase(),
    details: [job.description, job.requirements, job.preferred_qualifications]
      .map(value => String(value || "").toLowerCase()).join(" ")
  };
}

function jobMatchesSearchConcepts(job, concepts) {
  if (!concepts.length) return true;
  const text = getJobSearchText(job);
  const allText = `${text.title} ${text.company} ${text.category} ${text.details}`;
  return concepts.every(alternatives => alternatives.some(term => allText.includes(term)));
}

function getJobRelevance(job, query, locationQuery) {
  const concepts = getJobSearchConcepts(query);
  const text = getJobSearchText(job);
  const normalizedQuery = String(query || "").trim().toLowerCase();
  let score = 0;
  const reasons = [];
  if (/\bcustomer (?:support|service)\b/.test(normalizedQuery) && /\bcustomer (?:service|support) (?:rep(?:resentative)?|associate|agent)\b/.test(text.title)) {
    score += 50;
    reasons.push("Customer-service role match");
  }
  if (/\bsoftware (?:developer|programmer|engineer)\b/.test(normalizedQuery) && /\bsoftware (?:developer|programmer|engineer)\b/.test(text.title)) {
    score += 40;
    reasons.push("Software role match");
  }
  if (normalizedQuery && text.title === normalizedQuery) {
    score += 80;
    reasons.push("Exact job-title match");
  } else if (normalizedQuery && text.title.includes(normalizedQuery)) {
    score += 55;
    reasons.push("Strong job-title match");
  }
  let titleConceptMatches = 0;
  concepts.forEach(alternatives => {
    if (alternatives.some(term => text.title.includes(term))) titleConceptMatches += 1;
    else if (alternatives.some(term => text.company.includes(term))) score += 12;
    else if (alternatives.some(term => text.category.includes(term))) score += 8;
    else if (alternatives.some(term => text.details.includes(term))) score += 2;
  });
  if (titleConceptMatches) {
    score += titleConceptMatches * 18;
    reasons.push(`${titleConceptMatches} search term${titleConceptMatches === 1 ? "" : "s"} matched the title`);
  }
  if (locationQuery && normalizeUnitedStatesLocation(job.location).includes(locationQuery)) {
    score += 18;
    reasons.push("Location match");
  }
  const postedTime = Date.parse(job.posted_at || job.created_at || "");
  if (Number.isFinite(postedTime)) {
    const ageDays = Math.max(0, (Date.now() - postedTime) / 86400000);
    if (ageDays <= 7) { score += 10; reasons.push("Posted recently"); }
    else if (ageDays <= 30) score += 5;
  }
  if (job.verification_status === "verified") score += 7;
  if (job.salary_min != null || job.salary_max != null || (job.pay && job.pay !== "Not listed")) score += 3;
  job._relevanceScore = score;
  job._relevanceReasons = reasons.slice(0, 3);
  return score;
}

function getJobSortPay(job) {
  const maximum = Number(job.salary_max ?? job.salary_min);
  if (!Number.isFinite(maximum)) return -1;
  return job.salary_period === "hour" ? maximum * 2080 : maximum;
}

function getJobMinimumAnnualPay(job) {
  const minimum = Number(job.salary_min);
  if (!Number.isFinite(minimum)) return -1;
  const period = String(job.salary_period || "").toLowerCase();
  if (["hour", "hourly", "hr"].includes(period)) return minimum * 2080;
  if (["month", "monthly"].includes(period)) return minimum * 12;
  if (["week", "weekly"].includes(period)) return minimum * 52;
  return minimum;
}

function getJobRemoteEligibility(job) {
  if (getJobWorkSetting(job) !== "Remote") return "not-remote";
  const location = String(job.location || "").toLowerCase();
  if (/\b(?:worldwide|anywhere|global|all countries)\b/.test(location)) return "anywhere";
  return isUnitedStatesJobLocation(job.location) ? "us" : "restricted";
}

function jobMatchesStrictExclusions(job, exclusions, excludedTerms) {
  const title = String(job.title || "");
  const details = [job.title, job.company, job.description, job.requirements, job.preferred_qualifications].join(" ");
  if (excludedTerms.some(term => details.toLowerCase().includes(term))) return false;
  const patterns = {
    senior: /\b(?:senior|sr\.?|staff|principal|lead|manager|director|head|chief|vp|vice president)\b/i,
    staffing: /\b(?:staffing agency|staffing firm|recruiting agency|recruitment agency|third[- ]party recruiter)\b/i,
    commission: /\b(?:commission[- ]only|100% commission|commission based|independent contractor|1099)\b/i,
    clearance: /\b(?:security clearance|secret clearance|top secret|ts\/sci)\b/i,
    unpaid: /\b(?:unpaid|volunteer position|no compensation)\b/i
  };
  return ![...exclusions].some(name => patterns[name]?.test(name === "senior" ? title : details));
}

function sortJobResults(jobs, sortMode, query, locationQuery) {
  jobs.forEach(job => getJobRelevance(job, query, locationQuery));
  return [...jobs].sort((left, right) => {
    if (sortMode === "newest") return (Date.parse(right.posted_at || right.created_at || "") || 0) - (Date.parse(left.posted_at || left.created_at || "") || 0);
    if (sortMode === "pay-high") return getJobSortPay(right) - getJobSortPay(left);
    if (sortMode === "verified") return buildJobQualityReview(right).confirmed - buildJobQualityReview(left).confirmed || right._relevanceScore - left._relevanceScore;
    return right._relevanceScore - left._relevanceScore || (Date.parse(right.posted_at || right.created_at || "") || 0) - (Date.parse(left.posted_at || left.created_at || "") || 0);
  });
}

function renderActiveJobFilters(filters) {
  const container = document.getElementById("activeJobFilters");
  if (!container) return;
  const activeFilters = filters.filter(filter => filter.active);
  container.replaceChildren();
  const resetButton = document.getElementById("resetJobFiltersButton");
  if (resetButton) resetButton.disabled = activeFilters.length === 0;
  activeFilters.forEach(filter => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "active-job-filter-chip";
    button.textContent = `${filter.label} x`;
    button.setAttribute("aria-label", `Remove ${filter.label} filter`);
    button.addEventListener("click", () => {
      if (filter.checkboxName) {
        const checkbox = document.querySelector(`input[name="${filter.checkboxName}"][value="${filter.checkboxValue}"]`);
        if (checkbox) checkbox.checked = false;
      }
      const control = document.getElementById(filter.controlId);
      if (control) control.value = filter.defaultValue;
      if (filter.controlId === "locationSearchInput") sharedJobLocation = null;
      filterJobs();
    });
    container.appendChild(button);
  });
  const advancedFilterCount = document.getElementById("advancedFilterCount");
  if (advancedFilterCount) {
    const secondaryCount = activeFilters.filter(filter => ![
      "jobSearchInput",
      "locationSearchInput"
    ].includes(filter.controlId)).length;
    advancedFilterCount.hidden = secondaryCount === 0;
    advancedFilterCount.textContent = secondaryCount ? String(secondaryCount) : "";
    advancedFilterCount.setAttribute(
      "aria-label",
      `${secondaryCount} additional filter${secondaryCount === 1 ? "" : "s"} active`
    );
  }
}

function hideJobFromResults(jobId) {
  const numericJobId = Number(jobId);
  hiddenJobIds.add(numericJobId);
  localStorage.setItem("pathforgeHiddenJobs", JSON.stringify([...hiddenJobIds]));
  filterJobs();
  let toast = document.getElementById("jobSaveToast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "jobSaveToast";
    toast.setAttribute("role", "status");
    toast.setAttribute("aria-live", "polite");
    document.body.appendChild(toast);
  }
  window.clearTimeout(jobSaveToastTimer);
  toast.className = "job-save-toast success visible hidden-job-toast";
  toast.textContent = "Job hidden. You can restore hidden jobs under More filters.";
  jobSaveToastTimer = window.setTimeout(() => toast.classList.remove("visible"), 5000);
}

function restoreHiddenJobs() {
  hiddenJobIds.clear();
  localStorage.setItem("pathforgeHiddenJobs", "[]");
  filterJobs();
  showJobSaveToast("Hidden jobs restored.");
}

// All visible job filters converge here so counts, sorting, active chips, and
// pagination cannot drift out of sync.
function filterJobs(refreshFromServer = true) {
  clearDirectJobFocus();
  const jobSearchInput = document.getElementById("jobSearchInput");
  const locationSearchInput = document.getElementById("locationSearchInput");
  const locationScopeFilter =
    document.getElementById("locationScopeFilter");
  const categoryFilter = document.getElementById("categoryFilter");
  const jobSearchForm = document.getElementById("jobSearchForm");
  const employmentTypeFilter =
    document.getElementById("employmentTypeFilter");
  const remoteFilter = document.getElementById("remoteFilter");
  const experienceFilter = document.getElementById("experienceFilter");
  const ageFitFilter = document.getElementById("ageFitFilter");
  const datePostedFilter = document.getElementById("datePostedFilter");
  const listingQualityFilter = document.getElementById("listingQualityFilter");
  const applicationFeatureFilter = document.getElementById("applicationFeatureFilter");
  const locationMatchFilter = document.getElementById("locationMatchFilter");
  const remoteEligibilityFilter = document.getElementById("remoteEligibilityFilter");
  const minimumPayFilter = document.getElementById("minimumPayFilter");
  const excludeTermsFilter = document.getElementById("excludeTermsFilter");
  const jobSortSelect = document.getElementById("jobSortSelect");

  if (!jobSearchInput || !locationSearchInput || !categoryFilter) return;

  const jobSearch = jobSearchInput.value.toLowerCase();
  const locationSearch = normalizeUnitedStatesLocation(
    locationSearchInput.value
  );
  const selectedLocationScope = locationScopeFilter?.value || "us";
  const selectedCategory = categoryFilter.value;
  const selectedEmploymentType =
    employmentTypeFilter?.value || "all";
  const selectedRemote = remoteFilter?.value || "all";
  const selectedExperience = experienceFilter?.value || "all";
  const selectedAgeFit = ageFitFilter?.value || "all";
  const selectedDatePosted = datePostedFilter?.value || "all";
  const selectedListingQuality = listingQualityFilter?.value || "all";
  const selectedApplicationFeature = applicationFeatureFilter?.value || "all";
  const selectedLocationMatch = locationMatchFilter?.value || "nearby";
  const selectedRemoteEligibility = remoteEligibilityFilter?.value || "all";
  const minimumPay = Math.max(0, Number(minimumPayFilter?.value) || 0);
  const excludedTerms = String(excludeTermsFilter?.value || "").toLowerCase().split(",").map(term => term.trim()).filter(Boolean);
  const exclusions = new Set([...document.querySelectorAll('input[name="jobExclusion"]:checked')].map(input => input.value));
  const selectedSort = jobSortSelect?.value || "recommended";
  const teenGuidance = document.getElementById("teenJobFilterGuidance");
  if (teenGuidance) teenGuidance.hidden = !["age-14", "age-15", "age-16-17"].includes(selectedAgeFit);
  updateQuickJobPresetStates();
  scheduleJobSearchHistory({
    query: jobSearchInput.value.trim(),
    location: locationSearchInput.value.trim(),
    locationScope: selectedLocationScope,
    category: selectedCategory,
    employmentType: selectedEmploymentType,
    remote: selectedRemote,
    experience: selectedExperience,
    ageFit: selectedAgeFit
  });

  filteredJobs = allJobs.filter(job => {
    if (hiddenJobIds.has(Number(job.id))) return false;
    const matchesJob = jobMatchesSearchConcepts(job, getJobSearchConcepts(jobSearch));

    const normalizedJobLocation = normalizeUnitedStatesLocation(job.location);
    const matchesLocation = sharedJobLocation ? true : selectedLocationMatch === "exact" && locationSearch
      ? normalizedJobLocation === locationSearch || normalizedJobLocation.startsWith(`${locationSearch},`)
      : normalizedJobLocation.includes(locationSearch);
    let matchesNearbyDistance = true;

    if (sharedJobLocation) {
      if (job.is_remote === 1 && isUnitedStatesJobLocation(job.location)) {
        matchesNearbyDistance = true;
      } else {
        const jobCoordinates = findJobPlaceCoordinates(job.location);

        matchesNearbyDistance = Boolean(
          jobCoordinates
          && calculateMilesBetween(
            sharedJobLocation.latitude,
            sharedJobLocation.longitude,
            jobCoordinates.latitude,
            jobCoordinates.longitude
          ) <= getNearbyDistanceMiles()
        );
      }
    }
    const matchesLocationScope =
      selectedLocationScope === "all"
      || isUnitedStatesJobLocation(job.location);

    const matchesCategory =
      selectedCategory === "all" || job.category === selectedCategory;

    const matchesEmploymentType =
      selectedEmploymentType === "all"
      || normalizeEmploymentSchedule(job.employment_type || job.schedule)
        === selectedEmploymentType;
    const normalizedWorkSetting = getJobWorkSetting(job).toLowerCase().replace("-", "");
    const matchesRemote = selectedRemote === "all"
      || normalizedWorkSetting === selectedRemote;
    const remoteEligibility = getJobRemoteEligibility(job);
    const matchesRemoteEligibility = selectedRemoteEligibility === "all"
      || (selectedRemoteEligibility === "us" && ["us", "anywhere"].includes(remoteEligibility))
      || (selectedRemoteEligibility === "anywhere" && remoteEligibility === "anywhere");
    const matchesExperience =
      selectedExperience === "all"
      || getJobExperienceGroup(job) === selectedExperience;
    const matchesAgeFit = jobMatchesApplicantAge(job, selectedAgeFit);
    const postedAt = Date.parse(job.posted_at || job.created_at || "");
    const matchesDatePosted = selectedDatePosted === "all" || (Number.isFinite(postedAt) && postedAt >= Date.now() - Number(selectedDatePosted) * 86400000);
    const quality = buildJobQualityReview(job);
    const matchesListingQuality = selectedListingQuality === "all"
      || (selectedListingQuality === "pay" && (job.salary_min != null || job.salary_max != null || (job.pay && job.pay !== "Not listed")))
      || (selectedListingQuality === "deadline" && Boolean(job.application_deadline || job.expires_at))
      || (selectedListingQuality === "accommodation" && hasJobAccommodationInformation(job))
      || (selectedListingQuality === "complete" && quality.confirmed >= 6);
    const applicationFeatures = getJobApplicationFeatures(job);
    const matchesApplicationFeature = selectedApplicationFeature === "all"
      || applicationFeatures[selectedApplicationFeature] === true;
    const matchesMinimumPay = !minimumPay || getJobMinimumAnnualPay(job) >= minimumPay;
    const matchesExclusions = jobMatchesStrictExclusions(job, exclusions, excludedTerms);
    return (
      matchesJob
      && matchesLocation
      && matchesNearbyDistance
      && matchesLocationScope
      && matchesCategory
      && matchesEmploymentType
      && matchesRemote
      && matchesRemoteEligibility
      && matchesExperience
      && matchesAgeFit
      && matchesDatePosted
      && matchesListingQuality
      && matchesApplicationFeature
      && matchesMinimumPay
      && matchesExclusions
    );
  });

  filteredJobs = groupDuplicateJobs(filteredJobs);
  // The server already returns the complete catalog in the requested order,
  // including employer diversity. Only sort the temporary in-memory preview
  // while a fresh server search is being requested.
  if (refreshFromServer) {
    filteredJobs = sortJobResults(filteredJobs, selectedSort, jobSearch, locationSearch);
    if (selectedSort === "recommended" && !jobSearch) {
      filteredJobs = balanceStarterAndExperiencedJobs(
        filteredJobs,
        selectedExperience,
        selectedAgeFit
      );
    }
  }

  renderActiveJobFilters([
    { controlId: "jobSearchInput", defaultValue: "", label: `Search: ${jobSearchInput.value.trim()}`, active: Boolean(jobSearchInput.value.trim()) },
    { controlId: "locationSearchInput", defaultValue: "", label: `Location: ${locationSearchInput.value.trim()}`, active: Boolean(locationSearchInput.value.trim() || sharedJobLocation) },
    { controlId: "categoryFilter", defaultValue: "all", label: categoryFilter.selectedOptions[0]?.textContent || "Job field", active: selectedCategory !== "all" },
    { controlId: "employmentTypeFilter", defaultValue: "all", label: employmentTypeFilter?.selectedOptions[0]?.textContent || "Schedule", active: selectedEmploymentType !== "all" },
    { controlId: "remoteFilter", defaultValue: "all", label: remoteFilter?.selectedOptions[0]?.textContent || "Work setting", active: selectedRemote !== "all" },
    { controlId: "experienceFilter", defaultValue: "all", label: experienceFilter?.selectedOptions[0]?.textContent || "Experience", active: selectedExperience !== "all" },
    { controlId: "ageFitFilter", defaultValue: "all", label: ageFitFilter?.selectedOptions[0]?.textContent || "Age", active: selectedAgeFit !== "all" },
    { controlId: "datePostedFilter", defaultValue: "all", label: datePostedFilter?.selectedOptions[0]?.textContent || "Date posted", active: selectedDatePosted !== "all" },
    { controlId: "listingQualityFilter", defaultValue: "all", label: listingQualityFilter?.selectedOptions[0]?.textContent || "Details", active: selectedListingQuality !== "all" },
    { controlId: "applicationFeatureFilter", defaultValue: "all", label: applicationFeatureFilter?.selectedOptions[0]?.textContent || "Application", active: selectedApplicationFeature !== "all" },
    { controlId: "locationMatchFilter", defaultValue: "nearby", label: "Exact location only", active: selectedLocationMatch === "exact" },
    { controlId: "remoteEligibilityFilter", defaultValue: "all", label: remoteEligibilityFilter?.selectedOptions[0]?.textContent || "Remote eligibility", active: selectedRemoteEligibility !== "all" },
    { controlId: "minimumPayFilter", defaultValue: "", label: `Minimum pay: $${minimumPay.toLocaleString()}`, active: minimumPay > 0 },
    { controlId: "excludeTermsFilter", defaultValue: "", label: `Exclude: ${excludedTerms.join(", ")}`, active: excludedTerms.length > 0 },
    ...[...exclusions].map(value => ({ checkboxName: "jobExclusion", checkboxValue: value, label: `Exclude ${value}`, active: true }))
  ]);
  const restoreHiddenButton = document.getElementById("restoreHiddenJobsButton");
  if (restoreHiddenButton) {
    restoreHiddenButton.disabled = hiddenJobIds.size === 0;
    restoreHiddenButton.textContent = hiddenJobIds.size
      ? `Restore Hidden Jobs (${hiddenJobIds.size})`
      : "Restore Hidden Jobs";
  }

  if (refreshFromServer) jobCatalogLoading = true;
  displayJobs(filteredJobs);
  if (refreshFromServer) scheduleServerJobSearch();
}

function updateQuickJobPresetStates() {
  const activePresets = {
    "age-14": document.getElementById("ageFitFilter")?.value === "age-14",
    "age-15": document.getElementById("ageFitFilter")?.value === "age-15",
    teen: document.getElementById("ageFitFilter")?.value === "age-16-17",
    "first-job": document.getElementById("experienceFilter")?.value === "entry-level",
    "part-time": document.getElementById("employmentTypeFilter")?.value === "part-time",
    "pay-listed": document.getElementById("listingQualityFilter")?.value === "pay"
  };
  document.querySelectorAll("[data-job-preset]").forEach(button => {
    button.setAttribute(
      "aria-pressed",
      String(Boolean(activePresets[button.dataset.jobPreset]))
    );
  });
  const resetButton = document.getElementById("resetQuickJobPresetsButton");
  if (resetButton) resetButton.disabled = !Object.values(activePresets).some(Boolean);
}

function resetQuickJobPresets() {
  const quickPathControls = [
    "ageFitFilter",
    "experienceFilter",
    "employmentTypeFilter",
    "listingQualityFilter"
  ];
  quickPathControls.forEach(controlId => {
    const control = document.getElementById(controlId);
    if (control) control.value = "all";
  });
  filterJobs();
  document.querySelector("[data-job-preset]")?.focus();
}

function applyQuickJobPreset(preset) {
  const mappings = {
    "age-14": ["ageFitFilter", "age-14"],
    "age-15": ["ageFitFilter", "age-15"],
    teen: ["ageFitFilter", "age-16-17"],
    "first-job": ["experienceFilter", "entry-level"],
    "part-time": ["employmentTypeFilter", "part-time"],
    "pay-listed": ["listingQualityFilter", "pay"]
  };
  const mapping = mappings[preset];
  if (!mapping) return;
  const control = document.getElementById(mapping[0]);
  if (!control) return;
  control.value = control.value === mapping[1] ? "all" : mapping[1];
  filterJobs();
}

function getServerJobSearchParameters(offset = 0) {
  const parameters = new URLSearchParams({
    query: document.getElementById("jobSearchInput")?.value.trim() || "",
    location: sharedJobLocation ? "" : (document.getElementById("locationSearchInput")?.value.trim() || ""),
    location_scope: document.getElementById("locationScopeFilter")?.value || "us",
    location_mode: document.getElementById("locationMatchFilter")?.value || "nearby",
    category: document.getElementById("categoryFilter")?.value || "all",
    employment_type: document.getElementById("employmentTypeFilter")?.value || "all",
    remote: document.getElementById("remoteFilter")?.value || "all",
    remote_eligibility: document.getElementById("remoteEligibilityFilter")?.value || "all",
    experience: document.getElementById("experienceFilter")?.value || "all",
    age_fit: document.getElementById("ageFitFilter")?.value || "all",
    date_posted: document.getElementById("datePostedFilter")?.value || "all",
    listing_quality: document.getElementById("listingQualityFilter")?.value || "all",
    application_feature: document.getElementById("applicationFeatureFilter")?.value || "all",
    minimum_pay: document.getElementById("minimumPayFilter")?.value || "0",
    exclusions: [...document.querySelectorAll('input[name="jobExclusion"]:checked')].map(input => input.value).join(","),
    exclude_terms: document.getElementById("excludeTermsFilter")?.value || "",
    sort: document.getElementById("jobSortSelect")?.value || "recommended",
    limit: String(JOB_SEARCH_BATCH_SIZE),
    offset: String(offset)
  });
  return parameters;
}

async function runJobSearch(offset = 0, requestedDisplayCount = null) {
  const requestId = ++jobSearchRequestId;
  const previouslyDisplayed = displayedJobCount;
  jobCatalogLoading = true;
  try {
    const response = await fetchWithTimeout(
      apiUrl(`/jobs/search?${getServerJobSearchParameters(offset)}`),
      {},
      20000
    );
    if (!response.ok) throw new Error("Job search could not be completed.");
    const data = await response.json();
    if (requestId !== jobSearchRequestId) return;
    const knownIds = new Set(offset ? allJobs.map(job => Number(job.id)) : []);
    allJobs = offset ? allJobs.concat(data.jobs.filter(job => !knownIds.has(Number(job.id)))) : data.jobs;
    jobSearchTotal = data.total;
    jobSearchHasMore = data.has_more;
    populateJobCategories(data.categories || []);
    jobCatalogLoading = false;
    filterJobs(false);
    if (offset) {
      const target = Math.min(
        requestedDisplayCount ?? previouslyDisplayed + JOB_PAGE_SIZE,
        filteredJobs.length
      );
      while (displayedJobCount < target) displayJobs(filteredJobs, true);
    }
  } catch (error) {
    if (requestId !== jobSearchRequestId) return;
    jobCatalogLoading = false;
    console.error("Job search failed:", error);
    const resultCount = document.getElementById("jobResultCount");
    if (resultCount) resultCount.textContent = "Job search could not be refreshed. Try again.";
    const loadMoreButton = document.getElementById("loadMoreJobsButton");
    if (offset && loadMoreButton) {
      loadMoreButton.disabled = false;
      loadMoreButton.removeAttribute("aria-busy");
      loadMoreButton.textContent = "Try loading more jobs";
    }
  }
}

function scheduleServerJobSearch() {
  window.clearTimeout(jobSearchTimer);
  jobSearchTimer = window.setTimeout(() => void runJobSearch(0), 250);
}

async function loadMoreJobResults() {
  if (jobCatalogLoading) return;
  const loadMoreButton = document.getElementById("loadMoreJobsButton");
  const requestedDisplayCount = Math.min(
    displayedJobCount + JOB_PAGE_SIZE,
    jobSearchTotal
  );

  if (displayedJobCount < filteredJobs.length) {
    displayJobs(filteredJobs, true);
  }

  if (displayedJobCount >= requestedDisplayCount || !jobSearchHasMore) return;
  if (loadMoreButton) {
    loadMoreButton.disabled = true;
    loadMoreButton.setAttribute("aria-busy", "true");
    loadMoreButton.textContent = "Loading more jobs…";
  }
  await runJobSearch(allJobs.length, requestedDisplayCount);
}

function applyNaturalJobSearch() {
  const input = document.getElementById("naturalJobSearchInput");
  const status = document.getElementById("naturalJobSearchStatus");
  if (!input || !status) return;
  const original = input.value.trim();
  const text = original.toLowerCase();
  status.className = "form-message";
  if (!text) {
    status.textContent = "Describe the kind of job you want first.";
    status.classList.add("error-message");
    return;
  }
  const applied = [];
  const employment = document.getElementById("employmentTypeFilter");
  const remote = document.getElementById("remoteFilter");
  const category = document.getElementById("categoryFilter");
  const experience = document.getElementById("experienceFilter");
  const ageFit = document.getElementById("ageFitFilter");
  const location = document.getElementById("locationSearchInput");
  const query = document.getElementById("jobSearchInput");
  if (/\bpart[ -]?time\b/.test(text)) { employment.value = "part-time"; applied.push("part-time"); }
  else if (/\bfull[ -]?time\b/.test(text)) { employment.value = "full-time"; applied.push("full-time"); }
  if (/\b(remote|work from home|work at home)\b/.test(text)) { remote.value = "remote"; applied.push("remote"); }
  else if (/\bhybrid\b/.test(text)) { remote.value = "hybrid"; applied.push("hybrid"); }
  else if (/\b(on[ -]?site|in person)\b/.test(text)) { remote.value = "onsite"; applied.push("on-site"); }
  if (/\b(age[ -]?14|14[ -]?year[ -]?old|14yo)\b/.test(text) && ageFit) {
    ageFit.value = "age-14";
    applied.push("jobs for age 14");
  } else if (/\b(age[ -]?15|15[ -]?year[ -]?old|15yo)\b/.test(text) && ageFit) {
    ageFit.value = "age-15";
    applied.push("jobs for age 15");
  } else if (/\b(age[ -]?(16|17)|(16|17)[ -]?year[ -]?old|(16|17)yo|teen|teenager|high school student|under 18|first job)\b/.test(text) && ageFit) {
    ageFit.value = "age-16-17";
    applied.push("jobs for ages 16–17");
  }
  const categoryPatterns = [
    ["Warehouse", /\b(warehouse|forklift|picker|packer|shipping|receiving|stocker|fulfillment)\b/],
    ["Customer Service", /\b(customer service|call center|customer support)\b/],
    ["Food Service", /\b(food service|restaurant|server|cook|barista)\b/],
    ["Retail", /\b(retail|cashier|store associate)\b/],
    ["Sales", /\b(sales|account executive)\b/],
    ["Healthcare", /\b(healthcare|nurse|medical|clinical|caregiver)\b/],
    ["Technology", /\b(technology|software|developer|programmer|cybersecurity|it support)\b/],
    ["Administrative", /\b(administrative|office assistant|receptionist)\b/]
  ];
  const matchedCategory = categoryPatterns.find(([, pattern]) => pattern.test(text));
  if (matchedCategory && [...category.options].some(option => option.value === matchedCategory[0])) {
    category.value = matchedCategory[0]; applied.push(matchedCategory[0]);
  }
  if (/\b(no experience|entry level|first job)\b/.test(text)) {
    const option = [...experience.options].find(item => /entry|no experience/i.test(item.textContent));
    if (option) { experience.value = option.value; applied.push(option.textContent.trim()); }
  }
  const locationMatch = original.match(/\b(?:in|near)\s+([^,.;]+?)(?=\s+(?:with|that|paying|and|for)\b|[,.;]|$)/i);
  if (locationMatch) { location.value = locationMatch[1].trim(); applied.push(`location: ${location.value}`); }
  const cleanedQuery = original
    .replace(/\b(?:full|part)[ -]?time\b/gi, "").replace(/\b(remote|work from home|work at home|hybrid|on[ -]?site|in person)\b/gi, "")
    .replace(/\b(?:for\s+(?:an?\s+)?)?(?:age[ -]?(?:14|15|16|17)|(?:14|15|16|17)[ -]?year[ -]?old|(?:14|15|16|17)yo|teen|teenager|high school student|under 18)\b/gi, "")
    .replace(/\b(?:jobs?|work|roles?|positions?)\b/gi, "").replace(/\b(?:in|near)\s+([^,.;]+?)(?=\s+(?:with|that|paying|and|for)\b|[,.;]|$)/gi, "")
    .replace(/\b(with|that|paying|at least|no experience|entry level|first job)\b.*$/gi, "").replace(/\s+/g, " ").trim();
  query.value = matchedCategory ? "" : cleanedQuery;
  if (cleanedQuery && !matchedCategory) applied.push(`keywords: ${cleanedQuery}`);
  const advancedFilters = document.querySelector(".advanced-job-filters");
  if (advancedFilters) advancedFilters.open = true;
  filterJobs();
  status.textContent = applied.length ? `Applied: ${applied.join(" · ")}. Review or change any filter above.` : "No dependable filter could be identified. Try including a job field, location, schedule, or work setting.";
  status.classList.add(applied.length ? "success-message" : "error-message");
}

let jobSearchHistoryTimer = null;

function scheduleJobSearchHistory(search) {
  if (!document.getElementById("jobSearchInput")) return;
  window.clearTimeout(jobSearchHistoryTimer);
  const hasUsefulFilter = search.query || search.location ||
    [search.category, search.employmentType, search.remote, search.experience, search.ageFit]
      .some(value => value && value !== "all");
  if (!hasUsefulFilter) return;
  jobSearchHistoryTimer = window.setTimeout(() => {
    const history = JSON.parse(localStorage.getItem("pathforgeJobSearchHistory") || "[]");
    const key = JSON.stringify(search);
    const entry = { ...search, key, searchedAt: new Date().toISOString() };
    const updated = [entry, ...history.filter(item => item.key !== key)].slice(0, 20);
    localStorage.setItem("pathforgeJobSearchHistory", JSON.stringify(updated));
  }, 700);
}

function applyJobSearchHistoryParameters() {
  const parameters = new URLSearchParams(window.location.search);
  const mappings = {
    q: "jobSearchInput", location: "locationSearchInput",
    scope: "locationScopeFilter", category: "categoryFilter",
    type: "employmentTypeFilter", remote: "remoteFilter",
    experience: "experienceFilter", age: "ageFitFilter"
  };
  Object.entries(mappings).forEach(([parameter, id]) => {
    let value = parameters.get(parameter);
    const control = document.getElementById(id);
    if (parameter === "type" && value && value !== "all") {
      value = normalizeEmploymentSchedule(value) || value;
    }
    if (parameter === "experience" && value && value !== "all") {
      value = normalizeExperienceLevel(value) || value;
    }
    if (
      value !== null
      && control
      && [...control.options || []].some(option => option.value === value)
    ) {
      control.value = value;
    }
  });
  const advancedFilters = document.querySelector(".advanced-job-filters");
  const advancedValues = ["scope", "category", "type", "remote", "experience"]
    .map(parameter => parameters.get(parameter))
    .filter(Boolean);
  if (
    advancedFilters
    && advancedValues.some(value => !["all", "us"].includes(String(value).toLowerCase()))
  ) {
    advancedFilters.open = true;
  }
}

function initializeSearchHistoryPage() {
  const list = document.getElementById("searchHistoryList");
  if (!list) return;
  const render = () => {
    const history = JSON.parse(localStorage.getItem("pathforgeJobSearchHistory") || "[]");
    list.replaceChildren();
    if (!history.length) {
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = "Your recent job searches will appear here automatically.";
      list.appendChild(empty);
      return;
    }
    history.forEach(search => {
      const card = document.createElement("article");
      card.className = "search-history-card";
      const title = document.createElement("h2");
      title.textContent = search.query || "Job search";
      const details = document.createElement("p");
      const parts = [search.location, search.category !== "all" ? search.category : "", search.remote !== "all" ? search.remote : ""].filter(Boolean);
      details.textContent = parts.join(" • ") || "All available jobs";
      const time = document.createElement("small");
      time.textContent = "Searched " + new Date(search.searchedAt).toLocaleString();
      const link = document.createElement("a");
      const params = new URLSearchParams();
      if (search.query) params.set("q", search.query);
      if (search.location) params.set("location", search.location);
      [["scope", search.locationScope], ["category", search.category], ["type", search.employmentType], ["remote", search.remote], ["experience", search.experience], ["age", search.ageFit]].forEach(([key, value]) => { if (value) params.set(key, value); });
      link.href = "jobs.html?" + params.toString();
      link.textContent = "Run this search again";
      card.append(title, details, time, link);
      list.appendChild(card);
    });
  };
  document.getElementById("clearSearchHistoryButton")?.addEventListener("click", () => {
    localStorage.removeItem("pathforgeJobSearchHistory");
    render();
  });
  render();
}

function resetJobFilters() {
  const textInputs = [
    "jobSearchInput",
    "locationSearchInput",
    "minimumPayFilter",
    "excludeTermsFilter"
  ];
  const selectFilters = [
    "locationScopeFilter",
    "locationMatchFilter",
    "categoryFilter",
    "employmentTypeFilter",
    "remoteFilter",
    "remoteEligibilityFilter",
    "experienceFilter",
    "ageFitFilter",
    "datePostedFilter",
    "listingQualityFilter",
    "applicationFeatureFilter",
    "jobSortSelect"
  ];

  textInputs.forEach(inputId => {
    const input = document.getElementById(inputId);
    if (input) input.value = "";
  });

  selectFilters.forEach(filterId => {
    const filter = document.getElementById(filterId);
    if (filter) {
      if (filterId === "locationScopeFilter") {
        filter.value = "us";
      } else if (filterId === "locationMatchFilter") {
        filter.value = "nearby";
      } else if (filterId === "jobSortSelect") {
        filter.value = "recommended";
      } else {
        filter.value = "all";
      }
    }
  });

  document.querySelectorAll('input[name="jobExclusion"]').forEach(input => {
    input.checked = false;
  });

  sharedJobLocation = null;
  const naturalInput = document.getElementById("naturalJobSearchInput");
  const naturalStatus = document.getElementById("naturalJobSearchStatus");
  if (naturalInput) naturalInput.value = "";
  if (naturalStatus) naturalStatus.textContent = "";
  updateJobLocationStatus("");

  filterJobs();

  const firstInput = document.getElementById("jobSearchInput");
  if (firstInput) firstInput.focus();
}

function getCurrentSavedSearchCriteria() {
  return {
    keyword: document.getElementById("jobSearchInput")?.value.trim() || "",
    location:
      document.getElementById("locationSearchInput")?.value.trim() || "",
    location_scope:
      document.getElementById("locationScopeFilter")?.value || "us",
    category: document.getElementById("categoryFilter")?.value || "all",
    employment_type:
      document.getElementById("employmentTypeFilter")?.value || "all",
    remote_filter:
      document.getElementById("remoteFilter")?.value || "all",
    experience:
      document.getElementById("experienceFilter")?.value || "all",
    location_mode:
      document.getElementById("locationMatchFilter")?.value || "nearby",
    remote_eligibility:
      document.getElementById("remoteEligibilityFilter")?.value || "all",
    age_fit: document.getElementById("ageFitFilter")?.value || "all",
    date_posted: document.getElementById("datePostedFilter")?.value || "all",
    listing_quality:
      document.getElementById("listingQualityFilter")?.value || "all",
    application_feature:
      document.getElementById("applicationFeatureFilter")?.value || "all",
    minimum_pay:
      Math.max(0, Number(document.getElementById("minimumPayFilter")?.value) || 0),
    exclusions: [...document.querySelectorAll('input[name="jobExclusion"]:checked')]
      .map(input => input.value).join(","),
    exclude_terms:
      document.getElementById("excludeTermsFilter")?.value.trim() || ""
  };
}

function describeSavedSearch(savedSearch) {
  const parts = [];

  if (savedSearch.keyword) parts.push(`Keyword: ${savedSearch.keyword}`);
  if (savedSearch.location) parts.push(`Location: ${savedSearch.location}`);
  if (savedSearch.category !== "all") parts.push(savedSearch.category);
  if (savedSearch.employment_type !== "all") {
    parts.push(savedSearch.employment_type);
  }
  if (savedSearch.remote_filter !== "all") {
    parts.push(savedSearch.remote_filter === "onsite" ? "On-site" : savedSearch.remote_filter);
  }
  if (savedSearch.location_mode === "exact") parts.push("Exact location");
  if (savedSearch.remote_eligibility === "us") parts.push("Remote from U.S.");
  if (savedSearch.remote_eligibility === "anywhere") parts.push("Remote worldwide");
  if (savedSearch.age_fit !== "all") parts.push(savedSearch.age_fit.replace("age-", "Age "));
  if (savedSearch.date_posted !== "all") parts.push(`Past ${savedSearch.date_posted} days`);
  if (savedSearch.listing_quality !== "all") parts.push(`${savedSearch.listing_quality} details`);
  if (savedSearch.application_feature && savedSearch.application_feature !== "all") {
    const labels = {
      direct_apply: "Apply directly in PathForge",
      no_cover_letter: "No cover letter required",
      accommodation_contact: "Accommodation contact mentioned"
    };
    parts.push(labels[savedSearch.application_feature] || savedSearch.application_feature);
  }
  if (Number(savedSearch.minimum_pay) > 0) parts.push(`$${Number(savedSearch.minimum_pay).toLocaleString()}+`);
  if (savedSearch.exclusions) parts.push(`Excludes ${savedSearch.exclusions.split(",").join(", ")}`);
  if (savedSearch.exclude_terms) parts.push(`Without: ${savedSearch.exclude_terms}`);
  if (savedSearch.experience !== "all") {
    parts.push(
      savedSearch.experience === "entry-level"
        ? "Entry Level or No Experience"
        : savedSearch.experience === "experienced"
          ? "Experienced"
          : savedSearch.experience
    );
  }
  if (!parts.length) parts.push("All current jobs");

  return parts.join(" · ");
}

function setSavedSearchStatus(message, isError = false) {
  const status = document.getElementById("savedSearchStatus");
  if (!status) return;
  status.textContent = message;
  status.classList.toggle("error-message", isError);
}

function renderSavedSearches() {
  const list = document.getElementById("savedSearchList");
  if (!list) return;

  if (!savedSearches.length) {
    list.innerHTML = `
      <p class="saved-search-empty">
        No saved searches yet. Set your filters, then save this search.
      </p>
    `;
    return;
  }

  list.innerHTML = savedSearches.map(savedSearch => `
    <article class="saved-search-card">
      <div class="saved-search-card-heading">
        <div>
          <h4>${escapeEmployerHtml(savedSearch.name)}</h4>
          <p>${escapeEmployerHtml(describeSavedSearch(savedSearch))}</p>
        </div>
        ${savedSearch.unread_count ? `
          <span class="saved-search-alert-badge">
            ${savedSearch.unread_count} new
          </span>
        ` : ""}
      </div>

      <div class="saved-search-settings">
        <label>
          Frequency
          <select
            aria-label="Alert frequency for ${escapeEmployerHtml(savedSearch.name)}"
            data-action="change-saved-search-frequency"
            data-search-id="${savedSearch.id}"
          >
            <option value="daily" ${savedSearch.frequency === "daily" ? "selected" : ""}>
              Daily
            </option>
            <option value="weekly" ${savedSearch.frequency === "weekly" ? "selected" : ""}>
              Weekly
            </option>
          </select>
        </label>

        <label class="saved-search-enabled-label">
          <input
            type="checkbox"
            ${savedSearch.is_enabled ? "checked" : ""}
            data-action="toggle-saved-search"
            data-search-id="${savedSearch.id}"
          >
          Alerts enabled
        </label>
      </div>

      <div class="saved-search-card-actions">
        <button type="button" data-action="check-saved-search" data-search-id="${savedSearch.id}">
          Check Now
        </button>
        <button type="button" data-action="view-saved-search" data-search-id="${savedSearch.id}">
          View Matches${savedSearch.match_count ? ` (${savedSearch.match_count})` : ""}
        </button>
        <button
          type="button"
          class="saved-search-delete"
          data-action="delete-saved-search"
          data-search-id="${savedSearch.id}"
        >
          Delete
        </button>
      </div>
    </article>
  `).join("");
}

async function loadSavedSearches() {
  const section = document.getElementById("savedSearchesSection");
  if (!section) return;

  try {
    const response = await fetch(
      apiUrl("/saved-searches"),
      { credentials: "include" }
    );

    if (response.status === 401) {
      section.classList.add("hidden");
      return;
    }

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Saved searches could not be loaded.");
    }

    savedSearches = data.saved_searches || [];
    section.classList.remove("hidden");
    renderSavedSearches();
  } catch (error) {
    section.classList.remove("hidden");
    setSavedSearchStatus(error.message, true);
  }
}

async function submitSavedSearch(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const nameInput = document.getElementById("savedSearchName");
  const frequency = document.getElementById("savedSearchFrequency")?.value;
  const submitButton = document.getElementById("saveSearchSubmitButton");
  const payload = {
    name: nameInput.value.trim(),
    frequency: frequency || "daily",
    is_enabled: true,
    ...getCurrentSavedSearchCriteria()
  };

  submitButton.disabled = true;
  setSavedSearchStatus("Saving your search...");

  try {
    const response = await fetch(apiUrl("/saved-searches"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "The search could not be saved.");
    }

    document.getElementById("saveSearchForm").classList.add("hidden");
    form.reset();
    setSavedSearchStatus(
      sharedJobLocation
        ? "Search saved using the displayed city and state. Device coordinates were not saved."
        : "Search saved. New matching jobs will follow your selected frequency."
    );
    await loadSavedSearches();
  } catch (error) {
    setSavedSearchStatus(error.message, true);
  } finally {
    submitButton.disabled = false;
  }
}

async function updateSavedSearch(savedSearchId, updates) {
  const savedSearch = savedSearches.find(item => item.id === savedSearchId);
  if (!savedSearch) return;
  const payload = { ...savedSearch, ...updates };

  const response = await fetch(
    apiUrl(`/saved-searches/${savedSearchId}`),
    {
      method: "PUT",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }
  );
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "The saved search could not be updated.");
  }
  return data.saved_search;
}

async function changeSavedSearchFrequency(savedSearchId, frequency) {
  try {
    await updateSavedSearch(savedSearchId, { frequency });
    setSavedSearchStatus(
      `Alert frequency changed to ${frequency}.`
    );
    await loadSavedSearches();
  } catch (error) {
    setSavedSearchStatus(error.message, true);
    await loadSavedSearches();
  }
}

async function toggleSavedSearch(savedSearchId, isEnabled) {
  try {
    await updateSavedSearch(savedSearchId, { is_enabled: isEnabled });
    setSavedSearchStatus(
      isEnabled ? "Job alerts enabled." : "Job alerts paused."
    );
    await loadSavedSearches();
  } catch (error) {
    setSavedSearchStatus(error.message, true);
    await loadSavedSearches();
  }
}

async function checkSavedSearch(savedSearchId) {
  setSavedSearchStatus("Checking for newly added matching jobs...");
  try {
    const response = await fetch(
      apiUrl(`/saved-searches/${savedSearchId}/check`),
      { method: "POST", credentials: "include" }
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "The saved search could not be checked.");
    }
    setSavedSearchStatus(
      data.new_matches
        ? `${data.new_matches} newly added matching job${data.new_matches === 1 ? "" : "s"} found.`
        : "No newly added matching jobs were found."
    );
    await loadSavedSearches();
  } catch (error) {
    setSavedSearchStatus(error.message, true);
  }
}

async function viewSavedSearchMatches(savedSearchId) {
  try {
    const response = await fetch(
      apiUrl(`/saved-searches/${savedSearchId}/matches`),
      { credentials: "include" }
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Matching jobs could not be loaded.");
    }

    filteredJobs = data.matches || [];
    jobSearchTotal = filteredJobs.length;
    jobSearchHasMore = false;
    displayJobs(filteredJobs);
    document.getElementById("jobListings")?.scrollIntoView({ block: "start" });

    await fetch(
      apiUrl(`/saved-searches/${savedSearchId}/mark-read`),
      { method: "POST", credentials: "include" }
    );
    setSavedSearchStatus(
      filteredJobs.length
        ? "Showing alert matches below."
        : "This saved search has no new-job matches yet."
    );
    await loadSavedSearches();
  } catch (error) {
    setSavedSearchStatus(error.message, true);
  }
}

async function deleteSavedSearch(savedSearchId) {
  if (!window.confirm("Delete this saved search and its job alerts?")) return;

  try {
    const response = await fetch(
      apiUrl(`/saved-searches/${savedSearchId}`),
      { method: "DELETE", credentials: "include" }
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "The saved search could not be deleted.");
    }
    setSavedSearchStatus("Saved search deleted.");
    await loadSavedSearches();
  } catch (error) {
    setSavedSearchStatus(error.message, true);
  }
}

function openJobReportDialog(jobId, triggerButton) {
  const dialog = document.getElementById("jobReportDialog");
  const form = document.getElementById("jobReportForm");
  const message = document.getElementById("jobReportMessage");
  if (!dialog || !form) return;

  activeReportJobId = jobId;
  activeReportTrigger = triggerButton;
  form.reset();
  message.textContent = "";
  message.classList.remove("error-message", "success-message");
  dialog.classList.remove("hidden");
  dialog.setAttribute("aria-hidden", "false");
  document.getElementById("jobReportReason")?.focus();
}

function closeJobReportDialog() {
  const dialog = document.getElementById("jobReportDialog");
  if (!dialog) return;

  dialog.classList.add("hidden");
  dialog.setAttribute("aria-hidden", "true");
  activeReportJobId = null;
  activeReportTrigger?.focus();
  activeReportTrigger = null;
}

async function submitJobReport(event) {
  event.preventDefault();
  if (!activeReportJobId) return;

  const submitButton = document.getElementById("submitJobReportButton");
  const message = document.getElementById("jobReportMessage");
  const reason = document.getElementById("jobReportReason").value;
  const details = document.getElementById("jobReportDetails").value.trim();
  submitButton.disabled = true;
  message.textContent = "Submitting your report...";
  message.classList.remove("error-message", "success-message");

  try {
    const response = await fetch(
      apiUrl(`/jobs/${activeReportJobId}/report`),
      {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason, details })
      }
    );
    const data = await response.json();

    if (response.status === 401) {
      window.location.href = "login.html";
      return;
    }
    if (!response.ok) {
      throw new Error(data.detail || "The report could not be submitted.");
    }

    reportedJobIds.add(activeReportJobId);
    if (activeReportTrigger) {
      activeReportTrigger.textContent = "Reported";
      activeReportTrigger.classList.add("reported");
      activeReportTrigger.disabled = true;
    }
    message.textContent = (
      "Report submitted. PathForge will treat it as a review request, not proof of wrongdoing."
    );
    message.classList.add("success-message");
    window.setTimeout(closeJobReportDialog, 1400);
  } catch (error) {
    message.textContent = error.message;
    message.classList.add("error-message");
    submitButton.disabled = false;
  }
}

window.onload = function() {
  applyJobSearchHistoryParameters();
  loadJobs();
  loadSavedSearches();

  const categoryFilter = document.getElementById("categoryFilter");
  const jobSearchForm = document.getElementById("jobSearchForm");
  const jobSearchInput = document.getElementById("jobSearchInput");
  const locationSearchInput = document.getElementById("locationSearchInput");
  const useCurrentLocationButton =
    document.getElementById("useCurrentLocationButton");
  const additionalFilters = [
    "locationScopeFilter",
    "employmentTypeFilter",
    "remoteFilter",
    "experienceFilter",
    "ageFitFilter",
    "datePostedFilter",
    "listingQualityFilter",
    "applicationFeatureFilter",
    "jobSortSelect"
  ];
  const loadMoreButton = document.getElementById("loadMoreJobsButton");
  const resetFiltersButton =
    document.getElementById("resetJobFiltersButton");
  const resetQuickPresetsButton =
    document.getElementById("resetQuickJobPresetsButton");
  const restoreHiddenJobsButton =
    document.getElementById("restoreHiddenJobsButton");
  const chatInput = document.getElementById("chatInput");
  const showSaveSearchFormButton =
    document.getElementById("showSaveSearchFormButton");
  const saveSearchForm = document.getElementById("saveSearchForm");
  const cancelSaveSearchButton =
    document.getElementById("cancelSaveSearchButton");
  const jobReportForm = document.getElementById("jobReportForm");
  const closeJobReportButton =
    document.getElementById("closeJobReportDialog");
  const jobReportDialog = document.getElementById("jobReportDialog");
  const naturalSearchButton = document.getElementById("naturalJobSearchButton");
  const naturalSearchInput = document.getElementById("naturalJobSearchInput");
  const comparisonDialog = document.getElementById("jobComparisonDialog");

  document.querySelectorAll("[data-job-preset]").forEach(button => {
    button.addEventListener(
      "click",
      () => applyQuickJobPreset(button.dataset.jobPreset)
    );
  });
  resetQuickPresetsButton?.addEventListener("click", resetQuickJobPresets);

  if (categoryFilter) {
    categoryFilter.addEventListener("change", filterJobs);
  }

  jobSearchForm?.addEventListener("submit", event => {
    event.preventDefault();
    filterJobs();
  });

  if (jobSearchInput) {
    jobSearchInput.addEventListener("input", filterJobs);
  }

  if (locationSearchInput) {
    locationSearchInput.addEventListener("input", () => {
      sharedJobLocation = null;
      updateJobLocationStatus("");
      filterJobs();
    });
  }

  if (useCurrentLocationButton) {
    useCurrentLocationButton.addEventListener(
      "click",
      useCurrentJobLocation
    );
  }

  additionalFilters.forEach(filterId => {
    const filter = document.getElementById(filterId);
    if (filter) filter.addEventListener(filter.tagName === "INPUT" ? "input" : "change", filterJobs);
  });
  document.querySelectorAll('input[name="jobExclusion"]').forEach(input => {
    input.addEventListener("change", filterJobs);
  });

  if (loadMoreButton) {
    loadMoreButton.addEventListener("click", () => void loadMoreJobResults());
  }

  if (resetFiltersButton) {
    resetFiltersButton.addEventListener("click", resetJobFilters);
  }
  if (restoreHiddenJobsButton) {
    restoreHiddenJobsButton.addEventListener("click", restoreHiddenJobs);
  }

  naturalSearchButton?.addEventListener("click", applyNaturalJobSearch);
  naturalSearchInput?.addEventListener("keydown", event => {
    if (event.key === "Enter") applyNaturalJobSearch();
  });
  document.getElementById("openJobComparisonButton")?.addEventListener("click", openJobComparison);
  document.getElementById("closeJobComparisonButton")?.addEventListener("click", () => comparisonDialog?.close());
  document.getElementById("clearJobComparisonButton")?.addEventListener("click", () => {
    comparedJobIds.clear();
    document.querySelectorAll(".compare-job-control input").forEach(input => { input.checked = false; });
    updateJobComparisonBar();
  });
  comparisonDialog?.addEventListener("click", event => {
    if (event.target === comparisonDialog) comparisonDialog.close();
  });

  if (chatInput) {
    chatInput.addEventListener("keydown", function(event) {
      if (event.key === "Enter") {
        sendMessage();
      }
    });
  }

  if (showSaveSearchFormButton && saveSearchForm) {
    showSaveSearchFormButton.addEventListener("click", () => {
      saveSearchForm.classList.remove("hidden");
      document.getElementById("savedSearchName")?.focus();
    });
  }

  if (saveSearchForm) {
    saveSearchForm.addEventListener("submit", submitSavedSearch);
  }

  if (cancelSaveSearchButton && saveSearchForm) {
    cancelSaveSearchButton.addEventListener("click", () => {
      saveSearchForm.classList.add("hidden");
      showSaveSearchFormButton.focus();
    });
  }

  if (jobReportForm) {
    jobReportForm.addEventListener("submit", submitJobReport);
  }

  if (closeJobReportButton) {
    closeJobReportButton.addEventListener("click", closeJobReportDialog);
  }

  if (jobReportDialog) {
    jobReportDialog.addEventListener("click", event => {
      if (event.target === jobReportDialog) closeJobReportDialog();
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && !jobReportDialog.classList.contains("hidden")) {
        closeJobReportDialog();
      }
    });
  }
};

document.addEventListener("DOMContentLoaded", initializeSearchHistoryPage);
document.addEventListener("DOMContentLoaded", initializeExternalApplicationCapture);

function getPasswordReadiness(password, username = "", email = "") {
  const issues = [];
  const lengthRemaining = Math.max(0, 12 - password.length);
  const byteLength = new TextEncoder().encode(password).length;
  const common = new Set([
    "password", "password1", "password123", "12345678", "123456789",
    "qwerty123", "letmein", "welcome", "admin", "iloveyou",
    "changeme", "pathforge", "password1!"
  ]);
  if (lengthRemaining) issues.push(`${lengthRemaining} more character${lengthRemaining === 1 ? "" : "s"}`);
  if (byteLength > 72) issues.push(`${byteLength - 72} UTF-8 byte${byteLength - 72 === 1 ? "" : "s"} over the limit`);
  if (common.has(password.replace(/\s+/g, "").toLowerCase())) issues.push("a less common password");
  const identityParts = [username.trim().toLowerCase(), email.split("@")[0].trim().toLowerCase()]
    .filter(part => part.length >= 4);
  if (identityParts.some(part => password.toLowerCase().includes(part))) {
    issues.push("remove your username or email name");
  }
  return { ready: password.length > 0 && issues.length === 0, issues };
}

function initializePasswordReadiness() {
  const configurations = [
    { input: "registerPassword", help: "registerPasswordHelp", username: "registerUsername", email: "registerEmail" },
    { input: "passwordResetNewPassword", help: "passwordResetHelp", email: "passwordResetEmail" },
    { input: "newPassword", help: "passwordHelp" }
  ];
  configurations.forEach(configuration => {
    const input = document.getElementById(configuration.input);
    const help = document.getElementById(configuration.help);
    if (!input || !help) return;
    help.setAttribute("aria-live", "polite");
    const update = () => {
      const password = input.value;
      help.classList.remove("password-ready", "password-not-ready");
      if (!password) {
        help.textContent = "Use at least 12 characters. Common passwords and personal account information are not allowed. Maximum: 72 UTF-8 bytes.";
        return;
      }
      const result = getPasswordReadiness(
        password,
        document.getElementById(configuration.username)?.value || "",
        document.getElementById(configuration.email)?.value || ""
      );
      if (result.ready) {
        help.textContent = "✓ This password meets PathForge requirements.";
        help.classList.add("password-ready");
      } else {
        help.textContent = "Not ready: " + result.issues.join("; ") + ".";
        help.classList.add("password-not-ready");
      }
    };
    input.addEventListener("input", update);
    [configuration.username, configuration.email].forEach(id => {
      document.getElementById(id)?.addEventListener("input", update);
    });
  });
}

document.addEventListener("DOMContentLoaded", initializePasswordReadiness);

const registerForm = document.getElementById("registerForm");

if (registerForm) {
    registerForm.addEventListener("submit", async function (event) {
        event.preventDefault();

        const username = document.getElementById("registerUsername").value;
        const email = document.getElementById("registerEmail").value;
        const password = document.getElementById("registerPassword").value;
        const message = document.getElementById("registerMessage");

        try {
            const response = await fetch(apiUrl("/register"), {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                credentials: "include",
                body: JSON.stringify({
                    username: username,
                    email: email,
                    password: password
                })
            });

            const data = await response.json();

            if (!response.ok) {
                message.classList.remove("success-message");
                message.textContent = data.detail || "Registration failed.";
                return;
            }

            message.classList.add("success-message");
            message.textContent =
              "Account created successfully. Redirecting to the home page...";
            registerForm.reset();
            window.location.href = "index.html";

        } catch (error) {
            message.classList.remove("success-message");
            message.textContent = "Something went wrong. Please try again.";
        }
    });
}

const loginForm = document.getElementById("loginForm");

function getSafeLoginDestination() {
    const requestedPage = new URLSearchParams(window.location.search).get("next");
    const allowedPages = new Set([
        "dashboard.html", "profile.html", "saved-jobs.html",
        "applications.html", "employer-access.html", "employer.html",
        "account-security.html", "messages.html", "analytics.html"
    ]);
    return allowedPages.has(requestedPage) ? requestedPage : "index.html";
}

if (loginForm) {
    loginForm.addEventListener("submit", async function (event) {
        event.preventDefault();

        const identifier = document.getElementById("loginIdentifier").value;
        const password = document.getElementById("loginPassword").value;
        const message = document.getElementById("loginMessage");

        try {
            const response = await fetch(apiUrl("/login"), {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                credentials: "include",
                body: JSON.stringify({
                    identifier: identifier,
                    password: password
                })
            });

            const data = await response.json();

            if (!response.ok) {
                message.classList.remove("success-message");
                message.textContent = data.detail || "Login failed.";
                return;
            }

            message.classList.add("success-message");
            message.textContent =
              "Login successful. Redirecting...";
            window.location.href = getSafeLoginDestination();

        } catch (error) {
            message.classList.remove("success-message");
            message.textContent = "Something went wrong. Please try again.";
        }
    });
}

async function checkLoginStatus() {
    // Navigation begins in a signed-out state in the HTML and is promoted only
    // after /me confirms the session and role.
    const loginLink =
        document.getElementById("loginLink");

    const registerLink =
        document.getElementById("registerLink");

    const dashboardLink =
        document.getElementById("dashboardLink");

    const profileLink =
    document.getElementById("profileLink");

    const employerAccessLink =
        document.getElementById("employerAccessLink");

    const savedJobsLink =
    document.getElementById("savedJobsLink");

    const applicationsLink =
    document.getElementById("applicationsLink");

    const learningCenterLink =
    document.getElementById("learningCenterLink");

    const employerDashboardLink =
        document.getElementById("employerDashboardLink");

    let adminModerationLink =
        document.getElementById("adminModerationLink");

    let accountSecurityLink =
        document.getElementById("accountSecurityLink");

    let messagesLink = document.getElementById("messagesLink");
    let analyticsLink = document.getElementById("analyticsLink");

    const userStatus =
        document.getElementById("userStatus");

    const logoutButton =
        document.getElementById("logoutButton");

    let alertBellLink =
        document.getElementById("alertBellLink");

    const homeAccountAction =
        document.getElementById("homeAccountAction");

    const homeFinalAccountAction =
        document.getElementById("homeFinalAccountAction");

    const homeJobSeekerAction =
        document.getElementById("homeJobSeekerAction");

    const homeEmployerAction =
        document.getElementById("homeEmployerAction");

    // Start from a genuinely signed-out navigation state. This also prevents
    // protected destinations from flashing while /me is still loading.
    [dashboardLink, profileLink, savedJobsLink, applicationsLink,
     employerDashboardLink, logoutButton]
        .forEach(item => { if (item) item.style.display = "none"; });
    [loginLink, registerLink, learningCenterLink, employerAccessLink]
        .forEach(item => { if (item) item.style.display = "inline"; });

    try {
        const sessionStatus = await getSessionStatus();

        if (!sessionStatus.authenticated) {
            jobChatAuthenticated = false;
            setJobChatVisibility(false);
            if (learningCenterLink) learningCenterLink.style.display = "inline";
            if (employerAccessLink) employerAccessLink.style.display = "inline";
            return null;
        }

        const user = sessionStatus.user;
        jobChatAuthenticated = true;
        setJobChatVisibility(true);

        if (!accountSecurityLink) {
            const navLinks = document.querySelector(".nav-links");
            if (navLinks) {
                accountSecurityLink = document.createElement("a");
                accountSecurityLink.id = "accountSecurityLink";
                accountSecurityLink.href = "account-security.html";
                accountSecurityLink.textContent = "Settings";
                navLinks.insertBefore(accountSecurityLink, logoutButton || null);
            }
        }
        if (accountSecurityLink) {
            accountSecurityLink.style.display = "inline";
            if (window.location.pathname.endsWith("account-security.html")) {
                accountSecurityLink.setAttribute("aria-current", "page");
            }
        }

        if (user.role !== "admin" && !messagesLink) {
            const navLinks = document.querySelector(".nav-links");
            if (navLinks) {
                messagesLink = document.createElement("a");
                messagesLink.id = "messagesLink";
                messagesLink.href = "messages.html";
                messagesLink.textContent = "Messages";
                navLinks.insertBefore(messagesLink, accountSecurityLink || logoutButton || null);
            }
        }
        if (messagesLink) {
            messagesLink.style.display = user.role === "admin" ? "none" : "inline";
            if (window.location.pathname.endsWith("messages.html")) messagesLink.setAttribute("aria-current", "page");
        }
        if (user.role !== "admin" && !analyticsLink) {
            const navLinks = document.querySelector(".nav-links");
            if (navLinks) {
                analyticsLink = document.createElement("a"); analyticsLink.id = "analyticsLink";
                analyticsLink.href = "analytics.html"; analyticsLink.textContent = "Analytics";
                navLinks.insertBefore(analyticsLink, accountSecurityLink || logoutButton || null);
            }
        }
        if (analyticsLink) {
            analyticsLink.style.display = user.role === "admin" ? "none" : "inline";
            if (window.location.pathname.endsWith("analytics.html")) analyticsLink.setAttribute("aria-current", "page");
        }

        if (loginLink) {
            loginLink.style.display = "none";
        }

        if (registerLink) {
            registerLink.style.display = "none";
        }

        if (dashboardLink) {
            dashboardLink.style.display = "inline";
        }

        if (profileLink) {
            profileLink.style.display = "inline";
        }

        if (savedJobsLink) {
            savedJobsLink.style.display = "inline";
        }

        if (applicationsLink) {
            applicationsLink.style.display = "inline";
        }

        if (learningCenterLink) {
            learningCenterLink.style.display = "inline";
        }

        if (logoutButton) {
            logoutButton.style.display = "inline-block";
        }

        if (homeAccountAction) {
            if (user.role === "employer") {
                homeAccountAction.href = "employer.html";
                homeAccountAction.textContent =
                    "Open Employer Dashboard";
            } else if (user.role === "admin") {
                homeAccountAction.href = "admin-moderation.html";
                homeAccountAction.textContent = "Open Report Moderation";
            } else {
                homeAccountAction.href = "dashboard.html";
                homeAccountAction.textContent =
                    "Open Your Dashboard";
            }
        }

        if (homeFinalAccountAction) {
            if (user.role === "employer") {
                homeFinalAccountAction.href = "employer.html";
                homeFinalAccountAction.textContent =
                    "Open Employer Dashboard";
            } else if (user.role === "admin") {
                homeFinalAccountAction.href = "admin-moderation.html";
                homeFinalAccountAction.textContent = "Open Report Moderation";
            } else {
                homeFinalAccountAction.href = "dashboard.html";
                homeFinalAccountAction.textContent =
                    "Open Your Dashboard";
            }
        }

        if (homeJobSeekerAction) {
            homeJobSeekerAction.href = user.role === "job_seeker"
                ? "dashboard.html"
                : user.role === "employer"
                    ? "employer.html"
                    : "admin-moderation.html";
            homeJobSeekerAction.textContent = user.role === "job_seeker"
                ? "Open Your Dashboard"
                : user.role === "employer"
                    ? "Open Employer Dashboard"
                    : "Open Report Moderation";
        }

        if (homeEmployerAction && user.role === "employer") {
            homeEmployerAction.href = "employer.html";
            homeEmployerAction.textContent = "Open Employer Dashboard";
        }

        if (user.role === "admin") {
            if (alertBellLink) alertBellLink.style.display = "none";
            if (!adminModerationLink) {
                const navLinks = document.querySelector(".nav-links");
                if (navLinks) {
                    adminModerationLink = document.createElement("a");
                    adminModerationLink.id = "adminModerationLink";
                    adminModerationLink.href = "admin-moderation.html";
                    adminModerationLink.textContent = "Report Moderation";
                    navLinks.insertBefore(adminModerationLink, logoutButton || null);
                }
            }
            if (adminModerationLink) adminModerationLink.style.display = "inline";
            [dashboardLink, profileLink, savedJobsLink, applicationsLink,
             learningCenterLink, employerDashboardLink, employerAccessLink]
                .forEach(link => { if (link) link.style.display = "none"; });
        } else if (user.role === "employer") {
            if (alertBellLink) {
                alertBellLink.style.display = "none";
            }
            if (adminModerationLink) adminModerationLink.style.display = "none";

            if (employerDashboardLink) {
                employerDashboardLink.style.display = "inline";
            }

            if (employerAccessLink) {
                employerAccessLink.style.display = "none";
            }
            [dashboardLink, profileLink, savedJobsLink, applicationsLink]
                .forEach(link => { if (link) link.style.display = "none"; });
        } else {
            if (adminModerationLink) adminModerationLink.style.display = "none";
            alertBellLink = ensureJobAlertBell();
            alertBellLink.style.display = "inline-flex";
            loadJobAlertCount();

            if (employerDashboardLink) {
                employerDashboardLink.style.display = "none";
            }

            if (employerAccessLink) {
                employerAccessLink.style.display = "inline";
            }
        }

        if (userStatus) {
            userStatus.textContent =
                "Logged in as " +
                user.username +
                " (" +
                user.role +
                ")";
        }

        organizePrimaryNavigation(user.role);

        return user;

    } catch (error) {
        jobChatAuthenticated = false;
        setJobChatVisibility(false);
        console.error("Login check failed:", error);
        return null;
    }
}

function organizePrimaryNavigation(role) {
    // Keep frequent destinations visible and group secondary tools by purpose.
    // Existing link nodes are moved—not cloned—so IDs and event handlers remain intact.
    const navLinks = document.querySelector(".main-nav .nav-links");
    const logoutButton = document.getElementById("logoutButton");
    if (!navLinks || !logoutButton) return;

    let moreMenu = document.getElementById("navMoreMenu");
    let morePanel = document.getElementById("navMorePanel");

    if (!moreMenu) {
        moreMenu = document.createElement("details");
        moreMenu.id = "navMoreMenu";
        moreMenu.className = "nav-more";
        moreMenu.innerHTML = `
          <summary aria-label="Open more navigation links">More</summary>
          <div id="navMorePanel" class="nav-more-menu"></div>
        `;
        navLinks.insertBefore(moreMenu, logoutButton);
        morePanel = moreMenu.querySelector(".nav-more-menu");
        morePanel.addEventListener("click", event => {
            if (event.target.closest("a")) moreMenu.open = false;
        });
    }

    const moveIntoMore = ids => ids.forEach(id => {
        const link = document.getElementById(id);
        if (link && link.style.display !== "none") morePanel.appendChild(link);
    });

    if (role === "job_seeker") {
        let searchHistoryLink = document.getElementById("searchHistoryLink");
        if (!searchHistoryLink) {
            searchHistoryLink = document.createElement("a");
            searchHistoryLink.id = "searchHistoryLink";
            searchHistoryLink.href = "search-history.html";
            searchHistoryLink.textContent = "Search History";
            if (window.location.pathname.endsWith("search-history.html")) {
                searchHistoryLink.setAttribute("aria-current", "page");
            }
            navLinks.insertBefore(searchHistoryLink, logoutButton);
        }
        moveIntoMore([
            "applicationsLink", "savedJobsLink",
            "learningCenterLink", "employerAccessLink",
            "messagesLink", "analyticsLink", "searchHistoryLink",
        ]);
    } else if (role === "employer") {
        ["dashboardLink", "profileLink", "savedJobsLink", "applicationsLink",
         "learningCenterLink"].forEach(id => {
            const link = document.getElementById(id);
            if (link) link.style.display = "none";
        });
        moveIntoMore(["messagesLink", "analyticsLink"]);
    } else {
        moreMenu.remove();
    }

    let accountMenu = document.getElementById("navAccountMenu");
    let accountPanel = document.getElementById("navAccountPanel");

    if (!accountMenu) {
        accountMenu = document.createElement("details");
        accountMenu.id = "navAccountMenu";
        accountMenu.className = "nav-account";
        accountMenu.innerHTML = `
          <summary aria-label="Open account menu">Account</summary>
          <div id="navAccountPanel" class="nav-account-menu"></div>
        `;
        navLinks.insertBefore(accountMenu, logoutButton);
        accountPanel = accountMenu.querySelector(".nav-account-menu");
    }

    const profileLink = document.getElementById("profileLink");
    const accountSecurityLink = document.getElementById("accountSecurityLink");
    if (profileLink && profileLink.style.display !== "none") {
        accountPanel.appendChild(profileLink);
    }
    if (accountSecurityLink && accountSecurityLink.style.display !== "none") {
        accountPanel.appendChild(accountSecurityLink);
    }
    accountPanel.appendChild(logoutButton);

    const moreSummary = moreMenu?.querySelector("summary");
    if (moreMenu && morePanel) {
        moreMenu.classList.toggle("hidden", morePanel.children.length === 0);
        moreSummary.textContent = "Workspace";
        moreSummary.setAttribute("aria-label", "Open workspace navigation");
        moreMenu.classList.toggle(
            "has-current-page",
            Boolean(morePanel.querySelector('[aria-current="page"]'))
        );
    }

    const accountSummary = accountMenu.querySelector("summary");
    accountMenu.classList.toggle(
        "has-current-page",
        Boolean(accountPanel.querySelector('[aria-current="page"]'))
    );
    accountPanel.addEventListener("click", event => {
        if (event.target.closest("a") || event.target.closest("button")) {
            accountMenu.open = false;
        }
    });

    moreMenu?.addEventListener("toggle", () => {
        if (moreMenu.open) accountMenu.open = false;
    });
    accountMenu.addEventListener("toggle", () => {
        if (accountMenu.open && moreMenu) moreMenu.open = false;
    });

    document.addEventListener("click", event => {
        if (moreMenu?.open && !moreMenu.contains(event.target)) moreMenu.open = false;
        if (accountMenu.open && !accountMenu.contains(event.target)) accountMenu.open = false;
    });
    document.addEventListener("keydown", event => {
        if (event.key !== "Escape") return;
        if (moreMenu?.open) {
            moreMenu.open = false;
            moreSummary?.focus();
        } else if (accountMenu.open) {
            accountMenu.open = false;
            accountSummary.focus();
        }
    });
}


function ensureJobAlertBell() {
    let bellLink = document.getElementById("alertBellLink");

    if (bellLink) {
        return bellLink;
    }

    const navLinks = document.querySelector(".main-nav .nav-links");
    if (!navLinks) {
        return null;
    }

    bellLink = document.createElement("a");
    bellLink.id = "alertBellLink";
    bellLink.className = "alert-bell-link";
    bellLink.href = "alerts.html";
    bellLink.setAttribute("aria-label", "Notifications");
    bellLink.title = "Notifications";
    if (window.location.pathname.endsWith("alerts.html")) {
        bellLink.setAttribute("aria-current", "page");
    }
    bellLink.innerHTML = `
      <svg class="alert-bell-icon" viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
      <span class="alert-bell-label" aria-hidden="true">Notifications</span>
      <span id="alertBellBadge" class="alert-bell-badge hidden">0</span>
    `;

    const dashboardLink = document.getElementById("dashboardLink");
    const logoutButton = document.getElementById("logoutButton");
    if (dashboardLink?.parentElement === navLinks) {
        dashboardLink.insertAdjacentElement("afterend", bellLink);
    } else {
        navLinks.insertBefore(bellLink, logoutButton || null);
    }
    return bellLink;
}


async function loadJobAlertCount() {
    const bellLink = document.getElementById("alertBellLink");
    const badge = document.getElementById("alertBellBadge");
    if (!bellLink || !badge) return;

    try {
        const response = await fetch(
            apiUrl("/notifications/summary"),
            { credentials: "include" }
        );
        if (!response.ok) return;
        const data = await response.json();
        if (data.notifications_enabled === false) {
            badge.classList.add("hidden");
            bellLink.setAttribute("aria-label", "Notifications are turned off");
            return;
        }
        const unreadCount = Number(data.unread_count) || 0;

        badge.textContent = unreadCount > 99 ? "99+" : String(unreadCount);
        badge.classList.toggle("hidden", unreadCount === 0);
        bellLink.setAttribute(
            "aria-label",
            unreadCount
                ? `Notifications, ${unreadCount} unread`
                : "Notifications, no unread notifications"
        );
    } catch (error) {
        console.error("Job alert count could not be loaded:", error);
    }
}


function formatJobAlertDate(value) {
    if (!value) return "Recently added";
    const parsedDate = new Date(`${String(value).replace(" ", "T")}Z`);
    if (Number.isNaN(parsedDate.getTime())) return "Recently matched";
    return parsedDate.toLocaleDateString();
}


function renderJobAlerts(alerts) {
    const list = document.getElementById("jobAlertsList");
    const status = document.getElementById("alertsPageStatus");
    const markAllButton = document.getElementById("markAllAlertsReadButton");
    if (!list || !status) return;

    const unreadCount = alerts.filter(alert => !alert.is_read).length;
    if (markAllButton) markAllButton.disabled = unreadCount === 0;

    if (!alerts.length) {
        // The empty-state card carries the message; avoid repeating it in the live status region.
        status.textContent = "";
        list.innerHTML = `
          <div class="job-alerts-empty">
            <h2>No notifications here</h2>
            <p>PathForge will add relevant job-search activity when it becomes available.</p>
          </div>
        `;
        return;
    }

    status.textContent = unreadCount
        ? `${unreadCount} unread notification${unreadCount === 1 ? "" : "s"}.`
        : "You are all caught up.";
    list.innerHTML = alerts.map(alert => `
      <article class="job-alert-card ${alert.is_read ? "" : "unread"}">
        <div class="job-alert-card-heading">
          <div>
            <p class="job-alert-search-name">${escapeEmployerHtml(alert.notification_type.replaceAll("_", " "))}</p>
            <h2>${escapeEmployerHtml(alert.title)}</h2>
          </div>
          ${alert.is_read ? "" : '<span class="job-alert-new-label">New</span>'}
        </div>

        <p>${escapeEmployerHtml(alert.message)}</p>
        <p class="job-alert-date">${formatJobAlertDate(alert.created_at)}</p>

        <a
          class="job-alert-view-link"
          href="${escapeEmployerHtml(alert.href)}"
          data-action="open-notification"
          data-notification-id="${alert.id}"
        >
          View Details
        </a>
      </article>
    `).join("");
}


async function loadJobAlerts() {
    const list = document.getElementById("jobAlertsList");
    if (!list) return;

    try {
        const category = document.getElementById("notificationCategoryFilter")?.value || "all";
        const response = await fetch(apiUrl(`/notifications?category=${encodeURIComponent(category)}`), {
            credentials: "include"
        });
        if (response.status === 401) {
            window.location.href = "login.html";
            return;
        }
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || "Notifications could not be loaded.");
        }
        renderJobAlerts(data.notifications || []);
        if (data.notifications_enabled === false) {
            const status = document.getElementById("alertsPageStatus");
            status.textContent = "Notifications are turned off in Settings.";
            list.innerHTML = '<div class="job-alerts-empty"><h2>Notifications are off</h2><p><a href="account-security.html">Open Settings</a> to turn PathForge notifications back on.</p></div>';
        }
    } catch (error) {
        document.getElementById("alertsPageStatus").textContent = error.message;
        document.getElementById("alertsPageStatus").classList.add("error-message");
    }
}


async function openNotification(event, notificationId) {
    event.preventDefault();
    const href = event.currentTarget.href;
    try {
        await fetch(
            apiUrl(`/notifications/${notificationId}/mark-read`),
            { method: "POST", credentials: "include" }
        );
    } finally {
        window.location.href = href;
    }
}


async function markAllJobAlertsRead() {
    const button = document.getElementById("markAllAlertsReadButton");
    if (!button) return;
    button.disabled = true;

    try {
        const response = await fetch(
            apiUrl("/notifications/mark-read"),
            { method: "POST", credentials: "include" }
        );
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || "Alerts could not be marked as read.");
        }
        await loadJobAlerts();
        await loadJobAlertCount();
    } catch (error) {
        const status = document.getElementById("alertsPageStatus");
        status.textContent = error.message;
        status.classList.add("error-message");
        button.disabled = false;
    }
}


const logoutButton = document.getElementById("logoutButton");

if (logoutButton) {
    logoutButton.addEventListener("click", async function () {

        const confirmedLogout = window.confirm(
            "Are you sure you want to log out?"
        );

        if (!confirmedLogout) {
            return;
        }

        await fetch(apiUrl("/logout"), {
            method: "POST",
            credentials: "include"
        });

        window.location.href = "index.html";
    });
}

async function protectPage() {
    // The Resource Center and job search are intentionally public. Only pages
    // containing private account data or actions belong in this list.
    const protectedPages = [
    "dashboard.html",
    "profile.html",
    "saved-jobs.html",
    "applications.html",
    "employer-access.html",
    "account-security.html"
    ,"messages.html", "analytics.html"
];

    const currentPage = window.location.pathname.split("/").pop();

    if (!protectedPages.includes(currentPage)) {
        return;
    }

    try {
        const sessionStatus = await getSessionStatus();

        if (!sessionStatus.authenticated) {
            window.location.href =
                "login.html?next=" + encodeURIComponent(currentPage);
            return;
        }

    } catch (error) {
        window.location.href =
            "login.html?next=" + encodeURIComponent(currentPage);
    }
}

async function protectEmployerPage() {
    const currentPage =
        window.location.pathname.split("/").pop();

    if (currentPage !== "employer.html") {
        return;
    }

    try {
        const sessionStatus = await getSessionStatus();

        if (!sessionStatus.authenticated) {
            window.location.href = "login.html?next=employer.html";
            return;
        }

        const user = sessionStatus.user;

        if (user.role !== "employer") {
            window.location.href = "employer-access.html";
            return;
        }

        console.log("Employer access confirmed:", user.username);

    } catch (error) {
        console.error(
            "Employer page protection failed:",
            error
        );

        window.location.href = "index.html";
    }
}

// Dashboard summaries fail independently so one unavailable panel does not
// erase the rest of the user's workspace.
async function loadDashboard() {
    const welcomeHeading = document.getElementById("dashboardWelcome");

    if (!welcomeHeading) {
        return;
    }

    try {
        const response = await fetch(apiUrl("/dashboard-summary"), {
            credentials: "include"
        });

        if (!response.ok) {
            window.location.href = "login.html";
            return;
        }

        const data = await response.json();

        welcomeHeading.textContent = "Welcome back, " + data.user.username + "!";

        const savedJobsCount = document.getElementById("savedJobsCount");
        const applicationsCount = document.getElementById("applicationsCount");
        const interviewsCount = document.getElementById("interviewsCount");
        const followUpsCount = document.getElementById("followUpsCount");
        const jobAlertsCount = document.getElementById("jobAlertsCount");

        if (savedJobsCount) {
            savedJobsCount.textContent = data.summary.saved_jobs;
        }

        if (applicationsCount) {
            applicationsCount.textContent = data.summary.applications;
        }

        if (interviewsCount) {
            interviewsCount.textContent = data.summary.interviews;
        }

        if (followUpsCount) {
            followUpsCount.textContent = data.summary.follow_ups;
        }

        if (jobAlertsCount) {
            jobAlertsCount.textContent = data.summary.job_alerts;
        }

        await loadNextBestActions();

        } catch (error) {
        console.error("Dashboard connection error:", error);
        window.location.href = "login.html";
    }
}


function getNextActionTypeLabel(type) {
    const labels = {
        follow_up: "Follow-up",
        interview: "Interview",
        job_alert: "Job alert",
        deadline: "Deadline",
        application: "Application",
        status_update: "Application update",
        explore: "Job search"
    };

    return labels[type] || "Next step";
}


function renderNextBestActions(data) {
    const list = document.getElementById("nextBestActionsList");
    const status = document.getElementById("nextBestActionsStatus");
    const explanation = document.getElementById(
        "nextBestActionsExplanation"
    );

    if (!list || !status || !explanation) return;

    const actions = data.actions || [];
    status.textContent = actions.length === 1
        ? "1 recommended next step."
        : `${actions.length} recommended next steps.`;
    explanation.textContent = data.explanation || "";

    if (actions.length === 0) {
        list.innerHTML = `
          <div class="empty-state compact-empty-state">
            <h4>No urgent next steps</h4>
            <p>Explore current jobs or update your profile when you are ready.</p>
            <a class="empty-state-link" href="jobs.html">Browse Jobs</a>
          </div>
        `;
        return;
    }

    list.innerHTML = actions.map((action, index) => `
      <article class="next-best-action-card urgency-${action.urgency}">
        <div class="next-best-action-rank" aria-hidden="true">
          ${index + 1}
        </div>

        <div class="next-best-action-content">
          <div class="next-best-action-heading">
            <span class="next-best-action-type">
              ${escapeEmployerHtml(getNextActionTypeLabel(action.type))}
            </span>
            ${action.urgency === "urgent" ? `
              <span class="next-best-action-urgency">Needs attention</span>
            ` : ""}
          </div>

          <h4>${escapeEmployerHtml(action.title)}</h4>
          <p>${escapeEmployerHtml(action.reason)}</p>

          <a href="${escapeEmployerHtml(action.href)}">
            ${escapeEmployerHtml(action.action_label)}
          </a>
        </div>
      </article>
    `).join("");
}


async function loadNextBestActions() {
    const list = document.getElementById("nextBestActionsList");
    if (!list) return;
    list.innerHTML = buildContentLoadingState("Loading your next actions", 2);

    try {
        const response = await fetch(
            apiUrl("/next-best-actions"),
            { credentials: "include" }
        );
        const data = await response.json();
        if (!response.ok) {
            throw new Error(
                data.detail || "Your next actions could not be loaded."
            );
        }
        renderNextBestActions(data);
    } catch (error) {
        const status = document.getElementById("nextBestActionsStatus");
        status.textContent = (
            "Your next actions could not be loaded. Please refresh and try again."
        );
        status.classList.add("error-message");
        list.innerHTML = "";
        console.error("Next best actions could not be loaded:", error);
    }
}

const employerAccessForm =
    document.getElementById("employerAccessForm");

const employerWorkspaceForm = document.getElementById("employerWorkspaceForm");
if (employerWorkspaceForm) {
    employerWorkspaceForm.addEventListener("submit", async event => {
        event.preventDefault();
        const message = document.getElementById("employerWorkspaceMessage");
        const submitButton = employerWorkspaceForm.querySelector('button[type="submit"]');
        message.textContent = "Creating your employer workspace...";
        message.classList.remove("success-message", "error-message");
        submitButton.disabled = true;
        try {
            const response = await fetch(apiUrl("/employer/workspace"), {
                method: "POST", credentials: "include",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    company_name: document.getElementById("employerWorkspaceCompany").value.trim(),
                    website: document.getElementById("employerWorkspaceWebsite").value.trim() || null,
                    contact_email: document.getElementById("employerWorkspaceEmail").value.trim() || null,
                    current_password: document.getElementById("employerWorkspacePassword").value
                })
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || "The employer workspace could not be created.");
            message.textContent = data.message + " Opening your employer dashboard...";
            message.classList.add("success-message");
            employerWorkspaceForm.reset();
            window.setTimeout(() => { window.location.href = "employer.html"; }, 900);
        } catch (error) {
            message.textContent = error.message;
            message.classList.add("error-message");
            submitButton.disabled = false;
        }
    });
}

if (employerAccessForm) {
    employerAccessForm.addEventListener(
        "submit",
        async function (event) {
            event.preventDefault();

            const codeInput =
                document.getElementById("employerAccessCode");

            const message =
                document.getElementById("employerAccessMessage");

            const code = codeInput.value.trim();

            message.textContent = "";
            message.classList.remove(
                "success-message",
                "error-message"
            );

            if (code === "") {
                message.textContent =
                    "Please enter an employer access code.";

                message.classList.add("error-message");

                return;
            }

            try {
                const response = await fetchWithTimeout(
                    apiUrl("/employer-access/redeem"),
                    {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json"
                        },
                        credentials: "include",
                        body: JSON.stringify({
                            code: code
                        })
                    }
                );

                const data = await response.json();

                if (!response.ok) {
                    message.textContent =
                        data.detail ||
                        "Employer access could not be approved.";

                    message.classList.add("error-message");

                    return;
                }

                message.textContent =
                    data.message +
                    " Redirecting to the Employer Dashboard...";

                message.classList.add("success-message");

                codeInput.value = "";

                await checkLoginStatus();

                setTimeout(function () {
                    window.location.href = "employer.html";
                }, 1000);

            } catch (error) {
                message.textContent =
                    "The backend could not be reached. Please try again.";

                message.classList.add("error-message");
            }
        }
    );
}

async function loadProfile() {
    const profileForm = document.getElementById("profileForm");

    if (!profileForm) {
        return;
    }

    const message = document.getElementById("profileMessage");

    try {
        const response = await fetch(
            apiUrl("/profile"),
            {
                credentials: "include"
            }
        );

        if (response.status === 401) {
            window.location.href = "login.html";
            return;
        }

        const data = await response.json();

        if (!response.ok) {
            throw new Error(
                data.detail || "Profile could not be loaded."
            );
        }

        const profile = data.profile || {};

        document.getElementById("profileDisplayName").value =
            profile.display_name || "";

        document.getElementById("profileCareerStage").value =
            profile.career_stage || "";

        document.getElementById("profileCareerInterests").value =
            profile.career_interests || "";

        document.getElementById("profilePreferredIndustries").value =
            profile.preferred_industries || "";

        document.getElementById("profileSkills").value =
            profile.skills || "";

        document.getElementById("profileExperienceLevel").value =
            profile.experience_level || "";

        document.querySelectorAll(
            "#profileExperienceLevelDropdown input[type='radio']"
        ).forEach(radio => {
            radio.checked = radio.value === (profile.experience_level || "");
        });
        updateExperienceLevelSummary();

        document.getElementById("profilePreferredLocation").value =
            profile.preferred_location || "";

        const savedSchedulePreferences = new Set(
            splitFitPreferences(profile.schedule_preference)
        );

        document.querySelectorAll(
            "#profileSchedulePreference input[type='checkbox']"
        ).forEach(checkbox => {
            checkbox.checked = savedSchedulePreferences.has(
                normalizeFitText(checkbox.value)
            );
        });
        updateSchedulePreferenceSummary();

        document.getElementById("profileWorkPreference").value =
            profile.work_preference || "";

        document.querySelectorAll(
            "#profileWorkPreferenceDropdown input[type='radio']"
        ).forEach(radio => {
            radio.checked = radio.value === (profile.work_preference || "");
        });
        updateWorkPreferenceSummary();

        const savedAdditionalPayPreferences = new Set(
            splitFitPreferences(profile.desired_pay)
        );

        document.querySelectorAll(
            "#profileDesiredPay input[type='checkbox']"
        ).forEach(checkbox => {
            checkbox.checked = savedAdditionalPayPreferences.has(
                normalizeFitText(checkbox.value)
            );
        });
        updateAdditionalPayPreferenceSummary();

        document.getElementById("profileMaximumCommuteDistance").value =
            profile.maximum_commute_distance ?? "";

        document.getElementById("profileMaximumCommuteTime").value =
            profile.maximum_commute_time ?? "";

        document.getElementById("profilePayPeriod").value =
            profile.pay_period === "year" ? "year" : "hour";

        document.getElementById("profileMinimumBasePay").value =
            profile.minimum_base_pay ?? "";

        document.getElementById("profileCareerGoals").value =
            profile.career_goals || "";

    } catch (error) {
        console.error("Profile load failed:", error);

        message.textContent = error.message;
        message.classList.remove("success-message");
        message.classList.add("error-message");
    }
}

let profileAutoSaveTimer = null;
let profileSaveMode = "manual";
let profileSaveInFlight = false;
let profileSavePending = false;

function setupProfileForm() {
    const profileForm = document.getElementById("profileForm");

    if (!profileForm) {
        return;
    }

    profileForm.addEventListener(
        "submit",
        async function (event) {
            event.preventDefault();

            const isAutomaticSave = profileSaveMode === "automatic";
            profileSaveMode = "manual";

            if (profileSaveInFlight) {
                profileSavePending = true;
                return;
            }

            profileSaveInFlight = true;
            profileForm.setAttribute("aria-busy", "true");

            const message =
                document.getElementById("profileMessage");

            const saveButton =
                document.getElementById("saveProfileButton");

            message.textContent = isAutomaticSave ? "Saving changes…" : "";

            message.classList.remove(
                "success-message",
                "error-message"
            );

            if (!isAutomaticSave) {
                saveButton.disabled = true;
                saveButton.textContent = "Saving...";
            }

            const profileData = {
                display_name:
                    document.getElementById("profileDisplayName").value.trim(),

                career_stage:
                    document.getElementById("profileCareerStage").value,

                career_interests:
                    document.getElementById("profileCareerInterests").value.trim(),

                preferred_industries:
                    document.getElementById("profilePreferredIndustries").value.trim(),

                skills:
                    document.getElementById("profileSkills").value.trim(),

                experience_level:
                    document.getElementById("profileExperienceLevel").value,

                preferred_location:
                    document.getElementById("profilePreferredLocation").value.trim(),

                schedule_preference:
                    Array.from(
                        document.querySelectorAll(
                            "#profileSchedulePreference "
                            + "input[type='checkbox']:checked"
                        )
                    )
                        .map(checkbox => checkbox.value)
                        .join(", "),

                work_preference:
                    document.getElementById("profileWorkPreference").value,

                desired_pay:
                    Array.from(
                        document.querySelectorAll(
                            "#profileDesiredPay "
                            + "input[type='checkbox']:checked"
                        )
                    )
                        .map(checkbox => checkbox.value)
                        .join(", "),

                maximum_commute_distance:
                    document.getElementById("profileMaximumCommuteDistance").value === ""
                        ? null
                        : Number(document.getElementById("profileMaximumCommuteDistance").value),

                maximum_commute_time:
                    document.getElementById("profileMaximumCommuteTime").value === ""
                        ? null
                        : Number(document.getElementById("profileMaximumCommuteTime").value),

                pay_period:
                    document.getElementById("profilePayPeriod").value,

                minimum_base_pay:
                    document.getElementById("profileMinimumBasePay").value === ""
                        ? null
                        : Number(document.getElementById("profileMinimumBasePay").value),

                career_goals:
                    document.getElementById("profileCareerGoals").value.trim()
            };

            try {
                const response = await fetchWithTimeout(
                    apiUrl("/profile"),
                    {
                        method: "PUT",
                        headers: {
                            "Content-Type": "application/json"
                        },
                        credentials: "include",
                        body: JSON.stringify(profileData)
                    }
                );

                if (response.status === 401) {
                    window.location.href = "login.html";
                    return;
                }

                const data = await response.json();

                if (!response.ok) {
                    throw new Error(
                        data.detail || "Profile could not be saved."
                    );
                }

                if (!isAutomaticSave) {
                    message.textContent =
                        data.message || "Profile saved successfully.";

                    message.classList.add("success-message");

                    window.scrollTo(0, 0);
                } else {
                    message.textContent = "All changes saved.";
                    message.classList.add("success-message");
                }

            } catch (error) {
                console.error("Profile save failed:", error);

                message.textContent = error.message;
                message.classList.add("error-message");

            } finally {
                profileSaveInFlight = false;
                profileForm.removeAttribute("aria-busy");

                if (!isAutomaticSave) {
                    saveButton.disabled = false;
                    saveButton.textContent = "Save Profile";
                }

                if (profileSavePending && profileForm.isConnected) {
                    profileSavePending = false;
                    profileSaveMode = "automatic";
                    profileForm.requestSubmit();
                }
            }
        }
    );

    function queueProfileAutoSave(delay) {
        clearTimeout(profileAutoSaveTimer);
        profileAutoSaveTimer = setTimeout(function () {
            profileSaveMode = "automatic";
            profileForm.requestSubmit();
        }, delay);
    }

    profileForm.addEventListener("input", function (event) {
        if (event.target.matches("input, textarea")) {
            queueProfileAutoSave(700);
        }
    });

    profileForm.addEventListener("change", function (event) {
        if (event.target.matches("input, select")) {
            queueProfileAutoSave(150);
        }
    });
}

async function loadSavedJobs() {
  const savedJobsContainer =
    document.getElementById("savedJobsContainer");

  if (!savedJobsContainer) {
    return;
  }

  savedJobsContainer.innerHTML = buildContentLoadingState(
    "Loading saved jobs",
    2
  );

  try {
    const response = await fetch(
      apiUrl("/saved-jobs"),
      {
        credentials: "include"
      }
    );

    if (response.status === 401) {
      window.location.href = "login.html";
      return;
    }

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        data.detail || "Saved jobs could not be loaded."
      );
    }

    displaySavedJobs(data.saved_jobs);

  } catch (error) {
    console.error("Saved jobs load failed:", error);

    savedJobsContainer.innerHTML = `
      <div class="empty-state">
        <h3>Saved jobs could not be loaded</h3>
        <p>${escapeEmployerHtml(error.message)}</p>
        <button type="button" data-action="reload-saved-jobs">Try Again</button>
      </div>
    `;
  }
}


function displaySavedJobs(jobs) {
  const savedJobsContainer =
    document.getElementById("savedJobsContainer");

  if (!savedJobsContainer) {
    return;
  }

  savedJobsContainer.innerHTML = "";

  if (jobs.length === 0) {
    savedJobsContainer.innerHTML = `
      <div class="empty-state">
        <h3>You have no saved jobs yet</h3>

        <p>
          Browse available jobs and save the ones you want
          to revisit later.
        </p>

        <a class="empty-state-link" href="jobs.html">
          Browse Jobs
        </a>
      </div>
    `;

    return;
  }

  jobs.forEach(job => {
    const jobCard = document.createElement("article");
    jobCard.className = "job-card saved-job-card";
    jobCard.dataset.jobId = job.id;

    jobCard.innerHTML = `
      <h3>${escapeEmployerHtml(job.title)}</h3>

      <p>
        <strong>Company:</strong>
        <a href="company.html?name=${encodeURIComponent(job.company)}">${escapeEmployerHtml(job.company)}</a>
      </p>

      <p>
        <strong>Location:</strong>
        ${escapeEmployerHtml(job.location)}
      </p>

      <p>
        <strong>Pay:</strong>
        ${escapeEmployerHtml(job.pay)}
      </p>

      ${job.application_deadline ? `
        <p class="${
          applicationDeadlineHasPassed(job.application_deadline)
            ? "deadline-passed"
            : ""
        }">
          <strong>Application deadline:</strong>
          ${escapeEmployerHtml(
            formatApplicationDeadline(job.application_deadline)
          )}
          ${
            applicationDeadlineHasPassed(job.application_deadline)
              ? " (passed)"
              : ""
          }
        </p>
      ` : ""}

      <div class="job-details">
        <p>
          <strong>Description:</strong>
          ${escapeEmployerHtml(cleanJobPostingText(job.description))}
        </p>

        <p>
          <strong>Schedule:</strong>
          ${escapeEmployerHtml(job.schedule)}
        </p>

        <p>
          <strong>Experience:</strong>
          ${escapeEmployerHtml(job.experience)}
        </p>
      </div>

      <div class="job-card-actions">
        <a class="tailor-resume-button" href="resume.html?job=${job.id}">
          Review Résumé for This Job
        </a>
        <button
          type="button"
          class="remove-saved-job-button"
          data-action="remove-saved-job"
          data-job-id="${job.id}"
        >
          Remove Saved Job
        </button>
      </div>

      <p
        class="job-save-message"
        aria-live="polite"
      ></p>
    `;

    savedJobsContainer.appendChild(jobCard);
  });
}


async function removeSavedJob(jobId, button) {
  const jobCard = button.closest(".job-card");
  const message = jobCard.querySelector(".job-save-message");

  button.disabled = true;
  button.textContent = "Removing...";

  try {
    const response = await fetch(
      apiUrl(`/saved-jobs/${jobId}`),
      {
        method: "DELETE",
        credentials: "include"
      }
    );

    if (response.status === 401) {
      window.location.href = "login.html";
      return;
    }

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        data.detail || "The saved job could not be removed."
      );
    }

    savedJobIds.delete(jobId);
    jobCard.remove();

    const savedJobsContainer =
      document.getElementById("savedJobsContainer");

    if (
      savedJobsContainer &&
      savedJobsContainer.children.length === 0
    ) {
      displaySavedJobs([]);
    }

  } catch (error) {
    console.error("Remove saved job failed:", error);

    button.disabled = false;
    button.textContent = "Remove Saved Job";

    message.textContent = error.message;
    message.classList.add("error-message");
  }
}

// Application records are the source of truth for status history and follow-up reminders.
async function loadApplications() {
  const applicationsContainer =
    document.getElementById("applicationsContainer");

  if (!applicationsContainer) {
    return;
  }

  applicationsContainer.innerHTML = buildContentLoadingState(
    "Loading applications",
    2
  );

  try {
    const response = await fetch(
      apiUrl("/applications"),
      {
        credentials: "include"
      }
    );

    if (response.status === 401) {
      window.location.href = "login.html";
      return;
    }

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        data.detail ||
        "Applications could not be loaded."
      );
    }

    displayApplications(data.applications);
    renderApplicationHealth(data.applications);

  } catch (error) {
    console.error(
      "Application tracker load failed:",
      error
    );

    applicationsContainer.innerHTML = `
      <div class="empty-state">
        <h3>Applications could not be loaded</h3>
        <p>${error.message}</p>
        <button type="button" data-action="reload-applications">Try Again</button>
      </div>
    `;
  }
}

function renderApplicationHealth(applications) {
  const container = document.getElementById("applicationHealthSummary");
  if (!container) return;
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const reminders = [];
  applications.forEach(application => {
    const appliedDate = application.applied_at ? new Date(`${String(application.applied_at).slice(0, 10)}T00:00:00`) : null;
    const followUp = application.follow_up_date ? new Date(`${String(application.follow_up_date).slice(0, 10)}T00:00:00`) : null;
    const interview = application.interview_date ? new Date(`${String(application.interview_date).slice(0, 10)}T00:00:00`) : null;
    const active = !/rejected|withdrawn|hired|closed|not selected/i.test(application.status || "");
    if (active && followUp && followUp < today) reminders.push({ level: "urgent", title: `Follow up with ${application.company}`, reason: `The saved follow-up date for ${application.title} has passed.` });
    if (active && interview && interview >= today && !String(application.interview_details || "").trim()) reminders.push({ level: "prepare", title: `Prepare for ${application.company}`, reason: `An interview is scheduled, but no preparation notes are saved.` });
    if (active && appliedDate && !followUp && (today - appliedDate) / 86400000 >= 7) reminders.push({ level: "review", title: `Review ${application.title}`, reason: `This application was recorded at least 7 days ago without a follow-up date.` });
    if (active && !application.applied_at) reminders.push({ level: "review", title: `Complete the date for ${application.title}`, reason: "The tracker does not have an application date." });
  });
  if (!applications.length) {
    container.innerHTML = `<div class="application-health-empty"><strong>No applications to check yet</strong><p>Add an application to receive factual tracker reminders.</p></div>`;
    return;
  }
  if (!reminders.length) {
    container.innerHTML = `<div class="application-health-clear"><strong>No tracker issues found</strong><p>Your saved dates and active application details do not currently require attention.</p></div>`;
    return;
  }
  container.innerHTML = reminders.slice(0, 8).map(item => `<article class="application-health-item health-${item.level}"><div aria-hidden="true">${item.level === "urgent" ? "!" : "✓"}</div><section><strong>${escapeEmployerHtml(item.title)}</strong><p>${escapeEmployerHtml(item.reason)}</p></section></article>`).join("");
}

function initializeExternalApplicationCapture() {
  const form = document.getElementById("externalApplicationForm");
  const toggle = document.getElementById("toggleExternalCaptureButton");
  const cancel = document.getElementById("cancelExternalCaptureButton");
  const status = document.getElementById("externalCaptureStatus");
  if (!form || !toggle || !status) return;
  const setOpen = open => {
    form.classList.toggle("hidden", !open);
    toggle.setAttribute("aria-expanded", String(open));
    toggle.textContent = open ? "Close Form" : "Add Application";
    if (open) document.getElementById("externalJobTitle")?.focus();
  };
  toggle.addEventListener("click", () => setOpen(form.classList.contains("hidden")));
  cancel?.addEventListener("click", () => { form.reset(); status.textContent = ""; setOpen(false); });
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    status.className = "form-message external-capture-wide";
    status.textContent = "Adding this application privately...";
    try {
      const response = await fetchWithTimeout(apiUrl("/applications/external-capture"), {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: document.getElementById("externalJobTitle").value.trim(),
          company: document.getElementById("externalJobCompany").value.trim(),
          location: document.getElementById("externalJobLocation").value.trim() || "Not listed",
          application_url: document.getElementById("externalJobUrl").value.trim() || null,
          applied_at: document.getElementById("externalAppliedAt").value || null,
          follow_up_date: document.getElementById("externalFollowUpDate").value || null,
          status: "Applied",
          notes: document.getElementById("externalApplicationNotes").value.trim() || null
        })
      });
      const data = await response.json();
      if (response.status === 401) { window.location.href = "login.html"; return; }
      if (!response.ok) throw new Error(data.detail || "The external application could not be added.");
      form.reset();
      status.textContent = data.message;
      status.classList.add("success-message");
      await loadApplications();
    } catch (error) {
      status.textContent = error.message;
      status.classList.add("error-message");
    } finally {
      submit.disabled = false;
    }
  });
}

function displayApplications(applications) {
  const applicationsContainer =
    document.getElementById("applicationsContainer");

  if (!applicationsContainer) {
    return;
  }

  applicationsContainer.innerHTML = "";

  if (applications.length === 0) {
    applicationsContainer.innerHTML = `
      <div class="empty-state">
        <h3>No applications are being tracked yet</h3>

        <p>
          Applications submitted through PathForge will
          appear here automatically. You can also track
          applications completed on an employer website.
        </p>

        <a class="empty-state-link" href="jobs.html">
          Browse Jobs
        </a>
      </div>
    `;

    return;
  }

  applications.forEach(application => {
    const card = document.createElement("article");

    card.className = "application-card";
    card.dataset.applicationId = application.id;

    const employerManaged =
      Boolean(application.employer_managed);

    const methodText = employerManaged
      ? "Employer-managed PathForge application"
      : application.application_method === "pathforge"
        ? "PathForge tracker entry"
        : "Applied on employer website";

    const updateSourceText =
      application.last_update_source === "employer"
        ? "Latest tracked update from employer"
        : application.last_update_source === "system"
          ? "Latest tracked update from PathForge"
          : "Latest tracked update from you";

    const statusField = employerManaged
      ? `
        <div class="application-field">
          <span class="application-readonly-label">
            Status
          </span>

          <span class="application-employer-status">
            ${escapeEmployerHtml(application.status)}
          </span>

          <small class="application-managed-note">
            Updated by the employer
          </small>
        </div>
      `
      : `
        <div class="application-field">
          <label for="status-${application.id}">
            Status
          </label>

          <select
            id="status-${application.id}"
            class="application-status"
          >
            ${buildApplicationStatusOptions(
              application.status
            )}
          </select>
        </div>
      `;

    const applicationDateField = employerManaged
      ? `
        <div class="application-field">
          <span class="application-readonly-label">
            Application Date
          </span>

          <span class="application-readonly-value">
            ${escapeEmployerHtml(
              formatApplicationDisplayDate(
                application.applied_at
              )
            )}
          </span>
        </div>
      `
      : `
        <div class="application-field">
          <label for="applied-${application.id}">
            Application Date
          </label>

          <input
            id="applied-${application.id}"
            class="application-applied-date"
            type="date"
            value="${formatDateForInput(
              application.applied_at
            )}"
          >
        </div>
      `;

    const interviewField = employerManaged
      ? buildEmployerManagedInterviewDetails(application)
      : `
        <div class="application-field">
          <label for="interview-${application.id}">
            Interview Date
          </label>

          <input
            id="interview-${application.id}"
            class="application-interview-date"
            type="date"
            value="${formatDateForInput(
              application.interview_date
            )}"
          >
        </div>

        <div class="application-field">
          <label for="interview-time-${application.id}">
            Interview Time
          </label>
          <input
            id="interview-time-${application.id}"
            class="application-interview-time"
            type="time"
            value="${escapeEmployerHtml(
              application.interview_time || ""
            )}"
          >
        </div>

        <div class="application-field">
          <label for="interview-format-${application.id}">
            Interview Format
          </label>
          <select
            id="interview-format-${application.id}"
            class="application-interview-format"
          >
            <option value="">Select format</option>
            ${["In Person", "Phone", "Video"].map(format => `
              <option
                value="${format}"
                ${application.interview_format === format ? "selected" : ""}
              >${format}</option>
            `).join("")}
          </select>
        </div>

        <div class="application-field application-field-wide">
          <label for="interview-location-${application.id}">
            Interview Location or Link
          </label>
          <input
            id="interview-location-${application.id}"
            class="application-interview-location"
            type="text"
            maxlength="500"
            placeholder="Address, phone details, or video meeting link"
            value="${escapeEmployerHtml(
              application.interview_location || ""
            )}"
          >
        </div>

        <div class="application-field application-field-wide">
          <label for="interview-details-${application.id}">
            Interview Details
          </label>
          <textarea
            id="interview-details-${application.id}"
            class="application-interview-details-input"
            rows="3"
            maxlength="2000"
            placeholder="Add preparation notes or instructions from the employer."
          >${escapeEmployerHtml(
            application.interview_details || ""
          )}</textarea>
        </div>
      `;

    const deleteButton = employerManaged
      ? ""
      : `
        <button
          type="button"
          class="application-delete-button"
          data-action="delete-application"
          data-application-id="${application.id}"
        >
          Remove from Tracker
        </button>
      `;

    card.innerHTML = `
      <div class="application-card-heading">
        <div>
          <h3>${escapeEmployerHtml(application.title)}</h3>

          <p class="application-company">
            ${escapeEmployerHtml(application.company)}
          </p>
        </div>

        <div class="application-card-meta">
          <span class="application-method-badge">
            ${escapeEmployerHtml(methodText)}
          </span>
          <small class="application-update-source">
            ${escapeEmployerHtml(updateSourceText)}
          </small>
        </div>
      </div>

      <div class="application-job-summary">
        <p>
          <strong>Location:</strong>
          ${escapeEmployerHtml(application.location)}
        </p>

        <p>
          <strong>Pay:</strong>
          ${escapeEmployerHtml(application.pay)}
        </p>

        <p>
          <strong>Schedule:</strong>
          ${escapeEmployerHtml(application.schedule)}
        </p>

        ${application.application_deadline ? `
          <p class="${
            applicationDeadlineHasPassed(
              application.application_deadline
            )
              ? "deadline-passed"
              : ""
          }">
            <strong>Application deadline:</strong>
            ${escapeEmployerHtml(
              formatApplicationDeadline(
                application.application_deadline
              )
            )}
            ${
              applicationDeadlineHasPassed(
                application.application_deadline
              )
                ? " (passed)"
                : ""
            }
          </p>
        ` : ""}
      </div>

      ${buildApplicationFollowUpReminder(application)}

      <form
        class="application-edit-form"
        data-employer-managed="${employerManaged}"
      >
        <div class="application-form-grid">
          ${statusField}
          ${applicationDateField}
          ${interviewField}
        </div>

        <section class="application-personal-updates">
          <h4>Follow-Up &amp; Notes</h4>

          <div class="application-field">
            <label for="follow-up-${application.id}">
              Personal Follow-Up Date
            </label>

            <input
              id="follow-up-${application.id}"
              class="application-follow-up-date"
              type="date"
              value="${formatDateForInput(
                application.follow_up_date
              )}"
            >
          </div>

          <div class="application-field">
            <label for="notes-${application.id}">
            Personal Notes
            </label>

            <textarea
              id="notes-${application.id}"
              class="application-notes"
              rows="4"
              placeholder="Add your own reminders and follow-up notes."
            >${escapeEmployerHtml(
              application.notes || ""
            )}</textarea>
          </div>
        </section>

        ${buildApplicationHistoryTimeline(application)}

        <div class="application-card-actions">
          ${deleteButton}
        </div>

        <p
          class="application-message"
          aria-live="polite"
        ></p>
      </form>
    `;

    applicationsContainer.appendChild(card);
    enableApplicationAutoSave(
      card.querySelector(".application-edit-form"),
      application.id
    );
  });
}


function buildApplicationFollowUpReminder(application) {
  if (!application.follow_up_date) {
    return "";
  }

  const followUpDate = new Date(
    `${application.follow_up_date.slice(0, 10)}T00:00:00`
  );
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  if (Number.isNaN(followUpDate.getTime())) {
    return "";
  }

  const differenceInDays = Math.round(
    (followUpDate - today) / 86400000
  );

  let reminderClass = "upcoming";
  let reminderText = `Follow up on ${formatApplicationDisplayDate(
    application.follow_up_date
  )}`;

  if (differenceInDays < 0) {
    reminderClass = "overdue";
    reminderText = `Follow-up overdue since ${formatApplicationDisplayDate(
      application.follow_up_date
    )}`;
  } else if (differenceInDays === 0) {
    reminderClass = "due-today";
    reminderText = "Follow-up due today";
  } else if (differenceInDays === 1) {
    reminderText = "Follow-up due tomorrow";
  }

  return `
    <div class="application-follow-up-reminder ${reminderClass}">
      <strong>Reminder:</strong>
      ${escapeEmployerHtml(reminderText)}
    </div>
  `;
}


function buildApplicationHistoryTimeline(application) {
  const history = Array.isArray(application.history)
    ? application.history
    : [];

  if (history.length === 0) {
    return "";
  }

  const historyItems = history.map(entry => `
    <li class="application-history-item">
      <span class="application-history-marker" aria-hidden="true"></span>
      <div>
        <strong>${escapeEmployerHtml(
          describeApplicationHistoryEntry(entry)
        )}</strong>
        <small>
          ${escapeEmployerHtml(
            formatApplicationHistoryTimestamp(entry.created_at)
          )}
          &middot;
          ${escapeEmployerHtml(
            describeApplicationUpdateSource(entry.changed_by_type)
          )}
        </small>
      </div>
    </li>
  `).join("");

  return `
    <details class="application-history">
      <summary>
        Application history (${history.length})
      </summary>
      <ol>${historyItems}</ol>
    </details>
  `;
}


function describeApplicationHistoryEntry(entry) {
  if (entry.event_type === "application_created") {
    return `Application added with status ${entry.new_value || "Interested"}`;
  }

  if (entry.field_name === "status") {
    return `Status changed from ${entry.old_value || "Not set"} to ${entry.new_value || "Not set"}`;
  }

  const fieldLabels = {
    applied_at: "Application date",
    interview_date: "Interview date",
    interview_time: "Interview time",
    interview_format: "Interview format",
    interview_location: "Interview location or link",
    interview_details: "Interview details",
    follow_up_date: "Follow-up reminder"
  };

  const fieldLabel = fieldLabels[entry.field_name] || "Application information";

  if (!entry.new_value) {
    return `${fieldLabel} cleared`;
  }

  return `${fieldLabel} updated to ${entry.new_value}`;
}


function describeApplicationUpdateSource(source) {
  if (source === "employer") {
    return "Updated by employer";
  }

  if (source === "system") {
    return "Updated by PathForge";
  }

  return "Updated by you";
}


function formatApplicationHistoryTimestamp(value) {
  if (!value) {
    return "Date unavailable";
  }

  const normalizedValue = String(value).includes("T")
    ? value
    : `${value.replace(" ", "T")}Z`;
  const parsedDate = new Date(normalizedValue);

  if (Number.isNaN(parsedDate.getTime())) {
    return value;
  }

  return parsedDate.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit"
  });
}


function buildEmployerManagedInterviewDetails(application) {
  const hasInterview = Boolean(
    application.interview_date
    || application.interview_time
    || application.interview_format
    || application.interview_location
    || application.interview_details
  );

  if (!hasInterview) {
    return `
      <div class="application-field">
        <span class="application-readonly-label">
          Interview
        </span>

        <span class="application-readonly-value">
          Not scheduled
        </span>

        <small class="application-managed-note">
          Interview details will appear here when provided
          by the employer.
        </small>
      </div>
    `;
  }

  const locationMarkup =
    application.interview_location
      ? `
        <p>
          <strong>Location or link:</strong>
          ${escapeEmployerHtml(
            application.interview_location
          )}
        </p>
      `
      : "";

  const detailsMarkup =
    application.interview_details
      ? `
        <p>
          <strong>Details:</strong>
          ${escapeEmployerHtml(
            application.interview_details
          )}
        </p>
      `
      : "";

  return `
    <div class="application-field application-interview-summary">
      <span class="application-readonly-label">
        Interview
      </span>

      <div class="application-interview-details">
        <p>
          <strong>Date:</strong>
          ${escapeEmployerHtml(
            formatApplicationDisplayDate(
              application.interview_date
            )
          )}
        </p>

        <p>
          <strong>Time:</strong>
          ${escapeEmployerHtml(
            application.interview_time
            || "Not provided"
          )}
        </p>

        <p>
          <strong>Format:</strong>
          ${escapeEmployerHtml(
            application.interview_format
            || "Not provided"
          )}
        </p>

        ${locationMarkup}
        ${detailsMarkup}
      </div>
    </div>
  `;
}


function formatApplicationDisplayDate(value) {
  if (!value) {
    return "Not provided";
  }

  const parsedDate = new Date(
    String(value).includes("T")
      ? value
      : `${value}T00:00:00`
  );

  if (Number.isNaN(parsedDate.getTime())) {
    return String(value);
  }

  return parsedDate.toLocaleDateString(
    undefined,
    {
      year: "numeric",
      month: "long",
      day: "numeric"
    }
  );
}

function buildApplicationStatusOptions(
  selectedStatus
) {
  const statuses = [
    "Interested",
    "Applied",
    "Application Viewed",
    "Under Review",
    "Interview Scheduled",
    "Interview Completed",
    "Offer Extended",
    "Accepted",
    "Rejected",
    "Withdrawn"
  ];

  return statuses
    .map(status => {
      const selected =
        status === selectedStatus
          ? "selected"
          : "";

      return `
        <option value="${status}" ${selected}>
          ${status}
        </option>
      `;
    })
    .join("");
}

function formatDateForInput(value) {
  if (!value) {
    return "";
  }

  return value.slice(0, 10);
}


function formatDateTimeForInput(value) {
  if (!value) {
    return "";
  }

  return value.slice(0, 16);
}

const applicationAutoSaveTimers = new Map();
const applicationSaveStates = new Map();

function enableApplicationAutoSave(form, applicationId) {
  if (!form) {
    return;
  }

  form.addEventListener("submit", event => {
    event.preventDefault();
  });

  applicationSaveStates.set(applicationId, {
    inFlight: false,
    pending: false
  });

  form.querySelectorAll("select, input").forEach(field => {
    field.addEventListener("change", () => {
      window.clearTimeout(
        applicationAutoSaveTimers.get(applicationId)
      );
      saveApplicationChanges(form, applicationId);
    });
  });

  form.querySelectorAll("textarea").forEach(field => {
    field.addEventListener("input", () => {
      window.clearTimeout(
        applicationAutoSaveTimers.get(applicationId)
      );

      const timer = window.setTimeout(() => {
        saveApplicationChanges(form, applicationId);
      }, 700);

      applicationAutoSaveTimers.set(applicationId, timer);
    });
  });
}

async function saveApplicationChanges(form, applicationId) {
  const saveState = applicationSaveStates.get(applicationId) || {
    inFlight: false,
    pending: false
  };

  applicationSaveStates.set(applicationId, saveState);

  if (saveState.inFlight) {
    saveState.pending = true;
    return;
  }

  saveState.inFlight = true;

  const message =
    form.querySelector(".application-message");

  applicationAutoSaveTimers.delete(applicationId);
  form.setAttribute("aria-busy", "true");
  message.textContent = "Saving changes…";

  message.classList.remove(
    "success-message",
    "error-message"
  );

  const employerManaged =
    form.dataset.employerManaged === "true";

  const applicationData = {
    follow_up_date:
      form.querySelector(
        ".application-follow-up-date"
      ).value || null,

    notes:
      form.querySelector(".application-notes")
        .value
        .trim()
  };

  if (!employerManaged) {
    applicationData.status =
      form.querySelector(".application-status").value;

    applicationData.applied_at =
      form.querySelector(".application-applied-date")
        .value || null;

    applicationData.interview_date =
      form.querySelector(".application-interview-date")
        .value || null;

    applicationData.interview_time =
      form.querySelector(".application-interview-time")
        .value || null;

    applicationData.interview_format =
      form.querySelector(".application-interview-format")
        .value || null;

    applicationData.interview_location =
      form.querySelector(".application-interview-location")
        .value.trim() || null;

    applicationData.interview_details =
      form.querySelector(".application-interview-details-input")
        .value.trim() || null;
  }

  try {
    const response = await fetchWithTimeout(
      apiUrl(`/applications/${applicationId}`),
      {
        method: "PUT",

        headers: {
          "Content-Type": "application/json"
        },

        credentials: "include",

        body: JSON.stringify(applicationData)
      }
    );

    if (response.status === 401) {
      window.location.href = "login.html";
      return;
    }

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        data.detail ||
        "The application could not be updated."
      );
    }

    refreshApplicationCardAfterSave(
      form,
      applicationData,
      data
    );
    message.textContent = "All changes saved.";
    message.classList.add("success-message");

  } catch (error) {
    console.error(
      "Application update failed:",
      error
    );

    message.textContent = error.message;
    message.classList.add("error-message");

  } finally {
    saveState.inFlight = false;
    form.removeAttribute("aria-busy");

    if (saveState.pending && form.isConnected) {
      saveState.pending = false;
      saveApplicationChanges(form, applicationId);
    }

  }
}


function refreshApplicationCardAfterSave(
  form,
  applicationData,
  responseData
) {
  const card = form.closest(".application-card");

  if (!card) {
    return;
  }

  const source = card.querySelector(".application-update-source");

  if (source) {
    source.textContent = "Latest tracked update from you";
  }

  const historyMarkup = buildApplicationHistoryTimeline({
    history: responseData.history || []
  });
  const existingHistory = card.querySelector(".application-history");
  const historyWasOpen = Boolean(existingHistory?.open);

  if (existingHistory) {
    existingHistory.remove();
  }

  if (historyMarkup) {
    const actions = form.querySelector(".application-card-actions");
    actions.insertAdjacentHTML("beforebegin", historyMarkup);

    if (historyWasOpen) {
      form.querySelector(".application-history").open = true;
    }
  }

  const existingReminder = card.querySelector(
    ".application-follow-up-reminder"
  );
  const reminderMarkup = buildApplicationFollowUpReminder({
    follow_up_date: applicationData.follow_up_date
  });

  if (existingReminder) {
    existingReminder.remove();
  }

  if (reminderMarkup) {
    form.insertAdjacentHTML("beforebegin", reminderMarkup);
  }
}

async function deleteApplication(
  applicationId,
  button
) {
  const card = button.closest(".application-card");

  const message =
    card.querySelector(".application-message");

  const confirmed = window.confirm(
    "Remove this application from your tracker?"
  );

  if (!confirmed) {
    return;
  }

  button.disabled = true;
  button.textContent = "Removing...";

  try {
    const response = await fetch(
      apiUrl(`/applications/${applicationId}`),
      {
        method: "DELETE",
        credentials: "include"
      }
    );

    if (response.status === 401) {
      window.location.href = "login.html";
      return;
    }

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        data.detail ||
        "The application could not be removed."
      );
    }

    card.remove();
    applicationSaveStates.delete(applicationId);
    applicationAutoSaveTimers.delete(applicationId);

    const applicationsContainer =
      document.getElementById(
        "applicationsContainer"
      );

    if (
      applicationsContainer &&
      applicationsContainer.children.length === 0
    ) {
      displayApplications([]);
    }

  } catch (error) {
    console.error(
      "Application removal failed:",
      error
    );

    button.disabled = false;
    button.textContent = "Remove from Tracker";

    message.textContent = error.message;
    message.classList.add("error-message");
  }
}

function setupApplicationDialog() {
  const dialog =
    document.getElementById("applicationDialog");

  const closeButton =
    document.getElementById(
      "closeApplicationDialog"
    );

  if (!dialog || !closeButton) {
    return;
  }

  const internalForm =
    document.getElementById("internalApplicationForm");

  if (internalForm) {
    internalForm.addEventListener(
      "submit",
      function (event) {
        ApplicationService.submitInternalApplication(event);
      }
    );
  }

  closeButton.addEventListener(
    "click",
    closeApplicationDialog
  );


  closeButton.addEventListener(
    "click",
    closeApplicationDialog
  );

  dialog.addEventListener(
    "click",
    function (event) {
      if (event.target === dialog) {
        closeApplicationDialog();
      }
    }
  );

  document.addEventListener(
    "keydown",
    function (event) {
      if (
        event.key === "Escape" &&
        !dialog.classList.contains("hidden")
      ) {
        closeApplicationDialog();
      }
    }
  );
}

// =========================
// EMPLOYER JOB MANAGEMENT
// =========================

let employerJobs = [];

function escapeEmployerHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function cleanJobPostingText(value) {
  let decodedText = String(value || "");

  for (let index = 0; index < 2; index += 1) {
    const decoder = document.createElement("textarea");
    decoder.innerHTML = decodedText;
    decodedText = decoder.value;
  }

  const content = document.createElement("template");
  content.innerHTML = decodedText;

  return String(content.content.textContent || "")
    .replace(/\s+/g, " ")
    .trim();
}


function showEmployerMessage(element, text, type = "") {
  if (!element) {
    return;
  }

  element.textContent = text;
  element.classList.remove(
    "success-message",
    "error-message"
  );

  if (type === "success") {
    element.classList.add("success-message");
  }

  if (type === "error") {
    element.classList.add("error-message");
  }
}


async function readEmployerResponse(response) {
  try {
    return await response.json();
  } catch (error) {
    return {};
  }
}


function handleEmployerAuthorizationFailure(response) {
  if (response.status === 401) {
    window.location.href = "login.html";
    return true;
  }

  if (response.status === 403) {
    window.location.href = "employer-access.html";
    return true;
  }

  return false;
}


function toggleEmployerApplicationUrl(
  methodSelect,
  fieldContainer,
  urlInput
) {
  if (!methodSelect || !fieldContainer || !urlInput) {
    return;
  }

  const usesEmployerWebsite =
    methodSelect.value === "employer_website";

  fieldContainer.classList.toggle(
    "hidden",
    !usesEmployerWebsite
  );

  urlInput.required = usesEmployerWebsite;

  if (!usesEmployerWebsite) {
    urlInput.value = "";
  }
}


// Confirm employer access before loading jobs, applicants, statistics, or company data.
async function loadEmployerDashboard() {
  const jobsList =
    document.getElementById("employerJobsList");

  if (!jobsList) {
    return;
  }

  const dashboardMessage =
    document.getElementById("employerDashboardMessage");

  const welcomeHeading =
    document.getElementById("employerDashboardWelcome");

  try {
    const userResponse = await fetch(
      apiUrl("/me"),
      {
        credentials: "include"
      }
    );

    if (handleEmployerAuthorizationFailure(userResponse)) {
      return;
    }

    if (!userResponse.ok) {
      throw new Error("Employer account could not be loaded.");
    }

    const user = await userResponse.json();

    if (user.role !== "employer") {
      window.location.href = "employer-access.html";
      return;
    }

    if (welcomeHeading) {
      welcomeHeading.textContent =
        "Welcome, " + user.username;
    }

    await loadEmployerStatistics();
    await loadEmployerCompanyProfile();
    await loadEmployerJobs();
    await loadEmployerApplications();

  } catch (error) {
    console.error(
      "Employer dashboard load failed:",
      error
    );

    jobsList.innerHTML = `
      <div class="employer-empty-state">
        <h3>Your jobs could not be loaded</h3>
        <p>
          Make sure the PathForge backend is running,
          then refresh this page.
        </p>
      </div>
    `;

    showEmployerMessage(
      dashboardMessage,
      "The employer dashboard could not connect to the backend.",
      "error"
    );
  }
}


async function loadEmployerJobs() {
  const jobsList =
    document.getElementById("employerJobsList");

  if (!jobsList) {
    return;
  }

  jobsList.innerHTML = buildContentLoadingState("Loading your jobs", 2);

  try {
    const response = await fetch(
      apiUrl("/employer/jobs"),
      {
        credentials: "include"
      }
    );

    if (handleEmployerAuthorizationFailure(response)) {
      return;
    }

    const data = await readEmployerResponse(response);

    if (!response.ok) {
      throw new Error(
        data.detail || "Employer jobs could not be loaded."
      );
    }

    employerJobs = data.jobs || [];
    displayEmployerJobs(employerJobs);

  } catch (error) {
    console.error("Employer jobs load failed:", error);

    jobsList.innerHTML = `
      <div class="employer-empty-state">
        <h3>Your jobs could not be loaded</h3>
        <p>${escapeEmployerHtml(error.message)}</p>
        <button type="button" data-action="reload-employer-jobs">Try Again</button>
      </div>
    `;
  }
}


function displayEmployerJobs(jobs) {
  const jobsList =
    document.getElementById("employerJobsList");

  const jobsCount =
    document.getElementById("employerJobsCount");

  if (!jobsList) {
    return;
  }

  if (jobsCount) {
    jobsCount.textContent =
      jobs.length +
      (jobs.length === 1 ? " job" : " jobs");
  }

  jobsList.innerHTML = "";

  if (jobs.length === 0) {
    jobsList.innerHTML = `
      <div class="employer-empty-state">
        <h3>No jobs posted yet</h3>
        <p>
          Use the form above to create your first
          employer-owned job listing.
        </p>
        <a class="empty-state-link" href="#postJob">Post Your First Job</a>
      </div>
    `;

    return;
  }

  jobs.forEach(job => {
    const card = document.createElement("article");
    card.className = "employer-job-card";
    card.dataset.jobId = job.id;

    const applicationMethod =
      job.application_method === "employer_website"
        ? "Employer website"
        : "PathForge";

    const deadlinePassed =
      applicationDeadlineHasPassed(job.application_deadline);

      const applicationFormButton =
        job.application_method === "pathforge"
          ? `
            <button
              type="button"
              class="application-form-button"
              data-action="open-application-form-builder"
              data-job-id="${job.id}"
            >
              Application Form
            </button>
        `
        : "";

    const applicationLink = job.application_url
      ? `
        <p>
          <strong>Application website:</strong>
          <a
            href="${escapeEmployerHtml(job.application_url)}"
            target="_blank"
            rel="noopener noreferrer"
          >
            Open link
          </a>
        </p>
      `
      : "";

    card.innerHTML = `
      <div class="employer-job-heading">
        <div>
          <h3>${escapeEmployerHtml(job.title)}</h3>

          <p class="employer-job-company">
            ${escapeEmployerHtml(job.company)}
          </p>
        </div>

        <span
          class="
            job-status-badge
            job-status-${escapeEmployerHtml(job.status)}
          "
        >
          ${escapeEmployerHtml(
            job.status.charAt(0).toUpperCase() +
            job.status.slice(1)
          )}
        </span>
      </div>

      <div class="employer-job-details">
        <p>
          <strong>Location:</strong>
          ${escapeEmployerHtml(job.location)}
        </p>

        <p>
          <strong>Pay:</strong>
          ${escapeEmployerHtml(job.pay)}
        </p>

        <p>
          <strong>Schedule:</strong>
          ${escapeEmployerHtml(job.schedule)}
        </p>

        <p>
          <strong>Experience:</strong>
          ${escapeEmployerHtml(job.experience)}
        </p>

        <p>
          <strong>Category:</strong>
          ${escapeEmployerHtml(job.category)}
        </p>

        <p>
          <strong>Applications:</strong>
          ${escapeEmployerHtml(applicationMethod)}
        </p>

        ${job.application_deadline ? `
          <p class="${deadlinePassed ? "deadline-passed" : ""}">
            <strong>Application deadline:</strong>
            ${escapeEmployerHtml(
              formatApplicationDeadline(job.application_deadline)
            )}
            ${deadlinePassed ? " (passed)" : ""}
          </p>
        ` : ""}

        ${applicationLink}
      </div>

      <p class="employer-job-description">
        ${escapeEmployerHtml(cleanJobPostingText(job.description))}
      </p>

      ${job.requirements ? `
        <p class="employer-job-description">
          <strong>Requirements:</strong>
          ${escapeEmployerHtml(cleanJobPostingText(job.requirements))}
        </p>
      ` : ""}

      ${job.preferred_qualifications ? `
        <p class="employer-job-description">
          <strong>Preferred qualifications:</strong>
          ${escapeEmployerHtml(
            cleanJobPostingText(job.preferred_qualifications)
          )}
        </p>
      ` : ""}

      <div class="employer-job-controls">
        <div class="employer-status-control">
          <label for="employer-status-${job.id}">
            Status
          </label>

          <select
            id="employer-status-${job.id}"
            data-action="update-employer-job-status"
            data-job-id="${job.id}"
          >
            ${buildEmployerStatusOptions(job.status)}
          </select>
        </div>

                <div class="employer-job-actions">
          ${applicationFormButton}

          <button
            type="button"
            class="employer-edit-button"
            data-action="edit-employer-job"
            data-job-id="${job.id}"
          >
            Edit
          </button>

          <button
            type="button"
            class="employer-delete-button"
            data-action="delete-employer-job"
            data-job-id="${job.id}"
          >
            Delete
          </button>
        </div>

      </div>

      <p
        class="employer-job-card-message"
        role="status"
        aria-live="polite"
      ></p>
    `;

    jobsList.appendChild(card);
  });
}


function buildEmployerStatusOptions(selectedStatus) {
  const statuses = [
    {
      value: "active",
      label: "Active"
    },
    {
      value: "draft",
      label: "Draft"
    },
    {
      value: "closed",
      label: "Closed"
    }
  ];

  return statuses
    .map(status => {
      const selected =
        status.value === selectedStatus
          ? "selected"
          : "";

      return `
        <option value="${status.value}" ${selected}>
          ${status.label}
        </option>
      `;
    })
    .join("");
}


function getNewEmployerJobData() {
  return {
    title:
      document.getElementById("employerJobTitle").value.trim(),

    company:
      document.getElementById("employerJobCompany").value.trim(),

    location:
      document.getElementById("employerJobLocation").value.trim(),

    pay:
      document.getElementById("employerJobPay").value.trim(),

    description:
      document
        .getElementById("employerJobDescription")
        .value
        .trim(),

    requirements:
      document
        .getElementById("employerJobRequirements")
        .value
        .trim()
      || null,

    preferred_qualifications:
      document
        .getElementById("employerJobPreferredQualifications")
        .value
        .trim()
      || null,

    schedule:
      document.getElementById("employerJobSchedule").value.trim(),

    experience:
      document
        .getElementById("employerJobExperience")
        .value
        .trim(),

    category:
      document.getElementById("employerJobCategory").value.trim(),

    application_method:
      document.getElementById("employerApplicationMethod").value,

    application_url:
      document.getElementById("employerApplicationUrl").value.trim()
      || null,

    application_deadline:
      document.getElementById("employerJobDeadline").value
      || null,

    status:
      document.getElementById("employerJobStatus").value
  };
}


function setupEmployerJobForm() {
  const form =
    document.getElementById("employerJobForm");

  if (!form) {
    return;
  }

  const methodSelect =
    document.getElementById("employerApplicationMethod");

  const urlField =
    document.getElementById("employerApplicationUrlField");

  const urlInput =
    document.getElementById("employerApplicationUrl");

  const deadlineInput =
    document.getElementById("employerJobDeadline");

  if (deadlineInput) {
    deadlineInput.min =
      new Date().toISOString().split("T")[0];
  }

  methodSelect.addEventListener("change", function () {
    toggleEmployerApplicationUrl(
      methodSelect,
      urlField,
      urlInput
    );
  });

  toggleEmployerApplicationUrl(
    methodSelect,
    urlField,
    urlInput
  );

  form.addEventListener("submit", async function (event) {
    event.preventDefault();

    const submitButton =
      document.getElementById("employerJobSubmitButton");

    const message =
      document.getElementById("employerJobFormMessage");

    const jobData = getNewEmployerJobData();

    submitButton.disabled = true;
    submitButton.textContent = "Posting...";

    showEmployerMessage(message, "");

    try {
      const response = await fetch(
        apiUrl("/jobs"),
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          credentials: "include",
          body: JSON.stringify(jobData)
        }
      );

      if (handleEmployerAuthorizationFailure(response)) {
        return;
      }

      const data = await readEmployerResponse(response);

      if (!response.ok) {
        let errorMessage =
          "The application form could not be saved.";

      if (typeof data.detail === "string") {
        errorMessage = data.detail;
      } else if (Array.isArray(data.detail)) {
        errorMessage = data.detail
          .map(error => error.msg || "Invalid form value.")
          .join(" ");
      }

      throw new Error(errorMessage);
    }

      form.reset();

      toggleEmployerApplicationUrl(
        methodSelect,
        urlField,
        urlInput
      );

      showEmployerMessage(
        message,
        data.message || "Job created successfully.",
        "success"
      );

      await loadEmployerJobs();
      await loadEmployerStatistics();

    } catch (error) {
      console.error("Employer job creation failed:", error);

      showEmployerMessage(
        message,
        error.message,
        "error"
      );

    } finally {
      submitButton.disabled = false;
      submitButton.textContent = "Save Job";
    }
  });
}


function openEmployerJobEditor(jobId) {
  const job = employerJobs.find(
    employerJob => employerJob.id === jobId
  );

  if (!job) {
    return;
  }

  document.getElementById("editEmployerJobId").value =
    job.id;

  document.getElementById("editEmployerJobTitle").value =
    job.title;

  document.getElementById("editEmployerJobCompany").value =
    job.company;

  document.getElementById("editEmployerJobLocation").value =
    job.location;

  document.getElementById("editEmployerJobPay").value =
    job.pay;

  document.getElementById("editEmployerJobSchedule").value =
    job.schedule;

  document.getElementById("editEmployerJobExperience").value =
    job.experience;

  document.getElementById("editEmployerJobCategory").value =
    job.category;

  document.getElementById("editEmployerJobStatus").value =
    job.status;

  document.getElementById(
    "editEmployerApplicationMethod"
  ).value = job.application_method;

  document.getElementById(
    "editEmployerApplicationUrl"
  ).value = job.application_url || "";

  document.getElementById(
    "editEmployerJobDescription"
  ).value = job.description;

  document.getElementById(
    "editEmployerJobRequirements"
  ).value = job.requirements || "";

  document.getElementById(
    "editEmployerJobPreferredQualifications"
  ).value = job.preferred_qualifications || "";

  document.getElementById(
    "editEmployerJobDeadline"
  ).value = job.application_deadline || "";

  const methodSelect =
    document.getElementById(
      "editEmployerApplicationMethod"
    );

  const urlField =
    document.getElementById(
      "editEmployerApplicationUrlField"
    );

  const urlInput =
    document.getElementById(
      "editEmployerApplicationUrl"
    );

  toggleEmployerApplicationUrl(
    methodSelect,
    urlField,
    urlInput
  );

  showEmployerMessage(
    document.getElementById("employerJobEditMessage"),
    ""
  );

  const dialog =
    document.getElementById("employerJobEditDialog");

  dialog.classList.remove("hidden");

  document.getElementById("editEmployerJobTitle").focus();
}


function closeEmployerJobEditor() {
  const dialog =
    document.getElementById("employerJobEditDialog");

  if (!dialog) {
    return;
  }

  dialog.classList.add("hidden");
}


function getEditedEmployerJobData() {
  return {
    title:
      document
        .getElementById("editEmployerJobTitle")
        .value
        .trim(),

    company:
      document
        .getElementById("editEmployerJobCompany")
        .value
        .trim(),

    location:
      document
        .getElementById("editEmployerJobLocation")
        .value
        .trim(),

    pay:
      document
        .getElementById("editEmployerJobPay")
        .value
        .trim(),

    description:
      document
        .getElementById("editEmployerJobDescription")
        .value
        .trim(),

    requirements:
      document
        .getElementById("editEmployerJobRequirements")
        .value
        .trim()
      || null,

    preferred_qualifications:
      document
        .getElementById("editEmployerJobPreferredQualifications")
        .value
        .trim()
      || null,

    schedule:
      document
        .getElementById("editEmployerJobSchedule")
        .value
        .trim(),

    experience:
      document
        .getElementById("editEmployerJobExperience")
        .value
        .trim(),

    category:
      document
        .getElementById("editEmployerJobCategory")
        .value
        .trim(),

    application_method:
      document.getElementById(
        "editEmployerApplicationMethod"
      ).value,

    application_url:
      document
        .getElementById("editEmployerApplicationUrl")
        .value
        .trim()
      || null,

    application_deadline:
      document.getElementById(
        "editEmployerJobDeadline"
      ).value
      || null,

    status:
      document.getElementById("editEmployerJobStatus").value
  };
}


function setupEmployerJobEditor() {
  const form =
    document.getElementById("employerJobEditForm");

  if (!form) {
    return;
  }

  const methodSelect =
    document.getElementById(
      "editEmployerApplicationMethod"
    );

  const urlField =
    document.getElementById(
      "editEmployerApplicationUrlField"
    );

  const urlInput =
    document.getElementById(
      "editEmployerApplicationUrl"
    );

  const deadlineInput =
    document.getElementById("editEmployerJobDeadline");

  if (deadlineInput) {
    deadlineInput.min =
      new Date().toISOString().split("T")[0];
  }

  methodSelect.addEventListener("change", function () {
    toggleEmployerApplicationUrl(
      methodSelect,
      urlField,
      urlInput
    );
  });

  const closeButton =
    document.getElementById("closeEmployerEditDialog");

  const cancelButton =
    document.getElementById("cancelEmployerJobEdit");

  closeButton.addEventListener(
    "click",
    closeEmployerJobEditor
  );

  cancelButton.addEventListener(
    "click",
    closeEmployerJobEditor
  );

  const dialog =
    document.getElementById("employerJobEditDialog");

  dialog.addEventListener("click", function (event) {
    if (event.target === dialog) {
      closeEmployerJobEditor();
    }
  });

  document.addEventListener("keydown", function (event) {
    if (
      event.key === "Escape"
      && !dialog.classList.contains("hidden")
    ) {
      closeEmployerJobEditor();
    }
  });

  form.addEventListener("submit", async function (event) {
    event.preventDefault();

    const jobId = Number(
      document.getElementById("editEmployerJobId").value
    );

    const submitButton =
      document.getElementById(
        "employerJobEditSubmitButton"
      );

    const message =
      document.getElementById("employerJobEditMessage");

    const jobData = getEditedEmployerJobData();

    submitButton.disabled = true;
    submitButton.textContent = "Saving...";

    showEmployerMessage(message, "");

    try {
      const response = await fetch(
        apiUrl(`/employer/jobs/${jobId}`),
        {
          method: "PUT",
          headers: {
            "Content-Type": "application/json"
          },
          credentials: "include",
          body: JSON.stringify(jobData)
        }
      );

      if (handleEmployerAuthorizationFailure(response)) {
        return;
      }

      const data = await readEmployerResponse(response);

      if (!response.ok) {
        throw new Error(
          data.detail || "The job could not be updated."
        );
      }

      await loadEmployerJobs();
      await loadEmployerStatistics();
      closeEmployerJobEditor();

      showEmployerMessage(
        document.getElementById(
          "employerDashboardMessage"
        ),
        data.message || "Job updated successfully.",
        "success"
      );

    } catch (error) {
      console.error("Employer job update failed:", error);

      showEmployerMessage(
        message,
        error.message,
        "error"
      );

    } finally {
      submitButton.disabled = false;
      submitButton.textContent = "Save Changes";
    }
  });
}


async function updateEmployerJobStatus(
  jobId,
  newStatus,
  selectElement
) {
  const job = employerJobs.find(
    employerJob => employerJob.id === jobId
  );

  if (!job) {
    return;
  }

  const previousStatus = job.status;
  selectElement.disabled = true;

  const card = selectElement.closest(".employer-job-card");

  const message = card
    ? card.querySelector(".employer-job-card-message")
    : null;

  showEmployerMessage(message, "Updating status...");

  try {
    const response = await fetch(
      apiUrl(`/employer/jobs/${jobId}/status`),
      {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json"
        },
        credentials: "include",
        body: JSON.stringify({
          status: newStatus
        })
      }
    );

    if (handleEmployerAuthorizationFailure(response)) {
      return;
    }

    const data = await readEmployerResponse(response);

    if (!response.ok) {
      throw new Error(
        data.detail || "The job status could not be updated."
      );
    }

    job.status = newStatus;

    showEmployerMessage(
      message,
      data.message || "Job status updated.",
      "success"
    );

    await loadEmployerJobs();
    await loadEmployerStatistics();

  } catch (error) {
    console.error(
      "Employer job status update failed:",
      error
    );

    selectElement.value = previousStatus;

    showEmployerMessage(
      message,
      error.message,
      "error"
    );

  } finally {
    selectElement.disabled = false;
  }
}


async function deleteEmployerJob(jobId, button) {
  const job = employerJobs.find(
    employerJob => employerJob.id === jobId
  );

  if (!job) {
    return;
  }

  const confirmed = window.confirm(
    `Delete "${job.title}"? This cannot be undone.`
  );

  if (!confirmed) {
    return;
  }

  const card = button.closest(".employer-job-card");

  const message = card
    ? card.querySelector(".employer-job-card-message")
    : null;

  button.disabled = true;
  button.textContent = "Deleting...";

  showEmployerMessage(message, "");

  try {
    const response = await fetch(
      apiUrl(`/employer/jobs/${jobId}`),
      {
        method: "DELETE",
        credentials: "include"
      }
    );

    if (handleEmployerAuthorizationFailure(response)) {
      return;
    }

    const data = await readEmployerResponse(response);

    if (!response.ok) {
      throw new Error(
        data.detail || "The job could not be deleted."
      );
    }

    showEmployerMessage(
      document.getElementById(
        "employerDashboardMessage"
      ),
      data.message || "Job deleted successfully.",
      "success"
    );

    await loadEmployerJobs();
    await loadEmployerStatistics();

  } catch (error) {
    console.error("Employer job deletion failed:", error);

    showEmployerMessage(
      message,
      error.message,
      "error"
    );

    button.disabled = false;
    button.textContent = "Delete";
  }
}

// =========================
// EMPLOYER APPLICATION FORM BUILDER
// =========================

let applicationQuestionCounter = 0;


function createApplicationQuestionRow(question = null) {
  const questionList =
    document.getElementById("applicationQuestionList");

  if (!questionList) {
    return;
  }

  if (questionList.children.length >= 10) {
    showEmployerMessage(
      document.getElementById(
        "applicationFormBuilderMessage"
      ),
      "An application form can contain no more than 10 questions.",
      "error"
    );

    return;
  }

  applicationQuestionCounter += 1;

  const row = document.createElement("div");
  row.className = "application-question-builder-row";
  row.dataset.questionNumber = applicationQuestionCounter;

  const questionText = question
    ? question.question_text
    : "";

  const fieldType = question
    ? question.field_type
    : "short_text";

  const isRequired = question
    ? Boolean(question.is_required)
    : true;

  row.innerHTML = `
    <div class="application-question-row-heading">
      <h3>
        Question
        <span class="application-question-number"></span>
      </h3>

      <button
        type="button"
        class="application-question-remove-button"
        aria-label="Remove this application question"
      >
        Remove
      </button>
    </div>

    <div class="application-question-builder-grid">
      <div class="employer-form-field">
        <label>
          Question text
        </label>

        <input
          type="text"
          class="application-question-text"
          maxlength="300"
          value="${escapeEmployerHtml(questionText)}"
          required
        >
      </div>

      <div class="employer-form-field">
        <label>
          Answer type
        </label>

        <select class="application-question-type">
          <option
            value="short_text"
            ${fieldType === "short_text" ? "selected" : ""}
          >
            Short answer
          </option>

          <option
            value="long_text"
            ${fieldType === "long_text" ? "selected" : ""}
          >
            Long answer
          </option>

          <option
            value="yes_no"
            ${fieldType === "yes_no" ? "selected" : ""}
          >
            Yes or No
          </option>
        </select>
      </div>

      <label class="application-question-required">
        <input
          type="checkbox"
          class="application-question-required-input"
          ${isRequired ? "checked" : ""}
        >

        Required question
      </label>
    </div>
  `;

  const removeButton = row.querySelector(
    ".application-question-remove-button"
  );

  removeButton.addEventListener("click", function () {
    row.remove();
    updateApplicationQuestionNumbers();

    showEmployerMessage(
      document.getElementById(
        "applicationFormBuilderMessage"
      ),
      ""
    );
  });

  questionList.appendChild(row);
  updateApplicationQuestionNumbers();
}


function updateApplicationQuestionNumbers() {
  const rows = document.querySelectorAll(
    ".application-question-builder-row"
  );

  rows.forEach((row, index) => {
    const number = row.querySelector(
      ".application-question-number"
    );

    if (number) {
      number.textContent = index + 1;
    }
  });

  const addButton =
    document.getElementById(
      "addApplicationQuestionButton"
    );

  if (addButton) {
    addButton.disabled = rows.length >= 10;
  }
}


async function openApplicationFormBuilder(jobId) {
  const job = employerJobs.find(
    employerJob => employerJob.id === jobId
  );

  if (!job) {
    return;
  }

  if (job.application_method !== "pathforge") {
    showEmployerMessage(
      document.getElementById(
        "employerDashboardMessage"
      ),
      (
        "Custom forms are only available for jobs "
        + "using PathForge applications."
      ),
      "error"
    );

    return;
  }

  const dialog =
    document.getElementById(
      "applicationFormBuilderDialog"
    );

  const questionList =
    document.getElementById(
      "applicationQuestionList"
    );

  const jobIdInput =
    document.getElementById(
      "applicationBuilderJobId"
    );

  const jobName =
    document.getElementById(
      "applicationBuilderJobName"
    );

  const message =
    document.getElementById(
      "applicationFormBuilderMessage"
    );

  if (
    !dialog
    || !questionList
    || !jobIdInput
    || !jobName
  ) {
    return;
  }

  jobIdInput.value = job.id;

  jobName.textContent =
    `Create application questions for ${job.title}.`;

  questionList.innerHTML = "";

  showEmployerMessage(
    message,
    "Loading application form..."
  );

  dialog.classList.remove("hidden");

  try {
    const response = await fetch(
      apiUrl(`/employer/jobs/${job.id}/application-form`),
      {
        credentials: "include"
      }
    );

    if (handleEmployerAuthorizationFailure(response)) {
      return;
    }

    const data = await readEmployerResponse(response);

    if (!response.ok) {
      throw new Error(
        data.detail || "The application form could not be loaded."
      );
    }

    questionList.innerHTML = "";

    const questions = data.questions || [];

    questions.forEach(question => {
      createApplicationQuestionRow(question);
    });

    showEmployerMessage(message, "");

    if (questions.length === 0) {
      createApplicationQuestionRow();
    }

    const firstInput = questionList.querySelector(
      ".application-question-text"
    );

    if (firstInput) {
      firstInput.focus();
    }

  } catch (error) {
    console.error(
      "Application form load failed:",
      error
    );

    showEmployerMessage(
      message,
      error.message,
      "error"
    );
  }
}


function closeApplicationFormBuilder() {
  const dialog =
    document.getElementById(
      "applicationFormBuilderDialog"
    );

  if (!dialog) {
    return;
  }

  dialog.classList.add("hidden");

  const questionList =
    document.getElementById(
      "applicationQuestionList"
    );

  if (questionList) {
    questionList.innerHTML = "";
  }
}


function collectApplicationQuestions() {
  const rows = document.querySelectorAll(
    ".application-question-builder-row"
  );

  const questions = [];

  rows.forEach(row => {
    const questionText = row
      .querySelector(".application-question-text")
      .value
      .trim();

    const fieldType = row
      .querySelector(".application-question-type")
      .value;

    const isRequired = row
      .querySelector(
        ".application-question-required-input"
      )
      .checked;

    questions.push({
      question_text: questionText,
      field_type: fieldType,
      is_required: isRequired
    });
  });

  return questions;
}


async function saveEmployerApplicationForm() {
  const jobId = Number(
    document.getElementById(
      "applicationBuilderJobId"
    ).value
  );

  const saveButton =
    document.getElementById(
      "saveApplicationFormButton"
    );

  const message =
    document.getElementById(
      "applicationFormBuilderMessage"
    );

  const questions = collectApplicationQuestions();

  const hasBlankQuestion = questions.some(
    question => question.question_text === ""
  );

  if (hasBlankQuestion) {
    showEmployerMessage(
      message,
      "Application questions cannot be blank.",
      "error"
    );

    return;
  }

  const normalizedQuestions = questions.map(
    question => question.question_text.toLowerCase()
  );

  const uniqueQuestions = new Set(normalizedQuestions);

  if (uniqueQuestions.size !== normalizedQuestions.length) {
    showEmployerMessage(
      message,
      "Duplicate application questions are not allowed.",
      "error"
    );

    return;
  }

  saveButton.disabled = true;
  saveButton.textContent = "Saving...";

  showEmployerMessage(
    message,
    "Saving application form..."
  );

  try {
    const response = await fetch(
      apiUrl(`/employer/jobs/${jobId}/application-form`),
      {
        method: "PUT",
        headers: {
          "Content-Type": "application/json"
        },
        credentials: "include",
        body: JSON.stringify({
          questions: questions
        })
      }
    );

    if (handleEmployerAuthorizationFailure(response)) {
      return;
    }

    const data = await readEmployerResponse(response);

    if (!response.ok) {
      throw new Error(
        data.detail || "The application form could not be saved."
      );
    }

    showEmployerMessage(
      message,
      data.message || "Application form saved successfully.",
      "success"
    );

    showEmployerMessage(
      document.getElementById(
        "employerDashboardMessage"
      ),
      data.message || "Application form saved successfully.",
      "success"
    );

    setTimeout(function () {
      closeApplicationFormBuilder();
    }, 700);

  } catch (error) {
    console.error(
      "Application form save failed:",
      error
    );

    showEmployerMessage(
      message,
      error.message,
      "error"
    );

  } finally {
    saveButton.disabled = false;
    saveButton.textContent = "Save Application Form";
  }
}


function setupEmployerApplicationFormBuilder() {
  const dialog =
    document.getElementById(
      "applicationFormBuilderDialog"
    );

  if (!dialog) {
    return;
  }

  const closeButton =
    document.getElementById(
      "closeApplicationFormBuilder"
    );

  const cancelButton =
    document.getElementById(
      "cancelApplicationFormBuilder"
    );

  const addButton =
    document.getElementById(
      "addApplicationQuestionButton"
    );

  const saveButton =
    document.getElementById(
      "saveApplicationFormButton"
    );

  closeButton.addEventListener(
    "click",
    closeApplicationFormBuilder
  );

  cancelButton.addEventListener(
    "click",
    closeApplicationFormBuilder
  );

  addButton.addEventListener("click", function () {
    createApplicationQuestionRow();
  });

  saveButton.addEventListener(
    "click",
    saveEmployerApplicationForm
  );

  dialog.addEventListener("click", function (event) {
    if (event.target === dialog) {
      closeApplicationFormBuilder();
    }
  });

  document.addEventListener("keydown", function (event) {
    if (
      event.key === "Escape"
      && !dialog.classList.contains("hidden")
    ) {
      closeApplicationFormBuilder();
    }
  });
}

// =========================
// EMPLOYER RECEIVED APPLICATIONS
// =========================

async function loadEmployerApplications() {
  const applicationsList =
    document.getElementById(
      "employerApplicationsList"
    );

  if (!applicationsList) {
    return;
  }

  applicationsList.innerHTML = buildContentLoadingState(
    "Loading received applications",
    2
  );

  try {
    const response = await fetch(
      apiUrl("/employer/applications"),
      {
        credentials: "include"
      }
    );

    if (handleEmployerAuthorizationFailure(response)) {
      return;
    }

    const data = await readEmployerResponse(response);

    if (!response.ok) {
      let errorMessage =
        "Received applications could not be loaded.";

      if (typeof data.detail === "string") {
        errorMessage = data.detail;
      } else if (Array.isArray(data.detail)) {
        errorMessage = data.detail
          .map(error => {
            return error.msg || "Invalid request.";
          })
          .join(" ");
      }

      throw new Error(errorMessage);
    }

    displayEmployerApplications(
      data.applications || []
    );

  } catch (error) {
    console.error(
      "Employer applications load failed:",
      error
    );

    applicationsList.innerHTML = `
      <div class="employer-empty-state">
        <h3>Applications could not be loaded</h3>

        <p>
          ${escapeEmployerHtml(error.message)}
        </p>
        <button type="button" data-action="reload-employer-applications">Try Again</button>
      </div>
    `;
  }
}


function displayEmployerApplications(applications) {
  const applicationsList =
    document.getElementById(
      "employerApplicationsList"
    );

  const applicationsCount =
    document.getElementById(
      "employerApplicationsCount"
    );

  if (!applicationsList) {
    return;
  }

  if (applicationsCount) {
    applicationsCount.textContent =
      applications.length
      + (
        applications.length === 1
          ? " application"
          : " applications"
      );
  }

  applicationsList.innerHTML = "";

  if (applications.length === 0) {
    applicationsList.innerHTML = `
      <div class="employer-empty-state">
        <h3>No applications received yet</h3>

        <p>
          Applications submitted through PathForge will
          appear here.
        </p>
        <a class="empty-state-link" href="#manageJobs">Review Your Job Listings</a>
      </div>
    `;

    return;
  }

  applications.forEach(application => {

    const statusOptions =
      buildEmployerApplicationStatusOptions(
        application.status
      );

    const interviewFormatOptions =
      buildInterviewFormatOptions(
        application.interview_format
      );

    const card = document.createElement("article");

    card.className =
      "employer-application-card";

    card.dataset.applicationId =
      application.id;

    const submittedDate =
      formatEmployerApplicationDate(
        application.applied_at
        || application.created_at
      );

    const answers = application.answers || [];

    let answersMarkup = "";

    if (answers.length === 0) {
      answersMarkup = `
        <div class="employer-application-no-answers">
          <p>
            This application did not require any custom
            questions.
          </p>
        </div>
      `;
    } else {
      answersMarkup = answers
        .map((answer, index) => {
          const answerText =
            answer.answer_text
            || "No answer provided.";

          return `
            <div class="employer-application-answer">
              <p class="employer-application-question">
                <span>${index + 1}.</span>
                ${escapeEmployerHtml(
                  answer.question_text
                )}
              </p>

              <p class="employer-application-response">
                ${escapeEmployerHtml(answerText)}
              </p>
            </div>
          `;
        })
        .join("");
    }

    card.innerHTML = `
      <div class="employer-application-heading">
        <div>
          <h3>
            ${escapeEmployerHtml(application.username)}
          </h3>

          <p class="employer-applicant-email">
            ${escapeEmployerHtml(application.email)}
          </p>
        </div>

        <span class="employer-application-status">
          ${escapeEmployerHtml(application.status)}
        </span>
      </div>

      <div class="employer-application-summary">
        <p>
          <strong>Position:</strong>
          ${escapeEmployerHtml(application.job_title)}
        </p>

        <p>
          <strong>Company:</strong>
          ${escapeEmployerHtml(application.company)}
        </p>

        <p>
          <strong>Submitted:</strong>
          ${escapeEmployerHtml(submittedDate)}
        </p>

        ${application.application_deadline ? `
          <p class="${
            applicationDeadlineHasPassed(
              application.application_deadline
            )
              ? "deadline-passed"
              : ""
          }">
            <strong>Application deadline:</strong>
            ${escapeEmployerHtml(
              formatApplicationDeadline(
                application.application_deadline
              )
            )}
            ${
              applicationDeadlineHasPassed(
                application.application_deadline
              )
                ? " (passed)"
                : ""
            }
          </p>
        ` : ""}
      </div>

      <section class="employer-application-answers">
        <h4>Application Answers</h4>

        ${answersMarkup}
      </section>

            <form
        class="employer-application-management"
        data-action="update-employer-application"
        data-application-id="${application.id}"
      >
        <h4>Applicant Management</h4>

        <div class="employer-management-grid">

          <div class="employer-management-field">
            <label for="employer-app-status-${application.id}">
              Pipeline status
            </label>

            <select
              id="employer-app-status-${application.id}"
              class="employer-application-status-input"
              required
            >
              ${statusOptions}
            </select>
          </div>

          <div class="employer-management-field">
            <label for="employer-interview-date-${application.id}">
              Interview date
            </label>

            <input
              type="date"
              id="employer-interview-date-${application.id}"
              class="employer-interview-date-input"
              value="${escapeEmployerHtml(
                application.interview_date || ""
              )}"
            >
          </div>

          <div class="employer-management-field">
            <label for="employer-interview-time-${application.id}">
              Interview time
            </label>

            <input
              type="time"
              id="employer-interview-time-${application.id}"
              class="employer-interview-time-input"
              value="${escapeEmployerHtml(
                application.interview_time || ""
              )}"
            >
          </div>

          <div class="employer-management-field">
            <label for="employer-interview-format-${application.id}">
              Interview format
            </label>

            <select
              id="employer-interview-format-${application.id}"
              class="employer-interview-format-input"
            >
              ${interviewFormatOptions}
            </select>
          </div>

          <div class="employer-management-field">
            <label for="employer-interview-location-${application.id}">
              Address or meeting link
            </label>

            <input
              type="text"
              id="employer-interview-location-${application.id}"
              class="employer-interview-location-input"
              maxlength="500"
              value="${escapeEmployerHtml(
                application.interview_location || ""
              )}"
              placeholder="Office address or video link"
            >
          </div>

        </div>

        <div class="employer-management-field">
          <label for="employer-interview-details-${application.id}">
            Applicant-visible interview details
          </label>

          <textarea
            id="employer-interview-details-${application.id}"
            class="employer-interview-details-input"
            rows="4"
            maxlength="2000"
            placeholder="Arrival instructions, contact person, preparation details..."
          >${escapeEmployerHtml(
            application.interview_details || ""
          )}</textarea>
        </div>

        <div class="employer-management-field">
          <label for="employer-notes-${application.id}">
            Private employer notes
          </label>

          <textarea
            id="employer-notes-${application.id}"
            class="employer-notes-input"
            rows="4"
            maxlength="5000"
            placeholder="Private review notes. These are never shown to the applicant."
          >${escapeEmployerHtml(
            application.employer_notes || ""
          )}</textarea>

          <small>
            Only this employer account can access these notes.
          </small>
        </div>

        <div class="employer-management-actions">
          <button
            type="submit"
            class="employer-application-save-button"
          >
            Save Applicant Update
          </button>
        </div>

        <p
          class="employer-management-message"
          role="status"
          aria-live="polite"
        ></p>
      </form>
    `;

    applicationsList.appendChild(card);
  });
}


function formatEmployerApplicationDate(dateValue) {
  if (!dateValue) {
    return "Date unavailable";
  }

  const normalizedDate = String(dateValue).includes("T")
    ? dateValue
    : String(dateValue).replace(" ", "T");

  const parsedDate = new Date(normalizedDate);

  if (Number.isNaN(parsedDate.getTime())) {
    return String(dateValue);
  }

  return parsedDate.toLocaleDateString(
    undefined,
    {
      year: "numeric",
      month: "long",
      day: "numeric"
    }
  );
}

function buildEmployerApplicationStatusOptions(
  selectedStatus
) {
  const statuses = [
    "Applied",
    "Application Viewed",
    "Under Review",
    "Interview Scheduled",
    "Interview Completed",
    "Offer Extended",
    "Accepted",
    "Rejected",
    "Withdrawn"
  ];

  return statuses
    .map(status => {
      const selected =
        status === selectedStatus
          ? "selected"
          : "";

      return `
        <option
          value="${escapeEmployerHtml(status)}"
          ${selected}
        >
          ${escapeEmployerHtml(status)}
        </option>
      `;
    })
    .join("");
}


function buildInterviewFormatOptions(
  selectedFormat
) {
  const formats = [
    "",
    "In Person",
    "Phone",
    "Video"
  ];

  return formats
    .map(format => {
      const selected =
        format === (selectedFormat || "")
          ? "selected"
          : "";

      const label =
        format || "Select a format";

      return `
        <option
          value="${escapeEmployerHtml(format)}"
          ${selected}
        >
          ${escapeEmployerHtml(label)}
        </option>
      `;
    })
    .join("");
}


async function updateEmployerApplication(
  event,
  applicationId
) {
  event.preventDefault();

  const form = event.currentTarget;

  const saveButton = form.querySelector(
    ".employer-application-save-button"
  );

  const message = form.querySelector(
    ".employer-management-message"
  );

  const status = form.querySelector(
    ".employer-application-status-input"
  ).value;

  const interviewDate = form.querySelector(
    ".employer-interview-date-input"
  ).value;

  const interviewTime = form.querySelector(
    ".employer-interview-time-input"
  ).value;

  const interviewFormat = form.querySelector(
    ".employer-interview-format-input"
  ).value;

  const interviewLocation = form.querySelector(
    ".employer-interview-location-input"
  ).value.trim();

  const interviewDetails = form.querySelector(
    ".employer-interview-details-input"
  ).value.trim();

  const employerNotes = form.querySelector(
    ".employer-notes-input"
  ).value.trim();

  if (
    status === "Interview Scheduled"
    && (
      !interviewDate
      || !interviewTime
      || !interviewFormat
    )
  ) {
    showEmployerMessage(
      message,
      (
        "Interview date, time, and format are required "
        + "when scheduling an interview."
      ),
      "error"
    );

    return;
  }

  if (
    status === "Interview Scheduled"
    && (
      interviewFormat === "In Person"
      || interviewFormat === "Video"
    )
    && !interviewLocation
  ) {
    showEmployerMessage(
      message,
      "Enter an interview address or video meeting link.",
      "error"
    );

    return;
  }

  saveButton.disabled = true;
  saveButton.textContent = "Saving...";

  showEmployerMessage(
    message,
    "Saving applicant update..."
  );

  try {
    const response = await fetch(
      apiUrl(`/employer/applications/${applicationId}`),
      {
        method: "PUT",

        headers: {
          "Content-Type": "application/json"
        },

        credentials: "include",

        body: JSON.stringify({
          status: status,
          interview_date: interviewDate || null,
          interview_time: interviewTime || null,
          interview_format: interviewFormat || null,
          interview_location: interviewLocation || null,
          interview_details: interviewDetails || null,
          employer_notes: employerNotes || null
        })
      }
    );

    if (handleEmployerAuthorizationFailure(response)) {
      return;
    }

    const data = await readEmployerResponse(response);

    if (!response.ok) {
      let errorMessage =
        "The applicant update could not be saved.";

      if (typeof data.detail === "string") {
        errorMessage = data.detail;
      } else if (Array.isArray(data.detail)) {
        errorMessage = data.detail
          .map(error => {
            return error.msg || "Invalid update value.";
          })
          .join(" ");
      }

      throw new Error(errorMessage);
    }

    showEmployerMessage(
      document.getElementById(
        "employerDashboardMessage"
      ),
      data.message || "Application updated successfully.",
      "success"
    );

    await loadEmployerApplications();
    await loadEmployerStatistics();

  } catch (error) {
    console.error(
      "Employer application update failed:",
      error
    );

    showEmployerMessage(
      message,
      error.message,
      "error"
    );

    } finally {
    saveButton.disabled = false;
    saveButton.textContent =
      "Save Applicant Update";
  }
}

// =========================
// EMPLOYER DASHBOARD STATISTICS
// =========================

async function loadEmployerStatistics() {
  const activeJobsElement =
    document.getElementById(
      "employerActiveJobsStatistic"
    );

  if (!activeJobsElement) {
    return;
  }

  const applicantsElement =
    document.getElementById(
      "employerApplicantsStatistic"
    );

  const interviewsElement =
    document.getElementById(
      "employerInterviewsStatistic"
    );

  const hiresElement =
    document.getElementById(
      "employerHiresStatistic"
    );

  const jobsBreakdown =
    document.getElementById(
      "employerJobsBreakdown"
    );

  const message =
    document.getElementById(
      "employerStatisticsMessage"
    );

  try {
    const response = await fetch(
      apiUrl("/employer/statistics"),
      {
        credentials: "include"
      }
    );

    if (handleEmployerAuthorizationFailure(response)) {
      return;
    }

    const data = await readEmployerResponse(response);

    if (!response.ok) {
      throw new Error(
        data.detail ||
        "Dashboard statistics could not be loaded."
      );
    }

    const statistics = data.statistics || {};

    activeJobsElement.textContent =
      statistics.active_jobs ?? 0;

    applicantsElement.textContent =
      statistics.total_applicants ?? 0;

    interviewsElement.textContent =
      statistics.scheduled_interviews ?? 0;

    hiresElement.textContent =
      statistics.hires ?? 0;

    const draftJobs = statistics.draft_jobs ?? 0;
    const closedJobs = statistics.closed_jobs ?? 0;

    jobsBreakdown.textContent =
      `${draftJobs} draft · ${closedJobs} closed`;

    showEmployerMessage(message, "");

  } catch (error) {
    console.error(
      "Employer statistics load failed:",
      error
    );

    activeJobsElement.textContent = "—";
    applicantsElement.textContent = "—";
    interviewsElement.textContent = "—";
    hiresElement.textContent = "—";

    jobsBreakdown.textContent =
      "Statistics unavailable";

    showEmployerMessage(
      message,
      error.message,
      "error"
    );
  }
}

// =========================
// EMPLOYER COMPANY PROFILE
// =========================

async function loadEmployerCompanyProfile() {
  const form =
    document.getElementById("employerCompanyProfileForm");

  if (!form) {
    return;
  }

  const message =
    document.getElementById("companyProfileMessage");

  try {
    const response = await fetch(
      apiUrl("/employer/company-profile"),
      {
        credentials: "include"
      }
    );

    if (handleEmployerAuthorizationFailure(response)) {
      return;
    }

    const data = await readEmployerResponse(response);

    if (!response.ok) {
      throw new Error(
        data.detail ||
        "The company profile could not be loaded."
      );
    }

    const profile = data.company_profile || {};

    document.getElementById(
      "companyProfileName"
    ).value = profile.company_name || "";

    document.getElementById(
      "companyProfileWebsite"
    ).value = profile.website || "";

    document.getElementById(
      "companyProfileLogoUrl"
    ).value = profile.logo_url || "";

    document.getElementById(
      "companyProfileBrandColor"
    ).value = profile.brand_color || "#2563eb";

    document.getElementById(
      "companyProfileDescription"
    ).value = profile.company_description || "";

    document.getElementById(
      "companyProfileHiringPreferences"
    ).value = profile.hiring_preferences || "";

        const jobCompanyInput =
      document.getElementById("employerJobCompany");

    if (
      jobCompanyInput &&
      !jobCompanyInput.value.trim() &&
      profile.company_name
    ) {
      jobCompanyInput.value = profile.company_name;
    }

    updateCompanyProfilePreview();

  } catch (error) {
    console.error(
      "Company profile load failed:",
      error
    );

    showEmployerMessage(
      message,
      error.message,
      "error"
    );
  }
}


function updateCompanyProfilePreview() {
  const nameInput =
    document.getElementById("companyProfileName");

  const descriptionInput =
    document.getElementById(
      "companyProfileDescription"
    );

  const websiteInput =
    document.getElementById("companyProfileWebsite");

  const logoInput =
    document.getElementById("companyProfileLogoUrl");

  const colorInput =
    document.getElementById("companyProfileBrandColor");

  const logoPreview =
    document.getElementById("companyProfileLogoPreview");

  const namePreview =
    document.getElementById("companyProfileNamePreview");

  const descriptionPreview =
    document.getElementById(
      "companyProfileDescriptionPreview"
    );

  const websitePreview =
    document.getElementById(
      "companyProfileWebsitePreview"
    );

  if (
    !nameInput ||
    !descriptionInput ||
    !websiteInput ||
    !logoInput ||
    !colorInput ||
    !logoPreview ||
    !namePreview ||
    !descriptionPreview ||
    !websitePreview
  ) {
    return;
  }

  const companyName =
    nameInput.value.trim() || "Your Company";

  const companyDescription =
    descriptionInput.value.trim() ||
    "Add a company description to preview it here.";

  const website = websiteInput.value.trim();
  const logoUrl = logoInput.value.trim();
  const brandColor = colorInput.value || "#2563eb";

  namePreview.textContent = companyName;
  descriptionPreview.textContent = companyDescription;

  logoPreview.style.backgroundColor = brandColor;
  logoPreview.replaceChildren();

  const initial = document.createElement("span");
  initial.id = "companyProfileInitial";
  initial.textContent =
    companyName.charAt(0).toUpperCase() || "C";

  logoPreview.appendChild(initial);

  if (logoUrl) {
    const logoImage = document.createElement("img");
    logoImage.src = logoUrl;
    logoImage.alt = `${companyName} logo`;

    logoImage.addEventListener("load", function () {
      logoPreview.replaceChildren(logoImage);
    });

    logoImage.addEventListener("error", function () {
      logoPreview.replaceChildren(initial);
    });
  }

  if (website) {
    websitePreview.href = website;
    websitePreview.classList.remove("hidden");
  } else {
    websitePreview.href = "#";
    websitePreview.classList.add("hidden");
  }
}


async function saveEmployerCompanyProfile(event) {
  event.preventDefault();

  const saveButton =
    document.getElementById("saveCompanyProfileButton");

  const message =
    document.getElementById("companyProfileMessage");

  const profileData = {
    company_name:
      document.getElementById(
        "companyProfileName"
      ).value.trim(),

    company_description:
      document.getElementById(
        "companyProfileDescription"
      ).value.trim(),

    website:
      document.getElementById(
        "companyProfileWebsite"
      ).value.trim(),

    logo_url:
      document.getElementById(
        "companyProfileLogoUrl"
      ).value.trim(),

    brand_color:
      document.getElementById(
        "companyProfileBrandColor"
      ).value,

    hiring_preferences:
      document.getElementById(
        "companyProfileHiringPreferences"
      ).value.trim()
  };

  showEmployerMessage(message, "");

  saveButton.disabled = true;
  saveButton.textContent = "Saving...";

  try {
    const response = await fetch(
      apiUrl("/employer/company-profile"),
      {
        method: "PUT",

        headers: {
          "Content-Type": "application/json"
        },

        credentials: "include",
        body: JSON.stringify(profileData)
      }
    );

    if (handleEmployerAuthorizationFailure(response)) {
      return;
    }

    const data = await readEmployerResponse(response);

    if (!response.ok) {
      let errorMessage =
        data.detail ||
        "The company profile could not be saved.";

      if (Array.isArray(data.detail)) {
        errorMessage = data.detail
          .map(error => {
            return error.msg || "Invalid company profile value.";
          })
          .join(" ");
      }

      throw new Error(errorMessage);
    }

    updateCompanyProfilePreview();

    const jobCompanyInput =
      document.getElementById("employerJobCompany");

    if (
      jobCompanyInput &&
      data.company_profile
    ) {
      jobCompanyInput.value =
        data.company_profile.company_name;
    }

    showEmployerMessage(
      message,
      data.message ||
      "Company profile saved successfully.",
      "success"
    );

  } catch (error) {
    console.error(
      "Company profile save failed:",
      error
    );

    showEmployerMessage(
      message,
      error.message,
      "error"
    );

  } finally {
    saveButton.disabled = false;
    saveButton.textContent = "Save Company Profile";
  }
}


function setupEmployerCompanyProfile() {
  const form =
    document.getElementById("employerCompanyProfileForm");

  if (!form) {
    return;
  }

  form.addEventListener(
    "submit",
    saveEmployerCompanyProfile
  );

  const previewFields = [
    "companyProfileName",
    "companyProfileDescription",
    "companyProfileWebsite",
    "companyProfileLogoUrl",
    "companyProfileBrandColor"
  ];

  previewFields.forEach(fieldId => {
    const field = document.getElementById(fieldId);

    if (field) {
      field.addEventListener(
        "input",
        updateCompanyProfilePreview
      );

      field.addEventListener(
        "change",
        updateCompanyProfilePreview
      );
    }
  });

  updateCompanyProfilePreview();
}

// Skills Bank examples translate everyday responsibilities into job-relevant
// language without suggesting that users claim experience they do not have.
const SKILLS_BANK = {
  general: {
    label: "Any first job",
    introduction: "These transferable skills appear across many entry-level roles.",
    skills: [
      ["Reliable attendance", "Arrived on time for classes, practices, volunteer shifts, or recurring responsibilities."],
      ["Communication", "Explained information clearly, listened carefully, or asked useful questions."],
      ["Teamwork", "Shared responsibilities and completed your part of a group task."],
      ["Time management", "Balanced deadlines, activities, caregiving, or household responsibilities."],
      ["Problem solving", "Noticed an issue, considered options, and completed a practical next step."],
      ["Learning quickly", "Used instructions or feedback to perform an unfamiliar task more confidently."]
    ]
  },
  retail: {
    label: "Retail",
    introduction: "Retail employers often value customer support, accuracy, product learning, and dependable teamwork.",
    skills: [
      ["Customer service", "Helped someone understand choices or resolve a concern respectfully."],
      ["Point-of-sale accuracy", "Handled money, totals, or transactions accurately; claim POS experience only if you used one."],
      ["Product knowledge", "Learned details and used them to answer questions or make appropriate suggestions."],
      ["Stocking and organization", "Sorted, labeled, counted, or arranged items so others could find them."],
      ["Calm communication", "Stayed respectful and focused during a busy or difficult interaction."]
    ]
  },
  food_service: {
    label: "Food service",
    introduction: "Food-service roles combine guest care, speed, accuracy, cleanliness, and safety.",
    skills: [
      ["Order accuracy", "Followed multi-step instructions and checked details before finishing."],
      ["Food-safety awareness", "Followed hygiene or safe-handling rules; list certifications only when earned."],
      ["Team coordination", "Communicated handoffs and helped a group complete work during busy periods."],
      ["Cleaning standards", "Maintained an organized, sanitary workspace using an established routine."],
      ["Working under pressure", "Prioritized tasks and remained courteous when several needs arrived at once."]
    ]
  },
  customer_service: {
    label: "Customer service",
    introduction: "Customer-service work depends on listening, clear explanations, documentation, and appropriate escalation.",
    skills: [
      ["Active listening", "Restated a question or concern before offering the next step."],
      ["Clear communication", "Explained instructions in plain language through conversation, email, or chat."],
      ["Issue documentation", "Recorded accurate details so another person could understand what happened."],
      ["Conflict de-escalation", "Stayed calm, acknowledged concerns, and involved the right person when needed."],
      ["Follow-through", "Tracked an open task and confirmed that the promised next step was completed."]
    ]
  },
  office: {
    label: "Office or administrative",
    introduction: "Administrative roles reward organization, accurate records, professional communication, and discretion.",
    skills: [
      ["Scheduling", "Coordinated dates, reminders, appointments, or shared responsibilities."],
      ["Data entry", "Entered or reviewed information carefully and corrected errors."],
      ["Document preparation", "Created clear school, club, volunteer, or work documents."],
      ["Spreadsheet basics", "Organized rows, columns, totals, or lists; name software only when you have used it."],
      ["Confidentiality", "Handled private information responsibly and shared it only with appropriate people."]
    ]
  },
  warehouse: {
    label: "Warehouse or stocking",
    introduction: "Warehouse roles emphasize safety, inventory accuracy, dependable pace, and coordinated movement of goods.",
    skills: [
      ["Safety awareness", "Followed equipment, lifting, traffic, or workspace rules consistently."],
      ["Inventory accuracy", "Counted, labeled, sorted, or checked items against a list."],
      ["Picking and packing", "Prepared the correct items carefully; claim scanner experience only if applicable."],
      ["Physical organization", "Kept materials arranged to reduce errors and unnecessary movement."],
      ["Team communication", "Confirmed assignments and alerted others when a task or condition changed."]
    ]
  },
  childcare: {
    label: "Childcare",
    introduction: "Childcare requires attentive supervision, age-appropriate communication, planning, and safety awareness.",
    skills: [
      ["Supervision", "Stayed attentive to multiple needs and recognized when adult help was required."],
      ["Patient communication", "Adjusted explanations to another person's age or understanding."],
      ["Activity planning", "Prepared structured, suitable activities and the materials they required."],
      ["Routine management", "Helped maintain schedules for meals, homework, cleanup, or transitions."],
      ["First aid", "List CPR or first-aid credentials only if they are current and verifiable."]
    ]
  },
  hospitality: {
    label: "Hospitality",
    introduction: "Hospitality roles combine guest service, attention to detail, flexibility, and team coordination.",
    skills: [
      ["Guest service", "Welcomed people, answered questions, or helped them navigate an unfamiliar setting."],
      ["Attention to detail", "Checked a room, setup, reservation, or request against a clear standard."],
      ["Professional communication", "Used a courteous tone and passed accurate information to the next person."],
      ["Adaptability", "Changed priorities when schedules, attendance, or guest needs shifted."],
      ["Service recovery", "Acknowledged a problem and found the correct person or process to address it."]
    ]
  },
  technology: {
    label: "Entry-level technology",
    introduction: "Entry-level technology roles value methodical troubleshooting, documentation, and evidence of hands-on learning.",
    skills: [
      ["Troubleshooting", "Reproduced a problem, tested likely causes, and documented what resolved it."],
      ["Technical documentation", "Wrote steps that another person could follow successfully."],
      ["Hardware and software basics", "Set up or maintained devices and applications you have actually used."],
      ["Ticket or task tracking", "Recorded status, priority, actions taken, and remaining work."],
      ["Security awareness", "Used strong account practices and recognized suspicious links or requests."]
    ]
  },
  healthcare_support: {
    label: "Healthcare support",
    introduction: "Healthcare-support roles require accuracy, privacy, compassion, and strict attention to role boundaries.",
    skills: [
      ["Respectful communication", "Listened patiently and explained non-clinical information clearly."],
      ["Privacy awareness", "Protected personal information and followed rules about appropriate access."],
      ["Accurate records", "Recorded names, dates, instructions, or status information carefully."],
      ["Scheduling and follow-up", "Coordinated appointments or reminders and documented next steps."],
      ["Clinical skills", "List patient-care tasks or certifications only when trained and authorized to perform them."]
    ]
  }
};

function renderSkillsBank(jobType = "general") {
  const results = document.getElementById("skillsBankResults");
  const introduction = document.getElementById("skillsBankIntroduction");
  const bank = SKILLS_BANK[jobType] || SKILLS_BANK.general;
  if (!results || !introduction) return;

  introduction.textContent = bank.introduction;
  results.innerHTML = bank.skills.map(([name, evidence]) => `
    <article class="skills-bank-card">
      <h3>${escapeEmployerHtml(name)}</h3>
      <p><strong>Possible evidence:</strong> ${escapeEmployerHtml(evidence)}</p>
    </article>
  `).join("");
}

function initializeSkillsBank() {
  const jobType = document.getElementById("skillsBankJobType");
  if (!jobType) return;
  jobType.addEventListener("change", () => renderSkillsBank(jobType.value));
  renderSkillsBank(jobType.value);
}

const LEARNING_LESSON_CATALOG = [
  {
    id: "career-exploration",
    title: "Explore interests and strengths",
    description:
      "Compare interests, strengths, work values, duties, training, pay, and outlook."
  },
  {
    id: "career-goals",
    title: "Set realistic career goals",
    description:
      "Set achievable next steps, research employers, and recognize job scams."
  },
  {
    id: "career-transitions",
    title: "Navigate a first job or career change",
    description:
      "Recognize transferable experience and suitable entry points."
  },
  {
    id: "resume-fundamentals",
    title: "Review résumé fundamentals",
    description:
      "Understand contact information, organization, and ATS-safe structure."
  },
  {
    id: "resume-skills-experience",
    title: "Describe skills and experience",
    description:
      "Write truthful, evidence-based accomplishment statements."
  },
  {
    id: "resume-education-projects",
    title: "Present education and projects",
    description:
      "Use relevant education, projects, and volunteer experience."
  },
  {
    id: "resume-tailoring",
    title: "Tailor thoughtfully",
    description:
      "Improve relevance and use AI responsibly without changing facts."
  },
  {
    id: "job-search-readiness",
    title: "Organize your job search",
    description:
      "Build job-search, networking, and career-readiness routines."
  },
  {
    id: "interview-foundations",
    title: "Prepare for common interview questions",
    description:
      "Research the role and organize truthful answers."
  },
  {
    id: "behavioral-interviews",
    title: "Answer behavioral questions",
    description:
      "Use genuine examples and the STAR answer structure."
  },
  {
    id: "interview-formats",
    title: "Practice for interview formats",
    description:
      "Prepare for telephone, virtual, and in-person interviews."
  },
  {
    id: "interview-day-follow-up",
    title: "Plan interview day and follow-up",
    description:
      "Use a checklist and respond professionally afterward."
  }
];

let learningProgressByLesson = new Map();


// Lesson IDs connect accessible disclosure controls with optional saved progress.
function setupLearningControls() {
  const lessons =
    document.querySelectorAll(".learning-lesson");

  lessons.forEach(lesson => {
    const lessonId = lesson.id;

    if (
      !lessonId ||
      !LEARNING_LESSON_CATALOG.some(
        item => item.id === lessonId
      )
    ) {
      return;
    }

    const content =
      lesson.querySelector(".learning-lesson-content");

    if (!content) {
      return;
    }

    let controls =
      content.querySelector(
        ".learning-completion-controls"
      );

    if (!controls) {
      controls = document.createElement("div");
      controls.className =
        "learning-completion-controls";

      const status = document.createElement("p");
      status.className =
        "learning-completion-status";

      status.textContent = "Not started";

      const button = document.createElement("button");
      button.type = "button";
      button.className =
        "learning-completion-button";

      button.textContent = "Mark as reviewed";
      button.setAttribute("aria-pressed", "false");

      button.addEventListener(
        "click",
        async function () {
          const currentProgress =
            learningProgressByLesson.get(lessonId);

          const nextStatus =
            currentProgress?.is_completed
              ? "not_completed"
              : "completed";

          await saveLearningProgress(
            lessonId,
            nextStatus,
            button
          );
        }
      );

      controls.append(status, button);
      content.appendChild(controls);
    }

    lesson.addEventListener(
      "toggle",
      async function () {
        if (!lesson.open) {
          return;
        }

        await saveLearningProgress(
          lessonId,
          "started"
        );
      }
    );
  });
}


function setLearningCompletionButtonState(button, isCompleted) {
  if (!button) return;
  button.disabled = false;
  button.classList.toggle("is-completed", isCompleted);
  button.setAttribute("aria-pressed", String(isCompleted));
  button.setAttribute(
    "aria-label",
    isCompleted ? "Resource reviewed. Mark as not reviewed" : "Mark as reviewed"
  );
  button.title = isCompleted ? "Click to mark as not reviewed" : "Mark this resource as reviewed";
  button.textContent = isCompleted ? "Reviewed ✓" : "Mark as reviewed";
}

function renderLearningProgress(data) {
  const progress = Array.isArray(data.progress)
    ? data.progress
    : [];

  const summary = data.summary || {};

  learningProgressByLesson = new Map(
    progress.map(item => [
      item.lesson_id,
      item
    ])
  );

  const availableLessons =
    Number(summary.available_lessons) ||
    LEARNING_LESSON_CATALOG.length;

  const startedLessons =
    Number(summary.started_lessons) || 0;

  const completedLessons =
    Number(summary.completed_lessons) || 0;

  const startedCount =
    document.getElementById("learningStartedCount");

  const completedCount =
    document.getElementById(
      "learningCompletedCount"
    );

  const availableCount =
    document.getElementById(
      "learningAvailableCount"
    );

  const progressMessage =
    document.getElementById(
      "learningProgressMessage"
    );

  const progressBar =
    document.getElementById(
      "learningProgressBar"
    );

  const progressBarFill =
    document.getElementById(
      "learningProgressBarFill"
    );

  if (startedCount) {
    startedCount.textContent = startedLessons;
  }

  if (completedCount) {
    completedCount.textContent = completedLessons;
  }

  if (availableCount) {
    availableCount.textContent = availableLessons;
  }

  if (progressMessage) {
    progressMessage.classList.remove(
      "error-message"
    );

    if (startedLessons === 0) {
      progressMessage.textContent =
        "Open any resource when it becomes useful to you.";
    } else {
      progressMessage.textContent =
        completedLessons +
        " reviewed; " +
        startedLessons +
        " opened.";
    }
  }

  if (progressBar) {
    progressBar.setAttribute(
      "aria-valuemax",
      String(availableLessons)
    );

    progressBar.setAttribute(
      "aria-valuenow",
      String(completedLessons)
    );
  }

  if (progressBarFill) {
    const percentage =
      availableLessons > 0
        ? (
            completedLessons /
            availableLessons
          ) * 100
        : 0;

    progressBarFill.style.width =
      Math.min(percentage, 100) + "%";
  }

  LEARNING_LESSON_CATALOG.forEach(lesson => {
    const lessonElement =
      document.getElementById(lesson.id);

    if (!lessonElement) {
      return;
    }

    const savedProgress =
      learningProgressByLesson.get(lesson.id);

    const isCompleted =
      Boolean(savedProgress?.is_completed);

    const controls =
      lessonElement.querySelector(
        ".learning-completion-controls"
      );

    const status =
      controls?.querySelector(
        ".learning-completion-status"
      );

    const button =
      controls?.querySelector(
        ".learning-completion-button"
      );

    lessonElement.classList.toggle(
      "is-completed",
      isCompleted
    );

    if (status) {
      if (isCompleted) {
        status.textContent =
          "Successfully marked as reviewed. You can return anytime.";
      } else if (savedProgress) {
        status.textContent =
          "Opened. Mark reviewed if you found it useful.";
      } else {
        status.textContent =
          "Not started";
      }
    }

    setLearningCompletionButtonState(button, isCompleted);
  });

  updateLearningRecommendation(
    progress,
    completedLessons,
    availableLessons
  );
}


function updateLearningRecommendation(
  progress,
  completedLessons,
  availableLessons
) {
  const title =
    document.getElementById(
      "learningRecommendationTitle"
    );

  const description =
    document.getElementById(
      "learningRecommendationDescription"
    );

  const link =
    document.getElementById(
      "learningRecommendationLink"
    );

  const reason =
    document.getElementById(
      "learningRecommendationReason"
    );

  const followUp =
    document.getElementById(
      "learningFollowUpPrompt"
    );

  followUp?.classList.remove("error-message");

  if (
    !title ||
    !description ||
    !link ||
    !reason ||
    !followUp
  ) {
    return;
  }

  const incompleteStarted = progress
    .filter(item => !item.is_completed)
    .sort((first, second) => {
      const firstDate =
        first.last_opened_at || first.updated_at || "";

      const secondDate =
        second.last_opened_at || second.updated_at || "";

      return secondDate.localeCompare(firstDate);
    });

  let recommendation = null;

  if (incompleteStarted.length > 0) {
    recommendation =
      LEARNING_LESSON_CATALOG.find(
        lesson =>
          lesson.id ===
          incompleteStarted[0].lesson_id
      );

    reason.textContent =
      "Return to the resource you opened most recently.";
  }

  if (!recommendation) {
    recommendation =
      LEARNING_LESSON_CATALOG.find(
        lesson => {
          const saved =
            learningProgressByLesson.get(
              lesson.id
            );

          return !saved?.is_completed;
        }
      );

    reason.textContent =
      completedLessons > 0
        ? "This follows the resources you have already reviewed."
        : "This is a useful reference for many career paths.";
  }

  if (!recommendation) {
    recommendation =
      LEARNING_LESSON_CATALOG[0];

    reason.textContent =
      "You reviewed every resource. Choose any topic to revisit.";
  }

  title.textContent = recommendation.title;
  description.textContent =
    recommendation.description;

  link.href = "#" + recommendation.id;

  if (completedLessons >= availableLessons) {
    link.textContent = "Revisit resource";

    followUp.textContent =
      "You reviewed every available resource. Revisit any topic whenever you need it.";

  } else if (completedLessons > 0) {
    link.textContent = "Continue reviewing";

    followUp.textContent =
      "You have " +
      (availableLessons - completedLessons) +
      " resources not yet reviewed. Choose whichever is useful now.";

  } else {
    link.textContent = "Open suggested resource";

    followUp.textContent =
      "Open any resource, use what is relevant, and mark it reviewed if you wish.";
  }
}


async function loadLearningProgress() {
  // Lessons are public; authentication is required only to persist completion state.
  const message =
    document.getElementById(
      "learningProgressMessage"
    );

  if (!message) {
    return;
  }

  message.classList.remove("error-message");
  message.textContent = "Loading your saved activity...";

  try {
    const response = await fetch(
      apiUrl("/learning-progress"),
      {
        credentials: "include"
      }
    );

    if (response.status === 401) {
      learningProgressByLesson = new Map();
      message.textContent =
        "Resources are available to everyone. Sign in to save your progress.";
      document.querySelectorAll(".learning-completion-button").forEach(button => {
        button.textContent = "Sign in to save progress";
        button.setAttribute("aria-label", "Sign in to save learning progress");
      });
      return;
    }

    if (!response.ok) {
      throw new Error(
        "Your saved resource activity could not be loaded."
      );
    }

    const data = await response.json();

    renderLearningProgress(data);

  } catch (error) {
    console.error(
      "Learning progress load failed:",
      error
    );

    message.textContent =
      error.message ||
      "Your saved resource activity could not be loaded.";

    message.classList.add("error-message");
  }
}


async function saveLearningProgress(
  lessonId,
  status,
  button = null
) {
  const previousProgress = learningProgressByLesson.get(lessonId);
  const wasCompleted = Boolean(previousProgress?.is_completed);
  const followUp =
    document.getElementById(
      "learningFollowUpPrompt"
    );

  if (button) {
    button.disabled = true;
    button.textContent = "Saving...";
    button.setAttribute("aria-busy", "true");
  }

  try {
    const response = await fetch(
      apiUrl("/learning-progress/") +
        encodeURIComponent(lessonId),
      {
        method: "PUT",

        headers: {
          "Content-Type": "application/json"
        },

        credentials: "include",

        body: JSON.stringify({
          status: status
        })
      }
    );

    if (response.status === 401) {
      if (button) {
        button.textContent = "Sign in to save progress";
        button.setAttribute("aria-label", "Sign in to save learning progress");
      }
      if (followUp) {
        followUp.textContent = "Sign in to save which resources you have reviewed.";
      }
      return;
    }

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        data.detail ||
        "Your resource activity could not be saved."
      );
    }

    const savedProgress = data.progress || {
      lesson_id: lessonId,
      is_completed: status === "completed"
    };
    learningProgressByLesson.set(lessonId, savedProgress);

    const isCompleted = Boolean(savedProgress.is_completed);
    const lessonElement = document.getElementById(lessonId);
    lessonElement?.classList.toggle("is-completed", isCompleted);
    const lessonStatus = lessonElement?.querySelector(".learning-completion-status");
    if (lessonStatus) {
      lessonStatus.textContent = isCompleted
        ? "Successfully marked as reviewed."
        : "Marked as not reviewed. You can return whenever you are ready.";
    }
    setLearningCompletionButtonState(button, isCompleted);

    // Refresh aggregate counts and recommendations; the direct update above
    // keeps the clicked control correct even if this follow-up request fails.
    await loadLearningProgress();

    if (followUp && status === "completed") {
      followUp.textContent =
        "Lesson completed. PathForge updated your suggested next step.";
    }

    if (
      followUp &&
      status === "not_completed"
    ) {
      followUp.textContent =
        "Lesson returned to in progress so you can revisit it.";
    }

  } catch (error) {
    console.error(
      "Learning progress save failed:",
      error
    );

    if (followUp) {
      followUp.textContent =
        error.message ||
        "Your resource activity could not be saved.";

      followUp.classList.add("error-message");
    }

    setLearningCompletionButtonState(button, wasCompleted);

  } finally {
    if (button) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
      if (button.textContent === "Saving...") {
        setLearningCompletionButtonState(button, wasCompleted);
      }
    }
  }
}


let learningAssistantRequestInProgress = false;
let learningAssistantAttachment = null;
let learningAssistantUploadRequested = false;

const learningMockInterview = {
  active: false,
  role: "",
  interviewType: "general",
  questionIndex: 0,
  totalQuestions: 5,
  answers: [],
  flaggedAttempts: []
};

function setLearningAssistantBusy(isBusy) {
  const form =
    document.getElementById(
      "learningAssistantForm"
    );

  if (!form) {
    return;
  }

  const input =
  document.getElementById(
    "learningAssistantInput"
  );

  if (input) {
    input.disabled = isBusy;
  }

  const fileInput =
    document.getElementById(
      "learningAssistantFile"
    );

  if (fileInput) {
    fileInput.disabled =
      isBusy || learningMockInterview.active;
  }

  const careerStageSelect = document.getElementById("learningAssistantCareerStage");
  if (careerStageSelect) {
    careerStageSelect.disabled = isBusy || learningMockInterview.active;
  }

  const regularControls =
    form
      .closest(".learning-assistant-section")
      ?.querySelectorAll(
        "[data-learning-question], " +
        "#openMockInterviewButton, " +
        "#startMockInterviewButton"
      );

  regularControls?.forEach(button => {
    button.disabled =
      isBusy || learningMockInterview.active;
  });

  const endButton =
    document.getElementById(
      "endMockInterviewButton"
    );

  if (endButton) {
    endButton.disabled =
      isBusy || !learningMockInterview.active;
  }

  const messages =
    document.getElementById(
      "learningAssistantMessages"
    );

  messages?.setAttribute(
    "aria-busy",
    String(isBusy)
  );
}


function setMockInterviewInterface(isActive) {
  const setup =
    document.getElementById(
      "mockInterviewSetup"
    );

  const activeControls =
    document.getElementById(
      "mockInterviewActiveControls"
    );

  const label =
    document.getElementById(
      "learningAssistantInputLabel"
    );

  const input =
    document.getElementById(
      "learningAssistantInput"
    );

  const submit =
    document.getElementById(
      "learningAssistantSubmit"
    );

  const characterCount =
    document.getElementById(
      "learningAssistantCharacterCount"
    );

  if (setup) {
    setup.hidden = isActive;
  }

  if (activeControls) {
    activeControls.hidden = !isActive;
  }

  if (label) {
    label.textContent = isActive
      ? "Your interview answer"
      : "What would you like help with?";
  }

  if (input) {
    input.maxLength = isActive ? 2000 : 800;
    input.placeholder = isActive
      ? "Type your truthful interview answer..."
      : (
        "Example: Evaluate my resume or help me " +
        "practice an interview."
      );
    input.value = "";
  }

  if (submit) {
    submit.textContent = isActive
      ? "Submit answer"
      : "Send";
  }

  if (characterCount) {
    characterCount.textContent =
      isActive ? "0 / 2000" : "0 / 800";
  }

  const attachmentArea =
    document.getElementById(
      "learningAssistantAttachment"
    );

  if (attachmentArea) {
    attachmentArea.hidden =
      isActive || !learningAssistantUploadRequested;
  }

  setLearningAssistantBusy(false);
}


function updateMockInterviewProgress(
  questionNumber,
  totalQuestions
) {
  const progress =
    document.getElementById(
      "mockInterviewProgress"
    );

  if (progress) {
    progress.textContent =
      "Question " +
      questionNumber +
      " of " +
      totalQuestions;
  }
}


function endMockInterview(showMessage = true) {
  if (
    showMessage &&
    learningMockInterview.active
  ) {
    addLearningAssistantMessage(
      "assistant",
      (
        "Mock interview ended. You can begin another " +
        "practice session whenever you are ready."
      )
    );
  }

  learningMockInterview.active = false;
  learningMockInterview.role = "";
  learningMockInterview.interviewType = "general";
  learningMockInterview.questionIndex = 0;
  learningMockInterview.answers = [];
  learningMockInterview.flaggedAttempts = [];

  const progress =
    document.getElementById(
      "mockInterviewProgress"
    );

  if (progress) {
    progress.textContent = "Setup";
  }

  const panel = document.getElementById("mockInterviewPanel");
  const roleInput = document.getElementById("mockInterviewRole");
  const typeSelect = document.getElementById("mockInterviewType");

  if (panel) panel.hidden = true;
  if (roleInput) roleInput.value = "";
  if (typeSelect) typeSelect.value = "general";

  setMockInterviewInterface(false);

  const status =
    document.getElementById(
      "learningAssistantStatus"
    );

  if (status) {
    status.textContent =
      "Press Enter to send. Use Shift+Enter for a new line.";
  }
}


async function startMockInterview() {
  const roleInput =
    document.getElementById(
      "mockInterviewRole"
    );

  const typeSelect =
    document.getElementById(
      "mockInterviewType"
    );

  const status =
    document.getElementById(
      "learningAssistantStatus"
    );

  const role = String(
    roleInput?.value || ""
  ).trim();

  if (!role) {
    status.textContent =
      "Enter the role you want to practice for.";
    status.classList.add("error-message");
    roleInput?.focus();
    return;
  }

  status.classList.remove("error-message");
  status.textContent =
    "Preparing your mock interview...";

  learningAssistantRequestInProgress = true;
  setLearningAssistantBusy(true);

  try {
    const response = await fetch(
      (
        apiUrl("/") +
        "learning-assistant/mock-interview"
      ),
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        credentials: "include",
        body: JSON.stringify({
          role: role,
          interview_type:
            typeSelect?.value || "general",
          question_index: 0,
          answer: ""
        })
      }
    );

    if (response.status === 401) {
      window.location.href = "login.html";
      return;
    }

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        data.detail ||
        "The mock interview could not begin."
      );
    }

    learningMockInterview.active = true;
    learningMockInterview.role = role;
    learningMockInterview.interviewType =
      typeSelect?.value || "general";
    learningMockInterview.questionIndex = 0;
    learningMockInterview.totalQuestions =
      data.total_questions;
    learningMockInterview.answers = [];
    learningMockInterview.flaggedAttempts = [];

    clearLearningAssistantAttachment();
    setLearningAssistantUploadVisibility(false);
    setMockInterviewInterface(true);
    updateMockInterviewProgress(
      data.question_number,
      data.total_questions
    );

    addLearningAssistantMessage(
      "assistant",
      (
        "Hello, and thank you for meeting with me today. " +
        "We will be discussing the " +
        role +
        " role. Take a moment to think before each answer. " +
        "To begin, " +
        data.question
      ),
      [],
      (
        "Use only genuine experiences and describe your " +
        "own contribution."
      )
    );

    status.textContent =
      "Answer question 1 when you are ready.";

    document
      .getElementById("learningAssistantInput")
      ?.focus();

  } catch (error) {
    status.textContent =
      error.message ||
      "The mock interview could not begin.";
    status.classList.add("error-message");

  } finally {
    learningAssistantRequestInProgress = false;
    setLearningAssistantBusy(false);
  }
}


async function submitMockInterviewAnswer(answer) {
  const input =
    document.getElementById(
      "learningAssistantInput"
    );

  const status =
    document.getElementById(
      "learningAssistantStatus"
    );

  const characterCount =
    document.getElementById(
      "learningAssistantCharacterCount"
    );

  const cleanedAnswer =
    String(answer || "").trim();

  if (
    !input ||
    !status ||
    learningAssistantRequestInProgress
  ) {
    return;
  }

  status.classList.remove("error-message");

  if (!cleanedAnswer) {
    status.textContent =
      "Enter an interview answer before continuing.";
    status.classList.add("error-message");
    input.focus();
    return;
  }

  if (cleanedAnswer.length > 2000) {
    status.textContent =
      "Keep your answer under 2,000 characters.";
    status.classList.add("error-message");
    input.focus();
    return;
  }

  addLearningAssistantMessage(
    "user",
    cleanedAnswer
  );

  input.value = "";

  if (characterCount) {
    characterCount.textContent = "0 / 2000";
  }

  const typingMessage =
    addLearningAssistantTypingMessage();

  status.textContent =
    "Reviewing your interview answer...";

  learningAssistantRequestInProgress = true;
  setLearningAssistantBusy(true);

  try {
    const response = await fetch(
      (
        apiUrl("/") +
        "learning-assistant/mock-interview"
      ),
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        credentials: "include",
        body: JSON.stringify({
          role: learningMockInterview.role,
          interview_type:
            learningMockInterview.interviewType,
          question_index:
            learningMockInterview.questionIndex,
          answer: cleanedAnswer,
          answers: learningMockInterview.answers,
          flagged_attempts:
            learningMockInterview.flaggedAttempts
        })
      }
    );

    if (response.status === 401) {
      window.location.href = "login.html";
      return;
    }

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        data.detail ||
        "Your interview answer could not be reviewed."
      );
    }

    typingMessage?.remove();

    if (data.safety_notice) {
      const safetyMessage = addLearningAssistantMessage(
        "assistant",
        data.feedback
      );
      safetyMessage?.classList.add("assistant-safety-message");
      if (data.safety_level === "urgent") {
        safetyMessage?.classList.add("assistant-safety-urgent");
      }
      endMockInterview(false);
      status.textContent =
        "The mock interview is paused. Seek appropriate human support before continuing.";
      return;
    }

    if (data.retry_required) {
      learningMockInterview.flaggedAttempts.push({
        question_index:
          learningMockInterview.questionIndex,
        answer: cleanedAnswer
      });

      const warningMessage =
        addLearningAssistantMessage(
          "assistant",
          data.authenticity_review.message
        );

      warningMessage?.classList.add(
        "authenticity-warning-message"
      );

      addLearningAssistantMessage(
        "assistant",
        (
          data.interviewer_reply +
          " Question " +
          data.question_number +
          ": " +
          data.question
        )
      );

      status.textContent =
        (
          "Try question " +
          data.question_number +
          " again before continuing."
        );

      return;
    }

    learningMockInterview.answers.push(
      cleanedAnswer
    );

    if (data.complete) {
      const reportMessage =
        addLearningAssistantMessage(
          "assistant",
          data.summary,
          [],
          (
            "Keep every interview answer accurate and " +
            "personal to your own experience."
          )
        );

      reportMessage?.classList.add(
        "mock-interview-report-message"
      );

      endMockInterview(false);
      status.textContent =
        "Mock interview complete. You can start another session.";
      return;
    }

    learningMockInterview.questionIndex += 1;

    updateMockInterviewProgress(
      data.question_number,
      data.total_questions
    );

    addLearningAssistantMessage(
      "assistant",
      (
        data.interviewer_reply +
        " Question " +
        data.question_number +
        ": " +
        data.question
      )
    );

    status.textContent =
      (
        "Answer question " +
        data.question_number +
        " when you are ready."
      );

  } catch (error) {
    typingMessage?.remove();
    status.textContent =
      error.message ||
      "Your interview answer could not be reviewed.";
    status.classList.add("error-message");

  } finally {
    learningAssistantRequestInProgress = false;
    setLearningAssistantBusy(false);
    input.focus();
  }
}


function getMockInterviewRequest(value) {
  const request = String(value || "").trim();
  const normalized = request.toLowerCase().replace(/[’']/g, "'");
  const wantsMockInterview =
    /\b(?:start|begin|launch|do|conduct|run|practice|try)\s+(?:a\s+|an\s+)?(?:(?:behavioral|general|first[- ]job)\s+)?(?:mock|practice)\s+interview\b/.test(normalized) ||
    /\b(?:mock|practice)\s+interview\s+(?:me|with me)\b/.test(normalized) ||
    /\binterview\s+me\b/.test(normalized);

  if (!wantsMockInterview) return null;

  const roleMatch = request.match(
    /\b(?:for|as)\s+(?:an|a|the)?\s*([^,.!?]+?)(?:\s+(?:role|position|job))?(?:[,.!?]|$)/i
  );
  let role = String(roleMatch?.[1] || "")
    .replace(/^(?:mock|practice)\s+interview\s+/i, "")
    .replace(/\s+(?:mock|practice)\s+interview$/i, "")
    .trim();
  if (/^(?:me|you|this|it)$/i.test(role)) role = "";

  const interviewType = /\bbehavioral\b/i.test(request)
    ? "behavioral"
    : /\b(?:first[- ]job|first interview)\b/i.test(request)
      ? "first_job"
      : "general";

  return { request, role, interviewType };
}


async function openMockInterviewFromRequest(value) {
  const parsed = getMockInterviewRequest(value);
  if (!parsed) return false;

  const input = document.getElementById("learningAssistantInput");
  const characterCount = document.getElementById("learningAssistantCharacterCount");
  const panel = document.getElementById("mockInterviewPanel");
  const roleInput = document.getElementById("mockInterviewRole");
  const typeSelect = document.getElementById("mockInterviewType");
  const status = document.getElementById("learningAssistantStatus");

  addLearningAssistantMessage("user", parsed.request);
  if (input) input.value = "";
  if (characterCount) characterCount.textContent = "0 / 800";
  if (panel) panel.hidden = false;
  if (typeSelect) typeSelect.value = parsed.interviewType;

  if (parsed.role) {
    if (roleInput) roleInput.value = parsed.role;
    await startMockInterview();
  } else {
    addLearningAssistantMessage(
      "assistant",
      "Absolutely. Enter the job role you want to practice for, choose an interview type, and select Begin five-question interview."
    );
    if (status) status.textContent = "Enter a role to begin your mock interview.";
    roleInput?.focus();
  }

  return true;
}


async function handleLearningAssistantSubmission(value) {
  if (learningMockInterview.active) {
    await submitMockInterviewAnswer(value);
    return;
  }

  if (await openMockInterviewFromRequest(value)) return;

  await askLearningAssistant(value);
}


function scrollLearningAssistant() {
  const messages =
    document.getElementById(
      "learningAssistantMessages"
    );

  if (messages) {
    messages.scrollTop =
      messages.scrollHeight;
  }
}


function addLearningAssistantMessage(
  role,
  text,
  followUps = [],
  authenticityReminder = ""
) {
  const messages =
    document.getElementById(
      "learningAssistantMessages"
    );

  if (!messages) {
    return null;
  }

  const message = document.createElement("article");

  message.className =
    "learning-assistant-message " +
    (
      role === "user"
        ? "user-message"
        : "assistant-message"
    );

  const heading = document.createElement("strong");

  heading.textContent =
    role === "user"
      ? "You"
      : "PathForge Career Assistant";

  const paragraph = document.createElement("p");
  paragraph.textContent = text;

  message.append(heading, paragraph);

  if (
    role === "assistant" &&
    followUps.length > 0
  ) {
    const followUpContainer =
      document.createElement("div");

    followUpContainer.className =
      "learning-assistant-follow-ups";

    const followUpHeading =
      document.createElement("p");

    followUpHeading.textContent =
      "You could also ask:";

    followUpContainer.appendChild(
      followUpHeading
    );

    followUps.forEach(question => {
      const button =
        document.createElement("button");

      button.type = "button";
      button.textContent = question;

      button.addEventListener(
        "click",
        function () {
          askLearningAssistant(question);
        }
      );

      followUpContainer.appendChild(button);
    });

    message.appendChild(followUpContainer);
  }

  if (
    role === "assistant" &&
    authenticityReminder
  ) {
    const reminder = document.createElement("p");

    reminder.className =
      "learning-assistant-authenticity";

    reminder.textContent =
      authenticityReminder;

    message.appendChild(reminder);
  }

  messages.appendChild(message);
  scrollLearningAssistant();

  return message;
}


function addLearningAssistantTypingMessage() {
  const messages =
    document.getElementById(
      "learningAssistantMessages"
    );

  if (!messages) {
    return null;
  }

  const message = document.createElement("article");

  message.className =
    "learning-assistant-message " +
    "assistant-message typing-message";

  const heading = document.createElement("strong");
  heading.textContent =
    "PathForge Career Assistant";

  const paragraph = document.createElement("p");
  paragraph.textContent =
    "Preparing guidance...";

  message.append(heading, paragraph);
  messages.appendChild(message);

  scrollLearningAssistant();

  return message;
}


function appendLearningAssistantList(container, items) {
  const list = document.createElement("ul");
  (items || []).forEach(text => {
    const item = document.createElement("li");
    item.textContent = text;
    list.appendChild(item);
  });
  container.appendChild(list);
}


function addLearningAssistantResumeEvaluation(
  evaluation,
  followUps = [],
  authenticityReminder = ""
) {
  const messages = document.getElementById("learningAssistantMessages");
  if (!messages || !evaluation) return null;

  const review = adaptBackendResumeEvaluation(evaluation);
  const message = document.createElement("article");
  message.className = "learning-assistant-message assistant-message learning-resume-evaluation";

  const assistantName = document.createElement("strong");
  assistantName.textContent = "PathForge Career Assistant";
  const title = document.createElement("h3");
  title.textContent = "Your resume feedback";
  message.append(assistantName, title);

  const overview = document.createElement("div");
  overview.className = "learning-resume-overview";

  const scoreCard = document.createElement("section");
  scoreCard.className = "learning-resume-overview-card learning-resume-score-card";
  const scoreLabel = document.createElement("h4");
  scoreLabel.textContent = "Overall score";
  const ring = document.createElement("div");
  ring.className = "learning-resume-score-ring";
  const score = Math.max(0, Math.min(100, Number(review.score) || 0));
  ring.style.setProperty("--score-progress", `${score * 3.6}deg`);
  ring.setAttribute("aria-label", `Resume score: ${score} out of 100`);
  const ringValue = document.createElement("span");
  ringValue.innerHTML = `<strong>${score}</strong><small>/100</small>`;
  ring.appendChild(ringValue);
  const rangeName = score >= 81 ? "Exceptional evidence" : score >= 61
    ? "Strong foundation" : score >= 41 ? "Developing foundation" : "Early foundation";
  const rangeCaption = document.createElement("p");
  rangeCaption.textContent = rangeName;
  scoreCard.append(scoreLabel, ring, rangeCaption);

  const summaryCard = document.createElement("section");
  summaryCard.className = "learning-resume-overview-card";
  const summaryTitle = document.createElement("h4");
  summaryTitle.textContent = "Score summary";
  const summary = document.createElement("p");
  const passed = review.checks.filter(check => check.passed).length;
  summary.textContent = `${review.mode} review. ${passed} of ${review.checks.length} evidence checks are currently strong. This is guidance, not a hiring prediction.`;
  summaryCard.append(summaryTitle, summary);

  const rangesCard = document.createElement("section");
  rangesCard.className = "learning-resume-overview-card";
  const rangesTitle = document.createElement("h4");
  rangesTitle.textContent = "Score ranges";
  const ranges = document.createElement("div");
  ranges.className = "learning-resume-ranges";
  [[1, 40, "Early foundation"], [41, 60, "Developing"], [61, 80, "Strong"], [81, 100, "Exceptional evidence"]].forEach(([min, max, label]) => {
    const row = document.createElement("span");
    if (score >= min && score <= max) row.className = "current-range";
    row.innerHTML = `<strong>${min}&ndash;${max}</strong><span>${label}</span>`;
    ranges.appendChild(row);
  });
  rangesCard.append(rangesTitle, ranges);
  overview.append(scoreCard, summaryCard, rangesCard);
  message.appendChild(overview);

  const breakdown = evaluation.score_breakdown || review.scoreBreakdown;
  if (breakdown) {
    const context = document.createElement("section");
    context.className = "learning-resume-section learning-resume-context";
    const contextHeading = document.createElement("div");
    contextHeading.className = "learning-resume-section-heading";
    const contextTitle = document.createElement("h4");
    contextTitle.textContent = "Score context";
    const stage = document.createElement("span");
    const stageLabel = breakdown.career_stage?.label || "Career stage not confirmed";
    const stageSource = breakdown.career_stage?.source === "selected" ? "selected" : "auto";
    stage.textContent = `${stageLabel} (${stageSource})`;
    contextHeading.append(contextTitle, stage);
    const explanation = document.createElement("p");
    explanation.textContent = breakdown.context_explanation || "";
    const rubric = document.createElement("p");
    rubric.className = "learning-resume-rubric";
    const weights = breakdown.category_weights || {};
    const weightText = Object.keys(weights).length
      ? ` Weights: Skills ${weights.skills}%, impact ${weights.impact_metrics}%, grammar and tone ${weights.grammar_tone}%, formatting ${weights.formatting}%, timeline ${weights.timeline_logic}%.`
      : "";
    rubric.textContent = (breakdown.rubric_note || "") + weightText;
    const factors = document.createElement("div");
    factors.className = "learning-resume-factor-grid";
    [["What held the score back", breakdown.factors_lowering_score], ["What supported the score", breakdown.factors_supporting_score]].forEach(([headingText, items]) => {
      const group = document.createElement("div");
      const heading = document.createElement("h5");
      heading.textContent = headingText;
      group.appendChild(heading);
      appendLearningAssistantList(group, (items || []).slice(0, 3));
      factors.appendChild(group);
    });
    const reassurance = document.createElement("p");
    reassurance.className = "learning-resume-reassurance";
    reassurance.textContent = breakdown.reassurance_note || "";
    context.append(contextHeading, explanation, rubric, factors, reassurance);
    message.appendChild(context);
  }

  const strengths = document.createElement("section");
  strengths.className = "learning-resume-section learning-resume-strengths";
  const strengthsTitle = document.createElement("h4");
  strengthsTitle.textContent = "Strong points";
  strengths.appendChild(strengthsTitle);
  appendLearningAssistantList(strengths, review.strengths);
  message.appendChild(strengths);

  const checks = document.createElement("div");
  checks.className = "learning-resume-checks";
  review.checks.forEach(check => {
    const card = document.createElement("section");
    card.className = "learning-resume-check" + (check.passed ? "" : " needs-work");
    const heading = document.createElement("h4");
    heading.textContent = `${check.passed ? "Strong" : "Needs attention"}: ${check.title}`;
    const description = document.createElement("p");
    description.textContent = check.message;
    card.append(heading, description);
    (check.rewrites || []).forEach(rewrite => {
      const example = document.createElement("div");
      example.className = "learning-resume-rewrite";
      const before = document.createElement("p");
      before.textContent = `Before: ${rewrite.before}`;
      const after = document.createElement("p");
      after.textContent = `After: ${rewrite.after}`;
      example.append(before, after);
      card.appendChild(example);
    });
    checks.appendChild(card);
  });
  message.appendChild(checks);

  const priorities = document.createElement("section");
  priorities.className = "learning-resume-section learning-resume-priorities";
  const prioritiesTitle = document.createElement("h4");
  prioritiesTitle.textContent = "What to improve first";
  priorities.appendChild(prioritiesTitle);
  const ordered = document.createElement("ol");
  (review.actionItems || []).slice(0, 4).forEach(action => {
    const item = document.createElement("li");
    item.textContent = action;
    ordered.appendChild(item);
  });
  priorities.appendChild(ordered);
  message.appendChild(priorities);

  if (followUps.length) {
    const followUpContainer = document.createElement("div");
    followUpContainer.className = "learning-assistant-follow-ups";
    const prompt = document.createElement("p");
    prompt.textContent = "Continue with:";
    followUpContainer.appendChild(prompt);
    followUps.forEach(question => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = question;
      button.addEventListener("click", () => askLearningAssistant(question));
      followUpContainer.appendChild(button);
    });
    message.appendChild(followUpContainer);
  }
  if (authenticityReminder) {
    const reminder = document.createElement("p");
    reminder.className = "learning-assistant-authenticity";
    reminder.textContent = authenticityReminder;
    message.appendChild(reminder);
  }
  messages.appendChild(message);
  scrollLearningAssistant();
  return message;
}


// General guidance, file review, and mock interviews use separate validation paths.
async function askLearningAssistant(question) {
  const input =
    document.getElementById(
      "learningAssistantInput"
    );

  const status =
    document.getElementById(
      "learningAssistantStatus"
    );

  const characterCount =
    document.getElementById(
      "learningAssistantCharacterCount"
    );

  const cleanedQuestion =
    String(question || "").trim();

  if (!input || !status) {
    return;
  }

  if (learningAssistantRequestInProgress) {
  status.textContent =
    "Please wait for the current response.";

    return;
  }

  status.classList.remove("error-message");

  if (cleanedQuestion === "") {
    status.textContent =
      "Please enter a question or request.";

    status.classList.add("error-message");
    input.focus();

    return;
  }

  if (cleanedQuestion.length > 800) {
    status.textContent =
      "Please keep your question under 800 characters.";

    status.classList.add("error-message");
    input.focus();

    return;
  }

  addLearningAssistantMessage(
    "user",
    cleanedQuestion +
      (
        learningAssistantAttachment
          ? "\nAttached: " +
            learningAssistantAttachment.name
          : ""
      )
  );

  input.value = "";

  if (characterCount) {
    characterCount.textContent = "0 / 800";
  }

  const typingMessage =
    addLearningAssistantTypingMessage();
  const typingParagraph =
    typingMessage?.querySelector("p");
  const reviewStartedAt = Date.now();
  const minimumReviewTime =
    learningAssistantAttachment ? 2800 : 1800;

  if (typingParagraph) {
    typingParagraph.textContent =
      learningAssistantAttachment
        ? (
          "PathForge Career Assistant is typing while " +
          "reviewing your document..."
        )
        : (
          "PathForge Career Assistant is typing while " +
          "reviewing your request..."
        );
  }

  status.textContent =
    learningAssistantAttachment
      ? "The assistant is carefully reviewing the document."
      : "The assistant is preparing guidance.";

  learningAssistantRequestInProgress = true;
  setLearningAssistantBusy(true);

  try {
    const response = await fetch(
      apiUrl("/learning-assistant"),
      {
        method: "POST",

        headers: {
          "Content-Type": "application/json"
        },

        credentials: "include",

        body: JSON.stringify({
          message: cleanedQuestion,
          attachment_name:
            learningAssistantAttachment?.name || null,
          attachment_text:
            learningAssistantAttachment?.text || null,
          career_stage: learningAssistantAttachment
            ? (document.getElementById("learningAssistantCareerStage")?.value || "auto")
            : null
        })
      }
    );

    if (response.status === 401) {
      window.location.href = "login.html";
      return;
    }

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        data.detail ||
        "The assistant could not answer right now."
      );
    }

    status.textContent =
      "Reviewing the response for consistency...";

    await waitForMinimumAssistantReview(
      reviewStartedAt,
      minimumReviewTime
    );

    typingMessage?.remove();

    const followUpQuestions = Array.isArray(data.follow_up_questions)
      ? data.follow_up_questions
      : [];
    const assistantMessage = data.resume_evaluation
      ? addLearningAssistantResumeEvaluation(
          data.resume_evaluation,
          followUpQuestions,
          data.authenticity_reminder || ""
        )
      : addLearningAssistantMessage(
          "assistant",
          data.reply,
          followUpQuestions,
          data.authenticity_reminder || ""
        );
    if (data.safety_notice) {
      assistantMessage?.classList.add("assistant-safety-message");
      if (data.safety_level === "urgent") {
        assistantMessage?.classList.add("assistant-safety-urgent");
      }
    }

    status.textContent =
      "Guidance received. Review and personalize it.";

    clearLearningAssistantAttachment();

    if (data.request_document_upload === true) {
      setLearningAssistantUploadVisibility(
        true,
        assistantMessage
      );
      status.textContent =
        "Select your document, then ask what you would like help with.";
    } else {
      setLearningAssistantUploadVisibility(false);
    }

  } catch (error) {
    console.error(
      "Learning assistant request failed:",
      error
    );

    typingMessage?.remove();

    const errorMessage =
      addLearningAssistantMessage(
        "assistant",
        error.message ||
          "The assistant could not answer right now."
      );

    errorMessage?.classList.add(
      "error-message"
    );

    status.textContent =
      "The assistant could not answer. Please try again.";

    status.classList.add("error-message");

  } finally {
    learningAssistantRequestInProgress = false;
    setLearningAssistantBusy(false);
    input.focus();
  }
}


function setLearningAssistantUploadVisibility(
  isVisible,
  messageContainer = null
) {
  learningAssistantUploadRequested = isVisible;

  const attachmentArea =
    document.getElementById(
      "learningAssistantAttachment"
    );

  if (!attachmentArea) {
    return;
  }

  if (isVisible && messageContainer) {
    const followUps =
      messageContainer.querySelector(
        ".learning-assistant-follow-ups"
      );

    messageContainer.insertBefore(
      attachmentArea,
      followUps
    );
  } else if (!isVisible) {
    const form =
      document.getElementById(
        "learningAssistantForm"
      );

    const footer =
      form?.querySelector(
        ".learning-assistant-form-footer"
      );

    if (form && footer) {
      form.insertBefore(
        attachmentArea,
        footer
      );
    }
  }

  attachmentArea.hidden =
    !isVisible || learningMockInterview.active;
}


function clearLearningAssistantAttachment() {
  learningAssistantAttachment = null;

  const fileInput =
    document.getElementById(
      "learningAssistantFile"
    );

  const attachedFile =
    document.getElementById(
      "learningAssistantAttachedFile"
    );

  const attachedFileName =
    document.getElementById(
      "learningAssistantAttachedFileName"
    );

  if (fileInput) {
    fileInput.value = "";
  }

  if (attachedFileName) {
    attachedFileName.textContent = "";
  }

  attachedFile?.classList.add("hidden");
}


function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();

    reader.addEventListener("load", () => {
      const result = String(reader.result || "");
      resolve(result.split(",", 2)[1] || "");
    });

    reader.addEventListener("error", () => {
      reject(new Error("PathForge could not read that file."));
    });

    reader.readAsDataURL(file);
  });
}


async function attachLearningAssistantFile(file) {
  const status =
    document.getElementById(
      "learningAssistantStatus"
    );
  let shouldStartEvaluation = false;

  if (!file || !status) {
    return;
  }

  if (file.size > 5 * 1024 * 1024) {
    clearLearningAssistantAttachment();
    status.textContent =
      "Choose a document no larger than 5 MB.";
    status.classList.add("error-message");
    return;
  }

  status.classList.remove("error-message");
  status.textContent = "Reading " + file.name + "...";
  setLearningAssistantBusy(true);

  try {
    const contentBase64 =
      await readFileAsBase64(file);

    const response = await fetch(
      (
        apiUrl("/") +
        "learning-assistant/extract-document"
      ),
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        credentials: "include",
        body: JSON.stringify({
          filename: file.name,
          content_base64: contentBase64
        })
      }
    );

    if (response.status === 401) {
      window.location.href = "login.html";
      return;
    }

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        data.detail ||
        "PathForge could not read that document."
      );
    }

    learningAssistantAttachment = {
      name: data.filename,
      text: data.text
    };

    document.getElementById(
      "learningAssistantAttachedFileName"
    ).textContent =
      data.filename +
      " (" +
      Number(data.characters || 0).toLocaleString() +
      " readable characters)";

    document.getElementById(
      "learningAssistantAttachedFile"
    ).classList.remove("hidden");

    status.textContent =
      "Document ready. Starting your resume evaluation...";

    shouldStartEvaluation = true;

  } catch (error) {
    clearLearningAssistantAttachment();
    status.textContent =
      error.message ||
      "PathForge could not read that document.";
    status.classList.add("error-message");

  } finally {
    setLearningAssistantBusy(false);
  }

  if (shouldStartEvaluation) {
    await handleLearningAssistantSubmission(
      "Evaluate my attached resume. Identify its strengths, " +
      "the most important improvements, readability or ATS " +
      "concerns, and clear next steps. Keep every suggestion " +
      "truthful and do not invent experience or qualifications."
    );
  }
}


function setupLearningAssistant() {
  const form =
    document.getElementById(
      "learningAssistantForm"
    );

  const input =
    document.getElementById(
      "learningAssistantInput"
    );

  const characterCount =
    document.getElementById(
      "learningAssistantCharacterCount"
    );

  const suggestions =
    document.querySelectorAll(
      "[data-learning-question]"
    );

  if (!form || !input) {
    return;
  }

  const fileInput =
    document.getElementById(
      "learningAssistantFile"
    );

  fileInput?.addEventListener(
    "change",
    function () {
      const file = fileInput.files?.[0];

      if (file) {
        attachLearningAssistantFile(file);
      }
    }
  );

  document
    .getElementById("removeLearningAssistantFile")
    ?.addEventListener(
      "click",
      function () {
        clearLearningAssistantAttachment();

        const status =
          document.getElementById(
            "learningAssistantStatus"
          );

        if (status) {
          status.classList.remove("error-message");
          status.textContent = "Document removed.";
        }
      }
    );

  input.addEventListener(
    "input",
    function () {
      if (characterCount) {
        characterCount.textContent =
          input.value.length +
          " / " +
          input.maxLength;
      }
    }
  );

  input.addEventListener(
  "keydown",
  function (event) {
    if (
      event.key === "Enter" &&
      !event.shiftKey
    ) {
      event.preventDefault();

      handleLearningAssistantSubmission(
        input.value
      );
    }
  }
);

  form.addEventListener(
    "submit",
    function (event) {
      event.preventDefault();

      handleLearningAssistantSubmission(
        input.value
      );
    }
  );

  suggestions.forEach(button => {
    button.addEventListener(
      "click",
      function () {
        const question =
          button.dataset.learningQuestion;

        if (question) {
          askLearningAssistant(question);
        }
      }
    );
  });

  const openMockInterviewButton =
    document.getElementById(
      "openMockInterviewButton"
    );

  const mockInterviewPanel =
    document.getElementById(
      "mockInterviewPanel"
    );

  const startMockInterviewButton =
    document.getElementById(
      "startMockInterviewButton"
    );

  const endMockInterviewButton =
    document.getElementById(
      "endMockInterviewButton"
    );

  openMockInterviewButton?.addEventListener(
    "click",
    function () {
      mockInterviewPanel.hidden = false;
      document
        .getElementById("mockInterviewRole")
        ?.focus();
    }
  );

  startMockInterviewButton?.addEventListener(
    "click",
    startMockInterview
  );

  endMockInterviewButton?.addEventListener(
    "click",
    function () {
      endMockInterview(true);
    }
  );

  const status =
    document.getElementById(
      "learningAssistantStatus"
    );

  if (status) {
    status.textContent =
      "Press Enter to send. Use Shift+Enter for a new line.";
  }

  setLearningAssistantBusy(false);
}

function setupEmployerDashboard() {
  const employerJobForm =
    document.getElementById("employerJobForm");

  if (!employerJobForm) {
    return;
  }

  setupEmployerCompanyProfile();
  setupEmployerJobForm();
  setupEmployerJobEditor();
  setupEmployerApplicationFormBuilder();
  loadEmployerDashboard();
  }

const moderationReasonLabels = {
  suspected_scam: "Suspected scam or fraud",
  misleading_information: "Misleading information",
  expired_or_broken_link: "Expired or broken link",
  discriminatory_content: "Discriminatory content",
  duplicate_listing: "Duplicate listing",
  other: "Other concern"
};

async function loadAdminOperations() {
  const status = document.getElementById("operationsStatus");
  if (!status) return;
  status.textContent = "Loading catalog health…";
  status.classList.remove("error-message");
  try {
    const response = await fetch(apiUrl("/admin/operations"), { credentials: "include" });
    if (response.status === 401) { window.location.href = "login.html"; return; }
    if (response.status === 403) { window.location.href = "index.html"; return; }
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Catalog health could not be loaded.");
    const summary = data.summary || {};
    const values = {
      operationsActiveCount: summary.active_jobs,
      operationsBrokenCount: summary.broken_links,
      operationsStaleCount: summary.stale_jobs,
      operationsExpiringCount: summary.expiring_soon,
      operationsChangesCount: summary.changes_24h,
      operationsPendingCount: summary.pending_reports,
      operationsCategoryCount: summary.uncategorized_jobs,
      operationsTypeCount: summary.missing_employment_type,
      operationsPayCount: summary.missing_pay,
      operationsStateCount: summary.covered_states,
      operationsFailedSourceCount: summary.failed_sources,
      operationsDropCount: summary.source_drop_alerts
    };
    Object.entries(values).forEach(([id, value]) => {
      const element = document.getElementById(id);
      if (element) element.textContent = Number(value || 0).toLocaleString();
    });
    const sourceRows = document.getElementById("operationsSourceRows");
    if (sourceRows) sourceRows.innerHTML = (data.sources || []).map(source => `<tr><th scope="row">${escapeEmployerHtml(source.source)}</th><td>${source.total_jobs}</td><td>${source.active_jobs}</td><td>${Number(source.active_share_percent || 0).toLocaleString()}%</td><td>${source.broken_links}</td><td>${source.stale_jobs}</td><td>${escapeEmployerHtml(formatModerationDate(source.last_verified_at))}</td></tr>`).join("") || `<tr><td colspan="7">No listing sources yet.</td></tr>`;
    const geography = document.getElementById("operationsGeography");
    if (geography) {
      const missing = data.geography?.missing_states || [];
      geography.textContent = missing.length
        ? `No state-specific listings currently detected for: ${missing.join(", ")}. Nationwide and remote listings are tracked separately.`
        : "Every state and the District of Columbia has at least one state-specific listing.";
    }
    const failures = document.getElementById("operationsSourceFailures");
    if (failures) {
      const failedSources = (data.sync_sources || []).filter(source => source.status === "failed" || (source.previous_imported >= 10 && source.imported < source.previous_imported * 0.5));
      failures.innerHTML = failedSources.map(source => `<article class="moderation-report-card"><h4>${escapeEmployerHtml(source.employer)}</h4><p>${escapeEmployerHtml(source.source)} · Last attempted ${escapeEmployerHtml(formatModerationDate(source.last_attempt_at))}</p><p>${source.status === "failed" ? escapeEmployerHtml(source.error || "The source did not complete successfully.") : `Imported listings fell from ${Number(source.previous_imported).toLocaleString()} to ${Number(source.imported).toLocaleString()}. Verify the employer board before the next refresh.`}</p></article>`).join("") || `<div class="moderation-empty-state"><h3>No source alerts</h3><p>Every source completed without a large listing-count drop.</p></div>`;
    }
    const issueList = document.getElementById("operationsIssueList");
    if (issueList) issueList.innerHTML = (data.issues || []).map(job => `<article class="moderation-report-card"><div class="moderation-report-heading"><div><h4>${escapeEmployerHtml(job.title)}</h4><p>${escapeEmployerHtml(job.company)} · ${escapeEmployerHtml(job.source || "PathForge employer")}</p></div><span class="moderation-status-badge ${job.link_status === "unavailable" ? "status-submitted" : "status-reviewed"}">${job.link_status === "unavailable" ? "Broken link" : "Verify"}</span></div><p>Last verified: ${escapeEmployerHtml(formatModerationDate(job.last_verified_at))}</p><div class="moderation-listing-actions"><a href="jobs.html?job=${job.id}">Review listing</a></div></article>`).join("") || `<div class="moderation-empty-state"><h3>No immediate catalog issues</h3><p>All tracked listings are within the current health thresholds.</p></div>`;
    status.textContent = `${(data.issues || []).length} listing${(data.issues || []).length === 1 ? "" : "s"} need attention.`;
  } catch (error) {
    status.classList.add("error-message");
    status.textContent = error.message || "Catalog health could not be loaded.";
  }
}

function formatModerationDate(value) {
  if (!value) return "Not recorded";
  const input = String(value);
  const date = new Date(input.includes("T") ? input : input.replace(" ", "T") + "Z");
  if (Number.isNaN(date.getTime())) return "Not recorded";
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function getModerationListingUrl(report) {
  try {
    const url = new URL(report.application_url || report.source_url || "");
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch (error) { return ""; }
}

function renderModerationReports(reports) {
  const container = document.getElementById("moderationReportList");
  if (!container) return;
  if (!reports.length) {
    container.innerHTML = `<div class="moderation-empty-state"><h3>No reports in this view</h3><p>Choose another status to review earlier moderation activity.</p></div>`;
    return;
  }
  container.innerHTML = reports.map(report => {
    const listingUrl = getModerationListingUrl(report);
    const noteId = `moderationNote${report.id}`;
    const statusId = `moderationStatus${report.id}`;
    return `<article class="moderation-report-card" data-report-id="${report.id}">
      <div class="moderation-report-heading"><div>
        <span class="moderation-status-badge status-${escapeEmployerHtml(report.status)}">${report.status === "submitted" ? "Awaiting review" : escapeEmployerHtml(report.status)}</span>
        <h3>${escapeEmployerHtml(report.job_title)}</h3>
        <p>${escapeEmployerHtml(report.job_company)} · ${escapeEmployerHtml(report.job_location || "Location not listed")}</p>
      </div><span class="moderation-report-id">Report #${report.id}</span></div>
      <dl class="moderation-report-facts">
        <div><dt>Concern</dt><dd>${escapeEmployerHtml(moderationReasonLabels[report.reason] || report.reason)}</dd></div>
        <div><dt>Submitted</dt><dd>${escapeEmployerHtml(formatModerationDate(report.created_at))}</dd></div>
        <div><dt>Reporter</dt><dd>${escapeEmployerHtml(report.reporter_username)} (${escapeEmployerHtml(report.reporter_email)})</dd></div>
        <div><dt>Listing status</dt><dd>${escapeEmployerHtml(report.job_status || "Unknown")} · Link ${escapeEmployerHtml(report.link_status || "unknown")}</dd></div>
      </dl>
      <section class="moderation-report-details" aria-label="User report details"><h4>User-provided details</h4><p>${escapeEmployerHtml(report.details || "No additional details were provided.")}</p></section>
      <div class="moderation-listing-actions"><a href="jobs.html?job=${report.job_id}">View PathForge listing</a>${listingUrl ? `<a href="${escapeEmployerHtml(listingUrl)}" target="_blank" rel="noopener noreferrer">Open application source</a>` : ""}</div>
      <div class="moderation-decision-grid">
        <label for="${statusId}">Moderation status<select id="${statusId}" class="moderation-card-status"><option value="submitted" ${report.status === "submitted" ? "selected" : ""}>Awaiting review</option><option value="reviewed" ${report.status === "reviewed" ? "selected" : ""}>Reviewed</option><option value="resolved" ${report.status === "resolved" ? "selected" : ""}>Resolved</option></select></label>
        <label for="${noteId}">Internal moderation note<textarea id="${noteId}" class="moderation-card-note" maxlength="1000" placeholder="Record what was checked and why this status is appropriate.">${escapeEmployerHtml(report.moderation_note || "")}</textarea></label>
      </div>
      <div class="moderation-card-footer"><p>${report.moderator_username ? `Last handled by ${escapeEmployerHtml(report.moderator_username)} · ${escapeEmployerHtml(formatModerationDate(report.updated_at))}` : "No moderator action recorded yet."}</p><button class="moderation-save-button" type="button" data-report-id="${report.id}">Save Decision</button></div>
      <p class="moderation-card-message form-message" role="status" aria-live="polite"></p>
    </article>`;
  }).join("");
  container.querySelectorAll(".moderation-save-button").forEach(button => {
    button.addEventListener("click", () => saveModerationDecision(button));
  });
}

async function loadModerationReports() {
  const filter = document.getElementById("moderationStatusFilter");
  const pageStatus = document.getElementById("moderationPageStatus");
  if (!filter || !pageStatus) return;
  pageStatus.classList.remove("error-message", "success-message");
  pageStatus.textContent = "Loading reports…";
  try {
    const response = await fetch(apiUrl(`/admin/job-reports?status=${encodeURIComponent(filter.value)}`), { credentials: "include" });
    if (response.status === 401) { window.location.href = "login.html"; return; }
    if (response.status === 403) { window.location.href = "index.html"; return; }
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Reports could not be loaded.");
    document.getElementById("moderationSubmittedCount").textContent = data.counts.submitted;
    document.getElementById("moderationReviewedCount").textContent = data.counts.reviewed;
    document.getElementById("moderationResolvedCount").textContent = data.counts.resolved;
    document.getElementById("moderationAllCount").textContent = data.counts.all;
    renderModerationReports(data.reports);
    pageStatus.textContent = `${data.reports.length} report${data.reports.length === 1 ? "" : "s"} shown.`;
  } catch (error) {
    pageStatus.classList.add("error-message");
    pageStatus.textContent = error.message || "Reports could not be loaded.";
  }
}

async function saveModerationDecision(button) {
  const card = button.closest(".moderation-report-card");
  const message = card?.querySelector(".moderation-card-message");
  const status = card?.querySelector(".moderation-card-status")?.value;
  const moderationNote = card?.querySelector(".moderation-card-note")?.value || "";
  if (!card || !message || !status) return;
  button.disabled = true;
  message.classList.remove("error-message", "success-message");
  message.textContent = "Saving decision…";
  try {
    const response = await fetch(apiUrl(`/admin/job-reports/${button.dataset.reportId}`), { method: "PATCH", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status, moderation_note: moderationNote }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Decision could not be saved.");
    await loadModerationReports();
  } catch (error) {
    message.classList.add("error-message");
    message.textContent = error.message || "Decision could not be saved.";
    button.disabled = false;
  }
}

function initializeAdminModerationPage() {
  if (!document.getElementById("moderationReportList")) return;
  document.getElementById("moderationStatusFilter")?.addEventListener("change", loadModerationReports);
  document.getElementById("refreshOperationsButton")?.addEventListener("click", loadAdminOperations);
  loadAdminOperations();
  loadModerationReports();
}

function safeExternalUrl(value) {
  try {
    const url = new URL(value || "");
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch (error) { return ""; }
}

async function initializeCompanyResearchPage() {
  const content = document.getElementById("companyResearchContent");
  const status = document.getElementById("companyResearchStatus");
  if (!content || !status) return;
  const companyName = new URLSearchParams(window.location.search).get("name")?.trim();
  if (!companyName) {
    status.classList.add("error-message");
    status.textContent = "Choose a company from a PathForge job listing.";
    return;
  }
  try {
    const response = await fetch(apiUrl(`/companies/${encodeURIComponent(companyName)}`));
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Company research could not be loaded.");
    const company = data.company;
    document.title = `${company.name} — PathForge Company Research`;
    document.getElementById("companyResearchName").textContent = company.name;
    document.getElementById("companyResearchDescription").textContent = company.description || "PathForge does not currently have an employer-provided company description.";
    const logo = document.getElementById("companyResearchLogo");
    const logoUrl = safeExternalUrl(company.logo_url);
    logo.textContent = company.name.charAt(0).toUpperCase();
    if (logoUrl) logo.innerHTML = `<img src="${escapeEmployerHtml(logoUrl)}" alt="">`;
    if (company.brand_color && /^#[0-9a-f]{6}$/i.test(company.brand_color)) logo.style.backgroundColor = company.brand_color;
    const website = document.getElementById("companyResearchWebsite");
    const websiteUrl = safeExternalUrl(company.website);
    if (websiteUrl) { website.href = websiteUrl; website.hidden = false; }
    const summary = data.summary;
    document.getElementById("companyResearchSummary").innerHTML = `
      <div><strong>${summary.active_job_count}</strong><span>Active jobs</span></div>
      <div><strong>${summary.remote_job_count}</strong><span>Remote-listed jobs</span></div>
      <div><strong>${summary.published_salary_count}</strong><span>Jobs with published pay</span></div>
      <div><strong>${summary.locations.length}</strong><span>Listed locations</span></div>`;
    const sourceLabel = company.profile_source === "employer_provided" ? "Employer-provided" : "Not provided";
    document.getElementById("companyResearchWorkplace").innerHTML = `
      <p class="company-source-label">${sourceLabel}</p>
      <h3>Hiring process and workplace details</h3>
      <p>${escapeEmployerHtml(company.hiring_information || "The employer has not provided hiring-process, benefits, or workplace details on PathForge.")}</p>
      <h3>Job types currently listed</h3><p>${escapeEmployerHtml(summary.job_types.join(", ") || "Not specified")}</p>
      <h3>Locations represented</h3><p>${escapeEmployerHtml(summary.locations.slice(0, 12).join(", ") || "Not specified")}${summary.locations.length > 12 ? " and more" : ""}</p>`;
    const validSources = data.sources.filter(source => safeExternalUrl(source.url));
    document.getElementById("companyResearchSources").innerHTML = validSources.length ? validSources.map(source => `
      <article class="company-source-item"><div><strong>${escapeEmployerHtml(source.name)}</strong><span>${source.verification_status === "verified" ? "Official hiring source checked by PathForge" : "Listing source"}</span></div><a href="${escapeEmployerHtml(safeExternalUrl(source.url))}" target="_blank" rel="noopener noreferrer">Open source</a><p>Last checked: ${escapeEmployerHtml(formatJobCardDate(source.last_verified_at))}</p></article>`).join("") : `<p>No verified external resources are currently available.</p>`;
    document.getElementById("companyJobsCount").textContent = `${summary.active_job_count} active listing${summary.active_job_count === 1 ? "" : "s"}`;
    document.getElementById("companyResearchJobs").innerHTML = data.active_jobs.length ? data.active_jobs.map(job => `
      <article class="company-research-job"><div><h3><a href="jobs.html?job=${job.id}">${escapeEmployerHtml(job.title)}</a></h3><p>${escapeEmployerHtml(job.location || "Location not listed")}</p></div><div class="company-job-tags"><span>${escapeEmployerHtml(job.employment_type || job.schedule || "Job type not listed")}</span><span>${escapeEmployerHtml(job.pay || "Pay not listed")}</span><span>${escapeEmployerHtml(job.trust_label || "Limited Verification")}</span></div></article>`).join("") : `<p>No active PathForge jobs are currently listed.</p>`;
    status.textContent = "";
    content.hidden = false;
  } catch (error) {
    status.classList.add("error-message");
    status.textContent = error.message || "Company research could not be loaded.";
  }
}

function requiredFieldLabel(field) {
  if (!field) return "this field";
  let label = field.closest("label");
  if (!label && field.id) {
    label = document.querySelector(`label[for="${CSS.escape(field.id)}"]`);
  }
  const labelText = String(label?.textContent || field.getAttribute("aria-label") || field.name || "this field")
    .replace(/\*/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return labelText || "this field";
}

function markRequiredControl(field) {
  if (!(field instanceof HTMLElement) || field.disabled) return;
  let label = field.closest("label");
  if (!label && field.id) {
    label = document.querySelector(`label[for="${CSS.escape(field.id)}"]`);
  }
  if (!label || label.querySelector(".required-field-asterisk, .required-indicator")) return;

  const indicator = document.createElement("span");
  indicator.className = "required-field-asterisk";
  indicator.setAttribute("aria-hidden", "true");
  indicator.textContent = "*";
  if (label.contains(field)) {
    label.insertBefore(indicator, field);
  } else {
    label.appendChild(indicator);
  }
  label.classList.add("required-field-label");
}

function enhanceRequiredForm(form) {
  if (!(form instanceof HTMLFormElement)) return;
  const requiredFields = [...form.querySelectorAll("input[required], select[required], textarea[required]")]
    .filter(field => !field.disabled);
  if (!requiredFields.length) return;

  requiredFields.forEach(markRequiredControl);
  let reminder = form.querySelector(":scope > .required-fields-reminder");
  if (!reminder) {
    reminder = document.createElement("p");
    reminder.className = "required-fields-reminder";
    reminder.innerHTML = `<span aria-hidden="true">*</span> Required fields are marked with a red asterisk.`;
    form.insertBefore(reminder, form.firstChild);
  }

  let message = form.querySelector(":scope > .required-fields-message");
  if (!message) {
    message = document.createElement("p");
    message.className = "required-fields-message";
    message.setAttribute("role", "alert");
    message.setAttribute("aria-live", "assertive");
    message.hidden = true;
    reminder.after(message);
  }
}

function missingRequiredFields(form) {
  const seenGroups = new Set();
  return [...form.querySelectorAll("input[required], select[required], textarea[required]")]
    .filter(field => {
      if (field.disabled || field.validity.valid) return false;
      if ((field.type === "radio" || field.type === "checkbox") && field.name) {
        const groupKey = `${field.type}:${field.name}`;
        if (seenGroups.has(groupKey)) return false;
        seenGroups.add(groupKey);
      }
      return true;
    })
    .sort((first, second) => {
      const firstVisible = first.getClientRects().length > 0;
      const secondVisible = second.getClientRects().length > 0;
      if (firstVisible !== secondVisible) return firstVisible ? -1 : 1;
      const verticalDifference = first.getBoundingClientRect().top - second.getBoundingClientRect().top;
      if (Math.abs(verticalDifference) > 1) return verticalDifference;
      return first.getBoundingClientRect().left - second.getBoundingClientRect().left;
    });
}

function updateRequiredFieldsMessage(form, missingFields) {
  const message = form.querySelector(":scope > .required-fields-message");
  if (!message) return;
  if (!missingFields.length) {
    message.hidden = true;
    message.textContent = "";
    return;
  }
  const count = missingFields.length;
  message.textContent = `Please complete ${count} required field${count === 1 ? "" : "s"}. Start with: ${requiredFieldLabel(missingFields[0])}.`;
  message.hidden = false;
}

function initializeRequiredFieldGuidance() {
  document.querySelectorAll("form").forEach(enhanceRequiredForm);

  document.addEventListener("invalid", event => {
    const field = event.target;
    const form = field?.form;
    if (!form || !field.required) return;
    event.preventDefault();
    enhanceRequiredForm(form);
    const missingFields = missingRequiredFields(form);
    const firstMissingField = missingFields[0] || field;
    missingFields.forEach(missingField => {
      missingField.setAttribute("aria-invalid", "true");
      missingField.classList.add("required-field-missing");
    });

    if (form.dataset.requiredInvalidActive === "true") return;
    form.dataset.requiredInvalidActive = "true";
    updateRequiredFieldsMessage(form, missingFields);
    window.requestAnimationFrame(() => {
      firstMissingField.scrollIntoView({ behavior: "smooth", block: "center" });
      firstMissingField.focus({ preventScroll: true });
    });
  }, true);

  document.addEventListener("input", event => {
    const field = event.target;
    const form = field?.form;
    if (!form || !field.matches("input, select, textarea")) return;
    if (field.validity.valid) {
      field.removeAttribute("aria-invalid");
      field.classList.remove("required-field-missing");
    }
    delete form.dataset.requiredInvalidActive;
    const message = form.querySelector(":scope > .required-fields-message");
    if (message && !message.hidden) {
      updateRequiredFieldsMessage(form, missingRequiredFields(form));
    }
  }, true);

  const observer = new MutationObserver(mutations => {
    mutations.forEach(mutation => {
      const element = mutation.target instanceof Element ? mutation.target : mutation.target.parentElement;
      const form = element?.closest("form");
      if (form) enhanceRequiredForm(form);
      mutation.addedNodes.forEach(node => {
        if (!(node instanceof Element)) return;
        if (node.matches("form")) enhanceRequiredForm(node);
        node.querySelectorAll?.("form").forEach(enhanceRequiredForm);
      });
    });
  });
  observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["required"] });
}

// Install shared accessibility behavior before page-specific initialization runs.
function initializeGlobalAccessibility() {
  initializeMobileNavigation();

  const main = document.querySelector("main");

  if (main) {
    if (!main.id) {
      main.id = "mainContent";
    }

    if (!document.querySelector(".skip-to-content")) {
      const skipLink = document.createElement("a");
      skipLink.className = "skip-to-content";
      skipLink.href = `#${main.id}`;
      skipLink.textContent = "Skip to main content";
      document.body.prepend(skipLink);
    }
  }

  const pageName = window.location.pathname.split("/").pop() || "index.html";
  document.querySelectorAll(".main-nav a[href]:not(.nav-brand)").forEach(link => {
    const linkPage = link.getAttribute("href")?.split(/[?#]/)[0];
    if (linkPage === pageName) {
      link.setAttribute("aria-current", "page");
    } else if (link.getAttribute("aria-current") === "page") {
      link.removeAttribute("aria-current");
    }
  });

  document.querySelectorAll('a[target="_blank"]').forEach(link => {
    const relValues = new Set((link.getAttribute("rel") || "").split(/\s+/).filter(Boolean));
    relValues.add("noopener");
    relValues.add("noreferrer");
    link.setAttribute("rel", [...relValues].join(" "));
  });

  document.querySelectorAll("button.close-chat").forEach(button => {
    if (!button.getAttribute("aria-label")) {
      button.setAttribute("aria-label", "Close assistant");
    }
  });

  const connectionBanner = document.createElement("div");
  connectionBanner.className = "connection-status-banner hidden";
  connectionBanner.setAttribute("role", "status");
  connectionBanner.setAttribute("aria-live", "polite");
  document.body.appendChild(connectionBanner);

  const pathForgeBackendIsReachable = async () => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 3500);
    try {
      const response = await fetch(apiUrl("/health/email"), {
        cache: "no-store",
        credentials: "omit",
        signal: controller.signal
      });
      return response.ok;
    } catch (error) {
      return false;
    } finally {
      window.clearTimeout(timeout);
    }
  };

  const updateConnectionStatus = async () => {
    const browserReportsOffline = navigator.onLine === false;
    const backendAvailable = browserReportsOffline
      ? await pathForgeBackendIsReachable()
      : true;
    const connectionUnavailable = browserReportsOffline && !backendAvailable;

    connectionBanner.classList.toggle("hidden", !connectionUnavailable);
    connectionBanner.textContent = connectionUnavailable
      ? "PathForge cannot reach its services right now. Saved information remains unchanged; check your connection and try again."
      : "PathForge is connected.";

    if (!connectionUnavailable) {
      window.setTimeout(() => connectionBanner.classList.add("hidden"), 1200);
    }
  };

  window.addEventListener("offline", updateConnectionStatus);
  window.addEventListener("online", updateConnectionStatus);
  updateConnectionStatus();

  document.addEventListener("keydown", event => {
    if (event.key !== "Tab") {
      return;
    }

    const dialogs = [...document.querySelectorAll('[role="dialog"]')];
    const dialog = dialogs.reverse().find(item =>
      !item.closest(".hidden") && item.getClientRects().length > 0
    );

    if (!dialog) {
      return;
    }

    const focusable = [...dialog.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )].filter(item => item.getClientRects().length > 0);

    if (!focusable.length) {
      return;
    }

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
}

function initializeMobileNavigation() {
  // Build the trigger once in JavaScript so every page receives identical
  // responsive navigation without duplicating markup across the HTML files.
  const navigation = document.querySelector(".main-nav");
  const navigationLinks = navigation?.querySelector(".nav-links");
  if (!navigation || !navigationLinks || navigation.querySelector(".nav-menu-toggle")) return;

  if (!navigationLinks.id) navigationLinks.id = "primaryNavigationLinks";

  const toggle = document.createElement("button");
  toggle.className = "nav-menu-toggle";
  toggle.type = "button";
  toggle.setAttribute("aria-controls", navigationLinks.id);
  toggle.setAttribute("aria-expanded", "false");
  toggle.innerHTML = '<span class="nav-menu-icon" aria-hidden="true"></span><span>Menu</span>';
  navigation.insertBefore(toggle, navigationLinks);

  const setOpen = open => {
    navigation.classList.toggle("nav-open", open);
    toggle.setAttribute("aria-expanded", String(open));
  };

  toggle.addEventListener("click", () => {
    setOpen(!navigation.classList.contains("nav-open"));
  });

  navigationLinks.addEventListener("click", event => {
    if (event.target.closest("a") || event.target.closest(".nav-logout")) setOpen(false);
  });

  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && navigation.classList.contains("nav-open")) {
      setOpen(false);
      toggle.focus();
    }
  });

  const mobileQuery = window.matchMedia("(max-width: 700px)");
  mobileQuery.addEventListener("change", event => {
    if (!event.matches) setOpen(false);
  });
}

function initializePwaSupport() {
  if (!document.querySelector('link[rel="manifest"]')) {
    const manifest = document.createElement("link");
    manifest.rel = "manifest";
    manifest.href = "manifest.webmanifest";
    document.head.appendChild(manifest);
  }
  if (!document.querySelector('meta[name="theme-color"]')) {
    const theme = document.createElement("meta");
    theme.name = "theme-color";
    theme.content = "#172334";
    document.head.appendChild(theme);
  }
  if ("serviceWorker" in navigator && window.location.protocol.startsWith("http")) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("service-worker.js").catch(error => console.error("Offline support could not start:", error));
    });
  }

  // Keep offline browser support, but postpone the install promotion until
  // PathForge is ready to be presented as a standalone application.
  const installPromotionEnabled = false;
  if (!installPromotionEnabled) return;

  const currentPage = window.location.pathname.split("/").pop() || "index.html";
  if (currentPage !== "index.html") return;

  let installPrompt = null;
  const installPanel = document.createElement("aside");
  installPanel.className = "pwa-install-panel hidden";
  installPanel.setAttribute("aria-label", "Install PathForge");
  const installButton = document.createElement("button");
  installButton.className = "pwa-install-button";
  installButton.type = "button";
  installButton.textContent = "Install PathForge";
  installPanel.appendChild(installButton);
  const primaryNavigation = document.querySelector(".main-nav");
  if (primaryNavigation) {
    primaryNavigation.insertAdjacentElement("afterend", installPanel);
  } else {
    document.body.insertAdjacentElement("afterbegin", installPanel);
  }
  window.addEventListener("beforeinstallprompt", event => {
    event.preventDefault();
    installPrompt = event;
    installPanel.classList.remove("hidden");
  });
  installButton.addEventListener("click", async () => {
    if (!installPrompt) return;
    await installPrompt.prompt();
    installPrompt = null;
    installPanel.classList.add("hidden");
  });
  window.addEventListener("appinstalled", () => installPanel.classList.add("hidden"));
}

function formatSecurityDate(value) {
  if (!value) return "Unknown time";
  const parsed = new Date(String(value).replace(" ", "T"));
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

async function loadAccountSessions() {
  const container = document.getElementById("accountSessionsList");
  if (!container) return;
  container.innerHTML = "<p>Loading sessions…</p>";
  try {
    const response = await fetchWithTimeout(apiUrl("/account/sessions"), { credentials: "include" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Sessions could not be loaded.");
    container.innerHTML = data.sessions.map(session => `
      <article class="account-session-item ${session.current ? "current" : ""}">
        <div><strong>${session.current ? "Current session" : "Signed-in browser"}</strong><p>${escapeEmployerHtml(session.device)}</p><small>Last active ${escapeEmployerHtml(formatSecurityDate(session.last_seen_at))}</small></div>
        <button class="${session.current ? "button-secondary" : "session-revoke-button"}" type="button" data-session-id="${session.id}">${session.current ? "Sign out here" : "Revoke"}</button>
      </article>
    `).join("") || "<p>No active sessions were found.</p>";
  } catch (error) {
    container.innerHTML = `<p class="error-message">${escapeEmployerHtml(error.message)}</p>`;
  }
}

async function loadSecurityEvents() {
  const container = document.getElementById("securityEventsList");
  if (!container) return;
  try {
    const response = await fetchWithTimeout(apiUrl("/account/security-events"), { credentials: "include" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Security activity could not be loaded.");
    container.innerHTML = data.events.map(event => `<article><strong>${escapeEmployerHtml(event.event_summary)}</strong><time>${escapeEmployerHtml(formatSecurityDate(event.created_at))}</time></article>`).join("") || "<p>No security activity has been recorded yet.</p>";
  } catch (error) {
    container.innerHTML = `<p class="error-message">${escapeEmployerHtml(error.message)}</p>`;
  }
}

async function loadPrivacySettings() {
  const form = document.getElementById("privacySettingsForm");
  if (!form) return;
  try {
    const response = await fetchWithTimeout(apiUrl("/account/privacy"), { credentials: "include" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Privacy choices could not be loaded.");
    document.getElementById("allowPersonalizedGuidance").checked = data.allow_personalized_guidance;
    document.getElementById("allowEmployerDiscovery").checked = data.allow_employer_discovery;
    document.getElementById("securityNotifications").checked = data.security_notifications;
  } catch (error) {
    const status = document.getElementById("privacySettingsStatus");
    status.textContent = error.message;
    status.classList.add("error-message");
  }
}

function initializeAccountSecurityPage() {
  const passwordForm = document.getElementById("changePasswordForm");
  if (!passwordForm) return;
  loadAccountSessions();
  loadSecurityEvents();
  loadPrivacySettings();

  const verificationControls = document.getElementById("emailVerificationControls");
  const verificationSummary = document.getElementById("emailVerificationSummary");
  const verificationStatus = document.getElementById("emailVerificationStatus");
  const verificationForm = document.getElementById("emailVerificationForm");
  fetchWithTimeout(apiUrl("/me"), { credentials: "include" })
    .then(async response => {
      const user = await response.json();
      if (!response.ok) throw new Error(user.detail || "Verification status could not be loaded.");
      verificationSummary.textContent = user.email_verified
        ? `${user.email} is verified.`
        : `${user.email} has not been verified yet.`;
      verificationControls.classList.toggle("hidden", Boolean(user.email_verified));
    })
    .catch(error => { verificationStatus.textContent = error.message; verificationStatus.classList.add("error-message"); });

  const sensitiveForm = document.getElementById("sensitiveVerificationForm");
  const sensitiveStatus = document.getElementById("sensitiveVerificationStatus");
  const sensitiveButton = document.getElementById("sendSensitiveCodeButton");
  const setSensitiveVerificationReady = ready => {
    passwordForm.classList.toggle("hidden", !ready);
    sensitiveButton.classList.toggle("hidden", ready);
    sensitiveForm.classList.add("hidden");
    if (ready) {
      sensitiveStatus.className = "form-message success-message";
      sensitiveStatus.textContent = "Identity verified. You may change your password for the next 15 minutes.";
    }
  };
  fetchWithTimeout(apiUrl("/account/sensitive-verification/status"), { credentials: "include" })
    .then(response => response.json())
    .then(data => setSensitiveVerificationReady(Boolean(data.verified)))
    .catch(() => setSensitiveVerificationReady(false));

  sensitiveButton.addEventListener("click", async () => {
    sensitiveButton.disabled = true;
    sensitiveStatus.className = "form-message";
    sensitiveStatus.textContent = "Sending a security code…";
    try {
      const response = await fetchWithTimeout(apiUrl("/account/sensitive-verification/request"), { method: "POST", credentials: "include" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "A security code could not be sent.");
      sensitiveStatus.textContent = data.message;
      sensitiveForm.classList.remove("hidden");
      document.getElementById("sensitiveVerificationCode").focus();
    } catch (error) {
      sensitiveStatus.textContent = error.message;
      sensitiveStatus.classList.add("error-message");
    } finally { sensitiveButton.disabled = false; }
  });

  sensitiveForm.addEventListener("submit", async event => {
    event.preventDefault();
    const button = sensitiveForm.querySelector('button[type="submit"]');
    button.disabled = true;
    sensitiveStatus.className = "form-message";
    sensitiveStatus.textContent = "Confirming your identity…";
    try {
      const response = await fetchWithTimeout(apiUrl("/account/sensitive-verification/confirm"), {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: document.getElementById("sensitiveVerificationCode").value })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Your identity could not be verified.");
      sensitiveForm.reset();
      setSensitiveVerificationReady(true);
      document.getElementById("currentPassword").focus();
    } catch (error) {
      sensitiveStatus.textContent = error.message;
      sensitiveStatus.classList.add("error-message");
    } finally { button.disabled = false; }
  });

  document.getElementById("sendVerificationCodeButton").addEventListener("click", async event => {
    const button = event.currentTarget;
    button.disabled = true;
    verificationStatus.className = "form-message";
    verificationStatus.textContent = "Sending a verification code…";
    try {
      const response = await fetchWithTimeout(apiUrl("/account/email-verification/request"), { method: "POST", credentials: "include" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "A verification code could not be sent.");
      verificationStatus.textContent = data.message;
      verificationStatus.classList.add("success-message");
      if (!data.verified) verificationForm.classList.remove("hidden");
    } catch (error) { verificationStatus.textContent = error.message; verificationStatus.classList.add("error-message"); }
    finally { button.disabled = false; }
  });

  verificationForm.addEventListener("submit", async event => {
    event.preventDefault();
    const button = verificationForm.querySelector('button[type="submit"]');
    button.disabled = true;
    verificationStatus.className = "form-message";
    verificationStatus.textContent = "Checking your code…";
    try {
      const response = await fetchWithTimeout(apiUrl("/account/email-verification/confirm"), {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: document.getElementById("emailVerificationCode").value })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "The code could not be verified.");
      verificationStatus.textContent = data.message;
      verificationStatus.classList.add("success-message");
      verificationSummary.textContent = "Your account email is verified.";
      verificationControls.classList.add("hidden");
      await loadSecurityEvents();
    } catch (error) { verificationStatus.textContent = error.message; verificationStatus.classList.add("error-message"); }
    finally { button.disabled = false; }
  });

  passwordForm.addEventListener("submit", async event => {
    event.preventDefault();
    const status = document.getElementById("passwordChangeStatus");
    const button = passwordForm.querySelector('button[type="submit"]');
    button.disabled = true;
    status.className = "form-message";
    status.textContent = "Changing password…";
    try {
      const response = await fetchWithTimeout(apiUrl("/account/change-password"), {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: document.getElementById("currentPassword").value, new_password: document.getElementById("newPassword").value })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Password could not be changed.");
      passwordForm.reset();
      status.textContent = data.message;
      status.classList.add("success-message");
      await Promise.all([loadAccountSessions(), loadSecurityEvents()]);
    } catch (error) {
      status.textContent = error.message;
      status.classList.add("error-message");
      if (error.message.includes("Verify your identity")) {
        setSensitiveVerificationReady(false);
      }
    } finally { button.disabled = false; }
  });

  document.getElementById("privacySettingsForm").addEventListener("submit", async event => {
    event.preventDefault();
    const status = document.getElementById("privacySettingsStatus");
    const button = event.currentTarget.querySelector('button[type="submit"]');
    button.disabled = true;
    status.className = "form-message";
    status.textContent = "Saving privacy choices…";
    try {
      const response = await fetchWithTimeout(apiUrl("/account/privacy"), {
        method: "PUT", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ allow_personalized_guidance: document.getElementById("allowPersonalizedGuidance").checked, allow_employer_discovery: document.getElementById("allowEmployerDiscovery").checked, security_notifications: document.getElementById("securityNotifications").checked })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Privacy choices could not be saved.");
      status.textContent = data.message;
      status.classList.add("success-message");
      await loadJobAlertCount();
    } catch (error) { status.textContent = error.message; status.classList.add("error-message"); }
    finally { button.disabled = false; }
  });

  document.getElementById("accountSessionsList").addEventListener("click", async event => {
    const button = event.target.closest("[data-session-id]");
    if (!button || !window.confirm("Revoke this signed-in session?")) return;
    button.disabled = true;
    const response = await fetch(apiUrl(`/account/sessions/${button.dataset.sessionId}`), { method: "DELETE", credentials: "include" });
    if (response.ok) {
      const wasCurrent = button.textContent.includes("Sign out");
      if (wasCurrent) window.location.href = "login.html";
      else await Promise.all([loadAccountSessions(), loadSecurityEvents()]);
    } else button.disabled = false;
  });
  document.getElementById("refreshSessionsButton").addEventListener("click", loadAccountSessions);
  document.getElementById("downloadAccountDataButton").addEventListener("click", async () => {
    const status = document.getElementById("dataDownloadStatus");
    status.textContent = "Preparing your download…";
    try {
      const response = await fetchWithTimeout(apiUrl("/account/data-download"), { credentials: "include" }, 30000);
      if (!response.ok) throw new Error("Your account data could not be prepared.");
      const blob = await response.blob();
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob); link.download = "pathforge-account-data.json"; link.click();
      window.setTimeout(() => URL.revokeObjectURL(link.href), 1000);
      status.textContent = "Your account-data download is ready."; status.classList.add("success-message");
    } catch (error) { status.textContent = error.message; status.classList.add("error-message"); }
  });
}

function initializePasswordReset() {
  const requestForm = document.getElementById("passwordResetRequestForm");
  const confirmForm = document.getElementById("passwordResetConfirmForm");
  const status = document.getElementById("passwordResetStatus");
  if (!requestForm || !confirmForm || !status) return;

  requestForm.addEventListener("submit", async event => {
    event.preventDefault();
    const button = requestForm.querySelector('button[type="submit"]');
    button.disabled = true;
    status.className = "auth-message";
    status.textContent = "Requesting a reset code…";
    try {
      const response = await fetchWithTimeout(apiUrl("/password-reset/request"), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: document.getElementById("passwordResetEmail").value })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "A reset code could not be requested.");
      status.textContent = data.message;
      status.classList.add("success-message");
      confirmForm.classList.remove("hidden");
    } catch (error) { status.textContent = error.message; status.classList.add("error-message"); }
    finally { button.disabled = false; }
  });

  confirmForm.addEventListener("submit", async event => {
    event.preventDefault();
    const button = confirmForm.querySelector('button[type="submit"]');
    button.disabled = true;
    status.className = "auth-message";
    status.textContent = "Resetting your password…";
    try {
      const response = await fetchWithTimeout(apiUrl("/password-reset/confirm"), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: document.getElementById("passwordResetEmail").value, code: document.getElementById("passwordResetCode").value, new_password: document.getElementById("passwordResetNewPassword").value })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Your password could not be reset.");
      status.textContent = data.message;
      status.classList.add("success-message");
      confirmForm.reset();
      confirmForm.classList.add("hidden");
      document.getElementById("loginIdentifier").value = document.getElementById("passwordResetEmail").value;
    } catch (error) { status.textContent = error.message; status.classList.add("error-message"); }
    finally { button.disabled = false; }
  });
}

let activeConversationId = null;

async function loadConversationList(selectId = null) {
  const list = document.getElementById("conversationList");
  if (!list) return;
  try {
    const response = await fetchWithTimeout(apiUrl("/messages/conversations"), { credentials: "include" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Conversations could not be loaded.");
    list.innerHTML = data.conversations.map(item => `
      <button class="conversation-preview ${Number(item.id) === Number(activeConversationId) ? "active" : ""}" type="button" data-conversation-id="${item.id}">
        <span><strong>${escapeEmployerHtml(item.other_party)}</strong><b>${Number(item.unread_count) ? escapeEmployerHtml(String(item.unread_count)) : ""}</b></span>
        <em>${escapeEmployerHtml(item.title)} · ${escapeEmployerHtml(item.company)}</em>
        <small>${escapeEmployerHtml(item.last_message || "Conversation ready")}</small>
      </button>
    `).join("") || `<div class="message-empty-state"><h3>No conversations yet</h3><p>Start one from a qualifying PathForge application.</p></div>`;
    const target = selectId || Number(new URLSearchParams(window.location.search).get("conversation"));
    if (target && data.conversations.some(item => Number(item.id) === Number(target))) await openMessageConversation(target);
  } catch (error) { list.innerHTML = `<p class="error-message">${escapeEmployerHtml(error.message)}</p>`; }
}

async function openMessageConversation(conversationId) {
  const thread = document.getElementById("messageThread");
  activeConversationId = Number(conversationId);
  thread.setAttribute("aria-busy", "true");
  try {
    const response = await fetchWithTimeout(apiUrl(`/messages/conversations/${conversationId}`), { credentials: "include" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Conversation could not be loaded.");
    const blocked = Boolean(data.applicant_blocked || data.employer_blocked);
    const blockedByMe = data.current_user_id === data.applicant_id ? Boolean(data.applicant_blocked) : Boolean(data.employer_blocked);
    thread.innerHTML = `
      <header class="message-thread-heading"><div><p>${escapeEmployerHtml(data.company)}</p><h2 id="messageThreadTitle">${escapeEmployerHtml(data.title)}</h2><span>Conversation with ${escapeEmployerHtml(data.current_user_id === data.applicant_id ? data.employer_username : data.applicant_username)}</span></div><button id="toggleConversationBlock" class="button-secondary" type="button" data-blocked="${blockedByMe}">${blockedByMe ? "Unblock" : "Block"}</button></header>
      <div class="message-safety-note"><strong>Keep it safe:</strong> Never send passwords, government ID numbers, banking details, card numbers, or money.</div>
      <div id="messageThreadList" class="message-thread-list" aria-live="polite">
        ${data.messages.map(message => `<article class="direct-message ${message.sender_id === data.current_user_id ? "mine" : "theirs"}"><div><strong>${escapeEmployerHtml(message.sender_username)}</strong><time>${escapeEmployerHtml(formatSecurityDate(message.created_at))}</time></div><p>${escapeEmployerHtml(message.body)}</p>${message.sender_id === data.current_user_id ? "" : `<button class="message-report-button" type="button" data-message-id="${message.id}">Report</button>`}</article>`).join("") || `<div class="message-empty-state"><p>No messages yet. Start with a question about this application.</p></div>`}
      </div>
      <form id="messageComposer" class="message-composer">
        <label for="messageComposerBody">Message</label><textarea id="messageComposerBody" maxlength="2000" rows="4" placeholder="Write a job-related message…" ${blocked ? "disabled" : ""} required></textarea>
        <div><small>1–2,000 characters. Sensitive financial or identity information is blocked.</small><button type="submit" ${blocked ? "disabled" : ""}>Send message</button></div>
        <p id="messageComposerStatus" class="form-message" role="status" aria-live="polite">${blocked ? "This conversation is blocked." : ""}</p>
      </form>`;
    const messageList = document.getElementById("messageThreadList");
    messageList.scrollTop = messageList.scrollHeight;
    document.querySelectorAll(".conversation-preview").forEach(button => button.classList.toggle("active", Number(button.dataset.conversationId) === activeConversationId));
  } catch (error) { thread.innerHTML = `<p class="error-message">${escapeEmployerHtml(error.message)}</p>`; }
  finally { thread.removeAttribute("aria-busy"); }
}

async function loadEligibleConversations() {
  const list = document.getElementById("eligibleConversationList");
  const response = await fetchWithTimeout(apiUrl("/messages/eligible"), { credentials: "include" });
  const data = await response.json();
  if (!response.ok) { list.innerHTML = `<p class="error-message">${escapeEmployerHtml(data.detail || "Applications could not be loaded.")}</p>`; return; }
  list.innerHTML = data.applications.map(item => `<article><div><strong>${escapeEmployerHtml(item.title)}</strong><span>${escapeEmployerHtml(item.company)} · ${escapeEmployerHtml(item.other_party)}</span></div><button type="button" data-application-id="${item.application_id}" ${item.conversation_id ? `data-existing-conversation="${item.conversation_id}"` : ""}>${item.conversation_id ? "Open" : "Start"}</button></article>`).join("") || `<p>No qualifying PathForge applications are available.</p>`;
}

function initializeMessagesPage() {
  const page = document.querySelector(".messages-page");
  if (!page) return;
  loadConversationList();
  const dialog = document.getElementById("newConversationDialog");
  document.getElementById("newConversationButton").addEventListener("click", () => { dialog.classList.remove("hidden"); loadEligibleConversations(); document.getElementById("closeNewConversationDialog").focus(); });
  document.getElementById("closeNewConversationDialog").addEventListener("click", () => dialog.classList.add("hidden"));
  document.getElementById("conversationList").addEventListener("click", event => { const button = event.target.closest("[data-conversation-id]"); if (button) openMessageConversation(button.dataset.conversationId); });
  document.getElementById("eligibleConversationList").addEventListener("click", async event => {
    const button = event.target.closest("[data-application-id]"); if (!button) return;
    let conversationId = button.dataset.existingConversation;
    if (!conversationId) {
      const response = await fetchWithTimeout(apiUrl("/messages/conversations"), { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ application_id: Number(button.dataset.applicationId) }) });
      const data = await response.json(); if (!response.ok) return;
      conversationId = data.conversation_id;
    }
    dialog.classList.add("hidden"); await loadConversationList(conversationId);
  });
  document.getElementById("messageThread").addEventListener("submit", async event => {
    if (event.target.id !== "messageComposer") return; event.preventDefault();
    const body = document.getElementById("messageComposerBody").value.trim(); const status = document.getElementById("messageComposerStatus"); const button = event.target.querySelector('button[type="submit"]');
    button.disabled = true; status.className = "form-message"; status.textContent = "Sending…";
    try { const response = await fetchWithTimeout(apiUrl(`/messages/conversations/${activeConversationId}`), { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ body }) }); const data = await response.json(); if (!response.ok) throw new Error(data.detail || "Message could not be sent."); await openMessageConversation(activeConversationId); await loadConversationList(); }
    catch (error) { status.textContent = error.message; status.classList.add("error-message"); button.disabled = false; }
  });
  document.getElementById("messageThread").addEventListener("click", async event => {
    const blockButton = event.target.closest("#toggleConversationBlock");
    if (blockButton) { const blocked = blockButton.dataset.blocked === "true"; await fetch(apiUrl(`/messages/conversations/${activeConversationId}/block`), { method: "PUT", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ blocked: !blocked }) }); await openMessageConversation(activeConversationId); return; }
    const reportButton = event.target.closest("[data-message-id]");
    if (reportButton) { const reason = window.prompt("Briefly explain why this message should be reviewed."); if (!reason) return; const response = await fetch(apiUrl(`/messages/${reportButton.dataset.messageId}/report`), { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason }) }); const status = document.getElementById("messagesPageStatus"); status.textContent = response.ok ? "Message reported for review." : "The message could not be reported."; status.className = `form-message ${response.ok ? "success-message" : "error-message"}`; }
  });
}

function renderAnalyticsBars(container, rows) {
  const maximum = Math.max(1, ...rows.map(row => Number(row.count) || 0));
  container.innerHTML = rows.map(row => `<div class="analytics-bar-row"><div><strong>${escapeEmployerHtml(row.label || row.period || "Unspecified")}</strong><span>${Number(row.count) || 0}</span></div><div class="analytics-bar-track" aria-hidden="true"><span style="width:${Math.max(4, ((Number(row.count) || 0) / maximum) * 100)}%"></span></div></div>`).join("") || `<p class="analytics-empty">No activity has been recorded for this view yet.</p>`;
}

async function initializeAnalyticsPage() {
  const summary = document.getElementById("analyticsSummary");
  if (!summary) return;
  const status = document.getElementById("analyticsStatus");
  try {
    const response = await fetchWithTimeout(apiUrl("/analytics"), { credentials: "include" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Analytics could not be loaded.");
    const employer = data.role === "employer";
    document.getElementById("analyticsTitle").textContent = employer ? "Hiring activity" : "Your application activity";
    document.getElementById("analyticsIntroduction").textContent = employer ? "Review factual activity across jobs and applicants recorded in PathForge." : "Review the work you have recorded and identify follow-ups that need attention.";
    const cards = employer
      ? [["Active jobs", data.summary.active_jobs], ["Total applicants", data.summary.total_applications], ["Last 30 days", data.summary.applications_last_30_days], ["Interviews", data.summary.interviews_scheduled], ["Average first update", data.average_first_update_days == null ? "Not enough data" : `${data.average_first_update_days} days`]]
      : [["Tracked applications", data.summary.total_applications], ["Last 30 days", data.summary.applications_last_30_days], ["Interviews", data.summary.interviews_scheduled], ["Overdue follow-ups", data.summary.overdue_follow_ups], ["Upcoming follow-ups", data.summary.upcoming_follow_ups], ["Completed follow-ups", data.summary.completed_follow_ups], ["Saved jobs", data.summary.saved_jobs]];
    summary.innerHTML = cards.map(([label, value]) => `<article><span>${escapeEmployerHtml(String(label))}</span><strong>${escapeEmployerHtml(String(value ?? 0))}</strong></article>`).join("");
    renderAnalyticsBars(document.getElementById("analyticsStatusChart"), data.status_counts || []);
    renderAnalyticsBars(document.getElementById("analyticsActivityChart"), (data.weekly_activity || []).map(row => ({ ...row, label: `Week ${row.period}` })));
    document.getElementById("analyticsExplanation").textContent = data.explanation;
    status.textContent = "Analytics updated from current PathForge records.";
  } catch (error) { status.textContent = error.message; status.classList.add("error-message"); }
}

initializeGlobalAccessibility();
initializeRequiredFieldGuidance();
initializePwaSupport();
initializeAccountSecurityPage();
initializePasswordReset();
initializeMessagesPage();
initializeAnalyticsPage();
checkLoginStatus();
protectPage();
protectEmployerPage();
setupEmployerDashboard();
initializeAdminModerationPage();
initializeCompanyResearchPage();
loadCareerStagePersonalization();
loadDashboard();
loadProfile();
setupProfileForm();
loadSavedJobs();
loadApplications();
loadJobAlerts();
setupApplicationDialog();
initializeSkillsBank();
setupLearningAssistant();

const markAllAlertsReadButton =
  document.getElementById("markAllAlertsReadButton");

if (markAllAlertsReadButton) {
  markAllAlertsReadButton.addEventListener(
    "click",
    markAllJobAlertsRead
  );
}

document.getElementById("notificationCategoryFilter")?.addEventListener(
  "change",
  loadJobAlerts
);

const RESUME_MAX_FILE_SIZE = 1024 * 1024;

function getResumeWords(text) {
  return (text.toLowerCase().match(/[a-z][a-z0-9+#.-]{2,}/g) || [])
    .map((word) => word.replace(/[.-]+$/g, ""))
    .filter(Boolean);
}

function getResumeKeywords(text) {
  const ignoredWords = new Set([
    "and", "the", "with", "for", "that", "this", "from", "you",
    "your", "our", "are", "will", "have", "has", "job", "role",
    "work", "who", "but", "not", "all", "their", "they", "about",
    "into", "using", "years", "preferred", "required", "including"
  ]);
  const counts = new Map();

  getResumeWords(text).forEach((word) => {
    if (!ignoredWords.has(word) && word.length > 3) {
      counts.set(word, (counts.get(word) || 0) + 1);
    }
  });

  return [...counts.entries()]
    .sort((first, second) => second[1] - first[1])
    .slice(0, 12)
    .map(([word]) => word);
}

function getTailoringTerms(text) {
  const ignored = new Set([
    "and", "the", "with", "for", "that", "this", "from", "your",
    "you", "our", "are", "will", "have", "has", "job", "role",
    "work", "years", "required", "preferred", "including", "ability"
  ]);
  return [...new Set(getResumeWords(text).filter(word =>
    word.length > 3 && !ignored.has(word)
  ))];
}

function buildJobTailoringEvidence(resumeText, targetText) {
  if (!targetText.trim()) return null;
  const resumeLines = resumeText.split(/\r?\n/).map(line => line.trim())
    .filter(line => getResumeWords(line).length >= 4);
  const statements = targetText.split(/\r?\n|(?<=[.!?;])\s+/)
    .map(statement => statement.replace(/^[•\-*\s]+/, "")
      .replace(/^we(?:'|’)re excited about you because[^a-z0-9]*/i, "").trim())
    .filter(statement => getResumeWords(statement).length >= 5)
    .filter(statement => !/see (?:the )?official posting|complete qualifications|was born in|million hosts|base salary|compensation for this role|talk to your recruiter|employee work location/i.test(statement))
    .slice(0, 30);
  const supported = [];
  const missing = [];
  statements.forEach(statement => {
    const terms = getTailoringTerms(statement);
    if (terms.length < 2) return;
    let bestLine = "";
    let bestMatches = [];
    resumeLines.forEach(line => {
      const normalized = line.toLowerCase();
      const matches = terms.filter(term => normalized.includes(term));
      if (matches.length > bestMatches.length) {
        bestMatches = matches;
        bestLine = line;
      }
    });
    const threshold = Math.min(3, Math.max(2, Math.ceil(terms.length * 0.35)));
    const item = {
      requirement: statement.slice(0, 240),
      matchedTerms: bestMatches.slice(0, 6),
      evidence: bestLine.slice(0, 240)
    };
    if (bestMatches.length >= threshold) supported.push(item);
    else missing.push(item);
  });
  return {
    analyzedCount: statements.length,
    supported: supported.slice(0, 6),
    missing: missing.slice(0, 6),
    prompts: missing.slice(0, 4).map(item => {
      const topic = getTailoringTerms(item.requirement).slice(0, 3).join(", ");
      return `If you genuinely have experience related to ${topic || "this requirement"}, identify where you used it, what you did, and the truthful result. Otherwise, do not claim it.`;
    })
  };
}

function prepareResumeTextForReview(value) {
  const seen = new Map();
  return String(value || "")
    .replace(/\r\n?/g, "\n")
    .replace(/[•▪◦]/g, "•")
    .split("\n")
    .map(line => line.replace(/[ \t]+/g, " ").trim())
    .filter(line => {
      if (!line || /^page\s+\d+(?:\s+of\s+\d+)?$/i.test(line)) return false;
      const key = line.toLowerCase();
      const count = (seen.get(key) || 0) + 1;
      seen.set(key, count);
      return count <= 2;
    })
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function buildResumeReviewLegacy(resumeText, targetText, tailoringText = targetText) {
  const normalizedResume = resumeText.toLowerCase();
  const wordCount = getResumeWords(resumeText).length;
  const lines = resumeText
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const sectionPatterns = {
    "Experience section": /\b(experience|employment|work history)\b/i,
    "Skills section": /\b(skills|competencies|technical skills)\b/i,
    "Education section": /\b(education|degree|certificate|certification)\b/i
  };
  const strongVerbs = [
    "achieved", "analyzed", "built", "coordinated", "created", "delivered",
    "designed", "developed", "implemented", "improved", "increased",
    "launched", "led", "managed", "organized", "reduced", "resolved",
    "streamlined", "supported", "trained"
  ];
  const actionVerbPattern = new RegExp(
    "^(?:" + strongVerbs.join("|") + ")\\b",
    "i"
  );
  const bulletLines = lines
    .filter((line) => /^[•\-*▪◦]/.test(line))
    .map((line) => line.replace(/^[•\-*▪◦]\s*/, ""));
  const actionLedBullets = bulletLines.filter((line) =>
    actionVerbPattern.test(line)
  ).length;
  const detectedVerbCount = strongVerbs.filter((verb) =>
    new RegExp("\\b" + verb + "\\b", "i").test(resumeText)
  ).length;
  const hasEmail = /[\w.+-]+@[\w.-]+\.[a-z]{2,}/i.test(resumeText);
  const hasPhone = /(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]\d{3}[-.\s]\d{4}/.test(resumeText);
  const hasDates = /\b(?:19|20)\d{2}\b|\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(?:19|20)?\d{2}\b/i.test(resumeText);
  const hasFirstPersonPronouns = /\b(?:i|me|my|mine|we|our|ours)\b/i.test(resumeText);
  const hasWeakPhrases = /\b(?:responsible for|duties included|helped with|worked on)\b/i.test(resumeText);
  const hasMetrics = /(?:\d+%|\$\s?\d+|\b\d+\+?\s+(?:people|clients|projects|hours|days|weeks|months|users|customers|employees|tickets|sales)\b)/i
    .test(resumeText);
  const longLines = lines.filter((line) => getResumeWords(line).length > 35);
  const checks = [];
  let score = 0;

  const unusualCharacterCount = (resumeText.match(/[�□]/g) || []).length;
  const readableExtraction = unusualCharacterCount <= Math.max(2, wordCount * 0.01) && lines.length >= 4;
  checks.push({
    title: "Readable resume text",
    passed: readableExtraction,
    message: readableExtraction
      ? "The file produced readable text for this review."
      : "Some text may not have been read correctly. Check the pasted text or try a DOCX or text-based PDF."
  });

  const hasCoreContactDetails = hasEmail && hasPhone;
  score += hasCoreContactDetails ? 10 : 0;
  checks.push({
    title: "Contact details",
    passed: hasCoreContactDetails,
    message: hasCoreContactDetails
      ? "A professional email address and phone number appear to be present."
      : "Place both a professional email address and phone number near the top."
  });

  Object.entries(sectionPatterns).forEach(([title, pattern]) => {
    const passed = pattern.test(resumeText);
    if (passed) {
      score += 7;
    }
    checks.push({
      title,
      passed,
      message: passed
        ? "This information appears to be present."
        : "Consider adding a clearly labeled " + title.toLowerCase() + "."
    });
  });

  const usefulLength = wordCount >= 180 && wordCount <= 900;
  score += usefulLength ? 10 : 0;
  checks.push({
    title: "Focused length",
    passed: usefulLength,
    message: usefulLength
      ? wordCount + " words provides enough detail while remaining scannable."
      : wordCount < 180
        ? wordCount + " words may be too brief to show relevant evidence."
        : wordCount + " words may benefit from tighter editing."
  });

  const usesActionLanguage = bulletLines.length >= 2
    ? actionLedBullets / bulletLines.length >= 0.5
    : detectedVerbCount >= 3;
  score += usesActionLanguage ? 15 : 0;
  checks.push({
    title: "Action-oriented language",
    passed: usesActionLanguage,
    message: usesActionLanguage
      ? "Experience statements frequently begin with specific action verbs."
      : "Begin more bullets with precise action verbs that show what you did."
  });

  score += hasMetrics ? 15 : 0;
  checks.push({
    title: "Measurable results",
    passed: hasMetrics,
    message: hasMetrics
      ? "At least one result includes a number, amount, or percentage."
      : "Add honest numbers where possible, such as volume, time saved, or outcomes."
  });

  const scannable = longLines.length <= 2;
  score += scannable ? 10 : 0;
  checks.push({
    title: "Scannable statements",
    passed: scannable,
    message: scannable
      ? "Most lines are concise enough to scan quickly."
      : "Break long paragraphs into shorter, outcome-focused statements."
  });

  score += !hasFirstPersonPronouns ? 7 : 0;
  checks.push({
    title: "Concise resume voice",
    passed: !hasFirstPersonPronouns,
    message: hasFirstPersonPronouns
      ? "Remove first-person pronouns such as I, me, my, we, and our from resume bullets."
      : "The resume avoids unnecessary first-person pronouns."
  });

  score += !hasWeakPhrases ? 6 : 0;
  checks.push({
    title: "Specific contribution language",
    passed: !hasWeakPhrases,
    message: hasWeakPhrases
      ? "Replace phrases such as responsible for or worked on with specific actions and outcomes."
      : "The review did not detect common duty-only phrases."
  });

  score += hasDates ? 6 : 0;
  checks.push({
    title: "Experience and education dates",
    passed: hasDates,
    message: hasDates
      ? "Dates appear to give employers useful chronology. Check that their formatting is consistent."
      : "Add clear, consistently formatted dates to applicable experience and education entries."
  });

  const targetKeywords = targetText ? getResumeKeywords(targetText) : [];
  const missingKeywords = targetKeywords.filter((keyword) =>
    !normalizedResume.includes(keyword)
  );
  const matchedKeywords = targetKeywords.length - missingKeywords.length;
  let alignment = null;

  if (targetKeywords.length) {
    alignment = Math.round((matchedKeywords / targetKeywords.length) * 100);
  }

  const strengths = [];

  if (hasCoreContactDetails) {
    strengths.push(
      "The resume provides both an email address and phone number, making follow-up straightforward."
    );
  }

  const presentCoreSections = Object.entries(sectionPatterns)
    .filter(([, pattern]) => pattern.test(resumeText))
    .map(([title]) => title.replace(" section", ""));

  if (presentCoreSections.length >= 2) {
    strengths.push(
      "The overall structure includes recognizable " +
      presentCoreSections.join(", ") +
      " sections, helping readers locate important information."
    );
  }

  if (bulletLines.length >= 3) {
    strengths.push(
      "The resume uses " + bulletLines.length +
      " detected bullet points, supporting a scannable presentation."
    );
  }

  if (usesActionLanguage) {
    strengths.push(
      bulletLines.length
        ? actionLedBullets + " of " + bulletLines.length +
          " detected bullets begin with action-oriented language."
        : "The resume uses several action verbs to communicate contributions."
    );
  }

  if (hasMetrics) {
    strengths.push(
      "The resume includes measurable evidence that helps show scope or results."
    );
  }

  if (alignment !== null && alignment >= 60) {
    strengths.push(
      "The resume reflects many of the recurring terms in the supplied target description."
    );
  }

  if (!strengths.length) {
    strengths.push(
      "The resume provides a foundation that can be strengthened through clearer structure and more specific evidence."
    );
  }

  return {
    score: Math.min(100, score),
    wordCount,
    checks,
    strengths,
    alignment,
    missingKeywords: missingKeywords.slice(0, 8),
    tailoring: buildJobTailoringEvidence(resumeText, tailoringText)
  };
}

function getResumeSectionText(resumeText, headingPattern) {
  const lines = String(resumeText || "").split(/\r?\n/);
  const sectionHeading = new RegExp(`^(?:${headingPattern})\s*:?$`, "i");
  const anyHeading = /^(?:objective|summary|professional profile|experience|employment|work history|skills|technical skills|education|projects|activities|volunteer(?: experience)?|certifications?|awards?)\s*:?$/i;
  const start = lines.findIndex(line => sectionHeading.test(line.trim()));
  if (start < 0) return "";
  const collected = [];
  for (let index = start + 1; index < lines.length; index += 1) {
    if (anyHeading.test(lines[index].trim())) break;
    collected.push(lines[index]);
  }
  return collected.join("\n").trim();
}

function getResumeCareerStage(resumeText) {
  const normalized = resumeText.toLowerCase();
  if (/\b(?:high school|student|gpa|expected graduation|first job)\b/.test(normalized)) return "entry-level / high school";
  if (/\b(?:chief|c-suite|vice president|vp|executive director)\b/.test(normalized)) return "executive";
  return "mid-level";
}

function getResumeTimelineAudit(resumeText) {
  const monthNames = {jan:1,feb:2,mar:3,apr:4,may:5,jun:6,jul:7,aug:8,sep:9,oct:10,nov:11,dec:12};
  const token = "(?:(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\\s+)?(?:19|20)\\d{2}";
  const rangePattern = new RegExp(`(${token})\\s*(?:-|–|—|to)\\s*(${token}|present|current|now)`, "i");
  const parseDate = (value, isEnd = false) => {
    if (/^(?:present|current|now)$/i.test(value)) return (new Date().getFullYear() * 12) + new Date().getMonth() + 1;
    const year = Number(value.match(/(?:19|20)\d{2}/)?.[0]);
    const monthWord = value.match(/^[A-Za-z]+/)?.[0]?.slice(0, 3).toLowerCase();
    return (year * 12) + (monthWord ? monthNames[monthWord] : isEnd ? 12 : 1);
  };
  const ranges = String(resumeText || "").split(/\r?\n/).map(line => {
    const match = line.match(rangePattern);
    return match ? { start: parseDate(match[1]), end: parseDate(match[2], true), line: line.trim() } : null;
  }).filter(Boolean);
  const valid = ranges.filter(item => item.end >= item.start).sort((a, b) => a.start - b.start);
  const flags = ranges.filter(item => item.end < item.start).map(item => `The date range appears reversed: ${item.line}`);
  valid.slice(1).forEach((current, index) => {
    const previous = valid[index];
    const gap = current.start - previous.end - 1;
    const overlap = previous.end - current.start + 1;
    if (gap > 6) flags.push(`A gap of about ${gap} months appears between dated entries. It may be valid, but explain it when helpful.`);
    if (overlap > 6 && !/part[- ]time/i.test(previous.line + current.line)) flags.push(`Two entries overlap by about ${overlap} months. Clarify concurrent or part-time work if applicable.`);
  });
  const merged = [];
  valid.forEach(item => {
    const last = merged[merged.length - 1];
    if (!last || item.start > last.end + 1) merged.push({ start: item.start, end: item.end });
    else last.end = Math.max(last.end, item.end);
  });
  const documentedMonths = merged.reduce((total, item) => total + item.end - item.start + 1, 0);
  const claim = resumeText.match(/\b(\d{1,2})\+?\s+years?(?:\s+of)?(?:\s+[a-z][a-z-]*){0,4}\s+experience\b/i);
  if (claim && documentedMonths && Number(claim[1]) * 12 > documentedMonths + 1) {
    flags.push(`The summary claims ${claim[1]}+ year${Number(claim[1]) === 1 ? "" : "s"} of experience, but the detected work dates total about ${documentedMonths} months. Correct the claim or add any missing dated experience.`);
  }
  return { ranges, documentedMonths, flags };
}

function buildResumeBulletRewrite(bullet, resumeText) {
  const original = bullet || "Provided friendly customer service during peak hours.";
  const foodService = /\b(?:wendy|restaurant|food|cashier|crew member|drive[- ]?thru)\b/i.test(resumeText);
  if (foodService && /customer service|customers|orders|peak/i.test(original)) {
    return `Operated [POS or order system, if accurate] and served [truthful number] customers per hour during peak periods while maintaining [truthful accuracy or service result].`;
  }
  const cleaned = original.replace(/^(?:responsible for|duties included|helped with|worked on|provided)\s*/i, "").replace(/\.$/, "");
  return `[Specific action verb] ${cleaned} using [tool or method], resulting in [truthful outcome, volume, or improvement].`;
}

// Deprecated compatibility implementation. Resume scoring now runs only in main.py.
// This function is intentionally not called and can be removed after one release cycle.
function buildResumeReviewDeprecated(resumeText, jobDescription = "", tailoringText = jobDescription) {
  const lines = resumeText.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  const bullets = lines.filter(line => /^[•\-*▪◦]/.test(line)).map(line => line.replace(/^[•\-*▪◦]\s*/, ""));
  const experienceText = getResumeSectionText(resumeText, "experience|employment|work history");
  const skillsText = getResumeSectionText(resumeText, "skills|technical skills");
  const actionPattern = /^(?:achieved|analyzed|assisted|built|coordinated|created|delivered|designed|developed|implemented|improved|increased|led|managed|operated|organized|prepared|processed|reduced|resolved|served|streamlined|supported|trained)\b/i;
  const weakPattern = /\b(?:responsible for|duties included|helped with|worked on|provided friendly customer service)\b/i;
  const metricPattern = /(?:\d+%|\$\s?[\d,.]+|\b\d+\+?\s+(?:customers|orders|transactions|projects|tickets|users|hours)\b)/i;
  const hardSkillPattern = /\b(?:cash handling|pos|point of sale|inventory|food safety|order taking|drive[- ]?thru|microsoft (?:word|excel|office)|google (?:docs|sheets|workspace)|python|javascript|sql|bilingual|cpr|bls|forklift|crm|salesforce)\b/gi;
  const softSkillPattern = /\b(?:dependable|reliable|hard[- ]working|team player|communication|organized|friendly|motivated|punctual)\b/gi;
  const hardSkills = [...new Set((skillsText.match(hardSkillPattern) || []).map(value => value.toLowerCase()))];
  const softSkills = [...new Set((skillsText.match(softSkillPattern) || []).map(value => value.toLowerCase()))];
  const experienceBullets = bullets.filter(bullet => experienceText.includes(bullet));
  const reviewedBullets = experienceBullets.length ? experienceBullets : bullets;
  const actionCount = reviewedBullets.filter(bullet => actionPattern.test(bullet)).length;
  const metricCount = reviewedBullets.filter(bullet => metricPattern.test(bullet)).length;
  const weakBullets = reviewedBullets.filter(bullet => weakPattern.test(bullet) || !actionPattern.test(bullet));
  const timeline = getResumeTimelineAudit(resumeText);
  const wordCount = getResumeWords(resumeText).length;
  const careerStage = getResumeCareerStage(resumeText);
  const expectedRange = careerStage === "entry-level / high school" ? [100, 250] : careerStage === "executive" ? [500, 900] : [300, 500];
  const mode = jobDescription.trim().split(/\s+/).filter(Boolean).length >= 20 ? "JOB_REVIEW" : "GENERAL";
  const checks = [];
  const addCheck = (title, passed, message, rewrites = []) => checks.push({ title, passed, message, rewrites });
  const readable = lines.length >= 4 && (resumeText.match(/[ï¿½□]/g) || []).length <= 2;
  addCheck("Readable resume text", readable, readable ? "The extracted text is readable enough for a content review." : "Some text may not have been extracted correctly. Verify the document or paste clean text.");
  const hasContact = /[\w.+-]+@[\w.-]+\.[a-z]{2,}/i.test(resumeText) && /(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]\d{3}[-.\s]\d{4}/.test(resumeText);
  addCheck("Contact details", hasContact, hasContact ? "A professional email address and phone number are identifiable." : "Add both a professional email address and phone number near the top.");

  const experiencePassed = reviewedBullets.length >= 2 && actionCount >= Math.ceil(reviewedBullets.length / 2) && (metricCount > 0 || reviewedBullets.some(item => /\b(?:pos|cash|inventory|orders|customers|tool|system|project)\b/i.test(item)));
  addCheck("Experience evidence", experiencePassed,
    reviewedBullets.length
      ? `${reviewedBullets.length} experience bullet${reviewedBullets.length === 1 ? " was" : "s were"} detected; ${actionCount} begin with a specific action and ${metricCount} include measurable scale. ${experiencePassed ? "The section contains useful evidence, though every claim should remain truthful." : "Strengthen duty-only bullets by naming the action, tool or setting, and an honest result or workload."}`
      : "An Experience heading alone is not enough. Add concise bullets describing actions, tools or setting, and truthful results.",
    weakBullets.slice(0, 3).map(before => ({ before, after: buildResumeBulletRewrite(before, resumeText) }))
  );

  const skillsPassed = hardSkills.length >= 2;
  const roleSkillSuggestions = /\b(?:wendy|restaurant|food|cashier|crew member)\b/i.test(resumeText)
    ? ["POS operation", "cash handling", "order accuracy", "food safety", "inventory/restocking"]
    : [];
  addCheck("Skills evidence", skillsPassed,
    skillsText
      ? `${hardSkills.length ? "Concrete skills detected: " + hardSkills.join(", ") + ". " : "No clearly concrete tools or role-specific skills were detected. "}${softSkills.length ? "Generic strengths such as " + softSkills.join(", ") + " need supporting examples. " : ""}${!skillsPassed && roleSkillSuggestions.length ? "If accurate, consider adding: " + roleSkillSuggestions.join(", ") + "." : ""}`
      : "Add a Skills section containing verified tools, systems, certifications, languages, or role-specific abilities—not only personality traits."
  );

  const timelinePassed = timeline.ranges.length > 0 && timeline.flags.length === 0;
  addCheck("Claims and timeline", timelinePassed,
    timeline.flags.length ? timeline.flags.join(" ") : timeline.ranges.length ? `The dated entries provide about ${timeline.documentedMonths} months of documented chronology, and no numeric summary contradiction was detected.` : "No complete employment date range was detected, so experience-duration claims could not be verified."
  );

  const densityAcceptable = wordCount >= expectedRange[0] && wordCount <= expectedRange[1];
  const shortButUseful = wordCount >= 100 && careerStage === "entry-level / high school";
  addCheck("Relevant length and density", densityAcceptable || shortButUseful,
    `${wordCount} words is evaluated as ${careerStage}. ${expectedRange[0]}–${expectedRange[1]} words is a useful reference range, but relevance and evidence density matter more than filling space.${wordCount < expectedRange[0] && careerStage !== "entry-level / high school" ? " Add only missing evidence—never filler." : ""}`
  );

  const targetKeywords = mode === "JOB_REVIEW" ? getResumeKeywords(jobDescription) : [];
  const normalizedResume = resumeText.toLowerCase();
  const missingKeywords = targetKeywords.filter(keyword => !normalizedResume.includes(keyword));
  const alignment = targetKeywords.length ? Math.round(((targetKeywords.length - missingKeywords.length) / targetKeywords.length) * 100) : null;
  const evidenceScore = Math.min(100, 25 + actionCount * 8 + metricCount * 10 + hardSkills.length * 6 + (timelinePassed ? 12 : 0) + (hasContact ? 8 : 0) + (readable ? 7 : 0));
  const score = Math.max(20, Math.min(84, Math.round(50 + (evidenceScore - 50) * 0.58)));
  const strengths = [];
  if (hasContact) strengths.push("Contact details are easy to identify.");
  if (actionCount) strengths.push(`${actionCount} experience bullet${actionCount === 1 ? " begins" : "s begin"} with specific action language.`);
  if (hardSkills.length) strengths.push(`Concrete skills include ${hardSkills.slice(0, 5).join(", ")}.`);
  if (metricCount) strengths.push(`${metricCount} bullet${metricCount === 1 ? " includes" : "s include"} measurable scale or results.`);
  if (!strengths.length) strengths.push("The resume provides a starting point; the next step is adding specific, truthful evidence.");
  return {
    mode, score, wordCount, careerStage, checks, strengths,
    alignment, missingKeywords: missingKeywords.slice(0, 8),
    tailoring: mode === "JOB_REVIEW" ? buildJobTailoringEvidence(resumeText, tailoringText || jobDescription) : null
  };
}

// Prefer the backend's structured evaluator; the adapter below preserves the
// versioned rendering contract used by this page.
async function requestResumeEvaluation(payload) {
  const response = await fetch(
    apiUrl("/resume-evaluator/evaluate"),
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }
  );
  const data = await response.json();
  if (response.status === 401) {
    window.location.href = "login.html";
    return null;
  }
  if (!response.ok) {
    throw new Error(data.detail || "PathForge could not evaluate this resume.");
  }
  return data;
}

function setResumeReviewLoading(isLoading) {
  const button = document.getElementById("reviewResumeButton");
  const status = document.getElementById("resumeReviewStatus");
  button.disabled = isLoading;
  button.setAttribute("aria-busy", String(isLoading));
  button.textContent = isLoading ? "Reviewing resume..." : "Review resume";
  if (isLoading) {
    status.textContent = "Reviewing experience, skills, dates, and evidence...";
  }
}

function adaptBackendResumeEvaluation(result) {
  const experience = result.section_audits?.experience || {};
  const skills = result.section_audits?.skills || {};
  const timeline = result.timeline_audit || {};
  const evidence = result.analysis_evidence || {};
  const experienceRewrites = (result.critical_improvements || [])
    .filter(item => /bullet|accomplishment|action|impact/i.test(item.issue || ""))
    .map(item => ({ before: item.before, after: item.after }));
  const skillRewrites = (result.critical_improvements || [])
    .filter(item => /skill/i.test(item.issue || ""))
    .map(item => ({ before: item.before, after: item.after }));
  const timelineRewrites = (result.critical_improvements || [])
    .filter(item => /timeline|date|duration/i.test(item.issue || ""))
    .map(item => ({ before: item.before, after: item.after }));
  const timelinePassed = Boolean(timeline.employment_ranges?.length) && !(timeline.flags || []).length;
  const concreteSkills = (skills.concrete_skills || []).map(item => typeof item === "string" ? item : item.label);
  const isEarlyCareerStage = ["student", "entry_level"].includes(evidence.career_stage);
  const earlyCareerDensityIsUseful = concreteSkills.length >= 2 || experience.bullet_count >= 2;
  const careerStageLengthPassed = isEarlyCareerStage
    ? evidence.word_count >= 100 && (evidence.word_count > 200 || earlyCareerDensityIsUseful)
    : evidence.word_count >= (
      evidence.career_stage === "executive"
        ? 500
        : evidence.career_stage === "career_changer"
          ? 250
          : 300
    );
  const checks = [
    {
      title: "Experience evidence",
      passed: experience.action_led_bullet_ratio >= 0.5 && (experience.metric_count > 0 || experience.bullet_count >= 2),
      message: experience.assessment || "Experience evidence could not be fully assessed.",
      rewrites: experienceRewrites
    },
    {
      title: "Skills evidence",
      passed: concreteSkills.length >= 2,
      message: `${skills.assessment || "Skills need review."}${concreteSkills.length ? ` Concrete skills detected: ${concreteSkills.join(", ")}.` : ""}`,
      rewrites: skillRewrites
    },
    {
      title: "Claims and employment timeline",
      passed: timelinePassed,
      message: (timeline.flags || []).length
        ? timeline.flags.map(flag => flag.message).join(" ")
        : timeline.employment_ranges?.length
          ? `Your work history shows approximately ${timeline.documented_employment_months} months of experience, with no significant gaps detected.`
          : "No complete employment date range was detected, so duration claims could not be verified.",
      rewrites: timelineRewrites
    },
    {
      title: "Career-stage-aware length",
      passed: careerStageLengthPassed,
      message: `${evidence.word_count || 0} words were evaluated for the ${String(evidence.career_stage || "mid_level").replaceAll("_", " ")} career stage. Evidence density matters more than adding filler.`
    }
  ];
  const jobAlignment = result.job_alignment;
  const analyzed = Number(jobAlignment?.requirements_analyzed || 0);
  const supported = jobAlignment?.supported || [];
  const actionItems = [...new Set(result.score_breakdown?.priority_actions || [])].slice(0, 3);
  return {
    mode: result.evaluation_mode,
    score: result.overall_score,
    scoreBreakdown: result.score_breakdown || {
      career_stage: {
        code: evidence.career_stage || "mid_level",
        label: String(evidence.career_stage || "mid_level").replaceAll("_", " ")
      },
      context_explanation: "The score reflects the amount and quality of evidence available in this resume.",
      factors_lowering_score: [],
      factors_supporting_score: [],
      reassurance_note: "This score is guidance, not a hiring prediction."
    },
    wordCount: evidence.word_count || 0,
    careerStage: evidence.career_stage,
    checks,
    strengths: result.key_strengths || [],
    actionItems,
    alignment: null,
    missingKeywords: [],
    tailoring: jobAlignment ? {
      analyzedCount: analyzed,
      supported: supported.map(item => ({
        requirement: item.requirement,
        evidence: item.evidence,
        matchedTerms: item.matched_terms || []
      })),
      missing: (jobAlignment.unsupported_or_uncertain || []).map(item => ({
        requirement: item.requirement,
        evidence: item.evidence,
        matchedTerms: item.matched_terms || []
      })),
      prompts: (jobAlignment.unsupported_or_uncertain || []).slice(0, 4).map(item =>
        `Do you have truthful evidence for “${item.requirement.slice(0, 100)}”? If it is not documented or you do not meet it, treat it as a gap rather than claiming it.`
      )
    } : null
  };
}

function renderResumeReview(review) {
  const results = document.getElementById("resumeReviewResults");
  const checks = document.getElementById("resumeReviewChecks");
  const nextSteps = document.getElementById("resumeNextSteps");
  const keywordSection = document.getElementById("resumeKeywordSection");
  const keywordList = document.getElementById("resumeKeywordList");
  const strengthsList = document.getElementById("resumeStrengths");

  document.getElementById("resumeReadinessScore").textContent = review.score;
  const normalizedScore = Math.max(0, Math.min(100, Number(review.score) || 0));
  document.querySelector(".resume-readiness")?.style.setProperty(
    "--score-progress",
    `${normalizedScore * 3.6}deg`
  );
  const scoreRange = review.score >= 81
    ? "Exceptional evidence"
    : review.score >= 61
      ? "Strong foundation"
      : review.score >= 41
        ? "Developing foundation"
        : "Early foundation";
  document.getElementById("resumeCurrentScoreRange").textContent = scoreRange;
  document.querySelectorAll(".resume-score-ranges [data-score-min]").forEach(range => {
    const minimum = Number(range.dataset.scoreMin);
    const maximum = Number(range.dataset.scoreMax);
    const isCurrent = review.score >= minimum && review.score <= maximum;
    range.classList.toggle("current-range", isCurrent);
    if (isCurrent) {
      range.setAttribute("aria-current", "true");
    } else {
      range.removeAttribute("aria-current");
    }
  });
  const passedCheckCount = review.checks.filter((check) => check.passed).length;
  const overallAssessment = review.score >= 85
    ? "Strong foundation."
    : review.score >= 70
      ? "Solid foundation with a few improvements."
      : review.score >= 55
        ? "Useful content, but some evidence needs to be clearer."
        : "Good starting point, but the structure and evidence need work.";

  const stageSummaryHeader = review.scoreBreakdown?.summary_header ||
    `${review.scoreBreakdown?.career_stage?.label || "Career stage"} review`;
  document.getElementById("resumeReviewSummary").textContent =
    stageSummaryHeader + ". " + overallAssessment + " The review found " + passedCheckCount +
    " of " + review.checks.length +
    " evidence checks. This is guidance, not a hiring prediction.";

  const scoreBreakdown = review.scoreBreakdown;
  const scoreStageLabel = scoreBreakdown.career_stage?.label || "Career stage not confirmed";
  const scoreStageSource = scoreBreakdown.career_stage?.source === "selected" ? "selected" : "auto";
  document.getElementById("resumeDetectedCareerStage").textContent =
    `${scoreStageLabel} (${scoreStageSource})`;
  document.getElementById("resumeScoreContextExplanation").textContent =
    scoreBreakdown.context_explanation || "";
  const rubricWeights = scoreBreakdown.category_weights || {};
  const rubricWeightText = Object.keys(rubricWeights).length
    ? ` Weights: Skills ${rubricWeights.skills}%, impact ${rubricWeights.impact_metrics}%, grammar and tone ${rubricWeights.grammar_tone}%, formatting ${rubricWeights.formatting}%, timeline ${rubricWeights.timeline_logic}%.`
    : "";
  document.getElementById("resumeScoreRubric").textContent =
    (scoreBreakdown.rubric_note || "") + rubricWeightText;
  document.getElementById("resumeScoreReassurance").textContent =
    scoreBreakdown.reassurance_note || "";

  const loweringFactors = document.getElementById("resumeScoreLoweringFactors");
  const supportingFactors = document.getElementById("resumeScoreSupportingFactors");
  loweringFactors.replaceChildren();
  supportingFactors.replaceChildren();
  (scoreBreakdown.factors_lowering_score || []).slice(0, 3).forEach(factor => {
    const item = document.createElement("li");
    item.textContent = factor;
    loweringFactors.appendChild(item);
  });
  (scoreBreakdown.factors_supporting_score || []).slice(0, 3).forEach(factor => {
    const item = document.createElement("li");
    item.textContent = factor;
    supportingFactors.appendChild(item);
  });

  strengthsList.replaceChildren();
  review.strengths.forEach((strength) => {
    const item = document.createElement("li");
    item.textContent = strength;
    strengthsList.appendChild(item);
  });

  checks.replaceChildren();
  review.checks.forEach((check) => {
    const card = document.createElement("article");
    const heading = document.createElement("h3");
    const message = document.createElement("p");
    card.className = "resume-review-check" + (check.passed ? "" : " needs-work");
    heading.textContent = (check.passed ? "Strong: " : "Needs attention: ") + check.title;
    message.textContent = check.message;
    card.append(heading, message);
    (check.rewrites || []).forEach(rewrite => {
      const example = document.createElement("div");
      example.className = "resume-rewrite-example";
      const before = document.createElement("p");
      const after = document.createElement("p");
      before.innerHTML = `<strong>Before:</strong> ${escapeEmployerHtml(rewrite.before)}`;
      after.innerHTML = `<strong>After:</strong> ${escapeEmployerHtml(rewrite.after)}`;
      example.append(before, after);
      card.appendChild(example);
    });
    checks.appendChild(card);
  });

  nextSteps.replaceChildren();
  (review.actionItems || [])
    .slice(0, 3)
    .forEach((action) => {
      const item = document.createElement("li");
      item.textContent = action;
      nextSteps.appendChild(item);
    });
  if (!nextSteps.children.length) {
    const item = document.createElement("li");
    item.textContent =
      "Confirm that your strongest truthful examples clearly support the job requirements before applying.";
    nextSteps.appendChild(item);
  }

  keywordList.replaceChildren();
  if (review.alignment !== null) {
    keywordSection.classList.remove("hidden");
    document.getElementById("resumeKeywordSummary").textContent =
      "Your resume uses about " + review.alignment +
      "% of the important job-match words. Only add a missing word when it truthfully describes your experience.";
    review.missingKeywords.forEach((keyword) => {
      const item = document.createElement("span");
      item.className = "resume-keyword";
      item.textContent = keyword;
      keywordList.appendChild(item);
    });
    if (!review.missingKeywords.length) {
      const item = document.createElement("span");
      item.textContent = "No prominent target terms appear to be missing.";
      keywordList.appendChild(item);
    }
  } else {
    keywordSection.classList.add("hidden");
  }

  const tailoringSection = document.getElementById("resumeTailoringEvidence");
  const suitabilitySummary = document.getElementById("resumeSuitabilitySummary");
  const supportedContainer = document.getElementById("resumeSupportedEvidence");
  const missingContainer = document.getElementById("resumeMissingEvidence");
  const promptsList = document.getElementById("resumeTailoringPrompts");
  if (review.tailoring && tailoringSection && supportedContainer && missingContainer && promptsList) {
    tailoringSection.classList.remove("hidden");
    if (suitabilitySummary) {
      const analyzedCount = Number(review.tailoring.analyzedCount || 0);
      const supportedCount = review.tailoring.supported.length;
      const supportRatio = analyzedCount ? supportedCount / analyzedCount : 0;
      const assessment = !analyzedCount
        ? "Not enough job requirements were available for a suitability comparison."
        : supportRatio >= 0.7
          ? "Strong documented alignment"
          : supportRatio >= 0.35
            ? "Partial documented alignment"
            : "Limited documented alignment";
      suitabilitySummary.textContent = analyzedCount
        ? `${assessment}: related résumé evidence was found for ${supportedCount} of ${analyzedCount} analyzed requirement statements. Confirm every requirement yourself before applying.`
        : assessment;
    }
    supportedContainer.innerHTML = review.tailoring.supported.length
      ? review.tailoring.supported.map(item => `<article><strong>${escapeEmployerHtml(item.requirement)}</strong><p>Related resume wording: ${escapeEmployerHtml(item.evidence)}</p><span>Shared terms: ${escapeEmployerHtml(item.matchedTerms.join(", "))}</span></article>`).join("")
      : "<p>No clear supporting wording was detected. This does not mean you lack the experience.</p>";
    missingContainer.innerHTML = review.tailoring.missing.length
      ? review.tailoring.missing.map(item => `<article><strong>${escapeEmployerHtml(item.requirement)}</strong><p>No sufficiently related resume statement was detected.</p></article>`).join("")
      : review.tailoring.analyzedCount === 0
        ? "<p>This posting did not provide enough specific requirement statements for an evidence comparison. Review the official listing or paste more detailed requirements.</p>"
        : "<p>No major evidence gaps were detected in the analyzed statements. Review every claim manually.</p>";
    promptsList.replaceChildren();
    review.tailoring.prompts.forEach(prompt => {
      const item = document.createElement("li");
      item.textContent = prompt;
      promptsList.appendChild(item);
    });
  } else if (tailoringSection) {
    tailoringSection.classList.add("hidden");
    if (suitabilitySummary) suitabilitySummary.textContent = "";
  }

  results.classList.remove("hidden");
  results.focus({ preventScroll: true });
  results.scrollIntoView({
    behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
      ? "auto"
      : "smooth",
    block: "start"
  });
}

async function loadResumeJobTarget() {
  const targetStatus = document.getElementById("resumeJobTargetStatus");
  const roleInput = document.getElementById("resumeTargetRole");
  const descriptionInput = document.getElementById("resumeJobDescription");
  const jobId = Number(new URLSearchParams(window.location.search).get("job"));
  if (!targetStatus || !roleInput || !descriptionInput || !Number.isInteger(jobId) || jobId <= 0) return;
  targetStatus.textContent = "Loading the selected PathForge job…";
  try {
    const response = await fetch(apiUrl(`/jobs/${jobId}`));
    if (!response.ok) throw new Error("The selected job could not be loaded.");
    const job = await response.json();
    roleInput.value = `${job.title} at ${job.company}`;
    descriptionInput.value = [
      cleanJobPostingText(job.description),
      job.requirements ? `Requirements:\n${cleanJobPostingText(job.requirements)}` : "",
      job.preferred_qualifications ? `Preferred qualifications:\n${cleanJobPostingText(job.preferred_qualifications)}` : ""
    ].filter(Boolean).join("\n\n");
    selectedResumeJobRequirements = [
      job.requirements ? cleanJobPostingText(job.requirements) : "",
      job.preferred_qualifications ? cleanJobPostingText(job.preferred_qualifications) : ""
    ].filter(text => text && !/see (?:the )?official posting|complete qualifications/i.test(text)).join("\n");
    targetStatus.innerHTML = `Selected PathForge job: <strong>${escapeEmployerHtml(job.title)}</strong> at <a href="company.html?name=${encodeURIComponent(job.company)}">${escapeEmployerHtml(job.company)}</a>. Review the official posting before applying.`;
  } catch (error) {
    targetStatus.classList.add("error-message");
    targetStatus.textContent = error.message || "The selected job could not be loaded.";
  }
}

function initializeResumeReview() {
  const form = document.getElementById("resumeReviewForm");
  if (!form) {
    return;
  }

  const fileInput = document.getElementById("resumeFile");
  const dropZone = document.getElementById("resumeDropZone");
  const dropZoneTitle = document.getElementById("resumeDropZoneTitle");
  const dropZoneHint = document.getElementById("resumeDropZoneHint");
  const resumeText = document.getElementById("resumeText");
  const fileStatus = document.getElementById("resumeFileStatus");
  const resumeTextFallback = document.getElementById("resumeTextFallback");
  const showResumeTextButton = document.getElementById("showResumeTextButton");
  const status = document.getElementById("resumeReviewStatus");
  loadResumeJobTarget();

  showResumeTextButton?.addEventListener("click", () => {
    const willShow = resumeTextFallback.classList.contains("hidden");
    resumeTextFallback.classList.toggle("hidden", !willShow);
    showResumeTextButton.textContent = willShow
      ? "Hide pasted resume text"
      : "Can't upload a file? Paste resume text instead";
    showResumeTextButton.setAttribute("aria-expanded", String(willShow));
    if (willShow) resumeText.focus();
  });

  const resetResumeDropZone = () => {
    dropZone.classList.remove("drag-active", "has-file");
    dropZoneTitle.textContent = "Drag and drop your resume here";
    dropZoneHint.textContent = "or select this box to browse your files";
  };

  const processResumeFile = async file => {
    if (!file) {
      return;
    }
    const supportedExtensions = [
      ".pdf", ".docx", ".rtf", ".txt", ".md", ".csv",
      ".json", ".html", ".htm", ".xml"
    ];
    if (!supportedExtensions.some(extension => file.name.toLowerCase().endsWith(extension))) {
      fileInput.value = "";
      resetResumeDropZone();
      fileStatus.textContent = "Choose a PDF, DOCX, RTF, TXT, Markdown, CSV, JSON, HTML, or XML file.";
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      fileInput.value = "";
      resetResumeDropZone();
      fileStatus.textContent = "The selected file is larger than 5 MB.";
      return;
    }
    try {
      dropZone.classList.remove("has-file");
      dropZoneTitle.textContent = "Reading " + file.name + "...";
      dropZoneHint.textContent = "Please wait while PathForge prepares your resume.";
      fileStatus.textContent = "Reading " + file.name + "...";
      const response = await fetch(apiUrl("/learning-assistant/extract-document"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          filename: file.name,
          content_base64: await readFileAsBase64(file)
        })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "PathForge could not read that document.");
      resumeText.value = data.text;
      dropZone.classList.add("has-file");
      dropZoneTitle.textContent = file.name + " is ready";
      dropZoneHint.textContent = "Select this box to choose a different file.";
      fileStatus.textContent = file.name + " is ready for review. The file is not saved to your account.";
      resumeTextFallback.classList.add("hidden");
      showResumeTextButton.textContent = "Can't upload a file? Paste resume text instead";
      showResumeTextButton.setAttribute("aria-expanded", "false");
    } catch (error) {
      console.error("Resume file read failed:", error);
      fileInput.value = "";
      resetResumeDropZone();
      fileStatus.textContent = error.message || "PathForge could not read that file. Try pasting the resume text instead.";
    }
  };

  fileInput.addEventListener("change", () => {
    processResumeFile(fileInput.files[0]);
  });

  dropZone.addEventListener("click", () => fileInput.click());
  dropZone.addEventListener("keydown", event => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    fileInput.click();
  });

  ["dragenter", "dragover"].forEach(eventName => {
    dropZone.addEventListener(eventName, event => {
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
      dropZone.classList.add("drag-active");
    });
  });

  dropZone.addEventListener("dragleave", event => {
    if (event.relatedTarget && dropZone.contains(event.relatedTarget)) return;
    dropZone.classList.remove("drag-active");
  });

  dropZone.addEventListener("drop", event => {
    event.preventDefault();
    dropZone.classList.remove("drag-active");
    const file = event.dataTransfer?.files?.[0];
    if (!file) return;
    try {
      const transfer = new DataTransfer();
      transfer.items.add(file);
      fileInput.files = transfer.files;
    } catch (error) {
      console.debug("The dropped file could not be mirrored to the file field.", error);
    }
    processResumeFile(file);
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = prepareResumeTextForReview(resumeText.value);
    status.classList.remove("success-message", "error-message");
    if (getResumeWords(text).length < 40) {
      status.textContent =
        "Upload a resume file or paste at least 40 words for a useful review.";
      resumeTextFallback.classList.remove("hidden");
      showResumeTextButton.textContent = "Hide pasted resume text";
      showResumeTextButton.setAttribute("aria-expanded", "true");
      status.classList.add("error-message");
      resumeText.focus();
      return;
    }
    const jobDescription = document.getElementById("resumeJobDescription").value.trim();
    const targetRole = document.getElementById("resumeTargetRole").value.trim();
    setResumeReviewLoading(true);
    try {
      const result = await requestResumeEvaluation({
        resume_text: text,
        job_description: jobDescription || null,
        target_role: targetRole || null,
        career_stage: document.getElementById("resumeCareerStage")?.value || "auto"
      });
      if (!result) return;
      renderResumeReview(adaptBackendResumeEvaluation(result));
      status.textContent = "Resume reviewed successfully. Start with the items under What to improve first.";
      status.classList.add("success-message");
    } catch (error) {
      status.textContent = error.message || "PathForge could not evaluate this resume.";
      status.classList.add("error-message");
    } finally {
      setResumeReviewLoading(false);
    }
  });

  document.getElementById("clearResumeButton").addEventListener("click", () => {
    form.reset();
    document.getElementById("resumeReviewResults").classList.add("hidden");
    status.textContent = "Resume review cleared.";
    fileStatus.textContent =
      "Supported: PDF, DOCX, RTF, TXT, Markdown, CSV, JSON, HTML, and XML up to 5 MB.";
    resetResumeDropZone();
    resumeTextFallback.classList.add("hidden");
    showResumeTextButton.textContent = "Can't upload a file? Paste resume text instead";
    showResumeTextButton.setAttribute("aria-expanded", "false");
    dropZone.focus();
  });
}

function updateSchedulePreferenceSummary() {
  const summary = document.getElementById(
    "profileSchedulePreferenceSummary"
  );

  if (!summary) {
    return;
  }

  const selectedSchedules = Array.from(
    document.querySelectorAll(
      "#profileSchedulePreference input[type='checkbox']:checked"
    )
  ).map(checkbox => checkbox.value);

  if (selectedSchedules.length === 0) {
    summary.textContent = "Choose schedules";
  } else if (selectedSchedules.length <= 2) {
    summary.textContent = selectedSchedules.join(", ");
  } else {
    summary.textContent = `${selectedSchedules.length} schedules selected`;
  }
}

function updateExperienceLevelSummary() {
  const input = document.getElementById("profileExperienceLevel");
  const summary = document.getElementById("profileExperienceLevelSummary");

  if (!input || !summary) {
    return;
  }

  summary.textContent = input.value || "Select experience level";
}

function initializeExperienceLevelDropdown() {
  const dropdown = document.getElementById("profileExperienceLevelDropdown");
  const input = document.getElementById("profileExperienceLevel");

  if (!dropdown || !input) {
    return;
  }

  dropdown.querySelectorAll("input[type='radio']").forEach(radio => {
    radio.addEventListener("click", function () {
      if (input.value === radio.value) {
        radio.checked = false;
        input.value = "";
        updateExperienceLevelSummary();
        dropdown.open = false;
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });

    radio.addEventListener("change", function () {
      if (!radio.checked) {
        return;
      }

      input.value = radio.value;
      updateExperienceLevelSummary();
      dropdown.open = false;
    });
  });

  updateExperienceLevelSummary();
}

function updateWorkPreferenceSummary() {
  const input = document.getElementById("profileWorkPreference");
  const summary = document.getElementById("profileWorkPreferenceSummary");

  if (!input || !summary) {
    return;
  }

  summary.textContent = input.value || "Select work preference";
}

function initializeWorkPreferenceDropdown() {
  const dropdown = document.getElementById("profileWorkPreferenceDropdown");
  const input = document.getElementById("profileWorkPreference");
  const clearButton = document.getElementById("clearWorkPreference");

  if (!dropdown || !input) {
    return;
  }

  dropdown.querySelectorAll("input[type='radio']").forEach(radio => {
    radio.addEventListener("change", function () {
      input.value = radio.value;
      updateWorkPreferenceSummary();
      dropdown.open = false;
    });
  });

  if (clearButton) {
    clearButton.addEventListener("click", function () {
      dropdown.querySelectorAll("input[type='radio']").forEach(radio => {
        radio.checked = false;
      });
      input.value = "";
      updateWorkPreferenceSummary();
      dropdown.open = false;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
  }

  updateWorkPreferenceSummary();
}

function initializeSchedulePreferenceDropdown() {
  document.querySelectorAll(
    "#profileSchedulePreference input[type='checkbox']"
  ).forEach(checkbox => {
    checkbox.addEventListener(
      "change",
      updateSchedulePreferenceSummary
    );
  });

  updateSchedulePreferenceSummary();
}

function updateAdditionalPayPreferenceSummary() {
  const summary = document.getElementById(
    "profileDesiredPaySummary"
  );

  if (!summary) {
    return;
  }

  const selectedPreferences = Array.from(
    document.querySelectorAll(
      "#profileDesiredPay input[type='checkbox']:checked"
    )
  ).map(checkbox => checkbox.value);

  if (selectedPreferences.length === 0) {
    summary.textContent = "Choose additional pay preferences";
  } else if (selectedPreferences.length <= 2) {
    summary.textContent = selectedPreferences.join(", ");
  } else {
    summary.textContent =
      `${selectedPreferences.length} preferences selected`;
  }
}

function initializeAdditionalPayPreferenceDropdown() {
  document.querySelectorAll(
    "#profileDesiredPay input[type='checkbox']"
  ).forEach(checkbox => {
    checkbox.addEventListener(
      "change",
      updateAdditionalPayPreferenceSummary
    );
  });

  updateAdditionalPayPreferenceSummary();
}

function handleDelegatedActionClick(event) {
  const control = event.target.closest("[data-action]");
  if (!control) return;

  const action = control.dataset.action;
  const jobId = Number(control.dataset.jobId);
  const searchId = Number(control.dataset.searchId);
  const applicationId = Number(control.dataset.applicationId);

  const actions = {
    "toggle-job-chat": () => toggleChat(),
    "quick-job-message": () => quickMessage(control.dataset.message || ""),
    "send-job-message": () => sendMessage(),
    "reset-job-filters": () => resetJobFilters(),
    "save-job": () => saveJob(jobId, control),
    "toggle-job-details": () => toggleDetails(control),
    "begin-application": () => ApplicationService.begin(jobId),
    "report-job": () => openJobReportDialog(jobId, control),
    "hide-job": () => hideJobFromResults(jobId),
    "track-application-interest": () => ApplicationService.trackInterest(),
    "close-application-dialog": () => closeApplicationDialog(),
    "open-employer-website": () => ApplicationService.openEmployerWebsite(),
    "confirm-external-application": () => ApplicationService.confirmExternalApplication(),
    "check-saved-search": () => checkSavedSearch(searchId),
    "view-saved-search": () => viewSavedSearchMatches(searchId),
    "delete-saved-search": () => deleteSavedSearch(searchId),
    "reload-saved-jobs": () => loadSavedJobs(),
    "remove-saved-job": () => removeSavedJob(jobId, control),
    "reload-applications": () => loadApplications(),
    "delete-application": () => deleteApplication(applicationId, control),
    "reload-employer-jobs": () => loadEmployerJobs(),
    "open-application-form-builder": () => openApplicationFormBuilder(jobId),
    "edit-employer-job": () => openEmployerJobEditor(jobId),
    "delete-employer-job": () => deleteEmployerJob(jobId, control),
    "reload-employer-applications": () => loadEmployerApplications(),
    "open-notification": () => openNotification(event, Number(control.dataset.notificationId))
  };

  if (actions[action]) actions[action]();
}

function handleDelegatedActionChange(event) {
  const control = event.target.closest("[data-action]");
  if (!control) return;
  const action = control.dataset.action;
  if (action === "compare-job") {
    toggleJobComparison(Number(control.dataset.jobId), control);
  } else if (action === "change-saved-search-frequency") {
    changeSavedSearchFrequency(Number(control.dataset.searchId), control.value);
  } else if (action === "toggle-saved-search") {
    toggleSavedSearch(Number(control.dataset.searchId), control.checked);
  } else if (action === "update-employer-job-status") {
    updateEmployerJobStatus(Number(control.dataset.jobId), control.value, control);
  }
}

function handleDelegatedActionSubmit(event) {
  const form = event.target.closest("form[data-action]");
  if (!form) return;
  if (form.dataset.action === "update-employer-application") {
    updateEmployerApplication(event, Number(form.dataset.applicationId));
  }
}

document.addEventListener("click", handleDelegatedActionClick);
document.addEventListener("change", handleDelegatedActionChange);
document.addEventListener("submit", handleDelegatedActionSubmit);

document.addEventListener("DOMContentLoaded", initializeResumeReview);
document.addEventListener(
  "DOMContentLoaded",
  initializeExperienceLevelDropdown
);
document.addEventListener(
  "DOMContentLoaded",
  initializeWorkPreferenceDropdown
);
document.addEventListener(
  "DOMContentLoaded",
  initializeSchedulePreferenceDropdown
);
document.addEventListener(
  "DOMContentLoaded",
  initializeAdditionalPayPreferenceDropdown
);
