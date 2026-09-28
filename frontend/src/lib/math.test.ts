import { describe, expect, it } from 'vitest'

import { renderDelimitedMath } from './math'

describe('renderDelimitedMath', () => {
  it('renders only explicitly delimited math and preserves ordinary text', () => {
    const root = document.createElement('article')
    root.innerHTML = String.raw`<p>La formula \(x^2 + \frac{a}{b}\) è utile; 2 parole e a/b restano testo.</p>`
    renderDelimitedMath(root)
    expect(root.querySelectorAll('math')).toHaveLength(1)
    expect(root.querySelector('msup')).not.toBeNull()
    expect(root.querySelector('mfrac')).not.toBeNull()
    expect(root.textContent).toContain('è utile; 2 parole e a/b restano testo.')
  })

  it('ignores formulas inside inline and block code', () => {
    const root = document.createElement('article')
    root.innerHTML = String.raw`<p><code>\(x^2\)</code> <span>\[a+b\]</span></p><pre>$$c+d$$</pre>`
    renderDelimitedMath(root)
    console.log(root.innerHTML)
    expect(root.querySelectorAll('math')).toHaveLength(1)
    expect(root.querySelector('code')?.textContent).toBe('\\(x^2\\)')
    expect(root.querySelector('pre')?.textContent).toBe('$$c+d$$')
  })

  it('supports dollar display delimiters and common greek commands', () => {
    const root = document.createElement('article')
    root.textContent = '$$\\alpha_{1} = \\sqrt{4}$$'
    renderDelimitedMath(root)
    console.log(root.innerHTML)
    expect(root.querySelector('math')?.getAttribute('display')).toBe('block')
    expect(root.querySelector('mi')?.textContent).toBe('α')
    expect(root.querySelector('msqrt')).not.toBeNull()
  })
})
