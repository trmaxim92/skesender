<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import { buildKbToc, hydrateKbImages, type KbTocItem } from '@/utils/knowledgeUi'

const props = defineProps<{
  html: string
}>()

const emit = defineEmits<{
  toc: [items: KbTocItem[]]
}>()

const root = ref<HTMLElement | null>(null)

async function render() {
  await nextTick()
  const el = root.value
  if (!el) return
  el.innerHTML = props.html || '<p>Пустая статья</p>'
  const toc = buildKbToc(el)
  emit('toc', toc)
  await hydrateKbImages(el)
}

watch(() => props.html, () => {
  void render()
})

onMounted(() => {
  void render()
})

function scrollToHeading(id: string) {
  const target = root.value?.querySelector(`#${CSS.escape(id)}`)
  target?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

defineExpose({ scrollToHeading })
</script>

<template>
  <div ref="root" class="kb-prose" />
</template>
