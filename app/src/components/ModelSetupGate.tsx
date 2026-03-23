// VOXIS 4.0 DENSE — Model Setup Gate
// Shows download confirmation + progress when ML models are missing.
// Renders children (main App) once all models are installed.

import { useState, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { invoke } from '@tauri-apps/api/core';
import { listen, type UnlistenFn } from '@tauri-apps/api/event';

type GateState = 'checking' | 'needs_models' | 'downloading' | 'ready' | 'error';

interface ModelInfo {
  id: string;
  name: string;
  stage: string;
  size_mb: number;
  installed: boolean;
  required: boolean;
  description: string;
}

interface ModelStatus {
  all_installed: boolean;
  models: ModelInfo[];
  total_size_mb: number;
  missing_size_mb: number;
  models_dir: string;
}

interface DownloadEvent {
  event: string;
  id?: string;
  name?: string;
  pct?: number;
  mb_done?: number;
  mb_total?: number;
  downloaded?: number;
  index?: number;
  attempt?: number;
  max_retries?: number;
  failed?: number;
  total?: number;
  total_size_mb?: number;
  error?: string;
  failed_models?: string[];
}

interface Props { children: React.ReactNode; }

const FONT = 'Helvetica Neue, Helvetica, Arial, sans-serif';
const BG = '#EDE8D0';
const RED = '#C9382D';
const DARK = '#1A1A1A';
const MUTED = '#888070';

export default function ModelSetupGate({ children }: Props) {
  const [state, setState] = useState<GateState>('checking');
  const [status, setStatus] = useState<ModelStatus | null>(null);
  const [currentModel, setCurrentModel] = useState('');
  const [progress, setProgress] = useState(0);
  const [downloaded, setDownloaded] = useState(0);
  const [totalModels, setTotalModels] = useState(0);
  const [errorMsg, setErrorMsg] = useState('');
  const [logs, setLogs] = useState<string[]>([]);
  const unlistenRef = useRef<UnlistenFn | null>(null);
  const logUnlistenRef = useRef<UnlistenFn | null>(null);

  // ── Check model status on mount ────────────────────────────────────────

  useEffect(() => {
    checkModels();
    return () => {
      unlistenRef.current?.();
      logUnlistenRef.current?.();
    };
  }, []);

  const checkModels = async () => {
    setState('checking');
    try {
      const json = await invoke<string>('check_models');
      const parsed: ModelStatus = JSON.parse(json);
      setStatus(parsed);

      if (parsed.all_installed) {
        setState('ready');
      } else {
        setState('needs_models');
      }
    } catch (err) {
      // If sidecar isn't available yet (first install), show download prompt
      setState('needs_models');
      setStatus({
        all_installed: false,
        models: [],
        total_size_mb: 9800,
        missing_size_mb: 9800,
        models_dir: '~/.voxis/dependencies/models',
      });
    }
  };

  // ── Start download ─────────────────────────────────────────────────────

  const startDownload = async () => {
    setState('downloading');
    setProgress(0);
    setDownloaded(0);
    setLogs([]);

    // Listen for structured model-download events
    unlistenRef.current = await listen<string>('model-download', (event) => {
      try {
        const data: DownloadEvent = JSON.parse(event.payload);
        handleDownloadEvent(data);
      } catch {}
    });

    // Listen for log messages
    logUnlistenRef.current = await listen<string>('model-log', (event) => {
      setLogs(prev => [...prev.slice(-50), event.payload]);
    });

    try {
      await invoke<string>('download_models');
      // Re-check after download completes
      await checkModels();
    } catch (err: any) {
      setErrorMsg(err?.toString() || 'Download failed');
      setState('error');
    } finally {
      unlistenRef.current?.();
      logUnlistenRef.current?.();
    }
  };

  const handleDownloadEvent = (data: DownloadEvent) => {
    switch (data.event) {
      case 'start':
        setTotalModels(data.total || 0);
        break;
      case 'downloading':
        setCurrentModel(data.name || '');
        if (data.index !== undefined && data.total) {
          setDownloaded(data.index);
        }
        break;
      case 'progress':
        setProgress(data.pct || 0);
        setCurrentModel(`${data.name} — ${data.mb_done?.toFixed(0)}/${data.mb_total?.toFixed(0)} MB`);
        break;
      case 'downloaded':
        setDownloaded(prev => prev + 1);
        break;
      case 'complete':
        if (data.failed && data.failed > 0) {
          setErrorMsg(`${data.failed} model(s) failed: ${data.failed_models?.join(', ')}`);
          setState('error');
        }
        break;
      case 'error':
        setErrorMsg(data.error || 'Unknown error');
        break;
      case 'retry':
        setLogs(prev => [
          ...prev.slice(-50),
          `Retrying ${data.name} (attempt ${data.attempt}/${data.max_retries})...`,
        ]);
        break;
    }
  };

  // ── Render: Checking ───────────────────────────────────────────────────

  if (state === 'checking') {
    return (
      <div style={containerStyle}>
        <Spinner />
        <Label>CHECKING MODELS...</Label>
      </div>
    );
  }

  // ── Render: Ready → pass through to children ──────────────────────────

  if (state === 'ready') {
    return <>{children}</>;
  }

  // ── Render: Needs Models (confirmation screen) ─────────────────────────

  if (state === 'needs_models') {
    const missingCount = status?.models.filter(m => !m.installed).length
      || status?.models.length || 0;
    const sizeGB = ((status?.missing_size_mb || 9800) / 1024).toFixed(1);

    return (
      <div style={containerStyle}>
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          style={cardStyle}
        >
          <div style={{ fontSize: '0.75rem', fontWeight: 700, letterSpacing: '1.5px', color: MUTED, textTransform: 'uppercase' as const, marginBottom: '1.5rem' }}>
            MODEL SETUP REQUIRED
          </div>

          <h2 style={{ fontFamily: FONT, fontSize: '1.3rem', fontWeight: 300, color: DARK, margin: '0 0 0.8rem 0', lineHeight: 1.3 }}>
            VOXIS needs to download AI models<br />before processing audio.
          </h2>

          <p style={{ fontFamily: FONT, fontSize: '0.85rem', color: MUTED, margin: '0 0 1.5rem 0', lineHeight: 1.6 }}>
            {missingCount > 0 ? `${missingCount} models` : 'Models'} · ~{sizeGB} GB total · one-time download
          </p>

          {status?.models && status.models.length > 0 && (
            <div style={{ marginBottom: '1.5rem', width: '100%', maxWidth: 420 }}>
              {status.models.map((m) => (
                <div key={m.id} style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  padding: '0.35rem 0', borderBottom: '1px solid rgba(0,0,0,0.06)',
                  fontFamily: FONT, fontSize: '0.8rem',
                }}>
                  <span style={{ color: DARK, fontWeight: 500 }}>{m.name}</span>
                  <span style={{ color: m.installed ? '#4A7C59' : RED, fontWeight: 600, fontSize: '0.75rem', letterSpacing: '1px' }}>
                    {m.installed ? 'INSTALLED' : `${m.size_mb >= 1000 ? (m.size_mb / 1024).toFixed(1) + ' GB' : m.size_mb + ' MB'}`}
                  </span>
                </div>
              ))}
            </div>
          )}

          <motion.button
            onClick={startDownload}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            style={buttonStyle}
          >
            DOWNLOAD MODELS
          </motion.button>

          <p style={{ fontFamily: FONT, fontSize: '0.75rem', color: MUTED, marginTop: '1rem', textAlign: 'center' as const }}>
            Models are stored in ~/.voxis/ and can be reused across updates.
          </p>
        </motion.div>
      </div>
    );
  }

  // ── Render: Downloading ────────────────────────────────────────────────

  if (state === 'downloading') {
    return (
      <div style={containerStyle}>
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          style={cardStyle}
        >
          <div style={{ fontSize: '0.75rem', fontWeight: 700, letterSpacing: '1.5px', color: MUTED, textTransform: 'uppercase' as const, marginBottom: '1.5rem' }}>
            DOWNLOADING MODELS
          </div>

          <div style={{ width: '100%', maxWidth: 380, marginBottom: '1rem' }}>
            <div style={{
              width: '100%', height: 4, background: 'rgba(0,0,0,0.08)',
              borderRadius: 2, overflow: 'hidden',
            }}>
              <motion.div
                style={{ height: '100%', background: RED, borderRadius: 2 }}
                animate={{ width: `${progress}%` }}
                transition={{ duration: 0.3 }}
              />
            </div>
          </div>

          <p style={{ fontFamily: FONT, fontSize: '0.85rem', color: DARK, margin: '0 0 0.3rem 0', fontWeight: 500 }}>
            {currentModel || 'Preparing...'}
          </p>

          <p style={{ fontFamily: FONT, fontSize: '0.75rem', color: MUTED, margin: 0 }}>
            {totalModels > 0 ? `${downloaded}/${totalModels} models` : 'Starting download...'}
            {progress > 0 ? ` · ${progress.toFixed(0)}%` : ''}
          </p>

          {logs.length > 0 && (
            <div style={{
              marginTop: '1.2rem', width: '100%', maxWidth: 420,
              maxHeight: 100, overflowY: 'auto' as const,
              fontFamily: 'SF Mono, Menlo, monospace', fontSize: '0.75rem',
              color: MUTED, lineHeight: 1.6, padding: '0.5rem',
              background: 'rgba(0,0,0,0.03)', borderRadius: 4,
            }}>
              {logs.slice(-8).map((l, i) => <div key={i}>{l}</div>)}
            </div>
          )}
        </motion.div>
      </div>
    );
  }

  // ── Render: Error ──────────────────────────────────────────────────────

  return (
    <div style={containerStyle}>
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        style={cardStyle}
      >
        <div style={{ fontSize: '0.75rem', fontWeight: 700, letterSpacing: '1.5px', color: RED, textTransform: 'uppercase' as const, marginBottom: '1rem' }}>
          DOWNLOAD ERROR
        </div>

        <p style={{ fontFamily: FONT, fontSize: '0.85rem', color: DARK, margin: '0 0 1rem 0', textAlign: 'center' as const, maxWidth: 380 }}>
          {errorMsg || 'Some models failed to download.'}
        </p>

        <div style={{ display: 'flex', gap: '0.8rem' }}>
          <motion.button
            onClick={startDownload}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            style={buttonStyle}
          >
            RETRY DOWNLOAD
          </motion.button>
          <motion.button
            onClick={checkModels}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            style={{ ...buttonStyle, background: 'transparent', color: DARK, border: `1px solid ${MUTED}` }}
          >
            RE-CHECK
          </motion.button>
        </div>
      </motion.div>
    </div>
  );
}

