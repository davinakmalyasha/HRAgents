import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import i18n from '@/i18n'

import { StatusBadge, type StatusTone } from './StatusBadge'

const TONES: Array<[StatusTone, string]> = [
  ['waiting', '▲'],
  ['error', '●'],
  ['done', '✓'],
]

describe('StatusBadge', () => {
  it.each(TONES)('renders the %s tone with icon and label', (tone, icon) => {
    render(<StatusBadge tone={tone} labelKey={`status.${tone}`} />)

    const badge = screen.getByRole('status')
    expect(badge).toHaveTextContent(icon)
    expect(badge).toHaveTextContent(i18n.t(`status.${tone}`))
  })

  it('never drops the icon when the label is present', () => {
    render(<StatusBadge tone="waiting" labelKey="status.waiting" />)
    expect(screen.getByRole('status').textContent).toMatch(/▲/)
  })
})
