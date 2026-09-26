import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import { CountInput } from './CountInput'

function Field({ initial = '0' }: { initial?: string }) {
  const [value, setValue] = useState(initial)
  return (
    <>
      <label htmlFor="n">Immagini per unità</label>
      <CountInput id="n" value={value} onChange={setValue} />
    </>
  )
}

describe('CountInput', () => {
  it('si può cancellare lo 0 e scrivere un altro numero', async () => {
    const user = userEvent.setup()
    render(<Field />)
    const input = screen.getByLabelText('Immagini per unità')
    await user.clear(input)
    expect(input).toHaveValue('')
    await user.type(input, '3')
    expect(input).toHaveValue('3')
  })

  it('scrivere dopo lo 0 non produce "03"', async () => {
    const user = userEvent.setup()
    render(<Field />)
    const input = screen.getByLabelText('Immagini per unità')
    await user.type(input, '3')
    expect(input).toHaveValue('3')
    await user.type(input, '{Backspace}{Backspace}')
    expect(input).toHaveValue('')
    await user.type(input, '12')
    expect(input).toHaveValue('12')
  })

  it('la tastiera è numerica', () => {
    render(<Field />)
    expect(screen.getByLabelText('Immagini per unità')).toHaveAttribute('inputmode', 'numeric')
  })
})
