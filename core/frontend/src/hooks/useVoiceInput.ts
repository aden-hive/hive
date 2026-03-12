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
  onResult: (transcript: string) => void;
  onError?: (error: string) => void;
}

interface UseVoiceInputReturn {
  isListening: boolean;
  isSupported: boolean;
  startListening: () => void;
  stopListening: () => void;
  error: string | null;
}

export function useVoiceInput({ onResult, onError }: UseVoiceInputOptions): UseVoiceInputReturn {
  const [isListening, setIsListening] = useState(false);
  const [isSupported, setIsSupported] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const hasReceivedSpeech = useRef(false);
  const isStartingRef = useRef(false);
  const hasStartedRef = useRef(false);

  useEffect(() => {
    // Check if SpeechRecognition is supported
    const SpeechRecognitionConstructor = window.SpeechRecognition || window.webkitSpeechRecognition;
    
    if (SpeechRecognitionConstructor) {
      console.log("Speech recognition is supported");
      setIsSupported(true);
      
      // Only create recognition if it doesn't exist
      if (!recognitionRef.current) {
        recognitionRef.current = new SpeechRecognitionConstructor();
        
        const recognition = recognitionRef.current;
        recognition.continuous = false; // Don't keep listening - stop after one result
        recognition.interimResults = true;
        recognition.lang = "en-US";
        recognition.maxAlternatives = 1;

        recognition.onresult = (event: SpeechRecognitionEvent) => {
          console.log("Speech recognition result received");
          hasReceivedSpeech.current = true;
          
          // Get the latest result
          const result = event.results[event.results.length - 1];
          const transcript = result[0].transcript;
          
          console.log(`Transcript (${result.isFinal ? 'final' : 'interim'}):`, transcript);
          
          // Only process final results
          if (result.isFinal && transcript.trim()) {
            console.log("Final transcript:", transcript);
            onResult(transcript);
            // Stop after getting final result
            if (recognitionRef.current) {
              recognitionRef.current.stop();
            }
          }
        };

        recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
          console.error("Speech recognition error:", event.error, event);
          
          // Reset flags
          isStartingRef.current = false;
          hasStartedRef.current = false;
          
          // Ignore aborted errors if we manually stopped or if we haven't started yet
          if (event.error === "aborted") {
            console.log("Recognition was aborted");
            setIsListening(false);
            return;
          }
          
          // Handle specific errors
          if (event.error === "not-allowed" || event.error === "permission-denied") {
            const errorMessage = "Microphone permission denied. Please allow microphone access in your browser settings.";
            setError(errorMessage);
            if (onError) {
              onError(errorMessage);
            }
            alert(errorMessage);
          } else if (event.error === "no-speech") {
            console.log("No speech detected");
            if (!hasReceivedSpeech.current) {
              const errorMessage = "No speech detected. Please try again and speak clearly.";
              if (onError) {
                onError(errorMessage);
              }
            }
          } else {
            const errorMessage = `Speech recognition error: ${event.error}`;
            setError(errorMessage);
            if (onError) {
              onError(errorMessage);
            }
          }
          
          setIsListening(false);
        };

        recognition.onstart = () => {
          console.log("Speech recognition started");
          hasReceivedSpeech.current = false;
          isStartingRef.current = false;
          hasStartedRef.current = true;
          setIsListening(true);
        };

        recognition.onspeechstart = () => {
          console.log("User started speaking");
        };

        recognition.onspeechend = () => {
          console.log("User stopped speaking");
        };

        recognition.onend = () => {
          console.log("Speech recognition ended");
          isStartingRef.current = false;
          hasStartedRef.current = false;
          setIsListening(false);
        };
      }
    } else {
      setIsSupported(false);
      const errorMessage = "Speech recognition is not supported in this browser. Please use Chrome, Edge, or Safari.";
      setError(errorMessage);
      if (onError) {
        onError(errorMessage);
      }
      console.warn(errorMessage);
    }

    // Don't cleanup on every render - only on unmount
    return () => {
      // Only abort if component is actually unmounting
      if (recognitionRef.current) {
        try {
          recognitionRef.current.abort();
        } catch (e) {
          // Ignore errors on cleanup
        }
      }
    };
  }, []); // Empty dependency array - only run once on mount

  const startListening = useCallback(() => {
    if (!isSupported || !recognitionRef.current) {
      console.warn("Speech recognition not supported or not initialized");
      return;
    }

    // Check if already listening or starting
    if (isListening || isStartingRef.current) {
      console.log("Already listening or starting, ignoring start request");
      return;
    }

    try {
      setError(null);
      hasReceivedSpeech.current = false;
      isStartingRef.current = true;
      console.log("Starting speech recognition...");
      recognitionRef.current.start();
      // State will be set by onstart event
    } catch (err: any) {
      // Handle "already started" error
      if (err.message && err.message.includes("already started")) {
        console.log("Recognition already started");
        isStartingRef.current = false;
        return;
      }
      
      const errorMessage = `Failed to start speech recognition: ${err.message || err}`;
      console.error(errorMessage, err);
      setError(errorMessage);
      if (onError) {
        onError(errorMessage);
      }
      setIsListening(false);
      isStartingRef.current = false;
    }
  }, [isSupported, isListening, onError]);

  const stopListening = useCallback(() => {
    if (recognitionRef.current && isListening) {
      console.log("Manually stopping speech recognition");
      try {
        recognitionRef.current.stop();
      } catch (e) {
        console.error("Error stopping recognition:", e);
      }
    }
  }, [isListening]);

  return {
    isListening,
    isSupported,
    startListening,
    stopListening,
    error,
  };
}
