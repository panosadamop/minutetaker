const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('mt', {
  engineInfo: () => ipcRenderer.invoke('engine-info'),
  saveFile: (defaultName, data) => ipcRenderer.invoke('save-file', { defaultName, data }),
  openPath: (p) => ipcRenderer.invoke('open-path', p),
  showInFolder: (p) => ipcRenderer.invoke('show-in-folder', p),
  pickImage: () => ipcRenderer.invoke('pick-image'),
  onEngineExit: (cb) => ipcRenderer.on('engine-exit', (_e, code) => cb(code)),
});
