import { Navigate, Outlet, useLocation } from 'react-router'

import { useSettings } from '@/api/settings'

export const SETUP_PATH = '/impostazioni/configurazione'

/** Se il backend segnala un passo obbligatorio mancante (setup_required) ogni pagina porta alla
 * configurazione guidata (le impostazioni restano raggiungibili). Mentre carica non blocca nulla.
 * Sta fuori da settings.tsx perché avvolge ogni pagina: le impostazioni si caricano a parte. */
export function SetupGate() {
  const settings = useSettings()
  const location = useLocation()
  if (settings.data?.setup_required && !location.pathname.startsWith('/impostazioni')) {
    return <Navigate to={SETUP_PATH} replace />
  }
  return <Outlet />
}
