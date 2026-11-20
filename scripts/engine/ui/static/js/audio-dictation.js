// Ditado por voz: grava OGG/Opus no navegador (opus-recorder), manda ao backend e devolve o texto.
// Uma "session" por gravação; respostas atrasadas/canceladas são ignoradas. Ver /api/audio/*.
import { useState, useEffect, useRef, useCallback, t } from "./ui.js";
import { authToken } from "./api.js";

export const MAX_SECONDS = 600;
const BASE = "/vendor/opus-recorder/";
let loading = null;

function loadRecorder() {
  if (window.Recorder) return Promise.resolve();
  if (!loading) loading = new Promise((ok, no) => {
    const s = document.createElement("script");
    s.src = BASE + "recorder.min.js";
    s.onload = () => ok();
    s.onerror = () => { loading = null; no(new Error(t("dictation.recorder_load_failed"))); };
    document.head.appendChild(s);
  });
  return loading;
}

export async function fetchAudioConfig() {
  const headers = {}; const a = authToken(); if (a) headers["X-Netops-Session"] = a;
  try { const r = await fetch("/api/audio/config", { headers }); return r.ok ? await r.json() : { configured: false }; }
  catch (_) { return { configured: false }; }
}

async function upload(blob, signal) {
  const ext = /webm/.test(blob.type) ? "webm" : /mp4|aac/.test(blob.type) ? "m4a" : "ogg";
  const form = new FormData(); form.append("audio", blob, "voice." + ext);
  const headers = {}; const a = authToken(); if (a) headers["X-Netops-Session"] = a;
  const res = await fetch("/api/audio/transcribe", { method: "POST", headers, body: form, signal });
  const out = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof out.detail === "string" ? out.detail : t("dictation.transcribe_failed_http", { status: res.status }));
  const text = typeof out.transcription === "string" ? out.transcription.trim() : "";
  if (!text) throw new Error(t("dictation.empty_transcription"));
  return text;
}

// Formatos aceitos pelo backend/Whisper, em ordem de preferência. Chrome/Android: webm/opus;
// Firefox: ogg/opus; Safari/iOS: mp4 (AAC). Vazio = sem MediaRecorder → opus-recorder.
const NATIVE_TYPES = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/webm", "audio/mp4;codecs=mp4a.40.2", "audio/mp4"];
function nativeMime() {
  if (typeof window.MediaRecorder !== "function" || typeof MediaRecorder.isTypeSupported !== "function") return "";
  return NATIVE_TYPES.find((type) => { try { return MediaRecorder.isTypeSupported(type); } catch (_) { return false; } }) || "";
}

// Adaptador com a mesma interface usada do opus-recorder (start/stop/close/onstop).
async function nativeRecorder(mime, onBlob) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  const release = () => stream.getTracks().forEach((track) => { try { track.stop(); } catch (_) {} });
  let mr;
  try { mr = new MediaRecorder(stream, { mimeType: mime, audioBitsPerSecond: 32000 }); }
  catch (e) { release(); throw e; }
  const chunks = [];
  const api = { onstop: null, closed: false };
  mr.ondataavailable = (ev) => { if (ev.data && ev.data.size) chunks.push(ev.data); };
  mr.onstop = () => {
    release();
    try { api.onstop && api.onstop(); } catch (_) {}
    if (!api.closed) onBlob(new Blob(chunks, { type: (mr.mimeType || mime).split(";")[0] }));
  };
  api.start = () => { mr.start(1000); return Promise.resolve(); };  // fatias de 1 s: não perde tudo se a aba pausar
  api.stop = () => { if (mr.state !== "inactive") mr.stop(); else release(); };
  api.close = () => { api.closed = true; api.stop(); };
  return api;
}

