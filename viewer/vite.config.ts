import { defineConfig, Plugin } from 'vite';
import path from 'path';
import fs from 'fs';

function serveOutPlugin(): Plugin {
  return {
    name: 'serve-out',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url && req.url.startsWith('/out/')) {
          const relativePath = decodeURIComponent(req.url.slice('/out/'.length).split('?')[0]);
          const filePath = path.resolve(process.cwd(), '../out', relativePath);
          if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
            if (filePath.endsWith('.json')) {
              res.setHeader('Content-Type', 'application/json');
            } else if (filePath.endsWith('.webp')) {
              res.setHeader('Content-Type', 'image/webp');
            } else if (filePath.endsWith('.png')) {
              res.setHeader('Content-Type', 'image/png');
            } else if (filePath.endsWith('.bin')) {
              res.setHeader('Content-Type', 'application/octet-stream');
            }
            fs.createReadStream(filePath).pipe(res);
            return;
          }
        }
        next();
      });
    }
  };
}

export default defineConfig({
  plugins: [serveOutPlugin()],
  server: {
    port: 5173
  }
});
