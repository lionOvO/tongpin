import { describe, expect, it } from 'vitest'
import { closingPose, paperPose, ramp, scenePose, storyTimeline } from './public-motion'
describe('fixed public story', () => {
  it('keeps five readable holds and reaches the last scene on every desktop', () => {
    for (const h of [740,800,1000,1440]) {
      const timeline=storyTimeline(h)
      expect(timeline.starts[0]).toBe(0)
      expect(timeline.starts[4]!+timeline.spans[4]!).toBeCloseTo(timeline.total)
      expect(timeline.spans[2]).toBeGreaterThan(timeline.spans[0]!)
    }
    expect(scenePose(.5)).toMatchObject({opacity:1,y:0,scale:1})
    expect(scenePose(1,true).opacity).toBe(1)
  })
  it('hands off through the shared paper without superimposed body copy', () => {
    let previous=scenePose(.66).opacity
    for(let i=0;i<=340;i++) {
      const local=.66+i/1000
      const outgoing=scenePose(local), incoming=scenePose(local-1)
      expect(outgoing.opacity+incoming.opacity).toBeLessThanOrEqual(1.00001)
      expect(Math.min(outgoing.opacity,incoming.opacity)).toBe(0)
      expect(Math.abs(previous-outgoing.opacity)).toBeLessThan(.013)
      previous=outgoing.opacity
    }
    const forward=[.76,.8,.88,.96,1].map(n=>scenePose(n))
    const reverse=[1,.96,.88,.8,.76].map(n=>scenePose(n))
    expect(reverse).toEqual(forward.reverse())
  })
  it('carries the same paper through different panel sizes and back exactly', () => {
    const from={x:800,y:90,width:450,height:500}, to={x:540,y:45,width:820,height:580}
    expect(paperPose(from,to,0)).toMatchObject({...from,angle:0,identity:0})
    for(const key of ['x','y','width','height'] as const) expect(paperPose(from,to,1)[key]).toBeCloseTo(to[key])
    const middle=paperPose(from,to,.5)
    expect(middle.width).toBeLessThan(from.width)
    expect(middle.height).toBeLessThan(from.height)
    expect(middle.angle).toBe(-3);expect(middle.identity).toBe(1)
    const forward=[0,.2,.5,.8,1].map(t=>paperPose(from,to,t))
    expect([1,.8,.5,.2,0].map(t=>paperPose(from,to,t))).toEqual(forward.reverse())
    // Even equal-size chapter windows visibly fold and travel between scenes.
    expect(paperPose(to,to,.5).x).not.toBe(to.x)
    expect(paperPose(to,to,.5).width).toBeLessThan(to.width*.6)
  })
  it('clamps intermediate illustrations outside their timeline', () => {
    expect(ramp(-1,0,1)).toBe(0); expect(ramp(2,0,1)).toBe(1)
    expect(scenePose(-1).opacity).toBe(0);expect(scenePose(2).opacity).toBe(0)
    expect(scenePose(.76).progress).toBe(1)
  })
  it('reveals the closing actions after the conversation has left, in either direction', () => {
    expect(closingPose(-1)).toMatchObject({outgoing:1,spread:0,title:0,actions:0})
    expect(closingPose(2)).toMatchObject({outgoing:0,spread:1,title:1,actions:1,note:1})
    for (let i=0;i<=100;i++) {
      const pose=closingPose(i/100)
      if (pose.title>0) expect(pose.outgoing).toBe(0)
      if (pose.actions>0) expect(pose.title).toBeGreaterThan(0)
    }
    const samples=[0,.2,.4,.6,.8,1]
    expect([...samples].reverse().map(closingPose)).toEqual(samples.map(closingPose).reverse())
  })
})
