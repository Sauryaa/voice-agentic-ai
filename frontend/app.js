const state = {
  sessionId: null,
  isRecording: false,
  recorder: null,
  stream: null,
  chunks: [],
};

const startBtn = document.getElementById("startBtn");
const recordBtn = document.getElementById("recordBtn");
const sendTextBtn = document.getElementById("sendTextBtn");
const textForm = document.getElementById("textForm");
const textInput = document.getElementById("textInput");
const statusText = document.getElementById("statusText");
const chatList = document.getElementById("chatList");
const logLink = document.getElementById("logLink");

function setStatus(text) {
  statusText.textContent = `Status: ${text}`;
}

function addMessage(speaker, text) {
  const container = document.createElement("article");
  container.className = `message ${speaker}`;

  const label = document.createElement("p");
  label.className = "label";
  label.textContent = speaker === "agent" ? "Agent" : "Interviewee";

  const body = document.createElement("p");
  body.textContent = text;

  container.appendChild(label);
  container.appendChild(body);
  chatList.appendChild(container);
  chatList.scrollTop = chatList.scrollHeight;
}

function speak(text) {
  if (!("speechSynthesis" in window)) {
    return;
  }
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 1.0;
  utterance.pitch = 1.0;
  window.speechSynthesis.speak(utterance);
}

async function startInterview() {
  setStatus("starting interview...");
  const response = await fetch("/api/session/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });

  if (!response.ok) {
    const data = await response.json();
    throw new Error(data.detail || "Failed to start session");
  }

  const data = await response.json();
  state.sessionId = data.session_id;
  recordBtn.disabled = false;
  sendTextBtn.disabled = false;
  textInput.disabled = false;
  logLink.classList.remove("hidden");
  logLink.href = `/api/session/${state.sessionId}/log`;

  addMessage("agent", data.message);
  speak(data.message);
  setStatus(`session active (${data.current_question_index + 1}/${data.total_questions})`);
}

function chooseMimeType() {
  const options = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"];
  for (const option of options) {
    if (MediaRecorder.isTypeSupported(option)) {
      return option;
    }
  }
  return "";
}

async function startRecording() {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error("This browser does not support audio recording");
  }

  const mimeType = chooseMimeType();
  if (!mimeType) {
    throw new Error("No supported recording format was found in this browser");
  }

  state.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  state.chunks = [];

  state.recorder = new MediaRecorder(state.stream, { mimeType });
  state.recorder.ondataavailable = (event) => {
    if (event.data && event.data.size > 0) {
      state.chunks.push(event.data);
    }
  };

  state.recorder.onstop = async () => {
    try {
      await uploadAudio();
    } catch (error) {
      setStatus(error.message);
    } finally {
      stopStreamTracks();
    }
  };

  state.recorder.start();
  state.isRecording = true;
  recordBtn.textContent = "Stop Recording";
  recordBtn.classList.add("recording");
  setStatus("recording...");
}

function stopRecording() {
  if (state.recorder && state.isRecording) {
    state.recorder.stop();
  }
  state.isRecording = false;
  recordBtn.textContent = "Start Recording";
  recordBtn.classList.remove("recording");
  setStatus("processing audio...");
}

function stopStreamTracks() {
  if (state.stream) {
    state.stream.getTracks().forEach((track) => track.stop());
    state.stream = null;
  }
}

async function uploadAudio() {
  if (!state.sessionId) {
    throw new Error("Start the interview first");
  }
  if (!state.chunks.length) {
    throw new Error("No audio captured");
  }

  const blob = new Blob(state.chunks, { type: state.recorder.mimeType || "audio/webm" });
  const formData = new FormData();
  formData.append("audio", blob, "utterance.webm");

  const response = await fetch(`/api/session/${state.sessionId}/voice-turn`, {
    method: "POST",
    body: formData,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Voice turn failed");
  }

  if (data.transcript) {
    addMessage("interviewee", data.transcript);
  }
  addMessage("agent", data.assistant_message);
  speak(data.assistant_message);

  if (data.interview_complete) {
    recordBtn.disabled = true;
    sendTextBtn.disabled = true;
    textInput.disabled = true;
    setStatus("interview complete");
    return;
  }

  setStatus(`session active (${data.current_question_index + 1}/${data.total_questions})`);
}

async function sendTextTurn(text) {
  if (!state.sessionId) {
    throw new Error("Start the interview first");
  }
  const response = await fetch(`/api/session/${state.sessionId}/text-turn`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Text turn failed");
  }

  if (data.transcript) {
    addMessage("interviewee", data.transcript);
  }
  addMessage("agent", data.assistant_message);
  speak(data.assistant_message);

  if (data.interview_complete) {
    recordBtn.disabled = true;
    sendTextBtn.disabled = true;
    textInput.disabled = true;
    setStatus("interview complete");
    return;
  }

  setStatus(`session active (${data.current_question_index + 1}/${data.total_questions})`);
}

startBtn.addEventListener("click", async () => {
  try {
    await startInterview();
    startBtn.disabled = true;
  } catch (error) {
    setStatus(error.message);
  }
});

recordBtn.addEventListener("click", async () => {
  try {
    if (!state.sessionId) {
      throw new Error("Start interview first");
    }
    if (state.isRecording) {
      stopRecording();
    } else {
      await startRecording();
    }
  } catch (error) {
    setStatus(error.message);
    stopStreamTracks();
    state.isRecording = false;
    recordBtn.textContent = "Start Recording";
    recordBtn.classList.remove("recording");
  }
});

textForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = textInput.value.trim();
  if (!text) {
    return;
  }
  textInput.value = "";
  try {
    await sendTextTurn(text);
  } catch (error) {
    setStatus(error.message);
  }
});
