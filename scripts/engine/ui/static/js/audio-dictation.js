// Ditado por voz: grava OGG/Opus no navegador (opus-recorder), manda ao backend e devolve o texto.
// Uma "session" por gravação; respostas atrasadas/canceladas são ignoradas. Ver /api/audio/*.
import { useState, useEffect, useRef, useCallback } from "./ui.js";
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
    s.onerror = () => { loading = null; no(new Error("Não foi possível carregar o gravador.")); };
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
  const form = new FormData(); form.append("audio", blob, "voice.ogg");
  const headers = {}; const a = authToken(); if (a) headers["X-Netops-Session"] = a;
  const res = await fetch("/api/audio/transcribe", { method: "POST", headers, body: form, signal });
  const out = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof out.detail === "string" ? out.detail : "Falha ao transcrever o áudio.");
  const text = typeof out.transcription === "string" ? out.transcription.trim() : "";
  if (!text) throw new Error("O áudio não gerou uma transcrição.");
  return text;
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
      cb.current.onError("Este navegador não permite gravar áudio (use HTTPS ou localhost).");
      return;
    }
    const s = { cancelled: false, controller: new AbortController(), conversationId: convRef.current, recorder: null, timer: 0 };
    sessionRef.current = s; setPhase("starting"); setElapsed(0);
    try {
      await loadRecorder();
      const rec = new window.Recorder({
        encoderPath: BASE + "encoderWorker.min.js",
        encoderApplication: 2048, encoderSampleRate: 48000, encoderBitRate: 24000,
        numberOfChannels: 1, streamPages: false,
      });
      s.recorder = rec;
      rec.ondataavailable = async (data) => {
        if (s.cancelled || sessionRef.current !== s) return;
        const blob = new Blob([data], { type: "audio/ogg" });
        if (!blob.size) { cb.current.onError("A gravação está vazia."); reset(s); return; }
        setPhase("transcribing");
        try {
          const text = await upload(blob, s.controller.signal);
          if (s.cancelled || sessionRef.current !== s || convRef.current !== s.conversationId) return;
          cb.current.onText(text);
        } catch (e) {
          if (e.name !== "AbortError" && !s.cancelled && sessionRef.current === s) cb.current.onError(e.message || "Falha ao transcrever o áudio.");
        } finally { reset(s); }
      };
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
      cb.current.onError(denied ? "Permissão do microfone negada. Libere o acesso no navegador."
        : (e && e.name === "NotFoundError") ? "Nenhum microfone encontrado."
        : (e && e.message) || "Não foi possível iniciar a gravação.");
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
