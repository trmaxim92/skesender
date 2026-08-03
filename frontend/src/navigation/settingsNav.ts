import type { Component } from 'vue'
import {
  FileText,
  FormInput,
  IdCard,
  Radio,
  CircleDot,
  Webhook,
} from 'lucide-vue-next'
import type { PermissionCode } from '@/types'

export type SettingsNavLeaf = {
  to: string
  label: string
  description: string
  icon: Component
  permission: PermissionCode
}

export type SettingsNavGroup = {
  id: string
  title: string
  description: string
  items: SettingsNavLeaf[]
}

/** Logical settings sections (sidebar + /settings hub). */
export const SETTINGS_NAV_GROUPS: SettingsNavGroup[] = [
  {
    id: 'integrations',
    title: 'Интеграции',
    description: 'Подключение мессенджеров и исходящие события',
    items: [
      {
        to: '/channels',
        label: 'Каналы',
        description: 'Telegram, MAX и другие каналы связи',
        icon: Radio,
        permission: 'section.channels',
      },
      {
        to: '/webhooks',
        label: 'Webhooks',
        description: 'Уведомления во внешние системы',
        icon: Webhook,
        permission: 'section.webhooks',
      },
    ],
  },
  {
    id: 'crm',
    title: 'Обращения и клиенты',
    description: 'Поля карточек и шаблон закрытия',
    items: [
      {
        to: '/settings/appeal-fields',
        label: 'Поля обращения',
        description: 'Дополнительные поля в обращении',
        icon: FormInput,
        permission: 'section.settings',
      },
      {
        to: '/settings/client-fields',
        label: 'Карточка клиента',
        description: 'Поля профиля клиента',
        icon: IdCard,
        permission: 'section.settings',
      },
      {
        to: '/settings/close-template',
        label: 'Закрытие обращения',
        description: 'Системный шаблон при закрытии',
        icon: FileText,
        permission: 'section.settings',
      },
      {
        to: '/settings/presence-statuses',
        label: 'Статусы сотрудников',
        description: 'Присутствие, автораспределение и право писать',
        icon: CircleDot,
        permission: 'section.settings',
      },
    ],
  },
]

export function isSettingsPath(path: string): boolean {
  if (path === '/settings' || path.startsWith('/settings/')) return true
  if (path.startsWith('/channels')) return true
  if (path.startsWith('/webhooks')) return true
  return false
}

export function settingsLeafTitle(path: string): string | null {
  for (const group of SETTINGS_NAV_GROUPS) {
    for (const item of group.items) {
      if (path === item.to || path.startsWith(`${item.to}/`)) return item.label
    }
  }
  if (path === '/settings' || path.startsWith('/settings?')) return 'Настройки'
  return null
}
