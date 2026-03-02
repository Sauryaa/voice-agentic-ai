const SILENCE_TIMEOUT_MS = 3000;
const MIN_RECORDING_MS = 1200;
const SILENCE_THRESHOLD = 0.018;

const elements = {
  enableMicBtn: document.getElementById("enableMicBtn"),
  micStatus: document.getElementById("micStatus"),
  modeSelect: document.getElementById("modeSelect"),
  startBtn: document.getElementById("startBtn"),
  recordBtn: document.getElementById("recordBtn"),
  nextBtn: document.getElementById("nextBtn"),
  downloadBtn: document.getElementById("downloadBtn"),
  resetBtn: document.getElementById("resetBtn"),
  sessionId: document.getElementById("sessionId"),
  sessionStatus: document.getElementById("sessionStatus"),
  backendStatus: document.getElementById("backendStatus"),
  currentPrompt: document.getElementById("currentPrompt"),
  transcript: document.getElementById("transcript"),
  audioMeter: document.getElementById("audioMeter"),
};

const state = {
  sessionId: null,
  mode: "user_controlled",
  status: "idle",
  stream: null,
  audioContext: null,
  analyser: null,
  sourceNode: null,
  meterRafId: null,
  silenceRafId: null,
  recorder: null,
  recordingPromise: null,
  isRecording: false,
  stopOnSilence: false,
  recordStartedAt: 0,
  lastVoiceDetectedAt: 0,
  agentLoopRunning: false,
  abortAgentLoop: false,
  meterBars: [],
};

init();

function init() {
  buildMeterBars(16);
  bindEvents();
  syncButtons();
  checkBackendHealth();
}

function bindEvents() {
  elements.enableMicBtn.addEventListener("click", async () => {
    try {
      await ensureMicrophone();
      setMicStatus("Microphone ready", true);
    } catch (error) {
      setMicStatus(`Microphone error: ${error.message}`, false);
    }
  });

  elements.modeSelect.addEventListener("change", () => {
    state.mode = elements.modeSelect.value;
    syncButtons();
  });

  elements.startBtn.addEventListener("click", async () => {
    try {
      await startInterview();
    } catch (error) {
      setCurrentPrompt(`Start failed: ${error.message}`);
    }
  });

  elements.recordBtn.addEventListener("click", async () => {
    try {
      await handleUserControlledRecordToggle();
    } catch (error) {
      setCurrentPrompt(`Recording failed: ${error.message}`);
    }
  });

  elements.nextBtn.addEventListener("click", async () => {
    try {
      await forceNextQuestion();
    } catch (error) {
      setCurrentPrompt(`Could not move to next question: ${error.message}`);
    }
  });

  elements.downloadBtn.addEventListener("click", async () => {
    try {
      await downloadSessionJson();
    } catch (error) {
      setCurrentPrompt(`Download failed: ${error.message}`);
    }
  });

  elements.resetBtn.addEventListener("click", async () => {
    await resetSession();
  });
}

async function checkBackendHealth() {
  try {
    const payload = await apiJson("/health", { method: "GET" });
    if (payload.status === "ok") {
      elements.backendStatus.textContent = "healthy";
      return;
    }
    elements.backendStatus.textContent = "unhealthy";
  } catch (_error) {
    elements.backendStatus.textContent = "unreachable";
  }
}

function buildMeterBars(count) {
  elements.audioMeter.innerHTML = "";
  state.meterBars = [];
  for (let i = 0; i < count; i += 1) {
    const bar = document.createElement("div");
    bar.className = "meter-bar";
    bar.style.height = "10%";
    elements.audioMeter.appendChild(bar);
    state.meterBars.push(bar);
  }
}

async function ensureMicrophone() {
  if (state.stream) {
    return state.stream;
  }

  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error("Browser does not support microphone APIs.");
  }

  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  });

  state.stream = stream;
  initAudioGraph(stream);
  return stream;
}

function initAudioGraph(stream) {
  if (!state.audioContext) {
    state.audioContext = new (window.AudioContext || window.webkitAudioContext)();
  }

  if (state.sourceNode) {
    state.sourceNode.disconnect();
    state.sourceNode = null;
  }

  state.analyser = state.audioContext.createAnalyser();
  state.analyser.fftSize = 512;
  state.sourceNode = state.audioContext.createMediaStreamSource(stream);
  state.sourceNode.connect(state.analyser);

  startMeterAnimation();
}

