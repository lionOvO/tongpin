import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

const vuePlugin = vue()
const transform = vuePlugin.transform
const transformVue = typeof transform === 'function' ? transform : transform!.handler
// Component tests use Vue's client renderer with a lightweight host, without a DOM.
vuePlugin.transform = {
  handler(code, id, options) {
    return transformVue.call(this, code, id, { ...options, ssr: false })
  },
}
export default defineConfig({ plugins: [vuePlugin] })
