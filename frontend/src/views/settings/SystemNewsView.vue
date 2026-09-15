<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  createSystemNewsRequest,
  deleteSystemNewsRequest,
  listSystemNewsAdminRequest,
  type ApiSystemNews,
} from '@/api/notifications'
import { ApiError } from '@/api/client'

const items = ref<ApiSystemNews[]>([])
const loading = ref(false)
const error = ref('')
const saving = ref(false)

const title = ref('')
const body = ref('')
const sendPush = ref(true)

async function load() {
  loading.value = true
  error.value = ''
  try {
    items.value = await listSystemNewsAdminRequest()
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
})

async function publish() {
  if (!title.value.trim() || !body.value.trim()) return
  saving.value = true
  error.value = ''
  try {
    const created = await createSystemNewsRequest({
      title: title.value.trim(),
      body: body.value.trim(),
      send_push: sendPush.value,
    })
    items.value = [created, ...items.value]
    title.value = ''
    body.value = ''
    sendPush.value = true
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось опубликовать'
  } finally {
    saving.value = false
  }
}

async function remove(id: number) {
  if (!confirm('Удалить новость у всех сотрудников?')) return
  error.value = ''
  try {
    await deleteSystemNewsRequest(id)
    items.value = items.value.filter((n) => n.id !== id)
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось удалить'
  }
}

function formatAt(iso: string) {
  try {
    return new Date(iso).toLocaleString('ru-RU', {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}
</script>

<template>
  <div class="mx-auto max-w-3xl space-y-6 p-4 md:p-6">
    <div>
      <h2 class="text-lg font-semibold text-ink">Новости системы</h2>
      <p class="mt-1 text-sm text-mute">
        Объявления появятся у сотрудников в колокольчике (название и краткое описание). По клику
        откроется страница новости. При публикации можно сразу отправить push на телефоны.
      </p>
    </div>

    <p v-if="error" class="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
      {{ error }}
    </p>

    <form class="space-y-3 rounded-xl border border-line bg-panel p-4" @submit.prevent="publish">
      <label class="block">
        <span class="mb-1 block text-xs font-medium text-mute">Заголовок</span>
        <input
          v-model="title"
          type="text"
          maxlength="255"
          class="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-brand"
          placeholder="Например: Обновление от 15 сентября"
        />
      </label>
      <label class="block">
        <span class="mb-1 block text-xs font-medium text-mute">Текст</span>
        <textarea
          v-model="body"
          rows="5"
          maxlength="8000"
          class="w-full resize-y rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-brand"
          placeholder="Кратко перечислите изменения для команды"
        />
      </label>
      <label class="flex items-center gap-2 text-sm text-ink">
        <input v-model="sendPush" type="checkbox" class="size-4 rounded border-line" />
        Отправить push-уведомление на устройства сотрудников
      </label>
      <button
        type="submit"
        class="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white transition hover:opacity-90 disabled:opacity-50"
        :disabled="saving || !title.trim() || !body.trim()"
      >
        {{ saving ? 'Публикация…' : 'Опубликовать' }}
      </button>
    </form>

    <div class="space-y-3">
      <h3 class="text-sm font-semibold text-ink">Опубликованные</h3>
      <p v-if="loading" class="text-sm text-mute">Загрузка…</p>
      <p v-else-if="!items.length" class="text-sm text-mute">Пока нет новостей.</p>
      <article
        v-for="n in items"
        :key="n.id"
        class="rounded-xl border border-line bg-panel p-4"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <h4 class="font-medium text-ink">{{ n.title }}</h4>
            <p class="mt-1 whitespace-pre-wrap text-sm text-mute">{{ n.body }}</p>
            <p class="mt-2 text-[11px] text-mute">
              {{ formatAt(n.published_at) }}
              <span v-if="n.created_by_name"> · {{ n.created_by_name }}</span>
              · прочитано: {{ n.read_count }}
            </p>
          </div>
          <button
            type="button"
            class="shrink-0 rounded-lg border border-line px-2.5 py-1 text-xs text-mute transition hover:border-red-300 hover:text-red-600"
            @click="remove(n.id)"
          >
            Удалить
          </button>
        </div>
      </article>
    </div>
  </div>
</template>
