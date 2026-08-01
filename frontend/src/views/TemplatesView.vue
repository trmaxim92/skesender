<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Pencil, Trash2 } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
import { useTemplatesStore } from '@/stores/templates'
import type { ChannelTransport, Template, TemplateKind } from '@/types'
import { templateKindLabel, transportLabel } from '@/types'

const auth = useAuthStore()
const templates = useTemplatesStore()
const canWrite = computed(() => auth.can('action.write'))

const name = ref('')
const body = ref('')
const transport = ref<ChannelTransport | 'all'>('all')
const kind = ref<TemplateKind>('general')
const saving = ref(false)
const editingId = ref<string | null>(null)

onMounted(() => {
  void templates.fetchTemplates()
})

function resetForm() {
  name.value = ''
  body.value = ''
  transport.value = 'all'
  kind.value = 'general'
  editingId.value = null
}

function startEdit(t: Template) {
  editingId.value = t.id
  name.value = t.name
  body.value = t.body
  transport.value = t.transport
  kind.value = t.kind
}

async function save() {
  if (!name.value.trim() || !body.value.trim()) return
  saving.value = true
  let ok = false
  if (editingId.value) {
    ok = await templates.updateTemplate(editingId.value, {
      name: name.value.trim(),
      body: body.value.trim(),
      transport: transport.value,
      kind: kind.value,
    })
  } else {
    ok = await templates.addTemplate(
      name.value.trim(),
      body.value.trim(),
      transport.value,
      kind.value,
    )
  }
  saving.value = false
  if (!ok) return
  resetForm()
}

async function remove(id: string) {
  if (!confirm('Удалить общий шаблон?')) return
  await templates.removeTemplate(id)
  if (editingId.value === id) resetForm()
}
</script>

<template>
  <div class="h-full overflow-auto p-6">
    <div class="mb-4">
      <p class="text-sm text-muted">
        Общие шаблоны для ответов клиентам — доступны всем менеджерам. Личные шаблоны — в меню
        профиля.
      </p>
    </div>
    <p v-if="templates.error" class="mb-4 text-sm text-danger">{{ templates.error }}</p>
    <div class="mb-6 grid gap-6 lg:grid-cols-2">
      <form v-if="canWrite" class="rounded-2xl border border-line bg-panel p-4" @submit.prevent="save">
        <h2 class="mb-3 text-sm font-semibold">
          {{ editingId ? 'Редактировать шаблон' : 'Новый общий шаблон' }}
        </h2>
        <p class="mb-3 text-xs text-muted">
          Плейсхолдеры:
          <span v-pre class="font-mono">{{operator}}</span>,
          <span v-pre class="font-mono">{{contact}}</span>,
          <span v-pre class="font-mono">{{appeal}}</span>
        </p>
        <label class="mb-3 block">
          <span class="mb-1 block text-xs font-semibold text-muted">Название</span>
          <input
            v-model="name"
            required
            class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
          />
        </label>
        <label class="mb-3 block">
          <span class="mb-1 block text-xs font-semibold text-muted">Текст</span>
          <textarea
            v-model="body"
            required
            rows="4"
            class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
          />
        </label>
        <label class="mb-3 block">
          <span class="mb-1 block text-xs font-semibold text-muted">Тип</span>
          <select
            v-model="kind"
            class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm"
          >
            <option v-for="(label, key) in templateKindLabel" :key="key" :value="key">
              {{ label }}
            </option>
          </select>
        </label>
        <label class="mb-4 block">
          <span class="mb-1 block text-xs font-semibold text-muted">Канал</span>
          <select
            v-model="transport"
            class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm"
          >
            <option value="all">Все каналы</option>
            <option v-for="(label, key) in transportLabel" :key="key" :value="key">
              {{ label }}
            </option>
          </select>
        </label>
        <div class="flex flex-wrap gap-2">
          <button
            type="submit"
            class="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            :disabled="saving"
          >
            {{ saving ? '…' : editingId ? 'Сохранить' : 'Добавить' }}
          </button>
          <button
            v-if="editingId"
            type="button"
            class="rounded-xl border border-line px-4 py-2 text-sm font-medium text-muted hover:bg-surface"
            @click="resetForm"
          >
            Отмена
          </button>
        </div>
      </form>

      <div class="space-y-3">
        <p v-if="templates.loading" class="text-sm text-muted">Загрузка…</p>
        <p
          v-else-if="!templates.templates.length"
          class="rounded-2xl border border-dashed border-line px-4 py-8 text-center text-sm text-muted"
        >
          Пока нет общих шаблонов
        </p>
        <article
          v-for="t in templates.templates"
          :key="t.id"
          class="rounded-2xl border border-line bg-panel p-4"
        >
          <div class="mb-2 flex items-start justify-between gap-2">
            <div>
              <h3 class="text-sm font-semibold">{{ t.name }}</h3>
              <p class="text-[11px] text-muted">
                {{ templateKindLabel[t.kind] }} ·
                {{ t.transport === 'all' ? 'Все каналы' : transportLabel[t.transport] }}
              </p>
            </div>
            <div v-if="canWrite" class="flex gap-0.5">
              <button
                type="button"
                class="rounded-lg p-1.5 text-muted hover:bg-surface hover:text-ink"
                @click="startEdit(t)"
              >
                <Pencil class="size-4" />
              </button>
              <button
                type="button"
                class="rounded-lg p-1.5 text-muted hover:bg-surface hover:text-danger"
                @click="remove(t.id)"
              >
                <Trash2 class="size-4" />
              </button>
            </div>
          </div>
          <p class="whitespace-pre-wrap text-sm text-ink/90">{{ t.body }}</p>
        </article>
      </div>
    </div>
  </div>
</template>
