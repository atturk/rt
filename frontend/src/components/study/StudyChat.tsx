import {
  Check,
  Copy,
  LoaderCircle,
  Mic,
  Bookmark,
  BookmarkCheck,
  Paperclip,
  RotateCcw,
  SendHorizontal,
  Square,
  Trash2,
  X,
} from 'lucide-react'
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ClipboardEvent,
  type KeyboardEvent,
} from 'react'

import { errorMessage } from '@/api/client'
import {
  useClearStudyChat,
  useSaveStudyChatNote,
  useSendStudyChat,
  useStudyChat,
  useTranscribeStudyChatAudio,
  useUnsaveStudyChatNote,
  type StudyChatMessage,
} from '@/api/studyChat'
import { MathText } from '@/components/MathText'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/dialog'
import { IconButton } from '@/components/ui/icon-button'
import { renderDelimitedMath } from '@/lib/math'
import { useIsPhone } from '@/lib/phone'
import { recordingFormat } from '@/lib/recording'
import { cn } from '@/lib/utils'
import { ChatSparkIcon } from './ChatSparkIcon'

const MAX_IMAGES = 4
const MAX_IMAGE_BYTES = 10 * 1024 * 1024
const ALLOWED_IMAGE_MIMES = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif'])
const ALLOWED_IMAGE_EXT = /\.(png|jpe?g|webp|gif)$/i

// Bozze non inviate conservate in memoria + sessionStorage per durata della sessione app.
const draftMemory = new Map<number, string>()

function draftStorageKey(lessonId: number): string {
  return `rt.study-chat.draft.${lessonId}`
}

function readDraft(lessonId: number): string {
  if (draftMemory.has(lessonId)) return draftMemory.get(lessonId) ?? ''
  try {
    return window.sessionStorage.getItem(draftStorageKey(lessonId)) ?? ''
  } catch {
    return ''
  }
}

function writeDraft(lessonId: number, value: string): void {
  if (value) draftMemory.set(lessonId, value)
  else draftMemory.delete(lessonId)
  try {
    if (value) window.sessionStorage.setItem(draftStorageKey(lessonId), value)
    else window.sessionStorage.removeItem(draftStorageKey(lessonId))
  } catch {
    // sessionStorage può non essere disponibile in alcuni ambienti
  }
}

function isAllowedImageFile(file: File): boolean {
  if (file.type && ALLOWED_IMAGE_MIMES.has(file.type.toLowerCase())) return true
  return ALLOWED_IMAGE_EXT.test(file.name)
}

export interface StudyChatProps {
  lessonId: number
  unitId: string
  onClose: () => void
  onToast?: (message: string) => void
}

type PendingAttachment = {
  id: string
  file: File
  previewUrl: string
}

