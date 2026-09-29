<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  Braces,
  FileText,
  FolderPlus,
  ImagePlus,
  Pencil,
  Save,
  Smile,
  Trash2,
  X,
} from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
import { useMyTemplatesStore } from '@/stores/myTemplates'
import { fetchMyTemplateMediaBlob } from '@/api/cabinet'
import SoftSelect from '@/components/ui/SoftSelect.vue'
import type { ChannelTransport, Template, TemplateKind } from '@/types'
import { transportLabel } from '@/types'
import {
  TEMPLATE_CATEGORY_ICONS,
  resolveCategoryIcon,
  type TemplateCategoryIconKey,
} from '@/utils/templateCategoryIcons'

const MAX_IMAGES = 10
const NAME_MAX = 100
const BODY_MAX = 1000
const BODY_PLACEHOLDER =
  'Введите текст шаблона. Можно использовать {{operator}} и {{contact}}'

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
const route = useRoute()
const router = useRouter()
const canWrite = computed(() => auth.can('action.write'))

const formOpen = ref(false)
const showNewCategory = ref(false)
const categoryName = ref('')
const categoryIcon = ref<TemplateCategoryIconKey | null>(null)
const editingCategoryId = ref<string | null>(null)
const editingCategoryName = ref('')
const editingCategoryIcon = ref<TemplateCategoryIconKey | null>(null)

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

const pageTitle = computed(() =>
  editingId.value ? 'Редактирование шаблона' : 'Создание шаблона',
)

const pageSubtitle = computed(() =>
  editingId.value
    ? 'Измените данные и сохраните шаблон'
    : 'Заполните данные, чтобы сохранить новый шаблон',
)

const previewTitle = computed(() => name.value.trim() || 'Акция')
const previewBody = computed(
  () =>
    body.value.trim() ||
    'С 1 по 7 число комиссия 0%. Успейте воспользоваться предложением!',
)

const grouped = computed(() => {
  const groups: {
    id: string | null
    name: string
    icon: string | null
    items: Template[]
  }[] = []
  for (const cat of templates.categories) {
    const items = templates.templates.filter((t) => t.categoryId === cat.id)
    groups.push({ id: cat.id, name: cat.name, icon: cat.icon, items })
  }
  const uncategorized = templates.templates.filter((t) => !t.categoryId)
  if (uncategorized.length || !templates.categories.length) {
    groups.push({ id: null, name: 'Без категории', icon: null, items: uncategorized })
  }
  return groups
})

const categoryOptions = computed(() => [
  { value: '', label: 'Выберите категорию' },
  ...templates.categories.map((c) => ({ value: c.id, label: c.name })),
])

const transportOptions = computed(() => [
  { value: 'all', label: 'Все каналы' },
  ...Object.entries(transportLabel).map(([value, label]) => ({ value, label })),
])

const kindOptions = [
  { value: 'general', label: 'Обычный ответ' },
  { value: 'appeal_closed', label: 'При закрытии обращения' },
]

onMounted(async () => {
  await templates.fetchAll()
  openEditFromQuery()
})

watch(
  () => route.query.edit,
  () => {
    openEditFromQuery()
  },
)

function openEditFromQuery() {
  const raw = route.query.edit
  const id = typeof raw === 'string' ? raw : Array.isArray(raw) ? raw[0] : null
  if (!id || !canWrite.value) return
  const tpl = templates.templates.find((t) => t.id === id)
  if (!tpl) return
  startEdit(tpl)
  const nextQuery = { ...route.query }
  delete nextQuery.edit
  void router.replace({ query: nextQuery })
}

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
  showNewCategory.value = false
  categoryName.value = ''
  categoryIcon.value = null
  clearDraft()
}

function openCreate() {
  resetForm()
  formOpen.value = true
}

function closeForm() {
  resetForm()
  formOpen.value = false
}

function startEdit(t: Template) {
  editingId.value = t.id
  name.value = t.name
  body.value = t.body
  transport.value = t.transport
  kind.value = t.kind
  categoryId.value = t.categoryId ?? ''
  showNewCategory.value = false
  clearDraft()
  formOpen.value = true
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
  const created = await templates.addCategory(
    categoryName.value.trim(),
    categoryIcon.value,
  )
  savingCategory.value = false
  if (!created) return
  categoryName.value = ''
  categoryIcon.value = null
  showNewCategory.value = false
  categoryId.value = created.id
}

