const { chromium } = require('@playwright/test');
const { spawn } = require('child_process');
(async () => {
  const srv = spawn('npm', ['run', 'preview', '--', '--port', '4188', '--host', '127.0.0.1'], { shell: true, cwd: process.cwd() });
  await new Promise(r => setTimeout(r, 4000));
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1440, height: 260 } });
  try {
    await p.goto('http://127.0.0.1:4188/', { waitUntil: 'domcontentloaded', timeout: 15000 });
    await p.waitForTimeout(1500);
    await p.screenshot({ path: '../docs/shots/header-full-1440.png' });
    console.log('SHOT_OK');
  } catch (e) { console.log('ERR', e.message); }
  await b.close(); srv.kill();
})();
