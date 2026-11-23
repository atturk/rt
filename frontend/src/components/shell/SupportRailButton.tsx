import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Heart } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router'

import { api, unwrap } from '@/api/client'
import { Tooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

const SUPPORT_PROMPT_QUERY_KEY = ['support-prompt'] as const
const CLICK_MAX_MS = 350
// oxlint-disable-next-line react/only-export-components -- Costante usata dai test.
export const HOLD_MS = 900

export type Point = { x: number; y: number }
export type ShatterPiece = {
  vertices: [Point, Point, Point]
  cx: number
  cy: number
}

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value))
}

/**
 * Divide il quadrato unitario [0, 1]² in una griglia n×n con vertici interni spostati
 * casualmente (±jitter della cella) e ogni cella divisa in 2 triangoli (2n² frammenti).
 */
// oxlint-disable-next-line react/only-export-components -- Funzione pura esportata per i test.
export function shatterPieces(
  n = 4,
  jitter = 0.28,
  rand: () => number = Math.random,
): ShatterPiece[] {
  const cell = 1 / n
  const grid: Point[][] = []
  for (let i = 0; i <= n; i += 1) {
    const row: Point[] = []
    for (let j = 0; j <= n; j += 1) {
      const internal = i > 0 && i < n && j > 0 && j < n
      const dx = internal ? (rand() * 2 - 1) * jitter * cell : 0
      const dy = internal ? (rand() * 2 - 1) * jitter * cell : 0
      row.push({
        x: clamp01(j * cell + dx),
        y: clamp01(i * cell + dy),
      })
    }
    grid.push(row)
  }

  const pieces: ShatterPiece[] = []
  for (let r = 0; r < n; r += 1) {
    for (let c = 0; c < n; c += 1) {
      const tl = grid[r][c]
      const tr = grid[r][c + 1]
      const bl = grid[r + 1][c]
      const br = grid[r + 1][c + 1]
      const tris: [Point, Point, Point][] = rand() < 0.5
        ? [[tl, tr, br], [tl, br, bl]]
        : [[tl, tr, bl], [tr, br, bl]]
      for (const vertices of tris) {
        const cx = (vertices[0].x + vertices[1].x + vertices[2].x) / 3
        const cy = (vertices[0].y + vertices[1].y + vertices[2].y) / 3
        pieces.push({ vertices, cx, cy })
      }
    }
  }
  return pieces
}

type ShatterOrigin = {
  rect: { left: number; top: number; width: number; height: number }
  floorY: number
}