function startRenameCategory(id: string, current: string, icon: string | null) {
  editingCategoryId.value = id
  editingCategoryName.value = current
  editingCategoryIcon.value =
    icon && TEMPLATE_CATEGORY_ICONS.some((i) => i.key === icon)
      ? (icon as TemplateCategoryIconKey)
      : null
}

async function saveRenameCategory() {
  if (!editingCategoryId.value || !editingCategoryName.value.trim()) return
  const ok = await templates.updateCategory(editingCategoryId.value, {
    name: editingCategoryName.value.trim(),
    icon: editingCategoryIcon.value,
  })
  if (ok) {
    editingCategoryId.value = null
    editingCategoryName.value = ''
    editingCategoryIcon.value = null
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
      name: name.value.trim().slice(0, NAME_MAX),
      body: body.value.trim().slice(0, BODY_MAX),
      transport: transport.value,
      kind: kind.value,
      categoryId: cat,
      media: newFiles,
      removeAttachmentIds: removedAttachmentIds.value,
    })
  } else {
    ok = await templates.addTemplate({
      name: name.value.trim().slice(0, NAME_MAX),
      body: body.value.trim().slice(0, BODY_MAX),
      transport: transport.value,
      kind: kind.value,
      categoryId: cat,
      media: newFiles,
    })
  }
  saving.value = false
  if (!ok) return
  closeForm()
}

async function removeTemplate(id: string) {
  if (!confirm('Удалить шаблон?')) return
  await templates.removeTemplate(id)
  if (editingId.value === id) closeForm()
}
</script>

