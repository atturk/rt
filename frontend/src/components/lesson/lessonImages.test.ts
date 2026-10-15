import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import type { Schemas } from '@/api/client'
import { lessonImageUploads } from './lessonImages'
import { timecodeLock } from './timecodeLock'
const markdown = '## 1. Sezione\n### 1.1 Unità\n00:00\nTesto.'
const image: Schemas['EditorImage'] = { path: 'assets/images/a.png', name: 'a.png', url: '/api/v1/lessons/1/assets/images/a.png', alt_text: 'Figura' }
function mount(upload: (file: File) => Promise<Schemas['EditorImage']>, readOnly = false, source = markdown) {
  const parent = document.createElement('div')
  document.body.append(parent)
  let task: Promise<void> | undefined
  const view = new EditorView({ parent, state: EditorState.create({ doc: source, extensions: [lessonImageUploads({ upload, started: (t) => { task = t; void t.catch(() => undefined) } }), timecodeLock, EditorState.readOnly.of(readOnly)] }) })
  view.dispatch({ selection: { anchor: source.length } })
  const send = (type: 'paste' | 'drop', files: File[]) => {
    const event = new Event(type, { bubbles: true, cancelable: true })
    Object.defineProperty(event, type === 'paste' ? 'clipboardData' : 'dataTransfer', { value: { files, getData: () => '' } })
    vi.spyOn(view, 'posAtCoords').mockReturnValue(markdown.indexOf('Testo'))
    view.contentDOM.dispatchEvent(event)
    return task
  }
  return { view, send, parent }
}
it('incolla PNG, JPEG e GIF come riferimenti relativi, in ordine', async () => {
  const upload = vi.fn().mockResolvedValue(image)
  const { view, send, parent } = mount(upload)
  await send('paste', ['image/png', 'image/jpeg', 'image/gif'].map((type) => new File(['img'], 'figura', { type })))
  expect(upload).toHaveBeenCalledTimes(3)
  expect(view.state.doc.toString().match(/assets\/images\/a.png/g)).toHaveLength(3)
  expect(view.state.doc.toString()).not.toContain('/api/v1/')
  expect(view.state.doc.toString()).not.toContain('data:image')
  view.destroy(); parent.remove()
})
it('incolla nel corpo quando il cursore è sul titolo e il timecode è l’ultima riga', async () => {
  const source = '### 1.1 Unità\n00:00'
  const { view, send, parent } = mount(async () => image, false, source)
  view.dispatch({ selection: { anchor: source.indexOf('Unità') } })
  await send('paste', [new File(['img'], 'figura.png', { type: 'image/png' })])
  expect(view.state.doc.toString()).toBe(`${source}\n\n![Figura](assets/images/a.png)\n\n`)
  view.destroy(); parent.remove()
})
it('mantiene la posizione del trascinamento mentre il testo cambia', async () => {
  let resolve!: (i: Schemas['EditorImage']) => void
  const { view, send, parent } = mount(() => new Promise((r) => { resolve = r }))
  const task = send('drop', [new File(['img'], 'figura.png', { type: 'image/png' })])
  view.dispatch({ changes: { from: markdown.indexOf('Testo'), insert: 'Nuovo ' } })
  resolve(image)
  await task
  expect(view.state.doc.toString()).toContain('Nuovo \n\n![Figura](assets/images/a.png)\n\nTesto.')
  view.destroy(); parent.remove()
})
it('rifiuta altri formati e il caricamento in sola lettura', () => {
  const upload = vi.fn().mockResolvedValue(image)
  for (const readOnly of [false, true]) {
    const { view, send, parent } = mount(upload, readOnly)
    send('paste', [new File(['img'], 'figura.webp', { type: 'image/webp' })])
    if (readOnly) send('paste', [new File(['img'], 'figura.png', { type: 'image/png' })])
    expect(view.state.doc.toString()).toBe(markdown)
    view.destroy(); parent.remove()
  }
  expect(upload).not.toHaveBeenCalled()
})
it('propaga gli errori senza inserire riferimenti e ignora un editor smontato', async () => {
  const failed = mount(async () => { throw new Error('Caricamento fallito') })
  await expect(failed.send('paste', [new File(['img'], 'a.png', { type: 'image/png' })])).rejects.toThrow('Caricamento fallito')
  expect(failed.view.state.doc.toString()).toBe(markdown)
  failed.view.destroy(); failed.parent.remove()
  let resolve!: (i: Schemas['EditorImage']) => void
  const unmounted = mount(() => new Promise((r) => { resolve = r }))
  const task = unmounted.send('paste', [new File(['img'], 'a.png', { type: 'image/png' })])
  unmounted.view.destroy(); unmounted.parent.remove()
  resolve(image)
  await task
  expect(unmounted.view.state.doc.toString()).toBe(markdown)
})

