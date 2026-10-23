let lastClosedLessonId: number | null = null

export function setLastClosedLessonId(id: number | null) {
  lastClosedLessonId = id
}

export function getLastClosedLessonId(): number | null {
  return lastClosedLessonId
}

export function consumeLastClosedLessonId(): number | null {
  const id = lastClosedLessonId
  lastClosedLessonId = null
  return id
}

export function clearLastClosedLessonId() {
  lastClosedLessonId = null
}
