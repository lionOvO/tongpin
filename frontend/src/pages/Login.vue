<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, BriefcaseBusiness, UserRound, ShieldCheck, LoaderCircle, ArrowLeft, Eye, EyeOff } from '@lucide/vue'
import { api, authenticate, state, type AuthPayload } from '../store'
import AdminLoginStory from '../components/AdminLoginStory.vue'
const props = withDefaults(defineProps<{ mode?: 'login' | 'register' | 'reset'; admin?: boolean }>(), { mode: 'login' })
const route = useRoute(); const router = useRouter()
const registration = computed(() => props.mode === 'register'); const resetting = computed(() => props.mode === 'reset')
const method = ref<'password' | 'sms'>('password')
const needsCode = computed(() => props.mode !== 'login' || method.value === 'sms')
const needsPassword = computed(() => props.mode !== 'login' || method.value === 'password')
const title = computed(() => resetting.value && props.admin ? '设置管理账号密码' : props.admin ? '登录同频管理端' : registration.value ? '创建你的同频账号' : resetting.value ? '设置／找回密码' : '登录你的工作空间')
const subtitle = computed(() => props.admin ? resetting.value ? '验证工作人员手机号后，设置新的登录密码。' : '使用平台授权的工作人员账号，进入监管工作空间。' : registration.value ? '先验证手机号，再设置密码，开启独立工作空间。' : resetting.value ? '用注册手机号验证身份，设置新密码。原账号和材料将保留。' : '使用已注册的手机号，选择你方便的登录方式。')
const role = ref<'enterprise' | 'candidate'>(route.query.role === 'enterprise' ? 'enterprise' : 'candidate')
const phone = ref(''); const code = ref(''); const password = ref(''); const confirmation = ref(''); const visible = ref(false)
const error = ref(''); const notice = ref(''); const sending = ref(false); const submitting = ref(false); const accepted = ref(false)
const formElement = ref<HTMLFormElement | null>(null)
const options = ref<{ sms_available: boolean; missing: string[] } | null>(null)
const retryAt = ref(0); const now = ref(Date.now()); const remaining = computed(() => Math.max(0, Math.ceil((retryAt.value - now.value) / 1000)))
const phoneValid = computed(() => /^1[3-9][0-9]{9}$/.test(phone.value.trim()))
const passwordValid = computed(() => password.value.length >= 8 && password.value.length <= 128 && !!password.value.trim())
const validationIssue = computed(() => {
  if (!phoneValid.value) return { field: 'phone', message: phone.value.trim() ? '请输入有效的 11 位中国大陆手机号。' : needsCode.value ? '请填写接收本次验证码的手机号。' : '请填写登录手机号。' }
  if (needsCode.value && !/^[0-9]{6}$/.test(code.value)) return { field: 'code', message: '请输入短信中的 6 位验证码。' }
  if (needsPassword.value && !passwordValid.value) return { field: 'password', message: '密码需要 8–128 个字符，且不能全为空格。' }
  if (needsPassword.value && props.mode !== 'login' && confirmation.value !== password.value) return { field: 'confirmation', message: '两次输入的密码不一致，请重新确认。' }
  if (registration.value && !accepted.value) return { field: 'accepted', message: '请先勾选确认创建独立账号。' }
  if (needsCode.value && !options.value) return { field: 'code', message: '尚未连接短信服务，请点击下方「重新连接短信服务」后重试。' }
  if (needsCode.value && !options.value?.sms_available) return { field: 'code', message: '短信服务尚未配置，请联系管理员。' }
  return null
})
const query = computed(() => ({ ...(typeof route.query.redirect === 'string' ? { redirect: route.query.redirect } : {}), ...(role.value === 'enterprise' ? { role: 'enterprise' } : {}) }))
const timer = setInterval(() => { now.value = Date.now() }, 1000)
onUnmounted(() => { clearInterval(timer); password.value = ''; confirmation.value = ''; code.value = '' })
watch(method, () => { error.value = ''; notice.value = ''; password.value = ''; code.value = '' })
function phoneChanged() { error.value = ''; notice.value = ''; code.value = '' }
function readForm() {
  if (!formElement.value) return
  // Autofill can update native input values before Vue receives an input event.
  const values = new FormData(formElement.value)
  const value = (name: string) => String(values.get(name) ?? '')
  phone.value = value('phone').trim(); code.value = value('code').trim()
  password.value = value('password'); confirmation.value = value('confirmation')
  accepted.value = values.has('accepted')
}
function showIssue(field: string, message: string) {
  error.value = message
  const input = formElement.value?.elements.namedItem(field)
  if (input instanceof HTMLElement) input.focus()
}
async function loadOptions() { try { options.value = await api('/auth/options') } catch (e) { error.value = e instanceof Error ? e.message : '无法连接服务' } }
onMounted(loadOptions)
async function send() {
  if (sending.value || submitting.value) return
  error.value = ''; notice.value = ''
  readForm()
  if (!phoneValid.value) { showIssue('phone', '请填写有效的 11 位中国大陆手机号，再获取验证码。'); return }
  if (registration.value && !accepted.value) { showIssue('accepted', '请先勾选确认创建独立账号。'); return }
  sending.value = true
  try { const result = await api('/auth/sms/send', 'POST', { phone: phone.value.trim(), purpose: registration.value ? 'register' : resetting.value ? 'reset' : 'login' }); retryAt.value = Date.now() + result.retry_after * 1000; now.value = Date.now(); notice.value = result.message; code.value = '' }
  catch (e) { error.value = e instanceof Error ? e.message : '获取验证码失败' }
  finally { sending.value = false }
}
async function submit() {
  if (submitting.value || sending.value) return
  error.value = ''; notice.value = ''
  readForm()
  const issue = validationIssue.value
  if (issue) { showIssue(issue.field, issue.message); return }
  submitting.value = true
  try {
    const payload: AuthPayload = { phone: phone.value.trim() }
    if (needsCode.value) payload.code = code.value
    if (needsPassword.value) payload.password = password.value
    if (!resetting.value && !props.admin) payload.role = role.value
    await authenticate(props.admin && resetting.value ? '/auth/admin/password/reset' : props.admin ? method.value === 'password' ? '/auth/admin/login/password' : '/auth/admin/login/phone' : registration.value ? '/auth/register' : resetting.value ? '/auth/password/reset' : method.value === 'password' ? '/auth/login/password' : '/auth/login/phone', payload)
    password.value = ''; confirmation.value = ''; code.value = ''
    if (state.user?.role === 'admin') { await router.replace('/admin'); return }
    if (!resetting.value && role.value === 'enterprise' && state.user?.enterprise_status !== 'approved') { await router.replace('/enterprise-verification'); return }
    const next = typeof route.query.redirect === 'string' && ['/workspace', '/jobs', '/resumes', '/reports', '/fit', '/preferences', '/matches', '/compare', '/governance'].includes(route.query.redirect) ? route.query.redirect : '/workspace'
    await router.replace(next)
  } catch (e) { error.value = e instanceof Error ? e.message : '操作失败，请重试' }
  finally { submitting.value = false }
}
</script>
<template>
  <div class="auth-page" :class="{ 'auth-page-admin': props.admin }">
    <header class="auth-nav"><RouterLink to="/" class="brand"><span class="brand-symbol">同</span><strong>同频<small>TONGPIN</small></strong></RouterLink><span v-if="props.admin" class="auth-admin-nav-label"><ShieldCheck :size="14" />工作人员入口</span><RouterLink to="/" class="text-link"><ArrowLeft :size="15" />返回首页</RouterLink></header>
    <div class="auth-layout"><section v-if="!props.admin" class="auth-story"><p class="eyebrow">每一份期待，都值得认真对待</p><h1>带着你的期待，<br>找到<span>同频的人。</span></h1><p class="auth-description">从一份具体的经历、一条清晰的要求开始，<br>让下一次相遇，有据可循。</p><div class="auth-dialogue" aria-label="双向选择的示意"><article><small>招聘方的期待</small><p>一起解决具体的问题。</p><div class="auth-evidence"><span /><span /><span /></div></article><span class="auth-bridge">↔</span><article><small>个人的期待</small><p>在实践中，继续成长。</p><div class="auth-evidence"><span /><span /><span /></div></article></div><div class="auth-private"><ShieldCheck :size="20" /><p>你的材料，由你掌握。<small>简历与报告保存在你的账号下；共享对照前，由你确认。</small></p></div></section>
    <AdminLoginStory v-else />
    <section :class="['auth-card', { 'auth-card--login': props.mode === 'login' }]" aria-labelledby="auth-title"><span v-if="props.admin" class="auth-admin-card-mark" aria-hidden="true"><ShieldCheck :size="25" /></span><p class="eyebrow">{{ props.admin ? '同频 · 内部工作空间' : registration ? '从这里，开始同频' : resetting ? '回到你的账号' : '欢迎回来' }}</p><h2 id="auth-title">{{ title }}</h2><p class="auth-subtitle">{{ subtitle }}</p>
      <div v-if="props.mode === 'login'" class="auth-method" role="group" aria-label="登录方式"><button type="button" :class="{ active: method === 'password' }" :aria-pressed="method === 'password'" :disabled="submitting || sending" @click="method = 'password'">密码登录</button><button type="button" :class="{ active: method === 'sms' }" :aria-pressed="method === 'sms'" :disabled="submitting || sending" @click="method = 'sms'">验证码登录</button></div>
      <form ref="formElement" novalidate @submit.prevent="submit">
        <fieldset v-if="!resetting && !props.admin" class="auth-role"><legend>{{ registration ? '选择首次进入的工作空间' : '选择要进入的工作空间' }}</legend><label :class="{selected: role === 'candidate'}"><input name="role" v-model="role" type="radio" value="candidate" :disabled="submitting || sending"><UserRound :size="18" /><span>求职者</span></label><label :class="{selected: role === 'enterprise'}"><input name="role" v-model="role" type="radio" value="enterprise" :disabled="submitting || sending"><BriefcaseBusiness :size="18" /><span>招聘方</span></label></fieldset>
        <small v-if="!resetting && !props.admin" class="auth-role-note">求职空间可直接使用；招聘空间需提交企业资质并经人工核验。两边资料分别保存。</small>
        <label for="auth-phone">手机号码<div class="auth-phone"><span>+86</span><input id="auth-phone" name="phone" v-model="phone" @input="phoneChanged" type="tel" inputmode="numeric" :autocomplete="props.mode === 'login' ? 'username' : 'tel-national'" pattern="1[3-9][0-9]{9}" maxlength="11" placeholder="请输入手机号码" required :disabled="submitting || sending"></div></label>
        <div class="auth-credentials">
        <label :class="{ 'auth-credential-inactive': !needsCode }" :aria-hidden="!needsCode" :inert="!needsCode" for="auth-code">短信验证码<div class="auth-code"><input id="auth-code" name="code" v-model="code" type="text" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" placeholder="6 位验证码" required :disabled="submitting || !needsCode"><button type="button" @click="send" :disabled="!needsCode || sending || submitting || remaining > 0 || !options?.sms_available"><LoaderCircle v-if="sending" class="spin" :size="15" />{{ sending ? '正在发送' : remaining ? `${remaining} 秒后重发` : '获取验证码' }}</button></div></label>
        <div :class="['auth-password-fields', { 'auth-password-pair': props.mode !== 'login', 'auth-credential-inactive': !needsPassword }]" :aria-hidden="!needsPassword" :inert="!needsPassword">
        <label for="auth-password">{{ props.mode === 'login' ? '登录密码' : resetting ? '新密码' : '设置登录密码' }}<div class="auth-password"><input id="auth-password" name="password" v-model="password" :type="visible ? 'text' : 'password'" :autocomplete="props.mode === 'login' ? 'current-password' : 'new-password'" minlength="8" maxlength="128" :placeholder="props.mode === 'login' ? '请输入登录密码' : '8–128 位，建议包含字母和数字'" required :disabled="submitting || !needsPassword"><button type="button" :aria-label="visible ? '隐藏密码' : '显示密码'" :aria-pressed="visible" :disabled="submitting || !needsPassword" @click="visible = !visible"><EyeOff v-if="visible" :size="18" /><Eye v-else :size="18" /></button></div></label>
        <label v-if="props.mode !== 'login'" for="auth-confirmation">确认密码<input id="auth-confirmation" name="confirmation" v-model="confirmation" :type="visible ? 'text' : 'password'" autocomplete="new-password" minlength="8" maxlength="128" placeholder="再次输入密码" required :disabled="submitting"><small v-if="confirmation && confirmation !== password" class="auth-mismatch">两次输入的密码不一致</small></label>
        </div>
        </div>
        <div v-if="props.mode === 'login'" class="auth-help"><span>{{ method === 'sms' ? '仅用于登录已注册账号' : '手机号就是你的登录账号' }}</span><RouterLink :to="{ path: props.admin ? '/admin/forgot-password' : '/forgot-password', query }" class="text-link">设置／找回密码</RouterLink></div>
        <label v-if="registration" class="check auth-consent"><input name="accepted" v-model="accepted" type="checkbox" :disabled="submitting || sending"><span>我确认用此手机号创建独立账号。简历及偏好是否共享由我主动决定。</span></label>
        <div v-if="error" class="feedback error" role="alert">{{ error }}</div><div v-if="notice" class="feedback success" role="status">{{ notice }}</div>
        <div v-if="needsCode && options && !options.sms_available" class="auth-unavailable" role="status"><strong>短信服务待配置</strong><p>管理员完成短信配置后即可获取验证码。</p></div>
        <button class="primary full auth-submit" :disabled="submitting || sending"><LoaderCircle v-if="submitting" class="spin" :size="18" />{{ submitting ? '正在验证…' : registration ? '验证并注册' : resetting ? '验证并设置密码' : props.admin ? '登录管理端' : '登录工作空间' }}<ArrowRight v-if="!submitting" :size="18" /></button>
      </form>
      <p v-if="props.mode === 'login'" class="auth-endnote">{{ method === 'password' ? props.admin ? '手机号与密码用于验证工作人员身份。' : '使用已注册账号登录，个人材料由你掌握。' : '仅登录已注册账号，验证码有效期 5 分钟。' }}</p><p v-else-if="resetting" class="auth-endnote">密码更新后，其他设备需要重新登录。</p><p v-else class="auth-endnote">验证码有效期 5 分钟，请勿向他人透露。</p>
      <p v-if="!props.admin" class="auth-switch"><template v-if="registration">已有账号？<RouterLink :to="{ path: '/login', query }">去登录<ArrowRight :size="14" /></RouterLink></template><template v-else-if="resetting"><RouterLink :to="{ path: state.user?.role === 'admin' ? '/admin' : state.user ? '/workspace' : '/login', query }">{{ state.user ? '返回工作空间' : '返回账号登录' }}<ArrowRight :size="14" /></RouterLink></template><template v-else>还没有账号？<RouterLink :to="{ path: '/register', query }">验证码注册<ArrowRight :size="14" /></RouterLink></template></p>
      <p v-if="props.admin && resetting" class="auth-switch"><RouterLink to="/admin/login">返回管理端登录<ArrowRight :size="14" /></RouterLink></p><p v-if="props.admin" class="auth-admin-context"><ShieldCheck :size="16" /><span>管理端与用户端分别登录，会话互不影响。<small>尚未获得权限？请联系平台维护者。</small></span></p><button v-if="needsCode && !options" class="text-link" @click="loadOptions">重新连接短信服务</button>
    </section></div><footer class="auth-footer"><span>同频 · 基于原文的双向理解</span><span>让选择有据可循</span></footer>
  </div>
