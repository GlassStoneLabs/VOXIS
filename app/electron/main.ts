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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
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
    title: 'VOXIS — Glass Stone LLC',
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
        name: 'Audio & Video',
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
      filePath:     string;
      mode:         string;
      stereoWidth:  number;
      outputFormat: string;
    },
  ): Promise<string> => {
    const { filePath, mode, stereoWidth, outputFormat } = params;

    // --- Validate inputs ---
    if (!filePath || typeof filePath !== 'string') {
      return Promise.reject('Invalid file path.');
    }
    const validModes    = ['HIGH', 'EXTREME'];
    const validFormats  = ['WAV', 'FLAC'];
    const safeMode      = validModes.includes(mode) ? mode : 'HIGH';
    const safeFormat    = validFormats.includes(outputFormat) ? outputFormat : 'WAV';
    const safeWidth     = Math.max(0, Math.min(1, stereoWidth ?? 0.5));

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
    const outExt = safeFormat === 'FLAC' ? 'flac' : 'wav';
    const base   = path.join(restoredDir, `${stem}_voxis_mastered.${outExt}`);
    let outPath = base;
    let collision = 1;
    while (fs.existsSync(outPath)) {
      outPath = path.join(restoredDir, `${stem}_voxis_mastered_${collision}.${outExt}`);
      collision++;
    }

    // --- Build args ---
    const args: string[] = [
      '--input',        filePath,
      '--output',       outPath,
      '--stereo-width', safeWidth.toFixed(2),
      '--format',       safeFormat,
    ];
    if (safeMode === 'EXTREME') args.push('--extreme');

    send('trinity-log', '>> [VOXIS] Trinity V8.1 Engine starting...');

    return new Promise<string>((resolve, reject) => {
      let child: ChildProcess;

      try {
        child = spawn(binaryPath, args, {
          stdio: ['ignore', 'pipe', 'pipe'],
          env:   { ...process.env, PYTORCH_ENABLE_MPS_FALLBACK: '1' },
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
      const stderrRL = child.stderr
        ? createInterface({ input: child.stderr })
        : null;

      stderrRL?.on('line', (line: string) => {
        const trimmed = line.trim();
        if (trimmed) send('trinity-log', `[STDERR] ${trimmed}`);
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
          send('trinity-done', outPath);
          resolve(outPath);
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
// IPC: Save-As dialog
// ---------------------------------------------------------------------------
ipcMain.handle('dialog:saveFile', async (_event, defaultName: string, ext: string) => {
  if (!mainWindow) return null;
  const safeExt  = ['wav', 'flac'].includes(ext) ? ext : 'wav';
  const result = await dialog.showSaveDialog(mainWindow, {
    defaultPath: path.join(os.homedir(), 'Music', defaultName),
    filters: [
      { name: safeExt === 'flac' ? 'FLAC Audio' : 'WAV Audio', extensions: [safeExt] },
      { name: 'All Files', extensions: ['*'] },
    ],
  });
  return result.canceled ? null : result.filePath ?? null;
});

// ---------------------------------------------------------------------------
// IPC: Copy file
// ---------------------------------------------------------------------------
ipcMain.handle('file:copy', (_event, src: string, dest: string) => {
  if (typeof src !== 'string' || typeof dest !== 'string') return;
  fs.copyFileSync(src, dest);
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
    activeProcess.kill('SIGTERM');
    activeProcess = null;
  }
  app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
