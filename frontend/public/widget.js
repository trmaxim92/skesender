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
  var STORAGE_PROFILE = 'skysender_wc_profile_' + publicKey

  function loadProfile() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_PROFILE) || 'null') || null
    } catch (e) {
      return null
    }
  }

  function saveProfile(profile) {
    localStorage.setItem(STORAGE_PROFILE, JSON.stringify(profile))
  }

  var state = {
    open: false,
    view: 'lead', // lead | chat
    online: true,
    channelName: 'Поддержка',
    visitorId: localStorage.getItem(STORAGE_VISITOR) || '',
    token: localStorage.getItem(STORAGE_TOKEN) || '',
    dialogId: null,
    messages: [],
    sending: false,
    ws: null,
    profile: loadProfile(),
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
      return res.text().then(function (raw) {
        var data = null
        try {
          data = raw ? JSON.parse(raw) : null
        } catch (e) {
          data = { detail: raw }
        }
        if (!res.ok) {
          var detail = data && data.detail
          if (Array.isArray(detail)) {
            detail = detail
              .map(function (x) {
                return x.msg || JSON.stringify(x)
              })
              .join('; ')
          }
          var err = new Error(detail || res.statusText || 'error')
          err.status = res.status
          throw err
        }
        return data
      })
    })
  }

  function normalizePhone(value) {
    var digits = String(value || '').replace(/\D+/g, '')
    if (digits.length === 11 && digits[0] === '8') digits = '7' + digits.slice(1)
    if (digits.length === 10) digits = '7' + digits
    return digits
  }

  function formatPhoneDisplay(digits) {
    if (!digits || digits.length < 11) return digits || ''
    return (
      '+' +
      digits[0] +
      ' (' +
      digits.slice(1, 4) +
      ') ' +
      digits.slice(4, 7) +
      '-' +
      digits.slice(7, 9) +
      '-' +
      digits.slice(9, 11)
    )
  }

  function ensureSession(profile) {
    return api('/api/widget/session', {
      method: 'POST',
      body: {
        public_key: publicKey,
        visitor_id: state.visitorId || null,
        contact_name: profile.name,
        contact_phone: profile.phone,
      },
    }).then(function (data) {
      state.token = data.visitor_token
      state.visitorId = data.visitor_id
      state.dialogId = data.dialog_id
      state.channelName = data.channel_name || 'Поддержка'
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
      if (state.open && state.view === 'chat') setTimeout(connectWs, 3000)
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
      var empty = el('div', 'ss-wc-empty')
      empty.appendChild(el('div', 'ss-wc-empty-title', 'Вы в чате'))
      empty.appendChild(
        el('div', 'ss-wc-empty-text', 'Напишите вопрос — оператор ответит здесь'),
      )
      listEl.appendChild(empty)
      return
    }
    state.messages.forEach(function (m) {
      if (m.deleted_at) return
      var row = el('div', 'ss-wc-msg ' + (m.direction === 'out' ? 'ss-wc-out' : 'ss-wc-in'))
      var bubble = el('div', 'ss-wc-bubble', m.text || '')
      row.appendChild(bubble)
      listEl.appendChild(row)
    })
    listEl.scrollTop = listEl.scrollHeight
  }

  function setOfflineUI(offline) {
    statusEl.textContent = offline ? 'Недоступен' : 'Онлайн'
    statusDot.className = 'ss-wc-dot' + (offline ? ' ss-wc-dot-off' : '')
    inputEl.disabled = !!offline
    sendBtn.disabled = !!offline
    inputEl.placeholder = offline ? 'Канал временно выключен' : 'Напишите сообщение…'
  }

  function showView(view) {
    state.view = view
    leadEl.style.display = view === 'lead' ? 'flex' : 'none'
    chatEl.style.display = view === 'chat' ? 'flex' : 'none'
  }

  function startChatWithProfile(profile) {
    state.profile = profile
    saveProfile(profile)
    leadError.textContent = ''
    leadBtn.disabled = true
    leadBtn.textContent = 'Подключаем…'
    ensureSession(profile)
      .then(function () {
        showView('chat')
        return loadMessages()
      })
      .then(connectWs)
      .catch(function (err) {
        leadError.textContent = (err && err.message) || 'Не удалось открыть чат'
        showView('lead')
      })
      .then(function () {
        leadBtn.disabled = false
        leadBtn.textContent = 'Начать чат'
      })
  }

  function onLeadSubmit(e) {
    e.preventDefault()
    var name = (nameInput.value || '').trim().replace(/\s+/g, ' ')
    var phoneRaw = phoneInput.value || ''
    var phoneDigits = normalizePhone(phoneRaw)
    leadError.textContent = ''
    if (name.length < 2) {
      leadError.textContent = 'Укажите ФИО'
      nameInput.focus()
      return
    }
    if (phoneDigits.length !== 11 || phoneDigits[0] !== '7') {
      leadError.textContent = 'Укажите телефон в формате +7…'
      phoneInput.focus()
      return
    }
    phoneInput.value = formatPhoneDisplay(phoneDigits)
    startChatWithProfile({ name: name, phone: '+' + phoneDigits })
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
    if (state.profile && state.profile.name && state.profile.phone) {
      startChatWithProfile(state.profile)
    } else {
      showView('lead')
      if (state.profile) {
        nameInput.value = state.profile.name || ''
        phoneInput.value = state.profile.phone || ''
      }
    }
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

  var style = document.createElement('style')
  style.textContent = [
    '.ss-wc-root{all:initial;font-family:"Segoe UI",system-ui,-apple-system,sans-serif}',
    '.ss-wc-fab{position:fixed;right:22px;bottom:22px;z-index:2147483000;width:60px;height:60px;border:0;border-radius:999px;background:linear-gradient(145deg,#0f766e,#0d9488 45%,#14b8a6);color:#fff;cursor:pointer;box-shadow:0 14px 34px rgba(13,148,136,.38);display:grid;place-items:center;transition:transform .18s ease,box-shadow .18s ease}',
    '.ss-wc-fab:hover{transform:translateY(-2px);box-shadow:0 18px 40px rgba(13,148,136,.45)}',
    '.ss-wc-fab svg{width:26px;height:26px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}',
    '.ss-wc-fab-open{transform:rotate(8deg)}',
    '.ss-wc-panel{position:fixed;right:22px;bottom:96px;z-index:2147483000;width:min(380px,calc(100vw - 24px));height:min(560px,calc(100vh - 120px));display:none;flex-direction:column;background:#f4f7f6;border:1px solid rgba(15,23,42,.08);border-radius:22px;overflow:hidden;box-shadow:0 24px 60px rgba(15,23,42,.22);color:#0f172a}',
    '.ss-wc-head{display:flex;align-items:center;gap:12px;padding:14px 16px;background:linear-gradient(135deg,#0f766e,#0d9488);color:#fff;position:relative}',
    '.ss-wc-head::after{content:"";position:absolute;inset:auto 0 -18px 0;height:36px;background:linear-gradient(180deg,rgba(15,118,110,.18),transparent);pointer-events:none}',
    '.ss-wc-avatar{width:40px;height:40px;border-radius:14px;background:rgba(255,255,255,.18);display:grid;place-items:center;flex-shrink:0}',
    '.ss-wc-avatar svg{width:20px;height:20px;stroke:#fff;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}',
    '.ss-wc-head-main{min-width:0;flex:1}',
    '.ss-wc-title{font-size:15px;font-weight:700;letter-spacing:.01em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
    '.ss-wc-sub{display:flex;align-items:center;gap:6px;margin-top:2px;font-size:12px;opacity:.92}',
    '.ss-wc-dot{width:8px;height:8px;border-radius:50%;background:#86efac;box-shadow:0 0 0 3px rgba(134,239,172,.25)}',
    '.ss-wc-dot-off{background:#fecaca;box-shadow:0 0 0 3px rgba(254,202,202,.25)}',
    '.ss-wc-close{border:0;background:rgba(255,255,255,.14);color:#fff;cursor:pointer;width:32px;height:32px;border-radius:10px;font-size:18px;line-height:1}',
    '.ss-wc-lead,.ss-wc-chat{flex:1;min-height:0;display:none;flex-direction:column}',
    '.ss-wc-lead{padding:18px 16px 16px;gap:12px}',
    '.ss-wc-lead-card{background:#fff;border:1px solid rgba(15,23,42,.06);border-radius:18px;padding:16px;box-shadow:0 10px 24px rgba(15,23,42,.05)}',
    '.ss-wc-lead-title{font-size:16px;font-weight:700;margin:0 0 4px}',
    '.ss-wc-lead-text{font-size:13px;line-height:1.45;color:#64748b;margin:0 0 14px}',
    '.ss-wc-field{display:block;margin:0 0 10px}',
    '.ss-wc-label{display:block;font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:#64748b;margin:0 0 6px}',
    '.ss-wc-control{width:100%;box-sizing:border-box;border:1px solid #dbe3ea;border-radius:12px;padding:11px 12px;font-size:14px;outline:none;background:#f8fafc;color:#0f172a}',
    '.ss-wc-control:focus{border-color:#5eead4;background:#fff;box-shadow:0 0 0 3px rgba(45,212,191,.18)}',
    '.ss-wc-error{min-height:18px;font-size:12px;color:#dc2626;margin:2px 0 8px}',
    '.ss-wc-primary{width:100%;border:0;border-radius:12px;padding:12px 14px;background:linear-gradient(135deg,#0f766e,#14b8a6);color:#fff;font-size:14px;font-weight:700;cursor:pointer;box-shadow:0 10px 20px rgba(13,148,136,.25)}',
    '.ss-wc-primary:disabled{opacity:.6;cursor:default;box-shadow:none}',
    '.ss-wc-note{font-size:11px;color:#94a3b8;line-height:1.4;margin-top:auto;padding:0 2px}',
    '.ss-wc-list{flex:1;overflow:auto;padding:16px 14px;background:linear-gradient(180deg,#eef6f4,#f4f7f6 40%,#f8fafc)}',
    '.ss-wc-empty{text-align:center;padding:36px 12px;color:#64748b}',
    '.ss-wc-empty-title{font-size:14px;font-weight:700;color:#0f172a;margin-bottom:4px}',
    '.ss-wc-empty-text{font-size:13px;line-height:1.4}',
    '.ss-wc-msg{display:flex;margin:0 0 10px}',
    '.ss-wc-in{justify-content:flex-end}',
    '.ss-wc-out{justify-content:flex-start}',
    '.ss-wc-bubble{max-width:78%;padding:10px 12px;border-radius:16px;font-size:13.5px;line-height:1.45;white-space:pre-wrap;word-break:break-word;box-shadow:0 4px 14px rgba(15,23,42,.06)}',
    '.ss-wc-in .ss-wc-bubble{background:linear-gradient(145deg,#0f766e,#0d9488);color:#fff;border-bottom-right-radius:5px}',
    '.ss-wc-out .ss-wc-bubble{background:#fff;border:1px solid rgba(15,23,42,.06);border-bottom-left-radius:5px;color:#0f172a}',
    '.ss-wc-form{display:flex;gap:8px;padding:12px;border-top:1px solid rgba(15,23,42,.06);background:rgba(255,255,255,.92);backdrop-filter:blur(8px)}',
    '.ss-wc-input{flex:1;border:1px solid #dbe3ea;border-radius:14px;padding:11px 12px;font-size:14px;outline:none;background:#fff}',
    '.ss-wc-input:focus{border-color:#5eead4;box-shadow:0 0 0 3px rgba(45,212,191,.16)}',
    '.ss-wc-send{border:0;border-radius:14px;min-width:44px;background:linear-gradient(145deg,#0f766e,#14b8a6);color:#fff;font-size:16px;font-weight:700;cursor:pointer}',
    '.ss-wc-send:disabled{opacity:.5;cursor:default}',
  ].join('')
  document.head.appendChild(style)

  var root = el('div', 'ss-wc-root')

  var fab = el('button', 'ss-wc-fab')
  fab.type = 'button'
  fab.setAttribute('aria-label', 'Открыть чат')
  fab.innerHTML =
    '<svg viewBox="0 0 24 24"><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/></svg>'

  var panel = el('div', 'ss-wc-panel')

  var head = el('div', 'ss-wc-head')
  var avatar = el('div', 'ss-wc-avatar')
  avatar.innerHTML =
    '<svg viewBox="0 0 24 24"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>'
  var headMain = el('div', 'ss-wc-head-main')
  var titleEl = el('div', 'ss-wc-title', 'Поддержка')
  var sub = el('div', 'ss-wc-sub')
  var statusDot = el('span', 'ss-wc-dot')
  var statusEl = el('span', null, 'Онлайн')
  sub.appendChild(statusDot)
  sub.appendChild(statusEl)
  headMain.appendChild(titleEl)
  headMain.appendChild(sub)
  var closeBtn = el('button', 'ss-wc-close', '×')
  closeBtn.type = 'button'
  head.appendChild(avatar)
  head.appendChild(headMain)
  head.appendChild(closeBtn)

  // Lead form
  var leadEl = el('div', 'ss-wc-lead')
  var leadCard = el('div', 'ss-wc-lead-card')
  leadCard.appendChild(el('div', 'ss-wc-lead-title', 'Напишите нам'))
  leadCard.appendChild(
    el('p', 'ss-wc-lead-text', 'Оставьте контакты — и сразу перейдёте в чат с оператором.'),
  )
  var leadForm = el('form', 'ss-wc-lead-form')
  var nameField = el('label', 'ss-wc-field')
  nameField.appendChild(el('span', 'ss-wc-label', 'ФИО'))
  var nameInput = el('input', 'ss-wc-control')
  nameInput.type = 'text'
  nameInput.autocomplete = 'name'
  nameInput.placeholder = 'Иванов Иван Иванович'
  nameInput.required = true
  nameField.appendChild(nameInput)
  var phoneField = el('label', 'ss-wc-field')
  phoneField.appendChild(el('span', 'ss-wc-label', 'Телефон'))
  var phoneInput = el('input', 'ss-wc-control')
  phoneInput.type = 'tel'
  phoneInput.autocomplete = 'tel'
  phoneInput.placeholder = '+7 (999) 123-45-67'
  phoneInput.required = true
  phoneField.appendChild(phoneInput)
  var leadError = el('div', 'ss-wc-error')
  var leadBtn = el('button', 'ss-wc-primary', 'Начать чат')
  leadBtn.type = 'submit'
  leadForm.appendChild(nameField)
  leadForm.appendChild(phoneField)
  leadForm.appendChild(leadError)
  leadForm.appendChild(leadBtn)
  leadCard.appendChild(leadForm)
  leadEl.appendChild(leadCard)
  leadEl.appendChild(
    el('div', 'ss-wc-note', 'Данные нужны, чтобы оператор мог связаться с вами при необходимости.'),
  )

  // Chat
  var chatEl = el('div', 'ss-wc-chat')
  var listEl = el('div', 'ss-wc-list')
  var form = el('div', 'ss-wc-form')
  var inputEl = el('input', 'ss-wc-input')
  inputEl.type = 'text'
  inputEl.placeholder = 'Напишите сообщение…'
  var sendBtn = el('button', 'ss-wc-send', '↑')
  sendBtn.type = 'button'
  form.appendChild(inputEl)
  form.appendChild(sendBtn)
  chatEl.appendChild(listEl)
  chatEl.appendChild(form)

  panel.appendChild(head)
  panel.appendChild(leadEl)
  panel.appendChild(chatEl)
  root.appendChild(panel)
  root.appendChild(fab)
  document.body.appendChild(root)

  fab.addEventListener('click', function () {
    if (state.open) closePanel()
    else openPanel()
  })
  closeBtn.addEventListener('click', closePanel)
  leadForm.addEventListener('submit', onLeadSubmit)
  sendBtn.addEventListener('click', sendMessage)
  inputEl.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') {
      e.preventDefault()
      sendMessage()
    }
  })
  phoneInput.addEventListener('blur', function () {
    var digits = normalizePhone(phoneInput.value)
    if (digits.length === 11) phoneInput.value = formatPhoneDisplay(digits)
  })
})()
