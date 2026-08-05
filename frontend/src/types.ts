export type Role = 'admin' | 'operator' | 'viewer'

export type PermissionCode =
  | 'section.chats'
  | 'section.appeals'
  | 'section.mailing'
  | 'section.channels'
  | 'section.employees'
  | 'section.templates'
  | 'section.webhooks'
  | 'section.settings'
  | 'action.write'
  | 'action.manage_channels'
  | 'action.manage_users'
  | 'action.delete_appeals'

export type FieldType = 'text' | 'textarea' | 'number' | 'phone' | 'select' | 'date' | 'bool' | 'link'
export type FieldScope = 'client' | 'appeal'

export type ChannelTransport = 'maxbot' | 'max' | 'telegram' | 'tgapi' | 'vk' | 'webchat'

export type ChannelStatus = 'online' | 'connecting' | 'qr_pending' | 'offline' | 'error'

export type MessageStatus = 'sending' | 'sent' | 'delivered' | 'read' | 'failed'

export type AppealStatus = 'open' | 'closed'

export type TemplateKind = 'general' | 'appeal_closed'

export interface User {
  id: number
  name: string
  email: string
  role: Role
  accessRoleId?: number | null
  roleName?: string | null
  permissions: PermissionCode[]
  allChannels: boolean
  channelIds: number[]
  departmentIds: number[]
  isActive?: boolean
  presenceStatusId?: number | null
  presenceStatus?: PresenceStatus | null
  canWriteChats?: boolean
}

export interface PresenceStatus {
  id: number
  name: string
  slug: string
  color: string
  sortOrder: number
  isSystem: boolean
  isActive: boolean
  participatesInRouting: boolean
  canWriteChats: boolean
  onDuty: boolean
}

export interface PresenceEmployee {
  id: number
  name: string
  email: string
  roleName: string | null
  departmentIds: number[]
  isActive: boolean
  presenceStatus: PresenceStatus | null
}

export interface Department {
  id: number
  name: string
  slug: string
  isActive: boolean
  memberIds: number[]
  channelCount: number
  createdAt: string
}

export interface FieldDefinition {
  id: number
  scope: FieldScope
  departmentId: number | null
  key: string
  label: string
  fieldType: FieldType
  options: string[]
  required: boolean
  sortOrder: number
  isSystem: boolean
  isActive: boolean
}

export interface AccessRole {
  id: number
  name: string
  slug: string
  isSystem: boolean
  allChannels: boolean
  permissions: PermissionCode[]
  channelIds: number[]
  createdAt: string
}

export interface PermissionCatalogItem {
  code: PermissionCode
  label: string
}

export interface Channel {
  id: number
  name: string
  transport: ChannelTransport
  status: ChannelStatus
  identity: string
  unread: number
  connectedAt: string | null
  lastError?: string | null
  hasCredentials?: boolean
  departmentId?: number | null
  departmentName?: string | null
  publicKey?: string | null
}

export interface Dialog {
  id: string
  channelId: string
  contactName: string
  contactAvatarUrl?: string | null
  contactPhone: string
  lastMessage: string
  lastAt: string
  lastDirection?: 'in' | 'out' | null
  lastStatus?: MessageStatus | null
  unread: number
  assigneeId: number | null
  transport?: ChannelTransport | null
  appealId?: number | null
  appealNumber?: number | null
  appealStatus?: AppealStatus | null
  departmentId?: number | null
}

export interface Appeal {
  id: number
  dialogId: number
  number: number
  status: AppealStatus
  openedAt: string
  closedAt?: string | null
  closedById?: number | null
  closedByName?: string | null
}

export interface DialogSidebar {
  client: {
    contactName: string
    contactUsername?: string | null
    contactAvatarUrl?: string | null
    contactExternalId?: string | null
    contactPhone?: string | null
    channelId: number
    transport?: ChannelTransport | null
    channelName?: string | null
    dialogCreatedAt: string
    appealsCount: number
    assigneeId?: number | null
    assigneeName?: string | null
    departmentId?: number | null
  }
  currentAppeal: Appeal | null
  appeals: Appeal[]
  clientFields: FieldDefinition[]
  appealFields: FieldDefinition[]
  clientValues: Record<string, string>
  appealValues: Record<string, string>
}

