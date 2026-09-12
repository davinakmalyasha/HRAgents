// @vitest-environment node
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const SRC = fileURLToPath(new URL('..', import.meta.url))
const THEME_FILE = 'styles/theme.css'
const SCANNED = ['.ts', '.tsx', '.css']
const HEX = /#[0-9a-fA-F]{3,8}\b/

function sourceFiles(dir: string): string[] {
  const files: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      files.push(...sourceFiles(full))
      continue
    }
    if (SCANNED.some((extension) => entry.endsWith(extension))) {
      files.push(full)
    }
  }
  return files
}

describe('design token guard', () => {
  it('confines hex colors to the theme file', () => {
    const offenders: string[] = []

    for (const file of sourceFiles(SRC)) {
      const path = relative(SRC, file).split(sep).join('/')
      if (path === THEME_FILE || path.includes('.test.')) {
        continue
      }
      const lines = readFileSync(file, 'utf-8').split('\n')
      lines.forEach((line, index) => {
        if (HEX.test(line)) {
          offenders.push(`${path}:${index + 1}`)
        }
      })
    }

    expect(offenders).toEqual([])
  })
})
