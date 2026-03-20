/// <reference types="vite/client" />

interface Window {
  electronAPI: {
    dialog: {
      openFile: () => Promise<string | null>;
      saveFile: (defaultName: string, ext: string) => Promise<string | null>;
    };
    trinity: {
      runEngine: (params: {
        filePath: string;
        mode: string;
        stereoWidth: number;
        outputFormat: string;
        ramLimit?: number;
      }) => Promise<string>;
      getVersion: () => Promise<string>;
      onLog: (callback: (line: string) => void) => void;
      offLog: () => void;
      onDone: (callback: (outputPath: string) => void) => void;
      offDone: () => void;
      cancelEngine: () => Promise<void>;
    };
    shell: {
      openPath: (filePath: string) => Promise<void>;
      openFile: (filePath: string) => Promise<string>;
    };
    file: {
      copy: (src: string, dest: string) => Promise<void>;
      toPreviewUrl: (absPath: string) => string;
    };
    update: {
      onStatus: (cb: (s: { type: string; version?: string; percent?: number }) => void) => void;
      offStatus: () => void;
      download: () => Promise<void>;
      install: () => void;
    };
  };
}
