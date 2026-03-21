// VOXIS 4.0 DENSE — Electron Main Process
// Copyright (c) 2026 Glass Stone LLC. All Rights Reserved.
// Powered by Trinity V8.1 | Built by Glass Stone

import { app, BrowserWindow, dialog, ipcMain, shell, nativeImage, protocol, net } from 'electron';
import { autoUpdater } from 'electron-updater';
import { spawn, ChildProcess } from 'child_process';
import { createInterface } from 'readline';
import * as path from 'path';
import * as fs from 'fs';
import * as http from 'http';
import * as os from 'os';

// Auto-updater: check on launch, prompt user — no silent download
autoUpdater.autoDownload = false;
autoUpdater.autoInstallOnAppQuit = false;

// voxis-file:// — local audio streaming; must precede app.whenReady
protocol.registerSchemesAsPrivileged([
  { scheme: 'voxis-file', privileges: { stream: true, bypassCSP: true, supportFetchAPI: true, corsEnabled: true } },
]);

let mainWindow: BrowserWindow | null = null;
let activeProcess: ChildProcess | null = null;

const isDev = !app.isPackaged;

// Force OS-level app name (menu bar, dock, Activity Monitor)
app.setName('Voxis 4.0 DENSE');

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function getFFmpegPath(): string {
  if (process.platform === 'win32') {
    if (isDev) return path.join(__dirname, '..', 'resources', 'bin', 'ffmpeg.exe');
    return path.join(process.resourcesPath, 'bin', 'ffmpeg.exe');
  }
  // macOS/Linux: rely on system FFmpeg
  return 'ffmpeg';
}

function getSidecarPath(): string {
  const binaryName = process.platform === 'win32' ? 'trinity_v8_core.exe' : 'trinity_v8_core';
  if (isDev) {
    return path.join(__dirname, '..', 'resources', 'bin', binaryName);
  }
  return path.join(process.resourcesPath, 'bin', binaryName);
}

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function send(channel: string, data: string): void {
  mainWindow?.webContents?.send(channel, data);
}

// ---------------------------------------------------------------------------
// Wait for Vite dev server (dev mode only)
// ---------------------------------------------------------------------------
function waitForVite(url: string, maxRetries = 40): Promise<void> {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const check = () => {
      http
        .get(url, (res) => { res.resume(); resolve(); })
        .on('error', () => {
          attempts++;
          if (attempts >= maxRetries) {
            reject(new Error('Vite dev server did not start in time'));
          } else {
            setTimeout(check, 500);
          }
        });
    };
    check();
  });
}