function ShatterOverlay({
  origin,
  onDone,
}: {
  origin: ShatterOrigin
  onDone: () => void
}) {
  const reducedMotion = typeof window !== 'undefined'
    && Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)
  const pieces = useMemo(
    () => (reducedMotion ? [] : shatterPieces(4, 0.28)),
    [reducedMotion],
  )
  const fragmentRefs = useRef<(HTMLDivElement | null)[]>([])
  const reducedRef = useRef<HTMLDivElement | null>(null)
  const onDoneRef = useRef(onDone)
  useEffect(() => {
    onDoneRef.current = onDone
  }, [onDone])

  useEffect(() => {
    if (reducedMotion) {
      let start: number | null = null
      let rafId = 0
      const step = (now: number) => {
        if (start === null) start = now
        const elapsed = now - start
        const opacity = Math.max(0, 1 - elapsed / 200)
        if (reducedRef.current) reducedRef.current.style.opacity = String(opacity)
        if (elapsed >= 200) {
          onDoneRef.current()
          return
        }
        rafId = requestAnimationFrame(step)
      }
      rafId = requestAnimationFrame(step)
      return () => cancelAnimationFrame(rafId)
    }

    const bodies = pieces.map((piece) => ({
      cx: piece.cx,
      vx: (piece.cx - 0.5) * (1.2 + Math.random() * 1.6),
      vy: -(0.6 + Math.random() * 1.4) * (1 - piece.cy * 0.6),
      vr: (Math.random() * 2 - 1) * 7,
      x: 0,
      y: 0,
      rot: 0,
      cy: piece.cy,
    }))

    let start: number | null = null
    let last: number | null = null
    let rafId = 0
    const FADE_DELAY_MS = 650
    const FADE_DURATION_MS = 550
    const TOTAL_MS = FADE_DELAY_MS + FADE_DURATION_MS

    const step = (now: number) => {
      if (start === null) {
        start = now
        last = now
      }
      const dt = Math.min((now - (last ?? now)) / 16.667, 2)
      last = now
      const elapsed = now - start

      for (let i = 0; i < bodies.length; i += 1) {
        const b = bodies[i]
        const el = fragmentRefs.current[i]
        if (!el) continue
        b.vy += 0.32 * dt
        b.x += b.vx * dt
        b.y += b.vy * dt
        b.rot += b.vr * dt

        const floorLimit = origin.floorY - (origin.rect.top + b.cy * origin.rect.height)
        if (b.y >= floorLimit) {
          b.y = floorLimit
          b.vy = -Math.abs(b.vy) * 0.25
          b.vx *= 0.8
          b.vr *= 0.6
        }

        el.style.transform = `translate3d(${b.x}px, ${b.y}px, 0) rotate(${b.rot}deg)`
        if (elapsed > FADE_DELAY_MS) {
          el.style.opacity = String(Math.max(0, 1 - (elapsed - FADE_DELAY_MS) / FADE_DURATION_MS))
        }
      }

      if (elapsed >= TOTAL_MS) {
        onDoneRef.current()
        return
      }
      rafId = requestAnimationFrame(step)
    }

    rafId = requestAnimationFrame(step)
    return () => cancelAnimationFrame(rafId)
  }, [origin, pieces, reducedMotion])

  return createPortal(
    <div
      data-testid="support-shatter-overlay"
      aria-hidden
      className="pointer-events-none fixed inset-0 z-60"
    >
      {reducedMotion ? (
        <div
          ref={reducedRef}
          className="fixed flex items-center justify-center rounded-[9px] bg-blue-600 text-white"
          style={{
            left: origin.rect.left,
            top: origin.rect.top,
            width: origin.rect.width,
            height: origin.rect.height,
          }}
        >
          <Heart className="size-[18px] fill-current" aria-hidden />
        </div>
      ) : (
        pieces.map((piece, idx) => {
          const [v0, v1, v2] = piece.vertices
          return (
            <div
              key={idx}
              ref={(el) => {
                fragmentRefs.current[idx] = el
              }}
              className="fixed bg-blue-600"
              style={{
                left: origin.rect.left,
                top: origin.rect.top,
                width: origin.rect.width,
                height: origin.rect.height,
                clipPath: `polygon(${v0.x * 100}% ${v0.y * 100}%, ${v1.x * 100}% ${v1.y * 100}%, ${v2.x * 100}% ${v2.y * 100}%)`,
                transformOrigin: `${piece.cx * 100}% ${piece.cy * 100}%`,
              }}
            />
          )
        })
      )}
    </div>,
    document.body,
  )
}

