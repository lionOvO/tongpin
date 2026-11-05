import { beforeEach, afterEach, expect, it, vi } from 'vitest'
vi.stubGlobal('sessionStorage', { getItem: () => null, setItem: () => {} })
const { streamApi, state, clearSession } = await import('./store')
beforeEach(() => { clearSession(); state.csrf = 'test-csrf' })
afterEach(() => vi.restoreAllMocks())
function fakeStream(text: string, bytewise = false) {
  const bytes = new TextEncoder().encode(text)
  return new Response(new ReadableStream({ start(controller) {
    if (bytewise) bytes.forEach(byte => controller.enqueue(new Uint8Array([byte])))
    else controller.enqueue(bytes)
    controller.close()
  } }), { headers: { 'Content-Type': 'text/event-stream' } })
}
it('真实 SSE 片段跨字节/换行边界解析，带 CSRF 与当前标签页身份，仅提交一次', async () => {
  const receive = vi.fn(); const fetch = vi.fn(async (_url: string, _init: RequestInit) => fakeStream(': keepalive\r\n\r\nevent: preview\r\ndata: "你好"\r\n\r\nevent: done\r\ndata: {"version":2}\r\n\r\n', true))
  vi.stubGlobal('fetch', fetch)
  await expect(streamApi('/ai/workspaces/example/turns/stream', { expected_version: 1 }, receive)).resolves.toEqual({ version: 2 })
  expect(receive).toHaveBeenCalledExactlyOnceWith('preview', '你好')
  expect(fetch).toHaveBeenCalledTimes(1)
  const init = fetch.mock.calls[0]![1] as RequestInit
  expect(init.credentials).toBe('same-origin')
  expect(init.headers).toMatchObject({ 'X-CSRF-Token': 'test-csrf', 'X-Session-Scope': 'user' })
})
it('流中校验失败保留明确错误，不重发写操作', async () => {
  const fetch = vi.fn(async () => fakeStream('event: preview\ndata: "预览"\n\nevent: error\ndata: {"code":"AI_AGENT_VALIDATION","message":"引用未通过"}\n\n'))
  vi.stubGlobal('fetch', fetch)
  await expect(streamApi('/test', {}, vi.fn())).rejects.toMatchObject({ code: 'AI_AGENT_VALIDATION', message: '引用未通过' })
  expect(fetch).toHaveBeenCalledTimes(1)
})
it('断流不把预览当成正式结果，也不自动重试', async () => {
  const fetch = vi.fn(async () => fakeStream('event: preview\ndata: "部分回答"\n\n'))
  vi.stubGlobal('fetch', fetch)
  await expect(streamApi('/test', {}, vi.fn())).rejects.toThrow('连接已中断')
  expect(fetch).toHaveBeenCalledTimes(1)
})
it('切换身份后丢弃旧流的结果', async () => {
  let output!: ReadableStreamDefaultController<Uint8Array>
  vi.stubGlobal('fetch', vi.fn(async () => new Response(new ReadableStream({ start(c) { output = c } }), { headers: { 'Content-Type': 'text/event-stream' } })))
  const receive = vi.fn(); const promise = streamApi('/test', {}, receive)
  await new Promise(resolve => setTimeout(resolve, 0))
  clearSession()
  output.enqueue(new TextEncoder().encode('event: done\ndata: {"private":"old-account"}\n\n')); output.close()
  await expect(promise).rejects.toMatchObject({ code: 'STALE_CONTEXT' })
  expect(receive).not.toHaveBeenCalled()
})
