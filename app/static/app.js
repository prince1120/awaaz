// Awaaz — Modern Minimalist Voice AI Roundtable Client (Editorial Cream Theme, Zero Emojis)

const ROOM_DATA = {
  office: {
    id: 'office',
    title: 'Office Roundtable',
    desc: 'Sprint planning and technical feasibility with Rohan and Dev.',
    agenda: 'Sprint Review: Finalizing Q4 Voice AI architecture, API latency, and delivery deadline.',
    participants: [
      { id: 'manager', name: 'Rohan', role: 'Operations & Sprints', tag: 'MGR', color: '#78350f', desc: 'Timelines, resources & delivery risks' },
      { id: 'tech_lead', name: 'Dev', role: 'Lead Architect', tag: 'TECH', color: '#1e293b', desc: 'System design, scale & latency trade-offs' }
    ],
    chips: [
      'Manager, what is our release timeline?',
      'Dev, how do we architect low-latency voice streaming?',
      'Manager and Dev, what do both of you think of this proposal?',
      'Can we deliver this by Friday?'
    ]
  },
  chill: {
    id: 'chill',
    title: 'Chill Lounge',
    desc: 'Casual conversation, funny banter, and creative ideas with Sunny and Shiro.',
    agenda: 'Weekend Hangout: Planning a road trip, sharing hilarious stories, and brainstorming fun ideas.',
    participants: [
      { id: 'friend', name: 'Sunny', role: 'Close Friend', tag: 'SUNNY', color: '#0369a1', desc: 'Humor, jokes & creative banter' },
      { id: 'saheli', name: 'Shiro', role: 'Close Friend', tag: 'SHIRO', color: '#9d174d', desc: 'Warm, witty Hindi/Hinglish friend' }
    ],
    chips: [
      'Sunny, roast my startup idea.',
      'Shiro, what should we do this weekend?',
      'Both of you, tell me something interesting.',
      'Suggest a crazy name for our next adventure.'
    ]
  },
  family: {
    id: 'family',
    title: 'Family Living Room',
    desc: 'Parental care, health, wisdom, and grounded guidance with Mom and Dad.',
    agenda: 'Family Roundtable: Career decisions, maintaining good health, work-life balance, and peace of mind.',
    participants: [
      { id: 'mom', name: 'Mom (Shalini)', role: 'Mother', tag: 'MOM', color: '#9f1239', desc: 'Care, health, food & emotional support' },
      { id: 'dad', name: 'Dad (Mahesh)', role: 'Father', tag: 'DAD', color: '#166534', desc: 'Wisdom, discipline & career advice' }
    ],
    chips: [
      'Mom, I am feeling a bit stressed with work today.',
      'Dad, should I take a stable path or try a risky venture?',
      'Mom and Dad, what do you both think I should do?',
      'Mummy, aaj khane mein kya ban raha hai?'
    ]
  }
};

const state = {
  sessionId: `awaaz_${Date.now()}`,
  currentRoom: 'office',
  userName: 'Ken',
  isConnected: false,
  isMuted: false,
  audioContext: null,
  mediaStream: null,
  scriptProcessor: null,
  pcmBuffers: [],
  preRollBuffers: [],
  maxPreRoll: 3,
  speechStartTime: 0,
  silenceTimer: null,
  volumeThreshold: 0.013,
  silenceDurationMs: 1100,
  bargeInFrames: 0,
  voiceFrames: 0,
  ws: null,
  isPlayingQueue: false,
  scheduledSources: [],
  nextAudioTime: 0,
  playbackEndTimer: null,
  activeSpeakerId: null,
  turnCount: 0,
  currentTurnBubble: null,
  currentTurnSpeakerId: null,
  pendingPrompts: [],
  speakerTimers: [],
};

const els = {};

function initElements() {
  els.callBtn = document.getElementById('callBtn');
  els.callBtnLabel = document.getElementById('callBtnLabel');
  els.muteBtn = document.getElementById('muteBtn');
  els.muteLabel = document.getElementById('muteLabel');
  els.liveStatus = document.getElementById('liveStatus');
  els.liveStatusLabel = document.getElementById('liveStatusLabel');
  els.navRoomLabel = document.getElementById('navRoomLabel');
  els.transcriptViewport = document.getElementById('transcriptViewport');
  els.emptyTranscript = document.getElementById('emptyTranscript');
  els.textInput = document.getElementById('textInput');
  els.participantsGrid = document.getElementById('participantsGrid');
  els.promptsChips = document.getElementById('promptsChips');
  els.agendaDisplay = document.getElementById('agendaDisplay');
  els.agendaInput = document.getElementById('agendaInput');
  els.agendaEditWrap = document.getElementById('agendaEditWrap');
  els.agendaEditToggle = document.getElementById('agendaEditToggle');
}

