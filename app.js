const menuToggle = document.querySelector('.menu-toggle');
const navigation = document.querySelector('#primary-navigation');
const submenuToggles = document.querySelectorAll('.submenu-toggle');
const mobileLayout = window.matchMedia('(max-width: 760px)');

document.documentElement.classList.add('js');
menuToggle.hidden = false;

function setSubmenu(button, expanded) {
  button.setAttribute('aria-expanded', String(expanded));
  document.getElementById(button.getAttribute('aria-controls')).hidden = !expanded;
}

function closeSubmenus() {
  submenuToggles.forEach(button => setSubmenu(button, false));
}

function setMobileMenu(expanded) {
  menuToggle.setAttribute('aria-expanded', String(expanded));
  navigation.hidden = mobileLayout.matches && !expanded;
  if (!expanded) closeSubmenus();
}

submenuToggles.forEach(button => {
  button.hidden = false;
  setSubmenu(button, false);

  button.addEventListener('click', () => {
    const expanded = button.getAttribute('aria-expanded') === 'true';
    closeSubmenus();
    setSubmenu(button, !expanded);
  });

  const item = button.closest('.nav-item');
  item.addEventListener('pointerenter', event => {
    if (!mobileLayout.matches && event.pointerType === 'mouse') {
      closeSubmenus();
      setSubmenu(button, true);
    }
  });
  item.addEventListener('pointerleave', () => {
    if (!mobileLayout.matches && !item.contains(document.activeElement)) {
      setSubmenu(button, false);
    }
  });
  item.addEventListener('focusout', event => {
    if (!item.contains(event.relatedTarget)) setSubmenu(button, false);
  });
});

menuToggle.addEventListener('click', () => {
  setMobileMenu(menuToggle.getAttribute('aria-expanded') !== 'true');
});

document.addEventListener('click', event => {
  if (!event.target.closest('.site-header')) setMobileMenu(false);
});

document.addEventListener('keydown', event => {
  if (event.key !== 'Escape') return;
  if (document.querySelector('#connect-chat').open) return;
  const expandedSubmenu = document.querySelector('.submenu-toggle[aria-expanded="true"]');
  if (expandedSubmenu) {
    closeSubmenus();
    expandedSubmenu.focus();
  } else if (mobileLayout.matches && menuToggle.getAttribute('aria-expanded') === 'true') {
    setMobileMenu(false);
    menuToggle.focus();
  }
});

// Keep navigation visible on desktop and collapsed when entering the mobile layout.
mobileLayout.addEventListener('change', () => setMobileMenu(false));
setMobileMenu(false);

// Chat state is kept in this tab's session; storage failures fall back to memory.
const chatLauncher = document.querySelector('#chat-launcher');
const chatDialog = document.querySelector('#connect-chat');
const chatForm = document.querySelector('#chat-form');
const chatInput = document.querySelector('#chat-input');
const chatSend = document.querySelector('#chat-send');
const chatMessages = document.querySelector('#chat-messages');
const chatScroll = document.querySelector('#chat-scroll');
const chatStatus = document.querySelector('#chat-status');
const suggestedQuestions = document.querySelectorAll('.chat-suggestions button');
const chatStorageKey = 'connect-assistant-history';
let chatHistory = [];
let responsePending = false;

// The chat API is on this page's origin unless the chat-api-base meta tag in index.html names another one.
const chatApiBase = (document.querySelector('meta[name="chat-api-base"]')?.content || '').trim().replace(/\/+$/, '');
// A static host serves the page but has no chat API behind it: it answers /chat with "not found" or
// "method not allowed". That is a setup gap, not an outage, so it gets its own message and no retry.
const chatNotConnected = {
  answer: 'The assistant is not connected on this page yet. It answers when the site is opened from the project backend.',
  sources: [],
  status: 'unavailable'
};
const chatRequestTimeoutMs = 45000;
// Sources may link to the organization's site and to the document hosts its reports and newsletters use.
const chatSourceHosts = ['connectgovs.org', 'drive.google.com', 'docs.google.com', 'eepurl.com', 'mailchi.mp'];

