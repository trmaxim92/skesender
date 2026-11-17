<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Bot, RefreshCw, Sparkles } from 'lucide-vue-next'
import {
  fetchAiGlobalSettings,
  fetchAiMetrics,
  fetchAiProfile,
  fetchAiStatus,
  listLearningExamples,
  reviewLearningExample,
  saveAiGlobalSettings,
  saveAiProfile,
  type ApiAiGlobalSettings,
  type ApiAiLearning,
  type ApiAiMetrics,
  type ApiAiProfile,
  type ApiAiStatus,
} from '@/api/ai'
import { listDepartmentsRequest, mapDepartment } from '@/api/settings'
import { ApiError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import type { Department } from '@/types'

const auth = useAuthStore()
const canWrite = computed(() => auth.can('action.write'))

const departments = ref<Department[]>([])
const departmentId = ref<number | null>(null)
const globalSettings = ref<ApiAiGlobalSettings | null>(null)
const clientSecret = ref('')
const profile = ref<ApiAiProfile | null>(null)
const status = ref<ApiAiStatus | null>(null)
const metrics = ref<ApiAiMetrics | null>(null)
const learning = ref<ApiAiLearning[]>([])
const loading = ref(false)
const saving = ref(false)
const savingGlobal = ref(false)
const pinging = ref(false)
const error = ref('')
const ok = ref('')

async function loadDepartments() {
  departments.value = (await listDepartmentsRequest()).map(mapDepartment)
  if (departmentId.value == null && departments.value.length) {
    departmentId.value = departments.value[0].id
  }
}

async function loadGlobal() {
  globalSettings.value = await fetchAiGlobalSettings()
  status.value = await fetchAiStatus(false)
  clientSecret.value = ''
}

async function loadDepartmentData() {
  if (departmentId.value == null) return
  const [pr, met, learn] = await Promise.all([
    fetchAiProfile(departmentId.value),
    fetchAiMetrics(departmentId.value),
    listLearningExamples(departmentId.value, 'pending_review'),
  ])
  profile.value = pr
  metrics.value = met
  learning.value = learn
}

async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    await loadGlobal()
    await loadDepartmentData()
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить'
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    await loadDepartments()
    await loadAll()
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Ошибка загрузки'
  }
})

watch(departmentId, () => {
  void loadDepartmentData()
})

async function saveGlobal() {
  if (!canWrite.value || !globalSettings.value) return
  savingGlobal.value = true
  error.value = ''
  ok.value = ''
  try {
    const payload: Parameters<typeof saveAiGlobalSettings>[0] = {
      enabled: globalSettings.value.enabled,
      client_id: globalSettings.value.client_id,
      scope: globalSettings.value.scope,
      auth_url: globalSettings.value.auth_url,
      api_base: globalSettings.value.api_base,
      default_model: globalSettings.value.default_model,
      verify_ssl: globalSettings.value.verify_ssl,
      temperature: globalSettings.value.temperature,
      max_tokens: globalSettings.value.max_tokens,
      repetition_penalty: globalSettings.value.repetition_penalty,
      max_reply_words: globalSettings.value.max_reply_words,
      require_rag_for_auto: globalSettings.value.require_rag_for_auto,
    }
    if (clientSecret.value.trim()) {
      payload.client_secret = clientSecret.value.trim()
    }
    globalSettings.value = await saveAiGlobalSettings(payload)
    clientSecret.value = ''
    status.value = await fetchAiStatus(false)
    ok.value = 'Настройки GigaChat сохранены'
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось сохранить настройки'
  } finally {
    savingGlobal.value = false
  }
}

async function clearSecret() {
  if (!canWrite.value) return
  savingGlobal.value = true
  try {
    globalSettings.value = await saveAiGlobalSettings({ clear_secret: true })
    clientSecret.value = ''
    status.value = await fetchAiStatus(false)
    ok.value = 'Secret удалён'
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось очистить secret'
  } finally {
    savingGlobal.value = false
  }
}

async function save() {
  if (!canWrite.value || departmentId.value == null || !profile.value) return
  saving.value = true
  error.value = ''
  ok.value = ''
  try {
    profile.value = await saveAiProfile(departmentId.value, {
      enabled: profile.value.enabled,
      mode: profile.value.mode,
      system_prompt: profile.value.system_prompt,
      auto_confidence_min: profile.value.auto_confidence_min,
      max_auto_replies_per_dialog: profile.value.max_auto_replies_per_dialog,
      gigachat_model: profile.value.gigachat_model,
      primary_intents: profile.value.primary_intents,
    })
    metrics.value = await fetchAiMetrics(departmentId.value)
    ok.value = 'Профиль отдела сохранён'
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось сохранить'
  } finally {
    saving.value = false
  }
}

async function ping() {
  pinging.value = true
  try {
    status.value = await fetchAiStatus(true)
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Ping failed'
  } finally {
    pinging.value = false
  }
}

