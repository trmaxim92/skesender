<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Trash2 } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
import { useWebhooksStore, WEBHOOK_EVENTS } from '@/stores/webhooks'

const auth = useAuthStore()
const canWrite = computed(() => auth.can('action.write'))
const webhooks = useWebhooksStore()
const url = ref('')
const selected = ref<string[]>(['message.created', 'dialog.updated'])
const saving = ref(false)

onMounted(() => {
  void webhooks.fetchWebhooks()
})

function toggleEvent(ev: string) {
  if (selected.value.includes(ev)) {
    selected.value = selected.value.filter((e) => e !== ev)
  } else {
    selected.value = [...selected.value, ev]
  }
}

async function add() {
  if (!url.value.trim() || !selected.value.length) return
  saving.value = true
  const ok = await webhooks.addEndpoint(url.value.trim(), [...selected.value])
  saving.value = false
  if (ok) url.value = ''
}
</script>

<template>
  <div class="h-full overflow-auto p-6">
    <p v-if="webhooks.error" class="mb-4 text-sm text-danger">{{ webhooks.error }}</p>
    <form
      v-if="canWrite"
      class="mb-6 max-w-2xl rounded-2xl border border-line bg-panel p-4"
      @submit.prevent="add"
    >
      <h2 class="mb-3 text-sm font-semibold">Исходящий webhook</h2>
      <label class="mb-3 block">
        <span class="mb-1 block text-xs font-semibold text-muted">URL</span>
        <input
          v-model="url"
          required
          type="url"
          placeholder="https://…"
          class="w-full rounded-xl border border-line bg-surface px-3 py-2 font-mono text-sm outline-none ring-brand focus:ring-2"
        />
      </label>
      <div class="mb-4 flex flex-wrap gap-2">
        <button
          v-for="ev in WEBHOOK_EVENTS"
          :key="ev"
          type="button"
          class="rounded-lg border px-2.5 py-1 font-mono text-xs transition"
          :class="
            selected.includes(ev)
              ? 'border-brand bg-brand-soft text-brand'
              : 'border-line text-muted hover:bg-surface'
          "
          @click="toggleEvent(ev)"
        >
          {{ ev }}
        </button>
      </div>
      <button
        type="submit"
        class="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
        :disabled="saving"
      >
        {{ saving ? '…' : 'Добавить' }}
      </button>
    </form>

    <div class="max-w-3xl space-y-3">
      <p v-if="webhooks.loading" class="text-sm text-muted">Загрузка…</p>
      <article
        v-for="w in webhooks.endpoints"
        :key="w.id"
        class="flex items-start gap-3 rounded-2xl border border-line bg-panel p-4"
      >
        <div class="min-w-0 flex-1">
          <div class="mb-1 flex items-center gap-2">
            <span class="size-2 rounded-full" :class="w.active ? 'bg-ok' : 'bg-muted'" />
            <span class="truncate font-mono text-sm">{{ w.url }}</span>
          </div>
          <div class="flex flex-wrap gap-1.5">
            <span
              v-for="ev in w.events"
              :key="ev"
              class="rounded-md bg-surface px-2 py-0.5 font-mono text-[10px] text-muted"
            >
              {{ ev }}
            </span>
          </div>
        </div>
        <button
          v-if="canWrite"
          type="button"
          class="rounded-lg border border-line px-2.5 py-1 text-xs font-semibold"
          @click="webhooks.toggle(w.id)"
        >
          {{ w.active ? 'Выкл' : 'Вкл' }}
        </button>
        <button
          v-if="canWrite"
          type="button"
          class="rounded-lg p-1.5 text-muted hover:bg-surface hover:text-danger"
          @click="webhooks.remove(w.id)"
        >
          <Trash2 class="size-4" />
        </button>
      </article>
    </div>
  </div>
</template>