</template>

<style scoped>
/* Login methods form one switch; the form below keeps a stable position. */
.auth-page .auth-card .auth-method {
  display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:4px;
  margin:0 0 26px;padding:5px;border:1px solid var(--border-soft);
  border-radius:11px;background:var(--surface-soft);
}
.auth-page .auth-card .auth-method>button {
  display:flex;align-items:center;justify-content:center;min-width:0;min-height:42px;
  padding:9px 12px;border:1px solid transparent;border-radius:7px;
  background:transparent;color:var(--text-muted);font-size:13px;font-weight:600;
  line-height:1.6;box-shadow:none;transform:none;
}
.auth-page .auth-card .auth-method>button.active:not(:disabled) {
  background:var(--brand);color:var(--brand-on);border-color:var(--brand);
  box-shadow:0 1px 3px var(--button-shadow);
}
.auth-page .auth-card .auth-method>button:not(.active):hover:not(:disabled) {
  background:var(--surface-paper);color:var(--brand-ink);border-color:var(--brand-edge);
}
.auth-page .auth-card .auth-method>button:focus-visible {
  outline:2px solid var(--brand-focus);outline-offset:2px;
}
.auth-page .auth-card .auth-method>button:disabled {
  background:var(--disabled-paper);color:var(--disabled-ink);
  border:1px dashed var(--disabled-edge);box-shadow:none;cursor:wait;
}
</style>
