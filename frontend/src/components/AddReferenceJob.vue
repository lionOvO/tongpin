<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { Plus, X } from '@lucide/vue'
import { api, state } from '../store'
import type { Job } from '../types'

const emit = defineEmits<{ close: []; added: [job: Job] }>()
const title = ref(''), jd = ref(''), pending = ref(false), error = ref('')
const valid = computed(() => title.value.trim().length >= 2 && jd.value.trim().length >= 20)
let alive = true
onUnmounted(() => { alive = false })
async function add() {
  if (!valid.value || pending.value || state.switching) return
  pending.value = true; error.value = ''
  const epoch = state.epoch
  try {
    const job = await api<Job>('/jobs/references', 'POST', { title: title.value.trim(), jd: jd.value.trim() })
    if (!alive || epoch !== state.epoch) return
    emit('added', job)
  } catch (e) {
    if (alive && epoch === state.epoch) error.value = e instanceof Error ? e.message : '未能添加岗位，请重试。'
  } finally { if (alive && epoch === state.epoch) pending.value = false }
}
</script>

<template>
  <div class="modal-backdrop" @click.self="!pending && emit('close')">
    <section v-dialog class="modal reference-job-dialog" role="dialog" aria-modal="true" aria-labelledby="reference-job-title" :aria-busy="pending">
      <header class="detail-heading"><div><p class="eyebrow">个人岗位参照</p><h2 id="reference-job-title">添加要了解的岗位</h2><p class="reference-job-intro">粘贴岗位描述，添加后即可与已有岗位一起分析。仅自己可见，不会发布或投递。</p></div><button class="icon-button" type="button" aria-label="关闭添加岗位窗口" :disabled="pending" @click="emit('close')"><X :size="18" /></button></header>
      <form @submit.prevent="add">
        <label for="reference-job-name">岗位名称<input id="reference-job-name" v-model="title" autofocus required minlength="2" maxlength="100" :disabled="pending" placeholder="例如：Python 后端工程师" /></label>
        <label for="reference-job-description">完整岗位描述<textarea id="reference-job-description" v-model="jd" required minlength="20" maxlength="30000" rows="8" :disabled="pending" placeholder="粘贴岗位职责、任职要求及技术要求，至少 20 字。" aria-describedby="reference-job-note" /></label>
        <p id="reference-job-note" class="reference-job-note">{{ jd.trim().length }} / 30000 字 · 保留原文，便于查看判断依据</p>
        <p v-if="error" class="feedback error" role="alert">{{ error }}</p>
        <p v-if="pending" class="reference-job-progress" role="status">正在整理岗位要求，请稍候…</p>
        <footer class="reference-job-footer"><button type="button" class="secondary" :disabled="pending" @click="emit('close')">取消</button><button class="primary" :disabled="!valid || pending || state.switching"><Plus :size="16" />{{ pending ? '正在添加…' : '添加并选中' }}</button></footer>
      </form>
    </section>
  </div>
</template>

<style scoped>
.reference-job-dialog{max-width:640px}.reference-job-dialog>.detail-heading{align-items:flex-start;gap:20px}.reference-job-dialog h2{font-size:22px;margin-top:6px}.reference-job-intro{margin:12px 0 0;font-size:13px;line-height:1.8;color:var(--text-muted);max-width:470px}.reference-job-dialog .icon-button{flex-shrink:0}.reference-job-dialog form{display:grid;gap:18px}.reference-job-dialog form>label{display:grid;gap:9px;margin:0;font-size:13px;font-weight:600}.reference-job-dialog textarea{resize:vertical;min-height:180px;line-height:1.8}.reference-job-note{margin:-8px 0 0;font-size:11px;color:var(--text-muted);line-height:1.8}.reference-job-footer{display:flex;justify-content:flex-end;gap:12px;padding-top:18px;border-top:1px solid var(--border-soft)}.reference-job-progress{color:var(--brand-ink);font-size:13px;margin:0}.reference-job-dialog .feedback{margin:0}
@media(max-width:520px){.reference-job-dialog h2{font-size:19px}.reference-job-footer>button{flex:1;justify-content:center}.reference-job-dialog textarea{min-height:160px}}
</style>
