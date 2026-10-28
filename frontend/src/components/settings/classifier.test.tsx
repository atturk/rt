import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import { ClassifierSettingsSection } from './classifier'
const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) }) as never
afterEach(() => { cleanup(); vi.restoreAllMocks() })
it('salva modalità indipendenti e mostra il modello proprio', async () => {
 const initial = { model: 'shared', credential: 'openrouter', timeout_seconds: 30, jobs: { relevance: {mode:'off'}, question_types:{mode:'pipeline'} } }
 vi.spyOn(api,'GET').mockImplementation(((path: string) => Promise.resolve(ok(path.endsWith('/classifier') ? initial : {credentials:[{name:'openrouter',set:true}]}))) as never)
 const put=vi.spyOn(api,'PUT').mockResolvedValue(ok(initial))
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
 render(<QueryClientProvider client={client}><ClassifierSettingsSection /></QueryClientProvider>)
 await screen.findByLabelText('Modello condiviso')
 await userEvent.click(screen.getByRole('button',{name:'Modalità Tipo di domanda'}))
 await userEvent.click(screen.getByRole('menuitemradio',{name:'Manuale'}))
 await userEvent.click(screen.getByRole('button',{name:'Modello proprio Tipo di domanda'}))
 await userEvent.type(screen.getByLabelText('Modello proprio'),'own')
 await userEvent.click(screen.getByRole('button',{name:'Salva classificatore'}))
 await waitFor(()=>expect(put).toHaveBeenCalledWith('/api/v1/settings/classifier',{body:{...initial,jobs:{relevance:{mode:'off'},question_types:{mode:'manual',model:'own'}}}}))
})

it.each([undefined, 0.65])('mostra il default immagini 0,7 e conserva la soglia scelta: %s', async (threshold) => {
 const initial = { model: 'shared', credential: 'openrouter', timeout_seconds: 30, jobs: { images: { mode: 'manual', threshold } } }
 vi.spyOn(api, 'GET').mockImplementation(((path: string) => Promise.resolve(ok(path.endsWith('/classifier') ? initial : { credentials: [] }))) as never)
 render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ClassifierSettingsSection /></QueryClientProvider>)
 await userEvent.click(await screen.findByRole('button', { name: 'Modello proprio Immagini' }))
 expect(screen.getByLabelText('Soglia assegnazione')).toHaveValue(threshold ?? 0.7)
})

it('con le immagini accese sceglie la lettura e la salva', async () => {
 const initial = { model: 'shared', credential: 'openrouter', timeout_seconds: 30, images_reader: 'decision', jobs: { images: { mode: 'manual' } } }
 vi.spyOn(api, 'GET').mockImplementation(((path: string) => Promise.resolve(ok(path.endsWith('/classifier') ? initial : { credentials: [] }))) as never)
 const put = vi.spyOn(api, 'PUT').mockResolvedValue(ok(initial))
 render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ClassifierSettingsSection /></QueryClientProvider>)
 await userEvent.click(await screen.findByRole('button', { name: 'Lettura immagini' }))
 await userEvent.click(screen.getByRole('menuitemradio', { name: 'Descrittore' }))
 await userEvent.click(screen.getByRole('button', { name: 'Salva classificatore' }))
 await waitFor(() => expect(put).toHaveBeenCalledWith('/api/v1/settings/classifier', { body: expect.objectContaining({ images_reader: 'description' }) }))
 await userEvent.click(screen.getByRole('button', { name: 'Modalità Immagini' }))
 await userEvent.click(screen.getByRole('menuitemradio', { name: 'Spento' }))
 expect(screen.queryByRole('button', { name: 'Lettura immagini' })).toBeNull()
})

it('salva la lettura delle pagine delle fonti come immagine', async () => {
 const initial = { model: 'shared', credential: 'openrouter', timeout_seconds: 30, material_pages_reader: 'description', jobs: { images: { mode: 'manual' } } }
 vi.spyOn(api, 'GET').mockImplementation(((path: string) => Promise.resolve(ok(path.endsWith('/classifier') ? initial : { credentials: [] }))) as never)
 const put = vi.spyOn(api, 'PUT').mockResolvedValue(ok(initial))
 render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ClassifierSettingsSection /></QueryClientProvider>)
 await userEvent.click(await screen.findByRole('button', { name: 'Lettura pagine delle fonti' }))
 await userEvent.click(screen.getByRole('menuitemradio', { name: 'Immagine' }))
 await userEvent.click(screen.getByRole('button', { name: 'Salva classificatore' }))
 await waitFor(() => expect(put).toHaveBeenCalledWith('/api/v1/settings/classifier', { body: expect.objectContaining({ material_pages_reader: 'image' }) }))
})
