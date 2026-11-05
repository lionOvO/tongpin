import { describe, expect, it } from 'vitest'
import { applicationByJob } from './hiring'
import type { ApplicationSummary, ApplicationStatus } from './hiring'

const row = (id: string, job: string, status: ApplicationStatus, date: string) => ({
  id, job_id: job, status, created_at: date, job_title: 'Python 工程师', company_name: '同名企业',
}) as ApplicationSummary

describe('岗位与本人投递关联', () => {
  it('依据岗位标识区分同名公司和职位，不能用名称误标已投递', () => {
    const index = applicationByJob([row('application-a', 'job-a', 'submitted', '2026-10-13')])
    expect(index.get('job-a')?.id).toBe('application-a')
    expect(index.has('job-b')).toBe(false)
  })
  it('优先保留仍进行中的投递，旧记录较晚更新不会覆盖它', () => {
    const index = applicationByJob([
      row('history', 'job-a', 'closed', '2026-10-12'),
      row('active', 'job-a', 'invited', '2026-10-11'),
    ])
    expect(index.get('job-a')?.id).toBe('active')
  })
  it('全部结束时选最新投递，撤回不会继续当成有效投递', () => {
    const index = applicationByJob([
      row('old', 'job-a', 'rejected', '2026-10-11'),
      row('withdrawn', 'job-a', 'withdrawn', '2026-10-13'),
    ].reverse())
    expect(index.get('job-a')?.status).toBe('withdrawn')
    expect(applicationByJob([]).size).toBe(0)
  })
})
