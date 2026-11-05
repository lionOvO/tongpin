<script setup lang="ts">
import { state } from '../store'
defineProps<{ footer?: boolean }>()
</script>
<template><p v-if="state.presentation" :class="['notice', { 'notice-footer': footer }]" role="note"><span aria-hidden="true">i</span>{{ footer ? state.presentation.footer : state.presentation.bias_notice }}</p></template>
