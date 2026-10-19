export type BackupEvent =
  | { inizio: true; tipo?: 'backup' | 'copia' }
  | { fase: 'database' | 'media' | 'config' | 'copia'; fatto: number; totale: number; tipo?: 'backup' | 'copia' }
  | { fine: true; percorso: string; riepilogo?: string[]; avviso_chiave?: string; tipo?: 'backup' | 'copia' }
  | { errore: string; tipo?: 'backup' | 'copia' }

declare global {
  interface Window {
    __rtBackup?: (evento: BackupEvent) => void
    pywebview?: {
      api: {
        salva_copia_backup: (percorsoSnapshot: string) => Promise<{
          avviato?: boolean
          annullato?: boolean
          errore?: string
        }>
      }
    }
  }
}
