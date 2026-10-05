import { Bold, Code, Highlighter, Italic, Link, List, ListOrdered, Redo2, Search, SquareCheck, Strikethrough, Undo2, type LucideIcon } from 'lucide-react'
import { redoDepth, undoDepth } from '@codemirror/commands'
import type { EditorState } from '@codemirror/state'
import type { EditorView } from '@codemirror/view'

import { IconButton } from '@/components/ui/icon-button'
import { commandActive, commandShortcut, editorCommands, shortcutLabel, type ShortcutPreferences } from './markdownShortcuts'

const GROUPS: { id: string; icon: LucideIcon }[][] = [
  [{ id: 'undo', icon: Undo2 }, { id: 'redo', icon: Redo2 }],
  [{ id: 'bullet-list', icon: List }, { id: 'numbered-list', icon: ListOrdered }, { id: 'checkbox', icon: SquareCheck }],
  [{ id: 'bold', icon: Bold }, { id: 'italic', icon: Italic }, { id: 'strike', icon: Strikethrough }, { id: 'code', icon: Code }, { id: 'highlight', icon: Highlighter }, { id: 'link', icon: Link }],
  [{ id: 'search', icon: Search }],
]

export function EditorToolbar({ view, state = view?.state, shortcuts, readOnly }: { view: EditorView | null; state?: EditorState; shortcuts: ShortcutPreferences; readOnly: boolean }) {
  if (readOnly || state?.readOnly) return null
  return <div role="toolbar" aria-label="Strumenti dell’editor" className="rt-editor-toolbar">
    {GROUPS.map((group, index) => <div key={index} className="flex shrink-0 items-center gap-0.5">
      {index > 0 && <span role="separator" aria-orientation="vertical" className="mx-2 h-5 border-l" />}
      {group.map(({ id, icon }) => {
        const command = editorCommands.find(command => command.id === id)!
        const key = commandShortcut(command, shortcuts)
        const label = command.etichetta + (key ? ` (${shortcutLabel(key)})` : '')
        const formatting = ['bold', 'italic', 'strike', 'code', 'highlight', 'link', 'bullet-list', 'numbered-list', 'checkbox'].includes(id)
        const active = !!state && formatting && commandActive(state, id)
        const disabled = !view || !state || (id === 'undo' && undoDepth(state) === 0) || (id === 'redo' && redoDepth(state) === 0)
        return <IconButton key={id} label={label} icon={icon} active={active} aria-pressed={formatting ? active : undefined} disabled={disabled}
          onMouseDown={event => event.preventDefault()} onClick={() => { if (view) { command.run(view); if (id !== 'search') view.focus() } }} />
      })}
    </div>)}
  </div>
}
