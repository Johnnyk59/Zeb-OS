/**
 * useVoiceChat — real-time talk-to-Zeb voice, browser-native.
 *
 * Voice is not a separate assistant: it feeds the exact same gateway path as
 * the text composer, so it inherits identical permissions and full workspace
 * access. This is Zeb hearing and speaking with one of its own faculties, not
 * a bolt-on service.
 *
 * Uses the Web Speech API (SpeechRecognition for listening, speechSynthesis
 * for talking back) — no network calls, no external host. `onFinalTranscript`
 * fires with the recognized utterance so the caller can drop it into the
 * composer and send it just like a typed message. When voice mode is on,
 * `speak()` reads Zeb's replies aloud.
 */
import { useCallback, useEffect, useRef, useState } from "react";

// The Web Speech API isn't in TS's DOM lib; treat it structurally.
type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((e: unknown) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
};

function getRecognitionCtor(): (new () => SpeechRecognitionLike) | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function useVoiceChat(onFinalTranscript: (text: string) => void) {
  const [supported] = useState(() => getRecognitionCtor() !== null);
  const [listening, setListening] = useState(false);
  const [voiceMode, setVoiceMode] = useState(false);

  const recogRef = useRef<SpeechRecognitionLike | null>(null);
  const onFinalRef = useRef(onFinalTranscript);
  onFinalRef.current = onFinalTranscript;
  const voiceModeRef = useRef(false);
  voiceModeRef.current = voiceMode;

  const stopListening = useCallback(() => {
    try {
      recogRef.current?.stop();
    } catch {
      /* already stopped */
    }
    setListening(false);
  }, []);

  const startListening = useCallback(() => {
    const Ctor = getRecognitionCtor();
    if (!Ctor) return;
    // Cancel any in-flight speech so Zeb doesn't hear itself.
    try {
      window.speechSynthesis?.cancel();
    } catch {
      /* no synth */
    }
    const recog = new Ctor();
    recog.lang = navigator.language || "en-US";
    recog.continuous = false;
    recog.interimResults = true;
    recog.onresult = (e: unknown) => {
      // e.results is a list of alternatives; take the last final one.
      const ev = e as {
        results: ArrayLike<{ 0: { transcript: string }; isFinal: boolean }>;
      };
      let finalText = "";
      for (let i = 0; i < ev.results.length; i++) {
        const r = ev.results[i];
        if (r.isFinal) finalText += r[0].transcript;
      }
      if (finalText.trim()) {
        onFinalRef.current(finalText.trim());
        stopListening();
      }
    };
    recog.onend = () => setListening(false);
    recog.onerror = () => setListening(false);
    recogRef.current = recog;
    try {
      recog.start();
      setListening(true);
    } catch {
      setListening(false);
    }
  }, [stopListening]);

  const speak = useCallback((text: string) => {
    if (!voiceModeRef.current || !text.trim()) return;
    try {
      const synth = window.speechSynthesis;
      if (!synth) return;
      // Strip markdown/code fences so speech stays natural.
      const clean = text
        .replace(/```[\s\S]*?```/g, " code block ")
        .replace(/[*_`#>]/g, "")
        .slice(0, 1200);
      const utter = new SpeechSynthesisUtterance(clean);
      utter.lang = navigator.language || "en-US";
      synth.speak(utter);
    } catch {
      /* synthesis unavailable */
    }
  }, []);

  const toggleVoiceMode = useCallback(() => {
    setVoiceMode((v) => {
      const next = !v;
      if (!next) {
        try {
          window.speechSynthesis?.cancel();
        } catch {
          /* ignore */
        }
      }
      return next;
    });
  }, []);

  useEffect(
    () => () => {
      try {
        recogRef.current?.abort();
        window.speechSynthesis?.cancel();
      } catch {
        /* teardown */
      }
    },
    [],
  );

  return {
    supported,
    listening,
    voiceMode,
    startListening,
    stopListening,
    toggleVoiceMode,
    speak,
  };
}