async function review(id: number, st: 'approved' | 'rejected') {
  if (!canWrite.value) return
  try {
    await reviewLearningExample(id, st)
    learning.value = learning.value.filter((x) => x.id !== id)
    if (departmentId.value != null) {
      metrics.value = await fetchAiMetrics(departmentId.value)
    }
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось обновить пример'
  }
}
</script>

<template>
  <div class="ai-settings">
    <header class="ai-settings__head">
      <div>
        <h1><Bot :size="22" /> ИИ (GigaChat)</h1>
        <p>Секреты и настройки — только здесь, в модуле (не в .env)</p>
      </div>
      <button type="button" class="btn ghost" :disabled="pinging" @click="ping">
        <RefreshCw :size="16" /> Проверить GigaChat
      </button>
    </header>

    <p v-if="error" class="err">{{ error }}</p>
    <p v-if="ok" class="ok">{{ ok }}</p>

    <section v-if="globalSettings" class="card form">
      <h2>Подключение GigaChat</h2>
      <label class="check">
        <input v-model="globalSettings.enabled" type="checkbox" :disabled="!canWrite" />
        Модуль ИИ включён
      </label>
      <label>
        Client ID
        <input v-model="globalSettings.client_id" autocomplete="off" :disabled="!canWrite" />
      </label>
      <label>
        Client Secret
        <input
          v-model="clientSecret"
          type="password"
          autocomplete="new-password"
          :disabled="!canWrite"
          :placeholder="
            globalSettings.client_secret_set
              ? 'Секрет сохранён — введите новый, чтобы заменить'
              : 'Вставьте secret'
          "
        />
      </label>
      <div v-if="globalSettings.client_secret_set" class="actions">
        <button type="button" class="btn ghost" :disabled="!canWrite || savingGlobal" @click="clearSecret">
          Удалить secret
        </button>
      </div>
      <label>
        Scope
        <input v-model="globalSettings.scope" :disabled="!canWrite" />
      </label>
      <label>
        Модель по умолчанию
        <input v-model="globalSettings.default_model" :disabled="!canWrite" />
      </label>
      <label>
        Auth URL
        <input v-model="globalSettings.auth_url" :disabled="!canWrite" />
      </label>
      <label>
        API base
        <input v-model="globalSettings.api_base" :disabled="!canWrite" />
      </label>
      <label class="check">
        <input v-model="globalSettings.verify_ssl" type="checkbox" :disabled="!canWrite" />
        Проверять TLS (verify SSL)
      </label>
      <h3 class="subhead">Генерация (Sber)</h3>
      <div class="grid2">
        <label>
          Temperature
          <input
            v-model.number="globalSettings.temperature"
            type="number"
            min="0"
            max="2"
            step="0.05"
            :disabled="!canWrite"
          />
        </label>
        <label>
          Max tokens
          <input
            v-model.number="globalSettings.max_tokens"
            type="number"
            min="16"
            max="4096"
            :disabled="!canWrite"
          />
        </label>
        <label>
          Repetition penalty
          <input
            v-model.number="globalSettings.repetition_penalty"
            type="number"
            min="0.1"
            max="2"
            step="0.05"
            :disabled="!canWrite"
          />
        </label>
        <label>
          Лимит слов ответа
          <input
            v-model.number="globalSettings.max_reply_words"
            type="number"
            min="20"
            max="300"
            :disabled="!canWrite"
          />
        </label>
      </div>
      <label class="check">
        <input v-model="globalSettings.require_rag_for_auto" type="checkbox" :disabled="!canWrite" />
        Автоответ только при наличии RAG
      </label>
      <button
        type="button"
        class="btn primary"
        :disabled="!canWrite || savingGlobal"
        @click="saveGlobal"
      >
        <Sparkles :size="16" /> Сохранить подключение
      </button>
      <div v-if="status" class="row muted">
        <span>Статус</span>
        <strong>
          {{ status.ai_enabled ? 'вкл' : 'выкл' }}
          ·
          {{ status.gigachat_configured ? 'ключи заданы' : 'ключи не заданы' }}
        </strong>
      </div>
      <div v-if="status?.gigachat_ping" class="row">
        <span>Ping</span>
        <strong :class="status.gigachat_ping.ok ? 'ok' : 'err'">
          {{ status.gigachat_ping.ok ? 'ok' : status.gigachat_ping.detail }}
        </strong>
      </div>
    </section>

    <section class="card">
      <label>
        Отдел
        <select v-model.number="departmentId" :disabled="loading">
          <option v-for="d in departments" :key="d.id" :value="d.id">{{ d.name }}</option>
        </select>
      </label>
    </section>

    <section v-if="profile" class="card form">
      <h2>Профиль отдела</h2>
      <label class="check">
        <input v-model="profile.enabled" type="checkbox" :disabled="!canWrite" />
        Включить ИИ для отдела
      </label>
      <label>
        Режим
        <select v-model="profile.mode" :disabled="!canWrite">
          <option value="assist">Только рекомендации</option>
          <option value="hybrid">Гибрид (первичка + черновики)</option>
          <option value="auto">Автоответы (с порогом)</option>
        </select>
      </label>
      <label>
        Системный промпт отдела
        <textarea
          v-model="profile.system_prompt"
          rows="5"
          :disabled="!canWrite"
          placeholder="Роль: поддержка / продажи / реактивация…"
        />
      </label>
      <label>
        Порог автоответа (0–100)
        <input
          v-model.number="profile.auto_confidence_min"
          type="number"
          min="0"
          max="100"
          :disabled="!canWrite"
        />
      </label>
      <label>
        Макс. автоответов в диалоге
        <input
          v-model.number="profile.max_auto_replies_per_dialog"
          type="number"
          min="0"
          max="50"
          :disabled="!canWrite"
        />
      </label>
      <label>
        Модель GigaChat (отдел)
        <input v-model="profile.gigachat_model" :disabled="!canWrite" />
      </label>
      <label>
        Primary intents (через запятую)
        <input v-model="profile.primary_intents" :disabled="!canWrite" />
      </label>
      <button type="button" class="btn primary" :disabled="!canWrite || saving" @click="save">
        <Sparkles :size="16" /> Сохранить профиль
      </button>
    </section>

    <section v-if="metrics" class="card metrics">
      <h2>Метрики</h2>
      <div class="grid">
        <div><span>Всего</span><b>{{ metrics.suggestions_total }}</b></div>
        <div><span>Ожидают</span><b>{{ metrics.pending }}</b></div>
        <div><span>Принято</span><b>{{ metrics.accepted }}</b></div>
        <div><span>Правки</span><b>{{ metrics.edited }}</b></div>
        <div><span>Отказ</span><b>{{ metrics.rejected }}</b></div>
        <div><span>Авто</span><b>{{ metrics.auto_sent }}</b></div>
        <div><span>Обучение</span><b>{{ metrics.learning_pending }}</b></div>
        <div><span>В RAG</span><b>{{ metrics.learning_approved }}</b></div>
      </div>
    </section>

    <section class="card">
      <h2>Очередь обучения</h2>
      <p v-if="!learning.length" class="muted">Нет примеров на модерации</p>
      <article v-for="ex in learning" :key="ex.id" class="learn">
        <p><strong>Клиент:</strong> {{ ex.user_question }}</p>
        <p><strong>Оператор:</strong> {{ ex.operator_answer }}</p>
        <div class="actions">
          <button type="button" class="btn primary" :disabled="!canWrite" @click="review(ex.id, 'approved')">
            В базу
          </button>
          <button type="button" class="btn ghost" :disabled="!canWrite" @click="review(ex.id, 'rejected')">
            Отклонить
          </button>
        </div>
      </article>
    </section>
  </div>
