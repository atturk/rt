import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { studyChatApi, type StudyChatMessage } from '@/api/studyChat'
import { StudyChat } from './StudyChat'

vi.mock('@/lib/math', () => ({
  DELIMITED: /\$\$[\s\S]+?\$\$|\$[^$\n]+\$/g,
  renderDelimitedMath: vi.fn().mockResolvedValue(undefined),
}))

function wrapper() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  })
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
}

const MSG_USER: StudyChatMessage = {
  id: 1,
  lesson_id: 10,
  role: 'user',
  content: 'Cos’è la glicolisi?',
  content_html: '<p>Cos’è la glicolisi?</p>',
  images: [],
  image_urls: [],
  unit_id: '1.1',
  model: null,
  cost: null,
  error: null,
  saved_note_id: null,
  created_at: '2026-11-24T00:00:00',
}

const MSG_ASSISTANT: StudyChatMessage = {
  id: 2,
  lesson_id: 10,
  role: 'assistant',
  content: 'È la **via metabolica** nel citosol.',
  content_html: '<p>È la <strong>via metabolica</strong> nel citosol.</p>',
  images: [],
  image_urls: [],
  unit_id: '1.1',
  model: 'test-model',
  cost: 0.001,
  error: null,
  saved_note_id: null,
  created_at: '2026-11-24T00:00:01',
}

