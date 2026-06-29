let allJobs = [];

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
    const response = await fetch("http://127.0.0.1:8080/chat", {
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
    typingMessage.className = "bot-message";
    typingMessage.textContent = "Sorry, I couldn't connect to the Python backend.";
    console.error(error);
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
    const response = await fetch("http://127.0.0.1:8080/jobs");
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