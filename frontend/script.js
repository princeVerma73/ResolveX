/**
 * ResolveX — Frontend WebSocket Chat Client (Step 8)
 * Connects to ws://localhost:8000/ws/chat/{session_id}
 * Handles real-time streaming, token typewriter rendering, and multi-agent lifecycle events.
 */

// -----------------------------------------------------------------------------
// 1. Session & State Management
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

let socket = null;
let currentAssistantMessageDiv = null;
let currentContentSpan = null;
let reconnectTimer = null;

// DOM Elements
const sessionBadge = document.getElementById('session-badge');
const connectionStatus = document.getElementById('connection-status');
const statusText = document.getElementById('status-text');
const dotIndicator = document.getElementById('dot-indicator');
const pingIndicator = document.getElementById('ping-indicator');
const chatMessages = document.getElementById('chat-messages');
const chatForm = document.getElementById('chat-form');
const chatInput = document.getElementById('chat-input');
const btnSend = document.getElementById('btn-send');
const btnNewChat = document.getElementById('btn-new-chat');
const lifecycleBanner = document.getElementById('lifecycle-banner');
const lifecycleText = document.getElementById('lifecycle-text');
const lifecycleStep = document.getElementById('lifecycle-step');

// Display active session ID
sessionBadge.textContent = sessionId;

// -----------------------------------------------------------------------------
// 2. WebSocket Connection Management
// -----------------------------------------------------------------------------

function getWebSocketUrl() {
  const host = window.location.host || 'localhost:8000';
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  // If loaded directly from filesystem (file://), default to localhost:8000
  const wsHost = window.location.protocol === 'file:' ? 'localhost:8000' : host;
  return `${protocol}//${wsHost}/ws/chat/${sessionId}`;
}

function updateConnectionStatus(state) {
  if (state === 'connected') {
    connectionStatus.className = 'flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-300 border border-emerald-500/20';
    dotIndicator.className = 'relative inline-flex rounded-full h-2 w-2 bg-emerald-500';
    pingIndicator.className = 'animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75';
    statusText.textContent = 'Live Agent Connected';
    btnSend.disabled = false;
  } else if (state === 'connecting') {
    connectionStatus.className = 'flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium bg-amber-500/10 text-amber-300 border border-amber-500/20';
    dotIndicator.className = 'relative inline-flex rounded-full h-2 w-2 bg-amber-500';
    pingIndicator.className = 'animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75';
    statusText.textContent = 'Connecting...';
  } else {
    connectionStatus.className = 'flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium bg-rose-500/10 text-rose-300 border border-rose-500/20';
    dotIndicator.className = 'relative inline-flex rounded-full h-2 w-2 bg-rose-500';
    pingIndicator.className = 'hidden';
    statusText.textContent = 'Disconnected (Retrying)';
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
    console.log('[ResolveX] WebSocket connection established.');
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
    console.error('[ResolveX] WebSocket encounter error:', err);
    updateConnectionStatus('disconnected');
  };
}

// -----------------------------------------------------------------------------
// 3. UI Message Rendering & Event Handling
// -----------------------------------------------------------------------------

