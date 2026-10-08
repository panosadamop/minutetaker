// Builds a self-contained engine executable with PyInstaller into desktop/engine-dist.
const { execSync } = require('child_process');
const path = require('path');

const engine = path.join(__dirname, '..', '..', 'engine');
const out = path.join(__dirname, '..', 'engine-dist');
const py = process.env.MINUTETAKER_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const run = (c) => { console.log('>', c); execSync(c, { cwd: engine, stdio: 'inherit' }); };

run(`${py} -m pip install pyinstaller ".[all]"`);
run(`${py} -m PyInstaller --noconfirm --onedir --name minutetaker-engine --distpath "${out}" ` +
    `--collect-all faster_whisper --collect-all ctranslate2 --collect-submodules uvicorn ` +
    `--hidden-import soundcard --hidden-import keyring.backends minutetaker/__main__.py`);
// onedir puts files in engine-dist/minutetaker-engine/*; flatten for electron-builder extraResources
const fs = require('fs');
const inner = path.join(out, 'minutetaker-engine');
for (const f of fs.readdirSync(inner)) fs.renameSync(path.join(inner, f), path.join(out, f));
fs.rmdirSync(inner);
console.log('Engine bundled into', out);
