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
  editable?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)
const uploadError = ref('')
const editorRoot = ref<HTMLElement | null>(null)
const linkOpen = ref(false)
const linkUrl = ref('')

const editor = useEditor({
  content: props.modelValue || '<p></p>',
  editable: props.editable !== false,
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
      HTMLAttributes: { class: 'kb-link', rel: 'noopener noreferrer', target: '_blank' },
    }),
    Image.configure({
      allowBase64: false,
      HTMLAttributes: { class: 'kb-img' },
    }),
    Placeholder.configure({
      placeholder: 'Начните текст статьи… Можно вставить заголовки, списки и картинки.',
    }),
  ],
  editorProps: {
    attributes: {
      class: 'kb-tiptap-body',
      spellcheck: 'true',
    },
  },
  onUpdate: ({ editor: ed }) => {
    emit('update:modelValue', serializeKbHtml(ed.getHTML()))
    void nextTick(() => hydrateKbImages(editorRoot.value))
  },
  onCreate: () => {
    void nextTick(() => hydrateKbImages(editorRoot.value))
  },
})

watch(
  () => props.modelValue,
  (html) => {
    if (!editor.value) return
    const current = serializeKbHtml(editor.value.getHTML())
    if (html !== current) {
      editor.value.commands.setContent(html || '<p></p>', { emitUpdate: false })
      void nextTick(() => hydrateKbImages(editorRoot.value))
    }
  },
)

watch(
  () => props.editable,
  (editable) => {
    editor.value?.setEditable(editable !== false)
  },
)

onBeforeUnmount(() => {
  editor.value?.destroy()
})

const ready = computed(() => Boolean(editor.value))
const canLink = computed(() => editor.value?.isActive('link') ?? false)

function run(cmd: () => void) {
  if (!editor.value) return
  cmd()
}

function openLinkPanel() {
  if (!editor.value) return
  linkUrl.value = (editor.value.getAttributes('link').href as string) || 'https://'
  linkOpen.value = true
}

function applyLink() {
  if (!editor.value) return
  const trimmed = linkUrl.value.trim()
  if (!trimmed) {
    editor.value.chain().focus().extendMarkRange('link').unsetLink().run()
  } else {
    editor.value.chain().focus().extendMarkRange('link').setLink({ href: trimmed }).run()
  }
  linkOpen.value = false
}

function removeLink() {
  editor.value?.chain().focus().extendMarkRange('link').unsetLink().run()
  linkOpen.value = false
}

function pickImage() {
  uploadError.value = ''
  fileInput.value?.click()
}

