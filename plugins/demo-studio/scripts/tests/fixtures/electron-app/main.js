// tiny fixture app for test_electron.py: one frameless 800x600 window at 0,0
const { app, BrowserWindow } = require('electron');
app.whenReady().then(() => {
  const w = new BrowserWindow({ x: 0, y: 0, width: 800, height: 600, useContentSize: true, frame: false, show: true,
                                webPreferences: { contextIsolation: true } });
  w.loadFile(__dirname + '/index.html');
});
app.on('window-all-closed', () => app.quit());
