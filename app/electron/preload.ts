// VOXIS 4.0 DENSE — Electron Preload Script
// Copyright (c) 2026 Glass Stone LLC. All Rights Reserved.

import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('electronAPI', {
  dialog: {
    openFile: (): Promise<string | null> =>
      ipcRenderer.invoke('dialog:openFile'),
  },
  trinity: {
    runEngine: (params: {
      filePath: string;
      mode: string;
      stereoWidth: number;
      outputFormat: string;
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
  },
  shell: {
    openPath: (filePath: string): Promise<void> =>
      ipcRenderer.invoke('shell:openPath', filePath),
  },
});
