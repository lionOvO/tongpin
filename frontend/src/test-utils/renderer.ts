import { createRenderer } from 'vue'

// Exercise the rendered Vue page without a browser or an additional DOM dependency.
export interface HostNode {
  tag: string; tagName: string; text: string; props: Record<string, any>
  parent: HostNode | null; children: HostNode[]; addEventListener: () => void; getRootNode: () => { activeElement: null }
  readonly options: HostNode[]
}
export function node(tag: string, text = ''): HostNode {
  return { tag, tagName: tag.toUpperCase(), text, props: {}, parent: null, children: [], get options() { return all(this, 'option') }, addEventListener() {}, getRootNode: () => ({ activeElement: null }) }
}
export const renderer = createRenderer<HostNode, HostNode>({
  createElement: tag => node(tag), createText: text => node('#text', text), createComment: text => node('#comment', text),
  setText: (el, text) => { el.text = text },
  setElementText: (el, text) => { el.text = text; el.children = [] },
  patchProp: (el, key, _old, value) => { el.props[key] = value },
  insert(el, parent, anchor) {
    if (el.parent) el.parent.children.splice(el.parent.children.indexOf(el), 1)
    el.parent = parent
    const index = anchor ? parent.children.indexOf(anchor) : -1
    if (index < 0) parent.children.push(el); else parent.children.splice(index, 0, el)
  },
  remove(el) { if (el.parent) el.parent.children.splice(el.parent.children.indexOf(el), 1); el.parent = null },
  parentNode: el => el.parent,
  nextSibling: el => el.parent?.children[el.parent.children.indexOf(el) + 1] || null,
})
export const textOf = (el: HostNode): string => el.tag === '#comment' ? '' : el.text + el.children.map(textOf).join('')
export function all(el: HostNode, tag: string): HostNode[] {
  return [...(el.tag === tag ? [el] : []), ...el.children.flatMap(child => all(child, tag))]
}
