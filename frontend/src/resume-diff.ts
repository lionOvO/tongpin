// Keep unchanged context readable; highlight the changed range without quadratic diff work.
export function paragraphDiff(before: string, after: string) {
  const left = Array.from(before), right = Array.from(after)
  let start = 0, end = 0
  while (start < left.length && start < right.length && left[start] === right[start]) start++
  while (end < left.length - start && end < right.length - start && left[left.length - end - 1] === right[right.length - end - 1]) end++
  return { prefix: left.slice(0, start).join(''), removed: left.slice(start, left.length - end).join(''),
    added: right.slice(start, right.length - end).join(''), suffix: end ? left.slice(-end).join('') : '' }
}