function startMeterAnimation() {
  if (state.meterRafId) {
    cancelAnimationFrame(state.meterRafId);
    state.meterRafId = null;
  }

  const samples = new Uint8Array(state.analyser ? state.analyser.fftSize : 512);

  const animate = () => {
    let level = 0;

    if (state.analyser) {
      state.analyser.getByteTimeDomainData(samples);
      let sumSquares = 0;
      for (let i = 0; i < samples.length; i += 1) {
        const normalized = (samples[i] - 128) / 128;
        sumSquares += normalized * normalized;
      }
      level = Math.sqrt(sumSquares / samples.length);
    }

    updateMeterBars(level);
    state.meterRafId = requestAnimationFrame(animate);
  };

  state.meterRafId = requestAnimationFrame(animate);
}

function updateMeterBars(level) {
  const now = Date.now();
  const activity = Math.min(1, level * 5);

  state.meterBars.forEach((bar, idx) => {
    const pulse = (Math.sin(now / 120 + idx * 0.9) + 1) * 0.08;
    const scaled = Math.min(1, activity + pulse);
    const height = `${10 + scaled * 90}%`;

    bar.style.height = height;
    bar.style.backgroundColor = scaled > 0.18 ? "var(--bar-active)" : "var(--bar-idle)";
  });
}

function setMicStatus(text, active) {
  elements.micStatus.textContent = text;
  elements.micStatus.classList.toggle("active", Boolean(active));
}

function setCurrentPrompt(text) {
  elements.currentPrompt.textContent = text || "-";
}

function setSessionStatus(status) {
  state.status = status;
  elements.sessionStatus.textContent = status;
}

function syncButtons() {
  const hasSession = Boolean(state.sessionId);
  const isCompleted = state.status === "completed";
  const userControlled = state.mode === "user_controlled";

  elements.startBtn.disabled = hasSession;
  elements.recordBtn.disabled = !hasSession || !userControlled || isCompleted;
  elements.nextBtn.disabled = !hasSession || !userControlled || isCompleted;
  elements.downloadBtn.disabled = !hasSession;
  elements.modeSelect.disabled = hasSession;

  if (state.isRecording) {
    elements.recordBtn.classList.add("recording");
    elements.recordBtn.textContent = "Stop";
  } else {
    elements.recordBtn.classList.remove("recording");
    elements.recordBtn.textContent = "Record";
  }
}

async function startInterview() {
  state.mode = elements.modeSelect.value;

  await ensureMicrophone();
  setMicStatus("Microphone ready", true);

  const payload = await apiJson("/api/session/start", {
    method: "POST",
    body: JSON.stringify({ mode: state.mode }),
  });

  state.sessionId = payload.session_id;
  setSessionStatus(payload.status);
  elements.sessionId.textContent = payload.session_id;
  setCurrentPrompt(payload.current_prompt.text);
  await refreshTranscript();
  syncButtons();

  if (state.mode === "agent_controlled") {
    await runAgentMode(payload.current_prompt);
  } else {
    await speakText(payload.current_prompt.text);
  }
}

async function handleUserControlledRecordToggle() {
  if (!state.sessionId) {
    throw new Error("Start the interview first.");
  }

  if (!state.isRecording) {
    await beginRecording({ stopOnSilence: false });
    syncButtons();
    return;
  }

  const blob = await stopRecording();
  syncButtons();
  if (!blob) {
    return;
  }

  await processRecordedAnswer(blob);
}

async function forceNextQuestion() {
  if (!state.sessionId) {
    throw new Error("Start the interview first.");
  }

  const response = await apiJson("/api/interview/next", {
    method: "POST",
    body: JSON.stringify({ session_id: state.sessionId, force: true }),
  });

  setSessionStatus(response.status);

  if (response.next_prompt?.text) {
    setCurrentPrompt(response.next_prompt.text);
    await refreshTranscript();
    await speakText(response.next_prompt.text);
  }

  if (response.interview_complete) {
    setSessionStatus("completed");
  }

  syncButtons();
}