document.addEventListener('DOMContentLoaded', () => {
  initElements();
  renderRoomUI('office');

  // Pre-warm Web Audio context on user's first touch/click
  const unlockAudio = () => {
    getAudioContext();
    window.removeEventListener('click', unlockAudio);
    window.removeEventListener('keydown', unlockAudio);
    window.removeEventListener('touchstart', unlockAudio);
  };
  window.addEventListener('click', unlockAudio);
  window.addEventListener('keydown', unlockAudio);
  window.addEventListener('touchstart', unlockAudio);

  // Background server pre-warm
  fetch('/api/prewarm', { method: 'POST' }).catch(() => {});
});

function getAudioContext() {
  if (!state.audioContext) {
    state.audioContext = new (window.AudioContext || window.webkitAudioContext)();
  }
  if (state.audioContext.state === 'suspended') {
    state.audioContext.resume();
  }
  return state.audioContext;
}

function switchRoom(roomId) {
  if (!ROOM_DATA[roomId]) return;
  state.currentRoom = roomId;

  document.querySelectorAll('.nav-room-btn').forEach(btn => {
    if (btn.dataset.room === roomId) btn.classList.add('active');
    else btn.classList.remove('active');
  });

  renderRoomUI(roomId);

  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify({
      type: 'set_room',
      room_id: roomId,
    }));
  }
}

function renderRoomUI(roomId) {
  const room = ROOM_DATA[roomId];
  if (els.navRoomLabel) els.navRoomLabel.textContent = room.title;
  if (els.agendaDisplay) els.agendaDisplay.textContent = room.agenda;
  if (els.agendaInput) els.agendaInput.value = room.agenda;

  const roleConfigs = {
    office: { tag: 'BOSS', role: 'Founder & Boss', desc: 'Rohan and Kalpit report directly to you.' },
    chill: { tag: 'FRND', role: 'Close Friend', desc: 'Hanging out and bantering with Sunny & Shiro.' },
    family: { tag: 'SON', role: 'Son / Child', desc: 'Loving care, guidance and wisdom from Mom & Dad.' }
  };
  const userConfig = roleConfigs[roomId] || { tag: 'USER', role: 'Speaker', desc: 'Speak naturally.' };

  const userNavRole = document.getElementById('userNavRole');
  if (userNavRole) userNavRole.textContent = userConfig.tag;
  const userNameNav = document.getElementById('userNameNav');
  if (userNameNav) userNameNav.textContent = state.userName;
  const userAvatarLetter = document.getElementById('userAvatarLetter');
  if (userAvatarLetter) userAvatarLetter.textContent = (state.userName || 'K').charAt(0).toUpperCase();

  if (els.participantsGrid) {
    const userInitial = (state.userName || 'K').charAt(0).toUpperCase();
    const userCard = `
      <div class="stage-card user-card" id="card_user">
        <div class="card-header-row">
          <div class="avatar-badge-wrap">
            <div class="seat-avatar" style="background:#191512;">${userInitial}</div>
            <span class="seat-monogram">${userConfig.tag}</span>
          </div>
          <div class="seat-live-indicator" id="ind_user">
            <div class="equalizer-wave">
              <span class="wave-bar"></span>
              <span class="wave-bar"></span>
              <span class="wave-bar"></span>
            </div>
            <span class="ind-label">You</span>
          </div>
        </div>
        <div class="card-body-content">
          <div class="card-seat-name">${escapeHtml(state.userName)} (You)</div>
          <div class="card-seat-role">${userConfig.role}</div>
          <p class="card-seat-desc">${userConfig.desc}</p>
        </div>
      </div>
    `;

    const members = room.participants.map(p => {
      const avatarInitial = p.name.charAt(0).toUpperCase();
      const avatarColor = p.color || '#44403c';
      return `
        <div class="stage-card" id="card_${p.id}">
          <div class="card-header-row">
            <div class="avatar-badge-wrap">
              <div class="seat-avatar" style="background:${avatarColor};">${avatarInitial}</div>
              <span class="seat-monogram">${p.tag}</span>
            </div>
            <div class="seat-live-indicator" id="ind_${p.id}">
              <div class="equalizer-wave">
                <span class="wave-bar"></span>
                <span class="wave-bar"></span>
                <span class="wave-bar"></span>
              </div>
              <span class="ind-label">Seat</span>
            </div>
          </div>
          <div class="card-body-content">
            <div class="card-seat-name">${p.name}</div>
            <div class="card-seat-role">${p.role}</div>
            <p class="card-seat-desc">${p.desc}</p>
          </div>
        </div>
      `;
    }).join('');

    els.participantsGrid.innerHTML = userCard + members;
  }

  if (els.promptsChips) {
    els.promptsChips.innerHTML = room.chips.map(chip => `
      <button class="chip-btn" onclick="sendPrompt('${escapeQuotes(chip)}')">${chip}</button>
    `).join('');
  }
}

