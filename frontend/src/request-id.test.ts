import { afterEach, expect, test, vi } from 'vitest'
import { createRequestId } from './request-id'

afterEach(() => vi.unstubAllGlobals())

test('uses native UUIDs when available', () => {
  const randomUUID = vi.fn(() => '41b1095d-b9a4-4ea7-8881-ce2620e92256')
  vi.stubGlobal('crypto', { randomUUID })
  expect(createRequestId()).toBe('41b1095d-b9a4-4ea7-8881-ce2620e92256')
  expect(randomUUID).toHaveBeenCalledOnce()
})

test('HTTP contexts without randomUUID still produce distinct valid UUIDs', () => {
  const source = globalThis.crypto
  vi.stubGlobal('crypto', { getRandomValues: source.getRandomValues.bind(source) })
  const ids = Array.from({ length: 50 }, () => createRequestId())
  expect(new Set(ids).size).toBe(50)
  ids.forEach(id => expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/))
})
