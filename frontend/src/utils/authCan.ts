/** Pure permission checks shared by auth store and unit tests. */

export type AuthUserLike = {
  role?: string
  permissions?: string[] | null
  canWriteChats?: boolean
}

/** Match Pinia auth.can(): admin full access; empty ACL = deny-all. */
export function userCan(user: AuthUserLike | null | undefined, code: string): boolean {
  if (!user) return false
  if (user.role === 'admin') return true
  const perms = user.permissions
  if (!perms?.length) return false
  return perms.includes(code)
}

/**
 * Chat write in UI: role write + presence allows chat write.
 * `canWriteChats === false` locks compose (e.g. status «Обучение»).
 */
export function userCanWriteChats(user: AuthUserLike | null | undefined): boolean {
  return userCan(user, 'action.write') && user?.canWriteChats !== false
}

/** Hydrate should wipe the session only on definitive auth failure. */
export function shouldLogoutOnHydrateError(status: number | undefined | null): boolean {
  return status === 401
}
