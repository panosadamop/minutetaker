// Electron main process: starts the Python engine, creates the window, file dialogs.
const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const { spawn } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const net = require('net');
const path = require('path');

const TOKEN = crypto.randomBytes(24).toString('base64url');
let engineProc = null;
let port = 8765;
let win = null;

function freePort() {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.listen(0, '127.0.0.1', () => { const p = srv.address().port; srv.close(() => resolve(p)); });
  });
}

function engineCommand() {
  // Packaged app: PyInstaller bundle in resources/engine. Dev: system python + ../engine.
  const exe = process.platform === 'win32' ? 'minutetaker-engine.exe' : 'minutetaker-engine';
  const bundled = path.join(process.resourcesPath || '', 'engine', exe);
  if (app.isPackaged && fs.existsSync(bundled)) return { cmd: bundled, args: ['serve', '--port', String(port)], cwd: path.dirname(bundled) };
  const python = process.env.MINUTETAKER_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  return { cmd: python, args: ['-m', 'minutetaker', 'serve', '--port', String(port)], cwd: path.join(__dirname, '..', '..', 'engine') };
}

async function startEngine() {
  if (process.env.MINUTETAKER_ENGINE_URL) return; // external engine (debugging)
  port = await freePort();
  const { cmd, args, cwd } = engineCommand();
  engineProc = spawn(cmd, args, { cwd, env: { ...process.env, MINUTETAKER_TOKEN: TOKEN, PYTHONUNBUFFERED: '1' } });
  engineProc.stdout.on('data', (d) => process.stdout.write(`[engine] ${d}`));
  engineProc.stderr.on('data', (d) => process.stderr.write(`[engine] ${d}`));
  engineProc.on('exit', (code) => {
    if (win && !win.isDestroyed()) win.webContents.send('engine-exit', code);
  });
}

function createWindow() {
  win = new BrowserWindow({
    width: 1360, height: 860, minWidth: 980, minHeight: 640,
    backgroundColor: '#0a0b0d', title: 'MinuteTaker', autoHideMenuBar: true,
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, nodeIntegration: false },
  });
  if (process.env.VITE_DEV) win.loadURL('http://localhost:5173');
  else win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: 'deny' }; });
}

ipcMain.handle('engine-info', () => ({
  base: process.env.MINUTETAKER_ENGINE_URL || `http://127.0.0.1:${port}`,
  token: process.env.MINUTETAKER_ENGINE_URL ? (process.env.MINUTETAKER_TOKEN || '') : TOKEN,
  platform: process.platform,
}));

ipcMain.handle('save-file', async (_e, { defaultName, data }) => {
  const ext = path.extname(defaultName).slice(1);
  const { canceled, filePath } = await dialog.showSaveDialog(win, {
    defaultPath: path.join(app.getPath('documents'), defaultName),
    filters: [{ name: ext.toUpperCase(), extensions: [ext] }],
  });
  if (canceled || !filePath) return null;
  fs.writeFileSync(filePath, Buffer.from(data));
  return filePath;
});

ipcMain.handle('open-path', (_e, p) => shell.openPath(p));
ipcMain.handle('show-in-folder', (_e, p) => shell.showItemInFolder(p));
ipcMain.handle('pick-image', async () => {
  const { canceled, filePaths } = await dialog.showOpenDialog(win, { filters: [{ name: 'Images', extensions: ['png', 'jpg', 'jpeg'] }], properties: ['openFile'] });
  return canceled ? null : filePaths[0];
});

app.whenReady().then(async () => {
  await startEngine();
  createWindow();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});

app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('before-quit', () => { if (engineProc) engineProc.kill(); });
