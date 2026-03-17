// VOXIS V4.0.0 DENSE — Bauhaus Desktop UI
// Copyright © 2026 Glass Stone LLC. All Rights Reserved.
// CEO: Gabriel B. Rodriguez | Powered by Trinity V8.1

import { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence, type Variants } from 'framer-motion';
import './Bauhaus.css';

// ── Types ──────────────────────────────────────────────────────────────────
type DenoiseMode   = 'HIGH' | 'EXTREME';
type OutputFormat  = 'WAV' | 'FLAC';
type PipelineStatus = 'idle' | 'running' | 'done' | 'error';

interface Step {
  id:       number;
  label:    string;
  sublabel: string;
  matchStr: string;
}

// ── Constants ───────────────────────────────────────────────────────────────
const STEPS: Step[] = [
  { id: 1, label: 'INGEST',   sublabel: 'FFmpeg Universal Decode',      matchStr: '[1/6]' },
  { id: 2, label: 'SEPARATE', sublabel: 'BS-RoFormer Voice Isolation',   matchStr: '[2/6]' },
  { id: 3, label: 'ANALYZE',  sublabel: 'Spectrum + Auto-EQ Profile',    matchStr: '[3/6]' },
  { id: 4, label: 'DENOISE',  sublabel: 'VoiceRestore Enhancement',      matchStr: '[4/6]' },
  { id: 5, label: 'UPSCALE',  sublabel: 'AudioSR Diffusion → 48kHz',    matchStr: '[5/6]' },
  { id: 6, label: 'MASTER',   sublabel: 'Harman Curve Mastering',        matchStr: '[6/6]' },
  { id: 7, label: 'EXPORT',   sublabel: '24-bit WAV / FLAC Output',      matchStr: 'Finalizing Export' },
];

const FADE_UP: Variants = {
  hidden:  { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0, transition: { type: 'spring', stiffness: 300, damping: 24 } },
};

// ── Helpers ─────────────────────────────────────────────────────────────────
function basename(p: string): string {
  return p.split(/[\\/]/).pop() ?? p;
}

function detectStep(line: string): number | null {
  for (const s of STEPS) {
    if (line.includes(s.matchStr)) return s.id;
  }
  if (line.includes('Restoration Complete')) return 7;
  return null;
}

// ── Logo ─────────────────────────────────────────────────────────────────────
const Logo = () => (
  <svg viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg" className="logo-svg">
    <rect x="0" y="0" width="100" height="100" fill="#FFFFFF" />
    <line x1="20" y1="0" x2="20" y2="100" stroke="#141414" strokeWidth="3" />
    <line x1="80" y1="0" x2="80" y2="100" stroke="#141414" strokeWidth="3" />
    <line x1="0" y1="80" x2="100" y2="80" stroke="#141414" strokeWidth="3" />
    <line x1="0" y1="20" x2="100" y2="20" stroke="#141414" strokeWidth="3" />
    <line x1="50" y1="0" x2="50" y2="100" stroke="#141414" strokeWidth="2" />
    <circle cx="20" cy="80" r="10" fill="#E03E3E" stroke="#141414" strokeWidth="3" />
    <polygon points="20,80 35,65 35,95" fill="#2C6BB6" stroke="#141414" strokeWidth="3" />
    <polygon points="35,65 65,35 75,45 45,75" fill="#F0C420" stroke="#141414" strokeWidth="3" />
    <polygon points="45,75 75,45 85,55 55,85" fill="#F0C420" stroke="#141414" strokeWidth="3" />
    <rect x="65" y="10" width="20" height="25" fill="#2C6BB6" stroke="#141414" strokeWidth="3" />
    <polygon points="65,10 65,35 85,35" fill="#E03E3E" stroke="#141414" strokeWidth="3" />
    <line x1="35" y1="65" x2="45" y2="75" stroke="#141414" strokeWidth="3" />
    <line x1="50" y1="50" x2="60" y2="60" stroke="#141414" strokeWidth="3" />
    <line x1="65" y1="35" x2="75" y2="45" stroke="#141414" strokeWidth="3" />
  </svg>
);

