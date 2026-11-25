import { createContext, useContext } from 'react'

export const ReturnAddressContext = createContext('/')
export const useReturnAddress = () => useContext(ReturnAddressContext)
export const isUtilityPage = (path: string) => /^\/(impostazioni|bot|job|importa|guida)(\/|$)/.test(path)
export function rememberReturnAddress(previous: string, location: { pathname: string; search: string; hash: string }) {
  return isUtilityPage(location.pathname) ? previous : `${location.pathname}${location.search}${location.hash}`
}

/** Ultima pagina fuori dalla guida (Impostazioni comprese): «Indietro» nella guida torna lì,
 * da qualunque pagina la si apra (menu Aiuto, F1, collegamenti). */
export const GuideReturnContext = createContext('/')
export const useGuideReturnAddress = () => useContext(GuideReturnContext)
export function rememberGuideReturn(previous: string, location: { pathname: string; search: string; hash: string }) {
  return /^\/guida(\/|$)/.test(location.pathname) ? previous : `${location.pathname}${location.search}${location.hash}`
}
