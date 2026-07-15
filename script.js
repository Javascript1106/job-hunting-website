let allJobs = [];
let savedJobIds = new Set();
let trackedJobIds = new Set();
let activeApplicationJob = null;

function quickMessage(message) {
  const input = document.getElementById("chatInput");

  if (!input) {
    return;
  }

  input.value = message;
  sendMessage();
}

async function sendMessage() {
  const input = document.getElementById("chatInput");
  const chatBox = document.getElementById("chatBox");

  if (!input || !chatBox) return;

  const userText = input.value.trim();

  if (userText === "") return;

  addMessage(userText, "user-message");
  input.value = "";

  const typingMessage = addMessage("PathForge AI is typing...", "bot-message typing");

  try {
    const response = await fetch("http://127.0.0.1:8000/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ message: userText })
    });

    const data = await response.json();

    setTimeout(() => {
      typingMessage.className = "bot-message";
      typingMessage.textContent = data.reply;
      scrollChatToBottom();
    }, 500);

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

  chatWindow.classList.toggle("hidden-chat");
}

function scrollChatToBottom() {
  const chatBox = document.getElementById("chatBox");

  if (chatBox) {
    chatBox.scrollTop = chatBox.scrollHeight;
  }
}

async function loadJobs() {
  const jobListings = document.getElementById("jobListings");

  if (!jobListings) {
    return;
  }

  try {
    const jobsResponse = await fetch(
      "http://127.0.0.1:8000/jobs"
    );

    if (!jobsResponse.ok) {
      throw new Error("Jobs could not be loaded.");
    }

    allJobs = await jobsResponse.json();

        try {
      const savedResponse = await fetch(
        "http://127.0.0.1:8000/saved-jobs",
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
        "http://127.0.0.1:8000/applications",
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

    populateCategoryFilter(allJobs);
    displayJobs(allJobs);

  } catch (error) {
    console.error("Failed to load jobs:", error);

    jobListings.innerHTML = `
      <p class="error-message">
        Job listings could not be loaded. Please try again.
      </p>
    `;
  }
}

function displayJobs(jobs) {
  const jobListings = document.getElementById("jobListings");

  if (!jobListings) {
    return;
  }

  jobListings.innerHTML = "";

  if (jobs.length === 0) {
    jobListings.innerHTML = `
      <div class="empty-state">
        <h3>No jobs found</h3>
        <p>Try changing your search or filter options.</p>
      </div>
    `;

    return;
  }

  jobs.forEach(job => {
    const jobCard = document.createElement("article");
    jobCard.className = "job-card";
    jobCard.dataset.jobId = job.id;

    const isSaved = savedJobIds.has(job.id);
    const isTracked = trackedJobIds.has(job.id);

    jobCard.innerHTML = `
      <h3>${job.title}</h3>

      <p>
        <strong>Company:</strong>
        ${job.company}
      </p>

      <p>
        <strong>Location:</strong>
        ${job.location}
      </p>

      <p>
        <strong>Pay:</strong>
        ${job.pay}
      </p>

      <div class="job-details hidden">
        <p>
          <strong>Description:</strong>
          ${job.description}
        </p>

        <p>
          <strong>Schedule:</strong>
          ${job.schedule}
        </p>

        <p>
          <strong>Experience:</strong>
          ${job.experience}
        </p>
      </div>

      <div class="job-card-actions">
        <button
          type="button"
          class="job-details-button"
          onclick="toggleDetails(this)"
        >
          View Details
        </button>

        <button
          type="button"
          class="save-job-button ${isSaved ? "saved" : ""}"
          onclick="saveJob(${job.id}, this)"
          ${isSaved ? "disabled" : ""}
        >
          ${isSaved ? "Saved" : "Save Job"}
        </button>

        <button
          type="button"
          class="apply-job-button ${isTracked ? "tracked" : ""}"
          onclick="ApplicationService.begin(${job.id})"
          ${isTracked ? "disabled" : ""}
        >
          ${isTracked ? "In Tracker" : "Apply"}
        </button>
      </div>

      <p
        class="job-save-message"
        aria-live="polite"
      ></p>
    `;

    jobListings.appendChild(jobCard);
  });
}

function populateCategoryFilter(jobs) {
  const categoryFilter = document.getElementById("categoryFilter");

  if (!categoryFilter) return;

  categoryFilter.innerHTML = '<option value="all">All Categories</option>';

  const categories = [...new Set(jobs.map(job => job.category))];

  categories.forEach(category => {
    const option = document.createElement("option");
    option.value = category;
    option.textContent = category;
    categoryFilter.appendChild(option);
  });
}

function toggleDetails(button) {
  const jobCard = button.closest(".job-card");
  const details = jobCard.querySelector(".job-details");

  details.classList.toggle("hidden");

  if (details.classList.contains("hidden")) {
    button.textContent = "View Details";
  } else {
    button.textContent = "Hide Details";
  }
}

async function saveJob(jobId, button) {
  const jobCard = button.closest(".job-card");
  const message = jobCard.querySelector(".job-save-message");

  message.textContent = "";
  message.classList.remove(
    "success-message",
    "error-message"
  );

  button.disabled = true;
  button.textContent = "Saving...";

  try {
    const response = await fetch(
      `http://127.0.0.1:8000/saved-jobs/${jobId}`,
      {
        method: "POST",
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
        data.detail || "The job could not be saved."
      );
    }

    savedJobIds.add(jobId);

    button.textContent = "Saved";
    button.classList.add("saved");
    button.disabled = true;

    message.textContent = data.message;
    message.classList.add("success-message");

  } catch (error) {
    console.error("Save job failed:", error);

    button.textContent = "Save Job";
    button.disabled = false;

    message.textContent = error.message;
    message.classList.add("error-message");
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


  showPathForgeDialog(job) {
    openApplicationDialog(
      `Apply to ${job.company}`,
      `
        This employer will accept applications through
        PathForge. The full employer-created application
        form will be connected during the Employer
        Dashboard expansion.

        You can add this position to your tracker now so
        you do not lose your place.
      `,
      `
        <button
          type="button"
          onclick="ApplicationService.trackInterest()"
        >
          Add to Tracker
        </button>

        <button
          type="button"
          class="secondary-dialog-button"
          onclick="closeApplicationDialog()"
        >
          Not Now
        </button>
      `
    );
  },


  showEmployerWebsiteDialog(job) {
    openApplicationDialog(
      `Continue to ${job.company}`,
      `
        This employer uses its own application website.
        PathForge will open the official application page
        in a new tab.

        Return here afterward and tell us whether you
        completed the application.
      `,
      `
        <button
          type="button"
          onclick="ApplicationService.openEmployerWebsite()"
        >
          Continue to Employer Website
        </button>

        <button
          type="button"
          class="secondary-dialog-button"
          onclick="closeApplicationDialog()"
        >
          Cancel
        </button>
      `
    );
  },


  openEmployerWebsite() {
    if (
      !activeApplicationJob ||
      !activeApplicationJob.application_url
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
        Only add the job to your tracker as Applied if
        you completed the employer's application.
      `,
      `
        <button
          type="button"
          onclick="ApplicationService.confirmExternalApplication()"
        >
          Yes, I Applied
        </button>

        <button
          type="button"
          class="secondary-dialog-button"
          onclick="ApplicationService.trackInterest()"
        >
          Not Yet, Save in Tracker
        </button>

        <button
          type="button"
          class="secondary-dialog-button"
          onclick="closeApplicationDialog()"
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
        "http://127.0.0.1:8000/applications",
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

function filterJobs() {
  const jobSearchInput = document.getElementById("jobSearchInput");
  const locationSearchInput = document.getElementById("locationSearchInput");
  const categoryFilter = document.getElementById("categoryFilter");

  if (!jobSearchInput || !locationSearchInput || !categoryFilter) return;

  const jobSearch = jobSearchInput.value.toLowerCase();
  const locationSearch = locationSearchInput.value.toLowerCase();
  const selectedCategory = categoryFilter.value;

  const filteredJobs = allJobs.filter(job => {
    const matchesJob =
      job.title.toLowerCase().includes(jobSearch) ||
      job.company.toLowerCase().includes(jobSearch);

    const matchesLocation =
      job.location.toLowerCase().includes(locationSearch);

    const matchesCategory =
      selectedCategory === "all" || job.category === selectedCategory;

    return matchesJob && matchesLocation && matchesCategory;
  });

  displayJobs(filteredJobs);
}

window.onload = function() {
  loadJobs();

  const categoryFilter = document.getElementById("categoryFilter");
  const jobSearchInput = document.getElementById("jobSearchInput");
  const locationSearchInput = document.getElementById("locationSearchInput");
  const chatInput = document.getElementById("chatInput");

  if (categoryFilter) {
    categoryFilter.addEventListener("change", filterJobs);
  }

  if (jobSearchInput) {
    jobSearchInput.addEventListener("input", filterJobs);
  }

  if (locationSearchInput) {
    locationSearchInput.addEventListener("input", filterJobs);
  }

  if (chatInput) {
    chatInput.addEventListener("keydown", function(event) {
      if (event.key === "Enter") {
        sendMessage();
      }
    });
  }
};

const registerForm = document.getElementById("registerForm");

if (registerForm) {
    registerForm.addEventListener("submit", async function (event) {
        event.preventDefault();

        const username = document.getElementById("registerUsername").value;
        const email = document.getElementById("registerEmail").value;
        const password = document.getElementById("registerPassword").value;
        const message = document.getElementById("registerMessage");

        try {
            const response = await fetch("http://127.0.0.1:8000/register", {
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
                message.textContent = data.detail || "Registration failed.";
                return;
            }

            message.textContent = "Account created successfully. You can now log in.";
            registerForm.reset();

        } catch (error) {
            message.textContent = "Something went wrong. Please try again.";
        }
    });
}

const loginForm = document.getElementById("loginForm");

if (loginForm) {
    loginForm.addEventListener("submit", async function (event) {
        event.preventDefault();

        const identifier = document.getElementById("loginIdentifier").value;
        const password = document.getElementById("loginPassword").value;
        const message = document.getElementById("loginMessage");

        try {
            const response = await fetch("http://127.0.0.1:8000/login", {
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
                message.textContent = data.detail || "Login failed.";
                return;
            }

            message.textContent = "Login successful.";
            await checkLoginStatus();

        } catch (error) {
            message.textContent = "Something went wrong. Please try again.";
        }
    });
}

async function checkLoginStatus() {
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

    const employerDashboardLink =
        document.getElementById("employerDashboardLink");

    const userStatus =
        document.getElementById("userStatus");

    const logoutButton =
        document.getElementById("logoutButton");

    try {
        const response = await fetch(
            "http://127.0.0.1:8000/me",
            {
                credentials: "include"
            }
        );

        if (!response.ok) {
            return null;
        }

        const user = await response.json();

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

        if (logoutButton) {
            logoutButton.style.display = "inline-block";
        }

        if (user.role === "employer") {
            if (employerDashboardLink) {
                employerDashboardLink.style.display = "inline";
            }

            if (employerAccessLink) {
                employerAccessLink.style.display = "none";
            }
        } else {
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

        return user;

    } catch (error) {
        console.error("Login check failed:", error);
        return null;
    }
}


const logoutButton = document.getElementById("logoutButton");

if (logoutButton) {
    logoutButton.addEventListener("click", async function () {

        await fetch("http://127.0.0.1:8000/logout", {
            method: "POST",
            credentials: "include"
        });

        window.location.href = "index.html";
    });
}

async function protectPage() {
    const protectedPages = [
    "dashboard.html",
    "profile.html",
    "saved-jobs.html",
    "applications.html",
    "employer-access.html"
];

    const currentPage = window.location.pathname.split("/").pop();

    if (!protectedPages.includes(currentPage)) {
        return;
    }

    try {
        const response = await fetch("http://127.0.0.1:8000/me", {
            credentials: "include"
        });

        if (!response.ok) {
            window.location.href = "login.html";
            return;
        }

    } catch (error) {
        window.location.href = "login.html";
    }
}

async function protectEmployerPage() {
    const currentPage =
        window.location.pathname.split("/").pop();

    if (currentPage !== "employer.html") {
        return;
    }

    try {
        const response = await fetch(
            "http://127.0.0.1:8000/me",
            {
                credentials: "include"
            }
        );

        if (!response.ok) {
            window.location.href = "login.html";
            return;
        }

        const user = await response.json();

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

async function loadDashboard() {
    const welcomeHeading = document.getElementById("dashboardWelcome");

    if (!welcomeHeading) {
        return;
    }

    try {
        const response = await fetch("http://127.0.0.1:8000/dashboard-summary", {
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

        } catch (error) {
        console.error("Dashboard connection error:", error);
        window.location.href = "login.html";
    }
}

function setupDashboardActions() {
    const actionMessage = document.getElementById("dashboardActionMessage");
    const comingSoonButtons = document.querySelectorAll(".coming-soon-action");

    if (!actionMessage || comingSoonButtons.length === 0) {
        return;
    }

    comingSoonButtons.forEach(button => {
        button.addEventListener("click", function () {
            const featureName = button.dataset.feature;
            actionMessage.textContent =
                featureName + " will be added later in Week 5.";
        });
    });
}

const employerAccessForm =
    document.getElementById("employerAccessForm");

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
                const response = await fetch(
                    "http://127.0.0.1:8000/employer-access/redeem",
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
            "http://127.0.0.1:8000/profile",
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

        document.getElementById("profileCareerInterests").value =
            profile.career_interests || "";

        document.getElementById("profilePreferredIndustries").value =
            profile.preferred_industries || "";

        document.getElementById("profileSkills").value =
            profile.skills || "";

        document.getElementById("profileExperienceLevel").value =
            profile.experience_level || "";

        document.getElementById("profilePreferredLocation").value =
            profile.preferred_location || "";

        document.getElementById("profileSchedulePreference").value =
            profile.schedule_preference || "";

        document.getElementById("profileWorkPreference").value =
            profile.work_preference || "";

        document.getElementById("profileDesiredPay").value =
            profile.desired_pay || "";

        document.getElementById("profileCareerGoals").value =
            profile.career_goals || "";

    } catch (error) {
        console.error("Profile load failed:", error);

        message.textContent = error.message;
        message.classList.remove("success-message");
        message.classList.add("error-message");
    }
}

function setupProfileForm() {
    const profileForm = document.getElementById("profileForm");

    if (!profileForm) {
        return;
    }

    profileForm.addEventListener(
        "submit",
        async function (event) {
            event.preventDefault();

            const message =
                document.getElementById("profileMessage");

            const saveButton =
                document.getElementById("saveProfileButton");

            message.textContent = "";

            message.classList.remove(
                "success-message",
                "error-message"
            );

            saveButton.disabled = true;
            saveButton.textContent = "Saving...";

            const profileData = {
                display_name:
                    document.getElementById("profileDisplayName").value.trim(),

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
                    document.getElementById("profileSchedulePreference").value,

                work_preference:
                    document.getElementById("profileWorkPreference").value,

                desired_pay:
                    document.getElementById("profileDesiredPay").value.trim(),

                career_goals:
                    document.getElementById("profileCareerGoals").value.trim()
            };

            try {
                const response = await fetch(
                    "http://127.0.0.1:8000/profile",
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

                message.textContent =
                    data.message || "Profile saved successfully.";

                message.classList.add("success-message");

            } catch (error) {
                console.error("Profile save failed:", error);

                message.textContent = error.message;
                message.classList.add("error-message");

            } finally {
                saveButton.disabled = false;
                saveButton.textContent = "Save Profile";
            }
        }
    );
}

async function loadSavedJobs() {
  const savedJobsContainer =
    document.getElementById("savedJobsContainer");

  if (!savedJobsContainer) {
    return;
  }

  try {
    const response = await fetch(
      "http://127.0.0.1:8000/saved-jobs",
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
        <p>${error.message}</p>
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
      <h3>${job.title}</h3>

      <p>
        <strong>Company:</strong>
        ${job.company}
      </p>

      <p>
        <strong>Location:</strong>
        ${job.location}
      </p>

      <p>
        <strong>Pay:</strong>
        ${job.pay}
      </p>

      <div class="job-details">
        <p>
          <strong>Description:</strong>
          ${job.description}
        </p>

        <p>
          <strong>Schedule:</strong>
          ${job.schedule}
        </p>

        <p>
          <strong>Experience:</strong>
          ${job.experience}
        </p>
      </div>

      <div class="job-card-actions">
        <button
          type="button"
          class="remove-saved-job-button"
          onclick="removeSavedJob(${job.id}, this)"
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
      `http://127.0.0.1:8000/saved-jobs/${jobId}`,
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

async function loadApplications() {
  const applicationsContainer =
    document.getElementById("applicationsContainer");

  if (!applicationsContainer) {
    return;
  }

  try {
    const response = await fetch(
      "http://127.0.0.1:8000/applications",
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

  } catch (error) {
    console.error(
      "Application tracker load failed:",
      error
    );

    applicationsContainer.innerHTML = `
      <div class="empty-state">
        <h3>Applications could not be loaded</h3>
        <p>${error.message}</p>
      </div>
    `;
  }
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

    const methodText =
      application.application_method === "pathforge"
        ? "Applied through PathForge"
        : "Applied on employer website";

    card.innerHTML = `
      <div class="application-card-heading">
        <div>
          <h3>${application.title}</h3>

          <p class="application-company">
            ${application.company}
          </p>
        </div>

        <span class="application-method-badge">
          ${methodText}
        </span>
      </div>

      <div class="application-job-summary">
        <p>
          <strong>Location:</strong>
          ${application.location}
        </p>

        <p>
          <strong>Pay:</strong>
          ${application.pay}
        </p>

        <p>
          <strong>Schedule:</strong>
          ${application.schedule}
        </p>
      </div>

      <form
        class="application-edit-form"
        onsubmit="updateApplication(
          event,
          ${application.id}
        )"
      >
        <div class="application-form-grid">

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

          <div class="application-field">
            <label for="interview-${application.id}">
              Interview Date
            </label>

            <input
              id="interview-${application.id}"
              class="application-interview-date"
              type="datetime-local"
              value="${formatDateTimeForInput(
                application.interview_date
              )}"
            >
          </div>

          <div class="application-field">
            <label for="follow-up-${application.id}">
              Follow-Up Date
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

        </div>

        <div class="application-field">
          <label for="notes-${application.id}">
            Notes
          </label>

          <textarea
            id="notes-${application.id}"
            class="application-notes"
            rows="4"
            placeholder="Add reminders, contact names, interview details, or follow-up notes."
          >${application.notes || ""}</textarea>
        </div>

        <div class="application-card-actions">
          <button
            type="submit"
            class="application-save-button"
          >
            Save Changes
          </button>

          <button
            type="button"
            class="application-delete-button"
            onclick="deleteApplication(
              ${application.id},
              this
            )"
          >
            Remove from Tracker
          </button>
        </div>

        <p
          class="application-message"
          aria-live="polite"
        ></p>
      </form>
    `;

    applicationsContainer.appendChild(card);
  });
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

async function updateApplication(
  event,
  applicationId
) {
  event.preventDefault();

  const form = event.currentTarget;
  const message =
    form.querySelector(".application-message");

  const saveButton =
    form.querySelector(".application-save-button");

  message.textContent = "";

  message.classList.remove(
    "success-message",
    "error-message"
  );

  saveButton.disabled = true;
  saveButton.textContent = "Saving...";

  const applicationData = {
    status:
      form.querySelector(".application-status").value,

    applied_at:
      form.querySelector(".application-applied-date")
        .value || null,

    interview_date:
      form.querySelector(
        ".application-interview-date"
      ).value || null,

    follow_up_date:
      form.querySelector(
        ".application-follow-up-date"
      ).value || null,

    notes:
      form.querySelector(".application-notes")
        .value
        .trim()
  };

  try {
    const response = await fetch(
      `http://127.0.0.1:8000/applications/${applicationId}`,
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

    message.textContent = data.message;
    message.classList.add("success-message");

  } catch (error) {
    console.error(
      "Application update failed:",
      error
    );

    message.textContent = error.message;
    message.classList.add("error-message");

  } finally {
    saveButton.disabled = false;
    saveButton.textContent = "Save Changes";
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
      `http://127.0.0.1:8000/applications/${applicationId}`,
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

checkLoginStatus();
protectPage();
protectEmployerPage();
loadDashboard();
setupDashboardActions();
loadProfile();
setupProfileForm();
loadSavedJobs();
loadApplications();
setupApplicationDialog();
