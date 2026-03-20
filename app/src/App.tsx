// VOXIS V4.0.0 DENSE — Bauhaus Desktop UI
// Copyright © 2026 Glass Stone LLC. All Rights Reserved.
// CEO: Gabriel B. Rodriguez | Powered by Trinity V8.1

import { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import './Bauhaus.css';

// ── Types ──────────────────────────────────────────────────────────────────
type ProcessingMode = 'QUICK' | 'STANDARD' | 'EXTREME';
type UpscaleFactor  = 1 | 2 | 4;
type OutputFormat   = 'WAV' | 'FLAC' | 'MP3';
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
  { id: 7, label: 'EXPORT',   sublabel: '24-bit Output',                 matchStr: 'Finalizing Export' },
];

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

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function fmtTime(s: number): string {
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
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

// ── App ──────────────────────────────────────────────────────────────────────
export default function App() {
  // ── State ───────────────────────────────────────────────────────────────
  const [inputFile,      setInputFile]      = useState<string | null>(null);
  const [outputFile,     setOutputFile]     = useState<string | null>(null);
  const [processingMode, setProcessingMode] = useState<ProcessingMode>('STANDARD');
  const [upscaleFactor,  setUpscaleFactor]  = useState<UpscaleFactor>(4);
  const [outputFormat,   setOutputFormat]   = useState<OutputFormat>('FLAC');
  const [exportFormat,   setExportFormat]   = useState<OutputFormat>('FLAC');
  const [denoiseStrength, setDenoiseStrength] = useState(82);
  const [noiseProfile,   setNoiseProfile]   = useState('AUTO');
  const [restorationSteps, setRestorationSteps] = useState(44);
  const [generationGuidance, setGenerationGuidance] = useState(1.20);
  const [highPrecision,  setHighPrecision]  = useState(true);
  const [stereoOutput,   setStereoOutput]   = useState(true);
  const [ramLimit,       setRamLimit]       = useState(75);
  const [status,         setStatus]         = useState<PipelineStatus>('idle');
  const [currentStep,    setCurrentStep]    = useState(0);
  const [logs,           setLogs]           = useState<string[]>(['SYSTEM READY — SELECT A FILE TO BEGIN']);
  const [elapsedSec,     setElapsedSec]     = useState(0);

  // Auto-EQ readouts (populated by pipeline log parsing)
  const [autoLPF,   setAutoLPF]   = useState<number | null>(null);
  const [autoHPF,   setAutoHPF]   = useState<number | null>(null);
  const [autoVocal, setAutoVocal] = useState<number | null>(null);

  // Update notification
  const [updateStatus, setUpdateStatus] = useState<{ type: string; version?: string; percent?: number } | null>(null);

  // Input audio preview
  const [inputPreviewUrl,    setInputPreviewUrl]    = useState<string | null>(null);
  const [inputIsPlaying,     setInputIsPlaying]     = useState(false);
  const [inputAudioTime,     setInputAudioTime]     = useState(0);
  const [inputAudioDuration, setInputAudioDuration] = useState(0);

  // Output state
  const [_previewUrl,  setPreviewUrl]  = useState<string | null>(null);
  const [saveStatus,   setSaveStatus]  = useState<string | null>(null);
  // _previewUrl reserved for future waveform rendering
  void _previewUrl;

  // Refs
  const logBoxRef      = useRef<HTMLDivElement>(null);
  const inputAudioRef  = useRef<HTMLAudioElement>(null);
  const mountedRef     = useRef(true);
  const timerRef       = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastLogRef     = useRef<number>(0);
  const startTimeRef   = useRef<number>(0);

  // ── Derived ──────────────────────────────────────────────────────────────
  const isRunning  = status === 'running';
  const canProcess = !!inputFile && !isRunning;
  const progress   = Math.round((currentStep / STEPS.length) * 100);
  const elapsedFmt = elapsedSec > 0
    ? ` · ${Math.floor(elapsedSec / 60)}m ${String(elapsedSec % 60).padStart(2, '0')}s`
    : '';

  // Map UI mode → engine mode
  const engineMode = processingMode === 'EXTREME' ? 'EXTREME' : 'HIGH';

  // ── Lifecycle ────────────────────────────────────────────────────────────
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    const box = logBoxRef.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [logs]);

  useEffect(() => {
    window.electronAPI.update.onStatus(setUpdateStatus);
    return () => { window.electronAPI.update.offStatus(); };
  }, []);

  useEffect(() => {
    return () => {
      window.electronAPI.trinity.offLog();
      window.electronAPI.trinity.offDone();
    };
  }, []);

  // ── Log handler ──────────────────────────────────────────────────────────
  const appendLog = useCallback((line: string) => {
    if (!mountedRef.current) return;
    lastLogRef.current = Date.now();
    setLogs(prev => {
      const next = [...prev, line];
      return next.length > 200 ? next.slice(-200) : next;
    });

    const step = detectStep(line);
    if (step !== null) setCurrentStep(step);

    // Parse auto-EQ
    if (line.includes('Auto-EQ:')) {
      const hpfM   = line.match(/HPF=(\d+)Hz/);
      const lpfM   = line.match(/LPF=(\d+)Hz/);
      const vocalM = line.match(/Vocal=([+-]?[\d.]+)dB/);
      if (hpfM)   setAutoHPF(parseInt(hpfM[1]));
      if (lpfM)   setAutoLPF(parseInt(lpfM[1]));
      if (vocalM) setAutoVocal(parseFloat(vocalM[1]));
    }
  }, []);

  // ── Reset helpers ────────────────────────────────────────────────────────
  const resetOutputState = () => {
    setOutputFile(null);
    setPreviewUrl(null);
    setSaveStatus(null);
    setAutoLPF(null);
    setAutoHPF(null);
    setAutoVocal(null);
  };

  const handleNewRestoration = () => {
    setInputFile(null);
    setInputPreviewUrl(null);
    setInputIsPlaying(false);
    setInputAudioTime(0);
    setInputAudioDuration(0);
    resetOutputState();
    setStatus('idle');
    setCurrentStep(0);
    setElapsedSec(0);
    setLogs(['SYSTEM READY — SELECT A FILE TO BEGIN']);
  };

  // ── File Selection ─────────────────────────────────────────────────────
  const handleSelectFile = async () => {
    if (isRunning) return;
    try {
      const selected = await window.electronAPI.dialog.openFile();
      if (!selected) return;
      setInputFile(selected);
      setInputPreviewUrl(window.electronAPI.file.toPreviewUrl(selected));
      setInputAudioTime(0);
      setInputAudioDuration(0);
      setInputIsPlaying(false);
      resetOutputState();
      setCurrentStep(0);
      setStatus('idle');
      setLogs([`LOADED — ${basename(selected)}`, 'READY TO PROCESS.']);
    } catch (e) {
      appendLog(`[ERROR] File dialog: ${errMsg(e)}`);
    }
  };

  // ── Input audio toggle ─────────────────────────────────────────────────
  const toggleInputPlay = () => {
    const a = inputAudioRef.current;
    if (!a) return;
    if (a.paused) { a.play(); } else { a.pause(); }
  };

  // ── Processing ─────────────────────────────────────────────────────────
  const handleProcess = async () => {
    if (!inputFile || isRunning) return;

    setStatus('running');
    setCurrentStep(0);
    setElapsedSec(0);
    resetOutputState();
    setLogs(['>> [VOXIS] Initiating Trinity V8.1 Pipeline...']);

    startTimeRef.current = Date.now();
    lastLogRef.current   = Date.now();
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      if (!mountedRef.current) return;
      const elapsed = Math.floor((Date.now() - startTimeRef.current) / 1000);
      setElapsedSec(elapsed);
      if (Date.now() - lastLogRef.current > 90_000) {
        const m = Math.floor(elapsed / 60), s = elapsed % 60;
        const ts = `${m}m ${String(s).padStart(2, '0')}s`;
        lastLogRef.current = Date.now();
        setLogs(prev => {
          const msg = `[VOXIS] Neural inference running... ${ts} elapsed — please wait`;
          const next = [...prev, msg];
          return next.length > 200 ? next.slice(-200) : next;
        });
      }
    }, 1000);

    window.electronAPI.trinity.offLog();
    window.electronAPI.trinity.offDone();
    window.electronAPI.trinity.onLog(appendLog);
    window.electronAPI.trinity.onDone(setOutputFile);

    try {
      const result = await window.electronAPI.trinity.runEngine({
        filePath:     inputFile,
        mode:         engineMode,
        stereoWidth:  stereoOutput ? 0.5 : 0.0,
        outputFormat,
        ramLimit,
      });

      if (mountedRef.current) {
        setStatus('done');
        setCurrentStep(STEPS.length);
        setOutputFile(result);
        setPreviewUrl(window.electronAPI.file.toPreviewUrl(result));
        setExportFormat(outputFormat);
        appendLog('>> [VOXIS] RESTORATION COMPLETE');
        appendLog(`>> OUTPUT: ${basename(result)}`);
      }
    } catch (e) {
      if (mountedRef.current) {
        setStatus('error');
        appendLog(`>> [ERROR] ${errMsg(e)}`);
      }
    } finally {
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
      window.electronAPI.trinity.offLog();
      window.electronAPI.trinity.offDone();
    }
  };

  // ── Cancel ─────────────────────────────────────────────────────────────
  const handleCancel = async () => {
    if (!isRunning) return;
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    try {
      await window.electronAPI.trinity.cancelEngine();
      setStatus('idle');
      setCurrentStep(0);
      setElapsedSec(0);
    } catch (e) {
      appendLog(`[ERROR] Cancel failed: ${errMsg(e)}`);
    }
  };

  // ── Save As ────────────────────────────────────────────────────────────
  const handleSaveAs = async () => {
    if (!outputFile) return;
    const ext = exportFormat.toLowerCase() as string;
    const dest = await window.electronAPI.dialog.saveFile(basename(outputFile), ext);
    if (!dest) return;
    try {
      await window.electronAPI.file.copy(outputFile, dest);
      setSaveStatus(`Saved → ${basename(dest)}`);
      appendLog(`>> [VOXIS] Exported to: ${dest}`);
    } catch (e) {
      appendLog(`>> [ERROR] Save failed: ${errMsg(e)}`);
    }
  };

  // ── Reveal ────────────────────────────────────────────────────────────
  const handleRevealOutput = async () => {
    if (!outputFile) return;
    try {
      await window.electronAPI.shell.openPath(outputFile);
    } catch {
      appendLog(`[INFO] Output: ${outputFile}`);
    }
  };

  // ── Render ─────────────────────────────────────────────────────────────
  return (
    <div className="app-shell">

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
      <header className="app-header">
        <div className="header-brand-group">
          <Logo />
          <span className="brand-voxis">VOXIS</span>
          <span className="brand-dense">DENSE</span>
        </div>
        <div className="header-subtitle">
          AUDIO RESTORATION V4.0.0 | BY GLASS STONE
        </div>
        <div className="header-online">
          <span className="online-dot" />
          ONLINE
        </div>
      </header>

      {/* ── BODY ── */}
      <div className="app-body">

        {/* ── SIDEBAR ── */}
        <aside className="sidebar">

          {/* Processing Mode */}
          <div className="sb-section">
            <div className="sb-label">PROCESSING MODE</div>
            {(['QUICK', 'STANDARD', 'EXTREME'] as ProcessingMode[]).map(m => (
              <motion.button
                key={m}
                className={`mode-btn ${processingMode === m ? 'active' : ''} ${m === 'EXTREME' && processingMode === m ? 'extreme' : ''}`}
                onClick={() => setProcessingMode(m)}
                disabled={isRunning}
                whileTap={!isRunning ? { scale: 0.97 } : {}}
              >
                {m}
              </motion.button>
            ))}
          </div>

          {/* Upscale Factor */}
          <div className="sb-section">
            <div className="sb-label">UPSCALE FACTOR</div>
            <div className="btn-row">
              {([1, 2, 4] as UpscaleFactor[]).map(f => (
                <motion.button
                  key={f}
                  className={`factor-btn ${upscaleFactor === f ? 'active' : ''}`}
                  onClick={() => setUpscaleFactor(f)}
                  disabled={isRunning}
                  whileTap={!isRunning ? { scale: 0.95 } : {}}
                >
                  {f}x
                </motion.button>
              ))}
            </div>
          </div>

          {/* Output Format */}
          <div className="sb-section">
            <div className="sb-label">OUTPUT FORMAT</div>
            <div className="btn-row">
              {(['WAV', 'FLAC', 'MP3'] as OutputFormat[]).map(f => (
                <motion.button
                  key={f}
                  className={`format-btn ${outputFormat === f ? 'active' : ''}`}
                  onClick={() => { setOutputFormat(f); setExportFormat(f); }}
                  disabled={isRunning}
                  whileTap={!isRunning ? { scale: 0.95 } : {}}
                >
                  {f}
                </motion.button>
              ))}
            </div>
          </div>

          {/* Denoise Strength */}
          <div className="sb-section">
            <div className="sb-label-row">
              <span className="sb-label no-mb">DENOISE STRENGTH</span>
              <span className="sb-value val-red">{denoiseStrength}%</span>
            </div>
            <input
              type="range" min={0} max={100} value={denoiseStrength}
              onChange={e => setDenoiseStrength(+e.target.value)}
              className="bauhaus-range"
              disabled={isRunning}
            />
          </div>

          {/* Noise Profile */}
          <div className="sb-section">
            <div className="sb-label">NOISE PROFILE</div>
            <select
              className="bauhaus-select"
              value={noiseProfile}
              onChange={e => setNoiseProfile(e.target.value)}
              disabled={isRunning}
            >
              <option value="AUTO">AUTO (SMART)</option>
              <option value="MUSIC">MUSIC</option>
              <option value="PODCAST">PODCAST</option>
              <option value="VOICE">VOICE</option>
            </select>
          </div>

          {/* Restoration Steps */}
          <div className="sb-section">
            <div className="sb-label-row">
              <span className="sb-label no-mb lbl-red">RESTORATION STEPS</span>
              <span className="sb-value">{restorationSteps}</span>
            </div>
            <input
              type="range" min={8} max={64} value={restorationSteps}
              onChange={e => setRestorationSteps(+e.target.value)}
              className="bauhaus-range range-red"
              disabled={isRunning}
            />
          </div>

          {/* Generation Guidance */}
          <div className="sb-section">
            <div className="sb-label-row">
              <span className="sb-label no-mb lbl-red">GENERATION GUIDANCE</span>
              <span className="sb-value">{generationGuidance.toFixed(2)}</span>
            </div>
            <input
              type="range" min={0.5} max={3.0} step={0.05} value={generationGuidance}
              onChange={e => setGenerationGuidance(+e.target.value)}
              className="bauhaus-range range-red"
              disabled={isRunning}
            />
          </div>

          {/* High Precision */}
          <div className="sb-section">
            <div className="toggle-item">
              <span className="sb-label no-mb">HIGH PRECISION</span>
              <label className="toggle-switch">
                <input type="checkbox" checked={highPrecision}
                  onChange={e => setHighPrecision(e.target.checked)} disabled={isRunning} />
                <span className="toggle-track green" />
              </label>
            </div>
          </div>

          {/* Stereo Output */}
          <div className="sb-section">
            <div className="toggle-item">
              <span className="sb-label no-mb">STEREO OUTPUT</span>
              <label className="toggle-switch">
                <input type="checkbox" checked={stereoOutput}
                  onChange={e => setStereoOutput(e.target.checked)} disabled={isRunning} />
                <span className="toggle-track blue" />
              </label>
            </div>
          </div>

          {/* RAM Limit */}
          <div className="sb-section sb-section-ram">
            <div className="sb-label-row">
              <span className="sb-label no-mb">RAM USAGE LIMIT</span>
              <span className="sb-value val-ram">{ramLimit}%</span>
            </div>
            <input
              type="range" min={25} max={100} step={5} value={ramLimit}
              onChange={e => setRamLimit(+e.target.value)}
              className="bauhaus-range range-ram"
              disabled={isRunning}
            />
            <div className="ram-hint">
              {ramLimit <= 50 ? 'LOW — Slower, saves memory'
               : ramLimit <= 75 ? 'BALANCED — Recommended'
               : 'MAX — Fastest, high memory'}
            </div>
          </div>

        </aside>

        {/* ── MAIN PANEL ── */}
        <main className="main-panel">

          {/* ── File Strip ── */}
          {inputFile ? (
            <div className="file-strip">
              <motion.button
                className="file-play-btn"
                onClick={toggleInputPlay}
                whileHover={{ scale: 1.1 }}
                whileTap={{ scale: 0.9 }}
              >
                {inputIsPlaying ? '||' : '\u25B6'}
              </motion.button>
              <div className="file-info">
                <div className="file-name">{basename(inputFile).toUpperCase()}</div>
                <div className="file-meta">
                  {inputFile.split('.').pop()?.toUpperCase() ?? 'AUDIO'}
                </div>
              </div>
              <div className="waveform-bar">
                <div className="waveform-inner" />
              </div>
              <div className="file-duration">
                {fmtTime(inputAudioTime)} / {fmtTime(inputAudioDuration)}
              </div>
              <audio
                ref={inputAudioRef}
                src={inputPreviewUrl || undefined}
                onPlay={() => setInputIsPlaying(true)}
                onPause={() => setInputIsPlaying(false)}
                onEnded={() => { setInputIsPlaying(false); setInputAudioTime(0); }}
                onTimeUpdate={() => setInputAudioTime(inputAudioRef.current?.currentTime ?? 0)}
                onLoadedMetadata={() => setInputAudioDuration(inputAudioRef.current?.duration ?? 0)}
              />
            </div>
          ) : (
            <div className="file-strip file-strip-empty">
              <motion.button
                className="btn-select-file"
                onClick={handleSelectFile}
                whileHover={{ scale: 1.02, y: -1 }}
                whileTap={{ scale: 0.98 }}
              >
                + SELECT AUDIO FILE
              </motion.button>
            </div>
          )}

          {/* ── Content Area ── */}
          <div className="content-area">

            {/* Pipeline + Logs (when NOT done) */}
            {status !== 'done' && (
              <div className="pipeline-content">

                {/* Progress bar */}
                <AnimatePresence>
                  {isRunning && (
                    <motion.div
                      className="progress-strip"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                    >
                      <motion.div
                        className="progress-fill"
                        animate={{ width: `${progress}%` }}
                        transition={{ type: 'spring', stiffness: 80, damping: 20 }}
                      />
                    </motion.div>
                  )}
                </AnimatePresence>

                {/* Status line */}
                <div className="status-line">
                  {isRunning ? (
                    <motion.span
                      className="status-running"
                      animate={{ opacity: [1, 0.6, 1] }}
                      transition={{ repeat: Infinity, duration: 1.5 }}
                    >
                      {currentStep === 0
                        ? `\u25B6 STARTING...${elapsedFmt}`
                        : `\u25B6 STEP ${currentStep}/${STEPS.length} — ${STEPS[currentStep - 1]?.label ?? 'PROCESSING'}${elapsedFmt}`
                      }
                    </motion.span>
                  ) : status === 'error' ? (
                    <span className="status-error">\u25A0 ENGINE ERROR — CHECK LOG</span>
                  ) : (
                    <span className="status-idle">\u25CB STANDBY</span>
                  )}
                </div>

                {/* Auto EQ readouts (when available) */}
                {(autoLPF !== null || autoHPF !== null || autoVocal !== null) && (
                  <div className="eq-readouts">
                    <div className="eq-chip">
                      <span className="eq-chip-label">LPF</span>
                      <span className="eq-chip-val">{autoLPF !== null ? `${(autoLPF / 1000).toFixed(1)}kHz` : '—'}</span>
                    </div>
                    <div className="eq-chip">
                      <span className="eq-chip-label">HPF</span>
                      <span className="eq-chip-val">{autoHPF !== null ? `${autoHPF}Hz` : '—'}</span>
                    </div>
                    <div className="eq-chip">
                      <span className="eq-chip-label">VOCAL</span>
                      <span className="eq-chip-val">{autoVocal !== null ? `${autoVocal > 0 ? '+' : ''}${autoVocal}dB` : '—'}</span>
                    </div>
                  </div>
                )}

                {/* Pipeline steps (compact) */}
                {isRunning && (
                  <div className="pipeline-steps-compact">
                    {STEPS.map(step => {
                      const isActive = currentStep === step.id && isRunning;
                      const isDone   = currentStep > step.id;
                      return (
                        <div
                          key={step.id}
                          className={`ps-step ${isActive ? 'ps-active' : ''} ${isDone ? 'ps-done' : ''}`}
                        >
                          <span className="ps-indicator">
                            {isDone ? '\u25A0' : isActive ? '\u25B6' : '\u25CB'}
                          </span>
                          <span className="ps-label">{step.label}</span>
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* Log viewer */}
                <div className="log-viewer" ref={logBoxRef}>
                  {logs.map((line, i) => (
                    <div
                      key={i}
                      className={`log-line ${
                        line.includes('[ERROR]') ? 'log-error'
                        : line.startsWith('>>') ? 'log-step'
                        : ''
                      }`}
                    >
                      {line}
                    </div>
                  ))}
                </div>

                {/* Action bar */}
                <div className="action-bar">
                  {!isRunning ? (
                    <motion.button
                      className="btn-initiate"
                      onClick={handleProcess}
                      disabled={!canProcess}
                      whileHover={canProcess ? { scale: 1.02, y: -2 } : {}}
                      whileTap={canProcess ? { scale: 0.98 } : {}}
                    >
                      INITIATE RESTORATION
                    </motion.button>
                  ) : (
                    <motion.button
                      className="btn-cancel"
                      onClick={handleCancel}
                      whileHover={{ scale: 1.02, y: -2 }}
                      whileTap={{ scale: 0.98 }}
                    >
                      CANCEL
                    </motion.button>
                  )}

                  {status === 'error' && inputFile && (
                    <motion.button
                      className="btn-retry"
                      onClick={handleProcess}
                      whileHover={{ scale: 1.02 }}
                      whileTap={{ scale: 0.98 }}
                    >
                      RETRY
                    </motion.button>
                  )}
                </div>
              </div>
            )}

            {/* ── Completion Overlay ── */}
            <AnimatePresence>
              {status === 'done' && outputFile && (
                <motion.div
                  className="completion-overlay"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                >
                  <motion.div
                    className="completion-card"
                    initial={{ scale: 0.9, y: 20 }}
                    animate={{ scale: 1, y: 0 }}
                    transition={{ type: 'spring', stiffness: 300, damping: 25 }}
                  >
                    <div className="completion-check">{'\u2713'}</div>
                    <h2 className="completion-title">RESTORATION COMPLETE</h2>
                    <p className="completion-sub">48kHz / Stereo</p>

                    <div className="export-section">
                      <div className="export-label">EXPORT FORMAT</div>
                      <div className="export-btns">
                        {(['WAV', 'FLAC', 'MP3'] as OutputFormat[]).map(f => (
                          <motion.button
                            key={f}
                            className={`export-fmt-btn ${exportFormat === f ? 'active' : ''}`}
                            onClick={() => setExportFormat(f)}
                            whileTap={{ scale: 0.95 }}
                          >
                            {f}
                          </motion.button>
                        ))}
                      </div>
                      <div className="export-quality">High Quality Stream Ready</div>
                    </div>

                    <motion.button
                      className="btn-export"
                      onClick={handleSaveAs}
                      whileHover={{ scale: 1.03, y: -2 }}
                      whileTap={{ scale: 0.97 }}
                    >
                      EXPORT AUDIO ({exportFormat})
                    </motion.button>

                    <motion.button
                      className="btn-new-restore"
                      onClick={handleNewRestoration}
                      whileHover={{ opacity: 0.6 }}
                    >
                      START NEW RESTORATION
                    </motion.button>

                    <motion.button
                      className="btn-reveal-output"
                      onClick={handleRevealOutput}
                      whileHover={{ opacity: 0.6 }}
                    >
                      REVEAL IN FINDER
                    </motion.button>

                    {saveStatus && <div className="save-status">{saveStatus}</div>}
                  </motion.div>
                </motion.div>
              )}
            </AnimatePresence>

          </div>
        </main>
      </div>
    </div>
  );
}
