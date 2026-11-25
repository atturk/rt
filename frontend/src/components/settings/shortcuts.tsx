import { useState, type KeyboardEvent } from 'react'
import { RotateCcw } from 'lucide-react'

import { editorCommands, commandShortcut, isMacKeyboard, isReservedShortcut, normalizeShortcut, shortcutLabel, withShortcut, type EditorCommand, type ShortcutPreferences } from '@/components/lesson/markdownShortcuts'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/dialog'
import { IconButton } from '@/components/ui/icon-button'
import { Input } from '@/components/ui/input'
import { usePreference } from '@/lib/preferences'
import { SettingsGroup, SettingsPage, SettingsRow, SettingsSwitch } from './ui'

const DEFAULT_SHORTCUTS: ShortcutPreferences = {}

/** Usa il tasto fisico per lettere e parentesi: Option su Mac può cambiare event.key. */
function recordedKey(event: KeyboardEvent): string | null {
  if (['Control', 'Meta', 'Alt', 'Shift', 'AltGraph', 'Dead'].includes(event.key)) return null
  const punctuation: Record<string, string> = { BracketLeft: '[', BracketRight: ']', Backslash: '\\', Semicolon: ';', Quote: "'", Comma: ',', Period: '.', Slash: '/', Equal: '=' }
  const key = /^Key[A-Z]$/.test(event.code) ? event.code.slice(3).toLowerCase()
    : /^Digit\d$/.test(event.code) ? event.code.slice(5) : punctuation[event.code] ?? event.key
  const mac = isMacKeyboard()
  const modifiers = [event.metaKey ? (mac ? 'Mod' : 'Meta') : '', event.ctrlKey ? (mac ? 'Ctrl' : 'Mod') : '', event.altKey ? 'Alt' : '', event.shiftKey ? 'Shift' : ''].filter(Boolean)
  return [...modifiers, key.length === 1 ? key.toLowerCase() : key].join('-')
}

type Conflict = { command: EditorCommand; other: EditorCommand; key: string; previous: string | null }

export function EditorShortcutsSection() {
  const [toolbar, saveToolbar] = usePreference('editor.toolbar', true)
  const [preferences, save] = usePreference<ShortcutPreferences>('editor.shortcuts', DEFAULT_SHORTCUTS)
  const [search, setSearch] = useState('')
  const [recording, setRecording] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [conflict, setConflict] = useState<Conflict | null>(null)
  const commands = editorCommands.filter(command => {
    if (command.personalizzabile === false) return false
    const key = commandShortcut(command, preferences)
    const text = [command.etichetta, command.gruppo, key, shortcutLabel(key)].join(' ').toLocaleLowerCase('it')
    return text.includes(search.toLocaleLowerCase('it').trim())
  })
  const groups = [...new Set(commands.map(command => command.gruppo))]
  function store(next: ShortcutPreferences) { save(Object.keys(next).length ? next : undefined) }
  function assign(command: EditorCommand, key: string | null) {
    setRecording(null)
    if (key && isReservedShortcut(key)) { setMessage(`${shortcutLabel(key)} è riservata.`); return }
    const other = key && editorCommands.find(candidate => candidate.id !== command.id &&
      normalizeShortcut(commandShortcut(candidate, preferences) ?? '') === normalizeShortcut(key))
    if (other) setConflict({ command, other, key: key!, previous: commandShortcut(command, preferences) })
    else store(withShortcut(preferences, command, key))
  }
  function record(event: KeyboardEvent<HTMLButtonElement>, command: EditorCommand) {
    if (recording !== command.id) return
    event.preventDefault()
    event.stopPropagation()
    if (event.key === 'Escape') { setRecording(null); return }
    if (event.key === 'Backspace') { assign(command, null); return }
    const key = recordedKey(event)
    if (key) assign(command, key)
  }
  return (
    <SettingsPage
      title="Editor e scorciatoie"
      description="Barra di formattazione e combinazioni da tastiera dell’editor."
    >
      <SettingsGroup title="Editor">
        <SettingsSwitch
          id="editor-toolbar"
          label="Barra di formattazione"
          info="Mostra la barra rapida sopra il testo delle lezioni per grassetto, corsivo, liste e link."
          checked={toolbar}
          onChange={saveToolbar}
        />
        <div className="px-4 py-3">
          <Input
            type="search"
            aria-label="Cerca comando o combinazione"
            placeholder="Cerca comando o combinazione"
            value={search}
            onChange={e => { setSearch(e.target.value); setRecording(null) }}
          />
        </div>
      </SettingsGroup>
      {message && <Alert tone="warning">{message}</Alert>}
      {groups.map(group => (
        <SettingsGroup key={group} id={`scorciatoie-${group.toLowerCase()}`} title={group}>
          {commands.filter(command => command.gruppo === group).map(command => {
            const key = commandShortcut(command, preferences)
            return (
              <SettingsRow
                key={command.id}
                testId={`shortcut-${command.id}`}
                label={command.etichetta}
                compactControl
                control={
                  <div className="flex items-center gap-1.5">
                    <Button
                      variant="outline"
                      className="min-w-24 text-body"
                      aria-label={`Scorciatoia: ${command.etichetta}`}
                      onClick={() => { setMessage(null); setRecording(command.id) }}
                      onBlur={() => setRecording(null)}
                      onKeyDown={e => record(e, command)}
                    >
                      {recording === command.id ? 'Premi i tasti…' : shortcutLabel(key)}
                    </Button>
                    <IconButton
                      label={`Ripristina: ${command.etichetta}`}
                      icon={RotateCcw}
                      disabled={!Object.hasOwn(preferences, command.id)}
                      onClick={() => { setMessage(null); assign(command, command.predefinita) }}
                    />
                  </div>
                }
              />
            )
          })}
        </SettingsGroup>
      ))}
      {!commands.length && <p className="text-body text-muted-foreground">Nessun comando.</p>}
      <div>
        <Button
          variant="outline"
          disabled={!Object.keys(preferences).length}
          onClick={() => { save(undefined); setMessage(null); setRecording(null) }}
        >
          Ripristina tutte
        </Button>
      </div>
      <ConfirmDialog
        open={!!conflict}
        title="Scorciatoia già usata"
        confirmLabel="Scambia"
        onCancel={() => setConflict(null)}
        onConfirm={() => {
          if (!conflict) return
          store(withShortcut(withShortcut(preferences, conflict.command, conflict.key), conflict.other, conflict.previous))
          setConflict(null)
        }}
      >
        {conflict && <p>{shortcutLabel(conflict.key)} è già usata da «{conflict.other.etichetta}». Scambiare con «{conflict.command.etichetta}»?</p>}
      </ConfirmDialog>
    </SettingsPage>
  )
}
