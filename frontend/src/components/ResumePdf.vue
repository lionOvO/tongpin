<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch, nextTick } from 'vue'
import { FileText, ChevronLeft, ChevronRight, LoaderCircle } from '@lucide/vue'
import { apiBlob } from '../store'
import type { PDFDocumentLoadingTask, PDFDocumentProxy, RenderTask } from 'pdfjs-dist'

const props = defineProps<{ resumeId: string; name: string; compact?: boolean }>()
const host = ref<HTMLElement>(); const canvas = ref<HTMLCanvasElement>()
const loading = ref(true); const rendering = ref(false); const error = ref('')
const page = ref(1); const pages = ref(0)
let document: PDFDocumentProxy | undefined
let task: PDFDocumentLoadingTask | undefined
let renderTask: RenderTask | undefined
let resize: ResizeObserver | undefined
let visible: IntersectionObserver | undefined
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false; let started = false; let revision = 0
const abort = new AbortController()

async function render() {
  if (disposed || !document || !canvas.value || !host.value) return
  const ticket = ++revision
  const previous = renderTask
  renderTask?.cancel()
  rendering.value = true
  try {
    if (previous) await previous.promise.catch(() => {})
    const pdfPage = await document.getPage(page.value)
    if (disposed || ticket !== revision) return
    const width = host.value.clientWidth
    if (!width) return
    const base = pdfPage.getViewport({ scale: 1 })
    const density = Math.min(window.devicePixelRatio || 1, 2, Math.sqrt(4000000 / (width * width * base.height / base.width)))
    const viewport = pdfPage.getViewport({ scale: width / base.width * density })
    const target = canvas.value
    target.width = Math.ceil(viewport.width); target.height = Math.ceil(viewport.height)
    target.style.aspectRatio = `${viewport.width} / ${viewport.height}`
    const context = target.getContext('2d')
    if (!context) throw new Error('浏览器无法显示 PDF 画面，请下载原文件查看。')
    renderTask = pdfPage.render({ canvas: target, canvasContext: context, viewport })
    await renderTask.promise
    if (!disposed && ticket === revision) { loading.value = false; error.value = '' }
  } catch (cause) {
    if (!disposed && ticket === revision) {
      error.value = cause instanceof Error && cause.name !== 'RenderingCancelledException' ? 'PDF 画面未能加载，请下载原文件查看。' : ''
      loading.value = false
    }
  } finally { if (ticket === revision) rendering.value = false }
}

async function load() {
  if (started || disposed) return
  started = true
  try {
    const [blob, pdfjs] = await Promise.all([apiBlob('/resumes/' + props.resumeId + '/original', abort.signal), import('pdfjs-dist')])
    if (disposed) return
    pdfjs.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).href
    const assetRoot = `/pdfjs/${pdfjs.version}/`
    const bytes = new Uint8Array(await blob.arrayBuffer())
    if (disposed) return
    task = pdfjs.getDocument({ data: bytes, enableXfa: false, cMapUrl: assetRoot + 'cmaps/', cMapPacked: true,
      standardFontDataUrl: assetRoot + 'standard_fonts/', wasmUrl: assetRoot + 'wasm/', iccUrl: assetRoot + 'iccs/' })
    document = await task.promise
    if (disposed) return
    pages.value = document.numPages
    await nextTick(); await render()
  } catch (cause) {
    if (!disposed) {
      error.value = cause instanceof Error && !('name' in cause && cause.name === 'AbortError') ? cause.message : '原 PDF 未能加载，请下载原文件查看。'
      loading.value = false
    }
  }
}
watch(page, render)
onMounted(() => {
  resize = new ResizeObserver(() => { clearTimeout(timer); timer = setTimeout(render, 120) })
  if (host.value) resize.observe(host.value)
  if (props.compact && host.value && 'IntersectionObserver' in window) {
    visible = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) { visible?.disconnect(); void load() }
    }, { rootMargin: '160px' })
    visible.observe(host.value)
  } else void load()
})
onUnmounted(() => {
  disposed = true; revision++; abort.abort(); clearTimeout(timer); resize?.disconnect(); visible?.disconnect()
  renderTask?.cancel(); void task?.destroy().catch(() => {})
})
</script>

<template>
  <div :class="['resume-pdf', { 'resume-pdf-compact': compact }]" :aria-busy="loading || rendering">
    <div v-if="!compact && pages > 1" class="resume-pdf-pagination" role="group" aria-label="PDF 翻页">
      <button class="secondary" :disabled="page <= 1 || rendering" aria-label="上一页" @click="page--"><ChevronLeft :size="17" /></button>
      <span aria-live="polite">第 {{ page }} / {{ pages }} 页</span>
      <button class="secondary" :disabled="page >= pages || rendering" aria-label="下一页" @click="page++"><ChevronRight :size="17" /></button>
    </div>
    <div ref="host" class="resume-pdf-page">
      <canvas ref="canvas" v-show="!loading && !error" role="img" :aria-label="name + '，原 PDF 第 ' + page + ' 页'" />
      <div v-if="loading || error" class="resume-pdf-placeholder" :role="compact ? undefined : 'status'">
        <FileText v-if="error" :size="30" /><LoaderCircle v-else class="spin" :size="26" />
        <p>{{ error ? (compact ? '原 PDF 预览暂不可用' : error) : '正在加载原 PDF…' }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.resume-pdf{width:100%;min-width:0}
.resume-pdf-page{width:100%;background:#fff;position:relative}
.resume-pdf-page canvas{display:block;width:100%;height:auto}
.resume-pdf-placeholder{aspect-ratio:210/297;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;padding:24px;color:var(--text-muted);text-align:center;font-size:13px;box-sizing:border-box}
.resume-pdf-placeholder p{max-width:25em;overflow-wrap:anywhere}
.resume-pdf-pagination{display:flex;align-items:center;justify-content:center;gap:18px;padding:12px;background:var(--surface-paper);border-bottom:1px solid var(--border-soft);font-size:13px}
.resume-pdf-pagination button{padding:7px;min-height:34px}
.resume-pdf-compact .resume-pdf-placeholder{font-size:11px}
</style>
