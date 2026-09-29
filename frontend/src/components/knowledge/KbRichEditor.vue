<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import Image from '@tiptap/extension-image'
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

const editor = useEditor({
  content: props.modelValue || '',
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
      HTMLAttributes: { class: 'kb-link', rel: 'noopener noreferrer', target: '_blank' },
    }),
    Image.configure({
      allowBase64: false,
      HTMLAttributes: { class: 'kb-img' },
    }),
  ],
  editorProps: {
    attributes: {
      class: 'kb-tiptap-body outline-none min-h-[220px] px-1 py-1',
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
      editor.value.commands.setContent(html || '', { emitUpdate: false })
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

const canLink = computed(() => editor.value?.isActive('link') ?? false)

function setLink() {
  if (!editor.value) return
  const prev = editor.value.getAttributes('link').href as string | undefined
  const url = window.prompt('Ссылка (https://…)', prev || 'https://')
  if (url === null) return
  const trimmed = url.trim()
  if (!trimmed) {
    editor.value.chain().focus().extendMarkRange('link').unsetLink().run()
    return
  }
  editor.value.chain().focus().extendMarkRange('link').setLink({ href: trimmed }).run()
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
    editor.value
      .chain()
      .focus()
      .setImage({ src: url })
      .run()
    // Mark original path for serialize + hydrate to blob for preview.
    await nextTick()
    const imgs = editorRoot.value?.querySelectorAll(`img[src="${CSS.escape(url)}"]`)
    imgs?.forEach((img) => img.setAttribute('data-kb-src', url))
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
  <div ref="editorRoot" class="kb-editor overflow-hidden rounded-xl border border-line bg-panel">
    <div
      v-if="editable !== false"
      class="flex flex-wrap items-center gap-0.5 border-b border-line bg-surface/80 px-2 py-1.5"
    >
      <button
        type="button"
        class="kb-toolbar-btn"
        :class="{ 'is-on': editor?.isActive('heading', { level: 2 }) }"
        title="Заголовок H2"
        @click="editor?.chain().focus().toggleHeading({ level: 2 }).run()"
      >
        <Heading2 class="size-4" />
      </button>
      <button
        type="button"
        class="kb-toolbar-btn"
        :class="{ 'is-on': editor?.isActive('heading', { level: 3 }) }"
        title="Заголовок H3"
        @click="editor?.chain().focus().toggleHeading({ level: 3 }).run()"
      >
        <Heading3 class="size-4" />
      </button>
      <span class="mx-1 h-4 w-px bg-line" />
      <button
        type="button"
        class="kb-toolbar-btn"
        :class="{ 'is-on': editor?.isActive('bold') }"
        title="Жирный"
        @click="editor?.chain().focus().toggleBold().run()"
      >
        <Bold class="size-4" />
      </button>
      <button
        type="button"
        class="kb-toolbar-btn"
        :class="{ 'is-on': editor?.isActive('italic') }"
        title="Курсив"
        @click="editor?.chain().focus().toggleItalic().run()"
      >
        <Italic class="size-4" />
      </button>
      <span class="mx-1 h-4 w-px bg-line" />
      <button
        type="button"
        class="kb-toolbar-btn"
        :class="{ 'is-on': editor?.isActive('bulletList') }"
        title="Маркированный список"
        @click="editor?.chain().focus().toggleBulletList().run()"
      >
        <List class="size-4" />
      </button>
      <button
        type="button"
        class="kb-toolbar-btn"
        :class="{ 'is-on': editor?.isActive('orderedList') }"
        title="Нумерованный список"
        @click="editor?.chain().focus().toggleOrderedList().run()"
      >
        <ListOrdered class="size-4" />
      </button>
      <button
        type="button"
        class="kb-toolbar-btn"
        :class="{ 'is-on': editor?.isActive('blockquote') }"
        title="Цитата"
        @click="editor?.chain().focus().toggleBlockquote().run()"
      >
        <Quote class="size-4" />
      </button>
      <button
        type="button"
        class="kb-toolbar-btn"
        :class="{ 'is-on': canLink }"
        title="Ссылка"
        @click="setLink"
      >
        <Link2 class="size-4" />
      </button>
      <button
        type="button"
        class="kb-toolbar-btn"
        title="Картинка"
        :disabled="uploading"
        @click="pickImage"
      >
        <ImagePlus class="size-4" />
      </button>
      <input
        ref="fileInput"
        type="file"
        accept="image/*"
        class="hidden"
        @change="onFileChange"
      />
      <span v-if="uploading" class="ml-2 text-[11px] text-muted">Загрузка…</span>
      <span v-else-if="uploadError" class="ml-2 text-[11px] text-danger">{{ uploadError }}</span>
    </div>
    <EditorContent :editor="editor" class="px-3 py-3" />
  </div>
</template>

<style scoped>
.kb-toolbar-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  border-radius: 0.5rem;
  color: var(--color-muted);
  transition:
    background 0.15s,
    color 0.15s;
}
.kb-toolbar-btn:hover:not(:disabled) {
  background: var(--color-brand-soft);
  color: var(--color-brand);
}
.kb-toolbar-btn:disabled {
  opacity: 0.45;
}
.kb-toolbar-btn.is-on {
  background: var(--color-brand-soft);
  color: var(--color-brand);
}
</style>
