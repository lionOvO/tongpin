import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import Home from './pages/Home.vue'
import Admin from './pages/Admin.vue'
import Jobs from './pages/Jobs.vue'
import Resumes from './pages/Resumes.vue'
import Reports from './pages/Reports.vue'
import Preferences from './pages/Preferences.vue'
import Matches from './pages/Matches.vue'
import Compare from './pages/Compare.vue'
import Governance from './pages/Governance.vue'
import Login from './pages/Login.vue'
import EnterpriseVerification from './pages/EnterpriseVerification.vue'
import AIWorkspace from './pages/AIWorkspace.vue'
import RecruiterAI from './pages/RecruiterAI.vue'
import Applications from './pages/Applications.vue'
import Messages from './pages/Messages.vue'
import './theme.css'
import './style.css'
import './ai-workspace.css'
import './shell.css'
import './visual-system.css'
import './messages.css'
import './interaction-system.css'
import './recruiter-workspace.css'
import './theme-surfaces.css'
import './button-depth.css'
import { state, initialize, notifyError, switchWorkspace, setSessionScope } from './store'
import { staffRedirect, sessionScopeForPath } from './navigation'
const router = createRouter({ history: createWebHistory(), routes: [
  { path: '/', component: Home, meta: { title: '同频 · 从了解，走向同频' } },
  { path: '/login', component: Login, props: { mode: 'login' }, meta: { title: '账号登录' } },
  { path: '/register', component: Login, props: { mode: 'register' }, meta: { title: '验证码注册' } },
  { path: '/forgot-password', component: Login, props: { mode: 'reset' }, meta: { title: '设置／找回密码' } },
  { path: '/admin/login', component: Login, props: { mode: 'login', admin: true }, meta: { title: '平台工作人员登录' } },
  { path: '/admin/forgot-password', component: Login, props: { mode: 'reset', admin: true }, meta: { title: '管理账号设置／找回密码' } },
  ...(['overview', 'accounts', 'jobs', 'resumes', 'events'] as const).map((section, i) => ({ path: section === 'overview' ? '/admin' : '/admin/' + section, component: Admin, props: { section }, meta: { admin: true, title: ['监管概览', '账号监管', '招聘岗位监管', '求职资料监管', '操作记录'][i] } })),
  { path: '/admin/enterprise-reviews', component: EnterpriseVerification, props: { review: true }, meta: { title: '企业资质审核', admin: true } },
  { path: '/admin/governance', component: Governance, meta: { title: '审计与标准配置', admin: true } },
  { path: '/workspace', component: Home, meta: { title: '工作台' } },
  { path: '/jobs', component: Jobs, meta: { title: '岗位与用人需求' } },
  { path: '/applications', component: Applications, meta: { title: '投递与邀请' } },
  { path: '/messages', component: Messages, meta: { title: '消息中心' } },
  { path: '/resumes', component: Resumes, meta: { title: '简历材料' } },
  { path: '/reports', component: Reports, meta: { title: '能力报告与审阅', enterprise: true } },
  { path: '/fit', component: Reports, meta: { title: '我的岗位对照', candidate: true } },
  { path: '/ai-workspace', component: AIWorkspace, meta: { title: 'AI 工作区', candidate: true } },
  { path: '/recruiter-ai', component: RecruiterAI, meta: { title: '招聘 AI 工作区', enterprise: true } },
  { path: '/preferences', component: Preferences, meta: { title: '偏好与期待' } },
  { path: '/matches', component: Matches, meta: { title: '双方偏好对照' } },
  { path: '/compare', component: Compare, meta: { title: '岗位契合度与比较' } },
  { path: '/governance', redirect: '/admin/governance' },
  { path: '/enterprise-verification', component: EnterpriseVerification, meta: { title: '企业认证' } },
  { path: '/enterprise-reviews', redirect: '/admin/enterprise-reviews' },
  { path: '/:pathMatch(.*)*', redirect: '/' },
] })
router.beforeEach(async to => {
  setSessionScope(sessionScopeForPath(to.path))
  try { await initialize() } catch (e) { notifyError(e); const entry = to.path.startsWith('/admin') ? '/admin/login' : '/login'; if (to.path !== entry) return entry }
  const staffNavigation = staffRedirect(state.user, to)
  if (staffNavigation) return staffNavigation
  if (!state.user && !['/', '/login', '/register', '/forgot-password', '/admin/login', '/admin/forgot-password'].includes(to.path)) return { path: '/login', query: { redirect: to.path } }
  if (state.user && ['/login', '/register'].includes(to.path)) {
    if (to.query.role === 'enterprise' || to.query.role === 'candidate') {
      if (to.query.role === 'enterprise' && state.user.enterprise_status !== 'approved') return '/enterprise-verification'
      try { await switchWorkspace(to.query.role) } catch (e) { notifyError(e); return false }
    }
    return '/workspace'
  }
  const c = state.user?.role === 'candidate'
  if (state.user && ((to.meta.enterprise && c) || (to.meta.candidate && !c))) return '/workspace'
})
router.afterEach(() => { state.success = ''; state.error = '' })
const app = createApp(App)
// Keep keyboard focus inside an open modal and restore it when the modal closes.
const dialogs = new WeakMap<HTMLElement, { handler: (e: KeyboardEvent) => void; previous: HTMLElement | null }>()
app.directive('dialog', {
  mounted(el: HTMLElement) {
    const previous = document.activeElement as HTMLElement | null
    const elements = () => Array.from(el.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href]')).filter(e => e.offsetParent !== null)
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { el.querySelector<HTMLButtonElement>('button[aria-label^="关闭"]')?.click(); return }
      if (e.key !== 'Tab') return
      const items = elements(); const first = items[0]; const last = items.at(-1)
      if (e.shiftKey && (document.activeElement === first || !el.contains(document.activeElement))) { e.preventDefault(); last?.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus() }
    }
    dialogs.set(el,{ handler,previous }); el.addEventListener('keydown',handler)
    ;(el.querySelector<HTMLElement>('[autofocus]') || elements()[0])?.focus()
  },
  unmounted(el: HTMLElement) { const d = dialogs.get(el); if (d) { el.removeEventListener('keydown',d.handler); if (d.previous?.isConnected) d.previous.focus(); dialogs.delete(el) } },
})
app.use(router).mount('#app')
