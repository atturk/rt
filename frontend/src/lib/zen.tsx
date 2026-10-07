import { createContext, useContext } from 'react'
import type { RsvpPreference } from './studyPrefs'

export type ZenState = { active: boolean; tint: RsvpPreference['irlen'] }
export const ZenContext = createContext<(state: ZenState) => void>(() => undefined)
export const useZen = () => useContext(ZenContext)
export const IRLEN_COLORS = { pesca: '#f6dcc8', menta: '#d5eee2', pergamena: '#efe4c7' }
