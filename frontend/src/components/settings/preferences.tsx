import { useState, type FormEvent } from 'react'

import { useSavePreferences, type Settings } from '@/api/settings'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Field, SaveFeedback, Section } from './common'

export function PreferencesSection({ settings }: { settings: Settings }) {
  const save = useSavePreferences()
  const p = settings.preferences ?? {
    secondi_approvazione: 10,
    sfondo_gruppi: 'colori',
    modalita_arricchimento: 'manuale',
  }

  const [secondi, setSecondi] = useState(p.secondi_approvazione)
  const [sfondo, setSfondo] = useState(p.sfondo_gruppi)
  const [arricchimento, setArricchimento] = useState(p.modalita_arricchimento)

  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate({
      secondi_approvazione: Number(secondi),
      sfondo_gruppi: sfondo,
      modalita_arricchimento: arricchimento,
    })
  }

  return (
    <Section id="preferenze" title="Preferenze">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Field label="Secondi approvazione scaletta" htmlFor="pref-secondi">
          <Input
            id="pref-secondi"
            type="number"
            min={0}
            max={3600}
            value={secondi}
            disabled={save.isPending}
            onChange={(e) => setSecondi(Number(e.target.value))}
            className="max-w-[200px]"
          />
        </Field>

        <Field label="Sfondo dei gruppi in Lezioni" htmlFor="pref-sfondo">
          <Select
            id="pref-sfondo"
            value={sfondo}
            disabled={save.isPending}
            onChange={(e) => setSfondo(e.target.value as 'colori' | 'grigi' | 'niente')}
            className="max-w-[200px]"
          >
            <option value="colori">Colori</option>
            <option value="grigi">Grigi</option>
            <option value="niente">Niente</option>
          </Select>
        </Field>

        <Field label="Modalità dell'arricchimento" htmlFor="pref-arricchimento">
          <Select
            id="pref-arricchimento"
            value={arricchimento}
            disabled={save.isPending}
            onChange={(e) => setArricchimento(e.target.value as 'manuale' | 'automatica' | 'disattivata')}
            className="max-w-[200px]"
          >
            <option value="manuale">Manuale</option>
            <option value="automatica">Automatica</option>
            <option value="disattivata">Disattivata</option>
          </Select>
        </Field>

        <div>
          <Button type="submit" disabled={save.isPending}>
            Salva preferenze
          </Button>
        </div>
      </form>
      <SaveFeedback mutation={save} />
    </Section>
  )
}
