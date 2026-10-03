import { useParams, useSearchParams } from 'react-router'

import { errorMessage } from '@/api/client'
import { useLesson } from '@/api/hooks'
import { StudyFlow } from '@/components/study/Study'
import { PageHeader } from '@/components/shell/PageHeader'
import { Button } from '@/components/ui/button'
import type { Lesson } from '@/lib/format'

/** Studio di una lezione (dalla riga di Lezioni e dall'intestazione della lezione); con ?unita= le domande di una parte. */
export function StudyLessonPage() {
  const id = Number(useParams().lessonId)
  const [params] = useSearchParams()
  const lesson = useLesson(id)
  const only = params.get('unita')?.split(',').map((u) => u.trim()).filter(Boolean) ?? null
  const back = only ? { to: `/lezioni/${id}`, label: 'Esci' } : { to: '/', label: 'Esci' }
  if (lesson.isError) return <Failure back={back} error={lesson.error} retry={() => void lesson.refetch()} />
  if (!lesson.data) return <Loading back={back} />
  const ready = lesson.data.phases.rewrite === 'VALID'
  // La chiave riparte da capo se cambia la parte (un altro "Domande su questa parte").
  return <StudyFlow key={`${id}:${only?.join(',') ?? ''}`} lessons={ready ? [lesson.data as Lesson] : []} onlyUnits={only?.length ? only : null} back={back} />
}

function Loading({ back }: { back: { to: string; label: string } }) {
  return (
    <>
      <PageHeader title="Studio" muted titleAs="h1" back={back} />
      <div className="mx-auto w-full max-w-(--reading-width) px-4 pt-6" aria-busy="true" role="status" aria-label="Carico lo Studio">
        {[40, 100, 90, 70].map((w) => <div key={w} className="my-3 h-2.5 rounded-md bg-muted" style={{ width: `${w}%` }} />)}
      </div>
    </>
  )
}

function Failure({ back, error, retry }: { back: { to: string; label: string }; error: unknown; retry: () => void }) {
  return (
    <>
      <PageHeader title="Studio" muted titleAs="h1" back={back} />
      <p role="alert" className="mx-auto flex w-full max-w-(--reading-width) items-center gap-3 px-4 pt-6 text-body">
        <span className="text-danger">{errorMessage(error)}</span>
        <Button variant="outline" size="sm" onClick={retry}>Riprova</Button>
      </p>
    </>
  )
}
