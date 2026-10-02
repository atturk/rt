import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './App'
import './index.css'

// Le pagine si caricano a pezzi (routes/index.tsx): dopo un aggiornamento di RT una scheda aperta
// chiede chunk che non esistono più. Si ricarica la pagina una volta (non in loop) per avere
// index.html nuovo.
window.addEventListener('vite:preloadError', (event) => {
  try {
    const last = Number(sessionStorage.getItem('rt-chunk-reload') ?? 0)
    if (Date.now() - last < 10_000) return
    sessionStorage.setItem('rt-chunk-reload', String(Date.now()))
  } catch {
    return
  }
  event.preventDefault()
  window.location.reload()
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
