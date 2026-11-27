import { lazy, Suspense, useState } from 'react'
import { Link } from 'react-router'
import { PencilLine } from 'lucide-react'
import { buttonVariants } from '@/components/ui/button-variants'
import { IconButton } from '@/components/ui/icon-button'
import { hasLessonConflict, hasMissingModelError, missingModelPath, type Job } from '@/lib/jobs'

const NewLessonDialog = lazy(() => import('@/components/lessons/NewLessonDialog').then(m => ({ default: m.NewLessonDialog })))

export function LessonConflictAction({ job }: { job: Job }) {
  const [open, setOpen] = useState(false)
  if (job.state !== 'failed' || !hasLessonConflict(job)) return null
  return <>
    <IconButton label="Cambia i dati" icon={PencilLine} onClick={() => setOpen(true)} />
    {open && <Suspense fallback={null}><NewLessonDialog open onClose={() => setOpen(false)} initialJob={job} /></Suspense>}
  </>
}

export function MissingModelAction({ job }: { job: Pick<Job, 'state' | 'result' | 'error' | 'error_message'> }) {
  if (!hasMissingModelError(job)) return null
  return (
    <Link to={missingModelPath(job)} className={buttonVariants({ variant: 'outline', size: 'sm' })} data-testid="missing-model-link">
      Impostazioni › Modelli
    </Link>
  )
}
