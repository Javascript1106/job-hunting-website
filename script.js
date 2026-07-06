let allJobs = [];

function quickMessage(message) {
  const input = document.getElementById("chatInput");

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
    console.error("Registration error:", error);
    message.textContent = "Connection error: " + error.message;
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

  if (!jobListings) return;

  try {
    const response = await fetch("http://127.0.0.1:8000/jobs");
    allJobs = await response.json();

    populateCategoryFilter(allJobs);
    displayJobs(allJobs);
  } catch (error) {
    console.error("Failed to load jobs:", error);
  }
}

function displayJobs(jobs) {
  const jobListings = document.getElementById("jobListings");
  jobListings.innerHTML = "";

  jobs.forEach(job => {
    const jobCard = document.createElement("div");
    jobCard.className = "job-card";

    jobCard.innerHTML = `
      <h3>${job.title}</h3>
      <p><strong>Company:</strong> ${job.company}</p>
      <p><strong>Location:</strong> ${job.location}</p>
      <p><strong>Pay:</strong> ${job.pay}</p>

      <div class="job-details hidden">
        <p><strong>Description:</strong> ${job.description}</p>
        <p><strong>Schedule:</strong> ${job.schedule}</p>
        <p><strong>Experience:</strong> ${job.experience}</p>
      </div>

      <button onclick="toggleDetails(this)">View Details</button>
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
  const details = button.previousElementSibling;

  details.classList.toggle("hidden");

  if (details.classList.contains("hidden")) {
    button.textContent = "View Details";
  } else {
    button.textContent = "Hide Details";
  }
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
    const loginLink = document.getElementById("loginLink");
    const registerLink = document.getElementById("registerLink");
    const userStatus = document.getElementById("userStatus");
    const logoutButton = document.getElementById("logoutButton");

    try {
        const response = await fetch("http://127.0.0.1:8000/me", {
            credentials: "include"
        });

        if (!response.ok) {
            return;
        }

        const user = await response.json();

        if (loginLink) {
            loginLink.style.display = "none";
        }

        if (registerLink) {
            registerLink.style.display = "none";
        }

        if (userStatus) {
            userStatus.textContent = "Logged in as " + user.username;
        }

        if (logoutButton) {
            logoutButton.style.display = "inline-block";
        }

    } catch (error) {
        console.error("Login check failed:", error);
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

checkLoginStatus();

async function protectPage() {
    const protectedPages = [
        "employer.html"
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

protectPage();