import { useEffect, useState } from 'react'

import { type Settings, useSaveRewrite } from '@/api/settings'
import { Input } from '@/components/ui/input'
import { SlideToggle } from '@/components/ui/slide-toggle'
import { useCopyFormat } from '@/lib/copyFormat'
import { usePreference } from '@/lib/preferences'
import { useSourceDefaults, type SourceDefault, type SourceKind } from '@/lib/sourceDefaults'
import { ExtractOptions, UseOptions } from '@/components/sources/SourceControls'
import { useRsvpPrefs, type RsvpPreference } from '@/lib/studyPrefs'
import { STUDY_FONTS, studyFontAvailable, studyFontStack, useStudyFont, useStudyTextScale, type StudyFont } from '@/lib/studyText'
import type { ThemePreference } from '@/lib/theme'
import { clampRate } from '@/lib/playbackRate'
import { ZOOM_LEVELS, getZoom, isAppWindow, setZoom } from '@/lib/zoom'
import { SettingsGroup, SettingsMatrix, SettingsRow, SettingsSelect as Select, SettingsSwitch } from './ui'
import { useAutoSave } from './useAutoSave'
import { StudyStatusesSection } from './StudyStatusesSection'
import { useGeneralPreference } from './useGeneralPreference'

export function AppearanceSection({ settings }: { settings: Settings }) {
  const [theme, setTheme] = usePreference<ThemePreference>('theme', 'sistema')
  const [rsvp, setRsvp] = useRsvpPrefs()
  const [copy, setCopy] = useCopyFormat()
  const [rate, setRate] = usePreference('audio.rate', 1)
  const [playerFollowsUnit, setPlayerFollowsUnit] = usePreference('study.player-follows-unit', true)
  const [pdfQr, setPdfQr] = usePreference('pdf.qr-sito', true)
  const [revealSaved, setRevealSaved] = usePreference('file.mostra-salvati', true)
  const [zoom, setZoomState] = useState(getZoom)
  const [textFont, setTextFont] = useStudyFont()
  const [textScale, setTextScale] = useStudyTextScale()
  // Seravek e Avenir ci sono solo sul Mac: si mostrano i font installati, più quello salvato.
  const [availableFonts] = useState(() => new Set(STUDY_FONTS.filter(([v]) => studyFontAvailable(v)).map(([v]) => v)))
  const save = useGeneralPreference()
  const preferences = settings.preferences ?? { modalita_scaletta: 'auto' as const, secondi_approvazione: 10, sfondo_gruppi: 'colori' as const, modalita_arricchimento: 'manuale' as const, chiusura_x: 'background' as const }

  const [wpmEdit, setWpmEdit] = useState<{ base: number; value: number } | null>(null)
  const [pauseEdit, setPauseEdit] = useState<{ base: number; value: number } | null>(null)
  const wpmDraft = wpmEdit && wpmEdit.base === rsvp.wpm ? wpmEdit.value : rsvp.wpm
  const pauseDraft = pauseEdit && pauseEdit.base === rsvp.pauseMs ? pauseEdit.value : rsvp.pauseMs

  const rsvpMutation = {
    mutate: (next: RsvpPreference, opts?: { onSuccess?: () => void; onError?: (e: unknown) => void }) => {
      (setRsvp as (v: RsvpPreference, o?: { onSuccess?: () => void; onError?: (e: unknown) => void }) => void)(next, opts)
    },
  }
  const wpmValid = Number.isFinite(wpmDraft) && wpmDraft >= 100 && wpmDraft <= 900
  const pauseValid = Number.isFinite(pauseDraft) && pauseDraft >= 0 && pauseDraft <= 1200
  const wpmAuto = useAutoSave(rsvpMutation, { ...rsvp, wpm: wpmDraft }, {
    delay: 600,
    enabled: wpmValid,
    initial: rsvp,
    equals: (a, b) => a.wpm === b.wpm,
  })
  const pauseAuto = useAutoSave(rsvpMutation, { ...rsvp, pauseMs: pauseDraft }, {
    delay: 600,
    enabled: pauseValid,
    initial: rsvp,
    equals: (a, b) => a.pauseMs === b.pauseMs,
  })

  const [bgStatus, setBgStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')

  useEffect(() => {
    const onZoomChange = (e: Event) => {
      const z = (e as CustomEvent<{ zoom: number }>).detail?.zoom
      setZoomState(z ?? getZoom())
    }
    window.addEventListener('rt-zoom-change', onZoomChange)
    return () => window.removeEventListener('rt-zoom-change', onZoomChange)
  }, [])

  return <>
    <SettingsGroup id="aspetto" title="Aspetto">
      <SettingsRow
        label="Tema"
        htmlFor="pref-theme"
        control={
          <SlideToggle
            label="Tema"
            value={theme}
            onChange={setTheme}
            options={[{ value: 'sistema', label: 'Sistema' }, { value: 'chiaro', label: 'Chiaro' }, { value: 'scuro', label: 'Scuro' }]}
          />
        }
      />
      <SettingsRow
        label="Sfondo dei gruppi in Lezioni"
        htmlFor="pref-sfondo"
        status={{ status: bgStatus, error: save.error ? 'Salvataggio non riuscito.' : null, retry: () => {} }}
        control={
          <Select
            id="pref-sfondo"
            className="w-full @sm:w-60"
            value={preferences.sfondo_gruppi}
            disabled={save.isPending}
            onChange={(e) => {
              const next = e.target.value as typeof preferences.sfondo_gruppi
              setBgStatus('saving')
              save.mutate({ sfondo_gruppi: next }, {
                onSuccess: () => {
                  setBgStatus('saved')
                  setTimeout(() => setBgStatus(s => s === 'saved' ? 'idle' : s), 1500)
                },
                onError: () => setBgStatus('error'),
              })
            }}
          >
            <option value="colori">Colori</option>
            <option value="grigi">Grigi</option>
            <option value="niente">Niente</option>
          </Select>
        }
      />
      {isAppWindow() && (
        <SettingsRow
          label="Zoom"
          htmlFor="pref-zoom"
          info="Solo su questo dispositivo. Nell'app anche con Cmd + e Cmd − (Ctrl su Windows)."
          control={
            <Select id="pref-zoom" className="w-full @sm:w-28" value={zoom} onChange={(e) => setZoom(Number(e.target.value))}>
              {ZOOM_LEVELS.map(level => (
                <option key={level} value={level}>{Math.round(level * 100)}%</option>
              ))}
            </Select>
          }
        />
      )}
    </SettingsGroup>
    <SettingsGroup id="testo-studio" title="Testo dello Studio">
      <SettingsRow
        label="Font"
        htmlFor="pref-study-font"
        control={
          <div className="flex w-full items-center gap-2 @sm:w-60">
            <Select id="pref-study-font" className="min-w-0 flex-1" value={textFont} onChange={e => setTextFont(e.target.value as StudyFont)}>
              {STUDY_FONTS.filter(([v]) => v === textFont || availableFonts.has(v)).map(([v, label]) => <option key={v} value={v}>{label}</option>)}
            </Select>
            <span aria-hidden="true" className="shrink-0 text-heading" style={{ fontFamily: studyFontStack(textFont) }}>Aa</span>
          </div>
        }
      />
      <SettingsRow
        label="Dimensione"
        htmlFor="pref-study-scale"
        control={
          <Select id="pref-study-scale" className="w-full @sm:w-28" value={textScale.toFixed(1)} onChange={e => setTextScale(Number(e.target.value))}>
            {Array.from({ length: 13 }, (_, i) => (8 + i) / 10).map(n => <option key={n} value={n.toFixed(1)}>{Math.round(n * 100)}%</option>)}
          </Select>
        }
      />
      <SettingsSwitch
        id="pref-study-player-follows-unit"
        label="Il player segue l'unità"
        checked={playerFollowsUnit}
        onChange={setPlayerFollowsUnit}
      />
    </SettingsGroup>
    <StudyStatusesSection settings={settings} />
    <SettingsGroup id="copia" title="Copia" description="Formattazione conservata quando copi dalle lezioni.">
      <SettingsSwitch id="copy-bold" label="Grassetto" checked={copy.bold} onChange={bold => setCopy({ ...copy, bold })} />
      <SettingsSwitch id="copy-italic" label="Corsivo" checked={copy.italic} onChange={italic => setCopy({ ...copy, italic })} />
      <SettingsSwitch id="copy-highlights" label="Evidenziazioni" checked={copy.highlights} onChange={highlights => setCopy({ ...copy, highlights })} />
      <SettingsSwitch id="copy-color" label="Colore del testo" checked={copy.color} onChange={color => setCopy({ ...copy, color })} />
    </SettingsGroup>
    <SettingsGroup id="pdf" title="PDF esportati">
      <SettingsSwitch
        id="pdf-qr-sito"
        label="Logo e QR di RT («Rielaborato con RT») nella prima pagina"
        checked={pdfQr}
        onChange={setPdfQr}
      />
    </SettingsGroup>
    {isAppWindow() && (
      <SettingsGroup id="file-salvati" title="File salvati">
        <SettingsSwitch
          id="file-mostra-salvati"
          label={navigator.platform.includes('Win') ? 'Mostra in Esplora file i file appena salvati' : 'Mostra nel Finder i file appena salvati'}
          checked={revealSaved}
          onChange={setRevealSaved}
        />
      </SettingsGroup>
    )}
    <SettingsGroup id="lettura-veloce" title="Lettura veloce">
      <SettingsRow
        label="Velocità (parole/min)"
        htmlFor="rsvp-wpm"
        status={wpmAuto}
        control={
          <Input
            id="rsvp-wpm"
            type="number"
            min={100}
            max={900}
            step={25}
            className="w-full @sm:w-24"
            value={Number.isFinite(wpmDraft) ? wpmDraft : ''}
            onChange={e => setWpmEdit({ base: rsvp.wpm, value: e.target.valueAsNumber })}
            onBlur={wpmAuto.flush}
          />
        }
      />
      <SettingsRow
        label="Lettera di fuoco"
        htmlFor="rsvp-orp"
        control={
          <Select id="rsvp-orp" className="w-full @sm:w-60" value={rsvp.orp} onChange={e => setRsvp({ ...rsvp, orp: e.target.value as RsvpPreference['orp'] })}>
            <option value="prima">Prima</option>
            <option value="bilanciata">Bilanciata</option>
            <option value="dopo">Dopo</option>
          </Select>
        }
      />
      <SettingsRow
        label="Pausa dopo la frase (ms)"
        htmlFor="rsvp-pause"
        status={pauseAuto}
        control={
          <Input
            id="rsvp-pause"
            type="number"
            min={0}
            max={1200}
            step={50}
            className="w-full @sm:w-24"
            value={Number.isFinite(pauseDraft) ? pauseDraft : ''}
            onChange={e => setPauseEdit({ base: rsvp.pauseMs, value: e.target.valueAsNumber })}
            onBlur={pauseAuto.flush}
          />
        }
      />
      <SettingsSwitch id="rsvp-dyslexic" label="Font per dislessia" checked={rsvp.dyslexic} onChange={dyslexic => setRsvp({ ...rsvp, dyslexic })} />
      <SettingsSwitch id="rsvp-sound" label="Suono a ogni parola" checked={rsvp.sound} onChange={sound => setRsvp({ ...rsvp, sound })} />
    </SettingsGroup>
    <SettingsGroup id="audio" title="Audio">
      <SettingsRow
        label="Velocità di riproduzione"
        htmlFor="pref-audio-rate"
        control={
          <Select id="pref-audio-rate" className="w-full @sm:w-28" value={rate} onChange={e => setRate(clampRate(Number(e.target.value)))}>
            {[...new Set([0.5, 0.75, 1, 1.25, 1.5, 1.75, 2, 2.5, 3, rate])].sort((a, b) => a - b).map(n => <option key={n} value={n}>{String(n).replace('.', ',')}×</option>)}
          </Select>
        }
      />
    </SettingsGroup>
  </>
}

export function OutlineSettingsSection({ settings }: { settings: Settings }) {
  const save = useGeneralPreference()
  const preferences = settings.preferences ?? { modalita_scaletta: 'auto' as const, secondi_approvazione: 10, sfondo_gruppi: 'colori' as const, modalita_arricchimento: 'manuale' as const, chiusura_x: 'background' as const }
  const propMode = preferences.modalita_scaletta ?? 'auto'
  const [draftMode, setDraftMode] = useState<{ prop: string; value: 'auto' | 'timer' | 'manual' } | null>(null)
  const mode = draftMode && draftMode.prop === propMode ? draftMode.value : propMode
  const [modeStatus, setModeStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')

  function selectMode(next: 'auto' | 'timer' | 'manual') {
    setDraftMode({ prop: propMode, value: next })
    setModeStatus('saving')
    save.mutate(
      { modalita_scaletta: next },
      {
        onSuccess: () => {
          setModeStatus('saved')
          setTimeout(() => setModeStatus((s) => (s === 'saved' ? 'idle' : s)), 1500)
        },
        onError: () => setModeStatus('error'),
      },
    )
  }

  return (
    <SettingsGroup id="scaletta" title="Scaletta">
      <SettingsRow
        label="Approvazione della scaletta"
        htmlFor="pref-scaletta-mode"
        info="Scegli se la pipeline procede subito dopo aver preparato la scaletta, aspetta qualche secondo o attende sempre la tua conferma."
        status={{ status: modeStatus, error: save.error ? 'Salvataggio non riuscito.' : null, retry: () => selectMode(mode) }}
        control={
          <Select id="pref-scaletta-mode" className="w-full @sm:w-64" value={mode} disabled={save.isPending} onChange={e => selectMode(e.target.value as 'auto' | 'timer' | 'manual')}>
            <option value="auto">Procedi da sola</option>
            <option value="timer">Attendi qualche secondo</option>
            <option value="manual">Aspetta sempre me</option>
          </Select>
        }
      />
      {mode === 'timer' && <OutlineTimerRow initialSeconds={preferences.secondi_approvazione || 10} save={save} />}
    </SettingsGroup>
  )
}

function OutlineTimerRow({ initialSeconds, save }: { initialSeconds: number; save: ReturnType<typeof useGeneralPreference> }) {
  const [draft, setDraft] = useState<{ base: number; value: number } | null>(null)
  const seconds = draft && draft.base === initialSeconds ? draft.value : initialSeconds
  const valid = Number.isFinite(seconds) && seconds >= 1 && seconds <= 3600
  const autoSave = useAutoSave(save, seconds, {
    delay: 600,
    enabled: valid,
    initial: initialSeconds,
    serialize: (val) => ({ modalita_scaletta: 'timer' as const, secondi_approvazione: val }),
  })
  return (
    <SettingsRow
      label="Approva da sola dopo (secondi)"
      htmlFor="pref-secondi"
      status={autoSave}
      control={
        <Input
          id="pref-secondi"
          type="number"
          required
          min={1}
          max={3600}
          className="w-full @sm:w-24"
          value={Number.isFinite(seconds) ? seconds : ''}
          onChange={e => setDraft({ base: initialSeconds, value: e.target.valueAsNumber })}
          onBlur={autoSave.flush}
        />
      }
    />
  )
}

const SOURCE_ROWS: [SourceKind, string][] = [['slide', 'Slide'], ['testo', 'Documenti'], ['immagine', 'Immagini']]

/** Modalità e uso proposti nell'import per ogni tipo di file; la guida si sceglie lì. */
export function SourceDefaultsSection() {
  const [defaults, setDefaults] = useSourceDefaults()
  const set = (kind: SourceKind, change: Partial<SourceDefault>) => setDefaults({ ...defaults, [kind]: { ...defaults[kind], ...change } })
  return (
    <SettingsGroup
      id="fonti"
      title="Fonti"
      description="Opzioni predefinite proposte quando carichi i file di una lezione. Documenti sono i PDF verticali e i file Word, TXT e MD; per Word, TXT e MD si usa sempre solo il testo, quindi lì conta solo “Come usarla”."
    >
      <SettingsMatrix
        rowHeaderLabel="Tipo di file"
        columnGroups={[
          {
            id: 'extract',
            label: 'Cosa usare',
            columns: [
              { key: 'testo', label: 'Testo' },
              { key: 'immagini', label: 'Pagina' },
              { key: 'solo_immagini', label: 'Immagini' },
            ],
          },
          {
            id: 'use',
            label: 'Come usarla',
            columns: [
              { key: 'guida', label: 'Guida' },
              { key: 'contesto', label: 'Contesto' },
              { key: 'integra', label: 'Integra' },
            ],
          },
        ]}
        rows={SOURCE_ROWS.map(([kind, label]) => ({
          id: kind,
          label,
          testId: `source-default-${kind}`,
          cells: {
            extract: (
              <ExtractOptions
                className="grid w-[9.75rem] grid-cols-3 justify-items-center sm:w-[11.25rem]"
                value={defaults[kind].estrai}
                onChange={estrai => set(kind, { estrai })}
              />
            ),
            use: (
              <UseOptions
                className="grid w-[9.75rem] grid-cols-3 justify-items-center sm:w-[11.25rem]"
                showLabel={false}
                value={defaults[kind].uso}
                off={defaults[kind].estrai === 'solo_immagini' ? 'Solo immagini: nessun testo da usare' : null}
                unavailable={{ guida: 'La guida si sceglie nell’import' }}
                onChange={uso => uso !== 'guida' && set(kind, { uso })}
              />
            ),
          },
        }))}
      />
    </SettingsGroup>
  )
}

export function SpeedSection({ settings }: { settings: Settings }) {
  const saveRewrite = useSaveRewrite()
  const parallel = (settings.rewrite?.context_mode ?? 'macro') === 'macro'
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [error, setError] = useState<string | null>(null)

  function toggle(next: boolean) {
    setStatus('saving')
    setError(null)
    saveRewrite.mutate(
      { context_mode: next ? 'macro' : 'all' },
      {
        onSuccess: () => {
          setStatus('saved')
          setTimeout(() => setStatus((s) => (s === 'saved' ? 'idle' : s)), 1500)
        },
        onError: (err) => {
          setStatus('error')
          setError(err instanceof Error ? err.message : 'Salvataggio non riuscito.')
        },
      },
    )
  }

  return (
    <SettingsGroup id="velocita" title="Velocità">
      <SettingsSwitch
        id="rewrite-parallel"
        testId="toggle-parallel-work"
        label="Lavora in parallelo"
        info="Quando è attivo, RT elabora in parallelo le macro-sezioni della rielaborazione, legge più pagine delle fonti insieme, verifica le unità in parallelo ed esegue più job contemporaneamente. Disattivalo per passare alla rielaborazione sequenziale con tutto il contesto precedente."
        checked={parallel}
        disabled={saveRewrite.isPending}
        onChange={toggle}
        status={{ status, error, retry: () => toggle(parallel) }}
      />
    </SettingsGroup>
  )
}
