/** One pinned canvas, five scenes, native page scrolling. No wheel interception. */
export const clamp = (value: number) => Math.max(0, Math.min(1, value))
export function ramp(value: number, start: number, end: number) {
  const t = clamp((value - start) / (end - start))
  return t * t * (3 - 2 * t)
}
const lengths = [1, 1.1, 1.5, 1.15, 1.2]
export function storyTimeline(viewport: number) {
  const unit = Math.max(800, Math.min(1000, viewport * .95))
  const spans = lengths.map(length => length * unit)
  const starts = spans.map((_, i) => spans.slice(0, i).reduce((sum, n) => sum + n, 0))
  return { spans, starts, total: spans.reduce((sum, n) => sum + n, 0) }
}
export function scenePose(local: number, last = false) {
  // The paper travels while the two sets of body copy take separate turns.
  const incoming = ramp(local, -.12, 0)
  const outgoing = last ? 0 : ramp(local, .66, .78)
  return { opacity: incoming * (1 - outgoing), y: (1 - incoming) * 80 - outgoing * 65,
    scale: 1 - (1 - incoming) * .12 - outgoing * .12, progress: clamp(local / .66) }
}
/** The closing screen inherits the conversation's position before filling the stage. */
export function closingPose(progress: number) {
  const t = clamp(progress)
  return { progress: t, collapse: ramp(t, 0, .42), outgoing: 1 - ramp(t, 0, .32),
    spread: ramp(t, .12, .76), background: ramp(t, .08, .3),
    kicker: ramp(t, .43, .64), title: ramp(t, .53, .78),
    actions: ramp(t, .67, .9), note: ramp(t, .78, 1) }
}
export interface PaperRect { x: number; y: number; width: number; height: number }
export function paperPose(from: PaperRect, to: PaperRect, progress: number) {
  const t = clamp(progress), travel = ramp(t, 0, 1), arc = Math.sin(Math.PI * t)
  const mix = (a: number, b: number, amount: number) => a + (b - a) * amount
  const middleWidth = Math.min(440, from.width * .72, to.width * .72)
  const middleHeight = Math.min(330, from.height * .72, to.height * .72)
  const size = (a: number, middle: number, b: number) => t < .5
    ? mix(a, middle, ramp(t, 0, .5)) : mix(middle, b, ramp(t, .5, 1))
  const width = size(from.width, middleWidth, to.width)
  const height = size(from.height, middleHeight, to.height)
  const cx = mix(from.x + from.width / 2, to.x + to.width / 2, travel) - arc * 74
  const cy = mix(from.y + from.height / 2, to.y + to.height / 2, travel) - arc * 48
  return { x: cx - width / 2, y: cy - height / 2, width, height, angle: arc === 0 ? 0 : -3 * arc,
    identity: ramp(t, .36, .44) * (1 - ramp(t, .58, .64)) }
}
export function mountStoryMotion(track: HTMLElement, sections: HTMLElement[], enabled: () => boolean,
  onProgress: (index: number, progress: number, active: number) => void) {
  let frame = 0, previousTime = 0, currentY = window.scrollY
  let top = 88, dirty = true, destroyed = false, fixed = false
  let timeline = storyTimeline(window.innerHeight)
  let introStart = -1, gather = 0, intro = true, previousTarget = window.scrollY
  let replayY = window.scrollY, returningHome = false
  let active = -1
  const selectors = ['.tp-hero-visual', '.tp-scene-figure', '.tp-edit-demo', '.tp-employer-card', '.tp-journey-demo']
  let panels: HTMLElement[] = []
  let boxes: PaperRect[] = []
  let bridge: HTMLElement | null = null
  const stage = track.querySelector<HTMLElement>('.tp-story-stage')!
  const closing = track.parentElement!.querySelector<HTMLElement>('.tp-final')!
  function retireStage(retired: boolean) {
    if (stage.inert === retired) return
    stage.inert = retired
    stage.toggleAttribute('data-retired', retired)
    if (retired) stage.setAttribute('aria-hidden', 'true')
    else stage.removeAttribute('aria-hidden')
  }
  const set = (el: HTMLElement, key: string, value: number) => {
    const next = value.toFixed(4)
    if (el.style.getPropertyValue(key) !== next) el.style.setProperty(key, next)
  }
  function tick(time: number) {
    frame = 0
    const targetY = window.scrollY
    const dt = previousTime ? Math.min(48, time - previousTime) : 16
    previousTime = time
    if (dirty) {
      top = track.getBoundingClientRect().top + targetY
      timeline = storyTimeline(window.innerHeight)
      // Measure only on mount, resize or replay. All animation-frame writes below
      // are transforms/opacity; no frame reads a box it has just transformed.
      const nextPanels = sections.map((section, i) => section.querySelector<HTMLElement>(selectors[i]!)!)
      panels.filter(panel => !nextPanels.includes(panel)).forEach(panel => observer.unobserve(panel))
      panels = nextPanels
      panels.forEach(panel => observer.observe(panel))
      bridge = track.querySelector<HTMLElement>('.tp-stage-bridge')
      const transforms = panels.map(panel => panel.style.transform)
      panels.forEach(panel => { panel.style.transform = 'none' })
      const stageRect = stage.getBoundingClientRect()
      boxes = panels.map(panel => { const r = panel.getBoundingClientRect()
        return { x: r.left - stageRect.left, y: r.top - stageRect.top, width: r.width, height: r.height } })
      panels.forEach((panel, i) => { panel.style.transform = transforms[i]! })
      dirty = false
    }
    if (fixed !== enabled()) {
      fixed = enabled(); active = -1
      sections.forEach(el => {
        el.inert = false; el.removeAttribute('aria-hidden')
        el.style.removeProperty('opacity'); el.style.removeProperty('transform'); el.style.removeProperty('visibility')
      })
      panels.forEach(panel => panel.style.removeProperty('transform'))
      retireStage(false)
      closing.inert = false; closing.removeAttribute('aria-hidden'); closing.removeAttribute('data-closing')
      track.style.height = fixed ? `${timeline.total}px` : ''
      currentY = targetY
    }
    if (!fixed) { previousTime = 0; return }
    track.style.height = `${timeline.total}px`
    // The final section stays in normal layout. Counter-translate it during the
    // reveal so both scenes share the same viewport, then hand off at identity.
    // No positioning-mode switch, duplicate CTA or extra viewport of dead scroll.
    const exit = Math.max(0, targetY - top + 88 - timeline.total)
    set(track, '--stage-exit', exit)
    if (Math.abs(targetY - currentY) > window.innerHeight * 1.8) currentY = targetY
    else currentY += (targetY - currentY) * (1 - Math.exp(-dt / 115))
    if (Math.abs(targetY - currentY) < .15) currentY = targetY
    const distance = Math.max(0, currentY - top + 88)
    const closingStart = timeline.starts[4]! + timeline.spans[4]! * .66
    const ending = closingPose(distance >= timeline.total - .5 ? 1 : (distance - closingStart) / (timeline.total - closingStart))
    const showClosing = ending.progress > 0
    closing.toggleAttribute('data-closing', showClosing)
    closing.inert = ending.actions < .98
    closing.setAttribute('aria-hidden', String(!showClosing))
    set(closing, '--closing-offset', Math.max(0, timeline.total - (targetY - top + 88)))
    for (const key of ['background', 'kicker', 'title', 'actions', 'note'] as const) set(closing, `--closing-${key}`, ending[key])
    const lastBox = boxes[4]!
    set(closing, '--closing-x', (lastBox.x + lastBox.width / 2 - window.innerWidth / 2) * (1 - ending.spread))
    set(closing, '--closing-y', (lastBox.y + lastBox.height / 2 - (window.innerHeight - 88) / 2) * (1 - ending.spread))
    set(closing, '--closing-scale-x', .18 + .82 * ending.spread)
    set(closing, '--closing-scale-y', .23 + .77 * ending.spread)
    set(closing, '--closing-radius', 72 * (1 - ending.spread))
    retireStage(ending.outgoing <= .001)
    const transfer = timeline.starts.findIndex((start, i) => i < sections.length - 1
      && distance >= start + timeline.spans[i]! * .66 && distance < timeline.starts[i + 1]!)
    const travel = transfer < 0 ? 0 : clamp((distance - timeline.starts[transfer]! - timeline.spans[transfer]! * .66) / (timeline.spans[transfer]! * .34))
    const paper = transfer < 0 ? undefined : paperPose(boxes[transfer]!, boxes[transfer + 1]!, travel)
    if (track.dataset.transfer !== String(transfer)) track.dataset.transfer = String(transfer)
    if (paper && bridge) {
      set(bridge, '--paper-x', paper.x); set(bridge, '--paper-y', paper.y)
      set(bridge, '--paper-sx', paper.width / 1000); set(bridge, '--paper-sy', paper.height / 700)
      set(bridge, '--identity-x', paper.x + paper.width / 2); set(bridge, '--identity-y', paper.y + paper.height / 2)
      set(bridge, '--paper-angle', paper.angle); set(bridge, '--identity-opacity', paper.identity)
    }
    let dominant = 0, maxOpacity = -1
    const poses = sections.map((_, i) => {
      const start = timeline.starts[i]!
      const previousSpan = timeline.spans[Math.max(0, i - 1)]!
      const local = distance < start && i > 0 ? (distance - start) / previousSpan : (distance - start) / timeline.spans[i]!
      const pose = scenePose(local, i === sections.length - 1)
      if (i === sections.length - 1) { pose.opacity *= ending.outgoing; pose.y -= ending.collapse * 40 }
      if (pose.opacity > maxOpacity) { dominant = i; maxOpacity = pose.opacity }
      return pose
    })
    if (maxOpacity < .001 && transfer >= 0) dominant = transfer + (travel >= .5 ? 1 : 0)
    if (ending.progress > 0) dominant = 4
    sections.forEach((section, index) => {
      const pose = poses[index]!
      section.style.opacity = pose.opacity.toFixed(4)
      set(section, '--copy-shift', pose.y)
      // FLIP both real panels onto the same travelling sheet. At each endpoint
      // its matrix is identity, so handing the sheet back causes no visual jump.
      if (paper && (index === transfer || index === transfer + 1)) {
        const box = boxes[index]!
        panels[index]!.style.transform = `translate3d(${(paper.x - box.x).toFixed(3)}px,${(paper.y - box.y).toFixed(3)}px,0) rotate(${paper.angle.toFixed(3)}deg) scale(${(paper.width / box.width).toFixed(5)},${(paper.height / box.height).toFixed(5)})`
      } else if (index === 4 && ending.progress > 0) {
        const box = boxes[4]!, shrink = ending.collapse * .18
        panels[index]!.style.transform = `translate3d(${box.width * shrink / 2}px,${-28 * ending.collapse}px,0) rotate(${-3 * ending.collapse}deg) scale(${1 - shrink})`
      } else panels[index]!.style.removeProperty('transform')
      section.style.visibility = pose.opacity > .001 ? 'visible' : 'hidden'
      if (active !== dominant) { section.inert = index !== dominant; section.setAttribute('aria-hidden', String(index !== dominant)) }
      set(section, '--scene-progress', pose.progress)
      if (index === 1) [0, 1, 2].forEach(i => set(section, `--link-${i}`, ramp(pose.progress, i * .28, i * .28 + .24)))
      if (index === dominant) onProgress(index, pose.progress, dominant)
    })
    active = dominant
    set(track, '--story-progress', clamp(distance / timeline.total))
    set(track, '--bridge-opacity', ending.progress > 0 ? 0 : 1 - poses.reduce((sum, pose) => sum + pose.opacity, 0))
    set(track, '--company-weight', transfer < 0 ? (dominant === 3 ? 1 : 0)
      : (transfer === 3 ? 1 - ramp(travel, 0, 1) : transfer + 1 === 3 ? ramp(travel, 0, 1) : 0))
    if (returningHome && Math.abs(targetY - Math.max(0, top - 88)) < 1) {
      returningHome = false; intro = true; introStart = -1; gather = 0; replayY = targetY
    } else if (!returningHome && targetY < previousTarget - .5) intro = false
    previousTarget = targetY
    if (introStart < 0) introStart = time
    const scrollGather = ramp(distance / timeline.spans[0]!, .02, .62)
    if (intro) gather = Math.max(targetY > replayY + .5 ? scrollGather : 0, ramp(time - introStart, 220, 2050))
    else gather += (scrollGather - gather) * (1 - Math.exp(-dt / 90))
    if (Math.abs(scrollGather - gather) < .001 && !intro) gather = scrollGather
    set(sections[0]!, '--gather', gather)
    const animatingIntro = intro && time - introStart < 2050
    if (currentY !== targetY || animatingIntro || (!intro && Math.abs(scrollGather - gather) > .001)) request()
    else previousTime = 0
  }
  function request() { if (!destroyed && !frame) frame = requestAnimationFrame(tick) }
  function resize() { dirty = true; request() }
  const observer = new ResizeObserver(resize); observer.observe(track)
  window.addEventListener('scroll', request, { passive: true }); window.addEventListener('resize', resize, { passive: true })
  document.fonts.ready.then(() => { if (!destroyed) resize() }); request()
  return {
    refresh: resize,
    jump(index: number) {
      returningHome = index === 0
      window.scrollTo({ top: Math.max(0, top - 88 + (index === 5 ? timeline.total : timeline.starts[index]!)), behavior: 'smooth' }); request()
    },
    replayHero() { intro = true; introStart = -1; gather = 0; replayY = window.scrollY; set(sections[0]!, '--gather', 0); resize() },
    destroy() { destroyed = true; cancelAnimationFrame(frame); observer.disconnect()
      window.removeEventListener('scroll', request); window.removeEventListener('resize', resize) },
  }
}
