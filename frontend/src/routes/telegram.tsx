import { Bot } from 'lucide-react'

import { TelegramBotPanel } from '@/components/TelegramBotPanel'
import type { Area } from './types'

function TelegramPage() {
  return (
    <section className="flex max-w-2xl flex-col gap-4">
      <h1 className="text-xl font-bold tracking-tight">Bot Telegram</h1>
      <TelegramBotPanel />
    </section>
  )
}

/** Il pannello sta anche nelle impostazioni (RT4-F5); qui ha una pagina propria. */
export const telegramArea: Area = {
  routes: [{ path: 'bot', element: <TelegramPage /> }],
  nav: [{ to: '/bot', label: 'Bot Telegram', icon: Bot }],
}
