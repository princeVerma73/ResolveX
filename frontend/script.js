/**
 * ResolveX — Production Frontend WebSocket Chat Client
 * Minimalist ChatGPT & Gemini Aesthetic
 * Connects to ws://localhost:8000/ws/chat/{session_id}
 */

// -----------------------------------------------------------------------------
// 1. Session & Storage Management
// -----------------------------------------------------------------------------

function generateSessionId() {
  const chars = '0123456789ABCDEF';
  let hex = '';
  for (let i = 0; i < 12; i++) {
    hex += chars[Math.floor(Math.random() * chars.length)];
  }
  return `SES-${hex}`;
}

let sessionId = sessionStorage.getItem('resolvex_session_id') || generateSessionId();
sessionStorage.setItem('resolvex_session_id', sessionId);

function getSavedSessions() {
  try {
    return JSON.parse(localStorage.getItem('resolvex_chat_sessions') || '[]');
  } catch {
    return [];
  }
}

function saveSessionRecord(id, title) {
  let list = getSavedSessions();
  const existing = list.find((s) => s.id === id);
  if (existing) {
    if (title && existing.title === 'New Chat') {
      existing.title = title;
    }
  } else {
    list.unshift({
      id: id,
      title: title || 'New Chat',
      updatedAt: Date.now(),
    });
  }
  // Keep last 30 sessions
  if (list.length > 30) list = list.slice(0, 30);
  localStorage.setItem('resolvex_chat_sessions', JSON.stringify(list));
  renderSessionHistory();
}

function removeSessionRecord(id, event) {
  if (event) event.stopPropagation();
  let list = getSavedSessions().filter((s) => s.id !== id);
  localStorage.setItem('resolvex_chat_sessions', JSON.stringify(list));
  renderSessionHistory();
  if (sessionId === id) {
    startNewChat();
  }
}

// -----------------------------------------------------------------------------
// 2. DOM Elements & State
// -----------------------------------------------------------------------------

let socket = null;
let currentAssistantTextSpan = null;
let currentAssistantContainer = null;
let reconnectTimer = null;
let isFirstMessageInSession = true;

const sessionBadge = document.getElementById('session-badge');
const connectionStatus = document.getElementById('connection-status');
const statusText = document.getElementById('status-text');
const dotIndicator = document.getElementById('dot-indicator');
const pingIndicator = document.getElementById('ping-indicator');

const chatScrollContainer = document.getElementById('chat-scroll-container');
const heroState = document.getElementById('hero-state');
const messagesList = document.getElementById('messages-list');
const chatForm = document.getElementById('chat-form');
const chatInput = document.getElementById('chat-input');
const btnSend = document.getElementById('btn-send');
const btnNewChat = document.getElementById('btn-new-chat');
const btnClearChat = document.getElementById('btn-clear-chat');
const lifecycleBanner = document.getElementById('lifecycle-banner');
const lifecycleText = document.getElementById('lifecycle-text');
const lifecycleStep = document.getElementById('lifecycle-step');
const sessionHistoryList = document.getElementById('session-history-list');

// Mobile drawer elements
const sidebar = document.getElementById('sidebar');
const mobileBackdrop = document.getElementById('mobile-backdrop');
const btnOpenSidebar = document.getElementById('btn-open-sidebar');
const btnCloseSidebar = document.getElementById('btn-close-sidebar');

// Set active session ID in badge
sessionBadge.textContent = sessionId;

// -----------------------------------------------------------------------------
// 3. Sidebar Session History Rendering
// -----------------------------------------------------------------------------

