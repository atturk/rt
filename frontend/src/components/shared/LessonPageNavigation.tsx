import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { useLessons } from '@/api/hooks'
import { detectSwipe, isElementScrollableX } from '@/components/study/swipe'
import type { Lesson } from '@/lib/format'
import { lessonNeighbors } from '@/lib/lessonNeighbors'
import { useLessonJump } from '@/lib/useLessonJump'
import { LessonJumpButtons, LessonJumpTab } from './LessonJump'

import { lessonArrowAllowed } from '@/lib/lessonNavigationKeys'

export function LessonPageNavigation({ id, panel, title, children }: { id: number; panel: string | null; title: ReactNode; children: ReactNode }) {
  const all = useLessons()
  const navigate = useNavigate()
  const navigation = useLessonJump()
  const show = navigation.show
  const neighbors = lessonNeighbors((all.data ?? []) as Lesson[], id, { readyOnly: false })
  const titleRef = useRef<HTMLDivElement>(null)
  const [titleVisible, setTitleVisible] = useState(true)
  const [hover, setHover] = useState(false)
  const [touch, setTouch] = useState(false)
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const swipe = useRef<{ x: number; y: number; time: number; pointer: number } | null>(null)
  useEffect(() => {
    if (!titleRef.current || !globalThis.IntersectionObserver) return
    const observer = new IntersectionObserver(([entry]) => setTitleVisible(entry.isIntersecting), { rootMargin: '-52px 0px 0px 0px' })
    observer.observe(titleRef.current)
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    const media = window.matchMedia?.('(hover: none)')
    if (!media) return
    const change = () => setTouch(media.matches)
    change()
    media.addEventListener('change', change)
    return () => media.removeEventListener('change', change)
  }, [])
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (!lessonArrowAllowed(event)) return
      event.preventDefault()
      show(event.key === 'ArrowLeft' ? 'left' : 'right')
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [show])
  useEffect(() => () => { if (hoverTimer.current) clearTimeout(hoverTimer.current) }, [])
  useEffect(() => {
    navigation.close()
    window.scrollTo({ top: 0 })
  }, [id]) // oxlint-disable-line react-hooks/exhaustive-deps
  const enter = () => {
    if (hoverTimer.current) clearTimeout(hoverTimer.current)
    setHover(true)
    navigation.pause()
  }
  const leave = () => {
    hoverTimer.current = setTimeout(() => setHover(false), 150)
    navigation.resume()
  }
  const jump = (lesson: Lesson) => {
    navigation.close()
    setHover(false)
    navigate(`/lezioni/${lesson.id}${panel ? `?panel=${encodeURIComponent(panel)}` : ''}`)
    window.scrollTo({ top: 0 })
  }
  const floating = touch || !titleVisible
  return <article className="mx-auto w-full max-w-(--reading-width) pb-28 pt-7 max-md:pt-3" data-testid="lesson-page"
    onTouchStart={event => {
      swipe.current = null
      const point = event.touches[0]
      if (event.touches.length !== 1 || !point || point.clientX <= 25 || window.getSelection()?.toString() || isElementScrollableX(event.target as Element, event.currentTarget)) return
      swipe.current = { x: point.clientX, y: point.clientY, time: Date.now(), pointer: point.identifier }
    }}
    onTouchCancel={() => { swipe.current = null }}
    onTouchEnd={event => {
      const start = swipe.current
      swipe.current = null
      const point = Array.from(event.changedTouches).find(touch => touch.identifier === start?.pointer)
      if (!start || !point) return
      const direction = detectSwipe({ startX: start.x, startY: start.y, startTime: start.time, endX: point.clientX, endY: point.clientY, endTime: Date.now() }, { hasSelection: !!window.getSelection()?.toString() })
      if (direction) navigation.show(direction === 'next' ? 'right' : 'left')
    }}>
    <div ref={titleRef} className="relative" data-testid="lesson-title-box" tabIndex={-1}
      onPointerDown={event => { if (!(event.target as Element).closest('button, a')) event.currentTarget.focus({ preventScroll: true }) }}>
      {title}
      {!floating && (['left', 'right'] as const).map(side => <div key={side}
        className={`absolute top-0 hidden h-full min-h-24 w-[76px] [@media(hover:hover)]:block ${side === 'left' ? 'right-full' : 'left-full'}`}
        data-testid={`lesson-jump-zone-${side}`} onMouseEnter={enter} onMouseLeave={leave}>
        <div className={hover || navigation.jump?.side === side ? '' : 'invisible'}>
          <LessonJumpButtons neighbors={neighbors} side={side} onJump={jump} dim={hover} sequence={navigation.jump?.side === side ? navigation.jump.sequence : undefined} paused={navigation.paused} />
        </div>
      </div>)}
    </div>
    {floating && navigation.jump && <LessonJumpTab neighbors={neighbors} side={navigation.jump.side} onJump={jump}
      sequence={navigation.jump.sequence} paused={navigation.paused} onPause={navigation.pause} onResume={navigation.resume} />}
    {children}
  </article>
}
