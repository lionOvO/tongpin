<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { api, notifyError } from '../store'
import type { RecordData } from '../types'
const props = defineProps<{ modelValue: string }>()
const emit = defineEmits<{ 'update:modelValue': [id: string] }>()
const rows = ref<RecordData[]>([]); const query = ref(''); const offset = ref(0); const total = ref(0); const loading = ref(false)
let sequence = 0; let alive = true; let timer: ReturnType<typeof setTimeout> | undefined
async function load() {
  const ticket = ++sequence; loading.value = true
  try {
    const result = await api<{items:RecordData[];total:number}>(`/admin/governance/jobs?offset=${offset.value}&q=${encodeURIComponent(query.value)}`)
    if (!alive || ticket !== sequence) return
    rows.value = result.items; total.value = result.total
    if (!props.modelValue && rows.value.length) emit('update:modelValue',rows.value[0]!.id)
  } catch(e) { if (alive && ticket === sequence) notifyError(e) }
  finally { if (alive && ticket === sequence) loading.value = false }
}
watch(query, () => { sequence++; offset.value = 0; clearTimeout(timer); timer = setTimeout(load,250) })
function page(step:number) { offset.value = Math.max(0,offset.value + step * 50); void load() }
onMounted(load); onUnmounted(() => { alive = false; sequence++; clearTimeout(timer) })
</script>
<template>
  <div class="form-grid">
    <label>查找企业岗位<input v-model="query" type="search" maxlength="100" placeholder="按岗位名称搜索" /></label>
    <label>监管岗位<select :value="modelValue" :disabled="loading" @change="emit('update:modelValue',($event.target as HTMLSelectElement).value)"><option value="">请选择企业岗位</option><option v-if="modelValue && !rows.some(r => r.id === modelValue)" :value="modelValue">已选岗位 · {{ modelValue.slice(0,8) }}</option><option v-for="r in rows" :key="r.id" :value="r.id">{{ r.title }} · {{ r.status }} · {{ r.owner.slice(-8) }}</option></select></label>
  </div>
  <div v-if="total > 50" class="button-row"><button type="button" class="secondary" :disabled="loading || offset === 0" @click="page(-1)">上一页</button><small>{{ offset + 1 }}–{{ Math.min(offset + 50,total) }} / {{ total }}</small><button type="button" class="secondary" :disabled="loading || offset + 50 >= total" @click="page(1)">下一页</button></div>
</template>
