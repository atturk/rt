export type BackupEvent =
  | { inizio: true; tipo?: 'backup' | 'copia' | 'esporta' | 'importa' }
  | { fase: 'database' | 'media' | 'config' | 'copia'; fatto: number; totale: number; tipo?: 'backup' | 'copia' | 'esporta' | 'importa' }
  | { fine: true; percorso: string; riepilogo?: string[]; avviso_chiave?: string; tipo?: 'backup' | 'copia' | 'esporta' | 'importa' }
  | { errore: string; tipo?: 'backup' | 'copia' | 'esporta' | 'importa' }

export type OpenedFileItem = { token: string; name: string; size: number }

declare global {
  interface Window {
    __rtBackup?: (evento: BackupEvent) => void
    rtOpenedFiles?: (items: OpenedFileItem[]) => void
    pywebview?: {
      api: {
        salva_copia_backup: (percorsoSnapshot: string) => Promise<{
          avviato?: boolean
          annullato?: boolean
          errore?: string
        }>
        mostra_esportazione?: () => Promise<void> | void
        riavvia_dopo_importazione?: () => Promise<void> | void
        apri_aggiornamento?: () => Promise<void> | void
        badge?: (count: number) => Promise<void> | void
        notifica?: (titolo: string, testo: string, percorso?: string | null) => Promise<void> | void
        file_in_attesa?: () => Promise<OpenedFileItem[]> | OpenedFileItem[]
      }
    }
  }
}
