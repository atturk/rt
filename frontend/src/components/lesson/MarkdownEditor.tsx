import { defaultKeymap, history, historyKeymap } from '@codemirror/commands'
import { markdown } from '@codemirror/lang-markdown'
import { HighlightStyle, syntaxHighlighting } from '@codemirror/language'
import { tags } from '@lezer/highlight'
import { EditorState } from '@codemirror/state'
import { EditorView, keymap, lineNumbers } from '@codemirror/view'
import { useEffect, useRef } from 'react'

/**
 * Aspetto da anteprima dal vivo (design 4.2, schermata 02): titoli in grassetto, grassetto e
 * corsivo resi, i segni del Markdown (#, **, _, `) grigi. Il Markdown resta la fonte.
 */
const livePreview = HighlightStyle.define([
  { tag: tags.heading1, fontWeight: '600', fontSize: '22px' },
  { tag: [tags.heading2, tags.heading3, tags.heading4, tags.heading5, tags.heading6], fontWeight: '600' },
  { tag: tags.strong, fontWeight: '600' },
  { tag: tags.emphasis, fontStyle: 'italic' },
  { tag: tags.strikethrough, textDecoration: 'line-through' },
  { tag: [tags.processingInstruction, tags.meta, tags.contentSeparator, tags.labelName], color: 'var(--mute)' },
  { tag: [tags.link, tags.url], color: 'var(--link)', textDecoration: 'underline' },
  { tag: tags.monospace, fontFamily: 'var(--font-mono)', backgroundColor: 'var(--soft)' },
  { tag: tags.quote, color: 'var(--mute)' },
])

type Props = {
  value: string
  onChange: (value: string) => void
  /** Esc dentro l'editor: annulla la modifica. */
  onEscape: () => void
  label: string
  /** Riga (da 1) da portare in vista e selezionare, per gli errori. */
  focusLine?: number | null
}

/**
 * Editor Markdown (CodeMirror 6 con il linguaggio markdown): numeri di riga per ritrovare gli
 * errori del backend, annulla/ripeti, a capo automatico. Non controllato: il testo iniziale
 * è `value` al montaggio, poi ogni modifica arriva con onChange.
 */
export function MarkdownEditor({ value, onChange, onEscape, label, focusLine }: Props) {
  const host = useRef<HTMLDivElement>(null)
  const view = useRef<EditorView | null>(null)
  const callbacks = useRef({ onChange, onEscape })
  callbacks.current = { onChange, onEscape }

  useEffect(() => {
    if (!host.current) return
    const editor = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          lineNumbers(),
          history(),
          markdown(),
          syntaxHighlighting(livePreview),
          EditorView.lineWrapping,
          keymap.of([
            {
              key: 'Escape',
              run: () => {
                callbacks.current.onEscape()
                return true
              },
            },
            ...defaultKeymap,
            ...historyKeymap,
          ]),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) callbacks.current.onChange(update.state.doc.toString())
          }),
          EditorView.contentAttributes.of({ 'aria-label': label, 'aria-multiline': 'true' }),
        ],
      }),
    })
    view.current = editor
    editor.focus()
    return () => {
      editor.destroy()
      view.current = null
    }
    // Il testo iniziale conta solo al montaggio: poi l'editor ha il suo stato.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const editor = view.current
    if (!editor || !focusLine) return
    const line = editor.state.doc.line(Math.min(Math.max(focusLine, 1), editor.state.doc.lines))
    editor.dispatch({ selection: { anchor: line.from, head: line.to }, scrollIntoView: true })
    editor.focus()
  }, [focusLine])

  return <div ref={host} className="rt-md-editor" data-testid="markdown-editor" />
}
