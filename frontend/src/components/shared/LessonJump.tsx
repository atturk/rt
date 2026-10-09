import { ArrowLeft, ArrowRight, Calendar, Tag } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { IconButton } from '@/components/ui/icon-button'
import { lessonTitle, type Lesson } from '@/lib/format'
import type { LessonNeighbors } from '@/lib/lessonNeighbors'

import type { JumpSide } from '@/lib/useLessonJump'

export function LessonJumpButtons({ neighbors, side, onJump, sequence, paused = false, dim = false }: {
  neighbors: LessonNeighbors; side: JumpSide; onJump: (lesson: Lesson, side: JumpSide) => void
  sequence?: number; paused?: boolean; dim?: boolean
}) {
  const progress = useRef<HTMLSpanElement>(null)
  const animationRef = useRef<Animation | null>(null)
  useEffect(() => {
    if (sequence === undefined || !progress.current?.animate) return
    const animation = progress.current.animate([{ transform: 'scaleY(1)' }, { transform: 'scaleY(0)' }], { duration: 5000, fill: 'forwards' })
    animationRef.current = animation
    return () => { animation.cancel(); animationRef.current = null }
  }, [sequence])
  useEffect(() => {
    if (paused) animationRef.current?.pause()
    else animationRef.current?.play()
  }, [paused, sequence])
  const direction = side === 'left' ? 'prev' : 'next'
  const Arrow = side === 'left' ? ArrowLeft : ArrowRight
  return <div className="relative flex flex-col gap-1 p-1" data-testid={`lesson-jump-buttons-${side}`}>
    {([{ key: 'sameDay', Icon: Calendar, group: 'giorno' }, { key: 'sameSubject', Icon: Tag, group: 'materia' }] as const).map(({ key, Icon, group }) => {
      const target = neighbors[key][direction]
      const label = `Lezione ${side === 'left' ? 'prima' : 'dopo'} ${group === 'giorno' ? 'dello stesso giorno' : 'della stessa materia'}`
      return <IconButton key={key} icon={Icon} label={target ? `${label}: ${lessonTitle(target)}` : label}
        unavailable={target ? null : `nessuna lezione ${side === 'left' ? 'prima' : 'dopo'} ${group === 'giorno' ? 'dello stesso giorno' : 'della stessa materia'}`}
        onClick={() => { if (target) onJump(target, side) }} badge={<Arrow aria-hidden />}
        className={`w-16 gap-1 [&_svg]:size-4 ${side === 'left' ? 'flex-row-reverse' : ''} ${dim ? 'opacity-40 hover:opacity-100 focus-visible:opacity-100' : ''}`}
        data-testid={`lesson-jump-${side}-${key}`} />
    })}
    {sequence !== undefined && <span className={`absolute inset-y-1 w-0.5 overflow-hidden rounded bg-muted ${side === 'left' ? 'right-0' : 'left-0'}`} aria-hidden>
      <span ref={progress} className="block h-full w-full origin-top bg-study-learned" />
    </span>}
  </div>
}

export function LessonJumpTab({ side, onPause, onResume, ...buttons }: Parameters<typeof LessonJumpButtons>[0] & { onPause: () => void; onResume: () => void }) {
  return <div className={`fixed top-1/2 z-40 -translate-y-1/2 rounded-lg border bg-card shadow-panel ${side === 'left' ? 'left-[env(safe-area-inset-left)] rounded-l-none' : 'right-[env(safe-area-inset-right)] rounded-r-none'}`}
    data-testid={`lesson-jump-tab-${side}`} onMouseEnter={onPause} onMouseLeave={onResume} onFocusCapture={onPause} onBlurCapture={onResume}>
    <LessonJumpButtons {...buttons} side={side} />
  </div>
}
