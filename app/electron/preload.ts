// VOXIS 4.0 DENSE — Electron Preload Script
// Copyright (c) 2026 Glass Stone LLC. All Rights Reserved.

import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('electronAPI', {
  dialog: {
    openFile: (): Promise<string | null> =>
      ipcRenderer.invoke('dialog:openFile'),

    saveFile: (defaultName: string, ext: string): Promise<string | null> =>
      ipcRenderer.invoke('dialog:saveFile', defaultName, ext),
  },

  trinity: {
    runEngine: (params: {
      filePath:        string;
      mode:            string;
      stereoWidth:     number;
      outputFormat:    string;
      ramLimit?:       number;
      denoiseStrength?: number;
      denoiseSteps?:   number;
    }): Promise<string> =>
      ipcRenderer.invoke('trinity:runEngine', params),

    getVersion: (): Promise<string> =>
      ipcRenderer.invoke('trinity:getVersion'),

    onLog: (callback: (line: string) => void): void => {
      ipcRenderer.on('trinity-log', (_event, data: string) => callback(data));
    },
    offLog: (): void => {
      ipcRenderer.removeAllListeners('trinity-log');
    },

    onDone: (callback: (outputPath: string) => void): void => {
      ipcRenderer.on('trinity-done', (_event, data: string) => callback(data));
    },
    offDone: (): void => {
      ipcRenderer.removeAllListeners('trinity-done');
    },

    cancelEngine: (): Promise<void> =>
      ipcRenderer.invoke('trinity:cancelEngine'),
  },

  shell: {
    openPath: (filePath: string): Promise<void> =>
      ipcRenderer.invoke('shell:openPath', filePath),
    openFile: (filePath: string): Promise<string> =>
      ipcRenderer.invoke('shell:openFile', filePath),
  },

  file: {
    copy: (src: string, dest: string): Promise<void> =>
      ipcRenderer.invoke('file:copy', src, dest),

    toPreviewUrl: (absPath: string): string => {
      const normalized = absPath.replace(/\\/g, '/');
      const encoded = normalized.split('/').map(encodeURIComponent).join('/');
      return `voxis-file://${encoded}`;
    },
  },

  update: {
    onStatus: (cb: (s: { type: string; version?: string; percent?: number }) => void): void => {
      ipcRenderer.on('update-status', (_event, data) => cb(data));
    },
    offStatus: (): void => {
      ipcRenderer.removeAllListeners('update-status');
    },
    download: (): Promise<void> => ipcRenderer.invoke('update:download'),
    install:  (): void => { ipcRenderer.invoke('update:install'); },
  },

  license: {
    activate: (key: string, email: string): Promise<{
      success: boolean; message: string; tier?: string; email?: string;
    }> => ipcRenderer.invoke('license:activate', key, email),

    validate: (): Promise<{
      valid: boolean; tier?: string; email?: string;
      expiry?: string | null; reason?: string; offline?: boolean;
    }> => ipcRenderer.invoke('license:validate'),

    deactivate: (): Promise<void> =>
      ipcRenderer.invoke('license:deactivate'),

    getFingerprint: (): Promise<string> =>
      ipcRenderer.invoke('license:fingerprint'),
  },
});
