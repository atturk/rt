import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from './client'
import { sourcesApi, type SourcesView, type LessonVersion } from './sources'

describe('sourcesApi (Contratto 4.2.5b2)', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('getSources: restituisce vista completa fonti e stato', async () => {
    const mockView: SourcesView = {
      sources: [
        { id: 'src_1', tipo: 'audio', file: 'p1.m4a', impronta: 'imp1', aggiunta_il: '2026-10-12', ordine: 1, nome: 'Parte 1', durata_s: 3600, usata: true },
      ],
      has_unused_sources: false,
      can_undo: false,
      ultimo_aggiornamento: null,
      principale: 'src_1',
      ordine_usato: ['src_1'],
      principale_usato: 'src_1',
      solo_ricostruzione: false,
    }
    vi.spyOn(api, 'GET').mockResolvedValue({
      data: mockView,
      error: undefined,
      response: new Response(JSON.stringify(mockView), { status: 200 }),
    } as never)

    const result = await sourcesApi.getSources(42)
    expect(result).toEqual(mockView)
    expect(api.GET).toHaveBeenCalledWith('/api/v1/lessons/42/sources')
  })

  it('reorder: chiama PUT /sources/order con ids', async () => {
    const updatedView = { solo_ricostruzione: true } as SourcesView
    vi.spyOn(api, 'PUT').mockResolvedValue({
      data: updatedView,
      error: undefined,
      response: new Response(JSON.stringify(updatedView), { status: 200 }),
    } as never)

    const result = await sourcesApi.reorder(42, ['src_2', 'src_1'])
    expect(result).toEqual(updatedView)
    expect(api.PUT).toHaveBeenCalledWith('/api/v1/lessons/42/sources/order', { body: { ids: ['src_2', 'src_1'] } })
  })

  it('setPrimary: chiama PUT /sources/primary con id', async () => {
    const updatedView = { principale: 'src_2', solo_ricostruzione: true } as SourcesView
    vi.spyOn(api, 'PUT').mockResolvedValue({
      data: updatedView,
      error: undefined,
      response: new Response(JSON.stringify(updatedView), { status: 200 }),
    } as never)

    const result = await sourcesApi.setPrimary(42, 'src_2')
    expect(result).toEqual(updatedView)
    expect(api.PUT).toHaveBeenCalledWith('/api/v1/lessons/42/sources/primary', { body: { id: 'src_2' } })
  })

  it('updateLesson: avvia job con mode extend/rebuild', async () => {
    vi.spyOn(api, 'POST').mockResolvedValue({
      data: { job_id: 'job_123' },
      error: undefined,
      response: new Response(JSON.stringify({ job_id: 'job_123' }), { status: 202 }),
    } as never)

    const res = await sourcesApi.updateLesson(42, 'rebuild')
    expect(res).toEqual({ job_id: 'job_123' })
    expect(api.POST).toHaveBeenCalledWith('/api/v1/lessons/42/update', { body: { mode: 'rebuild' } })
  })

  it('undoUpdate: chiama POST /sources/update/undo', async () => {
    vi.spyOn(api, 'POST').mockResolvedValue({
      data: { status: 'update_undone' },
      error: undefined,
      response: new Response(JSON.stringify({ status: 'update_undone' }), { status: 200 }),
    } as never)

    const res = await sourcesApi.undoUpdate(42)
    expect(res).toEqual({ status: 'update_undone' })
    expect(api.POST).toHaveBeenCalledWith('/api/v1/lessons/42/update/undo')
  })

  it('getVersions: legge cronologia versioni', async () => {
    const mockVersions: LessonVersion[] = [
      { id: 'v1', il: '2026-10-12T10:00:00', modo: 'extend', fonti_aggiunte: ['p2.m4a'], unita_nuove: 2, unita_cambiate: 1, attuale: true },
    ]
    vi.spyOn(api, 'GET').mockResolvedValue({
      data: mockVersions,
      error: undefined,
      response: new Response(JSON.stringify(mockVersions), { status: 200 }),
    } as never)

    const res = await sourcesApi.getVersions(42)
    expect(res).toEqual(mockVersions)
    expect(api.GET).toHaveBeenCalledWith('/api/v1/lessons/42/versions')
  })

  it('restoreVersion: chiama POST /versions/{vid}/restore', async () => {
    vi.spyOn(api, 'POST').mockResolvedValue({
      data: { job_id: 'job_restore_1' },
      error: undefined,
      response: new Response(JSON.stringify({ job_id: 'job_restore_1' }), { status: 202 }),
    } as never)

    const res = await sourcesApi.restoreVersion(42, 'v1')
    expect(res).toEqual({ job_id: 'job_restore_1' })
    expect(api.POST).toHaveBeenCalledWith('/api/v1/lessons/42/versions/v1/restore')
  })
})
