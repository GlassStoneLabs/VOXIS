// VOXIS V4.0.0 DENSE — Bauhaus Desktop UI (Tauri)
// Copyright © 2026 Glass Stone LLC. All Rights Reserved.
// CEO: Gabriel B. Rodriguez | Powered by Trinity V8.2

import { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { invoke } from '@tauri-apps/api/core';
import { listen, type UnlistenFn } from '@tauri-apps/api/event';
import { convertFileSrc } from '@tauri-apps/api/core';
import './Bauhaus.css';

// ── Types ──────────────────────────────────────────────────────────────────
type ProcessingMode = 'QUICK' | 'STANDARD' | 'EXTREME';
type UpscaleFactor  = 1 | 2 | 4;
type OutputFormat   = 'WAV' | 'WAV24' | 'WAV32' | 'FLAC' | 'ALAC' | 'MP3';
type PipelineStatus = 'idle' | 'running' | 'done' | 'error';

interface Step {
  id:          number;
  label:       string;
  sublabel:    string;
  matchStr:    string;
  description: string;
}

// ── Constants ───────────────────────────────────────────────────────────────
const STEPS: Step[] = [
  { id: 1, label: 'GATEWAY',  sublabel: 'FFmpeg Universal Decode',       matchStr: '[1/6]',
    description: 'Decodes any audio or video format into a standardized 44.1kHz stereo WAV using FFmpeg. Supports MP3, FLAC, AAC, OGG, MP4, MOV, and more.' },
  { id: 2, label: 'PRISM',    sublabel: 'GS-PRISM Voice Isolation',     matchStr: '[2/6]',
    description: 'Splits the signal like light through glass — GS-PRISM isolates vocals from background music and instruments using the Glass Stone proprietary separation model.' },
  { id: 3, label: 'SPECTRAL', sublabel: 'Spectrum + Auto-EQ Profile',    matchStr: '[3/6]',
    description: 'Reads the full frequency spectrum to detect noise characteristics and compute optimal EQ settings. Auto-generates high-pass, low-pass, and vocal presence adjustments.' },
  { id: 4, label: 'PURIFY',   sublabel: 'GS-CRYSTAL Neural Restore',    matchStr: '[4/6]',
    description: 'Glass Stone purity pass — GS-CRYSTAL removes background noise, hiss, hum, and artifacts using a 301M parameter transformer-diffusion model that reconstructs clean speech.' },
  { id: 5, label: 'ASCEND',   sublabel: 'GS-ASCEND Diffusion → 48kHz', matchStr: '[5/6]',
    description: 'GS-ASCEND elevates audio to studio-quality 48kHz using Glass Stone latent diffusion. Recovers lost high-frequency detail and restores clarity that compression destroyed.' },
  { id: 6, label: 'TEMPER',   sublabel: 'GS-TEMPER Harman Mastering',   matchStr: '[6/6]',
    description: 'Like tempered glass — hardened and perfected. GS-TEMPER applies Harman curve EQ, adaptive HPF/LPF, multiband compression (−18 dB / 4:1), and LUFS loudness normalisation to −14 LUFS streaming standard.' },
  { id: 7, label: 'CAST',     sublabel: '24-bit Output',                 matchStr: 'Finalizing Export',
    description: 'Cast in glass — the final permanent form. Multiplexes the restored audio into WAV, FLAC, or MP3 at 24-bit depth with full metadata preservation.' },
];

// ── Helpers ─────────────────────────────────────────────────────────────────
function basename(p: string): string {
  return p.split(/[\\/]/).pop() ?? p;
}

function detectStep(line: string): number | null {
  for (const s of STEPS) {
    if (line.includes(s.matchStr)) return s.id;
  }
  if (line.includes('Restoration Complete') || line.includes('RESTORATION COMPLETE')) return 7;
  return null;
}

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function fmtTime(s: number): string {
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
}

// ── Logo (matches official VOXIS DENSE Bauhaus mark) ────────────────────────
const Logo = () => (
  <svg viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg" className="logo-svg">
    {/* Black cross structure */}
    <line x1="30" y1="0" x2="30" y2="120" stroke="#1A1A1A" strokeWidth="5" />
    <line x1="0" y1="48" x2="120" y2="48" stroke="#1A1A1A" strokeWidth="5" />
    <line x1="0" y1="78" x2="120" y2="78" stroke="#1A1A1A" strokeWidth="5" />
    {/* Red rectangle (upper-left) */}
    <rect x="8" y="10" width="52" height="50" fill="#C9382D" stroke="#1A1A1A" strokeWidth="2" />
    {/* Small blue circle (upper-right) */}
    <circle cx="68" cy="38" r="10" fill="#2B5EA0" stroke="#1A1A1A" strokeWidth="2" />
    {/* Small yellow triangle (upper-right) */}
    <polygon points="85,28 98,48 72,48" fill="#F5B731" stroke="#1A1A1A" strokeWidth="2" />
    {/* Large blue circle (lower-left) */}
    <circle cx="28" cy="82" r="20" fill="#2B5EA0" stroke="#1A1A1A" strokeWidth="2" />
    {/* Large yellow triangle (lower-center) */}
    <polygon points="60,52 90,110 30,110" fill="#F5B731" stroke="#1A1A1A" strokeWidth="2" />
  </svg>
);

// ── App ──────────────────────────────────────────────────────────────────────

// Distinct semantic color per stage — Bauhaus + extended palette
const STAGE_COLORS = [
  '#2B5EA0',  // 1 GATEWAY  — blue
  '#C9382D',  // 2 PRISM    — red
  '#D97706',  // 3 SPECTRAL — amber
  '#0D9488',  // 4 PURIFY   — teal
  '#7C3AED',  // 5 ASCEND   — violet
  '#EA580C',  // 6 TEMPER   — orange
  '#22C55E',  // 7 CAST     — green
];

const AnimatedStageProgress = ({ currentStep }: { currentStep: number }) => {
  const progressPct = currentStep === 0 ? 0 : Math.round((currentStep / STEPS.length) * 100);
  const activeColor = currentStep > 0 ? STAGE_COLORS[currentStep - 1] : STAGE_COLORS[0];

  // Bauhaus geometric shapes per stage
  const BAUHAUS_SHAPES = ['circle', 'square', 'triangle', 'circle', 'square', 'triangle', 'circle'] as const;

  return (
    <div className="stage-progress-container">
      {/* Overall progress bar */}
      <div className="stage-overall-bar">
        <motion.div
          className="stage-overall-fill"
          style={{ backgroundColor: activeColor }}
          animate={{ width: `${progressPct}%` }}
          transition={{ type: 'spring', stiffness: 80, damping: 20 }}
        />
      </div>
      <div className="stage-overall-label" style={{ color: activeColor }}>
        {currentStep === 0 ? 'INITIALIZING...' : `STAGE ${currentStep} OF ${STEPS.length} — ${STEPS[currentStep - 1]?.label}`}
      </div>

      {/* Stage list */}
      <div className="stage-list">
        {STEPS.map((step, i) => {
          const isActive = currentStep === step.id;
          const isDone = currentStep > step.id;
          const color = STAGE_COLORS[i];
          const shape = BAUHAUS_SHAPES[i];

          return (
            <motion.div
              key={step.id}
              className={`stage-block ${isActive ? 'active' : ''} ${isDone ? 'done' : ''}`}
              style={{ '--stage-color': color } as React.CSSProperties}
              initial={{ opacity: 0.2, x: -6 }}
              animate={{
                opacity: isActive ? 1 : isDone ? 0.85 : 0.2,
                x: 0,
                scale: isActive ? 1 : 0.98,
              }}
              transition={{ duration: 0.3, ease: [0.25, 1, 0.5, 1] }}
            >
              {/* Bauhaus diagonal stripe sweep (active only) */}
              {isActive && (
                <motion.div
                  className="stage-block-stripe"
                  style={{ '--stage-color': color } as React.CSSProperties}
                  initial={{ x: '-100%' }}
                  animate={{ x: '200%' }}
                  transition={{ repeat: Infinity, duration: 2.5, ease: 'linear' }}
                />
              )}

              {/* Colored left accent strip — animated height on active */}
              <motion.div
                className="stage-block-accent"
                style={{ backgroundColor: isDone || isActive ? color : 'transparent' }}
                animate={{ scaleY: isActive ? 1 : isDone ? 1 : 0 }}
                transition={{ duration: 0.3 }}
              />

              {/* Bauhaus geometric number badge */}
              <motion.div
                className={`stage-block-num bauhaus-${shape}`}
                style={{
                  backgroundColor: isDone || isActive ? color : 'transparent',
                  color: isDone || isActive ? '#fff' : 'var(--gray-2)',
                  borderColor: isDone || isActive ? color : 'var(--gray-2)',
                }}
                animate={{
                  rotate: isActive ? [0, 6, -6, 0] : 0,
                  scale: isActive ? [1, 1.12, 1] : isDone ? 1 : 0.9,
                }}
                transition={isActive
                  ? { rotate: { repeat: Infinity, duration: 3, ease: 'easeInOut' },
                      scale: { repeat: Infinity, duration: 1.5, ease: 'easeInOut' } }
                  : { duration: 0.25 }
                }
              >
                {isDone ? '✓' : step.id}
              </motion.div>

              <div className="stage-block-content">
                <motion.div
                  className="stage-block-title"
                  style={{ color: isActive ? color : undefined }}
                  animate={{ letterSpacing: isActive ? '2px' : '1.2px' }}
                  transition={{ duration: 0.4 }}
                >
                  {step.label}
                </motion.div>
                {isActive && (
                  <motion.div
                    className="stage-block-sub"
                    initial={{ opacity: 0, y: 4, x: -8 }}
                    animate={{ opacity: 1, y: 0, x: 0 }}
                    transition={{ delay: 0.1, duration: 0.3 }}
                  >
                    {step.sublabel}
                  </motion.div>
                )}
              </div>

              {/* Bauhaus color pulse overlay */}
              {isActive && (
                <motion.div
                  className="stage-block-pulse"
                  style={{ backgroundColor: color }}
                  animate={{ opacity: [0.04, 0.18, 0.04] }}
                  transition={{ repeat: Infinity, duration: 1.8, ease: 'easeInOut' }}
                />
              )}

              {/* Done: Bauhaus checkmark flash */}
              {isDone && (
                <motion.div
                  className="stage-block-done-flash"
                  style={{ borderColor: color }}
                  initial={{ opacity: 0.6, scale: 1.5 }}
                  animate={{ opacity: 0, scale: 1 }}
                  transition={{ duration: 0.5 }}
                />
              )}
            </motion.div>
          );
        })}
      </div>
    </div>
  );
};

// ── BauhausPlayer ────────────────────────────────────────────────────────────

interface BauhausPlayerProps {
  label: string;
  src: string | null;
  audioRef: React.RefObject<HTMLAudioElement | null>;
  isPlaying: boolean;
  currentTime: number;
  duration: number;
  volume: number;
  accentColor: string;
  onTogglePlay: () => void;
  onSeek: (e: React.MouseEvent<HTMLDivElement>) => void;
  onVolume: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onTimeUpdate: () => void;
  onLoadedMetadata: () => void;
  onPlay: () => void;
  onPause: () => void;
  onEnded: () => void;
}

const BauhausPlayer = ({
  label, src, audioRef, isPlaying, currentTime, duration,
  volume, accentColor,
  onTogglePlay, onSeek, onVolume,
  onTimeUpdate, onLoadedMetadata, onPlay, onPause, onEnded,
}: BauhausPlayerProps) => {
  const pct = duration > 0 ? (currentTime / duration) * 100 : 0;

  // Generate a static pseudo-waveform from the label string (deterministic bars)
  const bars = Array.from({ length: 40 }, (_, i) => {
    const seed = (label.charCodeAt(i % label.length) * 7 + i * 13) % 100;
    return 20 + (seed % 65);
  });

  return (
    <div className="bh-player" style={{ '--player-color': accentColor } as React.CSSProperties}>
      {/* Header row */}
      <div className="bh-player-header">
        <span className="bh-player-label">{label}</span>
        <span className="bh-player-time">{fmtTime(currentTime)} / {fmtTime(duration)}</span>
      </div>

      {/* Waveform scrubber */}
      <div className="bh-player-scrubber" onClick={onSeek} title="Seek">
        {/* Static waveform bars */}
        <div className="bh-waveform">
          {bars.map((h, i) => {
            const barPct = (i / bars.length) * 100;
            const played = barPct <= pct;
            return (
              <div
                key={i}
                className="bh-waveform-bar"
                style={{
                  height: `${h}%`,
                  backgroundColor: played ? accentColor : 'var(--gray-2)',
                  opacity: played ? 1 : 0.4,
                }}
              />
            );
          })}
        </div>
        {/* Playhead */}
        <motion.div
          className="bh-playhead"
          style={{ left: `${pct}%`, backgroundColor: accentColor }}
        />
      </div>

      {/* Controls row */}
      <div className="bh-player-controls">
        {/* Play/pause — Bauhaus circle button */}
        <motion.button
          className="bh-play-btn"
          style={{ backgroundColor: accentColor }}
          onClick={onTogglePlay}
          whileHover={{ scale: 1.08 }}
          whileTap={{ scale: 0.92 }}
          disabled={!src}
        >
          {isPlaying ? (
            <span className="bh-icon-pause">▐▐</span>
          ) : (
            <span className="bh-icon-play">▶</span>
          )}
        </motion.button>

        {/* Volume label + slider */}
        <div className="bh-volume-group">
          <span className="bh-vol-label">VOL</span>
          <input
            type="range" min="0" max="1" step="0.01"
            value={volume}
            onChange={onVolume}
            className="bh-vol-slider"
            style={{ '--player-color': accentColor } as React.CSSProperties}
          />
          <span className="bh-vol-value">{Math.round(volume * 100)}</span>
        </div>
      </div>

      {/* Hidden audio element */}
      <audio
        ref={audioRef}
        src={src || undefined}
        onPlay={onPlay}
        onPause={onPause}
        onEnded={onEnded}
        onTimeUpdate={onTimeUpdate}
        onLoadedMetadata={onLoadedMetadata}
      />
    </div>
  );
};

export default function App() {
  // ── State ───────────────────────────────────────────────────────────────
  const [inputFile,      setInputFile]      = useState<string | null>(null);
  const [outputFile,     setOutputFile]     = useState<string | null>(null);
  const [processingMode, setProcessingMode] = useState<ProcessingMode>('STANDARD');
  const [upscaleFactor,  setUpscaleFactor]  = useState<UpscaleFactor>(4);
  const [outputFormat,   setOutputFormat]   = useState<OutputFormat>('FLAC');
  const [exportFormat,   setExportFormat]   = useState<OutputFormat>('FLAC');
  const [denoiseStrength, setDenoiseStrength] = useState(55);
  const [noiseProfile,   setNoiseProfile]   = useState('AUTO');
  const [restorationSteps, setRestorationSteps] = useState(16);
  const [generationGuidance, setGenerationGuidance] = useState(0.50);
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

  // Input audio preview
  const [inputPreviewUrl,    setInputPreviewUrl]    = useState<string | null>(null);
  const [inputIsPlaying,     setInputIsPlaying]     = useState(false);
  const [inputAudioTime,     setInputAudioTime]     = useState(0);
  const [inputAudioDuration, setInputAudioDuration] = useState(0);

  // Input Playback Overrides
  const [inputVolume, setInputVolume] = useState(1.0);

  // Output Playback State
  const [outputPreviewUrl,    setOutputPreviewUrl]    = useState<string | null>(null);
  const [outputIsPlaying,     setOutputIsPlaying]     = useState(false);
  const [outputAudioTime,     setOutputAudioTime]     = useState(0);
  const [outputAudioDuration, setOutputAudioDuration] = useState(0);
  const [outputVolume, setOutputVolume] = useState(1.0);

  // Output state
  const [saveStatus,   setSaveStatus]  = useState<string | null>(null);

  // Refs
  const logBoxRef      = useRef<HTMLDivElement>(null);
  const inputAudioRef  = useRef<HTMLAudioElement>(null);
  const outputAudioRef = useRef<HTMLAudioElement>(null);
  const mountedRef     = useRef(true);
  const timerRef       = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastLogRef     = useRef<number>(0);
  const startTimeRef   = useRef<number>(0);
  const unlistenLogRef = useRef<UnlistenFn | null>(null);
  const unlistenDoneRef = useRef<UnlistenFn | null>(null);

  // ── Derived ──────────────────────────────────────────────────────────────
  const isRunning  = status === 'running';
  const canProcess = !!inputFile && !isRunning;
  // Removed unused progress variable
  const elapsedFmt = elapsedSec > 0
    ? ` · ${Math.floor(elapsedSec / 60)}m ${String(elapsedSec % 60).padStart(2, '0')}s`
    : '';

  // Map UI mode → engine mode
  const engineMode = processingMode === 'EXTREME' ? 'EXTREME' : 'HIGH';

  // ── Sync sliders to processing mode ──────────────────────────────────────
  useEffect(() => {
    if (isRunning) return;
    if (processingMode === 'EXTREME') {
      setDenoiseStrength(75);
      setRestorationSteps(48);
      setGenerationGuidance(0.70);
    } else if (processingMode === 'STANDARD') {
      setDenoiseStrength(55);
      setRestorationSteps(16);
      setGenerationGuidance(0.50);
    } else {
      // QUICK
      setDenoiseStrength(40);
      setRestorationSteps(8);
      setGenerationGuidance(0.35);
    }
  }, [processingMode]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Lifecycle ────────────────────────────────────────────────────────────
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    const box = logBoxRef.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [logs]);

  // Cleanup event listeners on unmount
  useEffect(() => {
    return () => {
      unlistenLogRef.current?.();
      unlistenDoneRef.current?.();
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

  // ── Audio Scrubbing & Volume ───────────────────────────────────────────
  const handleInputSeek = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!inputAudioRef.current) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const percent = (e.clientX - rect.left) / rect.width;
    inputAudioRef.current.currentTime = percent * inputAudioDuration;
    setInputAudioTime(percent * inputAudioDuration);
  };
  const handleInputVolume = (e: React.ChangeEvent<HTMLInputElement>) => {
    const vol = parseFloat(e.target.value);
    setInputVolume(vol);
    if (inputAudioRef.current) inputAudioRef.current.volume = vol;
  };

  const handleOutputSeek = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!outputAudioRef.current) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const percent = (e.clientX - rect.left) / rect.width;
    outputAudioRef.current.currentTime = percent * outputAudioDuration;
    setOutputAudioTime(percent * outputAudioDuration);
  };
  const handleOutputVolume = (e: React.ChangeEvent<HTMLInputElement>) => {
    const vol = parseFloat(e.target.value);
    setOutputVolume(vol);
    if (outputAudioRef.current) outputAudioRef.current.volume = vol;
  };

  // ── Reset helpers ────────────────────────────────────────────────────────
  const resetOutputState = () => {
    setOutputFile(null);
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

  // ── File Selection (Tauri dialog) ────────────────────────────────────────
  const handleSelectFile = async () => {
    if (isRunning) return;
    try {
      const selected = await invoke<string | null>('open_file_dialog');
      if (!selected) return;
      setInputFile(selected);
      setInputPreviewUrl(convertFileSrc(selected));
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

  // ── Output audio toggle ────────────────────────────────────────────────
  const toggleOutputPlay = () => {
    const a = outputAudioRef.current;
    if (!a) return;
    if (a.paused) { a.play(); } else { a.pause(); }
  };

  // ── Processing (Tauri invoke + event listeners) ──────────────────────────
  const handleProcess = async () => {
    if (!inputFile || isRunning) return;

    setStatus('running');
    setCurrentStep(0);
    setElapsedSec(0);
    resetOutputState();
    setOutputPreviewUrl(null);
    setOutputIsPlaying(false);
    setOutputAudioTime(0);
    setOutputAudioDuration(0);
    setLogs(['>> [VOXIS] Initiating Trinity V8.2 Pipeline...']);

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

    // Clean up previous listeners
    unlistenLogRef.current?.();
    unlistenDoneRef.current?.();

    // Subscribe to Tauri events
    unlistenLogRef.current = await listen<string>('trinity-log', (event) => {
      appendLog(event.payload);
    });
    unlistenDoneRef.current = await listen<string>('trinity-done', (event) => {
      setOutputFile(event.payload);
      setOutputPreviewUrl(convertFileSrc(event.payload));
    });

    try {
      const result = await invoke<string>('run_trinity_engine', {
        filePath:        inputFile,
        mode:            engineMode,
        stereoWidth:     stereoOutput ? 0.5 : 0.0,
        outputFormat,
        ramLimit,
        denoiseStrength: denoiseStrength / 100.0,
        denoiseSteps:    restorationSteps,
      });

      if (mountedRef.current) {
        setStatus('done');
        setCurrentStep(STEPS.length);
        setOutputFile(result);
        setOutputPreviewUrl(convertFileSrc(result));
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
      unlistenLogRef.current?.();
      unlistenDoneRef.current?.();
      unlistenLogRef.current = null;
      unlistenDoneRef.current = null;
    }
  };

  // ── Cancel ─────────────────────────────────────────────────────────────
  const handleCancel = async () => {
    if (!isRunning) return;
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    try {
      await invoke('cancel_engine');
      setStatus('idle');
      setCurrentStep(0);
      setElapsedSec(0);
      appendLog('>> [VOXIS] Processing cancelled by user.');
    } catch (e) {
      appendLog(`[ERROR] Cancel failed: ${errMsg(e)}`);
    }
  };

  // ── Save As (Tauri dialog + file copy) ──────────────────────────────────
  const handleSaveAs = async () => {
    if (!outputFile) return;
    const ext = exportFormat.toLowerCase();
    try {
      const dest = await invoke<string | null>('save_file_dialog', {
        defaultName: basename(outputFile),
        ext,
      });
      if (!dest) return;
      await invoke('copy_file', { src: outputFile, dest });
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
      await invoke('reveal_in_folder', { path: outputFile });
    } catch {
      appendLog(`[INFO] Output: ${outputFile}`);
    }
  };

  // ── Render ─────────────────────────────────────────────────────────────
  return (
    <div className="app-shell">

      {/* ── HEADER ── */}
      <header className="app-header">
        <div className="header-brand-group">
          <Logo />
          <span className="brand-voxis">VOXIS</span>
          <span className="brand-dense">DENSE</span>
        </div>
        <div className="header-subtitle">
          VOICE RESTORATION V4.0.0 | BY GLASS STONE
        </div>
        <div className="header-version">
          GUI V4.0.0 // ENGINE V8.2
        </div>
      </header>

      {/* ── BODY ── */}
      <div className="app-body">

        {/* ── SIDEBAR ── */}
        <aside className="sidebar">

          
          <AnimatePresence mode="wait">
            {status === 'idle' ? (
              <motion.div
                key="controls"
                className="sidebar-controls"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.12 }}
              >
{/* Processing Mode */}
          <div className="sb-section">
            <div className="sb-label">PROCESSING MODE</div>
            {(['QUICK', 'STANDARD', 'EXTREME'] as ProcessingMode[]).map(m => (
              <motion.button
                key={m}
                className={`mode-btn ${processingMode === m ? 'active' : ''} ${m === 'EXTREME' && processingMode === m ? 'extreme' : ''}`}
                onClick={() => setProcessingMode(m)}
                disabled={isRunning}
                whileHover={!isRunning ? { scale: 1.03, backgroundColor: 'var(--gray-1)' } : {}}
                whileTap={!isRunning ? { scale: 0.95 } : {}}
                transition={{ type: 'spring', stiffness: 400, damping: 25 }}
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
                  whileHover={!isRunning ? { scale: 1.05, backgroundColor: 'var(--gray-1)' } : {}}
                  whileTap={!isRunning ? { scale: 0.92 } : {}}
                  transition={{ type: 'spring', stiffness: 400, damping: 25 }}
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
              {(['WAV', 'FLAC', 'MP3', 'WAV24', 'WAV32', 'ALAC'] as OutputFormat[]).map(f => (
                <motion.button
                  key={f}
                  className={`format-btn ${outputFormat === f ? 'active' : ''}`}
                  onClick={() => { setOutputFormat(f); setExportFormat(f); }}
                  disabled={isRunning}
                  whileHover={!isRunning ? { scale: 1.05, backgroundColor: 'var(--gray-1)' } : {}}
                  whileTap={!isRunning ? { scale: 0.92 } : {}}
                  transition={{ type: 'spring', stiffness: 400, damping: 25 }}
                >
                  {f}
                </motion.button>
              ))}
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
              <motion.label
                className="toggle-switch"
                whileHover={!isRunning ? { scale: 1.05 } : {}}
                whileTap={!isRunning ? { scale: 0.95 } : {}}
              >
                <input type="checkbox" checked={highPrecision}
                  onChange={e => setHighPrecision(e.target.checked)} disabled={isRunning} />
                <span className="toggle-track green" />
              </motion.label>
            </div>
          </div>

          {/* Stereo Output */}
          <div className="sb-section">
            <div className="toggle-item">
              <span className="sb-label no-mb">STEREO OUTPUT</span>
              <motion.label
                className="toggle-switch"
                whileHover={!isRunning ? { scale: 1.05 } : {}}
                whileTap={!isRunning ? { scale: 0.95 } : {}}
              >
                <input type="checkbox" checked={stereoOutput}
                  onChange={e => setStereoOutput(e.target.checked)} disabled={isRunning} />
                <span className="toggle-track blue" />
              </motion.label>
            </div>
          </div>


              </motion.div>
            ) : (
              <motion.div
                key="telemetry"
                className="sidebar-telemetry"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.12 }}
              >
                <div className="telemetry-header">
                  VOXIS TELEMETRY
                  <div className="telemetry-time">{elapsedFmt.replace(' · ', '') || '0m 00s'}</div>
                </div>

                <div className="status-line sidebar-status">
                  {status === 'error' ? (
                    <span className="status-error">{'[!] '} ENGINE ERROR</span>
                  ) : (
                    <motion.span
                      className="status-running"
                      animate={{ opacity: [1, 0.6, 1] }}
                      transition={{ repeat: Infinity, duration: 1.5 }}
                    >
                      {currentStep === 0
                        ? `>> STARTING...`
                        : `>> STAGE ${currentStep}/${STEPS.length}`
                      }
                    </motion.span>
                  )}
                </div>

                {(autoLPF !== null || autoHPF !== null || autoVocal !== null) && (
                  <div className="eq-readouts sidebar-eq">
                    <div className="eq-chip"><span className="eq-chip-label">LPF</span><span className="eq-chip-val">{autoLPF !== null ? `${(autoLPF / 1000).toFixed(1)}kHz` : '—'}</span></div>
                    <div className="eq-chip"><span className="eq-chip-label">HPF</span><span className="eq-chip-val">{autoHPF !== null ? `${autoHPF}Hz` : '—'}</span></div>
                    <div className="eq-chip"><span className="eq-chip-label">VOCAL</span><span className="eq-chip-val">{autoVocal !== null ? `${autoVocal > 0 ? '+' : ''}${autoVocal}dB` : '—'}</span></div>
                  </div>
                )}

                <div className="log-viewer sidebar-logs" ref={logBoxRef}>
                  {logs.map((line, i) => (
                    <div
                      key={i}
                      className={`log-line ${
                        line.includes('[ERROR]') || line.includes('[!]') ? 'log-error'
                        : line.includes('[OK]') || line.includes('✓') || line.includes('Complete') ? 'log-ok'
                        : line.startsWith('>>') ? 'log-step'
                        : ''
                      }`}
                    >
                      {line}
                    </div>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>

        </aside>

        {/* ── MAIN PANEL ── */}
        <main className="main-panel">

          {/* ── File Strip ── */}
          {inputFile ? (
            <div className="file-strip">
              <div className="file-info">
                <div className="file-name">{basename(inputFile).toUpperCase()}</div>
                <div className="file-meta">
                  {inputFile.split('.').pop()?.toUpperCase() ?? 'AUDIO'}
                </div>
              </div>
              <motion.button
                className="file-change-btn"
                onClick={handleSelectFile}
                disabled={isRunning}
                whileHover={!isRunning ? { scale: 1.04 } : {}}
                whileTap={!isRunning ? { scale: 0.96 } : {}}
              >
                CHANGE
              </motion.button>
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
            <AnimatePresence mode="wait">
              {status !== 'done' ? (
                <motion.div
                  key="pipeline"
                  className="pipeline-content"
                  exit={{ opacity: 0, scale: 0.99 }}
                  transition={{ duration: 0.15 }}
                >

                {/* ── Bauhaus Audio Player (shown when file loaded) ── */}
                {inputFile && !isRunning && (
                  <BauhausPlayer
                    label={basename(inputFile).toUpperCase()}
                    src={inputPreviewUrl}
                    audioRef={inputAudioRef}
                    isPlaying={inputIsPlaying}
                    currentTime={inputAudioTime}
                    duration={inputAudioDuration}
                    volume={inputVolume}
                    accentColor={STAGE_COLORS[0]}
                    onTogglePlay={toggleInputPlay}
                    onSeek={handleInputSeek}
                    onVolume={handleInputVolume}
                    onPlay={() => setInputIsPlaying(true)}
                    onPause={() => setInputIsPlaying(false)}
                    onEnded={() => { setInputIsPlaying(false); setInputAudioTime(0); }}
                    onTimeUpdate={() => setInputAudioTime(inputAudioRef.current?.currentTime ?? 0)}
                    onLoadedMetadata={() => setInputAudioDuration(inputAudioRef.current?.duration ?? 0)}
                  />
                )}

                {/* ── Pipeline Guide (idle state) ── */}
                {!isRunning && status !== 'error' && (
                  <div className="pipeline-guide">
                    <div className="guide-header">7-STAGE NEURAL PIPELINE</div>
                    <div className="guide-grid">
                      {STEPS.map((step, i) => (
                        <div key={step.id} className="guide-chip">
                          <div className="guide-chip-num" style={{ backgroundColor: STAGE_COLORS[i] }}>{step.id}</div>
                          <div className="guide-chip-body">
                            <div className="guide-chip-title">{step.label}</div>
                            <div className="guide-chip-sub">{step.sublabel}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                
                {/* Pipeline + Animated Stage Progress */}
                {isRunning && (
                  <AnimatedStageProgress currentStep={currentStep} />
                )}


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
              </motion.div>
            ) : status === 'done' && outputFile ? (
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
                    <div className="completion-check">{'[OK]'}</div>
                    <h2 className="completion-title">RESTORATION COMPLETE</h2>
                    <p className="completion-sub">48kHz / Stereo</p>

                    {/* Before / After Comparison Players */}
                    <div className="ba-player">
                      {/* BEFORE row */}
                      <div className="ba-row">
                        <span className="ba-label">BEFORE</span>
                        <button className="ba-play" onClick={toggleInputPlay}>
                          {inputIsPlaying ? '▐▐' : '▶'}
                        </button>
                        <div className="ba-bar" onClick={handleInputSeek}>
                          <div className="ba-progress" style={{ width: `${inputAudioDuration ? (inputAudioTime / inputAudioDuration) * 100 : 0}%` }} />
                        </div>
                        <span className="ba-time">{fmtTime(inputAudioTime)} / {fmtTime(inputAudioDuration)}</span>
                      </div>
                      {/* AFTER row */}
                      <div className="ba-row">
                        <span className="ba-label">AFTER</span>
                        <button className="ba-play" onClick={toggleOutputPlay}>
                          {outputIsPlaying ? '▐▐' : '▶'}
                        </button>
                        <div className="ba-bar" onClick={handleOutputSeek}>
                          <div className="ba-progress" style={{ width: `${outputAudioDuration ? (outputAudioTime / outputAudioDuration) * 100 : 0}%` }} />
                        </div>
                        <span className="ba-time">{fmtTime(outputAudioTime)} / {fmtTime(outputAudioDuration)}</span>
                      </div>
                    </div>

                    <audio
                      ref={outputAudioRef}
                      src={outputPreviewUrl || undefined}
                      onPlay={() => setOutputIsPlaying(true)}
                      onPause={() => setOutputIsPlaying(false)}
                      onEnded={() => { setOutputIsPlaying(false); setOutputAudioTime(0); }}
                      onTimeUpdate={() => setOutputAudioTime(outputAudioRef.current?.currentTime ?? 0)}
                      onLoadedMetadata={() => setOutputAudioDuration(outputAudioRef.current?.duration ?? 0)}
                    />


                    <div className="export-section">
                      <div className="export-label">EXPORT FORMAT</div>
                      <div className="export-btns">
                        {(['WAV', 'FLAC', 'MP3', 'WAV24', 'WAV32', 'ALAC'] as OutputFormat[]).map(f => (
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
              ) : null}
            </AnimatePresence>

          </div>
        </main>
      </div>
    </div>
  );
}
