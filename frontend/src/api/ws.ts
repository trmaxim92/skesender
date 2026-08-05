import type { ApiDialog, ApiMessage } from '@/api/chats'

export type ChatSocketEvent =
  | { type: 'ping' }
  | { type: 'auth_ok' }
  | { type: 'message.created'; message: ApiMessage; dialog: ApiDialog }
  | { type: 'message.updated'; message: ApiMessage; dialog: ApiDialog }
  | { type: 'message.deleted'; message: ApiMessage; dialog: ApiDialog }
  | { type: 'dialog.updated'; dialog: ApiDialog }
  | {
      type: 'dialog.assigned'
      dialog: ApiDialog
      assigned_by?: { id: number; name: string | null } | null
    }
  | { type: 'dialog.typing'; dialog_id: number; channel_id?: number; department_id?: number | null; user_id?: number | null }

type Handlers = {
  onEvent: (event: ChatSocketEvent) => void
  onStatus?: (status: 'connecting' | 'open' | 'closed') => void
  onAuthFailure?: () => void
}

export class ChatsSocket {
  private ws: WebSocket | null = null
  private closedByUser = false
  private retryMs = 1000
  private retryTimer: number | undefined
  private authFailed = false
  private handlers: Handlers

  constructor(handlers: Handlers) {
    this.handlers = handlers
  }

  connect() {
    this.closedByUser = false
    this.authFailed = false
    this.clearRetry()
    this.open()
  }

  disconnect() {
    this.closedByUser = true
    this.clearRetry()
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
  }

  private clearRetry() {
    if (this.retryTimer !== undefined) {
      window.clearTimeout(this.retryTimer)
      this.retryTimer = undefined
    }
  }

  private open() {
    if (this.closedByUser || this.authFailed) return

    const token = localStorage.getItem('oe_access_token')
    if (!token) {
      this.handlers.onStatus?.('closed')
      return
    }

    if (this.ws) {
      try {
        this.ws.close()
      } catch {
        // ignore
      }
      this.ws = null
    }

    this.handlers.onStatus?.('connecting')
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    // Token is sent in the first frame after connect — not in the URL.
    const url = `${proto}//${window.location.host}/api/ws/chats`
    const ws = new WebSocket(url)
    this.ws = ws

    ws.onopen = () => {
      this.retryMs = 1000
      try {
        ws.send(JSON.stringify({ type: 'auth', token }))
      } catch {
        ws.close()
        return
      }
      this.handlers.onStatus?.('open')
    }

    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(String(ev.data)) as ChatSocketEvent
        if (data && typeof data === 'object' && 'type' in data) {
          if (data.type === 'auth_ok') return
          this.handlers.onEvent(data)
        }
      } catch {
        // ignore malformed frames
      }
    }

    ws.onclose = (ev) => {
      this.handlers.onStatus?.('closed')
      this.ws = null
      // Backend closes invalid tokens; stop hammering reconnect.
      if (ev.code === 1008 || ev.code === 4401 || ev.code === 4001) {
        this.authFailed = true
        this.handlers.onAuthFailure?.()
        return
      }
      if (!this.closedByUser && !this.authFailed) {
        const delay = this.retryMs
        this.retryMs = Math.min(this.retryMs * 2, 15000)
        this.retryTimer = window.setTimeout(() => this.open(), delay)
      }
    }

    ws.onerror = () => {
      ws.close()
    }
  }
}
