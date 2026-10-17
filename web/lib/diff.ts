export type Part = { text: string; kind: 'same' | 'removed' | 'added' }

// Word-level diff by longest common subsequence. Articles are short, so O(n*m) is fine.
export function diffWords(before: string, after: string): { before: Part[]; after: Part[] } {
  const a = before.split(/(\s+)/).filter(Boolean)
  const b = after.split(/(\s+)/).filter(Boolean)
  const lcs: number[][] = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0))
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1])
    }
  }

  const left: Part[] = []
  const right: Part[] = []
  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      left.push({ text: a[i], kind: 'same' })
      right.push({ text: b[j], kind: 'same' })
      i++
      j++
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      left.push({ text: a[i++], kind: 'removed' })
    } else {
      right.push({ text: b[j++], kind: 'added' })
    }
  }
  while (i < a.length) left.push({ text: a[i++], kind: 'removed' })
  while (j < b.length) right.push({ text: b[j++], kind: 'added' })
  return { before: left, after: right }
}