describe('MS1c: Inserisci al cursore e collegamento editor', () => {
  it('notifica lo stato del cursore quando l’editor è attivo o smontato', () => {
    const listener = vi.fn()
    window.addEventListener('rt-editor-cursor-state', listener)

    const { view, parent } = mount(async () => image)
    expect(listener).toHaveBeenCalledWith(
      expect.objectContaining({ detail: { hasCursor: true } }),
    )

    // Richiesta esplicita dello stato
    listener.mockClear()
    window.dispatchEvent(new CustomEvent('rt-editor-request-cursor-state'))
    expect(listener).toHaveBeenCalledWith(
      expect.objectContaining({ detail: { hasCursor: true } }),
    )

    // Allo smontaggio
    listener.mockClear()
    view.destroy()
    parent.remove()
    expect(listener).toHaveBeenCalledWith(
      expect.objectContaining({ detail: { hasCursor: false } }),
    )

    window.removeEventListener('rt-editor-cursor-state', listener)
  })

  it('inserisce al cursore più immagini come striscia (righe consecutive)', () => {
    const { view, parent } = mount(async () => image)
    const pos = markdown.indexOf('Testo.')
    view.dispatch({ selection: { anchor: pos } })

    window.dispatchEvent(
      new CustomEvent('rt-editor-insert-images', {
        detail: {
          items: [
            { path: 'assets/images/pag1.png', alt_text: 'Pagina 1' },
            { path: 'assets/images/pag2.png', alt_text: 'Pagina 2' },
          ],
        },
      }),
    )

    const doc = view.state.doc.toString()
    expect(doc).toContain(
      '\n\n![Pagina 1](assets/images/pag1.png)\n![Pagina 2](assets/images/pag2.png)\n\nTesto.',
    )
    view.destroy()
    parent.remove()
  })

  it('non inserisce sopra i titoli o timecode: sposta la posizione a fine riga / dopo il timecode', () => {
    const { view, parent } = mount(async () => image)
    // Cursore sul titolo ### 1.1 Unità
    const titlePos = markdown.indexOf('### 1.1') + 2
    view.dispatch({ selection: { anchor: titlePos } })

    window.dispatchEvent(
      new CustomEvent('rt-editor-insert-images', {
        detail: {
          items: [{ path: 'assets/images/pag1.png', alt_text: 'Pagina 1' }],
        },
      }),
    )

    const doc = view.state.doc.toString()
    // Il titolo e timecode restano intatti prima dell'immagine
    expect(doc).toContain('### 1.1 Unità\n00:00')
    expect(doc).toContain('![Pagina 1](assets/images/pag1.png)\n\nTesto.')
    view.destroy()
    parent.remove()
  })

  it('trascina una miniatura x-rt-media-image nel testo', () => {
    const { view, parent } = mount(async () => image)
    const at = markdown.indexOf('Testo.')
    vi.spyOn(view, 'posAtCoords').mockReturnValue(at)

    const event = new Event('drop', { bubbles: true, cancelable: true })
    const mediaItem = {
      path: 'assets/images/dropped.png',
      alt_text: 'Pagina trascinata',
      in_assets: true,
    }
    Object.defineProperty(event, 'dataTransfer', {
      value: {
        files: [],
        getData: (type: string) => (type === 'application/x-rt-media-image' ? JSON.stringify(mediaItem) : ''),
      },
    })

    view.contentDOM.dispatchEvent(event)
    expect(view.state.doc.toString()).toContain('![Pagina trascinata](assets/images/dropped.png)')
    view.destroy()
    parent.remove()
  })

  it('toglie dal testo le immagini selezionate mantenendo intatto il resto', () => {
    const docWithImages =
      '## 1. Sezione\n### 1.1 Unità\n00:00\n\n![Foto 1](assets/images/to_remove.png)\nTesto normale.'
    const { view, parent } = mount(async () => image, false, docWithImages)

    window.dispatchEvent(
      new CustomEvent('rt-editor-remove-images', {
        detail: { imageNames: ['to_remove.png'] },
      }),
    )

    const doc = view.state.doc.toString()
    expect(doc).not.toContain('to_remove.png')
    expect(doc).toContain('Testo normale.')
    view.destroy()
    parent.remove()
  })
})

