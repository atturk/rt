import { useState, useId } from 'react'
import {
  ArrowDown,
  ArrowUp,
  Plus,
  Trash2,
} from 'lucide-react'

import { api, unwrap } from '@/api/client'
import { useSavePreferences, type Settings } from '@/api/settings'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import {
  DEFAULT_STATUS_IDS,
  PRESET_COLORS,
  PRESET_ICONS,
  resolveStatusOrder,
  resolveStudyStatus,
  type CustomStudyStatus,
} from '@/components/study/studyProgress'
import { Section } from './common'

export function StudyStatusesSection({ settings }: { settings: Settings }) {
  const savePreferences = useSavePreferences()

  const rawStatuses = (settings.preferences?.stati_studio as CustomStudyStatus[]) ?? []
  const rawOrder = (settings.preferences?.ordine_stati_studio as string[]) ?? []

  const statuses = rawStatuses
  const order = resolveStatusOrder(statuses, rawOrder)

  const [deletePending, setDeletePending] = useState<{ id: string; name: string; count: number } | null>(null)
  const confirmTitleId = useId()

  const persist = (nextStatuses: CustomStudyStatus[], nextOrder: string[]) => {
    savePreferences.mutate({
      ...settings.preferences,
      stati_studio: nextStatuses,
      ordine_stati_studio: nextOrder,
    } as never)
  }

  const move = (index: number, direction: -1 | 1) => {
    const nextIndex = index + direction
    if (nextIndex < 0 || nextIndex >= order.length) return
    const newOrder = [...order]
    const temp = newOrder[index]
    newOrder[index] = newOrder[nextIndex]
    newOrder[nextIndex] = temp
    persist(statuses, newOrder)
  }

  const addStatus = () => {
    const existingNums = statuses
      .map((s) => parseInt(s.id.replace(/\D/g, '') || '0', 10))
      .filter((n) => !isNaN(n))
    const nextNum = existingNums.length > 0 ? Math.max(...existingNums) + 1 : 1
    const newId = `c${nextNum}`
    const newStatus: CustomStudyStatus = {
      id: newId,
      nome: 'Nuovo stato',
      colore: 'text-amber-500',
      icona: 'Star',
    }
    const nextStatuses = [...statuses, newStatus]
    const nextOrder = [...order, newId]
    persist(nextStatuses, nextOrder)
  }

  const updateStatus = (id: string, patch: Partial<CustomStudyStatus>) => {
    const nextStatuses = statuses.map((s) => (s.id === id ? { ...s, ...patch } : s))
    persist(nextStatuses, order)
  }

  const handleDeleteClick = async (status: CustomStudyStatus) => {
    try {
      // Controlla quante unità usano questo stato
      const usageRes = await unwrap(
        api.GET('/api/v1/study/statuses/{status_id}/usage', {
          params: { path: { status_id: status.id } },
        })
      )
      const count = usageRes?.count ?? 0
      if (count > 0) {
        setDeletePending({ id: status.id, name: status.nome, count })
        return
      }
    } catch {
      // In caso di errore procedi direttamente
    }
    executeDelete(status.id)
  }

  const executeDelete = async (id: string) => {
    try {
      await unwrap(
        api.DELETE('/api/v1/study/statuses/{status_id}', {
          params: { path: { status_id: id } },
        })
      )
    } catch {
      // Fallback: aggiorna le preferenze
    }
    const nextStatuses = statuses.filter((s) => s.id !== id)
    const nextOrder = order.filter((sId) => sId !== id)
    persist(nextStatuses, nextOrder)
    setDeletePending(null)
  }

  return (
    <Section
      id="stati-unita"
      title="Stati delle unità"
      description="Personalizza e ordina il ciclo degli stati di studio (tasto S e clic sull'icona)."
    >
      <div className="flex flex-col gap-2" data-testid="study-statuses-list">
        {order.map((id, index) => {
          const isDefault = DEFAULT_STATUS_IDS.includes(id)
          const def = resolveStudyStatus(id, statuses)
          const custom = statuses.find((s) => s.id === id)
          const Icon = def.icon

          return (
            <div
              key={id}
              data-testid={`status-row-${id}`}
              className="flex items-center gap-3 rounded-lg border bg-card p-2.5 text-body"
            >
              <div className="flex items-center gap-1">
                <IconButton
                  label="Sposta su"
                  icon={ArrowUp}
                  disabled={index === 0}
                  onClick={() => move(index, -1)}
                />
                <IconButton
                  label="Sposta giù"
                  icon={ArrowDown}
                  disabled={index === order.length - 1}
                  onClick={() => move(index, 1)}
                />
              </div>

              <div className="flex items-center gap-2">
                <Icon aria-hidden className={`size-5 shrink-0 ${def.className}`} />
              </div>

              {isDefault ? (
                <div className="flex-1 font-medium">{def.label}</div>
              ) : (
                <div className="flex flex-1 flex-wrap items-center gap-2">
                  <Input
                    value={custom?.nome ?? ''}
                    maxLength={24}
                    onChange={(e) => updateStatus(id, { nome: e.target.value })}
                    className="h-8 max-w-[200px] text-body"
                    placeholder="Nome stato"
                    aria-label={`Nome per stato ${custom?.nome}`}
                  />

                  {/* Selettore colore tra i preset */}
                  <select
                    value={custom?.colore}
                    onChange={(e) => updateStatus(id, { colore: e.target.value })}
                    className="h-8 rounded-md border border-input bg-card px-2 text-meta text-foreground"
                    aria-label="Colore dello stato"
                  >
                    {PRESET_COLORS.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.label}
                      </option>
                    ))}
                  </select>

                  {/* Selettore icona tra i preset */}
                  <select
                    value={custom?.icona}
                    onChange={(e) => updateStatus(id, { icona: e.target.value })}
                    className="h-8 rounded-md border border-input bg-card px-2 text-meta text-foreground"
                    aria-label="Icona dello stato"
                  >
                    {Object.keys(PRESET_ICONS).map((iconName) => (
                      <option key={iconName} value={iconName}>
                        {iconName}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {!isDefault && custom && (
                <IconButton
                  label="Elimina stato"
                  icon={Trash2}
                  onClick={() => handleDeleteClick(custom)}
                  aria-label={`Elimina stato ${custom.nome}`}
                />
              )}
            </div>
          )
        })}
      </div>

      <div className="mt-4 flex items-center justify-between">
        <Button variant="outline" size="sm" onClick={addStatus}>
          <Plus className="mr-1.5 size-4" />
          Aggiungi stato
        </Button>
      </div>

      {deletePending && (
        <Modal
          open
          onClose={() => setDeletePending(null)}
          title="Elimina stato"
          testId="confirm-delete-status-modal"
          actions={
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={() => setDeletePending(null)}>
                Annulla
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={() => executeDelete(deletePending.id)}
              >
                Elimina e converti
              </Button>
            </div>
          }
        >
          <div className="p-4 text-body">
            <h3 id={confirmTitleId} className="font-semibold text-danger">
              Stato in uso
            </h3>
            <p className="mt-2 text-muted-foreground">
              Ci sono <strong className="text-foreground">{deletePending.count}</strong> unità con
              lo stato «{deletePending.name}». Eliminandolo, torneranno a «In apprendimento».
              Vuoi continuare?
            </p>
          </div>
        </Modal>
      )}
    </Section>
  )
}
