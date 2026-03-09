import { useEffect, useRef, useState } from 'react';
import { useVoiceAgent } from './hooks/useVoiceAgent';
import type { AgentState, LangCode, TranscriptLine, LatencySnapshot } from './hooks/useVoiceAgent';
import './index.css';

const LANG_DISPLAY: Record<LangCode, { label: string; name: string }> = {
  en: { label: 'EN', name: 'English' },
  hi: { label: 'HI', name: 'हिन्दी' },
  ta: { label: 'TA', name: 'தமிழ்' },
};

const STATE_LABEL: Record<AgentState, string> = {
  idle:      'Tap to start',
  listening: 'Listening…',
  thinking:  'Processing…',
  speaking:  'Speaking…',
};

const STATE_DESC: Record<AgentState, string> = {
  idle:      'Start a consultation by tapping the orb',
  listening: 'Speak naturally — say anything to begin',
  thinking:  'Analyzing your symptoms…',
  speaking:  'You can speak anytime to interrupt',
};

function LatencyPanel({ latency }: { latency: LatencySnapshot | null }) {
  if (!latency) return (
    <div className="latency-panel empty">
      <div className="latency-title">Response Time</div>
      <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Waiting for first interaction</div>
    </div>
  );
  const good = latency.total_ms < 450;
  return (
    <div className="latency-panel">
      <div className="latency-title">Response Metrics</div>
      <div className="latency-grid">
        <div className="lat-item">
          <span className="lat-val">{latency.stt_ms}<span className="lat-unit">ms</span></span>
          <span className="lat-label">STT Audio</span>
        </div>
        <div className="lat-item">
          <span className="lat-val">{latency.llm_ms}<span className="lat-unit">ms</span></span>
          <span className="lat-label">Reasoning</span>
        </div>
        <div className="lat-item">
          <span className="lat-val">{latency.tts_ms}<span className="lat-unit">ms</span></span>
          <span className="lat-label">Synthesis</span>
        </div>
        <div className={`lat-item total ${good ? 'good' : 'warn'}`}>
          <span className="lat-val">{latency.total_ms}<span className="lat-unit">ms</span></span>
          <span className="lat-label">{good ? 'Total ✓' : 'Total ⏱'}</span>
        </div>
      </div>
    </div>
  );
}

function TranscriptEntry({ line }: { line: TranscriptLine }) {
  if (line.role === 'system') return <div className="transcript-entry system">{line.text}</div>;
  if (line.role === 'thought') return (
    <div className="transcript-entry thought">
      <span className="thought-label">Agent Thought</span>
      {line.text}
    </div>
  );
  return (
    <div className={`transcript-entry ${line.role}`}>
      {line.text}
    </div>
  );
}