async function onFileChange(ev: Event) {
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
    editorRoot.value
      ?.querySelectorAll('img')
      .forEach((img) => {
        const src = img.getAttribute('src')
        if (src === url || src?.startsWith('blob:')) {
          img.setAttribute('data-kb-src', url)
        }
      })
    await hydrateKbImages(editorRoot.value)
    emit('update:modelValue', serializeKbHtml(editor.value.getHTML()))
  } catch (e) {
    uploadError.value = e instanceof Error ? e.message : 'Не удалось загрузить'
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <div ref="editorRoot" class="kb-editor">
    <div v-if="editable !== false" class="kb-toolbar">
      <div class="kb-toolbar-group">
        <button
          type="button"
          class="kb-tool"
          :class="{ 'is-on': editor?.isActive('heading', { level: 2 }) }"
          @click="run(() => editor!.chain().focus().toggleHeading({ level: 2 }).run())"
        >
          <Heading2 class="size-4" />
          <span>Заголовок</span>
        </button>
        <button
          type="button"
          class="kb-tool"
          :class="{ 'is-on': editor?.isActive('heading', { level: 3 }) }"
          @click="run(() => editor!.chain().focus().toggleHeading({ level: 3 }).run())"
        >
          <Heading3 class="size-4" />
          <span>Подзаголовок</span>
        </button>
      </div>
      <div class="kb-toolbar-group">
        <button
          type="button"
          class="kb-tool"
          :class="{ 'is-on': editor?.isActive('bold') }"
          title="Жирный"
          @click="run(() => editor!.chain().focus().toggleBold().run())"
        >
          <Bold class="size-4" />
          <span>Жирный</span>
        </button>
        <button
          type="button"
          class="kb-tool"
          :class="{ 'is-on': editor?.isActive('italic') }"
          title="Курсив"
          @click="run(() => editor!.chain().focus().toggleItalic().run())"
        >
          <Italic class="size-4" />
          <span>Курсив</span>
        </button>
      </div>
      <div class="kb-toolbar-group">
        <button
          type="button"
          class="kb-tool"
          :class="{ 'is-on': editor?.isActive('bulletList') }"
          @click="run(() => editor!.chain().focus().toggleBulletList().run())"
        >
          <List class="size-4" />
          <span>Список</span>
        </button>
        <button
          type="button"
          class="kb-tool"
          :class="{ 'is-on': editor?.isActive('orderedList') }"
          @click="run(() => editor!.chain().focus().toggleOrderedList().run())"
        >
          <ListOrdered class="size-4" />
          <span>Нумерация</span>
        </button>
        <button
          type="button"
          class="kb-tool"
          :class="{ 'is-on': editor?.isActive('blockquote') }"
          @click="run(() => editor!.chain().focus().toggleBlockquote().run())"
        >
          <Quote class="size-4" />
          <span>Цитата</span>
        </button>
      </div>
      <div class="kb-toolbar-group">
        <button
          type="button"
          class="kb-tool"
          :class="{ 'is-on': canLink || linkOpen }"
          @click="openLinkPanel"
        >
          <Link2 class="size-4" />
          <span>Ссылка</span>
        </button>
        <button type="button" class="kb-tool" :disabled="uploading" @click="pickImage">
          <ImagePlus class="size-4" />
          <span>{{ uploading ? 'Загрузка…' : 'Картинка' }}</span>
        </button>
      </div>
      <input ref="fileInput" type="file" accept="image/*" class="hidden" @change="onFileChange" />
    </div>

    <div v-if="linkOpen" class="kb-link-bar">
      <input
        v-model="linkUrl"
        type="url"
        placeholder="https://…"
        class="kb-link-input"
        @keydown.enter.prevent="applyLink"
      />
      <button type="button" class="kb-link-btn primary" @click="applyLink">Ок</button>
      <button type="button" class="kb-link-btn" @click="removeLink">Убрать</button>
      <button type="button" class="kb-link-btn" @click="linkOpen = false">Закрыть</button>
    </div>

    <p v-if="uploadError" class="kb-upload-err">{{ uploadError }}</p>

    <div class="kb-editor-surface">
      <EditorContent v-if="ready" :editor="editor" />
      <p v-else class="kb-editor-loading">Подготовка редактора…</p>
    </div>
  </div>
</template>

<style>
.kb-editor {
  display: flex;
  flex-direction: column;
  min-height: 420px;
  overflow: hidden;
  border: 1px solid var(--color-line);
  border-radius: 1rem;
  background: var(--color-panel);
  box-shadow: 0 1px 2px color-mix(in srgb, var(--color-ink) 4%, transparent);
}

.kb-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  align-items: center;
  padding: 0.65rem 0.75rem;
  border-bottom: 1px solid var(--color-line);
  background: linear-gradient(
    180deg,
    color-mix(in srgb, var(--color-surface) 92%, #fff),
    var(--color-surface)
  );
}

.kb-toolbar-group {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  padding-right: 0.45rem;
  margin-right: 0.2rem;
  border-right: 1px solid color-mix(in srgb, var(--color-line) 85%, transparent);
}

.kb-toolbar-group:last-of-type {
  border-right: 0;
  margin-right: 0;
  padding-right: 0;
}

.kb-tool {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  height: 2.15rem;
  padding: 0 0.7rem;
  border: 1px solid transparent;
  border-radius: 0.65rem;
  background: transparent;
  color: var(--color-ink);
  font-size: 0.75rem;
  font-weight: 600;
  line-height: 1;
  cursor: pointer;
  transition:
    background 0.15s,
    border-color 0.15s,
    color 0.15s;
}

.kb-tool:hover:not(:disabled) {
  background: var(--color-panel);
  border-color: var(--color-line);
}

.kb-tool.is-on {
  background: var(--color-brand-soft);
  border-color: color-mix(in srgb, var(--color-brand) 25%, var(--color-line));
  color: var(--color-brand);
}

.kb-tool:disabled {
  opacity: 0.45;
  cursor: default;
}

.kb-tool span {
  white-space: nowrap;
}

@media (max-width: 640px) {
  .kb-tool span {
    display: none;
  }
  .kb-tool {
    width: 2.15rem;
    padding: 0;
    justify-content: center;
  }
}

.kb-link-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  align-items: center;
  padding: 0.55rem 0.75rem;
  border-bottom: 1px solid var(--color-line);
  background: var(--color-brand-soft);
}

