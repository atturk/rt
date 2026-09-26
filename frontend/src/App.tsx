import { QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { RouterProvider, createBrowserRouter } from 'react-router'

import { createQueryClient } from '@/api/queryClient'
import { routes } from '@/routes'

export function App() {
  const [router] = useState(() => createBrowserRouter(routes))
  const [client] = useState(() =>
    createQueryClient(() => {
      if (window.location.pathname !== '/login') router.navigate('/login', { replace: true })
    }),
  )
  return (
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}
