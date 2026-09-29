import {
  Building2,
  Car,
  FileText,
  Gift,
  Heart,
  LogIn,
  MessageCircle,
  Package,
  Phone,
  Star,
  Tag,
  UserPlus,
  Wallet,
  Wrench,
  type LucideIcon,
} from 'lucide-vue-next'

export type TemplateCategoryIconKey =
  | 'gift'
  | 'tag'
  | 'login'
  | 'user-plus'
  | 'message'
  | 'wallet'
  | 'wrench'
  | 'package'
  | 'building'
  | 'star'
  | 'file'
  | 'heart'
  | 'phone'
  | 'car'

export const TEMPLATE_CATEGORY_ICONS: {
  key: TemplateCategoryIconKey
  label: string
  icon: LucideIcon
}[] = [
  { key: 'gift', label: 'Акции', icon: Gift },
  { key: 'tag', label: 'Тег', icon: Tag },
  { key: 'login', label: 'Вход', icon: LogIn },
  { key: 'user-plus', label: 'Регистрация', icon: UserPlus },
  { key: 'message', label: 'Поддержка', icon: MessageCircle },
  { key: 'wallet', label: 'Финансы', icon: Wallet },
  { key: 'wrench', label: 'Техника', icon: Wrench },
  { key: 'package', label: 'Заказы', icon: Package },
  { key: 'building', label: 'Парк', icon: Building2 },
  { key: 'star', label: 'Избранное', icon: Star },
  { key: 'file', label: 'Документ', icon: FileText },
  { key: 'heart', label: 'Лояльность', icon: Heart },
  { key: 'phone', label: 'Связь', icon: Phone },
  { key: 'car', label: 'Авто', icon: Car },
]

const BY_KEY = Object.fromEntries(
  TEMPLATE_CATEGORY_ICONS.map((i) => [i.key, i.icon]),
) as Record<TemplateCategoryIconKey, LucideIcon>

const NAME_RULES: { match: RegExp; key: TemplateCategoryIconKey }[] = [
  { match: /акци|бонус|предлож/i, key: 'gift' },
  { match: /вход|логин|профиль/i, key: 'login' },
  { match: /регистр/i, key: 'user-plus' },
  { match: /поддерж|help|помощь/i, key: 'message' },
  { match: /финанс|оплат|вывод|комисс|платеж/i, key: 'wallet' },
  { match: /техн|ошибк|сбой/i, key: 'wrench' },
  { match: /заказ|доставк/i, key: 'package' },
  { match: /парк|fleet/i, key: 'building' },
  { match: /мои|личн/i, key: 'star' },
  { match: /друг/i, key: 'tag' },
]

export function resolveCategoryIcon(
  icon: string | null | undefined,
  categoryName?: string | null,
): LucideIcon {
  if (icon && icon in BY_KEY) return BY_KEY[icon as TemplateCategoryIconKey]
  const name = categoryName || ''
  for (const rule of NAME_RULES) {
    if (rule.match.test(name)) return BY_KEY[rule.key]
  }
  return FileText
}

export function isTemplateCategoryIconKey(value: string): value is TemplateCategoryIconKey {
  return value in BY_KEY
}