function renderSessionHistory() {
  const sessions = getSavedSessions();
  sessionHistoryList.innerHTML = '';

  if (sessions.length === 0) {
    const emptyNotice = document.createElement('div');
    emptyNotice.className = 'px-2 py-3 text-[11px] text-zinc-500 italic';
    emptyNotice.textContent = 'No previous conversations';
    sessionHistoryList.appendChild(emptyNotice);
    return;
  }

  sessions.forEach((s) => {
    const isActive = s.id === sessionId;
    const item = document.createElement('div');
    item.className = `group flex items-center justify-between px-2.5 py-2 rounded-lg cursor-pointer text-xs transition ${
      isActive
        ? 'bg-[#262626] text-white font-medium border border-[#383838]'
        : 'text-zinc-400 hover:bg-[#212121] hover:text-zinc-200'
    }`;

    item.innerHTML = `
      <div class="flex items-center gap-2 truncate">
        <svg class="w-3.5 h-3.5 text-zinc-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
        </svg>
        <span class="truncate max-w-[140px] text-xs">${escapeHtml(s.title || 'Conversation')}</span>
      </div>
      <button class="opacity-0 group-hover:opacity-100 text-zinc-500 hover:text-zinc-300 p-0.5 rounded transition" title="Delete conversation" data-id="${s.id}">
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M6 18L18 6M6 6l12 12"/>
        </svg>
      </button>
    `;

    // Click on item selects session
    item.addEventListener('click', (e) => {
      if (e.target.closest('button')) return;
      selectSession(s.id);
    });

    // Delete button
    const deleteBtn = item.querySelector('button');
    if (deleteBtn) {
      deleteBtn.addEventListener('click', (e) => removeSessionRecord(s.id, e));
    }

    sessionHistoryList.appendChild(item);
  });
}

function selectSession(targetId) {
  if (targetId === sessionId) return;
  sessionId = targetId;
  sessionStorage.setItem('resolvex_session_id', sessionId);
  sessionBadge.textContent = sessionId;

  closeMobileSidebar();
  clearMessagesCanvas();
  renderSessionHistory();

  if (socket) {
    socket.close();
  }
  connectWebSocket();
}

// -----------------------------------------------------------------------------
// 4. WebSocket Lifecycle Management
// -----------------------------------------------------------------------------

function getWebSocketUrl() {
  const host = window.location.host || 'localhost:8000';
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsHost = window.location.protocol === 'file:' ? 'localhost:8000' : host;
  return `${protocol}//${wsHost}/ws/chat/${sessionId}`;
}

function updateConnectionStatus(state) {
  if (state === 'connected') {
    dotIndicator.className = 'relative inline-flex rounded-full h-2 w-2 bg-emerald-500';
    pingIndicator.className = 'animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75';
    statusText.textContent = 'Live Agent Connected';
    statusText.className = 'text-[11px] text-zinc-300 font-medium';
    btnSend.disabled = false;
  } else if (state === 'connecting') {
    dotIndicator.className = 'relative inline-flex rounded-full h-2 w-2 bg-amber-500';
    pingIndicator.className = 'animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75';
    statusText.textContent = 'Connecting...';
    statusText.className = 'text-[11px] text-zinc-400 font-medium';
  } else {
    dotIndicator.className = 'relative inline-flex rounded-full h-2 w-2 bg-rose-500';
    pingIndicator.className = 'hidden';
    statusText.textContent = 'Disconnected (Retrying)';
    statusText.className = 'text-[11px] text-rose-400 font-medium';
    btnSend.disabled = true;
  }
}

function connectWebSocket() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return;
  }

  updateConnectionStatus('connecting');
  const wsUrl = getWebSocketUrl();
  console.log(`[ResolveX] Connecting to WebSocket: ${wsUrl}`);

  socket = new WebSocket(wsUrl);

  socket.onopen = () => {
    console.log('[ResolveX] WebSocket connection live.');
    updateConnectionStatus('connected');
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  socket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handleServerEvent(data);
    } catch (err) {
      console.error('[ResolveX] Failed to parse WebSocket frame:', err, event.data);
    }
  };

  socket.onclose = () => {
    console.warn('[ResolveX] WebSocket closed. Scheduling reconnection...');
    updateConnectionStatus('disconnected');
    socket = null;
    if (!reconnectTimer) {
      reconnectTimer = setTimeout(connectWebSocket, 3000);
    }
  };

  socket.onerror = (err) => {
    console.error('[ResolveX] WebSocket error:', err);
    updateConnectionStatus('disconnected');
  };
}

// -----------------------------------------------------------------------------
// 5. Message Rendering (ChatGPT / Gemini Minimalist Style)
// -----------------------------------------------------------------------------

function scrollToBottom() {
  chatScrollContainer.scrollTop = chatScrollContainer.scrollHeight;
}

