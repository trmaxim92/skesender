<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { FolderPlus, ImagePlus, Pencil, Trash2, X } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
import { useMyTemplatesStore } from '@/stores/myTemplates'
import { fetchMyTemplateMediaBlob } from '@/api/cabinet'
import type { ChannelTransport, Template, TemplateKind } from '@/types'
import { transportLabel } from '@/types'

const MAX_IMAGES = 10

type DraftItem = {
  key: string
  file?: File
  attachmentId?: number
  previewUrl: string
  name: string
  local: boolean
}

const auth = useAuthStore()
const templates = useMyTemplatesStore()
const canWrite = computed(() => auth.can('action.write'))

const categoryName = ref('')
const editingCategoryId = ref<string | null>(null)
const editingCategoryName = ref('')

const name = ref('')
const body = ref('')
const transport = ref<ChannelTransport | 'all'>('all')
const kind = ref<TemplateKind>('general')
const categoryId = ref<string>('')
const draftItems = ref<DraftItem[]>([])
const removedAttachmentIds = ref<number[]>([])
const dragOver = ref(false)
const saving = ref(false)
const savingCategory = ref(false)
const editingId = ref<string | null>(null)

const canSave = computed(
  () => Boolean(name.value.trim()) && Boolean(body.value.trim() || draftItems.value.length),
)

const grouped = computed(() => {
  const groups: { id: string | null; name: string; items: Template[] }[] = []
  for (const cat of templates.categories) {
    const items = templates.templates.filter((t) => t.categoryId === cat.id)
    groups.push({ id: cat.id, name: cat.name, items })
  }
  const uncategorized = templates.templates.filter((t) => !t.categoryId)
  if (uncategorized.length || !templates.categories.length) {
    groups.push({ id: null, name: 'Без категории', items: uncategorized })
  }
  return groups
})

onMounted(() => {
  void templates.fetchAll()
})

onUnmounted(() => {
  clearDraft()
})

function clearDraft() {
  for (const item of draftItems.value) {
    if (item.local) URL.revokeObjectURL(item.previewUrl)
  }
  draftItems.value = []
  removedAttachmentIds.value = []
}

function resetForm() {
  name.value = ''
  body.value = ''
  transport.value = 'all'
  kind.value = 'general'
  categoryId.value = ''
  editingId.value = null
  clearDraft()
}

function startEdit(t: Template) {
  editingId.value = t.id
  name.value = t.name
  body.value = t.body
  transport.value = t.transport
  kind.value = t.kind
  categoryId.value = t.categoryId ?? ''
  clearDraft()
  if (t.attachments.length) {
    void loadExistingPreviews(t)
  } else if (t.hasMedia) {
    void loadLegacyPreview(t.id)
  }
}

async function loadExistingPreviews(t: Template) {
  for (const att of t.attachments) {
    try {
      const blob = await fetchMyTemplateMediaBlob(Number(t.id), att.id)
      if (editingId.value !== t.id) return
      draftItems.value.push({
        key: `att-${att.id}`,
        attachmentId: att.id,
        previewUrl: URL.createObjectURL(blob),
        name: att.fileName,
        local: true,
      })
    } catch {
      // skip broken preview
    }
  }
}

async function loadLegacyPreview(id: string) {
  try {
    const blob = await fetchMyTemplateMediaBlob(Number(id), 0)
    if (editingId.value !== id) return
    draftItems.value.push({
      key: 'att-0',
      attachmentId: 0,
      previewUrl: URL.createObjectURL(blob),
      name: 'image.jpg',
      local: true,
    })
  } catch {
    // optional
  }
}

function addFiles(fileList: FileList | File[] | null) {
  if (!fileList) return
  const incoming = Array.from(fileList).filter((f) => f.type.startsWith('image/'))
  const room = MAX_IMAGES - draftItems.value.length
  for (const file of incoming.slice(0, Math.max(0, room))) {
    draftItems.value.push({
      key: `file-${file.name}-${file.size}-${file.lastModified}-${Math.random()}`,
      file,
      previewUrl: URL.createObjectURL(file),
      name: file.name,
      local: true,
    })
  }
}