<template>
  <div class="h-full overflow-auto">
    <!-- Form mode (create / edit) — matches mockup -->
    <div v-if="formOpen" class="mx-auto max-w-6xl p-4 sm:p-6">
      <header class="mb-6 flex items-start gap-3">
        <button
          type="button"
          class="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-xl text-muted transition hover:bg-panel hover:text-ink"
          aria-label="Назад"
          @click="closeForm"
        >
          <ArrowLeft class="size-5" />
        </button>
        <div class="min-w-0">
          <h1 class="text-xl font-bold tracking-tight text-ink sm:text-2xl">
            {{ pageTitle }}
          </h1>
          <p class="mt-1 text-sm text-muted">{{ pageSubtitle }}</p>
        </div>
      </header>

      <p v-if="templates.error" class="mb-4 text-sm text-danger">{{ templates.error }}</p>

      <div class="grid gap-6 lg:grid-cols-[minmax(240px,300px)_1fr]">
        <!-- Left tips -->
        <aside class="space-y-5">
          <div>
            <h2 class="mb-2 text-sm font-semibold text-ink">Пример</h2>
            <div class="rounded-2xl border border-line bg-panel p-4 shadow-sm">
              <div class="flex gap-3">
                <div
                  class="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand-soft text-brand"
                >
                  <Smile class="size-5" />
                </div>
                <div class="min-w-0">
                  <p class="text-sm font-bold text-ink">{{ previewTitle }}</p>
                  <p class="mt-1 text-sm leading-relaxed text-muted">{{ previewBody }}</p>
                </div>
              </div>
            </div>
          </div>

          <div class="space-y-4">
            <div class="flex gap-3">
              <div
                class="flex size-9 shrink-0 items-center justify-center rounded-xl bg-surface text-muted ring-1 ring-line"
              >
                <Braces class="size-4" />
              </div>
              <div class="min-w-0">
                <p class="text-sm font-semibold text-ink">Плейсхолдеры</p>
                <p class="mt-0.5 text-xs leading-relaxed text-muted">
                  Используйте
                  <span v-pre class="font-mono text-ink">{{operator}}</span>
                  и
                  <span v-pre class="font-mono text-ink">{{contact}}</span>
                  для автоподстановки данных.
                </p>
              </div>
            </div>
            <div class="flex gap-3">
              <div
                class="flex size-9 shrink-0 items-center justify-center rounded-xl bg-surface text-muted ring-1 ring-line"
              >
                <ImagePlus class="size-4" />
              </div>
              <div class="min-w-0">
                <p class="text-sm font-semibold text-ink">Изображения</p>
                <p class="mt-0.5 text-xs leading-relaxed text-muted">
                  Можно прикрепить до {{ MAX_IMAGES }} изображений к шаблону.
                </p>
              </div>
            </div>
            <div class="flex gap-3">
              <div
                class="flex size-9 shrink-0 items-center justify-center rounded-xl bg-surface text-muted ring-1 ring-line"
              >
                <FileText class="size-4" />
              </div>
              <div class="min-w-0">
                <p class="text-sm font-semibold text-ink">Форматирование</p>
                <p class="mt-0.5 text-xs leading-relaxed text-muted">
                  Сообщения лучше делать короткими и понятными для SMS и чатов.
                </p>
              </div>
            </div>
          </div>
        </aside>

        <!-- Right form -->
        <form
          class="rounded-2xl border border-line bg-panel p-5 shadow-sm sm:p-6"
          @submit.prevent="saveTemplate"
        >
          <section class="space-y-4">
            <h2 class="text-base font-bold text-ink">Основная информация</h2>

            <label class="block">
              <span class="mb-1.5 block text-sm font-medium text-ink">
                Название шаблона <span class="text-brand">*</span>
              </span>
              <div class="relative">
                <input
                  v-model="name"
                  required
                  :maxlength="NAME_MAX"
                  placeholder="Например, Акция, Приветствие, Новая регистрация"
                  class="w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 pr-16 text-sm outline-none ring-brand/20 placeholder:text-muted/70 focus:ring-2"
                />
                <span
                  class="pointer-events-none absolute bottom-2.5 right-3 text-[11px] tabular-nums text-muted"
                >
                  {{ name.length }}/{{ NAME_MAX }}
                </span>
              </div>
            </label>

            <label class="block">
              <span class="mb-1.5 block text-sm font-medium text-ink">
                Текст сообщения <span class="text-brand">*</span>
              </span>
              <div class="relative">
                <textarea
                  v-model="body"
                  :maxlength="BODY_MAX"
                  rows="6"
                  :placeholder="BODY_PLACEHOLDER"
                  class="w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 pb-7 text-sm outline-none ring-brand/20 placeholder:text-muted/70 focus:ring-2"
                />
                <span
                  class="pointer-events-none absolute bottom-2.5 right-3 text-[11px] tabular-nums text-muted"
                >
                  {{ body.length }}/{{ BODY_MAX }}
                </span>
              </div>
            </label>

            <div>
              <span class="mb-1.5 block text-sm font-medium text-ink">Изображения</span>
              <div
                class="rounded-xl border border-dashed px-4 py-5 transition"
                :class="
                  dragOver ? 'border-brand bg-brand-soft/40' : 'border-line bg-surface'
                "
                @dragenter.prevent="dragOver = true"
                @dragover.prevent="dragOver = true"
                @dragleave.prevent="dragOver = false"
                @drop.prevent="onDrop"
              >
                <div class="flex flex-wrap items-center gap-3">
                  <label
                    class="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-line bg-panel px-3.5 py-2 text-sm font-medium text-ink transition hover:border-brand/40"
                  >
                    <ImagePlus class="size-4 text-brand" />
                    Выбрать файлы
                    <input
                      type="file"
                      accept="image/jpeg,image/png,image/webp,image/*"
                      multiple
                      class="hidden"
                      :disabled="draftItems.length >= MAX_IMAGES"
                      @change="onMediaChange"
                    />
                  </label>
                  <span class="text-sm text-muted">или перетащите сюда</span>
                </div>
                <p class="mt-2 text-xs text-muted">
                  До {{ MAX_IMAGES }} изображений. Форматы: JPG, PNG, WEBP. Размер до 5 МБ.
                </p>
                <div v-if="draftItems.length" class="mt-3 flex flex-wrap gap-2">
                  <div v-for="(item, idx) in draftItems" :key="item.key" class="relative">
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
          </section>

          <section class="mt-8 space-y-4">
            <h2 class="text-base font-bold text-ink">Категории и каналы</h2>
            <div class="grid gap-4 sm:grid-cols-2">
              <div>
                <div class="block">
                  <span class="mb-1.5 block text-sm font-medium text-ink">
                    Категория <span class="text-brand">*</span>
                  </span>
                  <SoftSelect
                    v-model="categoryId"
                    :options="categoryOptions"
                    placeholder="Выберите категорию"
                    aria-label="Категория"
                  />
                </div>
                <button
                  v-if="canWrite"
                  type="button"
                  class="mt-2 inline-flex items-center gap-1.5 text-xs font-semibold text-brand hover:underline"
                  @click="showNewCategory = !showNewCategory"
                >
                  <FolderPlus class="size-3.5" />
                  {{ showNewCategory ? 'Скрыть' : 'Новая категория' }}
                </button>
                <div
                  v-if="showNewCategory"
                  class="mt-2 space-y-2 rounded-xl border border-line bg-surface p-3"
                >
                  <input
                    v-model="categoryName"
                    placeholder="Название категории"
                    class="w-full rounded-lg border border-line bg-panel px-3 py-2 text-sm outline-none ring-brand/20 focus:ring-2"
                    @keydown.enter.prevent="addCategory"
                  />
                  <div class="flex flex-wrap gap-1">
                    <button
                      v-for="opt in TEMPLATE_CATEGORY_ICONS"
                      :key="opt.key"
                      type="button"
                      class="flex size-8 items-center justify-center rounded-lg border transition"
                      :class="
                        categoryIcon === opt.key
                          ? 'border-brand bg-brand-soft text-brand'
                          : 'border-line bg-panel text-muted hover:text-ink'
                      "
                      :title="opt.label"
                      @click="categoryIcon = categoryIcon === opt.key ? null : opt.key"
                    >
                      <component :is="opt.icon" class="size-3.5" />
                    </button>
                  </div>
                  <button
                    type="button"
                    class="rounded-lg bg-brand px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
                    :disabled="savingCategory || !categoryName.trim()"
                    @click="addCategory"
                  >
                    {{ savingCategory ? '…' : 'Добавить категорию' }}
                  </button>
                </div>
              </div>

              <div class="block">
                <span class="mb-1.5 block text-sm font-medium text-ink">
                  Канал <span class="text-brand">*</span>
                </span>
                <SoftSelect
                  v-model="transport"
                  :options="transportOptions"
                  aria-label="Канал"
                />
              </div>

              <div class="block sm:col-span-2 sm:max-w-xs">
                <span class="mb-1.5 block text-sm font-medium text-ink">Тип</span>
                <SoftSelect
                  v-model="kind"
                  :options="kindOptions"
                  aria-label="Тип шаблона"
                />
              </div>
            </div>
          </section>

          <div class="mt-8 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
            <button
              type="button"
              class="rounded-xl border border-line bg-panel px-5 py-2.5 text-sm font-semibold text-ink transition hover:bg-surface"
              @click="closeForm"
            >
              Отмена
            </button>
            <button
              type="submit"
              class="inline-flex items-center gap-2 rounded-xl bg-brand px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:opacity-95 disabled:opacity-50"
              :disabled="saving || !canSave"
            >
              <Save class="size-4" />
              {{ saving ? 'Сохранение…' : 'Сохранить шаблон' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- List mode -->
    <div v-else class="mx-auto max-w-6xl p-4 sm:p-6">
      <header class="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 class="text-xl font-bold tracking-tight text-ink sm:text-2xl">Мои шаблоны</h1>
          <p class="mt-1 text-sm text-muted">
            Личные ответы с категориями — видны только вам.
          </p>
        </div>
        <button
          v-if="canWrite"
          type="button"
          class="inline-flex items-center gap-2 rounded-xl bg-brand px-4 py-2.5 text-sm font-semibold text-white shadow-sm"
          @click="openCreate"
        >
          <FolderPlus class="size-4" />
          Создать шаблон
        </button>
      </header>

      <p v-if="templates.error" class="mb-4 text-sm text-danger">{{ templates.error }}</p>

      <div class="mb-6 grid gap-6 lg:grid-cols-[280px_1fr]">
        <section class="rounded-2xl border border-line bg-panel p-4 shadow-sm">
          <h2 class="mb-3 text-sm font-bold text-ink">Категории</h2>
          <form
            v-if="canWrite"
            class="mb-3 space-y-2"
            @submit.prevent="addCategory"
          >
            <div class="flex gap-2">
              <input
                v-model="categoryName"
                required
                placeholder="Новая категория"
                class="min-w-0 flex-1 rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none ring-brand/20 focus:ring-2"
              />
              <button
                type="submit"
                class="inline-flex shrink-0 items-center justify-center rounded-xl bg-brand px-3 py-2 text-white disabled:opacity-50"
                :disabled="savingCategory"
                title="Добавить"
              >
                <FolderPlus class="size-4" />
              </button>
            </div>
            <div class="flex flex-wrap gap-1">
              <button
                v-for="opt in TEMPLATE_CATEGORY_ICONS"
                :key="opt.key"
                type="button"
                class="flex size-8 items-center justify-center rounded-lg border transition"
                :class="
                  categoryIcon === opt.key
                    ? 'border-brand bg-brand-soft text-brand'
                    : 'border-line bg-surface text-muted hover:text-ink'
                "
                :title="opt.label"
                @click="categoryIcon = categoryIcon === opt.key ? null : opt.key"
              >
                <component :is="opt.icon" class="size-3.5" />
              </button>
            </div>
          </form>

          <p v-if="templates.loading" class="text-sm text-muted">Загрузка…</p>
          <ul v-else class="space-y-1.5">
            <li
              v-for="cat in templates.categories"
              :key="cat.id"
              class="rounded-xl border border-line bg-surface px-2.5 py-2"
            >
              <div v-if="editingCategoryId === cat.id" class="space-y-2">
                <div class="flex gap-1.5">
                  <input
                    v-model="editingCategoryName"
                    class="min-w-0 flex-1 rounded-lg border border-line bg-panel px-2 py-1 text-sm outline-none ring-brand/20 focus:ring-2"
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
                <div class="flex flex-wrap gap-1">
                  <button
                    v-for="opt in TEMPLATE_CATEGORY_ICONS"
                    :key="opt.key"
                    type="button"
                    class="flex size-7 items-center justify-center rounded-lg border transition"
                    :class="
                      editingCategoryIcon === opt.key
                        ? 'border-brand bg-brand-soft text-brand'
                        : 'border-line bg-panel text-muted hover:text-ink'
                    "
                    :title="opt.label"
                    @click="
                      editingCategoryIcon =
                        editingCategoryIcon === opt.key ? null : opt.key
                    "
                  >
                    <component :is="opt.icon" class="size-3.5" />
                  </button>
                </div>
              </div>
              <div v-else class="flex items-center justify-between gap-2">
                <div class="flex min-w-0 items-center gap-2 text-sm font-medium">
                  <component
                    :is="resolveCategoryIcon(cat.icon, cat.name)"
                    class="size-3.5 shrink-0 text-muted"
                  />
                  <span class="truncate">{{ cat.name }}</span>
                </div>
                <div v-if="canWrite" class="flex shrink-0 gap-0.5">
                  <button
                    type="button"
                    class="rounded-md p-1 text-muted hover:bg-panel hover:text-ink"
                    title="Изменить"
                    @click="startRenameCategory(cat.id, cat.name, cat.icon)"
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

        <div class="space-y-5">
          <p v-if="templates.loading" class="text-sm text-muted">Загрузка шаблонов…</p>
          <template v-else>
            <section v-for="group in grouped" :key="group.id ?? 'none'">
              <h3 class="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted">
                <component
                  :is="resolveCategoryIcon(group.icon, group.name)"
                  class="size-3.5"
                />
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
                  class="rounded-2xl border border-line bg-panel p-4 shadow-sm"
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
          </template>
        </div>
      </div>
    </div>
  </div>
</template>