// Response: { answer: string, sources: [{ title, url }], status: 'ok' | 'unavailable' | 'error' }.
async function sendChatMessage(question) {
  // Earlier questions give a follow-up like "Who is eligible?" its context.
  const asked = chatHistory.filter(message => message.role === 'user').map(message => message.answer);
  if (asked.at(-1) === question) asked.pop();
  const response = await fetch(`${chatApiBase}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, history: asked.slice(-6) }),
    signal: AbortSignal.timeout(chatRequestTimeoutMs)
  });
  if (response.status === 404 || response.status === 405) return chatNotConnected;
  if (!response.ok) throw new Error(`Chat request failed with status ${response.status}`);
  return response.json();
}

function saveChatHistory() {
  try {
    sessionStorage.setItem(chatStorageKey, JSON.stringify(chatHistory));
  } catch {
    // The current conversation remains available when browser storage is disabled or full.
  }
}

function scrollToLatestMessage() {
  chatScroll.scrollTop = chatMessages.childElementCount ? chatScroll.scrollHeight : 0;
}

function updateChatControls() {
  chatSend.disabled = responsePending || !chatInput.value.trim();
  suggestedQuestions.forEach(button => { button.disabled = responsePending; });
  chatMessages.querySelectorAll('.chat-retry').forEach(button => { button.disabled = responsePending; });
  chatStatus.textContent = responsePending ? 'Finding an answer…' : '';
}

function appendChatMessage(message, retryQuestion) {
  const item = document.createElement('div');
  item.className = `chat-message chat-message-${message.role}`;
  if (message.status === 'error') item.classList.add('chat-message-error');

  const label = document.createElement('span');
  label.className = 'chat-message-label';
  label.textContent = message.role === 'user' ? 'You' : 'CONNECT · Assistant';
  if (message.status === 'error') label.textContent = 'CONNECT · Response unavailable';
  const answer = document.createElement('p');
  answer.textContent = message.answer;
  item.append(label, answer);

  const sources = document.createElement('div');
  sources.className = 'chat-sources';
  const sourceList = document.createElement('ul');
  for (const source of Array.isArray(message.sources) ? message.sources : []) {
    // Treat backend citation text and URLs as untrusted input.
    let url;
    try { url = new URL(source.url); } catch { continue; }
    const allowedHost = chatSourceHosts.some(host => url.hostname === host || url.hostname.endsWith(`.${host}`));
    if (url.protocol !== 'https:' || !allowedHost) continue;
    const link = document.createElement('a');
    link.href = url.href;
    link.textContent = source.title || 'CONNECT source';
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.setAttribute('aria-label', `${link.textContent} (opens in a new tab)`);
    const sourceItem = document.createElement('li');
    sourceItem.append(link);
    sourceList.append(sourceItem);
  }
  if (sourceList.childElementCount) {
    const sourceLabel = document.createElement('strong');
    sourceLabel.textContent = 'Sources';
    sources.append(sourceLabel, sourceList);
    item.append(sources);
  }

  if (message.status === 'error' && retryQuestion) {
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.className = 'chat-retry';
    retry.textContent = 'Try again';
    retry.addEventListener('click', () => submitChatMessage(retryQuestion, false));
    item.append(retry);
  }
  chatMessages.append(item);
  scrollToLatestMessage();
}

async function submitChatMessage(question, addUserMessage = true) {
  question = question.trim();
  if (!question || question.length > 2000 || responsePending) return;
  responsePending = true;
  if (addUserMessage) {
    const message = { role: 'user', answer: question };
    chatHistory.push(message);
    appendChatMessage(message);
  }
  chatInput.value = '';
  chatInput.focus({ preventScroll: true });
  updateChatControls();
  saveChatHistory();

  let response;
  try {
    response = await sendChatMessage(question);
    if (!response || typeof response.answer !== 'string' || !['ok', 'unavailable', 'error'].includes(response.status)) {
      throw new Error('Invalid assistant response');
    }
  } catch {
    response = { answer: 'We couldn’t load a response. Please try again.', sources: [], status: 'error' };
  }
  const message = { role: 'assistant', answer: response.answer, sources: response.sources, status: response.status, retryQuestion: question };
  chatHistory.push(message);
  appendChatMessage(message, question);
  saveChatHistory();
  responsePending = false;
  updateChatControls();
}

function closeChat() {
  chatDialog.close();
}

chatLauncher.hidden = false;
chatLauncher.addEventListener('click', () => {
  if (chatDialog.open) {
    closeChat();
  } else {
    setMobileMenu(false);
    chatDialog.show();
    chatLauncher.setAttribute('aria-expanded', 'true');
    chatInput.focus({ preventScroll: true });
    scrollToLatestMessage();
  }
});
document.querySelector('#chat-close').addEventListener('click', closeChat);
chatDialog.addEventListener('close', () => {
  chatLauncher.setAttribute('aria-expanded', 'false');
  chatLauncher.focus({ preventScroll: true });
});
chatDialog.addEventListener('keydown', event => {
  if (event.key === 'Escape') {
    event.preventDefault();
    event.stopPropagation();
    closeChat();
  }
});
chatInput.addEventListener('input', updateChatControls);
chatInput.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});
chatForm.addEventListener('submit', event => {
  event.preventDefault();
  submitChatMessage(chatInput.value);
});
suggestedQuestions.forEach(button => {
  button.addEventListener('click', () => submitChatMessage(button.textContent));
});

try {
  const saved = JSON.parse(sessionStorage.getItem(chatStorageKey) || '[]');
  if (Array.isArray(saved)) {
    chatHistory = saved.filter(message => message && ['user', 'assistant'].includes(message.role) && typeof message.answer === 'string');
    chatHistory.forEach(message => appendChatMessage(message, message.retryQuestion));
  }
} catch {
  // A new conversation is used when saved data cannot be read.
}
updateChatControls();
