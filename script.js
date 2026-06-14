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