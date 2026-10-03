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
