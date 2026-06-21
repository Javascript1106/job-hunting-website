let allJobs = [];

async function sendMessage() {
  const input = document.getElementById("chatInput");
  const chatBox = document.getElementById("chatBox");

  const userText = input.value.trim();

  if (userText === "") {
    return;
  }

  const userMessage = document.createElement("div");
  userMessage.className = "user-message";
  userMessage.textContent = userText;
  chatBox.appendChild(userMessage);

  input.value = "";

  const botMessage = document.createElement("div");
  botMessage.className = "bot-message";
  botMessage.textContent = "Thinking...";
  chatBox.appendChild(botMessage);

  try {
    const response = await fetch("http://127.0.0.1:8000/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ message: userText })
    });

    const data = await response.json();
    botMessage.textContent = data.reply;
  } catch (error) {
    botMessage.textContent = "Sorry, I couldn't connect to the Python backend.";
    console.error(error);
  }

  chatBox.scrollTop = chatBox.scrollHeight;
}

async function loadJobs() {
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
  const jobSearch = document.getElementById("jobSearchInput").value.toLowerCase();
  const locationSearch = document.getElementById("locationSearchInput").value.toLowerCase();
  const categoryFilter = document.getElementById("categoryFilter").value;

  const filteredJobs = allJobs.filter(job => {
    const matchesJob =
      job.title.toLowerCase().includes(jobSearch) ||
      job.company.toLowerCase().includes(jobSearch);

    const matchesLocation =
      job.location.toLowerCase().includes(locationSearch);

    const matchesCategory =
      categoryFilter === "all" || job.category === categoryFilter;

    return matchesJob && matchesLocation && matchesCategory;
  });

  displayJobs(filteredJobs);
}

window.onload = function() {
  loadJobs();

document
  .getElementById("categoryFilter")
  .addEventListener("change", filterJobs);  
  
document
    .getElementById("jobSearchInput")
    .addEventListener("input", filterJobs);

  document
    .getElementById("locationSearchInput")
    .addEventListener("input", filterJobs);
};