function onMediaChange(e: Event) {
  const input = e.target as HTMLInputElement
  addFiles(input.files)
  input.value = ''
}

function onDrop(e: DragEvent) {
  dragOver.value = false
  addFiles(e.dataTransfer?.files ?? null)
}

function removeDraftItem(index: number) {
  const item = draftItems.value[index]
  if (!item) return
  if (item.attachmentId != null) {
    removedAttachmentIds.value = [...removedAttachmentIds.value, item.attachmentId]
  }
  if (item.local) URL.revokeObjectURL(item.previewUrl)
  draftItems.value = draftItems.value.filter((_, i) => i !== index)
}

async function addCategory() {
  if (!categoryName.value.trim()) return
  savingCategory.value = true
  const created = await templates.addCategory(categoryName.value.trim())
  savingCategory.value = false
  if (!created) return
  categoryName.value = ''
  if (!categoryId.value) categoryId.value = created.id
}

function startRenameCategory(id: string, current: string) {
  editingCategoryId.value = id
  editingCategoryName.value = current
}

async function saveRenameCategory() {
  if (!editingCategoryId.value || !editingCategoryName.value.trim()) return
  const ok = await templates.renameCategory(
    editingCategoryId.value,
    editingCategoryName.value.trim(),
  )
  if (ok) {
    editingCategoryId.value = null
    editingCategoryName.value = ''
  }
}

async function removeCategory(id: string) {
  if (!confirm('Удалить категорию? Шаблоны останутся без категории.')) return
  await templates.removeCategory(id)
  if (categoryId.value === id) categoryId.value = ''
}

async function saveTemplate() {
  if (!canSave.value) return
  saving.value = true
  const cat = categoryId.value || null
  const newFiles = draftItems.value.map((d) => d.file).filter((f): f is File => Boolean(f))
  let ok = false
  if (editingId.value) {
    ok = await templates.updateTemplate(editingId.value, {
      name: name.value.trim(),
      body: body.value.trim(),
      transport: transport.value,
      kind: kind.value,
      categoryId: cat,
      media: newFiles,
      removeAttachmentIds: removedAttachmentIds.value,
    })
  } else {
    ok = await templates.addTemplate({
      name: name.value.trim(),
      body: body.value.trim(),
      transport: transport.value,
      kind: kind.value,
      categoryId: cat,
      media: newFiles,
    })
  }
  saving.value = false
  if (!ok) return
  resetForm()
}

async function removeTemplate(id: string) {
  if (!confirm('Удалить шаблон?')) return
  await templates.removeTemplate(id)
  if (editingId.value === id) resetForm()
}
</script>

