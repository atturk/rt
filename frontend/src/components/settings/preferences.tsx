import { useEffect, useState, type FormEvent } from 'react'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, unwrap } from '@/api/client'
import { type Settings } from '@/api/settings'
import { Button } from '@/components/ui/button'
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
import { ZOOM_LEVELS, getZoom, resetZoom, setZoom } from '@/lib/zoom'
import { Checkbox, Field, SaveFeedback, Section, SettingsSelect as Select } from './common'

/** Salva solo il controllo cambiato, rileggendo i valori generali per non ripristinare la modalità. */
function useGeneralPreference() {
  const client = useQueryClient()
  return useMutation({
    scope: { id: 'general-preferences' },
    mutationFn: async (change: Partial<NonNullable<Settings['preferences']>>) => {
      const latest = await unwrap(api.GET('/api/v1/settings'))
      return unwrap(api.PUT('/api/v1/settings/preferences', { body: {
        secondi_approvazione: 10, sfondo_gruppi: 'colori', modalita_arricchimento: 'manuale', ...latest.preferences, ...change,
      } }))
    },
    onSuccess: settings => { client.setQueryData(['settings'], settings) },
  })
}

export function AppearanceSection({ settings }: { settings: Settings }) {
  const [theme, setTheme] = usePreference<ThemePreference>('theme', 'sistema')
  const [rsvp, setRsvp] = useRsvpPrefs()
  const [copy, setCopy] = useCopyFormat()
  const [rate, setRate] = usePreference('audio.rate', 1)
  const [zoom, setZoomState] = useState(getZoom)
  const [textFont, setTextFont] = useStudyFont()
  const [textScale, setTextScale] = useStudyTextScale()
  // Seravek e Avenir ci sono solo sul Mac: si mostrano i font installati, più quello salvato.
  const [availableFonts] = useState(() => new Set(STUDY_FONTS.filter(([v]) => studyFontAvailable(v)).map(([v]) => v)))
  const save = useGeneralPreference()
  const preferences = settings.preferences ?? { secondi_approvazione: 10, sfondo_gruppi: 'colori' as const, modalita_arricchimento: 'manuale' as const }

  useEffect(() => {
    const onZoomChange = (e: Event) => {
      const z = (e as CustomEvent<{ zoom: number }>).detail?.zoom
      setZoomState(z ?? getZoom())
    }
    window.addEventListener('rt-zoom-change', onZoomChange)
    return () => window.removeEventListener('rt-zoom-change', onZoomChange)
  }, [])

  return <>
    <Section id="aspetto" title="Aspetto">
      <Field label="Tema" htmlFor="pref-theme"><SlideToggle label="Tema" value={theme} onChange={setTheme}
        options={[{ value: 'sistema', label: 'Sistema' }, { value: 'chiaro', label: 'Chiaro' }, { value: 'scuro', label: 'Scuro' }]} /></Field>
      <Field label="Sfondo dei gruppi in Lezioni" htmlFor="pref-sfondo">
        <Select id="pref-sfondo" value={preferences.sfondo_gruppi} disabled={save.isPending} onChange={e => save.mutate({ sfondo_gruppi: e.target.value as typeof preferences.sfondo_gruppi })}>
          <option value="colori">Colori</option><option value="grigi">Grigi</option><option value="niente">Niente</option>
        </Select>
      </Field>
      <Field label="Zoom" htmlFor="pref-zoom" hint="Solo su questo dispositivo. Nell'app anche con Cmd + e Cmd − (Ctrl su Windows).">
        <div className="flex items-center gap-2">
          <Select id="pref-zoom" value={zoom} onChange={e => setZoom(Number(e.target.value))}>
            {ZOOM_LEVELS.map(level => (
              <option key={level} value={level}>{Math.round(level * 100)}%</option>
            ))}
          </Select>
          <Button type="button" variant="outline" size="sm" onClick={resetZoom} disabled={zoom === 1}>
            100%
          </Button>
        </div>
      </Field>
      <SaveFeedback mutation={save} />
    </Section>
    <Section id="testo-studio" title="Testo dello Studio">
      <Field label="Font" htmlFor="pref-study-font">
        <div className="flex items-center gap-2">
          <Select id="pref-study-font" value={textFont} onChange={e => setTextFont(e.target.value as StudyFont)}>
            {STUDY_FONTS.filter(([v]) => v === textFont || availableFonts.has(v)).map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </Select>
          <span aria-hidden="true" className="text-heading" style={{ fontFamily: studyFontStack(textFont) }}>Aa</span>
        </div>
      </Field>
      <Field label="Dimensione" htmlFor="pref-study-scale">
        <Select id="pref-study-scale" value={textScale.toFixed(1)} onChange={e => setTextScale(Number(e.target.value))}>
          {Array.from({ length: 13 }, (_, i) => (8 + i) / 10).map(n => <option key={n} value={n.toFixed(1)}>{Math.round(n * 100)}%</option>)}
        </Select>
      </Field>
    </Section>
    <Section id="copia" title="Copia">
      <Checkbox id="copy-bold" label="Grassetto" checked={copy.bold} onChange={bold => setCopy({ ...copy, bold })} />
      <Checkbox id="copy-italic" label="Corsivo" checked={copy.italic} onChange={italic => setCopy({ ...copy, italic })} />
      <Checkbox id="copy-highlights" label="Evidenziazioni" checked={copy.highlights} onChange={highlights => setCopy({ ...copy, highlights })} />
      <Checkbox id="copy-color" label="Colore del testo" checked={copy.color} onChange={color => setCopy({ ...copy, color })} />
    </Section>
    <Section id="lettura-veloce" title="Lettura veloce">
      <Field label="Velocità (parole/min)" htmlFor="rsvp-wpm"><Input id="rsvp-wpm" type="number" min={100} max={900} step={25} value={rsvp.wpm}
        onChange={e => { const n = e.target.valueAsNumber; if (Number.isFinite(n) && n >= 100 && n <= 900) setRsvp({ ...rsvp, wpm: n }) }} /></Field>
      <Field label="Lettera di fuoco" htmlFor="rsvp-orp"><Select id="rsvp-orp" value={rsvp.orp} onChange={e => setRsvp({ ...rsvp, orp: e.target.value as RsvpPreference['orp'] })}>
        <option value="prima">Prima</option><option value="bilanciata">Bilanciata</option><option value="dopo">Dopo</option>
      </Select></Field>
      <Field label="Pausa dopo la frase (ms)" htmlFor="rsvp-pause"><Input id="rsvp-pause" type="number" min={0} max={1200} step={50} value={rsvp.pauseMs}
        onChange={e => { const n = e.target.valueAsNumber; if (Number.isFinite(n) && n >= 0 && n <= 1200) setRsvp({ ...rsvp, pauseMs: n }) }} /></Field>
      <Checkbox id="rsvp-dyslexic" label="Font per dislessia" checked={rsvp.dyslexic} onChange={dyslexic => setRsvp({ ...rsvp, dyslexic })} />
      <Checkbox id="rsvp-sound" label="Suono a ogni parola" checked={rsvp.sound} onChange={sound => setRsvp({ ...rsvp, sound })} />
    </Section>
    <Section id="audio" title="Audio"><Field label="Velocità di riproduzione" htmlFor="pref-audio-rate">
      <Select id="pref-audio-rate" value={rate} onChange={e => setRate(clampRate(Number(e.target.value)))}>
        {[...new Set([0.5, 0.75, 1, 1.25, 1.5, 1.75, 2, 2.5, 3, rate])].sort((a, b) => a - b).map(n => <option key={n} value={n}>{String(n).replace('.', ',')}×</option>)}
      </Select>
    </Field></Section>
  </>
}

export function OutlineSettingsSection({ settings }: { settings: Settings }) {
  const save = useGeneralPreference()
  const preferences = settings.preferences ?? { secondi_approvazione: 10, sfondo_gruppi: 'colori' as const, modalita_arricchimento: 'manuale' as const }
  const [seconds, setSeconds] = useState(preferences.secondi_approvazione)
  function submit(e: FormEvent) { e.preventDefault(); save.mutate({ secondi_approvazione: seconds }) }
  return <Section id="scaletta" title="Scaletta"><form onSubmit={submit}>
    <Field label="Approva da sola dopo (secondi)" htmlFor="pref-secondi" hint="0 = aspetta sempre te">
      <Input id="pref-secondi" type="number" required min={0} max={3600} value={seconds} onChange={e => setSeconds(e.target.valueAsNumber)} />
    </Field>
    <Button type="submit" disabled={save.isPending}>Salva scaletta</Button>
  </form><SaveFeedback mutation={save} /></Section>
}

const SOURCE_ROWS: [SourceKind, string][] = [['slide', 'Slide'], ['testo', 'Testi'], ['immagine', 'Immagini']]

/** Modalità e uso proposti nell'import per ogni tipo di file; la guida si sceglie lì. */
export function SourceDefaultsSection() {
  const [defaults, setDefaults] = useSourceDefaults()
  const set = (kind: SourceKind, change: Partial<SourceDefault>) => setDefaults({ ...defaults, [kind]: { ...defaults[kind], ...change } })
  return <Section id="fonti" title="Fonti">
    {SOURCE_ROWS.map(([kind, label]) => <div key={kind} className="flex flex-wrap items-center gap-3 text-body" data-testid={`source-default-${kind}`}>
      <span className="w-20">{label}</span>
      <ExtractOptions value={defaults[kind].estrai} onChange={estrai => set(kind, { estrai })} />
      <UseOptions value={defaults[kind].uso} off={defaults[kind].estrai === 'solo_immagini' ? 'Solo immagini: nessun testo da usare' : null}
        unavailable={{ guida: 'La guida si sceglie nell’import' }} onChange={uso => uso !== 'guida' && set(kind, { uso })} />
    </div>)}
  </Section>
}