.kb-link-input {
  flex: 1 1 12rem;
  min-width: 10rem;
  height: 2.1rem;
  padding: 0 0.75rem;
  border: 1px solid var(--color-line);
  border-radius: 0.65rem;
  background: var(--color-panel);
  color: var(--color-ink);
  font-size: 0.8125rem;
  outline: none;
}

.kb-link-input:focus {
  border-color: var(--color-brand);
}

.kb-link-btn {
  height: 2.1rem;
  padding: 0 0.75rem;
  border: 1px solid var(--color-line);
  border-radius: 0.65rem;
  background: var(--color-panel);
  color: var(--color-ink);
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
}

.kb-link-btn.primary {
  border-color: var(--color-brand);
  background: var(--color-brand);
  color: #fff;
}

.kb-upload-err {
  margin: 0;
  padding: 0.4rem 0.85rem;
  font-size: 0.75rem;
  color: var(--color-danger);
  background: var(--color-danger-soft);
}

.kb-editor-surface {
  flex: 1 1 auto;
  min-height: 320px;
  padding: 1rem 1.1rem 1.35rem;
  background:
    radial-gradient(
      ellipse 80% 50% at 0% 0%,
      color-mix(in srgb, var(--color-brand) 5%, transparent),
      transparent 55%
    ),
    var(--color-panel);
}

.kb-editor-loading {
  margin: 2rem 0;
  text-align: center;
  font-size: 0.875rem;
  color: var(--color-muted);
}

.kb-tiptap-body {
  min-height: 280px;
  outline: none;
  font-size: 1rem;
  line-height: 1.75;
  color: var(--color-ink);
}

.kb-tiptap-body p {
  margin: 0.55em 0;
}

.kb-tiptap-body h2 {
  margin: 1.15em 0 0.4em;
  font-size: 1.4rem;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.kb-tiptap-body h3 {
  margin: 1em 0 0.35em;
  font-size: 1.12rem;
  font-weight: 650;
}

.kb-tiptap-body ul {
  list-style: disc;
  padding-left: 1.4rem;
  margin: 0.55em 0;
}

.kb-tiptap-body ol {
  list-style: decimal;
  padding-left: 1.4rem;
  margin: 0.55em 0;
}

.kb-tiptap-body blockquote {
  margin: 0.85em 0;
  border-left: 3px solid var(--color-brand);
  padding-left: 0.9rem;
  color: var(--color-muted);
  font-style: italic;
}

.kb-tiptap-body a.kb-link {
  color: var(--color-brand);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.kb-tiptap-body img,
.kb-img {
  display: block;
  max-width: 100%;
  height: auto;
  margin: 1rem 0;
  border-radius: 0.75rem;
  border: 1px solid var(--color-line);
}

.kb-tiptap-body p.is-editor-empty:first-child::before {
  content: attr(data-placeholder);
  float: left;
  height: 0;
  pointer-events: none;
  color: color-mix(in srgb, var(--color-muted) 75%, transparent);
  font-style: normal;
}
</style>
