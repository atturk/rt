import { LogOut, Menu, Moon, Sun, X } from 'lucide-react'
import { useState } from 'react'
import { Link, NavLink, Navigate, Outlet, useLocation, useNavigate } from 'react-router'

import { ApiError } from '@/api/client'
import { useLogout, useMe } from '@/api/hooks'
import { Sidebar } from '@/components/Sidebar'
import { Button } from '@/components/ui/button'
import { useTheme } from '@/lib/theme'
import { cn } from '@/lib/utils'
import type { Area } from '@/routes/types'

export function Layout({ areas }: { areas: Area[] }) {
  const me = useMe()
  const location = useLocation()
  const navigate = useNavigate()
  const logout = useLogout()
  const [theme, toggleTheme] = useTheme()
  const [menuOpen, setMenuOpen] = useState(false)

  if (me.isError && me.error instanceof ApiError && me.error.status === 401) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  if (me.isPending) {
    return <p className="p-8 text-sm text-muted-foreground">Carico…</p>
  }
  if (me.isError) {
    return (
      <p role="alert" className="p-8 text-sm text-danger">
        {me.error.message}
      </p>
    )
  }

  const nav = areas.flatMap((a) => a.nav ?? [])
  return (
    <div className="flex min-h-dvh">
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-40 w-72 shrink-0 overflow-y-auto border-r bg-sidebar p-4 transition-transform md:sticky md:top-0 md:h-dvh md:translate-x-0',
          menuOpen ? 'translate-x-0 shadow-xl' : '-translate-x-full',
        )}
      >
        <div className="mb-4 flex items-center justify-between md:hidden">
          <span className="text-sm font-semibold">Lezioni</span>
          <Button variant="ghost" size="icon" aria-label="Chiudi il menu" onClick={() => setMenuOpen(false)}>
            <X />
          </Button>
        </div>
        <Sidebar onNavigate={() => setMenuOpen(false)} />
      </aside>
      {menuOpen && <div className="fixed inset-0 z-30 bg-black/25 md:hidden" onClick={() => setMenuOpen(false)} aria-hidden />}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b px-4 py-3 md:px-8">
          <Button variant="ghost" size="icon" className="md:hidden" aria-label="Apri il menu" onClick={() => setMenuOpen(true)}>
            <Menu />
          </Button>
          <Link to="/" className="mr-auto leading-none">
            <span className="text-3xl font-bold tracking-tighter">
              rt<span className="text-success">.</span>
            </span>
            <span className="ml-3 hidden text-xs text-muted-foreground sm:inline">Rielaborazione trascritti e active recall</span>
          </Link>
          <nav aria-label="Navigazione" className="flex items-center gap-1">
            {nav.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                title={label}
                className={({ isActive }) =>
                  cn('inline-flex h-9 items-center gap-2 rounded-md px-3 text-sm hover:bg-muted', isActive && 'bg-muted font-semibold')
                }
              >
                <Icon className="size-4" aria-hidden />
                <span className="hidden lg:inline">{label}</span>
              </NavLink>
            ))}
          </nav>
          <Button
            variant="outline"
            size="icon"
            onClick={toggleTheme}
            aria-label={theme === 'dark' ? 'Tema chiaro' : 'Tema scuro'}
            title={theme === 'dark' ? 'Tema chiaro' : 'Tema scuro'}
          >
            {theme === 'dark' ? <Sun /> : <Moon />}
          </Button>
          <Button
            variant="outline"
            size="icon"
            aria-label="Esci"
            title="Esci"
            disabled={logout.isPending}
            onClick={() => logout.mutate(undefined, { onSettled: () => navigate('/login', { replace: true }) })}
          >
            <LogOut />
          </Button>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 md:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
