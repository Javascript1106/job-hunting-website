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
        `http://127.0.0.1:8000/jobs/${job.id}/application-form`,
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
          `http://127.0.0.1:8000/jobs/`
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
            onclick="closeApplicationDialog()"
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

    const employerManaged =
      Boolean(application.employer_managed);

    const methodText = employerManaged
      ? "Employer-managed PathForge application"
      : application.application_method === "pathforge"
        ? "PathForge tracker entry"
        : "Applied on employer website";

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
            type="datetime-local"
            value="${formatDateTimeForInput(
              application.interview_date
            )}"
          >
        </div>
      `;

    const deleteButton = employerManaged
      ? ""
      : `
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
      `;

    card.innerHTML = `
      <div class="application-card-heading">
        <div>
          <h3>${escapeEmployerHtml(application.title)}</h3>

          <p class="application-company">
            ${escapeEmployerHtml(application.company)}
          </p>
        </div>

        <span class="application-method-badge">
          ${escapeEmployerHtml(methodText)}
        </span>
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
      </div>

      <form
        class="application-edit-form"
        data-employer-managed="${employerManaged}"
        onsubmit="updateApplication(
          event,
          ${application.id}
        )"
      >
        <div class="application-form-grid">
          ${statusField}
          ${applicationDateField}
          ${interviewField}

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

        <div class="application-card-actions">
          <button
            type="submit"
            class="application-save-button"
          >
            Save Personal Notes
          </button>

          ${deleteButton}
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
}

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
      "http://127.0.0.1:8000/me",
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

  jobsList.innerHTML = "<p>Loading your jobs...</p>";

  try {
    const response = await fetch(
      "http://127.0.0.1:8000/employer/jobs",
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

      const applicationFormButton =
        job.application_method === "pathforge"
          ? `
            <button
              type="button"
              class="application-form-button"
              onclick="openApplicationFormBuilder(${job.id})"
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

        ${applicationLink}
      </div>

      <p class="employer-job-description">
        ${escapeEmployerHtml(job.description)}
      </p>

      <div class="employer-job-controls">
        <div class="employer-status-control">
          <label for="employer-status-${job.id}">
            Status
          </label>

          <select
            id="employer-status-${job.id}"
            onchange="updateEmployerJobStatus(
              ${job.id},
              this.value,
              this
            )"
          >
            ${buildEmployerStatusOptions(job.status)}
          </select>
        </div>

                <div class="employer-job-actions">
          ${applicationFormButton}

          <button
            type="button"
            class="employer-edit-button"
            onclick="openEmployerJobEditor(${job.id})"
          >
            Edit
          </button>

          <button
            type="button"
            class="employer-delete-button"
            onclick="deleteEmployerJob(${job.id}, this)"
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
        "http://127.0.0.1:8000/jobs",
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
      submitButton.textContent = "Post Job";
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
        `http://127.0.0.1:8000/employer/jobs/${jobId}`,
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
      `http://127.0.0.1:8000/employer/jobs/${jobId}/status`,
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
      `http://127.0.0.1:8000/employer/jobs/${jobId}`,
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
      `http://127.0.0.1:8000/employer/jobs/${job.id}/application-form`,
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
      `http://127.0.0.1:8000/employer/jobs/${jobId}/application-form`,
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

  applicationsList.innerHTML =
    "<p>Loading received applications...</p>";

  try {
    const response = await fetch(
      "http://127.0.0.1:8000/employer/applications",
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
      </div>

      <section class="employer-application-answers">
        <h4>Application Answers</h4>

        ${answersMarkup}
      </section>

            <form
        class="employer-application-management"
        onsubmit="updateEmployerApplication(
          event,
          ${application.id}
        )"
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
      `http://127.0.0.1:8000/employer/applications/${applicationId}`,
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
      "http://127.0.0.1:8000/employer/statistics",
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
      "http://127.0.0.1:8000/employer/company-profile",
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
      "http://127.0.0.1:8000/employer/company-profile",
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

checkLoginStatus();
protectPage();
protectEmployerPage();
setupEmployerDashboard();
loadDashboard();
loadProfile();
setupProfileForm();
loadSavedJobs();
loadApplications();
setupApplicationDialog();
