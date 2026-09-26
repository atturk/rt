import { describe, expect, it } from 'vitest'

import { withImageUrls } from './images'

describe('withImageUrls', () => {
  it('porta le immagini della lezione all\'endpoint dell\'API', () => {
    const html = '<p><img src="assets/images/a1b2c3d4e5f60718.png" alt="Slide 1" /></p>'
    expect(withImageUrls(html, 7)).toBe('<p><img src="/api/v1/lessons/7/assets/images/a1b2c3d4e5f60718.png" alt="Slide 1" /></p>')
  })
  it('lascia stare gli altri src e i link', () => {
    const html = '<img src="https://example.org/x.png"><a href="assets/images/x.png">x</a>'
    expect(withImageUrls(html, 7)).toBe(html)
  })
})