// ── Helpers ─────────────────────────────────────────────────────────────────
function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

// ── App ──────────────────────────────────────────────────────────────────────
export default function App() {
  const [inputFile,    setInputFile]    = useState<string | null>(null);
  const [outputFile,   setOutputFile]   = useState<string | null>(null);
  const [mode,         setMode]         = useState<DenoiseMode>('HIGH');
  const [outputFormat, setOutputFormat] = useState<OutputFormat>('WAV');
  const [status,       setStatus]       = useState<PipelineStatus>('idle');
  const [currentStep,  setCurrentStep]  = useState(0);
  const [logs,         setLogs]         = useState<string[]>(['SYSTEM READY — SELECT A FILE TO BEGIN']);

  // Auto-EQ — populated by pipeline log parsing (read-only)
  const [autoLPF,   setAutoLPF]   = useState<number | null>(null);
  const [autoHPF,   setAutoHPF]   = useState<number | null>(null);
  const [autoVocal, setAutoVocal] = useState<number | null>(null);

  // Update notification
  const [updateStatus, setUpdateStatus] = useState<{ type: string; version?: string; percent?: number } | null>(null);

  // Preview player
  const [previewUrl,    setPreviewUrl]    = useState<string | null>(null);
  const [isPlaying,     setIsPlaying]     = useState(false);
  const [audioTime,     setAudioTime]     = useState(0);
  const [audioDuration, setAudioDuration] = useState(0);
  const [saveStatus,    setSaveStatus]    = useState<string | null>(null);

  const logEndRef  = useRef<HTMLDivElement>(null);
  const audioRef   = useRef<HTMLAudioElement>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  // Subscribe to update notifications from main process
  useEffect(() => {
    window.electronAPI.update.onStatus(setUpdateStatus);
  }, []);

  // Cleanup IPC listeners on unmount
  useEffect(() => {
    return () => {
      window.electronAPI.trinity.offLog();
      window.electronAPI.trinity.offDone();
    };
  }, []);

  const appendLog = useCallback((line: string) => {
    if (!mountedRef.current) return;
    setLogs(prev => {
      const next = [...prev, line];
      return next.length > 150 ? next.slice(-150) : next;
    });

    const step = detectStep(line);
    if (step !== null) setCurrentStep(step);

    // Parse auto-EQ from: "[NoiseProfiler] Auto-EQ: HPF=80Hz | LPF=14000Hz | Vocal=+2.1dB"
    if (line.includes('Auto-EQ:')) {
      const hpfM   = line.match(/HPF=(\d+)Hz/);
      const lpfM   = line.match(/LPF=(\d+)Hz/);
      const vocalM = line.match(/Vocal=([+-]?[\d.]+)dB/);
      if (hpfM)   setAutoHPF(parseInt(hpfM[1]));
      if (lpfM)   setAutoLPF(parseInt(lpfM[1]));
      if (vocalM) setAutoVocal(parseFloat(vocalM[1]));
    }
  }, []);

  // ── Reset preview/save state ───────────────────────────────────────────────
  const resetOutputState = () => {
    setOutputFile(null);
    setPreviewUrl(null);
    setIsPlaying(false);
    setAudioTime(0);
    setAudioDuration(0);
    setSaveStatus(null);
    setAutoLPF(null);
    setAutoHPF(null);
    setAutoVocal(null);
  };

  // ── File Selection ─────────────────────────────────────────────────────────
  const handleSelectFile = async () => {
    if (status === 'running') return;
    try {
      const selected = await window.electronAPI.dialog.openFile();
      if (!selected) return;
      setInputFile(selected);
      resetOutputState();
      setCurrentStep(0);
      setStatus('idle');
      setLogs([`LOADED — ${basename(selected)}`, 'READY TO PROCESS.']);
    } catch (e) {
      appendLog(`[ERROR] File dialog: ${errMsg(e)}`);
    }
  };

  // ── Processing ─────────────────────────────────────────────────────────────
  const handleProcess = async () => {
    if (!inputFile || status === 'running') return;

    setStatus('running');
    setCurrentStep(0);
    resetOutputState();
    setLogs(['>> [VOXIS] Initiating Trinity V8.1 Pipeline...']);

    // Detach any stale listeners before attaching fresh ones
    window.electronAPI.trinity.offLog();
    window.electronAPI.trinity.offDone();

    window.electronAPI.trinity.onLog(appendLog);
    window.electronAPI.trinity.onDone(setOutputFile);

    try {
      const result = await window.electronAPI.trinity.runEngine({
        filePath:     inputFile,
        mode,
        stereoWidth:  0.5,
        outputFormat,
      });

      if (mountedRef.current) {
        setStatus('done');
        setCurrentStep(STEPS.length);
        setOutputFile(result);
        setPreviewUrl(window.electronAPI.file.toPreviewUrl(result));
        appendLog('>> [VOXIS] RESTORATION COMPLETE');
        appendLog(`>> OUTPUT: ${basename(result)}`);
      }
    } catch (e) {
      if (mountedRef.current) {
        setStatus('error');
        appendLog(`>> [ERROR] ${errMsg(e)}`);
      }
    } finally {
      window.electronAPI.trinity.offLog();
      window.electronAPI.trinity.offDone();
    }
  };

  // ── Reveal Output ──────────────────────────────────────────────────────────
  const handleRevealOutput = async () => {
    if (!outputFile) return;
    try {
      await window.electronAPI.shell.openPath(outputFile);
    } catch (e) {
      appendLog(`[INFO] Output: ${outputFile}`);
    }
  };

  // ── Save As ────────────────────────────────────────────────────────────────
  const handleSaveAs = async () => {
    if (!outputFile) return;
    const ext  = outputFile.endsWith('.flac') ? 'flac' : 'wav';
    const dest = await window.electronAPI.dialog.saveFile(basename(outputFile), ext);
    if (!dest) return;
    try {
      await window.electronAPI.file.copy(outputFile, dest);
      setSaveStatus(`Saved → ${basename(dest)}`);
      appendLog(`>> [VOXIS] Saved to: ${dest}`);
    } catch (e) {
      appendLog(`>> [ERROR] Save failed: ${errMsg(e)}`);
    }
  };

  // ── Audio player controls ──────────────────────────────────────────────────
  const togglePlay = () => {
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) { a.play(); } else { a.pause(); }
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const a = audioRef.current;
    if (!a) return;
    a.currentTime = Number(e.target.value);
    setAudioTime(a.currentTime);
  };

  const fmtTime = (s: number) =>
    `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

  const isRunning  = status === 'running';
  const canProcess = !!inputFile && !isRunning;
  const progress   = Math.round((currentStep / STEPS.length) * 100);

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="bauhaus-container">

      {/* ── UPDATE BANNER ── */}
      <AnimatePresence>
        {updateStatus && (
          <motion.div
            className="update-banner"
            initial={{ opacity: 0, y: -32 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -32 }}
            transition={{ type: 'spring', stiffness: 400, damping: 30 }}
          >
            {updateStatus.type === 'available' && (
              <>
                <span>UPDATE AVAILABLE — v{updateStatus.version}</span>
                <motion.button className="btn-update" onClick={() => window.electronAPI.update.download()}
                  whileHover={{ scale: 1.04 }} whileTap={{ scale: 0.97 }}>
                  DOWNLOAD
                </motion.button>
              </>
            )}
            {updateStatus.type === 'progress' && (
              <span>DOWNLOADING UPDATE... {updateStatus.percent ?? 0}%</span>
            )}
            {updateStatus.type === 'downloaded' && (
              <>
                <span>UPDATE READY — RESTART TO APPLY</span>
                <motion.button className="btn-update btn-update-install" onClick={() => window.electronAPI.update.install()}
                  whileHover={{ scale: 1.04 }} whileTap={{ scale: 0.97 }}>
                  RESTART &amp; INSTALL
                </motion.button>
              </>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── HEADER ── */}
      <header className="header-grid">
        <div className="header-logo"><Logo /></div>
        <div className="header-brand">
          <span className="brand-voxis">VOXIS</span>
          <span className="brand-version">V4.0.0</span>
          <span className="brand-dense">DENSE</span>
        </div>
        <div className="header-divider" />
        <div className="header-meta">
          <div className="meta-row"><span className="meta-label">BUILT BY</span><span className="meta-value">GLASS STONE LLC</span></div>
          <div className="meta-row"><span className="meta-label">CEO</span><span className="meta-value">GABRIEL B. RODRIGUEZ</span></div>
          <div className="meta-row"><span className="meta-label">STUDIO</span><span className="meta-value">GLASS STONE · 2026</span></div>
        </div>
        <div className="header-engine">
          <span className="engine-badge">TRINITY V8.1</span>
        </div>
      </header>

      {/* ── MAIN GRID ── */}
      <motion.main
        className="main-grid"
        initial="hidden"
        animate="visible"
        variants={{ visible: { transition: { staggerChildren: 0.1 } } }}
      >

        {/* ── LEFT COLUMN ── */}
        <div className="col-left">

          {/* 01 — Input Source */}
          <motion.section className="module module-input" variants={FADE_UP}>
            <div className="module-number">01</div>
            <div className="module-title-wrap">
              <h3 className="module-title" style={{ marginBottom: 0, borderBottom: 'none' }}>INPUT SOURCE</h3>
              <motion.div className="accent-red" style={{ borderRadius: '50%' }}
                whileHover={{ scale: 1.2, rotate: 90 }} whileTap={{ scale: 0.9 }}
                transition={{ type: 'spring', stiffness: 400, damping: 10 }}
              />
            </div>
            <div style={{ height: 2, background: 'var(--black)', marginBottom: '1rem' }} />

            <motion.button
              className={`btn-file ${inputFile ? 'has-file' : ''}`}
              onClick={handleSelectFile}
              disabled={isRunning}
              whileHover={!isRunning ? { scale: 1.02, y: -2, x: -2 } : {}}
              whileTap={!isRunning ? { scale: 0.98, y: 2, x: 2 } : {}}
              transition={{ type: 'spring', stiffness: 500, damping: 30 }}
            >
              <span className="btn-file-icon">{inputFile ? '◆' : '+'}</span>
              <span className="btn-file-label">
                {inputFile ? basename(inputFile) : 'SELECT LOCAL MEDIA'}
              </span>
            </motion.button>

            <div className="format-chips">
              {['WAV', 'MP3', 'FLAC', 'MP4', 'MOV', 'MKV'].map(f => (
                <span key={f} className="chip">{f}</span>
              ))}
            </div>

            {inputFile && <div className="file-path-display">{inputFile}</div>}
          </motion.section>

          {/* 02 — Processing Matrix */}
          <motion.section className="module module-processing" variants={FADE_UP}>
            <div className="module-number">02</div>
            <div className="module-title-wrap">
              <h3 className="module-title" style={{ marginBottom: 0, borderBottom: 'none' }}>PROCESSING MATRIX</h3>
              <motion.div className="accent-red"
                style={{ background: 'var(--yellow)', width: 16, height: 16 }}
                whileHover={{ scale: 1.2, rotate: -45 }} whileTap={{ scale: 0.9 }}
                transition={{ type: 'spring', stiffness: 400, damping: 10 }}
              />
            </div>
            <div style={{ height: 2, background: 'var(--black)', marginBottom: '1rem' }} />

            <div className="processing-group">
              <label className="control-label">NOISE REDUCTION MODE</label>
              <div className="toggle-row">
                {(['HIGH', 'EXTREME'] as DenoiseMode[]).map(m => (
                  <motion.button
                    key={m}
                    className={`btn-toggle ${m === 'EXTREME' ? 'danger' : ''} ${mode === m ? (m === 'EXTREME' ? 'active danger-active' : 'active') : ''}`}
                    onClick={() => setMode(m)}
                    disabled={isRunning}
                    whileHover={!isRunning && mode !== m ? { y: -1, x: -1 } : {}}
                    whileTap={!isRunning ? { scale: 0.97, y: 2, x: 2 } : {}}
                  >
                    <span className="toggle-indicator" />
                    {m === 'HIGH' ? 'STD. DENOISE' : 'EXTREME REDUCTION'}
                  </motion.button>
                ))}
              </div>
            </div>

            <div className="processing-group">
              <label className="control-label">OUTPUT FORMAT</label>
              <div className="toggle-row">
                {(['WAV', 'FLAC'] as OutputFormat[]).map(f => (
                  <motion.button
                    key={f}
                    className={`btn-toggle ${outputFormat === f ? 'active' : ''}`}
                    onClick={() => setOutputFormat(f)}
                    disabled={isRunning}
                    whileHover={!isRunning && outputFormat !== f ? { y: -1, x: -1 } : {}}
                    whileTap={!isRunning ? { scale: 0.97, y: 2, x: 2 } : {}}
                  >
                    {f === 'WAV' ? 'WAV 24-BIT' : 'FLAC LOSSLESS'}
                  </motion.button>
                ))}
              </div>
            </div>
          </motion.section>

        </div>{/* /col-left */}

        {/* ── RIGHT COLUMN ── */}
        <div className="col-right">

          {/* 03 — Auto EQ */}
          <motion.section className="module module-eq" variants={FADE_UP}>
            <div className="module-number">03</div>
            <div className="module-title-wrap">
              <h3 className="module-title" style={{ marginBottom: 0, borderBottom: 'none' }}>AUTO EQ</h3>
              <motion.div className="accent-yellow"
                style={{ borderBottomColor: 'var(--blue)' }}
                whileHover={{ scale: 1.2, rotate: 180 }} whileTap={{ scale: 0.9 }}
                transition={{ type: 'spring', stiffness: 400, damping: 10 }}
              />
            </div>
            <div style={{ height: 2, background: 'var(--black)', marginBottom: '1rem' }} />
            <div className="eq-auto-note">SPECTRAL ANALYSIS → DYNAMIC EQ</div>

            {/* Low Pass */}
            <div className="eq-group">
              <label className="control-label">LOW PASS FILTER</label>
              <motion.div className="eq-auto-value"
                animate={autoLPF !== null ? { opacity: 1, scale: 1 } : { opacity: 0.4, scale: 0.95 }}
                transition={{ type: 'spring', stiffness: 300, damping: 20 }}
              >
                <span className="eq-auto-reading">
                  {autoLPF !== null ? `${(autoLPF / 1000).toFixed(1)}kHz` : '—'}
                </span>
                <span className="eq-auto-badge">{autoLPF !== null ? 'DETECTED' : 'WAITING'}</span>
              </motion.div>
              {autoLPF !== null && (
                <div className="eq-bar-track">
                  <motion.div className="eq-bar-fill eq-bar-lpf"
                    initial={{ width: '100%' }}
                    animate={{ width: `${(autoLPF / 20000) * 100}%` }}
                    transition={{ type: 'spring', stiffness: 200, damping: 25 }}
                  />
                </div>
              )}
            </div>

            {/* High Pass */}
            <div className="eq-group">
              <label className="control-label">HIGH PASS FILTER</label>
              <motion.div className="eq-auto-value"
                animate={autoHPF !== null ? { opacity: 1, scale: 1 } : { opacity: 0.4, scale: 0.95 }}
                transition={{ type: 'spring', stiffness: 300, damping: 20 }}
              >
                <span className="eq-auto-reading">
                  {autoHPF !== null
                    ? (autoHPF >= 1000 ? `${(autoHPF / 1000).toFixed(1)}kHz` : `${autoHPF}Hz`)
                    : '—'}
                </span>
                <span className="eq-auto-badge">{autoHPF !== null ? 'DETECTED' : 'WAITING'}</span>
              </motion.div>
              {autoHPF !== null && (
                <div className="eq-bar-track">
                  <motion.div className="eq-bar-fill eq-bar-hpf"
                    initial={{ width: '0%' }}
                    animate={{ width: `${Math.min(100, (autoHPF / 500) * 100)}%` }}
                    transition={{ type: 'spring', stiffness: 200, damping: 25 }}
                  />
                </div>
              )}
            </div>

            {/* Vocal Presence */}
            <div className="eq-group">
              <label className="control-label">VOCAL PRESENCE</label>
              <motion.div className="eq-auto-value"
                animate={autoVocal !== null ? { opacity: 1, scale: 1 } : { opacity: 0.4, scale: 0.95 }}
                transition={{ type: 'spring', stiffness: 300, damping: 20 }}
              >
                <span className="eq-auto-reading">
                  {autoVocal !== null ? `${autoVocal > 0 ? '+' : ''}${autoVocal}dB` : '—'}
                </span>
                <span className={`eq-auto-badge ${autoVocal !== null && autoVocal > 0 ? 'boost' : autoVocal !== null && autoVocal < 0 ? 'cut' : ''}`}>
                  {autoVocal !== null
                    ? (autoVocal > 0 ? 'BOOST' : autoVocal < 0 ? 'CUT' : 'FLAT')
                    : 'WAITING'}
                </span>
              </motion.div>
              {autoVocal !== null && (
                <div className="eq-bar-track vocal-track">
                  <motion.div
                    className={`eq-bar-fill eq-bar-vocal ${autoVocal >= 0 ? 'positive' : 'negative'}`}
                    initial={{ width: '50%' }}
                    animate={{ width: `${Math.min(100, Math.max(0, 50 + (autoVocal / 12) * 100))}%` }}
                    transition={{ type: 'spring', stiffness: 200, damping: 25 }}
                  />
                </div>
              )}
            </div>
          </motion.section>

          {/* 04 — Pipeline Monitor */}
          <motion.section className="module module-pipeline" variants={FADE_UP}>
            <div className="module-number">04</div>
            <div className="module-title-wrap">
              <h3 className="module-title" style={{ marginBottom: 0, borderBottom: 'none' }}>PIPELINE MONITOR</h3>
              <motion.svg
                width="20" height="20" viewBox="0 0 24 24" fill="var(--black)"
                animate={isRunning ? { rotate: 360 } : { rotate: 0 }}
                transition={{ repeat: isRunning ? Infinity : 0, duration: 4, ease: 'linear' }}
                whileHover={{ scale: 1.2 }}
              >
                <path d="M19.14,12.94c0.04-0.3,0.06-0.61,0.06-0.94c0-0.32-0.02-0.64-0.06-0.94l2.03-1.58c0.18-0.14,0.23-0.41,0.12-0.61l-1.92-3.32c-0.12-0.22-0.37-0.29-0.59-0.22l-2.39,0.96c-0.5-0.38-1.03-0.7-1.62-0.94L14.4,2.81c-0.04-0.24-0.24-0.41-0.48-0.41h-3.84c-0.24,0-0.43,0.17-0.47,0.41L9.25,5.35C8.66,5.59,8.12,5.92,7.63,6.29L5.24,5.33c-0.22-0.08-0.47,0-0.59,0.22L2.73,8.87C2.62,9.08,2.66,9.34,2.86,9.48l2.03,1.58C4.84,11.36,4.8,11.69,4.8,12s0.02,0.64,0.06,0.94l-2.03,1.58c-0.18,0.14-0.23,0.41-0.12,0.61l1.92,3.32c0.12,0.22,0.37,0.29,0.59,0.22l2.39-0.96c0.5,0.38,1.03,0.7,1.62,0.94l0.36,2.54c0.05,0.24,0.24,0.41,0.48,0.41h3.84c0.24,0,0.43-0.17,0.47-0.41l0.36-2.54c0.59-0.24,1.13-0.56,1.62-0.94l2.39,0.96c0.22,0.08,0.47,0,0.59-0.22l1.92-3.32c0.12-0.22,0.07-0.49-0.12-0.61L19.14,12.94z M12,15.6c-1.98,0-3.6-1.62-3.6-3.6s1.62-3.6,3.6-3.6s3.6,1.62,3.6,3.6S13.98,15.6,12,15.6z" />
              </motion.svg>
            </div>
            <div style={{ height: 2, background: 'var(--black)', marginBottom: '1rem' }} />

            <div className="pipeline-steps">
              {STEPS.map(step => {
                const isActive  = currentStep === step.id && isRunning;
                const isDone    = currentStep > step.id || (status === 'done' && currentStep >= step.id);
                const isPending = currentStep < step.id && !isActive;
                return (
                  <motion.div
                    key={step.id}
                    className={`pipeline-step ${isActive ? 'step-active' : ''} ${isDone ? 'step-done' : ''} ${isPending ? 'step-pending' : ''}`}
                    initial={{ opacity: 0, x: -12 }}
                    animate={{
                      opacity: isPending ? 0.45 : 1,
                      x: 0,
                      scale: isActive ? 1.02 : 1,
                    }}
                    transition={{ type: 'spring', stiffness: 400, damping: 28, delay: step.id * 0.04 }}
                    layout
                  >
                    <motion.div
                      className="step-indicator"
                      animate={isActive ? { scale: [1, 1.3, 1] } : { scale: 1 }}
                      transition={isActive ? { repeat: Infinity, duration: 1.2, ease: 'easeInOut' } : {}}
                    >
                      {isDone ? '■' : isActive ? '▶' : '○'}
                    </motion.div>
                    <div className="step-body">
                      <span className="step-label">{step.label}</span>
                      <AnimatePresence mode="wait">
                        <motion.span
                          key={isActive ? 'active' : 'default'}
                          className="step-sublabel"
                          initial={{ opacity: 0, y: 4 }}
                          animate={{ opacity: isActive ? 1 : 0.65, y: 0 }}
                          exit={{ opacity: 0, y: -4 }}
                          transition={{ duration: 0.2 }}
                        >
                          {isActive ? `Processing ${step.sublabel}...` : step.sublabel}
                        </motion.span>
                      </AnimatePresence>
                    </div>
                    <div className="step-num">{String(step.id).padStart(2, '0')}</div>
                  </motion.div>
                );
              })}
            </div>
          </motion.section>

        </div>{/* /col-right */}

        {/* ── 05 — ACTION ZONE (full width) ── */}
        <motion.section className={`module action-zone ${status}`} variants={FADE_UP}>
          <div className="action-top">
            <div className="action-left">
              <div className="module-number light">05</div>
              <h3 className="module-title light">EXECUTE &amp; EXPORT</h3>
            </div>
            <div className="action-controls">
              <motion.button
                className={`btn-main ${isRunning ? 'btn-processing' : ''}`}
                onClick={handleProcess}
                disabled={!canProcess}
                whileHover={canProcess ? { scale: 1.02, y: -2, x: -2 } : {}}
                whileTap={canProcess ? { scale: 0.98, y: 3, x: 3 } : {}}
              >
                {isRunning
                  ? <><span className="spin-indicator">◈</span> PROCESSING...</>
                  : 'INITIATE RESTORATION'}
              </motion.button>

              <AnimatePresence>
                {outputFile && (
                  <>
                    <motion.button
                      className="btn-reveal"
                      onClick={handleSaveAs}
                      initial={{ opacity: 0, scale: 0.8 }}
                      animate={{ opacity: 1, scale: 1 }}
                      whileHover={{ scale: 1.02, y: -2, x: -2 }}
                      whileTap={{ scale: 0.98, y: 2, x: 2 }}
                    >
                      SAVE AS
                    </motion.button>
                    <motion.button
                      className="btn-reveal"
                      onClick={handleRevealOutput}
                      initial={{ opacity: 0, scale: 0.8 }}
                      animate={{ opacity: 1, scale: 1 }}
                      whileHover={{ scale: 1.02, y: -2, x: -2 }}
                      whileTap={{ scale: 0.98, y: 2, x: 2 }}
                    >
                      REVEAL
                    </motion.button>
                  </>
                )}
              </AnimatePresence>
            </div>
          </div>

          <AnimatePresence>
            {isRunning && (
              <motion.div
                className="progress-bar-outer"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
              >
                <motion.div
                  className="progress-bar-inner"
                  animate={{ width: `${progress}%` }}
                  transition={{ type: 'spring', stiffness: 80, damping: 20 }}
                />
              </motion.div>
            )}
          </AnimatePresence>

          <div className="status-badges">
            <AnimatePresence mode="wait">
              {status === 'done' && outputFile && (
                <motion.div
                  key="done"
                  className="badge badge-done"
                  initial={{ opacity: 0, scale: 0.8, y: 6 }}
                  animate={{ opacity: 1, scale: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.8 }}
                  transition={{ type: 'spring', stiffness: 400, damping: 22 }}
                >
                  ■ COMPLETE — {basename(outputFile)}
                </motion.div>
              )}
              {status === 'error' && (
                <motion.div
                  key="error"
                  className="badge badge-error"
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0 }}
                >
                  ■ ENGINE ERROR — CHECK LOG
                </motion.div>
              )}
              {status === 'idle' && (
                <motion.div
                  key="idle"
                  className="badge badge-idle"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                >
                  ○ STANDBY
                </motion.div>
              )}
              {isRunning && (
                <motion.div
                  key="running"
                  className="badge badge-running"
                  initial={{ opacity: 0, scale: 0.8 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0 }}
                >
                  ▶ STEP {currentStep}/{STEPS.length} — {STEPS[Math.max(0, currentStep - 1)]?.label ?? 'INIT'}
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* ── Audio Preview ── */}
          <AnimatePresence>
            {previewUrl && outputFile && (
              <motion.div
                className="preview-panel"
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ type: 'spring', stiffness: 260, damping: 28 }}
              >
                <audio
                  ref={audioRef}
                  src={previewUrl}
                  onPlay={() => setIsPlaying(true)}
                  onPause={() => setIsPlaying(false)}
                  onEnded={() => setIsPlaying(false)}
                  onTimeUpdate={() => setAudioTime(audioRef.current?.currentTime ?? 0)}
                  onLoadedMetadata={() => setAudioDuration(audioRef.current?.duration ?? 0)}
                />

                <div className="preview-filename">◆ {basename(outputFile)}</div>

                <div className="preview-controls">
                  <motion.button
                    className="btn-play"
                    onClick={togglePlay}
                    whileHover={{ scale: 1.08 }}
                    whileTap={{ scale: 0.92 }}
                  >
                    {isPlaying ? '▌▌' : '▶'}
                  </motion.button>

                  <span className="preview-time">{fmtTime(audioTime)}</span>

                  <input
                    type="range"
                    className="preview-seek"
                    min={0}
                    max={audioDuration || 1}
                    step={0.1}
                    value={audioTime}
                    onChange={handleSeek}
                  />

                  <span className="preview-time muted">{fmtTime(audioDuration)}</span>
                </div>

                {saveStatus && (
                  <div className="preview-save-status">{saveStatus}</div>
                )}
              </motion.div>
            )}
          </AnimatePresence>

          <div className="log-viewer">
            {logs.map((line, i) => (
              <motion.div
                key={`${i}-${line.slice(0, 20)}`}
                className={`log-line ${
                  line.startsWith('[ERROR]') || line.startsWith('>> [ERROR]')
                    ? 'log-error'
                    : line.startsWith('>>')
                    ? 'log-step'
                    : ''
                }`}
                initial={{ opacity: 0, x: -6 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.15 }}
              >
                {line}
              </motion.div>
            ))}
            <div ref={logEndRef} />
          </div>
        </motion.section>

      </motion.main>

      {/* ── FOOTER ── */}
      <footer className="legal-footer">
        <span>POWERED BY TRINITY V8.1</span>
        <span className="footer-sep">|</span>
        <span>COPYRIGHT © 2026 GLASS STONE LLC</span>
        <span className="footer-sep">|</span>
        <span>CEO: GABRIEL B. RODRIGUEZ</span>
      </footer>

    </div>
  );
}
