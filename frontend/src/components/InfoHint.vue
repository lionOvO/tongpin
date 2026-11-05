<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, useId, watch } from 'vue'
import { Info } from '@lucide/vue'

defineProps<{ label: string; text: string }>()
const id = useId()
const trigger = ref<HTMLButtonElement | null>(null)
const tooltip = ref<HTMLElement | null>(null)
const hovered = ref(false)
const focused = ref(false)
const shown = computed(() => hovered.value || focused.value)
const position = ref({ left: '0px', top: '0px', visibility: 'hidden' as 'hidden' | 'visible' })

function hide() { hovered.value = false; focused.value = false }
watch(shown, async visible => {
  if (!visible) return
  position.value.visibility = 'hidden'
  await nextTick()
  if (!shown.value || !trigger.value || !tooltip.value) return
  const anchor = trigger.value.getBoundingClientRect()
  const box = tooltip.value.getBoundingClientRect()
  const width = document.documentElement.clientWidth
  const height = window.innerHeight
  const margin = 12
  const left = Math.max(margin, Math.min(anchor.right - box.width, width - box.width - margin))
  const above = anchor.top - box.height - 8
  const top = Math.max(margin, Math.min(above >= margin ? above : anchor.bottom + 8, height - box.height - margin))
  position.value = { left: `${left}px`, top: `${top}px`, visibility: 'visible' }
})
// Close rather than leaving a floating hint detached from its scrolled card.
onMounted(() => { window.addEventListener('scroll', hide, true); window.addEventListener('resize', hide) })
onUnmounted(() => { window.removeEventListener('scroll', hide, true); window.removeEventListener('resize', hide) })
</script>

<template>
  <button ref="trigger" class="info-hint-trigger" type="button" :aria-label="label" :aria-describedby="shown ? id : undefined" @pointerenter="hovered = true" @pointerleave="hovered = false" @focus="focused = true" @blur="focused = false" @keydown.esc="hide">
    <Info :size="14" />
  </button>
  <Teleport to="body">
    <div v-if="shown" :id="id" ref="tooltip" class="info-hint-popup" :style="position" role="tooltip">{{ text }}</div>
  </Teleport>
</template>

<style scoped>
.info-hint-trigger{display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;width:18px;height:24px;padding:0;border-radius:4px;line-height:1;color:var(--brand-ink);cursor:default}.info-hint-trigger>svg{display:block;margin:0}.info-hint-trigger:hover{background:var(--soft)}
.info-hint-popup{position:fixed;z-index:2000;width:240px;max-width:calc(100vw - 24px);max-height:calc(100dvh - 24px);padding:10px 12px;border:1px solid var(--brand-edge);border-radius:8px;background:#fff;box-shadow:0 4px 14px color-mix(in srgb, var(--text-main) 9.41%, transparent);font-size:12px;line-height:1.7;white-space:normal;overflow-wrap:anywhere;color:#423d34;pointer-events:none}
</style>
