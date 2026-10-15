// @vitest-environment node
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const THEME = fileURLToPath(new URL('./theme.css', import.meta.url))

function block(selector: string): Record<string, string> {
  const css = readFileSync(THEME, 'utf-8')
  const match = new RegExp(`${selector}\\s*\\{([^}]*)\\}`).exec(css)
  if (!match) throw new Error(`missing ${selector} block`)
  const tokens: Record<string, string> = {}
  for (const line of match[1].split('\n')) {
    const token = /(--[\w-]+):\s*(#[0-9a-fA-F]{6})\s*;/.exec(line)
    if (token) tokens[token[1]] = token[2]
  }
  return tokens
}

function luminance(hex: string): number {
  const channels = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
  const [r, g, b] = channels.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function ratio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

const AA_TEXT = 4.5
const AA_NON_TEXT = 3

describe('token contrast (WCAG 2.1 AA)', () => {
  it.each([
    ['light', ':root'],
    ['dark', '.dark'],
  ])('%s text tokens clear 4.5:1 on both surfaces', (_mode, selector) => {
    const tokens = block(selector)
    for (const text of ['--text-muted', '--text', '--text-strong']) {
      for (const surface of ['--bg', '--bg-subtle']) {
        expect(ratio(tokens[text], tokens[surface])).toBeGreaterThanOrEqual(AA_TEXT)
      }
    }
  })

  it.each([
    ['light', ':root'],
    ['dark', '.dark'],
  ])('%s status tones clear 3:1 as icon glyphs on both surfaces', (_mode, selector) => {
    const tokens = block(selector)
    for (const tone of ['--waiting', '--error', '--done']) {
      for (const surface of ['--bg', '--bg-subtle']) {
        expect(ratio(tokens[tone], tokens[surface])).toBeGreaterThanOrEqual(AA_NON_TEXT)
      }
    }
  })
})