async function runAgentMode(initialPrompt) {
  if (state.agentLoopRunning) {
    return;
  }

  state.agentLoopRunning = true;
  state.abortAgentLoop = false;

  let prompt = initialPrompt;

  try {
    while (prompt && state.sessionId && !state.abortAgentLoop) {
      setCurrentPrompt(prompt.text);
      await speakText(prompt.text);

      if (state.abortAgentLoop || !state.sessionId) {
        break;
      }

      const audioBlob = await recordUntilSilence();
      if (!audioBlob || state.abortAgentLoop) {
        break;
      }

      const transcript = (await transcribeBlob(audioBlob)).trim();
      if (!transcript) {
        prompt = {
          type: "clarification",
          question_id: prompt.question_id,
          text: "I did not catch that. Please repeat your answer.",
        };
        continue;
      }

      const response = await apiJson("/api/interview/respond", {
        method: "POST",
        body: JSON.stringify({ session_id: state.sessionId, text: transcript }),
      });

      setSessionStatus(response.status);
      await refreshTranscript();

      if (response.interview_complete) {
        if (response.next_prompt?.text) {
          setCurrentPrompt(response.next_prompt.text);
          await speakText(response.next_prompt.text);
        }
        break;
      }

      prompt = response.next_prompt;
    }
  } finally {
    state.agentLoopRunning = false;
    syncButtons();
  }
}

async function processRecordedAnswer(blob) {
  const transcriptText = (await transcribeBlob(blob)).trim();

  if (!transcriptText) {
    setCurrentPrompt("No speech detected. Please record again.");
    return;
  }

  const response = await apiJson("/api/interview/respond", {
    method: "POST",
    body: JSON.stringify({ session_id: state.sessionId, text: transcriptText }),
  });

  setSessionStatus(response.status);
  await refreshTranscript();

  if (response.next_prompt?.text) {
    setCurrentPrompt(response.next_prompt.text);
    await speakText(response.next_prompt.text);
  }

  if (response.interview_complete) {
    setSessionStatus("completed");
  }

  syncButtons();
}

async function beginRecording({ stopOnSilence }) {
  if (state.isRecording) {
    return;
  }

  const stream = await ensureMicrophone();
  if (typeof MediaRecorder === "undefined") {
    throw new Error("MediaRecorder is not supported in this browser.");
  }

  const options = {};
  const mimeType = pickMimeType();
  if (mimeType) {
    options.mimeType = mimeType;
  }

  const chunks = [];
  const recorder = new MediaRecorder(stream, options);

  state.recordingPromise = new Promise((resolve, reject) => {
    recorder.addEventListener("dataavailable", (event) => {
      if (event.data && event.data.size > 0) {
        chunks.push(event.data);
      }
    });

    recorder.addEventListener("error", (event) => {
      reject(event.error || new Error("Unknown MediaRecorder error"));
    });

    recorder.addEventListener("stop", () => {
      stopSilenceDetection();
      state.isRecording = false;
      state.stopOnSilence = false;
      state.recorder = null;

      const audioBlob = new Blob(chunks, {
        type: recorder.mimeType || "audio/webm",
      });
      resolve(audioBlob);
      syncButtons();
    });
  });

  state.recorder = recorder;
  state.isRecording = true;
  state.stopOnSilence = Boolean(stopOnSilence);
  state.recordStartedAt = Date.now();
  state.lastVoiceDetectedAt = Date.now();

  recorder.start(250);

  if (state.stopOnSilence) {
    startSilenceDetection();
  }

  syncButtons();
}

async function stopRecording() {
  if (!state.recorder) {
    return null;
  }

  const pending = state.recordingPromise;
  if (state.recorder.state !== "inactive") {
    state.recorder.stop();
  }

  return pending;
}

async function recordUntilSilence() {
  await beginRecording({ stopOnSilence: true });
  const blob = await state.recordingPromise;
  return blob;
}

function startSilenceDetection() {
  stopSilenceDetection();

  const sampleBuffer = new Uint8Array(state.analyser ? state.analyser.fftSize : 512);

  const monitor = () => {
    if (!state.isRecording || !state.stopOnSilence) {
      return;
    }

    let rms = 0;
    if (state.analyser) {
      state.analyser.getByteTimeDomainData(sampleBuffer);
      let sumSquares = 0;
      for (let i = 0; i < sampleBuffer.length; i += 1) {
        const normalized = (sampleBuffer[i] - 128) / 128;
        sumSquares += normalized * normalized;
      }
      rms = Math.sqrt(sumSquares / sampleBuffer.length);
    }

    if (rms > SILENCE_THRESHOLD) {
      state.lastVoiceDetectedAt = Date.now();
    }

    const now = Date.now();
    const recordingElapsedMs = now - state.recordStartedAt;
    const silenceElapsedMs = now - state.lastVoiceDetectedAt;

    if (
      recordingElapsedMs >= MIN_RECORDING_MS &&
      silenceElapsedMs >= SILENCE_TIMEOUT_MS &&
      state.recorder &&
      state.recorder.state !== "inactive"
    ) {
      state.recorder.stop();
      return;
    }

    state.silenceRafId = requestAnimationFrame(monitor);
  };

  state.silenceRafId = requestAnimationFrame(monitor);
}

