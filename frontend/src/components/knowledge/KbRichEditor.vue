<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import Image from '@tiptap/extension-image'
import Placeholder from '@tiptap/extension-placeholder'
import {
  Bold,
  Heading2,
  Heading3,
  ImagePlus,
  Italic,
  Link2,
  List,
  ListOrdered,
  Quote,
} from 'lucide-vue-next'
import { uploadKnowledgeImage } from '@/api/knowledge'
import { hydrateKbImages, serializeKbHtml } from '@/utils/knowledgeUi'

const props = defineProps<{
  modelValue: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const fileInput = ref<HTMLInputElement | null>(null)
const shell = ref<HTMLElement | null>(null)
const uploading = ref(false)
const uploadError = ref('')
const linkOpen = ref(false)
const linkUrl = ref('')
const initError = ref('')

const editor = useEditor({
  content: props.modelValue || '<p></p>',
  extensions: [
    StarterKit.configure({
      heading: { levels: [2, 3] },
      codeBlock: false,
      code: false,
      horizontalRule: false,
    }),
    Link.configure({
      openOnClick: false,
      autolink: true,
      HTMLAttributes: {
        class: 'text-brand underline underline-offset-2',
        rel: 'noopener noreferrer',
        target: '_blank',
      },
    }),
    Image.configure({
      allowBase64: false,
      HTMLAttributes: { class: 'kb-doc-img' },
    }),
    Placeholder.configure({
      placeholder: 'Пишите инструкцию… Выделите текст и оформите панелью сверху.',
    }),
  ],
  editorProps: {
    attributes: {
      class: 'kb-doc-editor outline-none',
      spellcheck: 'true',
    },
  },
  onUpdate: ({ editor: ed }) => {
    emit('update:modelValue', serializeKbHtml(ed.getHTML()))
    void nextTick(() => hydrateKbImages(shell.value))
  },
  onCreate: () => {
    void nextTick(() => hydrateKbImages(shell.value))
  },
})

watch(
  () => props.modelValue,
  (html) => {
    if (!editor.value) return
    const current = serializeKbHtml(editor.value.getHTML())
    if (html !== current) {
      editor.value.commands.setContent(html || '<p></p>', { emitUpdate: false })
      void nextTick(() => hydrateKbImages(shell.value))
    }
  },
)

onBeforeUnmount(() => {
  try {
    editor.value?.destroy()
  } catch {
    /* ignore */
  }
})

const active = computed(() => ({
  h2: editor.value?.isActive('heading', { level: 2 }) ?? false,
  h3: editor.value?.isActive('heading', { level: 3 }) ?? false,
  bold: editor.value?.isActive('bold') ?? false,
  italic: editor.value?.isActive('italic') ?? false,
  bullet: editor.value?.isActive('bulletList') ?? false,
  ordered: editor.value?.isActive('orderedList') ?? false,
  quote: editor.value?.isActive('blockquote') ?? false,
  link: editor.value?.isActive('link') ?? false,
}))

function chain() {
  return editor.value?.chain().focus()
}

function openLink() {
  if (!editor.value) return
  linkUrl.value = (editor.value.getAttributes('link').href as string) || 'https://'
  linkOpen.value = true
}

function applyLink() {
  const t = linkUrl.value.trim()
  if (!t) chain()?.extendMarkRange('link').unsetLink().run()
  else chain()?.extendMarkRange('link').setLink({ href: t }).run()
  linkOpen.value = false
}

function clearLink() {
  chain()?.extendMarkRange('link').unsetLink().run()
  linkOpen.value = false
}

async function onFile(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || !editor.value) return
  uploading.value = true
  uploadError.value = ''
  try {
    const { url } = await uploadKnowledgeImage(file)
    editor.value.chain().focus().setImage({ src: url }).run()
    await nextTick()
    shell.value?.querySelectorAll('img').forEach((img) => {
      const src = img.getAttribute('src')
      if (src === url || src?.startsWith('blob:')) img.setAttribute('data-kb-src', url)
    })
    await hydrateKbImages(shell.value)
    emit('update:modelValue', serializeKbHtml(editor.value.getHTML()))
  } catch (e) {
    uploadError.value = e instanceof Error ? e.message : 'Ошибка загрузки'
    initError.value = ''
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <div ref="shell" class="kb-doc">
    <!-- Sticky format bar — always outside the writing surface -->
    <div class="kb-doc-bar">
      <div class="kb-doc-bar-inner">
        <button
          type="button"
          class="kb-chip"
          :class="{ on: active.h2 }"
          @click="chain()?.toggleHeading({ level: 2 }).run()"
        >
          <Heading2 class="size-3.5" />
          H2
        </button>
        <button
          type="button"
          class="kb-chip"
          :class="{ on: active.h3 }"
          @click="chain()?.toggleHeading({ level: 3 }).run()"
        >
          <Heading3 class="size-3.5" />
          H3
        </button>
        <span class="kb-sep" />
        <button
          type="button"
          class="kb-chip"
          :class="{ on: active.bold }"
          @click="chain()?.toggleBold().run()"
        >
          <Bold class="size-3.5" />
          Жирный
        </button>
        <button
          type="button"
          class="kb-chip"
          :class="{ on: active.italic }"
          @click="chain()?.toggleItalic().run()"
        >
          <Italic class="size-3.5" />
          Курсив
        </button>
        <span class="kb-sep" />
        <button
          type="button"
          class="kb-chip"
          :class="{ on: active.bullet }"
          @click="chain()?.toggleBulletList().run()"
        >
          <List class="size-3.5" />
          Список
        </button>
        <button
          type="button"
          class="kb-chip"
          :class="{ on: active.ordered }"
          @click="chain()?.toggleOrderedList().run()"
        >
          <ListOrdered class="size-3.5" />
          1. 2. 3.
        </button>
        <button
          type="button"
          class="kb-chip"
          :class="{ on: active.quote }"
          @click="chain()?.toggleBlockquote().run()"
        >
          <Quote class="size-3.5" />
          Цитата
        </button>
        <span class="kb-sep" />
        <button type="button" class="kb-chip" :class="{ on: active.link || linkOpen }" @click="openLink">
          <Link2 class="size-3.5" />
          Ссылка
        </button>
        <button type="button" class="kb-chip" :disabled="uploading" @click="fileInput?.click()">
          <ImagePlus class="size-3.5" />
          {{ uploading ? '…' : 'Фото' }}
        </button>
        <input ref="fileInput" type="file" accept="image/*" class="hidden" @change="onFile" />
      </div>

      <div v-if="linkOpen" class="kb-link-row">
        <input
          v-model="linkUrl"
          type="url"
          class="kb-link-field"
          placeholder="https://example.com"
          @keydown.enter.prevent="applyLink"
        />
        <button type="button" class="kb-chip on" @click="applyLink">Готово</button>
        <button type="button" class="kb-chip" @click="clearLink">Убрать</button>
        <button type="button" class="kb-chip" @click="linkOpen = false">Закрыть</button>
      </div>
      <p v-if="uploadError" class="kb-err">{{ uploadError }}</p>
    </div>

    <div class="kb-doc-page">
      <EditorContent v-if="editor" :editor="editor" />
      <p v-else class="py-16 text-center text-sm text-muted">
        {{ initError || 'Загрузка редактора…' }}
      </p>
    </div>
  </div>
</template>
