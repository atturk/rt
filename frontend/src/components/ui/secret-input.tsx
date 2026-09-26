import * as React from 'react'

import { cn } from '@/lib/utils'
import { Input } from './input'

/** Campo per chiavi API e token. Non è type="password": Safari e il portachiavi di iCloud
 * ignorano autoComplete="off" sui campi password e propongono una password salvata. Qui il
 * testo è mascherato via CSS (-webkit-text-security) e i gestori di password più diffusi
 * (1Password, LastPass, Bitwarden, Dashlane) sono esclusi con i loro attributi. Id e name non
 * contengono "password", perché anche quello attiva i suggerimenti. */
export function SecretInput({ className, name, id, ...props }: Omit<React.ComponentProps<'input'>, 'type'>) {
  return (
    <Input
      {...props}
      id={id}
      name={name ?? id}
      type="text"
      autoComplete="off"
      autoCorrect="off"
      autoCapitalize="off"
      spellCheck={false}
      data-secret=""
      data-1p-ignore=""
      data-lpignore="true"
      data-bwignore=""
      data-form-type="other"
      className={cn('secret-mask', className)}
    />
  )
}
