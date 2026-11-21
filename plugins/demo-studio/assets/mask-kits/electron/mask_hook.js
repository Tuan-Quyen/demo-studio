// demo-studio mask kit (Electron, main process). Loaded with `electron -r mask_hook.js <app>`.
// Adds mask_preload.js to every session; the preload then runs the FULL privacy_mask.js + privacy_oracle.js in the
// page's main world (same code and same assertions as the web adapter). Inactive unless DS_MASK_PAYLOAD is set.
'use strict';
const fs = require('fs');
const path = require('path');
const { app, ipcMain, session } = require('electron');

const PAYLOAD = process.env.DS_MASK_PAYLOAD;
const PRELOAD = path.join(__dirname, 'mask_preload.js');

if (PAYLOAD) {
  let code = null;
  ipcMain.on('ds-mask:payload', (e) => {          // the sandboxed preload has no fs: it asks for the script text
    try { if (code === null) code = fs.readFileSync(PAYLOAD, 'utf8'); e.returnValue = code; } catch (err) { e.returnValue = ''; }
  });
  const add = (s) => { if (!s.getPreloads().includes(PRELOAD)) s.setPreloads([...s.getPreloads(), PRELOAD]); };
  app.on('session-created', add);
  app.whenReady().then(() => add(session.defaultSession));
}
