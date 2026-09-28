import { describe, expect, it } from 'vitest'

import { renderDelimitedMath } from './math'

describe('renderDelimitedMath', async () => {
  it('renders only explicitly delimited math and preserves ordinary text', async () => {
    const root = document.createElement('article')
    root.innerHTML = String.raw`<p>La formula \(x^2 + \frac{a}{b}\) è utile; 2 parole e a/b restano testo.</p>`
    await renderDelimitedMath(root)
    expect(root.querySelectorAll('math')).toHaveLength(1)
    expect(root.querySelector('msup')).not.toBeNull()
    expect(root.querySelector('mfrac')).not.toBeNull()
    expect(root.textContent).toContain('è utile; 2 parole e a/b restano testo.')
  })

  it('ignores formulas inside inline and block code', async () => {
    const root = document.createElement('article')
    root.innerHTML = String.raw`<p><code>\(x^2\)</code> <span>\[a+b\]</span></p><pre>$$c+d$$</pre>`
    await renderDelimitedMath(root)
    expect(root.querySelectorAll('math')).toHaveLength(1)
    expect(root.querySelector('code')?.textContent).toBe('\\(x^2\\)')
    expect(root.querySelector('pre')?.textContent).toBe('$$c+d$$')
  })

  it('supports dollar display delimiters and common greek commands', async () => {
    const root = document.createElement('article')
    root.textContent = '$$\\alpha_{1} = \\sqrt{4}$$'
    await renderDelimitedMath(root)
    expect(root.querySelector('math')?.getAttribute('display')).toBe('block')
    expect(root.querySelector('mi')?.textContent).toBe('α')
    expect(root.querySelector('msqrt')).not.toBeNull()
  })

  it('leaves prices and lone dollars as text', async () => {
    const root = document.createElement('article')
    root.textContent = 'Costa 5$ e 10$, oppure da $5 a $10; la formula $x_1$ sì.'
    await renderDelimitedMath(root)
    expect(root.querySelectorAll('math')).toHaveLength(1)
    expect(root.textContent).toContain('Costa 5$ e 10$, oppure da $5 a $10; la formula ')
  })

  it('renders environments the old parser did not know, and shows invalid TeX without throwing', async () => {
    const root = document.createElement('article')
    root.textContent = String.raw`$$\begin{pmatrix} a & b \\ c & d \end{pmatrix}$$ e \(\frac{1}{\)`
    await renderDelimitedMath(root)
    expect(root.querySelector('math[display=block] mtable')).not.toBeNull()
    expect(root.querySelectorAll('math')).toHaveLength(1)
    expect(root.textContent).toContain(String.raw`\(\frac{1}{\)`)
  })
})
