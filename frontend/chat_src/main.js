const chatHistory = document.getElementById("chatHistory");
const chatInput = document.getElementById("chatInput");
const sendBtn = document.getElementById("sendBtn");
const typingIndicator = document.getElementById("typingIndicator");


let messages = [];

// Auto-resize textarea
chatInput.addEventListener('input', function() {
  this.style.height = 'auto';
  this.style.height = (this.scrollHeight) + 'px';
  if (this.value === '') {
    this.style.height = 'auto';
  }
});

chatInput.addEventListener('keydown', function(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

sendBtn.addEventListener('click', sendMessage);

function appendMessage(role, content, imageUrl = null) {
  const msgDiv = document.createElement("div");
  msgDiv.className = `message ${role === 'user' ? 'user-message' : 'bot-message'}`;
  
  const iconClass = role === 'user' ? 'fa-user' : 'fa-robot';
  
  let innerHTML = `
    <div class="avatar"><i class="fa-solid ${iconClass}"></i></div>
    <div class="content">
      <p>${content.replace(/\n/g, '<br>')}</p>
  `;

  if (imageUrl) {
    innerHTML += `
      <div class="gen-image-container">
        <img src="${imageUrl}" alt="Generated Image" />
      </div>
    `;
  }
  
  innerHTML += `</div>`;
  msgDiv.innerHTML = innerHTML;
  
  chatHistory.appendChild(msgDiv);
  scrollToBottom();
}

function scrollToBottom() {
  chatHistory.scrollTo({
    top: chatHistory.scrollHeight,
    behavior: 'smooth'
  });
}

function showTyping() {
  typingIndicator.style.display = 'flex';
  scrollToBottom();
}

function hideTyping() {
  typingIndicator.style.display = 'none';
}

async function sendMessage() {
  const text = chatInput.value.trim();
  if (!text) return;


  
  // Disable input while generating
  chatInput.value = '';
  chatInput.style.height = 'auto';
  chatInput.disabled = true;
  sendBtn.disabled = true;
  
  // Append user message
  appendMessage('user', text);
  messages.push({ role: "user", content: text });
  
  showTyping();

  try {
    const payload = {
      messages: messages,
      grok_api_key: "",
      fal_api_key: ""
    };

    const response = await fetch('/chat-generate', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      const errText = await response.text();
      throw new Error(errText);
    }

    const data = await response.json();
    
    // Append bot response
    appendMessage('assistant', data.text, data.image_url);
    
    // Update local history
    messages.push({ role: "assistant", content: data.text });
    
  } catch (error) {
    console.error(error);
    appendMessage('assistant', `⚠️ Lỗi: ${error.message}`);
  } finally {
    hideTyping();
    chatInput.disabled = false;
    sendBtn.disabled = false;
    chatInput.focus();
  }
}