// ── Sub-components ───────────────────────────────────────────────────────────

function Spinner() {
  return (
    <motion.div
      style={{ width: 8, height: 8, borderRadius: '50%', background: RED }}
      animate={{ scale: [1, 1.6, 1], opacity: [1, 0.4, 1] }}
      transition={{ repeat: Infinity, duration: 1.2 }}
    />
  );
}

function Label({ children }: { children: string }) {
  return (
    <span style={{
      fontFamily: FONT, fontSize: '0.75rem', fontWeight: 700,
      letterSpacing: '1.5px', color: MUTED, textTransform: 'uppercase' as const,
      marginTop: '1rem',
    }}>
      {children}
    </span>
  );
}

// ── Styles ───────────────────────────────────────────────────────────────────

const containerStyle: React.CSSProperties = {
  display: 'flex', flexDirection: 'column',
  alignItems: 'center', justifyContent: 'center',
  height: '100vh', background: BG, gap: '1rem',
  fontFamily: FONT,
};

const cardStyle: React.CSSProperties = {
  display: 'flex', flexDirection: 'column',
  alignItems: 'center', padding: '2.5rem 3rem',
  maxWidth: 520, width: '90%',
};

const buttonStyle: React.CSSProperties = {
  fontFamily: FONT, fontSize: '0.75rem', fontWeight: 700,
  letterSpacing: '1.5px', textTransform: 'uppercase',
  background: RED, color: '#FFFFFF', border: 'none',
  padding: '0.7rem 2rem', borderRadius: 3, cursor: 'pointer',
};