describe('StudyChat', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    window.sessionStorage.clear()
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    })
  })

  it('mostra stato vuoto, invia con Invio e va a capo con Maiusc+Invio', async () => {
    vi.spyOn(studyChatApi, 'list').mockResolvedValue([])
    const sendSpy = vi.spyOn(studyChatApi, 'send').mockResolvedValue({
      user_message: MSG_USER,
      assistant_message: MSG_ASSISTANT,
    })

    render(<StudyChat lessonId={10} unitId="1.1" onClose={vi.fn()} />, { wrapper: wrapper() })

    expect(await screen.findByTestId('study-chat-empty')).toBeInTheDocument()
    const input = screen.getByTestId('study-chat-input') as HTMLTextAreaElement

    await userEvent.type(input, 'Prima riga{Shift>}{Enter}{/Shift}Seconda riga')
    expect(input.value).toBe('Prima riga\nSeconda riga')
    expect(sendSpy).not.toHaveBeenCalled()

    await userEvent.type(input, '{Enter}')
    await waitFor(() => expect(sendSpy).toHaveBeenCalledTimes(1))
    expect(sendSpy).toHaveBeenCalledWith(10, {
      text: 'Prima riga\nSeconda riga',
      unitId: '1.1',
      images: [],
    })
    expect(await screen.findByTestId('chat-msg-assistant-2')).toBeInTheDocument()
  })

  it('gestisce incolla immagine dagli appunti e limite 4 immagini', async () => {
    vi.spyOn(studyChatApi, 'list').mockResolvedValue([])
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => 'blob:preview'),
      revokeObjectURL: vi.fn(),
    })

    render(<StudyChat lessonId={10} unitId="1.1" onClose={vi.fn()} />, { wrapper: wrapper() })
    const input = await screen.findByTestId('study-chat-input')

    const imgFile = new File([new Uint8Array([1, 2, 3])], 'slide.png', { type: 'image/png' })
    fireEvent.paste(input, {
      clipboardData: {
        items: [{ kind: 'file', type: 'image/png', getAsFile: () => imgFile }],
        files: [imgFile],
      },
    })

    expect(await screen.findByTestId('study-chat-previews')).toBeInTheDocument()
    expect(screen.getByAltText('slide.png')).toBeInTheDocument()
  })

  it('copia Markdown e salva/toglie nei messaggi salvati', async () => {
    vi.spyOn(studyChatApi, 'list').mockResolvedValue([MSG_USER, MSG_ASSISTANT])
    const saveSpy = vi.spyOn(studyChatApi, 'saveNote').mockResolvedValue({
      message: { ...MSG_ASSISTANT, saved_note_id: 99 },
      note: {
        id: 99,
        lesson_id: 10,
        unit_id: '1.1',
        kind: 'chat',
        anchor: {},
        unit_fingerprint: '',
        request: MSG_USER.content,
        response: { text: MSG_ASSISTANT.content },
        spiegazione_html: MSG_ASSISTANT.content_html,
        correzione_html: '',
        model: 'test-model',
        cost: 0.001,
        created_at: '2026-11-24T00:00:01',
        applied_decision_id: null,
        issue_id: null,
        anchor_state: 'trovata',
        current_quote: null,
        precedente: false,
      },
    })
    const unsaveSpy = vi.spyOn(studyChatApi, 'unsaveNote').mockResolvedValue({
      ...MSG_ASSISTANT,
      saved_note_id: null,
    })
    const toastSpy = vi.fn()

    render(<StudyChat lessonId={10} unitId="1.1" onClose={vi.fn()} onToast={toastSpy} />, { wrapper: wrapper() })
    await screen.findByTestId('chat-msg-assistant-2')

    await userEvent.click(screen.getByTestId('chat-copy-2'))
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(MSG_ASSISTANT.content)
    expect(screen.getByRole('status')).toHaveTextContent('Copiato')

    const noteBtn = screen.getByTestId('chat-save-note-2')
    await userEvent.click(noteBtn)
    await waitFor(() => expect(saveSpy).toHaveBeenCalledWith(10, 2))
    expect(toastSpy).toHaveBeenCalledWith('Salvata nei messaggi salvati')
    expect(noteBtn).toHaveAttribute('aria-pressed', 'true')

    await userEvent.click(noteBtn)
    await waitFor(() => expect(unsaveSpy).toHaveBeenCalledWith(10, 2))
    expect(noteBtn).toHaveAttribute('aria-pressed', 'false')
  })

  it('cestino con conferma cancella la cronologia', async () => {
    vi.spyOn(studyChatApi, 'list').mockResolvedValue([MSG_USER, MSG_ASSISTANT])
    const clearSpy = vi.spyOn(studyChatApi, 'clear').mockResolvedValue(undefined as never)

    render(<StudyChat lessonId={10} unitId="1.1" onClose={vi.fn()} />, { wrapper: wrapper() })
    await screen.findByTestId('chat-msg-assistant-2')

    await userEvent.click(screen.getByTestId('study-chat-clear'))
    expect(screen.getByText('Cancellare la cronologia della chat di questa lezione?')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Cancella' }))
    await waitFor(() => expect(clearSpy).toHaveBeenCalledWith(10))
    expect(await screen.findByTestId('study-chat-empty')).toBeInTheDocument()
  })

  it('mostra errore nel fumetto con Riprova che reinvia la domanda precedente', async () => {
    const failedAssistant: StudyChatMessage = {
      ...MSG_ASSISTANT,
      id: 3,
      content: '',
      content_html: '',
      error: 'Errore di rete temporaneo',
    }
    vi.spyOn(studyChatApi, 'list').mockResolvedValue([MSG_USER, failedAssistant])
    const sendSpy = vi.spyOn(studyChatApi, 'send').mockResolvedValue({
      user_message: { ...MSG_USER, id: 4 },
      assistant_message: { ...MSG_ASSISTANT, id: 5 },
    })

    render(<StudyChat lessonId={10} unitId="1.1" onClose={vi.fn()} />, { wrapper: wrapper() })
    expect(await screen.findByText('Errore di rete temporaneo')).toBeInTheDocument()

    await userEvent.click(screen.getByTestId('chat-retry-3'))
    await waitFor(() => expect(sendSpy).toHaveBeenCalledWith(10, {
      text: MSG_USER.content,
      unitId: '1.1',
      images: [],
    }))
    expect(await screen.findByTestId('chat-msg-assistant-5')).toBeInTheDocument()
  })
})
