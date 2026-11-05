<script setup lang="ts">defineProps<{ title: string; text: string; to?: string; label?: string }>()</script>
<template><div class="empty"><span class="empty-symbol" aria-hidden="true">↔</span><h3>{{ title }}</h3><p>{{ text }}</p><RouterLink v-if="to" :to="to" class="button primary">{{ label || '开始准备' }} <span>↗</span></RouterLink><slot /></div></template>
