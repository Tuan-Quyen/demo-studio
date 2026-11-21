// demo-studio mask kit (Electron, renderer preload; registered by mask_hook.js). Runs before the page's own scripts.
// Executes the mask payload (config + privacy_mask.js + privacy_oracle.js + log sink) in the MAIN world, so the page
// sees exactly what a Playwright init script would give it on the web. Fail closed: if this does not run, the
// adapter's assertMasked() finds no window.__dsMask and refuses to record (exit 11).
'use strict';
const { webFrame, ipcRenderer } = require('electron');
try {
  const code = ipcRenderer.sendSync('ds-mask:payload');
  if (code) webFrame.executeJavaScript(code);
} catch (e) { /* adapter assertion reports the missing mask */ }