function openNameEdit() {
  const displayBox = document.getElementById('userNameDisplayBox');
  const inputBox = document.getElementById('userNameInputBox');
  const input = document.getElementById('userNameInput');
  if (displayBox && inputBox && input) {
    input.value = state.userName;
    displayBox.classList.add('hidden');
    inputBox.classList.remove('hidden');
    input.focus();
    input.select();
  }
}

function closeNameEdit() {
  const displayBox = document.getElementById('userNameDisplayBox');
  const inputBox = document.getElementById('userNameInputBox');
  if (displayBox && inputBox) {
    inputBox.classList.add('hidden');
    displayBox.classList.remove('hidden');
  }
}

function saveUserName() {
  const input = document.getElementById('userNameInput');
  if (!input) return;
  const newName = input.value.trim();
  if (newName) {
    state.userName = newName;
    const userNameNav = document.getElementById('userNameNav');
    if (userNameNav) userNameNav.textContent = state.userName;
    const userAvatarLetter = document.getElementById('userAvatarLetter');
    if (userAvatarLetter) userAvatarLetter.textContent = state.userName.charAt(0).toUpperCase();
    renderRoomUI(state.currentRoom);
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify({
        type: 'set_user_name',
        user_name: state.userName,
      }));
    }
  }
  closeNameEdit();
}

function handleNameInputKey(event) {
  if (event.key === 'Enter') {
    event.preventDefault();
    saveUserName();
  } else if (event.key === 'Escape') {
    closeNameEdit();
  }
}

function toggleEditAgenda() {
  if (!els.agendaEditWrap) return;
  const isHidden = els.agendaEditWrap.classList.contains('hidden');
  if (isHidden) {
    els.agendaEditWrap.classList.remove('hidden');
    els.agendaDisplay.classList.add('hidden');
    els.agendaEditToggle.classList.add('hidden');
    els.agendaInput.focus();
  } else {
    els.agendaEditWrap.classList.add('hidden');
    els.agendaDisplay.classList.remove('hidden');
    els.agendaEditToggle.classList.remove('hidden');
  }
}

function saveAgenda() {
  const newAgenda = els.agendaInput.value.trim();
  if (newAgenda) {
    ROOM_DATA[state.currentRoom].agenda = newAgenda;
    els.agendaDisplay.textContent = newAgenda;
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify({
        type: 'set_agenda',
        room_id: state.currentRoom,
        agenda: newAgenda,
      }));
    }
  }
  toggleEditAgenda();
}