function scrollToBottom() {
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function appendUserMessage(text) {
  const msgWrapper = document.createElement('div');
  msgWrapper.className = 'flex justify-end';

  const bubble = document.createElement('div');
  bubble.className = 'max-w-xl bg-indigo-600 text-white px-4 py-3 rounded-2xl rounded-tr-sm shadow-md text-sm leading-relaxed';
  bubble.textContent = text;

  msgWrapper.appendChild(bubble);
  chatMessages.appendChild(msgWrapper);
  scrollToBottom();
}

function startAssistantMessage() {
  const msgWrapper = document.createElement('div');
  msgWrapper.className = 'flex items-start gap-3';

  // Agent Avatar
  const avatar = document.createElement('div');
  avatar.className = 'h-8 w-8 rounded-xl bg-slate-800 border border-slate-700 flex items-center justify-center text-indigo-400 shrink-0 shadow-sm';
  avatar.innerHTML = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>`;

  const contentBox = document.createElement('div');
  contentBox.className = 'max-w-2xl bg-slate-900 border border-slate-800/80 px-4 py-3 rounded-2xl rounded-tl-sm text-sm text-slate-200 leading-relaxed shadow-sm flex flex-col gap-2';

  const textSpan = document.createElement('div');
  textSpan.className = 'typing-cursor whitespace-pre-wrap';

  contentBox.appendChild(textSpan);
  msgWrapper.appendChild(avatar);
  msgWrapper.appendChild(contentBox);
  chatMessages.appendChild(msgWrapper);
  scrollToBottom();

  currentAssistantMessageDiv = contentBox;
  currentContentSpan = textSpan;
}

function handleServerEvent(payload) {
  const event = payload.event;

  if (event === 'start') {
    lifecycleBanner.classList.remove('hidden');
    lifecycleStep.textContent = 'INITIATED';
    lifecycleText.textContent = `Processing query...`;
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
    if (currentContentSpan) {
      currentContentSpan.textContent += payload.delta;
      scrollToBottom();
    }
  } else if (event === 'done') {
    lifecycleBanner.classList.add('hidden');

    if (currentContentSpan) {
      currentContentSpan.classList.remove('typing-cursor');
      currentContentSpan.textContent = payload.response;
    }

    if (currentAssistantMessageDiv) {
      // 1. Add Intent Badge
      if (payload.intent) {
        const badge = document.createElement('div');
        const colorClass = getIntentBadgeStyle(payload.intent);
        badge.className = `inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-semibold tracking-wider uppercase border w-max ${colorClass}`;
        badge.textContent = `Intent: ${payload.intent}`;
        currentAssistantMessageDiv.appendChild(badge);
      }

      // 2. Add Grounded Citation Chips
      if (payload.citations && payload.citations.length > 0) {
        const citationsDiv = document.createElement('div');
        citationsDiv.className = 'flex flex-wrap gap-1.5 pt-1 text-[11px] text-slate-400 items-center';
        citationsDiv.innerHTML = '<span class="font-medium text-slate-500">Sources:</span>';
        payload.citations.forEach((c) => {
          const chip = document.createElement('span');
          chip.className = 'px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-indigo-300 font-mono';
          chip.textContent = c;
          citationsDiv.appendChild(chip);
        });
        currentAssistantMessageDiv.appendChild(citationsDiv);
      }

      // 3. Add Escalation Notice if flagged
      if (payload.is_escalated) {
        const escAlert = document.createElement('div');
        escAlert.className = 'mt-1 px-3 py-1.5 rounded-lg bg-rose-950/40 border border-rose-800/40 text-rose-300 text-xs flex items-center gap-2';
        escAlert.innerHTML = `
          <svg class="w-4 h-4 text-rose-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
          </svg>
          <span>Routed to Human Specialist Support</span>
        `;
        currentAssistantMessageDiv.appendChild(escAlert);
      }
    }

    currentAssistantMessageDiv = null;
    currentContentSpan = null;
    btnSend.disabled = false;
    scrollToBottom();
  } else if (event === 'error') {
    lifecycleBanner.classList.add('hidden');
    if (currentContentSpan) {
      currentContentSpan.classList.remove('typing-cursor');
      currentContentSpan.innerHTML = `<span class="text-rose-400">⚠️ ${payload.message}</span>`;
    }
    btnSend.disabled = false;
    scrollToBottom();
  }
}

function getIntentBadgeStyle(intent) {
  switch (intent) {
    case 'POLICY_INQUIRY':
      return 'bg-blue-500/10 text-blue-400 border-blue-500/20';
    case 'DATABASE_LOOKUP':
      return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20';
    case 'ACTION_EXECUTION':
      return 'bg-amber-500/10 text-amber-400 border-amber-500/20';
    case 'TECHNICAL_SUPPORT':
      return 'bg-purple-500/10 text-purple-400 border-purple-500/20';
    case 'GENERAL_ESCALATION':
      return 'bg-rose-500/10 text-rose-400 border-rose-500/20';
    default:
      return 'bg-slate-700 text-slate-300 border-slate-600';
  }
}

// -----------------------------------------------------------------------------
// 4. Input & User Interactions
// -----------------------------------------------------------------------------

function sendMessage(queryText) {
  const query = queryText.trim();
  if (!query) return;

  if (!socket || socket.readyState !== WebSocket.OPEN) {
    alert('WebSocket connection is not ready. Please wait a moment while it reconnects.');
    return;
  }

  appendUserMessage(query);
  chatInput.value = '';
  chatInput.style.height = 'auto';
  btnSend.disabled = true;

  // Send JSON frame to backend
  socket.send(JSON.stringify({ query: query }));
}

chatForm.addEventListener('submit', (e) => {
  e.preventDefault();
  sendMessage(chatInput.value);
});

// Auto-expand textarea & handle Enter key
chatInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage(chatInput.value);
  }
});

chatInput.addEventListener('input', () => {
  chatInput.style.height = 'auto';
  chatInput.style.height = Math.min(chatInput.scrollHeight, 128) + 'px';
});

// Quick suggestion prompt pills
document.querySelectorAll('.quick-pill').forEach((pill) => {
  pill.addEventListener('click', () => {
    // Strip leading emoji icon if present
    const cleanText = pill.textContent.replace(/^[\s\S]{1,3}\s/, '').trim();
    sendMessage(cleanText);
  });
});

// New Session Button
btnNewChat.addEventListener('click', () => {
  sessionId = generateSessionId();
  sessionStorage.setItem('resolvex_session_id', sessionId);
  sessionBadge.textContent = sessionId;

  if (socket) {
    socket.close();
  }

  // Clear existing messages except welcome hero
  const hero = chatMessages.firstElementChild;
  chatMessages.innerHTML = '';
  if (hero) chatMessages.appendChild(hero);

  connectWebSocket();
});

// -----------------------------------------------------------------------------
// 5. Initialize on Page Load
// -----------------------------------------------------------------------------
connectWebSocket();
