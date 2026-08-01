export function shouldShowOsPush(opts: {
  pushEnabled: boolean
  permission: 'granted' | 'denied' | 'default' | 'unsupported' | string
  visibilityState?: 'visible' | 'hidden' | 'prerender' | string
  isActiveDialog?: boolean
  force?: boolean
}): boolean

export function explainOsPushDecision(opts: {
  pushEnabled: boolean
  permission: string
  visibilityState?: string
  isActiveDialog?: boolean
  force?: boolean
}): { show: boolean; reason: string }
