import { Archive } from 'lucide-react'
import { useEffect, useState } from 'react'
import { archiveApi, fileSha } from '@/api/archive'
import { Tooltip } from '@/components/ui/tooltip'

export function ArchiveFileBadge({ file }: { file: File }) {
  const [known, setKnown] = useState(false)
  useEffect(() => {
    let current = true
    void fileSha(file)
      .then(async (sha) => {
        const found = (await archiveApi.lookup([sha]))[sha]
        if (current) setKnown(Boolean(found))
      })
      .catch(() => {})
    return () => {
      current = false
    }
  }, [file])
  return known ? <KnownBadge /> : null
}

export function KnownBadge() {
  return (
    <Tooltip content="Già nell'archivio">
      {(trigger) => (
        <span {...trigger} tabIndex={0} className="absolute bottom-1 left-1">
          <Archive className="size-3" aria-label="Già nell'archivio" />
        </span>
      )}
    </Tooltip>
  )
}
