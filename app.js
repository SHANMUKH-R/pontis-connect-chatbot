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
const chatStorageKey = 'connect-assistant-demo-history';
let chatHistory = [];
let responsePending = false;

// Replace this function with an API request when the backend is ready.
// Response: { answer: string, sources: [{ title, url }], status: 'ok' | 'unavailable' | 'error' }.
async function sendChatMessage(question) {
  await new Promise(resolve => setTimeout(resolve, 550));
  const text = question.toLowerCase();
  const examples = [
    {
      keywords: ['what does connect do', 'mission', 'about connect'],
      answer: 'CONNECT brings Pittsburgh and neighboring municipalities together to work on shared public-policy challenges and develop solutions collaboratively.',
      sources: [{ title: 'CONNECT — Mission and Vision', url: 'https://connectgovs.org/' }]
    },
    {
      keywords: ['climate', 'resilience', 'reports'],
      answer: 'Start with CONNECT’s Reports page for official publications. This example does not search the report collection or confirm a particular climate action report. Visit the official page to review the available documents.',
      sources: [{ title: 'CONNECT Reports', url: 'https://connectgovs.org/reports/' }]
    },
    {
      keywords: ['priorities', 'initiatives'],
      answer: 'CONNECT’s website organizes priorities into Public Safety & Wellbeing, Infrastructure & Resilience, Emerging Priorities, and Ongoing Priorities. Visit the official Priorities page for the latest project information.',
      sources: [{ title: 'CONNECT Priorities', url: 'https://connectgovs.org/priorities/' }]
    },
    {
      keywords: ['get involved', 'join', 'membership', 'participate'],
      answer: 'The CONNECT homepage links to membership information for municipalities. You can also explore the Member Center or contact info@connectgovs.org to ask about getting involved.',
      sources: [
        { title: 'CONNECT — Municipal Membership', url: 'https://connectgovs.org/' },
        { title: 'CONNECT Member Center', url: 'https://connectgovs.org/member-center/' }
      ]
    }
  ];
  const example = examples.find(item => item.keywords.some(keyword => text.includes(keyword)));
  if (example) return { answer: example.answer, sources: example.sources, status: 'ok' };
  return {
    answer: 'That question is not covered by this demonstration. Try one of the suggested questions, or explore CONNECT’s official Reports and Member Center pages.',
    sources: [
      { title: 'CONNECT Reports', url: 'https://connectgovs.org/reports/' },
      { title: 'CONNECT Member Center', url: 'https://connectgovs.org/member-center/' }
    ],
    status: 'unavailable'
  };
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
  chatStatus.textContent = responsePending ? 'Preparing an example response…' : '';
}

function appendChatMessage(message, retryQuestion) {
  const item = document.createElement('div');
  item.className = `chat-message chat-message-${message.role}`;
  if (message.status === 'error') item.classList.add('chat-message-error');

  const label = document.createElement('span');
  label.className = 'chat-message-label';
  label.textContent = message.role === 'user' ? 'You' : 'CONNECT · Example response';
  if (message.status === 'unavailable') label.textContent = 'CONNECT · Not available in this demo';
  if (message.status === 'error') label.textContent = 'CONNECT · Response unavailable';
  const answer = document.createElement('p');
  answer.textContent = message.answer;
  item.append(label, answer);

  const sources = document.createElement('div');
  sources.className = 'chat-sources';
  const sourceList = document.createElement('ul');
  for (const source of Array.isArray(message.sources) ? message.sources : []) {
    // Treat future backend citation text and URLs as untrusted input.
    let url;
    try { url = new URL(source.url); } catch { continue; }
    if (url.protocol !== 'https:' || (url.hostname !== 'connectgovs.org' && !url.hostname.endsWith('.connectgovs.org'))) continue;
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
