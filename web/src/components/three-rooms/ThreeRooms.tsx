import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

interface ThreeRoomsProps {
  board: ReactNode
  queue: ReactNode
  chat: ReactNode
}

/** Board / Queue / Chat — the standard anatomy of every workspace. */
export function ThreeRooms({ board, queue, chat }: ThreeRoomsProps) {
  const { t } = useTranslation()

  return (
    <Tabs defaultValue="board" className="gap-4">
      <TabsList>
        <TabsTrigger value="board">{t('rooms.board')}</TabsTrigger>
        <TabsTrigger value="queue">{t('rooms.queue')}</TabsTrigger>
        <TabsTrigger value="chat">{t('rooms.chat')}</TabsTrigger>
      </TabsList>
      <TabsContent value="board">{board}</TabsContent>
      <TabsContent value="queue">{queue}</TabsContent>
      <TabsContent value="chat">{chat}</TabsContent>
    </Tabs>
  )
}
