/* SkySender website chat widget */
;(function () {
  'use strict'

  var script =
    document.currentScript ||
    (function () {
      var list = document.getElementsByTagName('script')
      return list[list.length - 1]
    })()
  var publicKey = (script && script.getAttribute('data-key')) || ''
  if (!publicKey) {
    console.warn('[SkySender widget] data-key is required')
    return
  }

  var apiBase = (function () {
    try {
      return new URL(script.src).origin
    } catch (e) {
      return window.location.origin
    }
  })()

  var STORAGE_VISITOR = 'skysender_wc_vid_' + publicKey
  var STORAGE_TOKEN = 'skysender_wc_tok_' + publicKey

  var state = {
    open: false,
    online: true,
    channelName: 'Чат',
    visitorId: localStorage.getItem(STORAGE_VISITOR) || '',
    token: localStorage.getItem(STORAGE_TOKEN) || '',
    dialogId: null,
    messages: [],
    sending: false,
    ws: null,
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag)
    if (cls) node.className = cls
    if (text != null) node.textContent = text
    return node
  }

  function api(path, opts) {
    opts = opts || {}
    var headers = opts.headers || {}
    headers['Content-Type'] = 'application/json'
    if (state.token) headers.Authorization = 'Bearer ' + state.token
    return fetch(apiBase + path, {
      method: opts.method || 'GET',
      headers: headers,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    }).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) {
          var err = new Error((data && data.detail) || res.statusText || 'error')
          err.status = res.status
          throw err
        }
        return data
      })
    })
  }

  function ensureSession() {
    return api('/api/widget/session', {
      method: 'POST',
      body: {
        public_key: publicKey,
        visitor_id: state.visitorId || null,
        contact_name: 'Посетитель сайта',
      },
    }).then(function (data) {
      state.token = data.visitor_token
      state.visitorId = data.visitor_id
      state.dialogId = data.dialog_id
      state.channelName = data.channel_name || 'Чат'
      state.online = !!data.channel_online
      localStorage.setItem(STORAGE_VISITOR, state.visitorId)
      localStorage.setItem(STORAGE_TOKEN, state.token)
      titleEl.textContent = state.channelName
      setOfflineUI(!state.online)
      return data
    })
  }

  function loadMessages() {
    return api('/api/widget/messages').then(function (list) {
      state.messages = Array.isArray(list) ? list : []
      renderMessages()
    })
  }

  function connectWs() {
    if (state.ws) {
      try {
        state.ws.close()
      } catch (e) {}
      state.ws = null
    }
    if (!state.token) return
    var wsUrl = apiBase.replace(/^http/, 'ws') + '/api/widget/ws'
    var ws = new WebSocket(wsUrl)
    state.ws = ws
    ws.onopen = function () {
      ws.send(JSON.stringify({ type: 'auth', token: state.token }))
    }
    ws.onmessage = function (ev) {
      try {
        var data = JSON.parse(ev.data)
      } catch (e) {
        return
      }
      if (!data || !data.type) return
      if (data.type === 'message' && data.message) {
        upsertMessage(data.message)
      } else if (data.type === 'message_edited' && data.external_id) {
        state.messages.forEach(function (m) {
          if (m.external_id === data.external_id) m.text = data.text || m.text
        })
        renderMessages()
      } else if (data.type === 'message_deleted' && data.external_id) {
        state.messages = state.messages.filter(function (m) {
          return m.external_id !== data.external_id
        })
        renderMessages()
      }
    }
    ws.onclose = function () {
      if (state.open) {
        setTimeout(connectWs, 3000)
      }
    }
  }

  function upsertMessage(msg) {
    var key = msg.external_id || String(msg.id)
    var found = false
    state.messages.forEach(function (m, i) {
      var mk = m.external_id || String(m.id)
      if (mk === key) {
        state.messages[i] = Object.assign({}, m, msg)
        found = true
      }
    })
    if (!found) state.messages.push(msg)
    renderMessages()
  }

  function renderMessages() {
    listEl.innerHTML = ''
    if (!state.messages.length) {
      listEl.appendChild(el('div', 'ss-wc-empty', 'Напишите нам — ответим в этом окне'))
      return
    }
    state.messages.forEach(function (m) {
      if (m.deleted_at) return
      var row = el('div', 'ss-wc-msg ' + (m.direction === 'out' ? 'ss-wc-out' : 'ss-wc-in'))
      row.appendChild(el('div', 'ss-wc-bubble', m.text || ''))
      listEl.appendChild(row)
    })
    listEl.scrollTop = listEl.scrollHeight
  }

  function setOfflineUI(offline) {
    statusEl.textContent = offline ? 'Недоступен' : 'Онлайн'
    statusEl.className = 'ss-wc-status' + (offline ? ' ss-wc-off' : '')
    inputEl.disabled = !!offline
    sendBtn.disabled = !!offline
    if (offline) {
      inputEl.placeholder = 'Канал выключен'
    } else {
      inputEl.placeholder = 'Ваше сообщение…'
    }
  }

  function sendMessage() {
    var text = (inputEl.value || '').trim()
    if (!text || state.sending || !state.online) return
    state.sending = true
    sendBtn.disabled = true
    api('/api/widget/messages', { method: 'POST', body: { text: text } })
      .then(function (msg) {
        inputEl.value = ''
        upsertMessage(msg)
      })
      .catch(function (err) {
        if (err && err.status === 403) {
          state.online = false
          setOfflineUI(true)
        }
        console.warn('[SkySender widget] send failed', err)
      })
      .then(function () {
        state.sending = false
        sendBtn.disabled = !state.online
      })
  }

  function openPanel() {
    state.open = true
    panel.style.display = 'flex'
    fab.classList.add('ss-wc-fab-open')
    ensureSession()
      .then(loadMessages)
      .then(connectWs)
      .catch(function (err) {
        console.warn('[SkySender widget] session failed', err)
        listEl.innerHTML = ''
        listEl.appendChild(el('div', 'ss-wc-empty', 'Не удалось подключить чат'))
      })
  }

  function closePanel() {
    state.open = false
    panel.style.display = 'none'
    fab.classList.remove('ss-wc-fab-open')
    if (state.ws) {
      try {
        state.ws.close()
      } catch (e) {}
      state.ws = null
    }
  }

  // Styles
  var style = document.createElement('style')
  style.textContent = [
    '.ss-wc-root{all:initial;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}',
    '.ss-wc-fab{position:fixed;right:20px;bottom:20px;z-index:2147483000;width:56px;height:56px;border:0;border-radius:50%;background:#1d4ed8;color:#fff;cursor:pointer;box-shadow:0 8px 24px rgba(29,78,216,.35);font-size:22px;line-height:1}',
    '.ss-wc-fab:hover{filter:brightness(1.05)}',
    '.ss-wc-panel{position:fixed;right:20px;bottom:88px;z-index:2147483000;width:min(360px,calc(100vw - 24px));height:min(520px,calc(100vh - 120px));display:none;flex-direction:column;background:#fff;border:1px solid #e5e7eb;border-radius:16px;overflow:hidden;box-shadow:0 16px 48px rgba(15,23,42,.18);color:#0f172a}',
    '.ss-wc-head{display:flex;align-items:center;gap:8px;padding:12px 14px;background:#1d4ed8;color:#fff}',
    '.ss-wc-title{flex:1;font-size:14px;font-weight:650;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
    '.ss-wc-status{font-size:11px;opacity:.9}',
    '.ss-wc-status.ss-wc-off{opacity:.75}',
    '.ss-wc-close{border:0;background:transparent;color:#fff;cursor:pointer;font-size:18px;line-height:1;padding:4px}',
    '.ss-wc-list{flex:1;overflow:auto;padding:12px;background:#f8fafc}',
    '.ss-wc-empty{color:#64748b;font-size:13px;text-align:center;padding:24px 8px}',
    '.ss-wc-msg{display:flex;margin:0 0 8px}',
    '.ss-wc-in{justify-content:flex-end}',
    '.ss-wc-out{justify-content:flex-start}',
    '.ss-wc-bubble{max-width:80%;padding:8px 11px;border-radius:14px;font-size:13px;line-height:1.4;white-space:pre-wrap;word-break:break-word}',
    '.ss-wc-in .ss-wc-bubble{background:#1d4ed8;color:#fff;border-bottom-right-radius:4px}',
    '.ss-wc-out .ss-wc-bubble{background:#fff;border:1px solid #e2e8f0;border-bottom-left-radius:4px}',
    '.ss-wc-form{display:flex;gap:8px;padding:10px;border-top:1px solid #e5e7eb;background:#fff}',
    '.ss-wc-input{flex:1;border:1px solid #e2e8f0;border-radius:10px;padding:9px 11px;font-size:13px;outline:none}',
    '.ss-wc-input:focus{border-color:#93c5fd}',
    '.ss-wc-send{border:0;border-radius:10px;background:#1d4ed8;color:#fff;padding:0 12px;font-size:13px;font-weight:600;cursor:pointer}',
    '.ss-wc-send:disabled{opacity:.5;cursor:default}',
  ].join('')
  document.head.appendChild(style)

  var root = el('div', 'ss-wc-root')
  var fab = el('button', 'ss-wc-fab', '💬')
  fab.type = 'button'
  fab.setAttribute('aria-label', 'Открыть чат')

  var panel = el('div', 'ss-wc-panel')
  var head = el('div', 'ss-wc-head')
  var titleEl = el('div', 'ss-wc-title', 'Чат')
  var statusEl = el('div', 'ss-wc-status', '…')
  var closeBtn = el('button', 'ss-wc-close', '×')
  closeBtn.type = 'button'
  head.appendChild(titleEl)
  head.appendChild(statusEl)
  head.appendChild(closeBtn)

  var listEl = el('div', 'ss-wc-list')
  var form = el('div', 'ss-wc-form')
  var inputEl = el('input', 'ss-wc-input')
  inputEl.type = 'text'
  inputEl.placeholder = 'Ваше сообщение…'
  var sendBtn = el('button', 'ss-wc-send', '→')
  sendBtn.type = 'button'
  form.appendChild(inputEl)
  form.appendChild(sendBtn)

  panel.appendChild(head)
  panel.appendChild(listEl)
  panel.appendChild(form)
  root.appendChild(panel)
  root.appendChild(fab)
  document.body.appendChild(root)

  fab.addEventListener('click', function () {
    if (state.open) closePanel()
    else openPanel()
  })
  closeBtn.addEventListener('click', closePanel)
  sendBtn.addEventListener('click', sendMessage)
  inputEl.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') {
      e.preventDefault()
      sendMessage()
    }
  })
})()
