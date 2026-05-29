import { useState, useEffect, useRef, useCallback } from "react";

// TypeScript definitions for Web Speech API
interface SpeechRecognitionEvent extends Event {
  results: SpeechRecognitionResultList;
  resultIndex: number;
}

interface SpeechRecognitionErrorEvent extends Event {
  error: string;
  message: string;
}

interface SpeechRecognition extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  maxAlternatives: number;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null;
  onstart: (() => void) | null;
  onend: (() => void) | null;
  onspeechstart: (() => void) | null;
  onspeechend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
}

declare global {
  interface Window {
    SpeechRecognition: new () => SpeechRecognition;
    webkitSpeechRecognition: new () => SpeechRecognition;
  }
}

interface UseVoiceInputOptions {
  onResult: (transcript: string, isFinal: boolean) => void;
  onError?: (error: string) => void;
  lang?: string;
}

interface UseVoiceInputReturn {
  isListening: boolean;
  isSupported: boolean;
  startListening: () => void;
  stopListening: () => void;
  error: string | null;
}

export function useVoiceInput({ onResult, onError, lang = "en-US" }: UseVoiceInputOptions): UseVoiceInputReturn {
  const [isListening, setIsListening] = useState(false);
  const [isSupported, setIsSupported] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const hasReceivedSpeech = useRef(false);
  const isStartingRef = useRef(false);
  const hasStartedRef = useRef(false);

  // Keep callbacks in refs so handlers always call the latest version,
  // even after the component re-renders (e.g. activeThread changes).
  const onResultRef = useRef(onResult);
  const onErrorRef = useRef(onError);
  useEffect(() => { onResultRef.current = onResult; }, [onResult]);
  useEffect(() => { onErrorRef.current = onError; }, [onError]);

  // Sync lang to the recognition instance whenever it changes.
  // The instance is created once on mount; this keeps it up-to-date
  // without tearing it down and recreating it.
  useEffect(() => {
    if (recognitionRef.current) {
      recognitionRef.current.lang = lang;
    }
  }, [lang]);

  useEffect(() => {
    const SpeechRecognitionConstructor =
      window.SpeechRecognition || window.webkitSpeechRecognition;

    if (SpeechRecognitionConstructor) {
      setIsSupported(true);

      if (!recognitionRef.current) {
        recognitionRef.current = new SpeechRecognitionConstructor();

        const recognition = recognitionRef.current;
        recognition.continuous = false;
        recognition.interimResults = true;
        recognition.lang = lang;
        recognition.maxAlternatives = 1;

        recognition.onresult = (event: SpeechRecognitionEvent) => {
          hasReceivedSpeech.current = true;

          const result = event.results[event.results.length - 1];
          const transcript = result[0].transcript;

          // Forward both interim and final results to the caller.
          // Callers can use isFinal to decide whether to auto-submit.
          if (transcript.trim()) {
            onResultRef.current(transcript, result.isFinal);
          }

          if (result.isFinal && recognitionRef.current) {
            recognitionRef.current.stop();
          }
        };

        recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
          isStartingRef.current = false;
          hasStartedRef.current = false;

          if (event.error === "aborted") {
            setIsListening(false);
            return;
          }

          if (event.error === "not-allowed" || event.error === "permission-denied") {
            const msg =
              "Microphone permission denied. Please allow microphone access in your browser settings.";
            setError(msg);
            onErrorRef.current?.(msg);
          } else if (event.error === "no-speech") {
            if (!hasReceivedSpeech.current) {
              const msg = "No speech detected. Please try again and speak clearly.";
              onErrorRef.current?.(msg);
            }
          } else {
            const msg = `Speech recognition error: ${event.error}`;
            setError(msg);
            onErrorRef.current?.(msg);
          }

          setIsListening(false);
        };

        recognition.onstart = () => {
          hasReceivedSpeech.current = false;
          isStartingRef.current = false;
          hasStartedRef.current = true;
          setIsListening(true);
        };

        recognition.onspeechstart = () => {};
        recognition.onspeechend = () => {};

        recognition.onend = () => {
          isStartingRef.current = false;
          hasStartedRef.current = false;
          setIsListening(false);
        };
      }
    } else {
      setIsSupported(false);
      const msg =
        "Speech recognition is not supported in this browser. Please use Chrome, Edge, or Safari.";
      setError(msg);
      onErrorRef.current?.(msg);
    }

    return () => {
      if (recognitionRef.current) {
        try {
          recognitionRef.current.abort();
        } catch {
          // ignore cleanup errors
        }
      }
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const startListening = useCallback(() => {
    if (!isSupported || !recognitionRef.current) return;
    if (isListening || isStartingRef.current) return;

    try {
      setError(null);
      hasReceivedSpeech.current = false;
      isStartingRef.current = true;
      recognitionRef.current.start();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      if (message.includes("already started")) {
        isStartingRef.current = false;
        return;
      }
      const errorMessage = `Failed to start speech recognition: ${message}`;
      setError(errorMessage);
      onErrorRef.current?.(errorMessage);
      setIsListening(false);
      isStartingRef.current = false;
    }
  }, [isSupported, isListening]);

  // Use hasStartedRef (synchronous) instead of isListening (state, may be
  // slightly stale between onresult calling stop() and React flushing onend).
  const stopListening = useCallback(() => {
    if (recognitionRef.current && hasStartedRef.current) {
      try {
        recognitionRef.current.stop();
      } catch {
        // ignore
      }
    }
  }, []);

  return { isListening, isSupported, startListening, stopListening, error };
}