</template>

<style scoped>
.ai-settings {
  max-width: 820px;
  margin: 0 auto;
  padding: 1.25rem 1rem 3rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.ai-settings__head {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: flex-start;
}
.ai-settings__head h1 {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0;
  font-size: 1.35rem;
}
.ai-settings__head p {
  margin: 0.35rem 0 0;
  opacity: 0.7;
}
.card {
  border: 1px solid color-mix(in srgb, currentColor 12%, transparent);
  border-radius: 12px;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.card h2 {
  margin: 0;
  font-size: 1.05rem;
}
.subhead {
  margin: 0.25rem 0 0;
  font-size: 0.95rem;
  font-weight: 600;
  opacity: 0.85;
}
.grid2 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.75rem;
}
@media (max-width: 700px) {
  .grid2 {
    grid-template-columns: 1fr;
  }
}
.form label {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  font-size: 0.9rem;
}
.form input,
.form select,
.form textarea {
  padding: 0.55rem 0.65rem;
  border-radius: 8px;
  border: 1px solid color-mix(in srgb, currentColor 18%, transparent);
  background: transparent;
  color: inherit;
  font: inherit;
}
.check {
  flex-direction: row !important;
  align-items: center;
  gap: 0.5rem !important;
}
.row {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
}
.btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  border-radius: 8px;
  padding: 0.5rem 0.85rem;
  border: 1px solid color-mix(in srgb, currentColor 18%, transparent);
  background: transparent;
  color: inherit;
  cursor: pointer;
  width: fit-content;
}
.btn.primary {
  background: color-mix(in srgb, #2563eb 85%, black);
  border-color: transparent;
  color: #fff;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.metrics .grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.75rem;
}
.metrics .grid div {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}
.metrics span {
  font-size: 0.8rem;
  opacity: 0.65;
}
.learn {
  border-top: 1px solid color-mix(in srgb, currentColor 10%, transparent);
  padding-top: 0.75rem;
}
.actions {
  display: flex;
  gap: 0.5rem;
}
.err {
  color: #dc2626;
}
.ok {
  color: #16a34a;
}
.muted {
  opacity: 0.6;
}
@media (max-width: 700px) {
  .metrics .grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
