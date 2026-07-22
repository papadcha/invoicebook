const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
  call:        (cmd, payload = {}) => ipcRenderer.invoke('python', cmd, payload),
  openImportFile: ()               => ipcRenderer.invoke('open-import-dialog'),
  pickPdfFile:    ()               => ipcRenderer.invoke('open-pdf-dialog'),
  openStoredFile: (filename)       => ipcRenderer.invoke('open-stored-file', filename),
  minimize:    () => ipcRenderer.send('window-minimize'),
  maximize:    () => ipcRenderer.send('window-maximize'),
  close:       () => ipcRenderer.send('window-close'),
  platform:    process.platform,
});
