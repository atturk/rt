import { useState } from 'react'
import { usePreference } from '@/lib/preferences'
import { Switch } from '@/components/ui/switch'
import { Alert } from '@/components/ui/alert'
import { CalendarScheduleSettings } from './CalendarScheduleSettings'

export function CalendarSettingsSection() {
  const [enabled, setEnabled] = usePreference('calendar.missingWarning', true)
  const [error, setError] = useState<string | null>(null)
  return <div className="flex flex-col gap-5">
    <label className="flex items-center justify-between gap-3 text-body">Avviso lezioni mancanti<Switch label="Avviso lezioni mancanti" checked={enabled} onChange={setEnabled} /></label>
    <CalendarScheduleSettings onError={setError} />
    {error && <Alert tone="danger">{error}</Alert>}
  </div>
}
