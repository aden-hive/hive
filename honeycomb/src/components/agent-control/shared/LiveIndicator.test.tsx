import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { LiveIndicator } from './LiveIndicator'

describe('LiveIndicator', () => {
  it('renders "Live" text when isLive is true (default)', () => {
    render(<LiveIndicator />)

    expect(screen.getByText('Live')).toBeInTheDocument()
  })

  it('renders the pulsing indicator dot', () => {
    const { container } = render(<LiveIndicator />)

    const dot = container.querySelector('.bg-green-500')
    expect(dot).toBeInTheDocument()
  })

  it('returns null when isLive is false', () => {
    const { container } = render(<LiveIndicator isLive={false} />)

    expect(container.firstChild).toBeNull()
  })

  it('applies custom className', () => {
    const { container } = render(<LiveIndicator className="custom-class" />)

    const wrapper = container.firstChild as HTMLElement
    expect(wrapper).toHaveClass('custom-class')
  })
})
