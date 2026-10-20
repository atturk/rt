import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import type { Schemas } from '@/api/client'
import { dropTarget, lessonImageUploads, removeImagesFromDocument, replaceImageInDocument } from './lessonImages'
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

  it('sostituisce un’immagine nel documento con il ritaglio mantenendo la posizione', () => {
    const docWithImage =
      '## 1. Sezione\n### 1.1 Unità\n00:00\n\n![Foto Originale](assets/images/orig.png)\nTesto normale.'
    const { view, parent } = mount(async () => image, false, docWithImage)

    window.dispatchEvent(
      new CustomEvent('rt-editor-replace-image', {
        detail: {
          originalName: 'orig.png',
          newName: 'crop123.png',
          newAltText: 'Foto Ritagliata',
        },
      }),
    )

    const doc = view.state.doc.toString()
    expect(doc).not.toContain('orig.png')
    expect(doc).toContain('![Foto Ritagliata](assets/images/crop123.png)')
    expect(doc).toContain('Testo normale.')
    view.destroy()
    parent.remove()
  })
})

describe('dropTarget (Piano 9)', () => {
  it('con "Sotto il titolo": puntatore a metà paragrafo di 2.2 va dopo titolo, timecode e immagini già lì', () => {
    const text = [
      '## 1. Macro 1',
      '### 1.1 Sub 1',
      '00:01',
      'Testo 1.',
      '',
      '## 2. Macro 2',
      '### 2.2 Metaboliti',
      '05:30',
      '![già](assets/images/vecchia.png)',
      'Primo paragrafo di 2.2 riga 1',
      'Secondo rigo del paragrafo.',
    ].join('\n')

    const state = EditorState.create({ doc: text })
    const pos = text.indexOf('Primo paragrafo') + 8
    const target = dropTarget(state, pos, 'heading')

    expect(target.insertAt).toBe(text.indexOf('Primo paragrafo'))
    expect(target.label).toBe('Sotto «2.2 Metaboliti»')
    expect(target.headingLine).toBe(7)
  })

  it('con "Sotto il titolo": puntatore su una macro senza sottounità va sotto la macro', () => {
    const text = [
      '## 1. Sezione con sub',
      '### 1.1 Unità 1',
      '01:00',
      'Testo.',
      '',
      '## 2. Macro senza sottounità',
      'Testo della macro.',
    ].join('\n')

    const state = EditorState.create({ doc: text })
    const pos = text.indexOf('Testo della macro')
    const target = dropTarget(state, pos, 'heading')

    expect(target.insertAt).toBe(text.indexOf('Testo della macro'))
    expect(target.label).toBe('Sotto «2. Macro senza sottounità»')
    expect(target.headingLine).toBe(6)
  })

  it('con "Dove le lascio": inizio del blocco, mai dentro un titolo', () => {
    const text = [
      '### 2.2 Metaboliti',
      '05:30',
      '',
      'Primo paragrafo riga 1',
      'primo paragrafo riga 2',
      '',
      'Secondo paragrafo.',
    ].join('\n')

    const state = EditorState.create({ doc: text })

    // Puntatore a metà della seconda riga del primo paragrafo
    const posInPara = text.indexOf('primo paragrafo riga 2') + 5
    const targetPara = dropTarget(state, posInPara, 'free')
    expect(targetPara.insertAt).toBe(text.indexOf('Primo paragrafo riga 1'))
    expect(targetPara.label).toBeUndefined()

    // Puntatore sul titolo ### 2.2 Metaboliti: non va dentro il titolo, va dopo titolo e timecode
    const posInTitle = 5
    const targetTitle = dropTarget(state, posInTitle, 'free')
    expect(targetTitle.insertAt).toBe(state.doc.line(3).from)
    expect(targetTitle.label).toBeUndefined()
  })

  it('#w=320 viene riconosciuto da removeImagesFromDocument e replaceImageInDocument', () => {
    const source = [
      '### 1.1 Unità',
      '00:00',
      '',
      '![Foto](assets/images/pic.png#w=320)',
      '',
      'Testo.',
    ].join('\n')

    const view = new EditorView({ state: EditorState.create({ doc: source }) })

    // replace preserva il frammento di larghezza
    const replaced = replaceImageInDocument(view, 'pic.png', 'cropped.png', 'Nuovo Alt')
    expect(replaced).toBe(true)
    expect(view.state.doc.toString()).toContain('![Nuovo Alt](assets/images/cropped.png#w=320)')
    expect(view.state.doc.toString()).not.toContain('pic.png')

    // remove riconosce l'immagine anche con #w=320
    const removed = removeImagesFromDocument(view, ['cropped.png'])
    expect(removed).toBe(true)
    expect(view.state.doc.toString()).not.toContain('cropped.png')
    expect(view.state.doc.toString()).toContain('Testo.')
  })
})

