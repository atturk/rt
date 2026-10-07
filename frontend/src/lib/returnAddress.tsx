import { createContext, useContext } from 'react'

export const ReturnAddressContext = createContext('/')
export const useReturnAddress = () => useContext(ReturnAddressContext)
export const isUtilityPage = (path: string) => /^\/(impostazioni|bot|job|importa)(\/|$)/.test(path)
export function rememberReturnAddress(previous: string, location: { pathname: string; search: string; hash: string }) {
  return isUtilityPage(location.pathname) ? previous : `${location.pathname}${location.search}${location.hash}`
}