<template>
  <div class="h-full overflow-auto p-6">
    <div class="mb-4">
      <h1 class="text-lg font-semibold">Мои шаблоны</h1>
      <p class="mt-1 text-sm text-muted">
        Личные ответы с категориями — видны только вам. Можно прикрепить до {{ MAX_IMAGES }}
        изображений (выбор или перетаскивание).
      </p>
    </div>

    <p v-if="templates.error" class="mb-4 text-sm text-danger">{{ templates.error }}</p>

    <div class="mb-6 grid gap-6 xl:grid-cols-[280px_1fr]">
      <section class="rounded-2xl border border-line bg-panel p-4">
        <h2 class="mb-3 text-sm font-semibold">Категории</h2>
        <form v-if="canWrite" class="mb-3 flex gap-2" @submit.prevent="addCategory">
          <input
            v-model="categoryName"
            required
            placeholder="Например, Приветствие"
            class="min-w-0 flex-1 rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
          />
          <button
            type="submit"
            class="inline-flex shrink-0 items-center gap-1 rounded-xl bg-brand px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
            :disabled="savingCategory"
            title="Добавить категорию"
          >
            <FolderPlus class="size-4" />
          </button>
        </form>

        <p v-if="templates.loading" class="text-sm text-muted">Загрузка…</p>
        <ul v-else class="space-y-1.5">
          <li
            v-for="cat in templates.categories"
            :key="cat.id"
            class="rounded-xl border border-line bg-surface px-2.5 py-2"
          >
            <div v-if="editingCategoryId === cat.id" class="flex gap-1.5">
              <input
                v-model="editingCategoryName"
                class="min-w-0 flex-1 rounded-lg border border-line bg-panel px-2 py-1 text-sm outline-none ring-brand focus:ring-2"
                @keydown.enter.prevent="saveRenameCategory"
              />
              <button
                type="button"
                class="rounded-lg bg-brand px-2 py-1 text-xs font-semibold text-white"
                @click="saveRenameCategory"
              >
                OK
              </button>
            </div>
            <div v-else class="flex items-center justify-between gap-2">
              <button
                type="button"
                class="min-w-0 truncate text-left text-sm font-medium hover:text-brand"
                @click="categoryId = cat.id"
              >
                {{ cat.name }}
              </button>
              <div v-if="canWrite" class="flex shrink-0 gap-0.5">
                <button
                  type="button"
                  class="rounded-md p-1 text-muted hover:bg-panel hover:text-ink"
                  title="Переименовать"
                  @click="startRenameCategory(cat.id, cat.name)"
                >
                  <Pencil class="size-3.5" />
                </button>
                <button
                  type="button"
                  class="rounded-md p-1 text-muted hover:bg-panel hover:text-danger"
                  title="Удалить"
                  @click="removeCategory(cat.id)"
                >
                  <Trash2 class="size-3.5" />
                </button>
              </div>
            </div>
          </li>
          <li v-if="!templates.categories.length" class="px-1 py-2 text-sm text-muted">
            Пока нет категорий — создайте первую.
          </li>
        </ul>
      </section>

      <div class="space-y-6">
        <form
          v-if="canWrite"
          class="rounded-2xl border border-line bg-panel p-4"
          @submit.prevent="saveTemplate"
        >
          <h2 class="mb-3 text-sm font-semibold">
            {{ editingId ? 'Редактировать шаблон' : 'Новый шаблон' }}
          </h2>
          <p class="mb-3 text-xs text-muted">
            Плейсхолдеры:
            <span v-pre class="font-mono">{{operator}}</span>,
            <span v-pre class="font-mono">{{contact}}</span>
          </p>
          <div class="grid gap-3 sm:grid-cols-2">
            <label class="block sm:col-span-2">
              <span class="mb-1 block text-xs font-semibold text-muted">Название</span>
              <input
                v-model="name"
                required
                class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
              />
            </label>
            <label class="block sm:col-span-2">
              <span class="mb-1 block text-xs font-semibold text-muted">Текст</span>
              <textarea
                v-model="body"
                rows="4"
                placeholder="Можно оставить пустым, если есть картинки"
                class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
              />
            </label>
            <div class="block sm:col-span-2">
              <span class="mb-1 block text-xs font-semibold text-muted">
                Изображения
                <span class="font-normal">· {{ draftItems.length }}/{{ MAX_IMAGES }}</span>
              </span>
              <div
                class="rounded-xl border border-dashed px-3 py-4 transition"
                :class="
                  dragOver
                    ? 'border-brand bg-brand-soft/40'
                    : 'border-line bg-surface'
                "
                @dragenter.prevent="dragOver = true"
                @dragover.prevent="dragOver = true"
                @dragleave.prevent="dragOver = false"
                @drop.prevent="onDrop"
              >
                <div class="flex flex-wrap items-center gap-3">
                  <label
                    class="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-line bg-panel px-3 py-2 text-sm text-muted hover:border-brand/40 hover:text-ink"
                  >
                    <ImagePlus class="size-4" />
                    Выбрать файлы
                    <input
                      type="file"
                      accept="image/*"
                      multiple
                      class="hidden"
                      :disabled="draftItems.length >= MAX_IMAGES"
                      @change="onMediaChange"
                    />
                  </label>
                  <span class="text-xs text-muted">или перетащите сюда</span>
                </div>
                <div v-if="draftItems.length" class="mt-3 flex flex-wrap gap-2">
                  <div
                    v-for="(item, idx) in draftItems"
                    :key="item.key"
                    class="relative"
                  >
                    <img
                      :src="item.previewUrl"
                      :alt="item.name"
                      class="h-20 w-20 rounded-xl object-cover ring-1 ring-line"
                    />
                    <button
                      type="button"
                      class="absolute -right-1.5 -top-1.5 rounded-full bg-panel p-0.5 text-muted ring-1 ring-line hover:text-danger"
                      title="Убрать"
                      @click="removeDraftItem(idx)"
                    >
                      <X class="size-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
            <label class="block">
              <span class="mb-1 block text-xs font-semibold text-muted">Категория</span>
              <select
                v-model="categoryId"
                class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm"
              >
                <option value="">Без категории</option>
                <option v-for="cat in templates.categories" :key="cat.id" :value="cat.id">
                  {{ cat.name }}
                </option>
              </select>
            </label>
            <label class="block">
              <span class="mb-1 block text-xs font-semibold text-muted">Канал</span>
              <select
                v-model="transport"
                class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm"
              >
                <option value="all">Все каналы</option>
                <option
                  v-for="(label, key) in transportLabel"
                  :key="key"
                  :value="key"
                >
                  {{ label }}
                </option>
              </select>
            </label>
          </div>
          <div class="mt-4 flex flex-wrap gap-2">
            <button
              type="submit"
              class="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
              :disabled="saving || !canSave"
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

        <div class="space-y-5">
          <section v-for="group in grouped" :key="group.id ?? 'none'">
            <h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
              {{ group.name }}
              <span class="font-normal normal-case tracking-normal">
                · {{ group.items.length }}
              </span>
            </h3>
            <div
              v-if="!group.items.length"
              class="rounded-xl border border-dashed border-line px-3 py-4 text-sm text-muted"
            >
              Пусто
            </div>
            <div v-else class="space-y-2">
              <article
                v-for="t in group.items"
                :key="t.id"
                class="rounded-2xl border border-line bg-panel p-4"
              >
                <div class="mb-2 flex items-start justify-between gap-2">
                  <div>
                    <h4 class="text-sm font-semibold">{{ t.name }}</h4>
                    <p class="text-[11px] text-muted">
                      {{
                        t.transport === 'all'
                          ? 'Все каналы'
                          : transportLabel[t.transport]
                      }}
                      <span v-if="t.mediaCount">
                        · {{ t.mediaCount }}
                        {{ t.mediaCount === 1 ? 'изображение' : 'изобр.' }}
                      </span>
                    </p>
                  </div>
                  <div v-if="canWrite" class="flex gap-0.5">
                    <button
                      type="button"
                      class="rounded-lg p-1.5 text-muted hover:bg-surface hover:text-ink"
                      title="Редактировать"
                      @click="startEdit(t)"
                    >
                      <Pencil class="size-4" />
                    </button>
                    <button
                      type="button"
                      class="rounded-lg p-1.5 text-muted hover:bg-surface hover:text-danger"
                      title="Удалить"
                      @click="removeTemplate(t.id)"
                    >
                      <Trash2 class="size-4" />
                    </button>
                  </div>
                </div>
                <div class="flex gap-3">
                  <div
                    v-if="t.hasMedia"
                    class="flex h-16 w-16 shrink-0 items-center justify-center rounded-lg bg-surface text-muted ring-1 ring-line"
                    :title="`${t.mediaCount} изображений`"
                  >
                    <ImagePlus class="size-6" />
                  </div>
                  <p class="min-w-0 flex-1 whitespace-pre-wrap text-sm text-ink/90">
                    {{ t.body || '—' }}
                  </p>
                </div>
              </article>
            </div>
          </section>
        </div>
      </div>
    </div>
  </div>
</template>
