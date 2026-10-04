import { createContext, useContext } from 'react'

/** Apre il popup Nuova lezione (sta nel layout: lo apre il pulsante + della barra e le pagine). */
export const NewLessonContext = createContext<() => void>(() => undefined)

export function useOpenNewLesson() {
  return useContext(NewLessonContext)
}
