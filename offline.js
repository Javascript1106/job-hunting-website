document.getElementById("retryConnectionButton")?.addEventListener(
  "click",
  () => window.location.reload()
);

window.addEventListener("online", () => {
  const status = document.getElementById("connectionStatus");
  if (status) {
    status.textContent =
      "A connection is available — select Try again to continue.";
  }
});
