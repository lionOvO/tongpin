<script setup lang="ts">
import { computed, watch, ref, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowUpRight, LayoutDashboard, BriefcaseBusiness, Files, ScanText, SlidersHorizontal, GitCompareArrows, HeartHandshake, ShieldCheck, PanelLeftClose, PanelLeftOpen, LoaderCircle, Sparkles, Inbox, MessageSquare } from '@lucide/vue'
import { state, candidate, logout, action, refresh, notifyError, switchWorkspace } from './store'
import { inbox, clearInbox, refreshInbox } from './messages'
import VideoCallPanel from './components/VideoCallPanel.vue'
const inboxUnread = computed(() => inbox.unread)
let inboxTimer: ReturnType<typeof setInterval> | undefined
async function refreshNotifications() { if (document.visibilityState === 'visible') { try { await refreshInbox() } catch { /* The message page provides connection feedback. */ } } }
watch(() => [state.actor, state.sessionScope, state.epoch], () => { clearInbox(); void refreshNotifications() })
onMounted(() => { void refreshNotifications(); inboxTimer = setInterval(refreshNotifications, 20000); document.addEventListener('visibilitychange', refreshNotifications) })
onBeforeUnmount(() => { clearInterval(inboxTimer); document.removeEventListener('visibilitychange', refreshNotifications) })
const route = useRoute(); const router = useRouter(); const mobileOpen = ref(false)
const sidebarCollapsed = ref(false)
const mobileQuery = window.matchMedia('(max-width:760px)')
const mobileViewport = ref(mobileQuery.matches)
const navigationToggle = ref<HTMLButtonElement | null>(null)
const navigationHidden = computed(() => ['/ai-workspace', '/recruiter-ai'].includes(route.path) && state.aiFocus || (mobileViewport.value ? !mobileOpen.value : sidebarCollapsed.value))
const workspaceLabel = computed(() => state.switching ? '正在切换…' : candidate.value ? state.user?.enterprise_status === 'approved' ? '切换到招聘方' : '企业认证 · 招聘方入口' : '切换到求职者')
function toggleNavigation() { if (mobileViewport.value) mobileOpen.value = !mobileOpen.value; else sidebarCollapsed.value = !sidebarCollapsed.value }
function closeNavigation() { if (mobileViewport.value) mobileOpen.value = false; else sidebarCollapsed.value = true; navigationToggle.value?.focus() }
function updateViewport(event: MediaQueryListEvent) { mobileViewport.value = event.matches; mobileOpen.value = false }
function closeOnEscape(event: KeyboardEvent) { if (event.key === 'Escape' && mobileOpen.value) closeNavigation() }
onMounted(() => { mobileQuery.addEventListener('change', updateViewport); window.addEventListener('keydown', closeOnEscape) })
onBeforeUnmount(() => { mobileQuery.removeEventListener('change', updateViewport); window.removeEventListener('keydown', closeOnEscape) })
watch(() => route.path, () => { mobileOpen.value = false })
const staff = computed(() => state.user?.role === 'admin')
const groups = computed(() => staff.value ? [{ name: '平台监管', links: [
{ to: '/admin', title: '监管概览', icon: LayoutDashboard }, { to: '/admin/enterprise-reviews', title: '企业资质审核', icon: ShieldCheck }, { to: '/admin/accounts', title: '账号监管', icon: HeartHandshake }, { to: '/admin/jobs', title: '招聘岗位', icon: BriefcaseBusiness }, { to: '/admin/resumes', title: '求职资料', icon: Files }, { to: '/admin/events', title: '操作记录', icon: ScanText }, { to: '/admin/governance', title: '审计与标准配置', icon: SlidersHorizontal }
] }] : [
  { name: '工作空间', links: [{ to: '/workspace', title: '工作台', icon: LayoutDashboard }, { to: candidate.value ? '/ai-workspace' : '/recruiter-ai', title: candidate.value ? 'AI 工作区' : '招聘 AI 工作区', icon: Sparkles }, { to: '/jobs', title: candidate.value ? '查看岗位' : '岗位与需求', icon: BriefcaseBusiness }, { to: '/applications', title: candidate.value ? '我的投递' : '应聘与邀请', icon: Inbox }, { to: '/messages', title: '消息中心', icon: MessageSquare }, { to: '/resumes', title: candidate.value ? '我的简历' : '简历与初筛', icon: Files }, { to: candidate.value ? '/fit' : '/reports', title: candidate.value ? '我的岗位对照' : '报告与审阅', icon: ScanText }, { to: '/compare', title: candidate.value ? '岗位契合度' : '已确认报告比较', icon: GitCompareArrows }] },
  { name: '彼此期待', links: [{ to: '/preferences', title: candidate.value ? '我的偏好' : '团队偏好与氛围', icon: SlidersHorizontal }, { to: '/matches', title: '双方偏好对照', icon: HeartHandshake }] },
])
const actorName = computed(() => state.user?.name || '')
const exiting = ref(false)
watch(() => state.user, user => { if (!user && !state.loading && !state.switching && !['/', '/login', '/register', '/forgot-password', '/admin/login', '/admin/forgot-password'].includes(route.path)) { mobileOpen.value = false; router.replace(route.path.startsWith('/admin') ? '/admin/login' : '/login') } })
async function exit() { exiting.value = true; try { await logout(); await router.replace(route.path.startsWith('/admin') ? '/admin/login' : '/login') } catch(e) { notifyError(e) } finally { exiting.value = false } }
async function switchSide() {
  mobileOpen.value = false
  if (candidate.value && state.user?.enterprise_status !== 'approved') { await router.push('/enterprise-verification'); return }
  try { await switchWorkspace(candidate.value ? 'enterprise' : 'candidate'); await router.replace('/workspace') } catch (e) { notifyError(e) }
}
watch(() => state.user?.workspace_role, (role, previous) => {
  if (state.sessionScope === 'user' && role && previous && role !== previous && !['/', '/login', '/register', '/forgot-password', '/admin/login', '/admin/forgot-password'].includes(route.path)) router.replace('/workspace')
})
</script>
<template>
  <VideoCallPanel />
  <div v-if="['/', '/login', '/register', '/forgot-password', '/admin/login', '/admin/forgot-password'].includes(route.path)" :class="['landing-shell', { 'landing-shell-public': route.path === '/' }]"><RouterView :key="route.path" /></div>
  <div v-else-if="state.user" :class="['app-shell', { 'app-shell-ai': route.path === '/ai-workspace', 'app-shell-messages': route.path === '/messages', 'app-shell-recruiter': route.path === '/recruiter-ai', 'app-shell-ai-focused': ['/ai-workspace', '/recruiter-ai'].includes(route.path) && state.aiFocus, 'sidebar-collapsed': sidebarCollapsed }]">
    <button v-if="mobileOpen" class="nav-scrim" @click="closeNavigation" aria-label="关闭导航" />
    <aside id="workspace-navigation" :class="['sidebar', { open: mobileOpen }]" :inert="navigationHidden">
      <div class="sidebar-heading"><RouterLink :to="staff ? '/admin' : '/'" class="brand"><span class="brand-symbol">同</span><strong>同频<small>TONGPIN</small></strong></RouterLink></div>
      <button class="sidebar-collapse" @click="closeNavigation" aria-controls="workspace-navigation"><PanelLeftClose :size="15" /><span>收起侧边栏</span></button>
      <div v-if="staff || !candidate" class="workspace-tag"><span class="status-dot" />{{ staff ? '同频平台管理端' : '招聘团队工作空间' }}</div>
      <button v-if="!staff" class="workspace-switch" :title="workspaceLabel" :disabled="state.busy || state.loading || state.switching || exiting" @click="switchSide"><component :is="candidate ? BriefcaseBusiness : HeartHandshake" :size="16" /><span>{{ workspaceLabel }}</span><ArrowUpRight :size="15" /></button>
      <nav aria-label="主导航"><div v-for="g in groups" :key="g.name" class="nav-group"><p>{{ g.name }}</p><RouterLink v-for="link in g.links" :key="link.to" :to="link.to" :active-class="staff ? 'staff-parent-active' : 'router-link-active'" exact-active-class="router-link-active" @click="mobileOpen = false"><component :is="link.icon" :size="19" /><span>{{ link.title }}</span><span v-if="link.to === '/messages' && inboxUnread" class="nav-unread" :aria-label="inboxUnread + ' 条未读'">{{ inboxUnread > 99 ? '99+' : inboxUnread }}</span><span class="nav-end">↗</span></RouterLink></div></nav>
      <div class="sidebar-foot"><p>{{ staff ? '守护真实与可信的相遇。' : '让每一份期待，都被看见。' }}</p><small>{{ staff ? '内部工作人员 · 操作全程留痕' : '独立账号 · 选择有据可循' }}</small></div>
    </aside>
    <div class="main-shell"><header class="topbar"><div class="topbar-leading"><button ref="navigationToggle" class="icon-button navigation-toggle" @click="toggleNavigation" :aria-label="navigationHidden ? '展开侧边栏' : '收起侧边栏'" :title="navigationHidden ? '展开侧边栏' : '收起侧边栏'" :aria-expanded="!navigationHidden" aria-controls="workspace-navigation"><component :is="navigationHidden ? PanelLeftOpen : PanelLeftClose" :size="20" /></button><div class="breadcrumb">同频 <span>/</span> {{ route.meta.title }}</div></div><div class="topbar-actions"><span class="demo-tag">{{ state.user.role === 'admin' ? '平台工作人员' : candidate ? '求职者' : '招聘方' }}</span><span class="account-name">{{ actorName }}</span><RouterLink :to="staff ? '/admin/forgot-password' : '/forgot-password'" class="text-link">{{ state.user.has_password ? '修改密码' : '设置密码' }}</RouterLink><button class="text-link" :disabled="exiting || state.loading || state.switching || state.busy" @click="exit">{{ exiting ? '正在退出…' : '退出登录' }}</button><span class="user-avatar">{{ candidate ? '我' : '同' }}</span></div></header>
      <main><div v-if="state.error" class="feedback error" role="alert">{{ state.error }}<button @click="state.error = ''" aria-label="关闭错误提示">×</button></div><div v-if="state.success" class="feedback success" role="status">{{ state.success }}<button @click="state.success = ''" aria-label="关闭成功提示">×</button></div><div v-if="state.loading" class="loading"><LoaderCircle class="spin" /> 正在加载工作空间…</div><template v-else-if="!state.presentation"><div class="empty"><h3>暂时无法连接服务</h3><p>请确认前后端已启动，随后重新加载。</p><button class="primary" @click="action(refresh)">重新连接</button></div></template><RouterView v-else :key="state.actor + route.path" /></main>
      <footer class="app-footer"><span>同频 · 基于原文的双向理解</span><span>{{ state.health?.llm_mode !== 'demo' ? 'AI 分析' : '本地演示规则' }} · {{ state.health?.env || '连接中' }}</span></footer>
    </div>
    <div v-if="state.busy" class="busy-indicator" role="status"><LoaderCircle class="spin" :size="17" />{{ state.progress || '正在处理，请稍候…' }}</div>
  </div>
</template>
