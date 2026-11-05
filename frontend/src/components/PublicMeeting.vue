<script setup lang="ts">
import doors from '../assets/tongpin-mutual-doors.webp'
import smallDoors from '../assets/tongpin-mutual-doors-small.webp'
import { ArrowRight, BriefcaseBusiness, UserRound } from '@lucide/vue'
</script>

<template>
  <figure class="tp-meeting">
    <div class="tp-meeting-heading"><span>从各自的期待，走向共同的可能</span><span class="tp-meeting-mark" aria-hidden="true">↔</span></div>
    <div class="tp-meeting-picture">
      <img class="tp-meeting-left" :src="doors" :srcset="`${smallDoors} 960w, ${doors} 1672w`" sizes="(max-width: 1000px) 92vw, 55vw" width="1672" height="941" fetchpriority="high" alt="求职者与招聘者分别打开自己的门，在同一高度走向彼此，两条路径在中央交汇。">
      <img class="tp-meeting-right" :src="doors" :srcset="`${smallDoors} 960w, ${doors} 1672w`" sizes="(max-width: 1000px) 92vw, 55vw" width="1672" height="941" alt="" aria-hidden="true">
      <svg class="tp-meeting-resonance" viewBox="0 0 800 450" fill="none" aria-hidden="true">
        <path class="tp-resonance-left" pathLength="1" d="M190 312 C280 348 335 370 400 368" />
        <path class="tp-resonance-right" pathLength="1" d="M610 312 C520 348 465 370 400 368" />
        <circle cx="400" cy="368" r="7" />
      </svg>
    </div>
    <figcaption class="tp-meeting-roles">
      <div><span class="tp-meeting-icon"><UserRound :size="17" /></span><span><strong>我带来经历与期待</strong><small>展示所长，自主选择岗位</small></span></div>
      <span class="tp-meeting-between" aria-hidden="true">↔</span>
      <div><span class="tp-meeting-icon"><BriefcaseBusiness :size="17" /></span><span><strong>我带来岗位与诚意</strong><small>说清需要，认真了解每个人</small></span></div>
    </figcaption>
    <p class="tp-meeting-principle">每段经历都值得被看见<span aria-hidden="true">·</span>每次选择都由双方决定<ArrowRight :size="14" aria-hidden="true" /></p>
  </figure>
</template>