// conversationId: muda ao trocar de conversa. onText(text): insere no rascunho. onError(msg).
export function useDictation({ conversationId, onText, onError }) {
  const [configured, setConfigured] = useState(false);
  const [phase, setPhase] = useState("idle");   // idle | starting | recording | transcribing
  const [elapsed, setElapsed] = useState(0);
  const sessionRef = useRef(null);
  const convRef = useRef(conversationId);
  const cb = useRef({ onText, onError });
  cb.current = { onText, onError };
  convRef.current = conversationId;

  const refresh = useCallback(() => fetchAudioConfig().then((c) => setConfigured(!!c.configured)), []);
  useEffect(() => {
    refresh();
    window.addEventListener("netops-audio-config", refresh);
    return () => window.removeEventListener("netops-audio-config", refresh);
  }, [refresh]);

  const teardown = useCallback((s) => {
    if (!s) return;
    s.cancelled = true;
    clearInterval(s.timer);
    try { s.controller.abort(); } catch (_) {}
    try { s.recorder && s.recorder.stop(); } catch (_) {}
    try { s.recorder && s.recorder.close && s.recorder.close(); } catch (_) {}
  }, []);

  const reset = useCallback((s) => {
    if (sessionRef.current === s) { sessionRef.current = null; setPhase("idle"); setElapsed(0); }
  }, []);

  const cancel = useCallback(() => { const s = sessionRef.current; teardown(s); reset(s); }, [teardown, reset]);

  // conversa mudou: descarta gravação/transcrição em curso; desmontar também libera o microfone.
  useEffect(() => () => { teardown(sessionRef.current); sessionRef.current = null; }, [conversationId, teardown]);

  const start = useCallback(async () => {
    if (sessionRef.current) return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      cb.current.onError(t("dictation.browser_unsupported"));
      return;
    }
    const s = { cancelled: false, controller: new AbortController(), conversationId: convRef.current, recorder: null, timer: 0 };
    sessionRef.current = s; setPhase("starting"); setElapsed(0);
    try {
      const handle = async (blob) => {
        if (s.cancelled || sessionRef.current !== s) return;
        if (!blob.size) { cb.current.onError(t("dictation.recording_empty")); reset(s); return; }
        setPhase("transcribing");
        try {
          const text = await upload(blob, s.controller.signal);
          if (s.cancelled || sessionRef.current !== s || convRef.current !== s.conversationId) return;
          cb.current.onText(text);
        } catch (e) {
          if (e.name !== "AbortError" && !s.cancelled && sessionRef.current === s) cb.current.onError(e.message || t("dictation.transcribe_failed"));
        } finally { reset(s); }
      };
      const mime = nativeMime();
      let rec;
      if (mime) {
        // MediaRecorder nativo (padrão): grava direto do microfone, sem Web Audio. No celular o
        // opus-recorder (AudioContext/ScriptProcessor) gerava Ogg só com cabeçalhos (0 s, 0 KB).
        rec = await nativeRecorder(mime, handle);
      } else {
        await loadRecorder();
        rec = new window.Recorder({
          encoderPath: BASE + "encoderWorker.min.js",
          encoderApplication: 2048, encoderSampleRate: 48000, encoderBitRate: 24000,
          numberOfChannels: 1, streamPages: false,
        });
        rec.ondataavailable = (data) => handle(new Blob([data], { type: "audio/ogg" }));
      }
      s.recorder = rec;
      rec.onstop = () => clearInterval(s.timer);
      await rec.start();
      if (s.cancelled) { teardown(s); return; }   // cancelado enquanto start() pendia: solta o microfone
      const t0 = Date.now();
      s.timer = setInterval(() => {
        const sec = Math.floor((Date.now() - t0) / 1000);
        setElapsed(sec);
        if (sec >= MAX_SECONDS) stop();
      }, 250);
      setPhase("recording");
    } catch (e) {
      teardown(s); reset(s);
      const denied = e && (e.name === "NotAllowedError" || e.name === "SecurityError");
      cb.current.onError(denied ? t("dictation.mic_denied")
        : (e && e.name === "NotFoundError") ? t("dictation.mic_not_found")
        : (e && e.message) || t("dictation.start_failed"));
    }
  }, [teardown, reset]);

  const stop = useCallback(() => {
    const s = sessionRef.current;
    if (!s || s.cancelled || !s.recorder) return;
    clearInterval(s.timer);
    try { s.recorder.stop(); } catch (_) { cancel(); }   // dispara ondataavailable com o arquivo completo
  }, [cancel]);

  return { configured, phase, elapsed, start, stop, cancel };
}
