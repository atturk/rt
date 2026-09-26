import { ApiError, csrfMiddleware, toApiError, unwrap } from './client'

function run(method: string) {
  const request = new Request('http://localhost/api/v1/x', { method })
  return (csrfMiddleware.onRequest as (o: { request: Request }) => Request)({ request })
}

describe('csrfMiddleware', () => {
  beforeEach(() => {
    document.cookie = 'rt_csrf=abc%3D; path=/'
  })
  it('aggiunge X-CSRF-Token alle scritture', () => {
    expect(run('POST').headers.get('X-CSRF-Token')).toBe('abc=')
    expect(run('PUT').headers.get('X-CSRF-Token')).toBe('abc=')
  })
  it('non lo aggiunge alle letture', () => {
    expect(run('GET').headers.get('X-CSRF-Token')).toBeNull()
  })
})

describe('errori', () => {
  it('legge il formato uniforme dell\'API', () => {
    const err = toApiError(409, { error: { code: 'lesson_busy', message: 'Job in corso' } })
    expect(err).toBeInstanceOf(ApiError)
    expect([err.status, err.code, err.message]).toEqual([409, 'lesson_busy', 'Job in corso'])
  })
  it('unwrap solleva su risposta non ok', async () => {
    const response = new Response(null, { status: 401 })
    await expect(unwrap(Promise.resolve({ error: { error: { code: 'unauthorized', message: 'No' } }, response }))).rejects.toMatchObject({
      status: 401,
      code: 'unauthorized',
    })
  })
  it('unwrap segnala API non raggiungibile', async () => {
    await expect(unwrap(Promise.reject(new TypeError('fetch failed')))).rejects.toMatchObject({ code: 'network_error' })
  })
})
