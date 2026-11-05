<script setup lang="ts">
import { computed, ref } from 'vue'
import { paragraphDiff } from '../resume-diff'
const props = defineProps<{ before: string; modelValue: string; selected: boolean; index: number; pending: boolean; disabled: boolean; supplement: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: string]; 'update:selected': [value: boolean] }>()
const editing = ref(false)
const diff = computed(() => paragraphDiff(props.before, props.modelValue))
</script>
<template>
  <div class="ai-revision" :class="{ 'not-selected': pending && !selected }">
    <header><label v-if="pending" class="ai-revision-choice"><input type="checkbox" :checked="selected" :disabled="disabled" @change="emit('update:selected', ($event.target as HTMLInputElement).checked)">采纳这段修改</label><strong v-else>已采纳的修改</strong><button v-if="pending" type="button" class="secondary" :disabled="disabled" @click="editing = !editing">{{ editing ? '完成调整' : '手动调整' }}</button></header>
    <div class="ai-revision-columns">
      <section class="ai-before"><small>修改前</small><p>{{ diff.prefix }}<del v-if="diff.removed">{{ diff.removed }}</del>{{ diff.suffix }}</p></section>
      <section class="ai-after"><small>{{ supplement ? '修改后 · 新增本人补充' : '修改后' }}</small><p>{{ diff.prefix }}<ins v-if="diff.added">{{ diff.added }}</ins>{{ diff.suffix }}</p></section>
    </div>
    <label v-if="pending && editing" class="ai-revision-editor">建议内容 {{ index + 1 }}<textarea :value="modelValue" maxlength="2500" rows="5" :disabled="disabled" @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)" /></label>
    <small class="ai-diff-legend">删除线表示移除，绿色下划线表示新增；未采纳的段落保持原样。</small>
  </div>
</template>
