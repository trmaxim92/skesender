<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RefreshCw, Sparkles } from 'lucide-vue-next'
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

const inputClass =
  'w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none ring-brand focus:ring-2 disabled:opacity-60'
const labelClass = 'mb-1 block text-xs font-semibold text-muted'
const panelClass = 'space-y-4 rounded-2xl border border-line bg-panel p-4'
const btnPrimary =
  'inline-flex items-center gap-1.5 rounded-xl bg-brand px-3.5 py-2 text-sm font-semibold text-white disabled:opacity-50'
const btnGhost =
  'inline-flex items-center gap-1.5 rounded-xl border border-line bg-surface px-3 py-2 text-sm font-medium text-ink hover:bg-panel disabled:opacity-50'

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
  error.value = ''
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
  <div class="h-full overflow-auto p-4 md:p-6">
    <div class="mx-auto max-w-3xl space-y-5 pb-10">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 class="text-lg font-semibold tracking-tight">GigaChat</h2>
          <p class="mt-1 text-sm text-muted">
            Секреты и параметры генерации хранятся здесь (не в .env).
          </p>
        </div>
        <button type="button" :class="btnGhost" :disabled="pinging" @click="ping">
          <RefreshCw class="size-4" :class="pinging ? 'animate-spin' : ''" />
          Проверить
        </button>
      </div>

      <p v-if="error" class="text-sm text-danger">{{ error }}</p>
      <p v-if="ok" class="text-sm text-ok">{{ ok }}</p>
      <p v-if="loading && !globalSettings" class="text-sm text-muted">Загрузка…</p>

      <section v-if="globalSettings" :class="panelClass">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h3 class="text-sm font-semibold">Подключение</h3>
          <div class="flex flex-wrap items-center gap-2">
            <span
              class="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
              :class="
                status?.ai_enabled ? 'bg-ok/15 text-ok' : 'bg-surface text-muted'
              "
            >
              {{ status?.ai_enabled ? 'модуль вкл' : 'модуль выкл' }}
            </span>
            <span
              class="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
              :class="
                status?.gigachat_configured
                  ? 'bg-ok/15 text-ok'
                  : 'bg-danger/15 text-danger'
              "
            >
              {{ status?.gigachat_configured ? 'ключи заданы' : 'нет ключей' }}
            </span>
            <span
              v-if="status?.gigachat_ping"
              class="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
              :class="
                status.gigachat_ping.ok ? 'bg-ok/15 text-ok' : 'bg-danger/15 text-danger'
              "
            >
              ping: {{ status.gigachat_ping.ok ? 'ok' : status.gigachat_ping.detail }}
            </span>
          </div>
        </div>

        <label class="flex items-center gap-2 text-sm">
          <input
            v-model="globalSettings.enabled"
            type="checkbox"
            class="size-4 rounded border-line"
            :disabled="!canWrite"
          />
          Модуль ИИ включён
        </label>

        <div class="grid gap-3 sm:grid-cols-2">
          <label class="block sm:col-span-2">
            <span :class="labelClass">Client ID</span>
            <input
              v-model="globalSettings.client_id"
              :class="inputClass"
              autocomplete="off"
              :disabled="!canWrite"
            />
          </label>
          <label class="block sm:col-span-2">
            <span :class="labelClass">Client Secret</span>
            <input
              v-model="clientSecret"
              type="password"
              :class="inputClass"
              autocomplete="new-password"
              :disabled="!canWrite"
              :placeholder="
                globalSettings.client_secret_set
                  ? 'Секрет сохранён — введите новый, чтобы заменить'
                  : 'Вставьте secret'
              "
            />
          </label>
        </div>

        <div v-if="globalSettings.client_secret_set" class="flex">
          <button
            type="button"
            :class="btnGhost"
            :disabled="!canWrite || savingGlobal"
            @click="clearSecret"
          >
            Удалить secret
          </button>
        </div>

        <div class="grid gap-3 sm:grid-cols-2">
          <label class="block">
            <span :class="labelClass">Scope</span>
            <input v-model="globalSettings.scope" :class="inputClass" :disabled="!canWrite" />
          </label>
          <label class="block">
            <span :class="labelClass">Модель по умолчанию</span>
            <input
              v-model="globalSettings.default_model"
              :class="inputClass"
              :disabled="!canWrite"
            />
          </label>
          <label class="block sm:col-span-2">
            <span :class="labelClass">Auth URL</span>
            <input
              v-model="globalSettings.auth_url"
              :class="[inputClass, 'font-mono text-xs']"
              :disabled="!canWrite"
            />
          </label>
          <label class="block sm:col-span-2">
            <span :class="labelClass">API base</span>
            <input
              v-model="globalSettings.api_base"
              :class="[inputClass, 'font-mono text-xs']"
              :disabled="!canWrite"
            />
          </label>
        </div>

        <label class="flex items-center gap-2 text-sm">
          <input
            v-model="globalSettings.verify_ssl"
            type="checkbox"
            class="size-4 rounded border-line"
            :disabled="!canWrite"
          />
          Проверять TLS (verify SSL)
        </label>

        <div class="border-t border-line pt-4">
          <h4 class="mb-3 text-xs font-semibold uppercase tracking-wide text-muted">
            Генерация (Sber)
          </h4>
          <div class="grid gap-3 sm:grid-cols-2">
            <label class="block">
              <span :class="labelClass">Temperature</span>
              <input
                v-model.number="globalSettings.temperature"
                type="number"
                min="0"
                max="2"
                step="0.05"
                :class="inputClass"
                :disabled="!canWrite"
              />
            </label>
            <label class="block">
              <span :class="labelClass">Max tokens</span>
              <input
                v-model.number="globalSettings.max_tokens"
                type="number"
                min="16"
                max="4096"
                :class="inputClass"
                :disabled="!canWrite"
              />
            </label>
            <label class="block">
              <span :class="labelClass">Repetition penalty</span>
              <input
                v-model.number="globalSettings.repetition_penalty"
                type="number"
                min="0.1"
                max="2"
                step="0.05"
                :class="inputClass"
                :disabled="!canWrite"
              />
            </label>
            <label class="block">
              <span :class="labelClass">Лимит слов ответа</span>
              <input
                v-model.number="globalSettings.max_reply_words"
                type="number"
                min="20"
                max="300"
                :class="inputClass"
                :disabled="!canWrite"
              />
            </label>
          </div>
          <label class="mt-3 flex items-center gap-2 text-sm">
            <input
              v-model="globalSettings.require_rag_for_auto"
              type="checkbox"
              class="size-4 rounded border-line"
              :disabled="!canWrite"
            />
            Автоответ только при наличии RAG
          </label>
        </div>

        <button
          type="button"
          :class="btnPrimary"
          :disabled="!canWrite || savingGlobal"
          @click="saveGlobal"
        >
          <Sparkles class="size-4" />
          Сохранить подключение
        </button>
      </section>

      <section :class="panelClass">
        <h3 class="text-sm font-semibold">Отдел</h3>
        <label class="block max-w-md">
          <span :class="labelClass">Профиль ИИ</span>
          <select
            v-model.number="departmentId"
            :class="inputClass"
            :disabled="loading || !departments.length"
          >
            <option v-for="d in departments" :key="d.id" :value="d.id">{{ d.name }}</option>
          </select>
        </label>
      </section>

      <section v-if="profile" :class="panelClass">
        <h3 class="text-sm font-semibold">Профиль отдела</h3>
        <label class="flex items-center gap-2 text-sm">
          <input
            v-model="profile.enabled"
            type="checkbox"
            class="size-4 rounded border-line"
            :disabled="!canWrite"
          />
          Включить ИИ для отдела
        </label>
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="block">
            <span :class="labelClass">Режим</span>
            <select v-model="profile.mode" :class="inputClass" :disabled="!canWrite">
              <option value="assist">Только рекомендации</option>
              <option value="hybrid">Гибрид (первичка + черновики)</option>
              <option value="auto">Автоответы (с порогом)</option>
            </select>
          </label>
          <label class="block">
            <span :class="labelClass">Модель GigaChat (отдел)</span>
            <input v-model="profile.gigachat_model" :class="inputClass" :disabled="!canWrite" />
          </label>
          <label class="block sm:col-span-2">
            <span :class="labelClass">Системный промпт</span>
            <textarea
              v-model="profile.system_prompt"
              rows="5"
              :class="inputClass"
              :disabled="!canWrite"
              placeholder="Роль: поддержка / продажи / реактивация…"
            />
          </label>
          <label class="block">
            <span :class="labelClass">Порог автоответа (0–100)</span>
            <input
              v-model.number="profile.auto_confidence_min"
              type="number"
              min="0"
              max="100"
              :class="inputClass"
              :disabled="!canWrite"
            />
          </label>
          <label class="block">
            <span :class="labelClass">Макс. автоответов в диалоге</span>
            <input
              v-model.number="profile.max_auto_replies_per_dialog"
              type="number"
              min="0"
              max="50"
              :class="inputClass"
              :disabled="!canWrite"
            />
          </label>
          <label class="block sm:col-span-2">
            <span :class="labelClass">Primary intents (через запятую)</span>
            <input
              v-model="profile.primary_intents"
              :class="inputClass"
              :disabled="!canWrite"
            />
          </label>
        </div>
        <button type="button" :class="btnPrimary" :disabled="!canWrite || saving" @click="save">
          <Sparkles class="size-4" />
          Сохранить профиль
        </button>
      </section>

      <section v-if="metrics" :class="panelClass">
        <h3 class="text-sm font-semibold">Метрики</h3>
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div class="rounded-xl border border-line bg-surface px-3 py-2">
            <div class="text-[11px] text-muted">Всего</div>
            <div class="text-lg font-semibold">{{ metrics.suggestions_total }}</div>
          </div>
          <div class="rounded-xl border border-line bg-surface px-3 py-2">
            <div class="text-[11px] text-muted">Ожидают</div>
            <div class="text-lg font-semibold">{{ metrics.pending }}</div>
          </div>
          <div class="rounded-xl border border-line bg-surface px-3 py-2">
            <div class="text-[11px] text-muted">Принято</div>
            <div class="text-lg font-semibold">{{ metrics.accepted }}</div>
          </div>
          <div class="rounded-xl border border-line bg-surface px-3 py-2">
            <div class="text-[11px] text-muted">Правки</div>
            <div class="text-lg font-semibold">{{ metrics.edited }}</div>
          </div>
          <div class="rounded-xl border border-line bg-surface px-3 py-2">
            <div class="text-[11px] text-muted">Отказ</div>
            <div class="text-lg font-semibold">{{ metrics.rejected }}</div>
          </div>
          <div class="rounded-xl border border-line bg-surface px-3 py-2">
            <div class="text-[11px] text-muted">Авто</div>
            <div class="text-lg font-semibold">{{ metrics.auto_sent }}</div>
          </div>
          <div class="rounded-xl border border-line bg-surface px-3 py-2">
            <div class="text-[11px] text-muted">Обучение</div>
            <div class="text-lg font-semibold">{{ metrics.learning_pending }}</div>
          </div>
          <div class="rounded-xl border border-line bg-surface px-3 py-2">
            <div class="text-[11px] text-muted">В RAG</div>
            <div class="text-lg font-semibold">{{ metrics.learning_approved }}</div>
          </div>
        </div>
      </section>

      <section :class="panelClass">
        <h3 class="text-sm font-semibold">Очередь обучения</h3>
        <p v-if="!learning.length" class="text-sm text-muted">Нет примеров на модерации</p>
        <article
          v-for="ex in learning"
          :key="ex.id"
          class="space-y-2 border-t border-line pt-3 first:border-t-0 first:pt-0"
        >
          <p class="text-sm">
            <span class="font-semibold">Клиент:</span> {{ ex.user_question }}
          </p>
          <p class="text-sm">
            <span class="font-semibold">Оператор:</span> {{ ex.operator_answer }}
          </p>
          <div class="flex flex-wrap gap-2">
            <button
              type="button"
              :class="btnPrimary"
              :disabled="!canWrite"
              @click="review(ex.id, 'approved')"
            >
              В базу
            </button>
            <button
              type="button"
              :class="btnGhost"
              :disabled="!canWrite"
              @click="review(ex.id, 'rejected')"
            >
              Отклонить
            </button>
          </div>
        </article>
      </section>
    </div>
  </div>
</template>
