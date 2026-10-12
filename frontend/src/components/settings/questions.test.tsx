import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'
import { api } from '@/api/client'
import { QuestionsSettingsSection } from './questions'
const definition = { id: 'query-sql', nome: 'Query SQL', icona: 'Database', materie: ['Informatica'], cerca: 'Trova query', chiedi: 'Chiedi una query', anche_adatti: false, continua: false, correzione: 'soluzione', varianti: false }
const result = (data: unknown) => ({ data, response: new Response('{}', { status: 200 }) })
function setup() {
  vi.spyOn(api, 'GET').mockImplementation((async (path: string) => result(path === '/api/v1/settings/questions' ? { types: [definition], templates: [definition], materie: ['Informatica', 'Storia'] } : path.includes('/export') ? definition : path === '/api/v1/lessons' ? [{ id: 7, titolo: 'Tabelle', materia: 'Informatica' }] : { units: [{ id: '1.1', title: 'SELECT' }] })) as never)
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><QuestionsSettingsSection /></MemoryRouter></QueryClientProvider>)
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
async function choose(label: string, value: string) {
  await userEvent.click(screen.getByRole('button', { name: label }))
  await userEvent.click(await screen.findByRole('menuitemradio', { name: value }))
}
it('modifica i campi mantenendo l’id quando cambia il nome', async () => {
  const put = vi.spyOn(api, 'PUT').mockResolvedValue(result(definition) as never)
  setup(); await userEvent.click(await screen.findByRole('button', { name: 'Modifica Query SQL' }))
  expect(screen.getByLabelText('Identificativo')).toHaveAttribute('readonly')
  fireEvent.change(screen.getByLabelText('Nome'), { target: { value: 'Tabelle' } })
  fireEvent.change(screen.getByLabelText('Cerca'), { target: { value: 'Trova tabelle' } })
  fireEvent.change(screen.getByLabelText('Chiedi'), { target: { value: 'Scrivi SELECT' } })
  for (const label of ['Storia', 'Anche contenuti adatti', 'Unità consecutive', 'Varianti verificate']) await userEvent.click(screen.getByLabelText(label))
  await choose('Correzione', 'Testo della lezione')
  await userEvent.click(screen.getByRole('button', { name: 'Salva tipo' }))
  await waitFor(() => expect(put).toHaveBeenCalledWith('/api/v1/settings/questions/{identifier}', { params: { path: { identifier: 'query-sql' } }, body: { ...definition, nome: 'Tabelle', cerca: 'Trova tabelle', chiedi: 'Scrivi SELECT', materie: ['Informatica', 'Storia'], anche_adatti: true, continua: true, varianti: true, correzione: 'testo' } }))
})
it('copia la galleria, richiede la materia e demanda l’id al server', async () => {
  const post = vi.spyOn(api, 'POST').mockResolvedValue(result(definition) as never)
  setup(); await screen.findByRole('button', { name: 'Modifica Query SQL' }); fireEvent.click(screen.getByText('Scegli un modello da copiare'))
  await userEvent.click(screen.getByRole('button', { name: 'Usa Query SQL' }))
  expect(screen.getByLabelText('Identificativo')).toHaveValue('Generato dal nome')
  expect(screen.getByRole('button', { name: 'Salva tipo' })).toBeDisabled()
  await userEvent.click(screen.getByLabelText('Informatica')); await userEvent.click(screen.getByRole('button', { name: 'Salva tipo' }))
  await waitFor(() => expect(post).toHaveBeenCalledWith('/api/v1/settings/questions', { body: expect.objectContaining({ nome: definition.nome, materie: ['Informatica'], cerca: definition.cerca, chiedi: definition.chiedi }) }))
  expect(post).toHaveBeenCalledWith('/api/v1/settings/questions', { body: { ...definition, id: '' } })
})
it('prova le istruzioni non salvate sull’unità scelta', async () => {
  const post = vi.spyOn(api, 'POST').mockResolvedValue(result({ label: 'presente', example: { question_text: 'Scrivi SELECT', pregenerated_material: 'SELECT 1' } }) as never)
  setup(); await userEvent.click(await screen.findByRole('button', { name: 'Modifica Query SQL' }))
  fireEvent.change(screen.getByLabelText('Chiedi'), { target: { value: 'Una prova nuova' } })
  fireEvent.click(screen.getByText('Prova su un’unità')); await choose('Lezione', 'Tabelle'); await choose('Unità', '1.1 · SELECT')
  await userEvent.click(screen.getByRole('button', { name: 'Prova' }))
  expect(await screen.findByTestId('question-trial-result')).toHaveTextContent('SELECT 1')
  expect(post).toHaveBeenCalledExactlyOnceWith('/api/v1/settings/questions/trial', { body: { definition: { ...definition, chiedi: 'Una prova nuova' }, lesson_id: 7, unit_id: '1.1', mock: false } })
})
it('importa JSON rinominato; un file invalido non viene inviato', async () => {
  const post = vi.spyOn(api, 'POST').mockResolvedValue(result({ ...definition, id: 'query-sql-2' }) as never)
  setup(); const input = await screen.findByLabelText('Importa tipo JSON')
  await userEvent.upload(input, new File(['{invalid'], 'bad.json', { type: 'application/json' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('File JSON non valido'); expect(post).not.toHaveBeenCalled()
  await userEvent.upload(input, new File([JSON.stringify(definition)], 'query.json', { type: 'application/json' }))
  expect(await screen.findByRole('status')).toHaveTextContent('query-sql-2'); expect(post).toHaveBeenCalledWith('/api/v1/settings/questions/import', { body: definition })
})
it('esporta il JSON e conferma l’eliminazione conservando lo storico', async () => {
  setup(); const remove = vi.spyOn(api, 'DELETE').mockResolvedValue(result({ message: 'Eliminato' }) as never)
  const create = vi.fn((blob: Blob) => { expect(blob).toBeInstanceOf(Blob); return 'blob:export' }); const revoke = vi.fn()
  class ExportURL extends URL { static createObjectURL = create; static revokeObjectURL = revoke }
  vi.stubGlobal('URL', ExportURL); const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  await userEvent.click(await screen.findByRole('button', { name: 'Esporta Query SQL' })); await waitFor(() => expect(click).toHaveBeenCalledOnce())
  const content = await new Promise<string>(resolve => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.readAsText(create.mock.calls[0][0]) }); expect(JSON.parse(content)).toEqual(definition)
  expect(api.GET).toHaveBeenCalledWith('/api/v1/settings/questions/{identifier}/export', { params: { path: { identifier: 'query-sql' } } }); expect(revoke).toHaveBeenCalledWith('blob:export')
  await userEvent.click(screen.getByRole('button', { name: 'Elimina Query SQL' })); expect(screen.getByRole('dialog')).toHaveTextContent('resteranno nello storico')
  await userEvent.click(screen.getByRole('button', { name: 'Elimina' }))
  await waitFor(() => expect(remove).toHaveBeenCalledWith('/api/v1/settings/questions/{identifier}', { params: { path: { identifier: 'query-sql' } } }))
})
