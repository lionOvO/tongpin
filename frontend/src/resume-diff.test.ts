import { expect, it } from 'vitest'
import { paragraphDiff } from './resume-diff'
it('突出真实改动并保留前后上下文', () => {
  expect(paragraphDiff('我负责接口开发。', '我负责业务接口测试。')).toEqual({ prefix: '我负责', removed: '接口开发', added: '业务接口测试', suffix: '。' })
})
it('处理新增、删除及 Unicode，不把相同段落标为修改', () => {
  expect(paragraphDiff('项目😀', '项目😀')).toEqual({ prefix: '项目😀', removed: '', added: '', suffix: '' })
  expect(paragraphDiff('负责开发', '负责')).toEqual({ prefix: '负责', removed: '开发', added: '', suffix: '' })
  expect(paragraphDiff('负责', '负责接口')).toEqual({ prefix: '负责', removed: '', added: '接口', suffix: '' })
})