export function StudyChat({ lessonId, unitId, onClose, onToast }: StudyChatProps) {
  const isPhone = useIsPhone()
  const chatQuery = useStudyChat(lessonId)
  const sendMutation = useSendStudyChat(lessonId)
  const clearMutation = useClearStudyChat(lessonId)
  const saveNoteMutation = useSaveStudyChatNote(lessonId)
  const unsaveNoteMutation = useUnsaveStudyChatNote(lessonId)
  const transcribeMutation = useTranscribeStudyChatAudio(lessonId)

  const [draft, setDraft] = useState(() => readDraft(lessonId))
  const [attachments, setAttachments] = useState<PendingAttachment[]>([])
  const [attachError, setAttachError] = useState<string | null>(null)
  const [confirmClear, setConfirmClear] = useState(false)
  const [copiedId, setCopiedId] = useState<number | null>(null)
  const [pendingOptimistic, setPendingOptimistic] = useState<{
    text: string
    previewUrls: string[]
  } | null>(null)
  const [recording, setRecording] = useState(false)
  const [sttError, setSttError] = useState<string | null>(null)

  const scrollRef = useRef<HTMLDivElement>(null)
  const nearBottomRef = useRef(true)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const attachmentsRef = useRef<PendingAttachment[]>(attachments)
  useEffect(() => {
    attachmentsRef.current = attachments
  }, [attachments])

  // Cambio lezione: carica la bozza della nuova lezione e pulisce eventuali allegati temporanei
  const prevLessonRef = useRef(lessonId)
  useEffect(() => {
    if (prevLessonRef.current !== lessonId) {
      prevLessonRef.current = lessonId
      setDraft(readDraft(lessonId))
      setAttachError(null)
      setSttError(null)
      setPendingOptimistic(null)
      nearBottomRef.current = true
      setAttachments((prev) => {
        prev.forEach((a) => URL.revokeObjectURL?.(a.previewUrl))
        return []
      })
    }
  }, [lessonId])

  useEffect(() => {
    return () => {
      attachmentsRef.current.forEach((a) => URL.revokeObjectURL?.(a.previewUrl))
      recorderRef.current?.stream.getTracks().forEach((t) => t.stop())
    }
  }, [])

  const updateDraft = useCallback(
    (next: string) => {
      setDraft(next)
      writeDraft(lessonId, next)
    },
    [lessonId],
  )

  // Adatta l'altezza del campo testo fino a ~8 righe
  useLayoutEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 168)}px`
  }, [draft])

  const messages = useMemo(() => chatQuery.data ?? [], [chatQuery.data])

  // Scroll automatico in fondo ai nuovi messaggi, mantenendo la posizione se l'utente ha scorso su
  useLayoutEffect(() => {
    const el = scrollRef.current
    if (!el || !nearBottomRef.current) return
    el.scrollTop = el.scrollHeight
  }, [messages.length, pendingOptimistic])

  const handleScroll = () => {
    const el = scrollRef.current
    if (!el) return
    nearBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60
  }

  // Esc chiude il pannello se il focus non è nel campo con testo e non c'è un dialogo aperto
  useEffect(() => {
    const onKeyDown = (e: globalThis.KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return
      if (document.querySelector('dialog[open]')) return
      const target = e.target as HTMLElement | null
      if (target?.closest?.('input, textarea, select, [contenteditable]')) return
      e.preventDefault()
      onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const addImages = useCallback((files: File[]) => {
    if (!files.length) return
    setAttachError(null)
    setAttachments((prev) => {
      const next = [...prev]
      for (const file of files) {
        if (!isAllowedImageFile(file)) {
          setAttachError('Sono ammesse solo immagini (PNG, JPEG, WebP o GIF).')
          continue
        }
        if (file.size > MAX_IMAGE_BYTES) {
          setAttachError('Ogni immagine può pesare al massimo 10 MB.')
          continue
        }
        if (next.length >= MAX_IMAGES) {
          setAttachError(`Puoi allegare al massimo ${MAX_IMAGES} immagini.`)
          break
        }
        const previewUrl = URL.createObjectURL ? URL.createObjectURL(file) : ''
        next.push({ id: `${Date.now()}-${Math.random().toString(36).slice(2)}`, file, previewUrl })
      }
      return next
    })
  }, [])

  const removeAttachment = (id: string) => {
    setAttachments((prev) => {
      const target = prev.find((a) => a.id === id)
      if (target?.previewUrl) URL.revokeObjectURL?.(target.previewUrl)
      return prev.filter((a) => a.id !== id)
    })
  }

  const handlePaste = (e: ClipboardEvent<HTMLTextAreaElement>) => {
    const items = Array.from(e.clipboardData?.items ?? [])
    const pastedImages: File[] = []
    for (const item of items) {
      if (item.kind === 'file' && item.type.startsWith('image/')) {
        const f = item.getAsFile()
        if (f) pastedImages.push(f)
      }
    }
    if (!pastedImages.length && e.clipboardData?.files?.length) {
      for (const f of Array.from(e.clipboardData.files)) {
        if (isAllowedImageFile(f)) pastedImages.push(f)
      }
    }
    if (pastedImages.length) {
      e.preventDefault()
      addImages(pastedImages)
    }
  }

  const dispatchMessage = async (textToSend: string, filesToSend: File[]) => {
    const clean = textToSend.trim()
    if ((!clean && filesToSend.length === 0) || sendMutation.isPending) return
    setAttachError(null)
    setSttError(null)
    nearBottomRef.current = true
    const previewUrls = filesToSend.map((f) => (URL.createObjectURL ? URL.createObjectURL(f) : ''))
    setPendingOptimistic({ text: clean, previewUrls })
    try {
      await sendMutation.mutateAsync({
        text: clean,
        unitId,
        images: filesToSend,
      })
    } finally {
      previewUrls.forEach((u) => u && URL.revokeObjectURL?.(u))
      setPendingOptimistic(null)
    }
  }

  const handleSend = async () => {
    const clean = draft.trim()
    if ((!clean && attachments.length === 0) || sendMutation.isPending) return
    const filesToSend = attachments.map((a) => a.file)
    const oldDraft = draft
    const oldAttachments = attachments
    updateDraft('')
    setAttachments([])
    try {
      await dispatchMessage(clean, filesToSend)
      oldAttachments.forEach((a) => a.previewUrl && URL.revokeObjectURL?.(a.previewUrl))
    } catch (err) {
      // Ripristina bozza se la richiesta HTTP fallisce prima di salvare
      updateDraft(oldDraft)
      setAttachments(oldAttachments)
      setAttachError(errorMessage(err))
    }
  }

  const handleRetry = async (failedMsgIndex: number) => {
    let userText = ''
    for (let i = failedMsgIndex - 1; i >= 0; i--) {
      if (messages[i]?.role === 'user') {
        userText = messages[i].content
        break
      }
    }
    if (!userText.trim()) return
    try {
      await dispatchMessage(userText, [])
    } catch (err) {
      setAttachError(errorMessage(err))
    }
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && e.nativeEvent.keyCode !== 229) {
      e.preventDefault()
      void handleSend()
    }
  }

  const handleCopy = (msg: StudyChatMessage) => {
    if (!msg.content) return
    void navigator.clipboard?.writeText(msg.content)
    setCopiedId(msg.id)
    setTimeout(() => {
      setCopiedId((cur) => (cur === msg.id ? null : cur))
    }, 2000)
  }

  const handleToggleNote = async (msg: StudyChatMessage) => {
    if (saveNoteMutation.isPending || unsaveNoteMutation.isPending) return
    if (msg.saved_note_id != null) {
      await unsaveNoteMutation.mutateAsync(msg.id)
    } else {
      await saveNoteMutation.mutateAsync(msg.id)
      onToast?.('Salvata nei messaggi salvati')
    }
  }

  const sttSupported =
    typeof window !== 'undefined' && 'MediaRecorder' in window && !!navigator.mediaDevices?.getUserMedia

  const toggleRecording = async () => {
    if (recording) {
      recorderRef.current?.stop()
      recorderRef.current = null
      setRecording(false)
      return
    }
    setSttError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const format = recordingFormat((t) => MediaRecorder.isTypeSupported(t))
      const rec = new MediaRecorder(stream, format.mimeType ? { mimeType: format.mimeType } : undefined)
      const chunks: Blob[] = []
      rec.ondataavailable = (e) => {
        if (e.data.size) chunks.push(e.data)
      }
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        const type = rec.mimeType || format.mimeType || 'audio/webm'
        const file = new File(chunks, `domanda.${format.extension}`, { type })
        void transcribeMutation
          .mutateAsync(file)
          .then((res) => {
            const transcribed = (res.text ?? '').trim()
            if (!transcribed) return
            const current = readDraft(lessonId)
            const next = current.trim() ? `${current.trimEnd()} ${transcribed}` : transcribed
            updateDraft(next)
            textareaRef.current?.focus()
          })
          .catch((err) => setSttError(errorMessage(err)))
      }
      rec.start()
      recorderRef.current = rec
      setRecording(true)
    } catch (err) {
      const denied = err instanceof Error && err.name === 'NotAllowedError'
      const inApp = 'pywebview' in window
      setSttError(
        denied
          ? inApp
            ? 'Microfono non consentito. Menu RT › Controlla permessi.'
            : 'Il browser non ha il permesso di usare il microfono.'
          : 'Microfono non disponibile.',
      )
    }
  }

  return (
    <aside
      data-study-chat
      data-testid="study-chat-panel"
      aria-label="Chat dello Studio"
      className={cn(
        'flex flex-col bg-background',
        isPhone
          ? 'fixed inset-0 z-60 h-dvh w-full'
          : 'w-[380px] shrink-0 border-l border-border/80 md:sticky md:top-[53px] md:h-[calc(100dvh-53px)]',
      )}
    >
      {/* Intestazione */}
      <div className="flex h-12 shrink-0 items-center justify-between border-b border-border/80 px-4">
        <div className="flex items-center gap-2">
          <ChatSparkIcon className="size-4 text-foreground" />
          <h2 className="text-body font-semibold text-foreground">Chat</h2>
        </div>
        <div className="flex items-center gap-1">
          <IconButton
            label="Cancella cronologia"
            icon={Trash2}
            disabled={messages.length === 0 || clearMutation.isPending}
            onClick={() => setConfirmClear(true)}
            data-testid="study-chat-clear"
          />
          <IconButton
            label="Chiudi chat"
            icon={X}
            onClick={onClose}
            data-testid="study-chat-close"
          />
        </div>
      </div>

      {/* Area messaggi */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 py-4"
        data-testid="study-chat-messages"
      >
        {chatQuery.isLoading && (
          <p className="text-meta text-muted-foreground">Caricamento chat…</p>
        )}

        {!chatQuery.isLoading && messages.length === 0 && !pendingOptimistic && (
          <div
            className="my-auto flex flex-col items-center gap-3 px-4 text-center text-muted-foreground"
            data-testid="study-chat-empty"
          >
            <ChatSparkIcon className="size-8 text-muted-foreground/70" />
            <p className="text-body leading-relaxed">
              Chiedi spiegazioni, incolla un passaggio da verificare o allega un&apos;immagine.
            </p>
          </div>
        )}

        {messages.map((msg, idx) => {
          if (msg.role === 'user') {
            return (
              <div
                key={msg.id}
                data-testid={`chat-msg-user-${msg.id}`}
                className="flex max-w-[85%] flex-col gap-1.5 self-end rounded-2xl rounded-br-sm border border-border/60 bg-muted/70 px-3.5 py-2.5 text-body text-foreground"
              >
                {(msg.image_urls ?? []).length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {(msg.image_urls ?? []).map((url, i) => (
                      <img
                        key={i}
                        src={url}
                        alt={`Allegato ${i + 1}`}
                        className="max-h-36 max-w-full rounded-lg border border-border/60 object-contain"
                      />
                    ))}
                  </div>
                )}
                {msg.content && (
                  <p className="whitespace-pre-wrap [overflow-wrap:anywhere]">{msg.content}</p>
                )}
              </div>
            )
          }

          const isSaved = msg.saved_note_id != null
          const isCopied = copiedId === msg.id
          return (
            <div
              key={msg.id}
              data-testid={`chat-msg-assistant-${msg.id}`}
              className="flex flex-col gap-1.5 self-start w-full max-w-full text-body text-foreground"
            >
              {msg.error ? (
                <div
                  role="alert"
                  className="flex flex-col items-start gap-2 rounded-xl border border-danger/30 bg-danger-soft/40 p-3 text-meta text-danger"
                  data-testid={`chat-msg-error-${msg.id}`}
                >
                  <span>{msg.error}</span>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 gap-1 px-2.5 text-meta"
                    disabled={sendMutation.isPending}
                    onClick={() => void handleRetry(idx)}
                    data-testid={`chat-retry-${msg.id}`}
                  >
                    <RotateCcw className="size-3.5" aria-hidden /> Riprova
                  </Button>
                </div>
              ) : (
                <>
                  <ChatMarkdown html={msg.content_html} text={msg.content} />
                  <div className="flex items-center gap-1 pt-0.5 text-muted-foreground">
                    <IconButton
                      label={isCopied ? 'Copiato' : 'Copia'}
                      icon={isCopied ? Check : Copy}
                      className="size-7 min-w-7 [&_svg]:size-3.5"
                      onClick={() => handleCopy(msg)}
                      data-testid={`chat-copy-${msg.id}`}
                    />
                    {isCopied && (
                      <span className="text-meta text-ok" role="status">
                        Copiato
                      </span>
                    )}
                    <IconButton
                      label={isSaved ? 'Togli dai messaggi salvati' : 'Salva nei messaggi salvati'}
                      icon={isSaved ? BookmarkCheck : Bookmark}
                      active={isSaved}
                      className={cn(
                        'size-7 min-w-7 [&_svg]:size-3.5',
                        isSaved && 'text-primary',
                      )}
                      aria-pressed={isSaved}
                      onClick={() => void handleToggleNote(msg)}
                      data-testid={`chat-save-note-${msg.id}`}
                    />
                  </div>
                </>
              )}
            </div>
          )
        })}

        {pendingOptimistic && (
          <>
            <div className="flex max-w-[85%] flex-col gap-1.5 self-end rounded-2xl rounded-br-sm border border-border/60 bg-muted/70 px-3.5 py-2.5 text-body text-foreground">
              {pendingOptimistic.previewUrls.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {pendingOptimistic.previewUrls.map((url, i) =>
                    url ? (
                      <img
                        key={i}
                        src={url}
                        alt={`Allegato ${i + 1}`}
                        className="max-h-36 max-w-full rounded-lg border border-border/60 object-contain"
                      />
                    ) : null,
                  )}
                </div>
              )}
              {pendingOptimistic.text && (
                <p className="whitespace-pre-wrap [overflow-wrap:anywhere]">{pendingOptimistic.text}</p>
              )}
            </div>
            <div
              role="status"
              aria-label="Risposta in arrivo"
              data-testid="study-chat-typing"
              className="flex items-center gap-1.5 self-start text-meta text-muted-foreground"
            >
              <span className="inline-flex gap-0.5" aria-hidden>
                <span className="size-1 animate-bounce rounded-full bg-muted-foreground [animation-delay:0ms]" />
                <span className="size-1 animate-bounce rounded-full bg-muted-foreground [animation-delay:150ms]" />
                <span className="size-1 animate-bounce rounded-full bg-muted-foreground [animation-delay:300ms]" />
              </span>
            </div>
          </>
        )}
      </div>

      {/* Input in basso */}
      <div className="shrink-0 border-t border-border/80 p-3">
        {(attachError || sttError) && (
          <Alert tone="danger" className="mb-2 py-1.5 text-meta">
            {attachError ?? sttError}
          </Alert>
        )}

        {attachments.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2" data-testid="study-chat-previews">
            {attachments.map((att) => (
              <div key={att.id} className="relative size-14 overflow-hidden rounded-lg border border-border bg-muted">
                {att.previewUrl ? (
                  <img src={att.previewUrl} alt={att.file.name} className="size-full object-cover" />
                ) : (
                  <span className="flex size-full items-center justify-center px-1 text-[10px] text-muted-foreground">
                    {att.file.name}
                  </span>
                )}
                <button
                  type="button"
                  aria-label={`Rimuovi ${att.file.name}`}
                  onClick={() => removeAttachment(att.id)}
                  className="absolute right-0.5 top-0.5 flex size-4 items-center justify-center rounded-full bg-background/90 text-foreground shadow hover:bg-background"
                >
                  <X className="size-3" aria-hidden />
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="flex items-end gap-1.5 rounded-xl border border-border bg-card p-1.5 focus-within:ring-2 focus-within:ring-ring">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="image/png,image/jpeg,image/webp,image/gif"
            className="sr-only"
            data-testid="study-chat-file-input"
            onChange={(e) => {
              addImages(Array.from(e.target.files ?? []))
              e.target.value = ''
            }}
          />
          <IconButton
            label="Allega immagine"
            icon={Paperclip}
            side="top"
            className="size-8 min-w-8 [&_svg]:size-4"
            disabled={attachments.length >= MAX_IMAGES || sendMutation.isPending}
            onClick={() => fileInputRef.current?.click()}
            data-testid="study-chat-attach"
          />
          <IconButton
            label={
              transcribeMutation.isPending
                ? 'Trascrizione in corso…'
                : recording
                  ? 'Ferma registrazione'
                  : 'Dettatura vocale'
            }
            icon={transcribeMutation.isPending ? LoaderCircle : recording ? Square : Mic}
            side="top"
            active={recording}
            className={cn(
              'size-8 min-w-8 [&_svg]:size-4',
              recording && 'text-danger',
              transcribeMutation.isPending && '[&_svg]:animate-spin',
            )}
            disabled={transcribeMutation.isPending || (!recording && !sttSupported)}
            onClick={() => void toggleRecording()}
            data-testid="study-chat-mic"
          />
          <textarea
            ref={textareaRef}
            rows={1}
            value={draft}
            placeholder="Chiedi sulla lezione…"
            aria-label="Messaggio per la chat"
            data-testid="study-chat-input"
            onChange={(e) => updateDraft(e.target.value)}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            className="max-h-42 min-h-8 flex-1 resize-none bg-transparent py-1.5 text-body text-foreground placeholder:text-muted-foreground focus:outline-none"
          />
          <IconButton
            label="Invia messaggio"
            icon={SendHorizontal}
            side="top"
            variant="solid"
            className="size-8 min-w-8 [&_svg]:size-4"
            disabled={(!draft.trim() && attachments.length === 0) || sendMutation.isPending}
            onClick={() => void handleSend()}
            data-testid="study-chat-send"
          />
        </div>
      </div>

      <ConfirmDialog
        open={confirmClear}
        title="Cancella cronologia"
        confirmLabel="Cancella"
        confirmDisabled={clearMutation.isPending}
        onCancel={() => setConfirmClear(false)}
        onConfirm={() => {
          clearMutation.mutate(undefined, {
            onSuccess: () => setConfirmClear(false),
          })
        }}
      >
        <p>Cancellare la cronologia della chat di questa lezione?</p>
      </ConfirmDialog>
    </aside>
  )
}

function ChatMarkdown({ html, text }: { html?: string; text: string }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (ref.current) void renderDelimitedMath(ref.current)
  }, [html, text])
  if (!html) {
    return (
      <div ref={ref} className="rt-document rt-reading text-body leading-relaxed [overflow-wrap:anywhere]">
        <MathText text={text} />
      </div>
    )
  }
  return (
    <div
      ref={ref}
      className="rt-document rt-reading text-body leading-relaxed [overflow-wrap:anywhere]"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
