import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from './client'
import { subjectsApi } from './subjects'

describe('subjectsApi (Contratto 4.2.5b2)', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('list: chiama GET /api/v1/subjects', async () => {
    const mockData = [
      { nome: 'Data mining', lezioni: 6 },
      { nome: 'Elettromagnetismo', lezioni: 4 },
    ]
    vi.spyOn(api, 'GET').mockResolvedValue({
      data: mockData,
      error: undefined,
      response: new Response(JSON.stringify(mockData), { status: 200 }),
    } as never)

    const result = await subjectsApi.list()
    expect(result).toEqual(mockData)
    expect(api.GET).toHaveBeenCalledWith('/api/v1/subjects')
  })

  it('create: chiama POST /api/v1/subjects con nome', async () => {
    const newItem = { nome: 'Farmacologia', lezioni: 0 }
    vi.spyOn(api, 'POST').mockResolvedValue({
      data: newItem,
      error: undefined,
      response: new Response(JSON.stringify(newItem), { status: 201 }),
    } as never)

    const result = await subjectsApi.create('Farmacologia')
    expect(result).toEqual(newItem)
    expect(api.POST).toHaveBeenCalledWith('/api/v1/subjects', { body: { nome: 'Farmacologia' } })
  })

  it('delete: chiama DELETE /api/v1/subjects/{nome}', async () => {
    vi.spyOn(api, 'DELETE').mockResolvedValue({
      data: undefined,
      error: undefined,
      response: new Response(null, { status: 204 }),
    } as never)

    await subjectsApi.delete('Farmacologia')
    expect(api.DELETE).toHaveBeenCalledWith('/api/v1/subjects/Farmacologia')
  })
})
