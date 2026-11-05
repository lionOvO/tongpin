import { defineConfig, type Plugin } from 'vite'
import { createReadStream, readdirSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { createRequire } from 'node:module'
import vue from '@vitejs/plugin-vue'

// Keep PDF fonts, CMaps and image decoders local in both dev and production.
function pdfAssets(): Plugin {
  const root = dirname(createRequire(import.meta.url).resolve('pdfjs-dist/package.json'))
  const version = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8')).version
  const prefix = `pdfjs/${version}/`
  const assets = new Map<string, string>()
  for (const directory of ['cmaps', 'standard_fonts', 'wasm', 'iccs']) {
    for (const file of readdirSync(join(root, directory), { withFileTypes: true })) {
      if (file.isFile()) assets.set(prefix + directory + '/' + file.name, join(root, directory, file.name))
    }
  }
  return {
    name: 'local-pdf-assets',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const file = assets.get((req.url || '').split('?')[0]!.replace(/^\//, ''))
        if (!file) return next()
        res.setHeader('Content-Type', file.endsWith('.wasm') ? 'application/wasm' : file.endsWith('.js') ? 'text/javascript' : 'application/octet-stream')
        createReadStream(file).pipe(res)
      })
    },
    generateBundle() {
      for (const [fileName, path] of assets) this.emitFile({ type: 'asset', fileName, source: readFileSync(path) })
    },
  }
}
export default defineConfig({
  plugins: [vue(), pdfAssets()],
  server: { host: '127.0.0.1', strictPort: true, proxy: { '/api': { target: process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000', changeOrigin: false, rewrite: path => path.replace(/^\/api/, '') } } },
  build: { target: 'es2022' },
})