function stopSilenceDetection() {
  if (state.silenceRafId) {
    cancelAnimationFrame(state.silenceRafId);
    state.silenceRafId = null;
  }
}

function pickMimeType() {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
  ];

  for (const mimeType of candidates) {
    if (MediaRecorder.isTypeSupported(mimeType)) {
      return mimeType;
    }
  }

  return "";
}

async function transcribeBlob(blob) {
  const audioBase64 = await blobToBase64(blob);

  const payload = await apiJson("/api/transcribe", {
    method: "POST",
    body: JSON.stringify({
      audio_base64: audioBase64,
      mime_type: blob.type || "audio/webm",
    }),
  });

  return payload.text || "";
}

async function refreshTranscript() {
  if (!state.sessionId) {
    elements.transcript.innerHTML = "";
    return;
  }

  const log = await apiJson(`/api/session/${state.sessionId}/log`, {
    method: "GET",
  });

  setSessionStatus(log.status);
  renderTranscript(log.turns);

  const latestPromptTurn = [...log.turns]
    .reverse()
    .find((turn) => turn.speaker === "agent" && ["question", "clarification", "completion"].includes(turn.type));
  if (latestPromptTurn) {
    setCurrentPrompt(latestPromptTurn.text);
  }

  syncButtons();
}

function renderTranscript(turns) {
  elements.transcript.innerHTML = "";

  if (!turns || turns.length === 0) {
    const placeholder = document.createElement("p");
    placeholder.className = "muted";
    placeholder.textContent = "No transcript yet.";
    elements.transcript.appendChild(placeholder);
    return;
  }

  turns.forEach((turn) => {
    const row = document.createElement("div");
    row.className = `turn ${turn.speaker}`;

    const meta = document.createElement("div");
    meta.className = "turn-meta";
    const questionLabel = turn.question_id ? `Q${turn.question_id}` : "Session";
    const timestamp = new Date(turn.timestamp).toLocaleTimeString();
    meta.textContent = `${turn.turn_index}. ${turn.speaker} | ${turn.type} | ${questionLabel} | ${timestamp}`;

    const text = document.createElement("div");
    text.textContent = turn.text;

    row.appendChild(meta);
    row.appendChild(text);
    elements.transcript.appendChild(row);
  });

  elements.transcript.scrollTop = elements.transcript.scrollHeight;
}

async function downloadSessionJson() {
  if (!state.sessionId) {
    throw new Error("No active session to download.");
  }

  const response = await fetch(`/api/session/${state.sessionId}/download`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || "Failed to download JSON");
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);

  const link = document.createElement("a");
  link.href = url;
  link.download = `interview_${state.sessionId}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();

  URL.revokeObjectURL(url);
}

async function resetSession() {
  state.abortAgentLoop = true;
  state.agentLoopRunning = false;

  if (state.recorder && state.recorder.state !== "inactive") {
    state.recorder.stop();
  }

  window.speechSynthesis?.cancel();

  state.sessionId = null;
  setSessionStatus("idle");
  elements.sessionId.textContent = "-";
  elements.transcript.innerHTML = "";
  setCurrentPrompt("Interview not started.");

  syncButtons();
}

async function speakText(text) {
  if (!text || !window.speechSynthesis) {
    return;
  }

  window.speechSynthesis.cancel();

  await new Promise((resolve) => {
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1.0;
    utterance.pitch = 1.0;
    utterance.onend = () => resolve();
    utterance.onerror = () => resolve();
    window.speechSynthesis.speak(utterance);
  });
}

async function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const result = String(reader.result || "");
      resolve(result);
    };
    reader.onerror = () => reject(new Error("Failed to encode audio blob."));
    reader.readAsDataURL(blob);
  });
}

async function apiJson(url, options) {
  const requestOptions = {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers || {}),
    },
  };

  const response = await fetch(url, requestOptions);
  if (!response.ok) {
    const detail = await safeErrorText(response);
    throw new Error(detail || `Request failed with status ${response.status}`);
  }

  return response.json();
}

async function safeErrorText(response) {
  try {
    const payload = await response.json();
    if (payload?.detail) {
      return payload.detail;
    }
    return JSON.stringify(payload);
  } catch (_error) {
    return await response.text();
  }
}
