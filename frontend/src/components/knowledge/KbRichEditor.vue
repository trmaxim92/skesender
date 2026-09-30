<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import Image from '@tiptap/extension-image'
import Placeholder from '@tiptap/extension-placeholder'
import TextAlign from '@tiptap/extension-text-align'
import Underline from '@tiptap/extension-underline'
import {
  AlignCenter,
  AlignLeft,
  AlignRight,
  Bold,
  ImagePlus,
  Italic,
  Link2,
  List,
  ListOrdered,
  Minus,
  Quote,
  Redo2,
  Undo2,
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

const editor = useEditor({
  content: props.modelValue || '<p></p>',
  extensions: [
    StarterKit.configure({
      heading: { levels: [1, 2, 3] },
      codeBlock: false,
      code: false,
    }),
    Underline,
    TextAlign.configure({
      types: ['heading', 'paragraph'],
      alignments: ['left', 'center', 'right'],
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
      placeholder: 'Начните писать инструкцию…',
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
  h1: editor.value?.isActive('heading', { level: 1 }) ?? false,
  h2: editor.value?.isActive('heading', { level: 2 }) ?? false,
  h3: editor.value?.isActive('heading', { level: 3 }) ?? false,
  bold: editor.value?.isActive('bold') ?? false,
  italic: editor.value?.isActive('italic') ?? false,
  bullet: editor.value?.isActive('bulletList') ?? false,
  ordered: editor.value?.isActive('orderedList') ?? false,
  quote: editor.value?.isActive('blockquote') ?? false,
  link: editor.value?.isActive('link') ?? false,
  left: editor.value?.isActive({ textAlign: 'left' }) ?? false,
  center: editor.value?.isActive({ textAlign: 'center' }) ?? false,
  right: editor.value?.isActive({ textAlign: 'right' }) ?? false,
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
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <div ref="shell" class="kb-doc">
    <div class="kb-doc-bar">
      <div class="kb-doc-bar-inner">
        <button
          type="button"
          class="kb-tool"
          title="Заголовок 1"
          :class="{ on: active.h1 }"
          @click="chain()?.toggleHeading({ level: 1 }).run()"
        >
          H1
        </button>
        <button
          type="button"
          class="kb-tool"
          title="Заголовок 2"
          :class="{ on: active.h2 }"
          @click="chain()?.toggleHeading({ level: 2 }).run()"
        >
          H2
        </button>
        <button
          type="button"
          class="kb-tool"
          title="Заголовок 3"
          :class="{ on: active.h3 }"
          @click="chain()?.toggleHeading({ level: 3 }).run()"
        >
          H3
        </button>
        <span class="kb-sep" />
        <button
          type="button"
          class="kb-tool"
          title="Жирный"
          :class="{ on: active.bold }"
          @click="chain()?.toggleBold().run()"
        >
          <Bold class="size-3.5" />
        </button>
        <button
          type="button"
          class="kb-tool"
          title="Курсив"
          :class="{ on: active.italic }"
          @click="chain()?.toggleItalic().run()"
        >
          <Italic class="size-3.5" />
        </button>
        <span class="kb-sep" />
        <button
          type="button"
          class="kb-tool"
          title="Ссылка"
          :class="{ on: active.link || linkOpen }"
          @click="openLink"
        >
          <Link2 class="size-3.5" />
        </button>
        <button
          type="button"
          class="kb-tool"
          title="Маркированный список"
          :class="{ on: active.bullet }"
          @click="chain()?.toggleBulletList().run()"
        >
          <List class="size-3.5" />
        </button>
        <button
          type="button"
          class="kb-tool"
          title="Нумерованный список"
          :class="{ on: active.ordered }"
          @click="chain()?.toggleOrderedList().run()"
        >
          <ListOrdered class="size-3.5" />
        </button>
        <span class="kb-sep" />
        <button
          type="button"
          class="kb-tool"
          title="По левому краю"
          :class="{ on: active.left }"
          @click="chain()?.setTextAlign('left').run()"
        >
          <AlignLeft class="size-3.5" />
        </button>
        <button
          type="button"
          class="kb-tool"
          title="По центру"
          :class="{ on: active.center }"
          @click="chain()?.setTextAlign('center').run()"
        >
          <AlignCenter class="size-3.5" />
        </button>
        <button
          type="button"
          class="kb-tool"
          title="По правому краю"
          :class="{ on: active.right }"
          @click="chain()?.setTextAlign('right').run()"
        >
          <AlignRight class="size-3.5" />
        </button>
        <span class="kb-sep" />
        <button
          type="button"
          class="kb-tool"
          title="Цитата / важно"
          :class="{ on: active.quote }"
          @click="chain()?.toggleBlockquote().run()"
        >
          <Quote class="size-3.5" />
        </button>
        <button
          type="button"
          class="kb-tool"
          title="Изображение"
          :disabled="uploading"
          @click="fileInput?.click()"
        >
          <ImagePlus class="size-3.5" />
        </button>
        <button
          type="button"
          class="kb-tool"
          title="Разделитель"
          @click="chain()?.setHorizontalRule().run()"
        >
          <Minus class="size-3.5" />
        </button>
        <span class="kb-sep" />
        <button type="button" class="kb-tool" title="Отменить" @click="chain()?.undo().run()">
          <Undo2 class="size-3.5" />
        </button>
        <button type="button" class="kb-tool" title="Повторить" @click="chain()?.redo().run()">
          <Redo2 class="size-3.5" />
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
        <button type="button" class="kb-tool on" @click="applyLink">OK</button>
        <button type="button" class="kb-tool" @click="clearLink">Убрать</button>
        <button type="button" class="kb-tool" @click="linkOpen = false">✕</button>
      </div>
      <p v-if="uploadError" class="kb-err">{{ uploadError }}</p>
    </div>

    <div class="kb-doc-page">
      <EditorContent v-if="editor" :editor="editor" />
      <p v-else class="py-16 text-center text-sm text-muted">Загрузка редактора…</p>
    </div>
  </div>
</template>