function hideHeroState() {
  if (heroState && !heroState.classList.contains('hidden')) {
    heroState.classList.add('hidden');
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function appendUserMessage(text) {
  hideHeroState();

  const row = document.createElement('div');
  row.className = 'flex justify-end pt-2';

  const pill = document.createElement('div');
  pill.className = 'max-w-[85%] sm:max-w-xl bg-[#2f2f2f] text-zinc-100 px-4 py-2.5 rounded-3xl text-[15px] leading-relaxed select-text shadow-xs';
  pill.textContent = text;

  row.appendChild(pill);
  messagesList.appendChild(row);
  scrollToBottom();

  if (isFirstMessageInSession) {
    saveSessionRecord(sessionId, text.length > 28 ? text.slice(0, 28) + '...' : text);
    isFirstMessageInSession = false;
  }
}

function startAssistantMessage() {
  hideHeroState();

  const row = document.createElement('div');
  row.className = 'flex items-start gap-3.5 pt-1';

  // Minimal spark/avatar icon (Gemini/ChatGPT style)
  const avatar = document.createElement('div');
  avatar.className = 'h-7 w-7 rounded-full bg-[#2a2a2a] border border-[#383838] flex items-center justify-center text-indigo-400 shrink-0 mt-0.5';
  avatar.innerHTML = `
    <svg class="w-3.5 h-3.5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
    </svg>
  `;

  // Content body directly on the clean canvas
  const body = document.createElement('div');
  body.className = 'flex-1 text-[15px] text-zinc-200 leading-relaxed space-y-2 min-w-0';

  const textSpan = document.createElement('div');
  textSpan.className = 'streaming-cursor whitespace-pre-wrap leading-relaxed select-text';

  body.appendChild(textSpan);
  row.appendChild(avatar);
  row.appendChild(body);
  messagesList.appendChild(row);
  scrollToBottom();

  currentAssistantContainer = body;
  currentAssistantTextSpan = textSpan;
}

// -----------------------------------------------------------------------------
// 6. WebSocket Server Event Protocol Handling
// -----------------------------------------------------------------------------

function handleServerEvent(payload) {
  const event = payload.event;

  if (event === 'start') {
    lifecycleBanner.classList.remove('hidden');
    lifecycleStep.textContent = 'INIT';
    lifecycleText.textContent = 'Analyzing request with LangGraph...';
    startAssistantMessage();
  } else if (event === 'routing') {
    lifecycleBanner.classList.remove('hidden');
    lifecycleStep.textContent = 'ROUTING';
    lifecycleText.textContent = payload.status || 'Classifying query intent...';
  } else if (event === 'retrieval') {
    lifecycleBanner.classList.remove('hidden');
    lifecycleStep.textContent = 'RAG';
    lifecycleText.textContent = `Retrieved ${payload.chunks_count} grounded policy passages`;
  } else if (event === 'token') {
    if (currentAssistantTextSpan) {
      currentAssistantTextSpan.textContent += payload.delta;
      scrollToBottom();
    }
  } else if (event === 'done') {
    lifecycleBanner.classList.add('hidden');

    if (currentAssistantTextSpan) {
      currentAssistantTextSpan.classList.remove('streaming-cursor');
      currentAssistantTextSpan.textContent = payload.response;
    }

    if (currentAssistantContainer) {
      // 1. Sleek Intent Badge
      if (payload.intent) {
        const metaRow = document.createElement('div');
        metaRow.className = 'flex flex-wrap items-center gap-2 pt-2';

        const intentBadge = document.createElement('span');
        intentBadge.className = 'inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-mono bg-[#262626] border border-[#333] text-zinc-400';
        intentBadge.innerHTML = `<span class="h-1.5 w-1.5 rounded-full ${getIntentDotColor(payload.intent)}"></span>${payload.intent}`;
        metaRow.appendChild(intentBadge);

        // 2. Citation Chips
        if (payload.citations && payload.citations.length > 0) {
          payload.citations.forEach((c) => {
            const chip = document.createElement('span');
            chip.className = 'px-2 py-0.5 rounded bg-[#242424] border border-[#333] text-zinc-400 text-[11px] font-mono hover:text-zinc-200 transition cursor-default';
            chip.textContent = c;
            metaRow.appendChild(chip);
          });
        }

        currentAssistantContainer.appendChild(metaRow);
      }

      // 3. Human Escalation Notice if flagged
      if (payload.is_escalated) {
        const escAlert = document.createElement('div');
        escAlert.className = 'mt-2 px-3 py-1.5 rounded-lg bg-rose-950/30 border border-rose-900/40 text-rose-300 text-xs flex items-center gap-2';
        escAlert.innerHTML = `
          <svg class="w-4 h-4 text-rose-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
          </svg>
          <span>Routed to Human Specialist Support</span>
        `;
        currentAssistantContainer.appendChild(escAlert);
      }
    }

    currentAssistantContainer = null;
    currentAssistantTextSpan = null;
    btnSend.disabled = false;
    scrollToBottom();
  } else if (event === 'error') {
    lifecycleBanner.classList.add('hidden');
    if (currentAssistantTextSpan) {
      currentAssistantTextSpan.classList.remove('streaming-cursor');
      currentAssistantTextSpan.innerHTML = `<span class="text-rose-400 text-sm">⚠️ ${payload.message}</span>`;
    }
    btnSend.disabled = false;
    scrollToBottom();
  }
}

function getIntentDotColor(intent) {
  switch (intent) {
    case 'POLICY_INQUIRY':
      return 'bg-blue-400';
    case 'DATABASE_LOOKUP':
      return 'bg-emerald-400';
    case 'ACTION_EXECUTION':
      return 'bg-amber-400';
    case 'TECHNICAL_SUPPORT':
      return 'bg-purple-400';
    case 'GENERAL_ESCALATION':
      return 'bg-rose-400';
    default:
      return 'bg-zinc-400';
  }
}

// -----------------------------------------------------------------------------
// 7. Input Dispatching & User Actions
// -----------------------------------------------------------------------------

function sendMessage(queryText) {
  const query = queryText.trim();
  if (!query) return;

  if (!socket || socket.readyState !== WebSocket.OPEN) {
    alert('WebSocket connection is not ready. Reconnecting, please wait...');
    connectWebSocket();
    return;
  }

  appendUserMessage(query);
  chatInput.value = '';
  chatInput.style.height = 'auto';
  btnSend.disabled = true;

  // Dispatch JSON frame matching backend contract
  socket.send(JSON.stringify({ query: query }));
}

chatForm.addEventListener('submit', (e) => {
  e.preventDefault();
  sendMessage(chatInput.value);
});

// Auto-expand textarea & Enter-to-send (Shift+Enter for newline)
chatInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage(chatInput.value);
  }
});

