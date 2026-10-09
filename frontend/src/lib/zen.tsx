import { createContext, useContext, useState, type Dispatch, type SetStateAction } from 'react'
import type { RsvpPreference } from './studyPrefs'

export type RsvpLayoutState = { active: boolean; tint: RsvpPreference['irlen'] }
export const RsvpLayoutContext = createContext<(state: RsvpLayoutState) => void>(() => undefined)
export const useRsvpLayout = () => useContext(RsvpLayoutContext)
export const IRLEN_COLORS = { pesca: '#f6dcc8', menta: '#d5eee2', pergamena: '#efe4c7' }

export const ZenContext = createContext<(state: RsvpLayoutState) => void>(() => undefined)
export const useZenLayout = () => useContext(ZenContext)

/** La modalità vive sopra la route: cambiare lezione non equivale a uscire dalla zen. */
export const StudyZenContext = createContext<[boolean, Dispatch<SetStateAction<boolean>>] | null>(null)
export function useStudyZen(initial = false): [boolean, Dispatch<SetStateAction<boolean>>] {
  const local = useState(initial)
  return useContext(StudyZenContext) ?? local
}
