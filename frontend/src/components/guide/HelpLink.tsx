import { HelpCircle } from 'lucide-react'
import { Link, useInRouterContext } from 'react-router'
import { Tooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

export function HelpLink({
  to,
  label = 'Guida',
  className,
}: {
  to: string
  label?: string
  className?: string
}) {
  const inRouter = useInRouterContext()

  return (
    <Tooltip content={label}>
      {(trigger) => {
        const classes = cn(
          'inline-flex items-center justify-center rounded-md p-1 text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring',
          className,
        )
        if (inRouter) {
          return (
            <Link
              {...trigger}
              to={to}
              aria-label={label}
              data-testid="help-link"
              className={classes}
            >
              <HelpCircle className="size-3.5" aria-hidden />
            </Link>
          )
        }
        return (
          <a
            {...trigger}
            href={to}
            aria-label={label}
            data-testid="help-link"
            className={classes}
          >
            <HelpCircle className="size-3.5" aria-hidden />
          </a>
        )
      }}
    </Tooltip>
  )
}
