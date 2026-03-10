// v3 — voice-only agent hook: AudioContext decoding + browser TTS for HI/TA
import { useState, useRef, useCallback, useEffect } from 'react';

const WS_URL = "ws://127.0.0.1:8000/ws/voice";

export interface LatencySnapshot {
  stt_ms: number;
  llm_ms: number;
  tts_ms: number;
  total_ms: number;
}

export interface TranscriptLine {
  role: 'user' | 'agent' | 'system' | 'thought';
  text: string;
  ts: number;
}

export type AgentState = 'idle' | 'listening' | 'thinking' | 'speaking';
export type LangCode = 'en' | 'hi' | 'ta';

// ── Shared AudioContext (one per page lifetime) ─────────────────────────────
let sharedAudioCtx: AudioContext | null = null;
function getAudioCtx(): AudioContext {
  if (!sharedAudioCtx || sharedAudioCtx.state === 'closed') {
    sharedAudioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
  }
  return sharedAudioCtx;
}

export function useVoiceAgent() {
  const [agentState, setAgentState]     = useState<AgentState>('idle');
  const agentStateRef = useRef<AgentState>('idle');
  
  const updateAgentState = useCallback((state: AgentState) => {
    setAgentState(state);
    agentStateRef.current = state;
  }, []);

  const [transcript, setTranscript]     = useState<TranscriptLine[]>([]);
  const [latency, setLatency]           = useState<LatencySnapshot | null>(null);
  const [detectedLang, setDetectedLang] = useState<LangCode>('en');
  const [isConnected, setIsConnected]   = useState(false);

  const ws           = useRef<WebSocket | null>(null);
  const recognition  = useRef<any>(null);
  const currentNode  = useRef<AudioBufferSourceNode | null>(null);  // AudioContext source
  const listeningRef = useRef(false);

  // Pre-load voices on mount (browser caches them after first getVoices())
  useEffect(() => {
    if ('speechSynthesis' in window) {
      window.speechSynthesis.getVoices();
      window.speechSynthesis.onvoiceschanged = () => window.speechSynthesis.getVoices();
    }
  }, []);

  const addLine = useCallback((role: TranscriptLine['role'], text: string) => {
    setTranscript(prev => [...prev, { role, text, ts: Date.now() }]);
  }, []);

  const audioQueue = useRef<Blob[]>([]);
  const isPlaying = useRef(false);

  // ── Stop all current audio (Cartesia WAV) ────────────────────
  const stopAllAudio = useCallback(() => {
    // Clear the queue
    audioQueue.current = [];
    isPlaying.current = false;
    // Stop AudioContext source node
    if (currentNode.current) {
      try { currentNode.current.stop(); } catch (_) {}
      currentNode.current = null;
    }
  }, []);

  const processAudioQueue = useCallback(async () => {
    if (isPlaying.current || audioQueue.current.length === 0) return;
    
    isPlaying.current = true;
    const blob = audioQueue.current.shift()!;
    
    try {
      const ctx = getAudioCtx();
      if (ctx.state === 'suspended') await ctx.resume();

      const arrayBuffer = await blob.arrayBuffer();
      const audioBuffer = await ctx.decodeAudioData(arrayBuffer);

      const source = ctx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(ctx.destination);
      currentNode.current = source;

      source.onended = () => {
        currentNode.current = null;
        isPlaying.current = false;
        
        if (audioQueue.current.length > 0) {
          processAudioQueue();
        } else {
          updateAgentState('listening');
          if (listeningRef.current && recognition.current) {
            try { recognition.current.start(); } catch (_) {}
          }
        }
      };
      
      source.start(0);
      updateAgentState('speaking');
      
      if (recognition.current) {
        try { recognition.current.abort(); } catch (_) {}
      }
    } catch (err) {
      console.error('[TTS] AudioContext decode failed:', err);
      isPlaying.current = false;
      processAudioQueue(); // Try next in queue
    }
  }, [updateAgentState]);

  // ── Play WAV bytes via AudioContext (robust, format-agnostic) ──────────────
  const playAudioBytes = useCallback((blob: Blob) => {
    audioQueue.current.push(blob);
    processAudioQueue();
  }, [processAudioQueue]);

  // ── Handle structured WebSocket events from server ─────────────────────────
  const handleServerEvent = useCallback((payload: any) => {
    switch (payload.event) {
      case 'transcript':
        addLine(payload.role as 'user' | 'agent', payload.text);
        break;
      case 'lang':
        setDetectedLang(payload.lang as LangCode);
        break;
      case 'latency':
        setLatency({
          stt_ms:   payload.stt_ms   ?? 0,
          llm_ms:   payload.llm_ms   ?? 0,
          tts_ms:   payload.tts_ms   ?? 0,
          total_ms: payload.total_ms ?? 0,
        });
        break;
      case 'status':
        updateAgentState(payload.state as AgentState);
        break;
      case 'thought':
        addLine('thought', payload.text);
        break;

      default:
        break;
    }
  }, [addLine, updateAgentState]);

  // ── Start voice consultation ────────────────────────────────────────────────
  const startConsultation = useCallback(async () => {
    try {
      // Unlock AudioContext on user gesture (required by browsers)
      const ctx = getAudioCtx();
      if (ctx.state === 'suspended') await ctx.resume();

      ws.current = new WebSocket(WS_URL);

      ws.current.onopen = () => {
        listeningRef.current = true;
        setIsConnected(true);
        updateAgentState('listening');
        // Clear transcript on every new connection for a "Fresh Chat" experience
        setTranscript([]);
        addLine('system', 'Connected — clinical history syncing...');
      };

      ws.current.onmessage = (event) => {
        if (typeof event.data === 'string') {
          try {
            handleServerEvent(JSON.parse(event.data));
          } catch {
            addLine('agent', event.data);
          }
        } else if (event.data instanceof Blob) {
          // Binary = Cartesia WAV audio for English
          playAudioBytes(event.data);
        }
      };

      ws.current.onclose = () => {
        listeningRef.current = false;
        setIsConnected(false);
        updateAgentState('idle');
        stopAllAudio();
        stopRecognition();
        addLine('system', 'Session ended.');
      };

      ws.current.onerror = () => {
        addLine('system', 'Connection error — ensure backend is running on port 8000.');
      };

      // ── Browser SpeechRecognition for STT (fallback / primary in dev) ───────
      const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
      if (SR) {
        recognition.current = new SR();
        recognition.current.continuous     = true;
        recognition.current.interimResults = false;
        recognition.current.lang           = 'en-IN';   // accepts EN, HI, TA too

        recognition.current.onresult = (e: any) => {
          // ANTI-ECHO FEEDBACK LOOP PRECAUTION
          // If the agent is speaking, the microphone will pick up the laptop speakers.
          // This causes it to instantly repeatedly barge-in on itself, chopping the audio
          // into 50ms stutters which sounds exactly like a "garbled/blurred voice".
          if (agentStateRef.current === 'speaking' || agentStateRef.current === 'thinking') {
            return;
          }

          const spoken = e.results[e.results.length - 1][0].transcript.trim();
          if (!spoken || ws.current?.readyState !== WebSocket.OPEN) return;

          // Barge-in: stop whatever is currently playing
          stopAllAudio();

          ws.current.send(JSON.stringify({ event: 'barge_in' }));
          ws.current.send(JSON.stringify({ text: spoken }));
          updateAgentState('thinking');
        };

        recognition.current.onerror = (e: any) => {
          if (e.error !== 'no-speech') console.warn('SpeechRecognition:', e.error);
        };

        recognition.current.onend = () => {
          if (listeningRef.current && recognition.current && agentStateRef.current !== 'speaking') {
            try { recognition.current.start(); } catch (_) {}
          }
        };

        recognition.current.start();
      } else {
        addLine('system', 'Speech Recognition not available — use Chrome or Edge.');
      }
    } catch (err) {
      console.error('Failed to start consultation:', err);
      addLine('system', 'Error: microphone access denied or server offline.');
    }
  }, [addLine, handleServerEvent, playAudioBytes, stopAllAudio, updateAgentState]);

  const stopRecognition = () => {
    if (recognition.current) {
      recognition.current.stop();
      recognition.current = null;
    }
  };

  const endConsultation = useCallback(() => {
    listeningRef.current = false;
    stopAllAudio();
    stopRecognition();
    ws.current?.close();
  }, [stopAllAudio]);

  return {
    agentState,
    transcript,
    latency,
    detectedLang,
    isConnected,
    startConsultation,
    endConsultation,
  };
}
