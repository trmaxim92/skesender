<script setup lang="ts">
import { computed, onBeforeUnmount, watch } from 'vue'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import {
  Bold,
  Heading2,
  Heading3,
  Italic,
  Link2,
  List,
  ListOrdered,
  Quote,
} from 'lucide-vue-next'

const props = defineProps<{
  modelValue: string
  editable?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

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
  ],
  editorProps: {
    attributes: {
      class: 'kb-tiptap-body outline-none min-h-[220px] px-1 py-1',
    },
  },
  onUpdate: ({ editor: ed }) => {
    emit('update:modelValue', ed.getHTML())
  },
})

watch(
  () => props.modelValue,
  (html) => {
    if (!editor.value) return
    const current = editor.value.getHTML()
    if (html !== current) {
      editor.value.commands.setContent(html || '', { emitUpdate: false })
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
</script>

<template>
  <div class="kb-editor overflow-hidden rounded-xl border border-line bg-panel">
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
    </div>
    <EditorContent :editor="editor" class="px-3 py-3" />
  </div>
</template>

<style scoped>
.kb-toolbar-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  size: 2rem;
  width: 2rem;
  height: 2rem;
  border-radius: 0.5rem;
  color: var(--color-muted);
  transition: background 0.15s, color 0.15s;
}
.kb-toolbar-btn:hover {
  background: var(--color-brand-soft);
  color: var(--color-brand);
}
.kb-toolbar-btn.is-on {
  background: var(--color-brand-soft);
  color: var(--color-brand);
}
</style>
