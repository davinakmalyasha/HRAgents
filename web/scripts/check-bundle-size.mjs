#!/usr/bin/env node
/**
 * Bundle budget: gzip size of the built JS/CSS, with a hard ceiling.
 *
 * The build already code-splits by route; this keeps an accidental import of a
 * heavy dependency (or a route losing its split) from shipping silently. Gzip
 * is what the browser downloads, so that is the number measured.
 */
import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { gzipSync } from 'node:zlib'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ASSETS = fileURLToPath(new URL('../dist/assets/', import.meta.url))
const KB = 1024
const BUDGETS = {
  total: 400 * KB,
  entry: 180 * KB,
  css: 50 * KB,
}

if (!existsSync(ASSETS)) {
  console.error('bundle: dist/assets is missing; run `npm run build` first')
  process.exit(1)
}

const files = readdirSync(ASSETS).filter((name) => /\.(js|css)$/.test(name))
const sizes = files.map((name) => ({
  name,
  gzip: gzipSync(readFileSync(join(ASSETS, name))).length,
}))

const total = sizes.reduce((sum, file) => sum + file.gzip, 0)
const css = sizes
  .filter((file) => file.name.endsWith('.css'))
  .reduce((sum, file) => sum + file.gzip, 0)
const entry = sizes.find((file) => /^index-.*\.js$/.test(file.name))?.gzip ?? 0

const rows = [
  ['entry (index-*.js)', entry, BUDGETS.entry],
  ['css', css, BUDGETS.css],
  ['all js + css', total, BUDGETS.total],
]

let failed = false
for (const [label, value, budget] of rows) {
  const ok = value <= budget
  failed ||= !ok
  console.log(
    `${ok ? 'ok  ' : 'FAIL'} ${label.padEnd(20)} ${(value / KB).toFixed(1).padStart(7)} KB` +
      ` / ${(budget / KB).toFixed(0)} KB`,
  )
}

if (failed) {
  console.error('bundle: over budget; split the route or drop the dependency')
  process.exit(1)
}