function escapeQuotes(str) {
  return str.replace(/'/g, "\\'");
}

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

async function toggleVoiceCall() {
  initElements();
  getAudioContext();

  if (state.isConnected) {
    leaveDiscussion();
  } else {
    await joinDiscussion();
  }
}

async function joinDiscussion() {
  initElements();
  updateStatus('Connecting...', true);

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/voice?session_id=${state.sessionId}`;

  try {
    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = async () => {
      state.isConnected = true;
      updateStatus('Connected', true);
      els.callBtn.classList.add('in-call');
      els.callBtnLabel.textContent = 'End Discussion';
      els.muteBtn.classList.remove('hidden');

      state.ws.send(JSON.stringify({
        type: 'set_room',
        room_id: state.currentRoom,
      }));

      state.ws.send(JSON.stringify({
        type: 'set_user_name',
        user_name: state.userName,
      }));

      const currentAgenda = ROOM_DATA[state.currentRoom].agenda;
      if (currentAgenda) {
        state.ws.send(JSON.stringify({
          type: 'set_agenda',
          room_id: state.currentRoom,
          agenda: currentAgenda,
        }));
      }

      await startMicCapture();

      // Flush any queued prompts sent while connecting
      if (state.pendingPrompts && state.pendingPrompts.length > 0) {
        while (state.pendingPrompts.length > 0) {
          const queued = state.pendingPrompts.shift();
          transmitText(queued);
        }
      }
    };

    state.ws.onmessage = async (evt) => {
      const data = JSON.parse(evt.data);
      handleServerEvent(data);
    };

    state.ws.onclose = () => { leaveDiscussion(); };
    state.ws.onerror = (err) => {
      console.error('WebSocket error:', err);
      updateStatus('Error', false);
    };
  } catch (err) {
    console.error('Join error:', err);
    updateStatus('Failed', false);
  }
}

function leaveDiscussion() {
  state.isConnected = false;
  stopMicCapture();
  stopAudioQueue();

  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.close();
  }

  clearActiveSpeaker();
  updateStatus('Ready', false);
  if (els.callBtn) {
    els.callBtn.classList.remove('in-call');
    els.callBtnLabel.textContent = 'Start Discussion';
  }
  if (els.muteBtn) els.muteBtn.classList.add('hidden');
}

function handleServerEvent(msg) {
  switch (msg.type) {
    case 'room_changed':
      if (msg.agenda && els.agendaDisplay) {
        els.agendaDisplay.textContent = msg.agenda;
        if (els.agendaInput) els.agendaInput.value = msg.agenda;
      }
      break;

    case 'agenda_updated':
      if (msg.agenda && els.agendaDisplay) {
        els.agendaDisplay.textContent = msg.agenda;
        if (els.agendaInput) els.agendaInput.value = msg.agenda;
      }
      break;

    case 'turn_plan':
      if (msg.speakers && msg.speakers.length > 1) {
        const room = ROOM_DATA[state.currentRoom];
        const names = msg.speakers.map(pid => {
          const p = room ? room.participants.find(x => x.id === pid) : null;
          return p ? p.name : pid;
        });
        if (msg.peer_referral) {
          updateStatus(`${names[0]} invited ${names[1]}`, true);
        } else {
          updateStatus(`Order: ${names.join(' → ')}`, true);
        }
      }
      break;

    case 'latency_stats':
      if (msg.ttfa_ms) {
        updateStatus(`Live · TTFA ${msg.ttfa_ms}ms`, true);
      }
      break;

    case 'agent_speech':
      appendTranscriptBubble({
        speakerId: msg.speaker_id,
        speakerName: msg.speaker_name,
        role: msg.role,
        text: msg.text,
        isUser: false,
      });

      if (msg.audio_base64) {
        queueAudio({
          audioBase64: msg.audio_base64,
          speakerId: msg.speaker_id,
        });
      }
      break;

    case 'agent_done':
      state.currentTurnBubble = null;
      state.currentTurnSpeakerId = null;
      break;

    case 'user_speech':
      if (msg.text && msg.text.trim().length > 0) {
        appendTranscriptBubble({
          speakerId: 'user',
          speakerName: `${state.userName} (You)`,
          role: msg.role || 'Boss',
          text: msg.text,
          isUser: true,
        });
      }
      break;

    case 'interrupted':
      state.currentTurnBubble = null;
      state.currentTurnSpeakerId = null;
      stopAudioQueue();
      clearActiveSpeaker();
      showInterruptedNotice();
      break;

    case 'status':
      if (msg.status === 'listening') {
        updateStatus('Listening', true);
      }
      break;
  }
}

async function startMicCapture() {
  if (state.mediaStream) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      }
    });
    state.mediaStream = stream;

    const ctx = getAudioContext();
    const source = ctx.createMediaStreamSource(stream);
    const processor = ctx.createScriptProcessor(4096, 1, 1);

    processor.onaudioprocess = (e) => {
      if (!state.isConnected || state.isMuted) return;

      const input = e.inputBuffer.getChannelData(0);
      let sum = 0;
      for (let i = 0; i < input.length; i++) sum += input[i] * input[i];
      const rms = Math.sqrt(sum / input.length);

      // When AI agents are speaking through speakers:
      // Prevent speaker audio feedback from self-interrupting while allowing natural human barge-in (> 0.032 RMS sustained for 2 frames ~170ms).
      if (state.isPlayingQueue) {
        if (rms > 0.032) {
          state.bargeInFrames = (state.bargeInFrames || 0) + 1;
          if (state.bargeInFrames >= 2) {
            state.bargeInFrames = 0;
            stopAudioQueue();
            clearActiveSpeaker();
            showInterruptedNotice();
            if (state.ws && state.ws.readyState === WebSocket.OPEN) {
              state.ws.send(JSON.stringify({ type: 'barge_in' }));
            }
            // Transition directly to recording user audio without dropping frame!
          } else {
            return;
          }
        } else {
          state.bargeInFrames = 0;
          return;
        }
      }

      state.bargeInFrames = 0;

      // Maintain rolling pre-roll buffer of incoming frames
      if (!state.preRollBuffers) state.preRollBuffers = [];
      state.preRollBuffers.push(new Float32Array(input));
      if (state.preRollBuffers.length > (state.maxPreRoll || 3)) {
        state.preRollBuffers.shift();
      }

      // Speech recording with calibrated VAD
      if (rms > state.volumeThreshold) {
        state.voiceFrames = (state.voiceFrames || 0) + 1;
        // On speech onset, prepend pre-roll frames so starting syllable is never clipped
        if (state.voiceFrames === 1 && state.pcmBuffers.length === 0) {
          for (let p = 0; p < state.preRollBuffers.length - 1; p++) {
            state.pcmBuffers.push(state.preRollBuffers[p]);
          }
        }
        setActiveSpeaker('user');
        state.pcmBuffers.push(new Float32Array(input));
        if (state.speechStartTime === 0) state.speechStartTime = Date.now();
        if (state.silenceTimer) {
          clearTimeout(state.silenceTimer);
          state.silenceTimer = null;
        }
      } else {
        state.voiceFrames = 0;
        if (state.pcmBuffers.length > 0) {
          if (!state.silenceTimer) {
            state.silenceTimer = setTimeout(() => {
              clearActiveSpeaker();
              flushUserAudio();
            }, state.silenceDurationMs);
          }
        }
      }
    };

    source.connect(processor);
    processor.connect(ctx.destination);
    state.scriptProcessor = processor;
  } catch (err) {
    console.error('Mic error:', err);
    updateStatus('Mic Error', false);
  }
}

function stopMicCapture() {
  if (state.mediaStream) {
    state.mediaStream.getTracks().forEach(t => t.stop());
    state.mediaStream = null;
  }
  if (state.scriptProcessor) {
    state.scriptProcessor.disconnect();
    state.scriptProcessor = null;
  }
  clearActiveSpeaker();
}

function downsampleTo16k(buffer, sampleRate) {
  if (sampleRate === 16000) return buffer;
  const ratio = sampleRate / 16000;
  const newLength = Math.round(buffer.length / ratio);
  const result = new Float32Array(newLength);
  let offsetResult = 0;
  let offsetBuffer = 0;
  while (offsetResult < result.length) {
    const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
    let accum = 0, count = 0;
    for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
      accum += buffer[i];
      count++;
    }
    result[offsetResult] = count > 0 ? accum / count : buffer[offsetBuffer];
    offsetResult++;
    offsetBuffer = nextOffsetBuffer;
  }
  return result;
}

function flushUserAudio() {
  if (state.pcmBuffers.length === 0) return;

  if (state.isPlayingQueue) {
    stopAudioQueue();
    clearActiveSpeaker();
  }

  const totalLen = state.pcmBuffers.reduce((acc, b) => acc + b.length, 0);
  const merged = new Float32Array(totalLen);
  let offset = 0;
  for (const buf of state.pcmBuffers) {
    merged.set(buf, offset);
    offset += buf.length;
  }
  state.pcmBuffers = [];
  state.speechStartTime = 0;
  state.silenceTimer = null;

  const ctx = getAudioContext();
  const inputSampleRate = ctx.sampleRate || 48000;
  const targetSampleRate = 16000;

  // Downsample merged audio to 16kHz for 3x bandwidth savings & optimal Saaras STT
  const downsampled = downsampleTo16k(merged, inputSampleRate);

  const durationSec = downsampled.length / targetSampleRate;
  if (durationSec < 0.25) return;

  const wavBytes = encodeWAV(downsampled, targetSampleRate);
  const b64 = arrayBufferToBase64(wavBytes);

  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify({
      type: 'audio',
      audio_base64: b64,
    }));
  }
}

function encodeWAV(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);

  function writeString(pos, str) {
    for (let i = 0; i < str.length; i++) view.setUint8(pos + i, str.charCodeAt(i));
  }

  writeString(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, 'WAVE');
  writeString(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, 'data');
  view.setUint32(40, samples.length * 2, true);

  let p = 44;
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(p, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    p += 2;
  }
  return buffer;
}

function arrayBufferToBase64(buffer) {
  let binary = '';
  const bytes = new Uint8Array(buffer);
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return window.btoa(binary);
}

async function queueAudio(item) {
  try {
    const ctx = getAudioContext();
    const raw = atob(item.audioBase64);
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);

    const audioBuf = await ctx.decodeAudioData(bytes.buffer);
    scheduleAudioPlayback(audioBuf, item.speakerId);
  } catch (err) {
    console.error('Audio decode error:', err);
  }
}

function scheduleAudioPlayback(audioBuf, speakerId) {
  const ctx = getAudioContext();
  const now = ctx.currentTime;
  state.isPlayingQueue = true;

  // If buffer fell behind or starting fresh, add lead time for smooth continuous stream
  if (!state.nextAudioTime || state.nextAudioTime < now) {
    state.nextAudioTime = now + 0.035;
  }

  const scheduledStart = state.nextAudioTime;
  const src = ctx.createBufferSource();
  src.buffer = audioBuf;
  src.connect(ctx.destination);
  src.start(scheduledStart);
  state.scheduledSources.push(src);

  // Synchronize UI highlight with exact audio playback start
  const delayMs = Math.max(0, (scheduledStart - now) * 1000);
  const speakerTimer = setTimeout(() => {
    setActiveSpeaker(speakerId);
  }, delayMs);
  if (!state.speakerTimers) state.speakerTimers = [];
  state.speakerTimers.push(speakerTimer);

  state.nextAudioTime += audioBuf.duration;

  // Clear speaker animation and active state when final audio chunk finishes
  if (state.playbackEndTimer) clearTimeout(state.playbackEndTimer);
  const remainingMs = Math.max(0, (state.nextAudioTime - now) * 1000);
  state.playbackEndTimer = setTimeout(() => {
    state.isPlayingQueue = false;
    clearActiveSpeaker();
    state.nextAudioTime = 0;
    updateStatus('Listening', true);
  }, remainingMs + 40);
}

function stopAudioQueue() {
  state.isPlayingQueue = false;
  state.nextAudioTime = 0;
  if (state.playbackEndTimer) {
    clearTimeout(state.playbackEndTimer);
    state.playbackEndTimer = null;
  }
  if (state.speakerTimers && state.speakerTimers.length > 0) {
    state.speakerTimers.forEach(t => clearTimeout(t));
    state.speakerTimers = [];
  }
  if (state.scheduledSources && state.scheduledSources.length > 0) {
    state.scheduledSources.forEach(s => {
      try { s.stop(); } catch (e) {}
    });
    state.scheduledSources = [];
  }
}

function setActiveSpeaker(speakerId) {
  clearActiveSpeaker();
  state.activeSpeakerId = speakerId;
  const card = document.getElementById(`card_${speakerId}`);
  if (card) {
    card.classList.add('is-active-speaker');
    const ind = card.querySelector('.seat-live-indicator');
    if (ind) ind.classList.add('speaking');
  }
}

function clearActiveSpeaker() {
  state.activeSpeakerId = null;
  document.querySelectorAll('.stage-card').forEach(c => {
    c.classList.remove('is-active-speaker');
    const ind = c.querySelector('.seat-live-indicator');
    if (ind) ind.classList.remove('speaking');
  });
}

function appendTranscriptBubble({ speakerId, speakerName, role, text, isUser }) {
  if (els.emptyTranscript) els.emptyTranscript.style.display = 'none';

  if (!isUser && state.currentTurnBubble && state.currentTurnSpeakerId === speakerId) {
    const textEl = state.currentTurnBubble.querySelector('.chat-bubble');
    if (textEl) {
      textEl.textContent += ' ' + text;
      if (els.transcriptViewport) {
        els.transcriptViewport.scrollTop = els.transcriptViewport.scrollHeight;
      }
      return;
    }
  }

  state.turnCount++;

  const bubble = document.createElement('div');
  bubble.className = `chat-row ${isUser ? 'user-row' : 'agent-row'}`;
  const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  // Get color if agent
  let pillColor = '#645a4f';
  const room = ROOM_DATA[state.currentRoom];
  if (room) {
    const p = room.participants.find(x => x.id === speakerId);
    if (p && p.color) pillColor = p.color;
  }
  if (isUser) pillColor = '#b45309';

  const rolePill = role ? `<span class="speaker-pill" style="background:${pillColor};">${escapeHtml(role)}</span>` : '';
  bubble.innerHTML = `
    <div class="chat-meta-bar">
      <span>${escapeHtml(speakerName)}</span>
      ${rolePill}
      <span style="color:var(--text-light); font-weight:400; margin-left:auto;">${timeStr}</span>
    </div>
    <div class="chat-bubble">${escapeHtml(text)}</div>
  `;

  if (!isUser) {
    state.currentTurnBubble = bubble;
    state.currentTurnSpeakerId = speakerId;
  } else {
    state.currentTurnBubble = null;
    state.currentTurnSpeakerId = null;
  }

  if (els.transcriptViewport) {
    els.transcriptViewport.appendChild(bubble);
    els.transcriptViewport.scrollTop = els.transcriptViewport.scrollHeight;
  }
}

function showInterruptedNotice() {
  if (els.transcriptViewport) {
    const notice = document.createElement('div');
    notice.className = 'interrupted-badge';
    notice.textContent = 'Interrupted by User';
    els.transcriptViewport.appendChild(notice);
    els.transcriptViewport.scrollTop = els.transcriptViewport.scrollHeight;
  }
}

function sendPrompt(text) {
  if (!text) return;
  if (!state.isConnected) {
    if (!state.pendingPrompts) state.pendingPrompts = [];
    state.pendingPrompts.push(text);
    joinDiscussion();
  } else {
    transmitText(text);
  }
}

function handleTextSubmit(e) {
  e.preventDefault();
  const val = els.textInput.value.trim();
  if (!val) return;
  els.textInput.value = '';
  sendPrompt(val);
}

function transmitText(text) {
  if (state.isPlayingQueue) {
    stopAudioQueue();
    clearActiveSpeaker();
    showInterruptedNotice();
  }
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify({
      type: 'text',
      text: text,
    }));
  }
}

function toggleMute() {
  state.isMuted = !state.isMuted;
  if (state.isMuted) {
    els.muteBtn.classList.add('is-muted');
    els.muteLabel.textContent = 'Unmute';
  } else {
    els.muteBtn.classList.remove('is-muted');
    els.muteLabel.textContent = 'Mute';
  }
}

async function resetRoomMemory() {
  if (confirm('Clear discussion memory for this room?')) {
    try {
      await fetch('/api/reset', { method: 'POST' });
      state.turnCount = 0;
      if (els.transcriptViewport) {
        els.transcriptViewport.innerHTML = `
          <div class="transcript-empty-state" id="emptyTranscript">
            <div class="empty-icon-wrap">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"></path>
                <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
                <line x1="12" y1="19" x2="12" y2="22"></line>
              </svg>
            </div>
            <h3 class="empty-title">Memory Cleared</h3>
            <p class="empty-sub">Start fresh by speaking or picking any topic starter below.</p>
          </div>
        `;
      }
      stopAudioQueue();
      clearActiveSpeaker();
      if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify({ type: 'reset' }));
      }
    } catch (err) {
      console.error('Reset error:', err);
    }
  }
}

function updateStatus(text, isActive) {
  const lbl = document.getElementById('liveStatusLabel');
  if (lbl) lbl.textContent = text;
  const dot = document.querySelector('.live-dot');
  if (dot) {
    if (isActive) dot.classList.add('active');
    else dot.classList.remove('active');
  }
}