chatInput.addEventListener('input', () => {
  chatInput.style.height = 'auto';
  chatInput.style.height = Math.min(chatInput.scrollHeight, 144) + 'px';
});

// Quick suggestion prompt pills
document.querySelectorAll('.quick-pill').forEach((pill) => {
  pill.addEventListener('click', () => {
    const subtitle = pill.querySelector('.truncate');
    const textToSend = subtitle ? subtitle.textContent.trim() : pill.textContent.trim();
    sendMessage(textToSend);
  });
});

// Start New Chat
function startNewChat() {
  sessionId = generateSessionId();
  sessionStorage.setItem('resolvex_session_id', sessionId);
  sessionBadge.textContent = sessionId;
  isFirstMessageInSession = true;

  clearMessagesCanvas();
  renderSessionHistory();

  if (socket) {
    socket.close();
  }
  connectWebSocket();
}

function clearMessagesCanvas() {
  messagesList.innerHTML = '';
  if (heroState) {
    heroState.classList.remove('hidden');
  }
  lifecycleBanner.classList.add('hidden');
}

btnNewChat.addEventListener('click', startNewChat);
btnClearChat.addEventListener('click', clearMessagesCanvas);

// Keyboard shortcut: Cmd/Ctrl + N for new chat
window.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'n') {
    e.preventDefault();
    startNewChat();
  }
});

// -----------------------------------------------------------------------------
// 8. Mobile Sidebar Controls
// -----------------------------------------------------------------------------

function openMobileSidebar() {
  sidebar.classList.remove('-translate-x-full');
  mobileBackdrop.classList.remove('hidden');
}

function closeMobileSidebar() {
  sidebar.classList.add('-translate-x-full');
  mobileBackdrop.classList.add('hidden');
}

if (btnOpenSidebar) btnOpenSidebar.addEventListener('click', openMobileSidebar);
if (btnCloseSidebar) btnCloseSidebar.addEventListener('click', closeMobileSidebar);
if (mobileBackdrop) mobileBackdrop.addEventListener('click', closeMobileSidebar);

// -----------------------------------------------------------------------------
// 9. Initial Setup on Page Load
// -----------------------------------------------------------------------------

saveSessionRecord(sessionId, 'Current Chat');
renderSessionHistory();
connectWebSocket();
