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

  file: {
    // Copy outputFile to a user-chosen destination (Save As)
    copy: (src: string, dest: string): Promise<void> =>
      ipcRenderer.invoke('file:copy', src, dest),

    // Convert an absolute local path to a voxis-file:// URL for <audio> preview
    toPreviewUrl: (absPath: string): string => {
      const encoded = absPath.split('/').map(encodeURIComponent).join('/');
      return `voxis-file://${encoded}`;
    },
  },
});
