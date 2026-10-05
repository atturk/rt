import { useState, type FormEvent } from 'react'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, unwrap } from '@/api/client'
import { type Settings } from '@/api/settings'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SlideToggle } from '@/components/ui/slide-toggle'
import { usePreference } from '@/lib/preferences'
import type { ThemePreference } from '@/lib/theme'
import { clampRate } from '@/lib/playbackRate'
import { Checkbox, Field, SaveFeedback, Section, SettingsSelect as Select } from './common'

// Forma concordata con studyPrefs.ts: Claude collega il lettore alle preferenze al merge.
export type RsvpPreference = {
  wpm: number; orp: 'prima' | 'bilanciata' | 'dopo'; pauseMs: number; comma: boolean
  step: number; size: number; sound: boolean; pitch: number; dyslexic: boolean
  irlen: null | 'pesca' | 'menta' | 'pergamena'; noise: null | 'bianco' | 'rosa' | 'marrone'; noiseVolume: number
}
const RSVP_DEFAULT: RsvpPreference = { wpm: 300, orp: 'bilanciata', pauseMs: 400, comma: false,
  step: 5, size: 60, sound: true, pitch: 1, dyslexic: false, irlen: null, noise: null, noiseVolume: 0.25 }

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
  const [highlighter, setHighlighter] = usePreference('study.highlighter', { color: 0, arrows: true })
  const [rsvp, setRsvp] = usePreference<RsvpPreference>('study.rsvp', RSVP_DEFAULT)
  const [rate, setRate] = usePreference('audio.rate', 1)
  const save = useGeneralPreference()
  const preferences = settings.preferences ?? { secondi_approvazione: 10, sfondo_gruppi: 'colori' as const, modalita_arricchimento: 'manuale' as const }
  return <>
    <Section id="aspetto" title="Aspetto">
      <Field label="Tema" htmlFor="pref-theme"><SlideToggle label="Tema" value={theme} onChange={setTheme}
        options={[{ value: 'sistema', label: 'Sistema' }, { value: 'chiaro', label: 'Chiaro' }, { value: 'scuro', label: 'Scuro' }]} /></Field>
      <Field label="Sfondo dei gruppi in Lezioni" htmlFor="pref-sfondo">
        <Select id="pref-sfondo" value={preferences.sfondo_gruppi} disabled={save.isPending} onChange={e => save.mutate({ sfondo_gruppi: e.target.value as typeof preferences.sfondo_gruppi })}>
          <option value="colori">Colori</option><option value="grigi">Grigi</option><option value="niente">Niente</option>
        </Select>
      </Field>
      <SaveFeedback mutation={save} />
    </Section>
    <Section id="studio" title="Studio">
      <div className="flex flex-wrap justify-between gap-2 text-body"><span>Colori dell’evidenziatore</span><span className="text-muted-foreground">Giallo, verde, azzurro, rosa, arancio</span></div>
      <Checkbox id="pref-arrows" label="Frecce per cambiare unità" checked={highlighter.arrows} onChange={arrows => setHighlighter({ ...highlighter, arrows })} />
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
