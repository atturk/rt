// Only the study API is reachable from this entry point; credentials stay in memory.
let token = null
const base = (import.meta.env.VITE_RT_MINI_API_URL || '').replace(/\/$/, '')
export class StudyError extends Error {
  constructor(message, code, status) { super(message); this.code = code; this.status = status }
}
export async function request(path, { method = 'GET', body, blob = false } = {}) {
  const headers = new Headers()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (body && !(body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
    body = JSON.stringify(body)
  }
  if (!token && method !== 'GET') {
    const csrf = document.cookie.split(';').map(v => v.trim()).find(v => v.startsWith('rt_csrf='))
    if (csrf) headers.set('X-CSRF-Token', decodeURIComponent(csrf.slice(8)))
  }
  let response
  try { response = await fetch(`${base}/api/v1/mini-app${path}`, { method, body, headers, credentials: base ? 'omit' : 'same-origin' }) }
  catch { throw new StudyError('RT non è raggiungibile. Controlla che sia avviato e riprova.', 'network_error', 0) }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new StudyError(data.error?.message || 'Operazione non riuscita.', data.error?.code, response.status)
  }
  return blob ? response.blob() : response.json()
}
export async function authenticate() {
  const auth = await request('/auth', { method: 'POST', body: { init_data: window.Telegram?.WebApp?.initData || '' } })
  token = auth.token
}
export async function waitJob(accepted, onProgress = () => {}) {
  const deadline = Date.now() + 10 * 60 * 1000
  while (Date.now() < deadline) {
    const job = await request(`/jobs/${encodeURIComponent(accepted.job_id)}`)
    onProgress(job)
    if (job.state === 'succeeded') return job.result
    if (['failed', 'cancelled', 'waiting_for_decision'].includes(job.state)) throw new StudyError(job.error || 'Operazione interrotta.', 'job_failed', 409)
    if (job.state === 'queued' && job.worker_available === false) throw new StudyError('Operazione accodata. Avvia il worker di RT, poi premi Riprova.', 'worker_offline', 503)
    await new Promise(resolve => setTimeout(resolve, 1000))
  }
  throw new StudyError('L’operazione continua in RT. Riprova più tardi.', 'job_timeout', 408)
}
export function lessonPath(id, suffix = '') { return `/lessons/${encodeURIComponent(id)}${suffix}` }