export interface Message {
  id: string
  dialogId: string
  direction: 'in' | 'out'
  text: string
  at: string
  status: MessageStatus
  operatorName?: string
  attachments?: MessageAttachment[]
  replyTo?: ReplyPreview | null
  editedAt?: string | null
  deletedAt?: string | null
  /** Manager-only note; never sent to the client */
  isInternal?: boolean
  appealId?: number | null
  /** Local optimistic bubble not yet confirmed by API */
  pending?: boolean
}

export interface ReplyPreview {
  id: string
  text: string
  direction: 'in' | 'out'
  operatorName?: string | null
}

export interface MessageAttachment {
  id: number
  kind: 'image' | 'video' | 'audio' | 'file'
  fileName: string
  mimeType?: string | null
  sizeBytes?: number | null
  url: string
}

export interface TemplateCategory {
  id: string
  name: string
  sortOrder: number
  updatedAt: string
}

export interface Template {
  id: string
  name: string
  body: string
  transport: ChannelTransport | 'all'
  kind: TemplateKind
  categoryId: string | null
  categoryName: string | null
  hasMedia: boolean
  mediaName: string | null
  isMine: boolean
  updatedAt: string
}

export interface TemplateGroup {
  categoryId: string | null
  categoryName: string
  templates: Template[]
}

export interface WebhookEndpoint {
  id: string
  url: string
  events: string[]
  active: boolean
}

export const transportLabel: Record<ChannelTransport, string> = {
  maxbot: 'MAX · бот',
  max: 'MAX · аккаунт',
  telegram: 'Telegram · бот',
  tgapi: 'Telegram · аккаунт',
  vk: 'ВКонтакте',
  webchat: 'Виджет на сайт',
}

/** Short badge text for lists */
export const transportBadge: Record<ChannelTransport, string> = {
  maxbot: 'MAX',
  max: 'MAX',
  telegram: 'TG',
  tgapi: 'TG',
  vk: 'VK',
  webchat: 'WEB',
}

export const transportBadgeClass: Record<ChannelTransport, string> = {
  maxbot: 'bg-max text-white',
  max: 'bg-max text-white',
  telegram: 'bg-tg text-white',
  tgapi: 'bg-tg text-white',
  vk: 'bg-vk text-white',
  webchat: 'bg-brand text-white',
}

export const roleLabel: Record<Role, string> = {
  admin: 'Админ',
  operator: 'Оператор',
  viewer: 'Просмотр',
}

export const SECTION_BY_PATH: Record<string, PermissionCode> = {
  '/chats': 'section.chats',
  '/appeals': 'section.appeals',
  '/mailing': 'section.mailing',
  '/channels': 'section.channels',
  '/users': 'section.employees',
  '/roles': 'section.employees',
  '/departments': 'section.employees',
  '/employees': 'section.chats',
  '/webhooks': 'section.webhooks',
  '/settings': 'section.settings',
  '/settings/appeal-fields': 'section.settings',
  '/settings/client-fields': 'section.settings',
  '/settings/close-template': 'section.settings',
  '/settings/presence-statuses': 'section.settings',
}

export const FIRST_SECTION_PATHS = [
  '/chats',
  '/appeals',
  '/mailing',
  '/channels',
  '/users',
  '/departments',
  '/webhooks',
  '/settings',
  '/settings/appeal-fields',
  '/settings/close-template',
] as const

export const statusLabel: Record<ChannelStatus, string> = {
  online: 'Онлайн',
  connecting: 'Подключение',
  qr_pending: 'Ожидает QR',
  offline: 'Офлайн',
  error: 'Ошибка',
}

export const messageStatusLabel: Record<MessageStatus, string> = {
  sending: 'Отправляется…',
  sent: 'Отправлено',
  delivered: 'Доставлено',
  read: 'Прочитано',
  failed: 'Ошибка',
}

export const appealStatusLabel: Record<AppealStatus, string> = {
  open: 'Открыто',
  closed: 'Закрыто',
}

export const templateKindLabel: Record<TemplateKind, string> = {
  general: 'Обычный',
  appeal_closed: 'Закрытие обращения',
}

/** Индикатор набора текста собеседником (не статус сообщения в БД). */
export const typingLabel = 'печатает…'
