import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { PREFERENCES_KEY } from '@/lib/preferences'
import { EditorShortcutsSection } from './shortcuts'

let client: QueryClient
beforeEach(() => {
  localStorage.clear()
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(PREFERENCES_KEY, {})
  vi.spyOn(api, 'GET').mockImplementation(() => Promise.resolve({ data: client.getQueryData(PREFERENCES_KEY), response: new Response('{}', { status: 200 }) }) as never)
  vi.spyOn(api, 'PUT').mockResolvedValue({ response: new Response(null, { status: 204 }) } as never)
  vi.spyOn(api, 'DELETE').mockResolvedValue({ response: new Response(null, { status: 204 }) } as never)
  render(<QueryClientProvider client={client}><EditorShortcutsSection /></QueryClientProvider>)
})
afterEach(() => { cleanup(); client.clear(); vi.restoreAllMocks() })
async function record(command: string, event: { key: string; code?: string; ctrlKey?: boolean; shiftKey?: boolean }) {
  const button = screen.getByRole('button', { name: `Scorciatoia: ${command}` })
  await userEvent.click(button)
  expect(button).toHaveTextContent('Premi i tasti…')
  fireEvent.keyDown(button, event)
}
it('il conflitto nomina il comando, annulla senza salvare e scambia solo dopo conferma', async () => {
  await record('Grassetto', { key: 'i', code: 'KeyI', ctrlKey: true })
  expect(screen.getByRole('dialog')).toHaveTextContent('«Corsivo»')
  expect(api.PUT).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole('button', { name: 'Annulla' }))
  expect(screen.getByRole('button', { name: 'Scorciatoia: Grassetto' })).toHaveTextContent('Ctrl+B')
  await record('Grassetto', { key: 'i', code: 'KeyI', ctrlKey: true })
  await userEvent.click(screen.getByRole('button', { name: 'Scambia' }))
  await waitFor(() => expect(api.PUT).toHaveBeenCalledWith('/api/v1/preferences/{name}', { params: { path: { name: 'editor.shortcuts' } }, body: { bold: 'Mod-i', italic: 'Mod-b' } }))
  expect(screen.getByRole('button', { name: 'Scorciatoia: Corsivo' })).toHaveTextContent('Ctrl+B')
})
it('registra solo le differenze, cerca per nome o tasti, Backspace disabilita ed Esc annulla', async () => {
  await record('Grassetto', { key: 'j', code: 'KeyJ', ctrlKey: true })
  await waitFor(() => expect(api.PUT).toHaveBeenCalled())
  await userEvent.type(screen.getByRole('searchbox'), 'ctrl+j')
  expect(screen.getAllByTestId(/^shortcut-/)).toHaveLength(1)
  expect(screen.getByTestId('shortcut-bold')).toBeVisible()
  await record('Grassetto', { key: 'Escape' })
  expect(screen.getByRole('button', { name: 'Scorciatoia: Grassetto' })).toHaveTextContent('Ctrl+J')
  await record('Grassetto', { key: 'Backspace' })
  await waitFor(() => expect(client.getQueryData(PREFERENCES_KEY)).toEqual({ 'editor.shortcuts': { bold: null } }))
  await userEvent.clear(screen.getByRole('searchbox'))
  expect(screen.getByRole('button', { name: 'Scorciatoia: Grassetto' })).toHaveTextContent('Nessuna')
  await userEvent.click(within(screen.getByTestId('shortcut-bold')).getByRole('button', { name: 'Ripristina: Grassetto' }))
  await waitFor(() => expect(api.DELETE).toHaveBeenCalled())
  expect(screen.getByRole('button', { name: 'Scorciatoia: Grassetto' })).toHaveTextContent('Ctrl+B')
})
it('non assegna le sette combinazioni riservate e ripristina tutte con DELETE', async () => {
  for (const key of ['z', 'c', 'v', 'x', 'a', 'f']) {
    await record('Grassetto', { key, ctrlKey: true })
    expect(screen.getByRole('status')).toHaveTextContent('è riservata')
  }
  await record('Grassetto', { key: 'Z', code: 'KeyZ', ctrlKey: true, shiftKey: true })
  expect(api.PUT).not.toHaveBeenCalled()
  await record('Grassetto', { key: 'j', code: 'KeyJ', ctrlKey: true })
  await waitFor(() => expect(api.PUT).toHaveBeenCalledTimes(1))
  await userEvent.click(screen.getByRole('button', { name: 'Ripristina tutte' }))
  await waitFor(() => expect(api.DELETE).toHaveBeenCalledWith('/api/v1/preferences/{name}', { params: { path: { name: 'editor.shortcuts' } } }))
})
it('su Mac registra il tasto fisico con Option e mostra i simboli', async () => {
  vi.spyOn(navigator, 'platform', 'get').mockReturnValue('MacIntel')
  const button = screen.getByRole('button', { name: 'Scorciatoia: Grassetto' })
  await userEvent.click(button)
  fireEvent.keyDown(button, { key: '∆', code: 'KeyJ', metaKey: true, altKey: true })
  await waitFor(() => expect(api.PUT).toHaveBeenCalledWith('/api/v1/preferences/{name}', { params: { path: { name: 'editor.shortcuts' } }, body: { bold: 'Mod-Alt-j' } }))
  expect(button).toHaveTextContent('⌘⌥J')
})
