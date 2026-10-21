import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import type { Schemas } from '@/api/client'
import { history, undo } from '@codemirror/commands'
import { RT_SECTION_IMAGE_DRAG_TYPE } from './imageSections'
import { lessonImageStrips } from './lessonImageStrips'
import { dropTarget, sectionDropTarget, moveDocumentImage, lessonImageUploads, removeImagesFromDocument, replaceImageInDocument } from './lessonImages'
import { timecodeLock } from './timecodeLock'
const markdown = '## 1. Sezione\n### 1.1 Unità\n00:00\nTesto.'
const image: Schemas['EditorImage'] = { path: 'assets/images/a.png', name: 'a.png', url: '/api/v1/lessons/1/assets/images/a.png', alt_text: 'Figura' }
function mount(upload: (file: File) => Promise<Schemas['EditorImage']>, readOnly = false, source = markdown) {
  const parent = document.createElement('div')
  document.body.append(parent)
  let task: Promise<void> | undefined
  const view = new EditorView({ parent, state: EditorState.create({ doc: source, extensions: [history(), lessonImageStrips(1), lessonImageUploads({ upload, started: (t) => { task = t; void t.catch(() => undefined) } }), timecodeLock, EditorState.readOnly.of(readOnly)] }) })
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
  expect(view.state.doc.toString()).toBe(`${source}\n\n![Figura](assets/images/a.png#w=480)\n\n`)
  view.destroy(); parent.remove()
})
it('mantiene la posizione del trascinamento mentre il testo cambia', async () => {
  let resolve!: (i: Schemas['EditorImage']) => void
  const { view, send, parent } = mount(() => new Promise((r) => { resolve = r }))
  const task = send('drop', [new File(['img'], 'figura.png', { type: 'image/png' })])
  view.dispatch({ changes: { from: markdown.indexOf('Testo'), insert: 'Nuovo ' } })
  resolve(image)
  await task
  expect(view.state.doc.toString()).toContain('Nuovo \n\n![Figura](assets/images/a.png#w=480)\n\nTesto.')
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

  it('inserisce al cursore più immagini nel testo con larghezza', () => {
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
      '\n\n![Pagina 1](assets/images/pag1.png#w=480)\n![Pagina 2](assets/images/pag2.png#w=480)\n\nTesto.',
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
    expect(doc).toMatch(/!\[Pagina 1\]\(assets\/images\/pag1.png#w=480\)\n+Testo\./)
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
    expect(view.state.doc.toString()).toContain('![Pagina trascinata](assets/images/dropped.png#w=480)')
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
  it('nel testo inserisce all’inizio del paragrafo dopo la sezione', () => {
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
    const target = dropTarget(state, pos)

    expect(target.insertAt).toBe(text.indexOf('Primo paragrafo'))
    expect(target.label).toBeUndefined()
  })

  it('in una macro senza sottounità rispetta il punto del testo', () => {
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
    const target = dropTarget(state, pos)

    expect(target.insertAt).toBe(text.indexOf('Testo della macro'))
    expect(target.label).toBeUndefined()
  })

  it('inizio del blocco, mai dentro un titolo o una sezione', () => {
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
    const targetPara = dropTarget(state, posInPara)
    expect(targetPara.insertAt).toBe(text.indexOf('Primo paragrafo riga 1'))
    expect(targetPara.label).toBeUndefined()

    // Puntatore sul titolo ### 2.2 Metaboliti: non va dentro il titolo, va dopo titolo e timecode
    const posInTitle = 5
    const targetTitle = dropTarget(state, posInTitle)
    expect(targetTitle.insertAt).toBe(state.doc.line(2).to)
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


it('rilascio sul bottone aggiunge alla sezione corretta senza larghezza', async () => {
  const source = markdown + '\n\n### 1.2 Altra\n00:30\nTesto secondo'
  const { view, parent } = mount(async () => image, false, source)
  const button = parent.querySelector('[data-unit-images="1.2"]')!
  const event = new Event('drop', { bubbles: true, cancelable: true })
  Object.defineProperty(event, 'dataTransfer', { value: { files: [], getData: (type: string) => type === 'application/x-rt-media-image' ? JSON.stringify({ path: 'assets/images/b.png', alt_text: 'B', in_assets: true }) : '' } })
  button.dispatchEvent(event)
  expect(view.state.doc.toString()).toContain('00:30\n\n![B](assets/images/b.png)')
  expect(view.state.doc.toString()).not.toContain('#w=')
  view.destroy(); parent.remove()
})
it.each(['section', 'text', 'reorder'] as const)('spostamento %s senza duplicati e con un solo annulla', destination => {
  const source = '### 1.1 Prima\n00:00\n![A](assets/images/a.png)\n![B](assets/images/b.png)\nTesto primo\n\n### 1.2 Seconda\n00:30\nTesto secondo'
  const { view, parent } = mount(async () => image, false, source)
  const target = destination === 'section' ? sectionDropTarget(view.state, '1.2')! : destination === 'reorder' ? sectionDropTarget(view.state, '1.1', 'a.png')! : dropTarget(view.state, source.indexOf('Testo secondo'))
  const moving = destination === 'reorder' ? 'b.png' : 'a.png'
  expect(moveDocumentImage(view, { name: moving, fromUnit: '1.1' }, target, destination !== 'text')).toBe(true)
  expect(view.state.doc.toString().match(new RegExp(moving.replace('.', '\\.'), 'g'))).toHaveLength(1)
  if (destination === 'text') expect(view.state.doc.toString()).toContain('a.png#w=480')
  if (destination === 'reorder') expect(view.state.doc.toString().indexOf('b.png')).toBeLessThan(view.state.doc.toString().indexOf('a.png'))
  expect(undo(view)).toBe(true)
  expect(view.state.doc.toString()).toBe(source)
  view.destroy(); parent.remove()
})
it('immagine nel testo trascinata alla sezione perde la larghezza', () => {
  const source = markdown + '\n\n![Testo](assets/images/a.png#w=220)'
  const { view, parent } = mount(async () => image, false, source)
  moveDocumentImage(view, { name: 'a.png', fromText: source.indexOf('![Testo]') }, sectionDropTarget(view.state, '1.1')!, true)
  expect(view.state.doc.toString()).toContain('00:00\n\n![Testo](assets/images/a.png)')
  expect(view.state.doc.toString()).not.toContain('#w=')
  undo(view)
  expect(view.state.doc.toString()).toBe(source)
  view.destroy(); parent.remove()
})
it('durante il drag mostra i bersagli vuoti e li ripulisce alla fine', () => {
  const { view, parent } = mount(async () => image)
  const event = new Event('dragover', { bubbles: true, cancelable: true })
  Object.defineProperty(event, 'dataTransfer', { value: { types: [RT_SECTION_IMAGE_DRAG_TYPE] } })
  vi.spyOn(view, 'posAtCoords').mockReturnValue(markdown.length)
  view.contentDOM.dispatchEvent(event)
  expect(view.dom).toHaveClass('rt-dragging-images')
  view.contentDOM.dispatchEvent(new Event('dragend', { bubbles: true }))
  expect(view.dom).not.toHaveClass('rt-dragging-images')
  view.destroy(); parent.remove()
})
