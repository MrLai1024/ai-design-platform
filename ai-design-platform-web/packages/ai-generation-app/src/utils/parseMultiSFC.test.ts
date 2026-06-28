// src/utils/parseMultiSFC.test.ts
import { describe, it, expect } from 'vitest'
import { parseMultiSFC, parseSingleCodeBlock } from './parseMultiSFC'

describe('parseMultiSFC', () => {
  it('parses multi-file with ## heading markers', () => {
    const input = `
## App.vue
\`\`\`vue
<template>
  <div>Hello</div>
</template>
\`\`\`

## UserList.vue
\`\`\`vue
<template>
  <ul><li v-for="u in users">{{ u }}</li></ul>
</template>
\`\`\`
`
    const result = parseMultiSFC(input)
    expect(result).toHaveLength(2)
    expect(result[0]!.filename).toBe('App.vue')
    expect(result[0]!.code).toContain('<div>Hello</div>')
    expect(result[1]!.filename).toBe('UserList.vue')
    expect(result[1]!.code).toContain('v-for')
  })

  it('returns empty array when no headings found', () => {
    const input = 'Just some text without headings'
    expect(parseMultiSFC(input)).toEqual([])
  })

  it('handles headings without code fences gracefully', () => {
    const input = '## App.vue\nNo code block here'
    expect(parseMultiSFC(input)).toEqual([])
  })

  it('handles incomplete streaming content', () => {
    const input = '## App.vue\n```vue\n<template>\n  <div>Incomplete'
    const result = parseMultiSFC(input)
    expect(result).toHaveLength(0) // no closing fence yet
  })
})

describe('parseSingleCodeBlock', () => {
  it('extracts the first vue code block when no headings present', () => {
    const input = 'Here is some code:\n```vue\n<template><div>Hi</div></template>\n```'
    const result = parseSingleCodeBlock(input)
    expect(result).not.toBeNull()
    expect(result!.filename).toBe('App.vue')
    expect(result!.code).toContain('<div>Hi</div>')
  })

  it('returns null when no code block found', () => {
    expect(parseSingleCodeBlock('No code here')).toBeNull()
  })
})