// ---------------------------------------------------------------------------
// Create main window
// ---------------------------------------------------------------------------
async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1120,
    height: 820,
    minWidth: 900,
    minHeight: 700,
    titleBarStyle: 'hiddenInset',
    title: 'VOXIS 4.0 DENSE — Voice Restoration | Glass Stone LLC',
    icon: path.join(__dirname, '..', 'resources', 'icons', 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  if (isDev) {
    const devUrl = 'http://localhost:5173';
    await waitForVite(devUrl);
    mainWindow.loadURL(devUrl);
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  } else {
    mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ---------------------------------------------------------------------------
// IPC: File dialog
// ---------------------------------------------------------------------------
ipcMain.handle('dialog:openFile', async () => {
  if (!mainWindow) return null;
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile'],
    filters: [
      {
        name: 'Voice & Audio Files',
        extensions: ['wav', 'mp3', 'flac', 'aac', 'ogg', 'm4a', 'aiff', 'mp4', 'mov', 'mkv', 'avi'],
      },
    ],
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0];
});

// ---------------------------------------------------------------------------
// IPC: Run Trinity Engine (sidecar)
// ---------------------------------------------------------------------------
ipcMain.handle(
  'trinity:runEngine',
  (
    _event,
    params: {
      filePath:        string;
      mode:            string;
      stereoWidth:     number;
      outputFormat:    string;
      ramLimit?:       number;
      denoiseStrength?: number;  // 0.0–1.0 (cfg_strength)
      denoiseSteps?:   number;   // 8–64 (diffusion steps)
    },
  ): Promise<string> => {
    const { filePath, mode, stereoWidth, outputFormat, ramLimit, denoiseStrength, denoiseSteps } = params;

    // --- Validate inputs ---
    if (!filePath || typeof filePath !== 'string') {
      return Promise.reject('Invalid file path.');
    }
    const validModes    = ['HIGH', 'EXTREME'];
    const validFormats  = ['WAV', 'FLAC', 'MP3'];
    const safeMode      = validModes.includes(mode) ? mode : 'HIGH';
    const safeFormat    = validFormats.includes(outputFormat) ? outputFormat : 'WAV';
    const safeWidth     = Math.max(0, Math.min(1, stereoWidth ?? 0.5));
    const safeRamLimit  = Math.max(25, Math.min(100, ramLimit ?? 75));
    const safeCfg       = Math.max(0.1, Math.min(1.0, denoiseStrength ?? 0.55));
    const safeSteps     = Math.max(8, Math.min(64, Math.round(denoiseSteps ?? 16)));

    // --- Guard: reject if already processing ---
    if (activeProcess) {
      return Promise.reject('Engine is already running. Wait for the current job to finish.');
    }

    // --- Verify binary exists ---
    const binaryPath = getSidecarPath();
    if (!fs.existsSync(binaryPath)) {
      return Promise.reject(
        `Trinity Engine binary not found at:\n${binaryPath}\n\nRun: npm run build:engine`,
      );
    }

    // --- Derive output path (~/Music/Voxis Restored/) ---
    const restoredDir = path.join(os.homedir(), 'Music', 'Voxis Restored');
    fs.mkdirSync(restoredDir, { recursive: true });
    const stem   = path.basename(filePath, path.extname(filePath));
    const outExt = safeFormat === 'FLAC' ? 'flac' : safeFormat === 'MP3' ? 'mp3' : 'wav';
    const base   = path.join(restoredDir, `${stem}_voxis_mastered.${outExt}`);
    let outPath = base;
    let collision = 1;
    while (fs.existsSync(outPath)) {
      outPath = path.join(restoredDir, `${stem}_voxis_mastered_${collision}.${outExt}`);
      collision++;
    }

    // --- Build args ---
    // Note: If format is MP3, run engine as WAV then convert post-process
    const engineFormat = safeFormat === 'MP3' ? 'WAV' : safeFormat;
    const needsMp3Convert = safeFormat === 'MP3';

    // If MP3 requested, engine outputs WAV; we'll convert after
    let engineOutPath = outPath;
    if (needsMp3Convert) {
      engineOutPath = outPath.replace(/\.mp3$/i, '.wav');
    }

    const args: string[] = [
      '--input',          filePath,
      '--output',         engineOutPath,
      '--stereo-width',   safeWidth.toFixed(2),
      '--format',         engineFormat,
      '--ram-limit',      String(safeRamLimit),
      '--denoise-steps',  String(safeSteps),
      '--denoise-strength', safeCfg.toFixed(2),
    ];
    if (safeMode === 'EXTREME') args.push('--extreme');

    send('trinity-log', '>> [VOXIS] Trinity V8.1 Engine starting...');

    return new Promise<string>((resolve, reject) => {
      let child: ChildProcess;

      try {
        // Ensure FFmpeg is discoverable — Electron strips Homebrew/MacPorts from PATH
        const extraPaths = ['/opt/homebrew/bin', '/usr/local/bin', '/opt/local/bin'];
        const currentPath = process.env.PATH || '/usr/bin:/bin';
        const fullPath = [...extraPaths, ...currentPath.split(':')].filter((v, i, a) => a.indexOf(v) === i).join(':');

        child = spawn(binaryPath, args, {
          stdio: ['ignore', 'pipe', 'pipe'],
          env:   {
            ...process.env,
            PATH:                        fullPath,
            PYTORCH_ENABLE_MPS_FALLBACK: '1',
            PYTHONUNBUFFERED:            '1',   // force line-flush when piped (fixes silent log)
            PYTHONFAULTHANDLER:          '1',   // crash tracebacks visible in stderr
          },
        });
        activeProcess = child;
      } catch (err) {
        reject(`Failed to launch Trinity Engine: ${errMsg(err)}`);
        return;
      }

      // Stream stdout line-by-line
      const stdoutRL = child.stdout
        ? createInterface({ input: child.stdout })
        : null;

      stdoutRL?.on('line', (line: string) => {
        const trimmed = line.trim();
        if (trimmed) send('trinity-log', trimmed);
      });

      // Stream stderr (Python tqdm / torch progress writes to stderr)
      // Filter out known noisy-but-harmless warnings from third-party libs
      const STDERR_SUPPRESS = [
        'FutureWarning',
        'torch.cuda.amp.autocast',
        'torch.amp.autocast',
        'torch.nn.utils.weight_norm',
        'WeightNorm.apply',
        'rotary_embedding_torch',
        'warnings.warn',
        '% |',          // tqdm progress bars
        'it/s]',        // tqdm speed indicator
        'it, ',         // tqdm counter
      ];
      const stderrRL = child.stderr
        ? createInterface({ input: child.stderr })
        : null;

      stderrRL?.on('line', (line: string) => {
        const trimmed = line.trim();
        if (!trimmed) return;
        if (STDERR_SUPPRESS.some(pat => trimmed.includes(pat))) return;
        send('trinity-log', `[STDERR] ${trimmed}`);
      });

      child.on('error', (err: Error) => {
        stdoutRL?.close();
        stderrRL?.close();
        activeProcess = null;
        const msg = `[ERROR] Failed to start engine: ${err.message}`;
        send('trinity-log', msg);
        reject(msg);
      });

      child.on('close', (code: number | null) => {
        stdoutRL?.close();
        stderrRL?.close();
        activeProcess = null;

        send('trinity-log', `>> [VOXIS] Engine exited (code ${code ?? -1})`);

        if (code === 0) {
          // Post-process: convert WAV → MP3 if user requested MP3
          if (needsMp3Convert && fs.existsSync(engineOutPath)) {
            send('trinity-log', '>> [VOXIS] Converting to MP3 (320kbps)...');
            const ffmpeg = spawn(getFFmpegPath(), [
              '-y', '-hide_banner', '-loglevel', 'error',
              '-i', engineOutPath,
              '-c:a', 'libmp3lame', '-b:a', '320k', '-q:a', '0',
              outPath,
            ]);
            ffmpeg.on('close', (mp3Code) => {
              if (mp3Code === 0) {
                // Remove intermediate WAV
                try { fs.unlinkSync(engineOutPath); } catch { /* ok */ }
                send('trinity-log', '>> [VOXIS] MP3 export complete.');
                send('trinity-done', outPath);
                resolve(outPath);
              } else {
                // Fallback: return the WAV instead
                send('trinity-log', '[WARN] MP3 conversion failed — returning WAV.');
                send('trinity-done', engineOutPath);
                resolve(engineOutPath);
              }
            });
            ffmpeg.on('error', () => {
              send('trinity-log', '[WARN] FFmpeg not found — returning WAV.');
              send('trinity-done', engineOutPath);
              resolve(engineOutPath);
            });
          } else {
            send('trinity-done', outPath);
            resolve(outPath);
          }
        } else {
          reject(`Trinity Engine exited with code ${code ?? -1}. Check the activity log.`);
        }
      });
    });
  },
);

// ---------------------------------------------------------------------------
// IPC: Get version
// ---------------------------------------------------------------------------
ipcMain.handle('trinity:getVersion', () => {
  return 'VOXIS 4.0 DENSE | Trinity V8.1 | Glass Stone LLC © 2026';
});

// ---------------------------------------------------------------------------
// IPC: Open path in Finder
// ---------------------------------------------------------------------------
ipcMain.handle('shell:openPath', (_event, filePath: string) => {
  if (typeof filePath === 'string' && filePath.length > 0) {
    shell.showItemInFolder(filePath);
  }
});

// ---------------------------------------------------------------------------
// IPC: Open file in default application
// ---------------------------------------------------------------------------
ipcMain.handle('shell:openFile', (_event, filePath: string) => {
  if (typeof filePath === 'string' && filePath.length > 0) {
    return shell.openPath(filePath);
  }
});

// ---------------------------------------------------------------------------
// IPC: Save-As dialog
// ---------------------------------------------------------------------------
ipcMain.handle('dialog:saveFile', async (_event, defaultName: string, ext: string) => {
  if (!mainWindow) return null;
  const safeExt  = ['wav', 'flac', 'mp3'].includes(ext) ? ext : 'wav';
  const formatNames: Record<string, string> = { wav: 'WAV Audio', flac: 'FLAC Audio', mp3: 'MP3 Audio' };
  const result = await dialog.showSaveDialog(mainWindow, {
    defaultPath: path.join(os.homedir(), 'Music', defaultName),
    filters: [
      { name: formatNames[safeExt] ?? 'Audio', extensions: [safeExt] },
      { name: 'All Files', extensions: ['*'] },
    ],
  });
  return result.canceled ? null : result.filePath ?? null;
});

// ---------------------------------------------------------------------------
// IPC: Copy file (async — avoids blocking main thread for large files)
// ---------------------------------------------------------------------------
ipcMain.handle('file:copy', async (_event, src: string, dest: string) => {
  if (typeof src !== 'string' || typeof dest !== 'string') throw new Error('Invalid paths');
  await fs.promises.copyFile(src, dest);
});

// ---------------------------------------------------------------------------
// IPC: Cancel active Trinity engine process
// ---------------------------------------------------------------------------
ipcMain.handle('trinity:cancelEngine', () => {
  if (activeProcess) {
    activeProcess.kill('SIGTERM');
    activeProcess = null;
    send('trinity-log', '>> [VOXIS] Processing cancelled by user.');
  }
});

// ---------------------------------------------------------------------------
// Auto-updater events (production only — no-op in dev)
// ---------------------------------------------------------------------------
autoUpdater.on('update-available', (info) => {
  mainWindow?.webContents.send('update-status', { type: 'available', version: info.version });
});
autoUpdater.on('download-progress', (p) => {
  mainWindow?.webContents.send('update-status', { type: 'progress', percent: Math.round(p.percent) });
});
autoUpdater.on('update-downloaded', () => {
  mainWindow?.webContents.send('update-status', { type: 'downloaded' });
});
autoUpdater.on('error', () => {
  // Silently ignore update check errors (offline, network issues, etc.)
});

ipcMain.handle('update:download', () => autoUpdater.downloadUpdate());
ipcMain.handle('update:install',  () => autoUpdater.quitAndInstall());

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------
app.whenReady().then(() => {
  protocol.handle('voxis-file', (req) => {
    const filePath = decodeURIComponent(req.url.replace('voxis-file://', ''));
    return net.fetch('file://' + filePath);
  });

  // Set dock icon on macOS (required in dev mode — production uses .icns from bundle)
  if (process.platform === 'darwin') {
    const iconPath = isDev
      ? path.join(__dirname, '..', 'resources', 'icons', 'icon.png')
      : path.join(process.resourcesPath, '..', 'Resources', 'icon.icns');
    try {
      const dockIcon = nativeImage.createFromPath(iconPath);
      if (!dockIcon.isEmpty()) app.dock?.setIcon(dockIcon);
    } catch { /* icon not found — use default */ }
  }

  createWindow().then(() => {
    // Check for updates after window is ready (production only)
    if (app.isPackaged) {
      autoUpdater.checkForUpdates().catch(() => {});
    }
  });
});

app.on('window-all-closed', () => {
  if (activeProcess) {
    const proc = activeProcess;
    activeProcess = null;
    // Wait for child to exit before quitting so output files aren't corrupted
    proc.once('exit', () => app.quit());
    proc.kill('SIGTERM');
    // Fallback: force quit after 5s if process doesn't respond
    setTimeout(() => app.quit(), 5000).unref();
  } else {
    app.quit();
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});

// ---------------------------------------------------------------------------
// License IPC handlers
// ---------------------------------------------------------------------------
import {
  activateLicense,
  validateLicense,
  deactivateLicense,
  getMachineFingerprint,
} from './license';

ipcMain.handle('license:activate', async (_event, key: string, email: string) => {
  return activateLicense(key, email);
});

ipcMain.handle('license:validate', async () => {
  return validateLicense();
});

ipcMain.handle('license:deactivate', async () => {
  return deactivateLicense();
});

ipcMain.handle('license:fingerprint', () => {
  return getMachineFingerprint();
});
