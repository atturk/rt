import { Brain, Headphones, SlidersHorizontal, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { Modal } from '@/components/ui/modal'
import { useRsvpPrefs, type RsvpPreference } from '@/lib/studyPrefs'
import type { StudyStatus } from '@/api/studyProgress'
import { useSettings } from '@/api/settings'
import { resolveStudyStatus, type CustomStudyStatus } from './studyProgress'
import { cn } from '@/lib/utils'
import { IrlenWarningModal } from './IrlenWarningModal'

/** La barra segue il mouse e il focus, mai lo scroll del testo. */
export function ZenHeader({
  title, settings, onSettings, onExit, irlen, onIrlen, hasNonYellowHighlight, status, onStatus,
  hasAudio, audioOpen, onToggleAudio, onReview,
}: {
  title: string; settings: boolean; onSettings: (open: boolean) => void; onExit: () => void
  irlen: RsvpPreference['irlen']; onIrlen: (value: RsvpPreference['irlen']) => void
  hasNonYellowHighlight?: boolean
  status?: StudyStatus
  onStatus?: () => void
  hasAudio?: boolean
  audioOpen?: boolean
  onToggleAudio?: () => void
  onReview?: () => void
}) {
  const [prefs, setPrefs] = useRsvpPrefs()
  const [showWarning, setShowWarning] = useState(false)
  const [open, setOpen] = useState(false)
  const bar = useRef<HTMLDivElement>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const cancel = () => { if (timer.current) clearTimeout(timer.current); timer.current = null }
  const show = () => { cancel(); setOpen(true) }
  const leave = () => {
    cancel()
    if (!settings && !bar.current?.contains(document.activeElement)) timer.current = setTimeout(() => setOpen(false), 2000)
  }
  useEffect(() => {
    const mouse = (event: PointerEvent) => {
      if (event.pointerType !== 'mouse') return
      if (event.clientY <= 40 || bar.current?.contains(event.target as Node)) show()
      else if (!timer.current) leave()
    }
    const touch = (event: PointerEvent) => {
      if (!window.matchMedia('(hover: none)').matches || event.pointerType !== 'touch' || settings) return
      if (event.clientY <= 40) show()
      else if (!bar.current?.contains(event.target as Node)) setOpen(false)
    }
    window.addEventListener('pointermove', mouse)
    window.addEventListener('pointerdown', touch)
    return () => { cancel(); window.removeEventListener('pointermove', mouse); window.removeEventListener('pointerdown', touch) }
  }, [settings]) // oxlint-disable-line react-hooks/exhaustive-deps
  const settingsQuery = useSettings()
  const customStatuses = settingsQuery.data?.stati_studio as CustomStudyStatus[] | undefined
  const currentStatus = status ?? 'da-imparare'
  const currentDef = resolveStudyStatus(currentStatus, customStatuses)
  return <>
    <div className="rt-zen-hot" data-testid="zen-hot" aria-hidden />
    <div ref={bar} className="rt-zen-bar flex items-center gap-2 bg-background px-3" data-open={open || settings || undefined}
      data-testid="zen-bar" onPointerEnter={event => { if (event.pointerType === 'mouse') show() }} onPointerLeave={leave}
      onFocusCapture={show} onBlurCapture={leave}>
      {onStatus && (
        <IconButton
          label={`Stato: ${currentDef.label} · S`}
          aria-label={`Stato: ${currentDef.label.toLocaleLowerCase('it')}`}
          icon={currentDef.icon}
          className={cn(currentDef.className, 'size-7 min-w-7 [&_svg]:size-4')}
          onClick={onStatus}
          data-testid="zen-status"
        />
      )}
      {onReview && (
        <IconButton
          label="Domande su questa unità · D"
          icon={Brain}
          className="size-7 min-w-7 [&_svg]:size-4"
          onClick={onReview}
          data-testid="zen-unit-questions-btn"
        />
      )}
      {hasAudio && onToggleAudio && (
        <IconButton
          label={audioOpen ? 'Chiudi player audio · P' : 'Player audio · P'}
          icon={Headphones}
          active={audioOpen}
          aria-expanded={audioOpen}
          className="size-7 min-w-7 [&_svg]:size-4"
          onClick={onToggleAudio}
          data-testid="zen-audio-player-btn"
        />
      )}
      <span className="min-w-0 flex-1 truncate text-meta text-muted-foreground">{title}</span>
      <IconButton label="Impostazioni zen" icon={SlidersHorizontal} aria-expanded={settings} onClick={() => onSettings(!settings)} />
      <IconButton label="Esci dalla modalità zen · Z" icon={X} onClick={onExit} />
    </div>
    <Modal open={settings} onClose={() => onSettings(false)} title="Impostazioni zen" testId="zen-settings"
      className="max-md:mb-0 max-md:w-full max-md:rounded-b-none">
      <p className="mb-2 mt-4 text-meta text-muted-foreground">Modalità Irlen</p>
      <div className="flex flex-wrap gap-1" role="group" aria-label="Modalità Irlen">
        {([null, 'pesca', 'menta', 'pergamena'] as const).map(value => <Button key={value ?? 'off'} size="sm"
          variant={irlen === value ? 'outline' : 'ghost'} aria-pressed={irlen === value} onClick={() => {
            if (value !== null && irlen === null && prefs.irlenHighlightWarning && hasNonYellowHighlight) {
              setShowWarning(true)
            }
            onIrlen(value)
          }}>
          {value === null ? 'Spenta' : value === 'pesca' ? 'Pesca' : value === 'menta' ? 'Menta' : 'Pergamena'}
        </Button>)}
      </div>
    </Modal>
    <IrlenWarningModal
      open={showWarning}
      onClose={() => setShowWarning(false)}
      onDismiss={(dontShowAgain) => {
        if (dontShowAgain) setPrefs({ ...prefs, irlenHighlightWarning: false })
      }}
    />
  </>
}
