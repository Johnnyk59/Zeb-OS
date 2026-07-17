/** Browser-native, silence-aware voice conversation mode for Zeb chat. */
import { useCallback, useEffect, useRef, useState } from "react";

export const VOICE_SILENCE_MS = 2500;

type SpeechRecognitionResultLike = {
  0: { transcript: string };
  isFinal: boolean;
};

type SpeechRecognitionEventLike = {
  resultIndex?: number;
  results: ArrayLike<SpeechRecognitionResultLike>;
};

type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
};

function getRecognitionCtor(): (new () => SpeechRecognitionLike) | null {
  if (typeof window === "undefined") return null;
  const browser = window as unknown as {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  };
  return browser.SpeechRecognition ?? browser.webkitSpeechRecognition ?? null;
}

export function useVoiceChat(
  onFinalTranscript: (text: string) => void,
  onBargeIn?: () => void,
) {
  const [supported] = useState(() => getRecognitionCtor() !== null);
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [voiceMode, setVoiceMode] = useState(false);
  const [transcript, setTranscript] = useState("");

  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const restartTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const finalTranscriptRef = useRef("");
  const interimTranscriptRef = useRef("");
  const listeningWantedRef = useRef(false);
  const automaticListenRef = useRef(false);
  const voiceModeRef = useRef(false);
  const startListeningRef = useRef<() => void>(() => {});
  const onFinalRef = useRef(onFinalTranscript);
  const onBargeInRef = useRef(onBargeIn);

  useEffect(() => {
    onFinalRef.current = onFinalTranscript;
    onBargeInRef.current = onBargeIn;
    voiceModeRef.current = voiceMode;
  }, [onBargeIn, onFinalTranscript, voiceMode]);

  const clearTimers = useCallback(() => {
    if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
    if (restartTimerRef.current) clearTimeout(restartTimerRef.current);
    silenceTimerRef.current = null;
    restartTimerRef.current = null;
  }, []);

  const stopSpeaking = useCallback(() => {
    try {
      window.speechSynthesis?.cancel();
    } catch {
      // Speech synthesis is optional.
    }
    setSpeaking(false);
  }, []);

  const stopListening = useCallback(() => {
    listeningWantedRef.current = false;
    clearTimers();
    try {
      recognitionRef.current?.abort();
    } catch {
      // Recognition may already be stopped.
    }
    recognitionRef.current = null;
    finalTranscriptRef.current = "";
    interimTranscriptRef.current = "";
    setTranscript("");
    setListening(false);
  }, [clearTimers]);

  const flushTranscript = useCallback(() => {
    const text = `${finalTranscriptRef.current} ${interimTranscriptRef.current}`
      .replace(/\s+/g, " ")
      .trim();
    listeningWantedRef.current = false;
    clearTimers();
    try {
      recognitionRef.current?.stop();
    } catch {
      // Recognition may have ended while the silence timer fired.
    }
    recognitionRef.current = null;
    finalTranscriptRef.current = "";
    interimTranscriptRef.current = "";
    setTranscript("");
    setListening(false);
    if (text) onFinalRef.current(text);
  }, [clearTimers]);

  const armSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
    silenceTimerRef.current = setTimeout(flushTranscript, VOICE_SILENCE_MS);
  }, [flushTranscript]);

  const startListening = useCallback(() => {
    const Recognition = getRecognitionCtor();
    if (!Recognition) return;

    if (automaticListenRef.current) automaticListenRef.current = false;
    else onBargeInRef.current?.();
    stopSpeaking();
    clearTimers();
    setVoiceMode(true);
    voiceModeRef.current = true;
    listeningWantedRef.current = true;
    finalTranscriptRef.current = "";
    interimTranscriptRef.current = "";
    setTranscript("");

    const recognition = new Recognition();
    recognition.lang = navigator.language || "en-US";
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.onresult = (event) => {
      let interim = "";
      const first = Math.max(0, event.resultIndex ?? 0);
      for (let index = first; index < event.results.length; index += 1) {
        const result = event.results[index];
        const chunk = result[0]?.transcript ?? "";
        if (result.isFinal) finalTranscriptRef.current += ` ${chunk}`;
        else interim += ` ${chunk}`;
      }
      interimTranscriptRef.current = interim;
      const live = `${finalTranscriptRef.current} ${interim}`
        .replace(/\s+/g, " ")
        .trim();
      setTranscript(live);
      if (live) armSilenceTimer();
    };
    recognition.onerror = () => {
      listeningWantedRef.current = false;
      clearTimers();
      setListening(false);
    };
    recognition.onend = () => {
      setListening(false);
      if (!listeningWantedRef.current) return;
      restartTimerRef.current = setTimeout(() => {
        try {
          recognition.start();
          setListening(true);
        } catch {
          listeningWantedRef.current = false;
        }
      }, 120);
    };
    recognitionRef.current = recognition;
    try {
      recognition.start();
      setListening(true);
    } catch {
      listeningWantedRef.current = false;
      setListening(false);
    }
  }, [armSilenceTimer, clearTimers, stopSpeaking]);
  useEffect(() => {
    startListeningRef.current = startListening;
  }, [startListening]);

  const speak = useCallback((text: string) => {
    if (!voiceModeRef.current || !text.trim()) return;
    try {
      const synth = window.speechSynthesis;
      if (!synth) return;
      synth.cancel();
      const clean = text
        .replace(/```[\s\S]*?```/g, " code block ")
        .replace(/[*_`#>]/g, "")
        .slice(0, 2400);
      const utterance = new SpeechSynthesisUtterance(clean);
      utterance.lang = navigator.language || "en-US";
      utterance.onstart = () => setSpeaking(true);
      utterance.onend = () => {
        setSpeaking(false);
        if (voiceModeRef.current) {
          restartTimerRef.current = setTimeout(
            () => {
              automaticListenRef.current = true;
              startListeningRef.current();
            },
            220,
          );
        }
      };
      utterance.onerror = () => setSpeaking(false);
      synth.speak(utterance);
    } catch {
      setSpeaking(false);
    }
  }, []);

  const toggleVoiceMode = useCallback(() => {
    setVoiceMode((current) => {
      const next = !current;
      voiceModeRef.current = next;
      if (!next) {
        stopListening();
        stopSpeaking();
      }
      return next;
    });
  }, [stopListening, stopSpeaking]);

  useEffect(
    () => () => {
      listeningWantedRef.current = false;
      clearTimers();
      try {
        recognitionRef.current?.abort();
        window.speechSynthesis?.cancel();
      } catch {
        // Browser voice APIs are best-effort during teardown.
      }
    },
    [clearTimers],
  );

  return {
    supported,
    listening,
    speaking,
    transcript,
    voiceMode,
    silenceMs: VOICE_SILENCE_MS,
    startListening,
    stopListening,
    stopSpeaking,
    toggleVoiceMode,
    speak,
  };
}
