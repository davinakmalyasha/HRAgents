import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ScoreBar } from './ScoreBar'

describe('ScoreBar', () => {
  it('exposes the score to assistive tech', () => {
    render(<ScoreBar value={0.82} label="Portfolio score" />)

    const bar = screen.getByRole('progressbar', { name: 'Portfolio score' })
    expect(bar).toHaveAttribute('aria-valuenow', '82')
    expect(screen.getByText('0.82')).toBeInTheDocument()
  })

  it('clamps out-of-range values', () => {
    render(<ScoreBar value={1.4} label="Clamped" />)
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100')
  })
})
