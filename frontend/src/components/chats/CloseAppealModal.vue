<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Modal from '@/components/ui/Modal.vue'

const props = defineProps<{
  open: boolean
  busy?: boolean
  previewText: string
  contactName: string
  appealNumber: number | null
}>()

const emit = defineEmits<{
  close: []
  confirm: [withReply: boolean]
}>()

const withReply = ref(true)

watch(
  () => props.open,
  (open) => {
    if (open) withReply.value = !!props.previewText.trim()
  },
)

const canSendReply = computed(() => !!props.previewText.trim())

function confirm() {
  emit('confirm', withReply.value && canSendReply.value)
}
</script>

<template>
  <Modal v-if="open" title="Закрыть обращение" @close="emit('close')">
    <div class="space-y-4">
      <p class="text-sm text-muted">
        Обращение
        <span v-if="appealNumber" class="font-semibold text-ink">#{{ appealNumber }}</span>
        для <span class="font-semibold text-ink">{{ contactName }}</span>
        будет закрыто.
      </p>

      <label class="flex items-start gap-2 text-sm">
        <input
          v-model="withReply"
          type="checkbox"
          class="mt-1"
          :disabled="!canSendReply || busy"
        />
        <span>
          <span class="font-semibold text-ink">Отправить отбивку клиенту</span>
          <span v-if="!canSendReply" class="mt-0.5 block text-xs text-muted">
            Нет шаблона «Закрытие обращения» для этого канала.
          </span>
        </span>
      </label>

      <div
        v-if="withReply && canSendReply"
        class="rounded-xl border border-line bg-surface px-3 py-2.5 text-sm whitespace-pre-wrap"
      >
        {{ previewText }}
      </div>

      <div class="flex justify-end gap-2 pt-1">
        <button
          type="button"
          class="rounded-xl border border-line px-4 py-2 text-sm font-semibold text-muted hover:bg-surface"
          :disabled="busy"
          @click="emit('close')"
        >
          Отмена
        </button>
        <button
          type="button"
          class="rounded-xl bg-ok px-4 py-2 text-sm font-semibold text-white hover:brightness-105 disabled:opacity-50"
          :disabled="busy"
          @click="confirm"
        >
          {{ busy ? 'Закрываем…' : 'Закрыть' }}
        </button>
      </div>
    </div>
  </Modal>
</template>
