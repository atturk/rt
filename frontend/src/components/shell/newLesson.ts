import { createContext, useContext } from 'react'

export type NewLessonOptions = {
  date?: string
  slotKey?: string
  initialFiles?: File[]
}

/** Apre il popup Nuova lezione (sta nel layout: lo apre il pulsante + della barra e le pagine). */
export const NewLessonContext = createContext<(options?: NewLessonOptions | unknown) => void>(() => undefined)

export function useOpenNewLesson() {
  return useContext(NewLessonContext)
}