export function SupportRailButton() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const buttonRef = useRef<HTMLButtonElement | null>(null)
  const holdTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const pressStartRef = useRef<number | null>(null)
  const handledRef = useRef(false)
  const [pressing, setPressing] = useState(false)
  const [shatter, setShatter] = useState<ShatterOrigin | null>(null)

  const prompt = useQuery({
    queryKey: SUPPORT_PROMPT_QUERY_KEY,
    queryFn: () => unwrap(api.GET('/api/v1/system/support-prompt')),
    staleTime: 60 * 60 * 1000,
    refetchOnWindowFocus: true,
    retry: false,
  })

  const hidePromptCache = useCallback(() => {
    queryClient.setQueryData(SUPPORT_PROMPT_QUERY_KEY, (old: { visible?: boolean; url?: string } | undefined) => ({
      url: old?.url ?? '',
      visible: false,
    }))
  }, [queryClient])

  const cancelPress = useCallback(() => {
    clearTimeout(holdTimerRef.current)
    holdTimerRef.current = undefined
    pressStartRef.current = null
    setPressing(false)
  }, [])

  useEffect(() => () => clearTimeout(holdTimerRef.current), [])

  const triggerOpen = useCallback(() => {
    cancelPress()
    hidePromptCache()
    void api.POST('/api/v1/system/support-prompt', { body: { event: 'opened' } }).catch(() => {})
    void navigate('/impostazioni/supporta')
  }, [cancelPress, hidePromptCache, navigate])

  const triggerHide = useCallback(() => {
    cancelPress()
    const btn = buttonRef.current
    const rect = btn?.getBoundingClientRect() ?? { left: 10, top: 200, width: 36, height: 36 }
    const navRect = btn?.closest('nav')?.getBoundingClientRect()
    const floorY = navRect && navRect.height > 0 ? navRect.bottom : window.innerHeight
    setShatter({
      rect: {
        left: rect.left,
        top: rect.top,
        width: rect.width || 36,
        height: rect.height || 36,
      },
      floorY,
    })
    hidePromptCache()
    void api.POST('/api/v1/system/support-prompt', { body: { event: 'hidden' } }).catch(() => {})
  }, [cancelPress, hidePromptCache])

  const startHold = useCallback(() => {
    clearTimeout(holdTimerRef.current)
    handledRef.current = false
    pressStartRef.current = Date.now()
    setPressing(true)
    holdTimerRef.current = setTimeout(() => {
      handledRef.current = true
      triggerHide()
    }, HOLD_MS)
  }, [triggerHide])

  const visible = Boolean(prompt.data?.visible)
  if (!visible && !shatter) return null

  return (
    <>
      {visible && (
        <Tooltip
          side="right"
          describe={false}
          content={
            <>
              <div>Clic per donare</div>
              <div>Clic a lungo per nascondere</div>
            </>
          }
        >
          {(trigger) => (
            <button
              ref={(el) => {
                buttonRef.current = el
                trigger.ref(el)
              }}
              type="button"
              data-testid="support-rail-button"
              aria-label="Supporta RT. Clic per donare, clic a lungo per nascondere"
              onMouseEnter={trigger.onMouseEnter}
              onMouseLeave={trigger.onMouseLeave}
              onFocus={trigger.onFocus}
              onBlur={() => {
                trigger.onBlur()
                cancelPress()
              }}
              onContextMenu={(e) => e.preventDefault()}
              onPointerDown={(e) => {
                if (e.pointerType === 'mouse' && e.button !== 0) return
                trigger.onPointerDown()
                try {
                  e.currentTarget.setPointerCapture(e.pointerId)
                } catch {
                  // jsdom / ambientazione senza pointer capture
                }
                startHold()
              }}
              onPointerUp={(e) => {
                try {
                  if (e.currentTarget.hasPointerCapture?.(e.pointerId)) {
                    e.currentTarget.releasePointerCapture(e.pointerId)
                  }
                } catch {
                  // ignore
                }
                // Il gesto col puntatore decide da sé: il click sintetico che segue non deve
                // aprire la pagina dopo un rilascio tra 350 e 900 ms o una pressione annullata.
                const start = pressStartRef.current
                const alreadyHandled = handledRef.current
                handledRef.current = true
                cancelPress()
                if (!alreadyHandled && start !== null && Date.now() - start <= CLICK_MAX_MS) triggerOpen()
              }}
              onPointerCancel={(e) => {
                try {
                  if (e.currentTarget.hasPointerCapture?.(e.pointerId)) {
                    e.currentTarget.releasePointerCapture(e.pointerId)
                  }
                } catch {
                  // ignore
                }
                cancelPress()
              }}
              onPointerLeave={() => {
                if (pressStartRef.current !== null) cancelPress()
              }}
              onKeyDown={(e) => {
                trigger.onKeyDown(e)
                if (e.key === 'Enter') {
                  e.preventDefault()
                  handledRef.current = true
                  triggerOpen()
                } else if (e.key === ' ') {
                  e.preventDefault()
                  if (!e.repeat && pressStartRef.current === null) {
                    startHold()
                  }
                }
              }}
              onKeyUp={(e) => {
                if (e.key === ' ') {
                  e.preventDefault()
                  if (!handledRef.current) cancelPress()
                }
              }}
              onClick={() => {
                // Fallback per attivazioni sintetiche senza pointerDown/Enter (es. screen reader)
                if (!handledRef.current) {
                  triggerOpen()
                }
                handledRef.current = false
              }}
              style={{
                touchAction: 'none',
                userSelect: 'none',
                transform: pressing ? 'scale(0.94)' : undefined,
                transition: 'transform 150ms ease-out',
              }}
              className={cn(
                'rt-support-enter relative inline-flex size-9 shrink-0 cursor-pointer items-center justify-center overflow-hidden rounded-[9px]',
                'bg-blue-600 text-white shadow-sm hover:bg-blue-700',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2 focus-visible:ring-offset-background',
              )}
            >
              <span
                aria-hidden
                className="pointer-events-none absolute inset-0 rounded-[9px]"
                style={{
                  background: 'radial-gradient(circle, rgba(255,255,255,0.42) 0%, rgba(255,255,255,0.38) 60%, rgba(255,255,255,0) 100%)',
                  transform: pressing ? 'scale(1.5)' : 'scale(0)',
                  opacity: pressing ? 1 : 0,
                  transition: pressing
                    ? `transform ${HOLD_MS}ms linear, opacity 120ms ease-out`
                    : 'transform 200ms ease-out, opacity 200ms ease-out',
                }}
              />
              <Heart className="relative z-10 size-[18px] shrink-0 fill-current" aria-hidden />
            </button>
          )}
        </Tooltip>
      )}
      {shatter && (
        <ShatterOverlay
          origin={shatter}
          onDone={() => setShatter(null)}
        />
      )}
    </>
  )
}
