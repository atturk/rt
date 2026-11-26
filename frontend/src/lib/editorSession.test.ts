import { describe, expect, it, vi } from 'vitest'

import { registerEditorFlush, releaseEditor } from './editorSession'

describe('editorSession', () => {
  it('prima di un job della lezione salva la bozza e lascia il lease dell\'editor', async () => {
    const flush = vi.fn().mockResolvedValue(undefined)
    const unregister = registerEditorFlush(7, flush)
    await releaseEditor(7)
    await releaseEditor(8)
    expect(flush).toHaveBeenCalledTimes(1)
    unregister()
    await releaseEditor(7)
    expect(flush).toHaveBeenCalledTimes(1)
  })

  it('un editor smontato non toglie quello montato dopo', async () => {
    const first = vi.fn().mockResolvedValue(undefined)
    const second = vi.fn().mockResolvedValue(undefined)
    const unregisterFirst = registerEditorFlush(3, first)
    registerEditorFlush(3, second)
    unregisterFirst()
    await releaseEditor(3)
    expect(second).toHaveBeenCalledTimes(1)
    expect(first).not.toHaveBeenCalled()
  })
})