function ReminderPanel() {
  const [status, setStatus] = useState<{ type: 'success' | 'error' | 'info'; msg: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [patients, setPatients] = useState<any[]>([]);
  const [selectedPatient, setSelectedPatient] = useState('');

  const fetchTasks = () => {
    fetch('http://127.0.0.1:8000/api/patients')
      .then(res => res.json())
      .then(data => {
        if (data.patients && data.patients.length > 0) {
           setPatients(data.patients);
           // Only auto-select if nothing is selected or if current selection is not in new list
           setSelectedPatient(curr => {
             if (curr && data.patients.some((p: any) => p.id === curr)) return curr;
             const firstReal = data.patients.find((p: any) => !String(p.id).startsWith('demo_'));
             return firstReal ? firstReal.id : data.patients[0].id;
           });
        } else {
           setStatus({ type: 'info', msg: 'No pending tasks found.' });
        }
      })
      .catch((err) => {
        console.error("Failed to load clinic tasks:", err);
        setStatus({ type: 'error', msg: 'Connection to clinical API failed.' });
      });
  };

  useEffect(() => {
    fetchTasks();
  }, []);

  const trigger = async () => {
    setLoading(true);
    setStatus(null);
    try {
      // Find the full patient object to pass all precomputed context
      const patientObj = patients.find(p => p.id === selectedPatient) || { id: selectedPatient };
      
      const res = await fetch('http://127.0.0.1:8000/api/campaigns/trigger', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          patient_id: selectedPatient,
          ...patientObj // Spreads patient_name, doctor_name, date_str, time_str, etc.
        }),
      });
      const data = await res.json();
      if (data.status === 'error') {
        setStatus({ type: 'error', msg: data.message || 'Error' });
      } else {
        setStatus({ type: 'success', msg: 'Call initiated!' });
        setTimeout(fetchTasks, 2000);
      }
    } catch (err: any) {
      console.error("Trigger failed:", err);
      setStatus({ type: 'error', msg: `System offline: ${err.message || 'Unknown'}` });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="reminder-panel">
      <div className="reminder-header">
        <div className="reminder-icon">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path></svg>
        </div>
        <div>
          <div className="reminder-title">Outbound Campaigns</div>
          <div className="reminder-subtitle">Trigger intelligent follow-up calls</div>
        </div>
      </div>
      
      {patients.length > 0 && (
        <div className="campaign-field-group">
          <label className="campaign-label">Select Clinical Task</label>
          <select 
            className="campaign-select" 
            value={selectedPatient} 
            onChange={(e) => setSelectedPatient(e.target.value)}
          >
            {patients.map(p => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
      )}

      <button className="campaign-button" onClick={trigger} disabled={loading || patients.length === 0}>
        {loading ? <span className="loader-dots">Scheduling</span> : 'Trigger Agent Call'}
      </button>
      {status && <div className={`reminder-status ${status.type}`}>{status.msg}</div>}
    </div>
  );
}

function SessionInfo({ lang, isConnected }: { lang: LangCode; isConnected: boolean }) {
  const langInfo = LANG_DISPLAY[lang];
  return (
    <div className="session-info">
      <div className="session-row">
        <span className="session-label">Connection</span>
        <span className={`session-value ${isConnected ? 'green' : ''}`}>
          <div className={`status-dot ${isConnected ? 'online' : 'offline'}`} />
          {isConnected ? 'Secure' : 'Offline'}
        </span>
      </div>
      <div className="session-row">
        <span className="session-label">Engine</span>
        <span className="session-value">{langInfo.name}</span>
      </div>
      <div className="session-row">
        <span className="session-label">Security</span>
        <span className="session-value" style={{ color: 'var(--accent-cyan)', fontSize: 11, letterSpacing: 0.5 }}>HIPAA COMPLIANT</span>
      </div>
    </div>
  );
}

// ── Medical Stethoscope SVG ────────────────────────────────────────────────────────
const StethoscopeSVG = () => (
  <svg viewBox="0 0 24 24" className="stethoscope path-beat">
    <path 
      d="M19 4v3a7 7 0 0 1-14 0V4M12 11v8M9 21h6" 
      strokeLinecap="round" strokeLinejoin="round"
    />
    <circle cx="12" cy="18" r="2" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const MicSVG = () => (
  <svg viewBox="0 0 24 24" className="mic-icon">
    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
    <path d="M19 10v2a7 7 0 0 1-14 0v-2" stroke="currentColor" strokeWidth="2" fill="none"/>
    <line x1="12" y1="19" x2="12" y2="23" stroke="currentColor" strokeWidth="2"/>
    <line x1="8" y1="23" x2="16" y2="23" stroke="currentColor" strokeWidth="2"/>
  </svg>
);


export default function App() {
  const {
    agentState,
    transcript,
    latency,
    detectedLang,
    isConnected,
    startConsultation,
    endConsultation,
  } = useVoiceAgent();

  const [showReasoning, setShowReasoning] = useState(true);
  const txEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    txEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [transcript]);

  const handleMicClick = () => {
    if (isConnected) endConsultation();
    else startConsultation();
  };

  return (
    <div className="app-root">
      
      {/* ── Left Sidebar Zone ── */}
      <aside className="sidebar">
        <div className="brand">
          <div className="logo-container">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--accent-cyan)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"></path></svg>
          </div>
          <span className="logo-text">2Care<span className="logo-dot">.ai</span></span>
        </div>
        
        <div className="sidebar-group">
          <div className="sidebar-label">Preferences</div>
          <div className="toggle-row">
            <span>Show Reasoning</span>
            <label className="switch">
              <input 
                type="checkbox" 
                checked={showReasoning} 
                onChange={() => setShowReasoning(!showReasoning)} 
              />
              <span className="slider round"></span>
            </label>
          </div>
        </div>

        <SessionInfo lang={detectedLang} isConnected={isConnected} />
        <LatencyPanel latency={latency} />
      </aside>

      {/* ── Center UI / Orb Zone ── */}
      <main className="center-zone">
        <button 
          className={`orb-container orb-${agentState}`} 
          onClick={handleMicClick}
          title="Tap to toggle consultation"
        >
          {agentState !== 'idle' && (
            <>
              <div className="ripple" />
              <div className="ripple" />
              <div className="ripple" />
            </>
          )}
          <div className="orb">
            {agentState === 'thinking' ? <StethoscopeSVG /> : <MicSVG />}
          </div>
        </button>

        <div className="state-label">{STATE_LABEL[agentState]}</div>
        <div className="state-desc">{STATE_DESC[agentState]}</div>
      </main>

      {/* ── Right Panel Zone ── */}
      <aside className="right-panel">
        <div className="transcript-panel">
          <div className="transcript-scroll">
            {transcript.length === 0 && (
              <div className="transcript-entry system" style={{ background: 'transparent', opacity: 0.5 }}>
                Conversation transcript will appear here.
              </div>
            )}
            {transcript
              .filter(line => showReasoning || line.role !== 'thought')
              .map((line, i) => (
                <TranscriptEntry key={i} line={line} />
              ))}
            <div ref={txEndRef} />
          </div>
        </div>
        
        <ReminderPanel />
      </aside>

    </div>
  );
}
