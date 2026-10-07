import { type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import { cn } from '@/lib/utils'
import { buttonVariants } from './button-variants'
import { Tooltip } from './tooltip'

export type ButtonProps = React.ComponentProps<'button'> & VariantProps<typeof buttonVariants>

export function Button({ className, variant, size, type = 'button', title, ...props }: ButtonProps) {
  if (title) return <Tooltip content={title}>{(trigger) => <button {...trigger} type={type} className={cn(buttonVariants({ variant, size }), className)} {...props} />}</Tooltip>
  return <button type={type} className={cn(buttonVariants({ variant, size }), className)} {...props} />
}
