// npm run public: serve the app locally and expose it through a Cloudflare quick tunnel.
// PORT env var picks the local port (default 3000). Ctrl-C stops both processes.
const { spawn } = require('child_process');
const path = require('path');

const port = process.env.PORT || '3000';
const root = path.join(__dirname, '..');
const procs = [];

function run(name, args, onLine) {
  const p = spawn('npx', ['--yes', ...args], { cwd: root, shell: true });
  for (const s of [p.stdout, p.stderr]) {
    let buf = '';
    s.on('data', (d) => {
      buf += d;
      const lines = buf.split(/\r?\n/);
      buf = lines.pop();
      for (const l of lines) if (l.trim()) onLine(l);
    });
  }
  p.on('exit', (code) => { console.log(`[${name}] saiu (${code})`); stop(code || 0); });
  procs.push(p);
}

let stopping = false;
function stop(code) {
  if (stopping) return;
  stopping = true;
  for (const p of procs) {
    if (p.exitCode !== null) continue;
    // shell:true wraps the child; on Windows kill the whole tree
    if (process.platform === 'win32') spawn('taskkill', ['/pid', String(p.pid), '/T', '/F']);
    else p.kill('SIGINT');
  }
  setTimeout(() => process.exit(code), 500);
}
process.on('SIGINT', () => stop(0));
process.on('SIGTERM', () => stop(0));

// serve silently picks another port when this one is busy, and the tunnel would then
// expose whatever still listens here, so refuse to start instead
const probe = require('net').createServer();
probe.once('error', () => {
  console.error(`Porta ${port} ocupada. Feche o outro servidor ou use PORT=<porta>.`);
  process.exit(1);
});
probe.listen(+port, () => probe.close(start));

function start() {
  run('serve', ['serve', '.', '-l', port, '--no-port-switching'], (l) => {
    if (!/^\s*HTTP\s/.test(l)) console.log(`[serve] ${l}`);
  });
  run('cloudflared', ['cloudflared', 'tunnel', '--url', `http://localhost:${port}`], (l) => {
    const m = l.match(/https:\/\/[a-z0-9-]+\.trycloudflare\.com/);
    if (m) console.log(`\n  Publico: ${m[0]}\n`);
    else if (/ERR|error/i.test(l)) console.log(`[cloudflared] ${l}`);
  });
}
