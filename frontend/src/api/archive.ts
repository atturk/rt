import { api, unwrap } from './client'

export type SourceOptions = {
  pagine?: string | number[] | null
  estrai?: 'testo' | 'immagini'
  uso?: 'guida' | 'contesto' | 'integra'
}
export type ArchiveUsage = {
  lezione_id: number | null
  titolo: string
  data: string
  pagine: number[] | null
  materia: string
}
export type ArchiveLookup = {
  impronta: string
  pagine_totali: number | null
  usate: ArchiveUsage[]
  da_continuare: string | null
}
export const archiveApi = {
  lookup: (sha: string[]): Promise<Record<string, ArchiveLookup | null>> =>
    unwrap(api.POST('/api/v1/archive/lookup', { body: { sha } })),
}

export async function fileSha(file: File): Promise<string> {
  const data =
    typeof file.arrayBuffer === 'function'
      ? await file.arrayBuffer()
      : await new Promise<ArrayBuffer>((resolve, reject) => {
          const reader = new FileReader()
          reader.onload = () => resolve(reader.result as ArrayBuffer)
          reader.onerror = () => reject(reader.error)
          reader.readAsArrayBuffer(file)
        })
  const digest = await crypto.subtle.digest('SHA-256', data)
  return Array.from(new Uint8Array(digest), (n) => n.toString(16).padStart(2, '0')).join('')
}

export function compressPages(pages: number[]): string {
  const sorted = [...new Set(pages)].sort((a, b) => a - b)
  const runs: string[] = []
  for (let i = 0; i < sorted.length; i++) {
    const first = sorted[i]
    let last = first
    while (sorted[i + 1] === last + 1) last = sorted[++i]
    runs.push(first === last ? String(first) : `${first}–${last}`)
  }
  return runs.join(', ')
}
export const defaultExtraction = (name: string): 'testo' | 'immagini' =>
  /\.(docx|txt)$/i.test(name) ? 'testo' : 'immagini'

export type ArchiveRow = {
  impronta: string
  nome: string
  tipo: string
  pagine_totali: number | null
  durata_s: number | null
  dimensione: number
  materie: string[]
  usi: number
  da_continuare: string | null
}
export type ArchivePage = { numero: number; ignorata: boolean; lezione_id: number | null }
export type ArchiveDetail = ArchiveRow & {
  pagine: ArchivePage[]
  lezioni: { id: number | null; titolo: string; data: string; pagine: number[] | null }[]
  trascrizione_inizio: string
}
export const archiveFilesApi = {
  list: (filters: { materia?: string; tipo?: string; q?: string }): Promise<ArchiveRow[]> =>
    unwrap(api.GET('/api/v1/archive', { params: { query: filters } })),
  detail: (sha: string): Promise<ArchiveDetail> =>
    unwrap(api.GET('/api/v1/archive/{sha}', { params: { path: { sha } } })),
  ignore: (sha: string, pagine: number[], ignorata: boolean) =>
    unwrap(
      api.PUT('/api/v1/archive/{sha}/ignored', { params: { path: { sha } }, body: { pagine, ignorata } }),
    ),
  deletePages: (sha: string, pagine: number[]) =>
    unwrap(api.POST('/api/v1/archive/{sha}/pages/delete', { params: { path: { sha } }, body: { pagine } })),
  crop: (sha: string, n: number, rect: [number, number, number, number], sostituisci: boolean) =>
    unwrap(
      api.POST('/api/v1/archive/{sha}/pages/{n}/crop', {
        params: { path: { sha, n } },
        body: { rect, sostituisci },
      }),
    ),
  delete: (sha: string) => unwrap(api.DELETE('/api/v1/archive/{sha}', { params: { path: { sha } } })),
  addToLesson: (
    sha: string,
    lesson_id: number,
    pagine: number[] | null,
    uso: NonNullable<SourceOptions['uso']>,
    estrai: 'testo' | 'immagini',
  ) =>
    unwrap(
      api.POST('/api/v1/archive/{sha}/add-to-lesson', {
        params: { path: { sha } },
        body: { lesson_id, pagine, uso, estrai },
      }),
    ),
  addToMedia: (sha: string, lesson_id: number, pagine: number[]) =>
    unwrap(
      api.POST('/api/v1/archive/{sha}/add-to-media', {
        params: { path: { sha } },
        body: { lesson_id, pagine },
      }),
    ),
}
