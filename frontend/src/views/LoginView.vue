<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const email = ref('admin@order-elite.local')
const password = ref('demo')
const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

function safeRedirect(raw: unknown): string {
  if (typeof raw !== 'string') return auth.firstAllowedPath()
  if (!raw.startsWith('/') || raw.startsWith('//')) return auth.firstAllowedPath()
  return raw
}

async function submit() {
  const ok = await auth.login(email.value, password.value)
  if (ok) {
    await router.push(safeRedirect(route.query.redirect))
  }
}
</script>

<template>
  <div class="relative flex min-h-full items-center justify-center overflow-hidden bg-surface px-4">
    <div
      class="pointer-events-none absolute inset-0 opacity-70"
      style="
        background:
          radial-gradient(ellipse 60% 50% at 20% 20%, #dbe7ff 0%, transparent 55%),
          radial-gradient(ellipse 50% 40% at 80% 80%, #e8eef8 0%, transparent 50%);
      "
    />
    <form
      class="relative w-full max-w-md rounded-2xl border border-line bg-panel p-8 shadow-sm"
      @submit.prevent="submit"
    >
      <div class="mb-6">
        <div class="mb-1 text-2xl font-bold tracking-tight">SkySender</div>
        <p class="text-sm text-muted">Вход в кабинет операторов</p>
      </div>

      <label class="mb-4 block">
        <span class="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">Email</span>
        <input
          v-model="email"
          type="email"
          required
          class="w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 outline-none ring-brand focus:ring-2"
        />
      </label>

      <label class="mb-4 block">
        <span class="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">Пароль</span>
        <input
          v-model="password"
          type="password"
          required
          class="w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 outline-none ring-brand focus:ring-2"
        />
      </label>

      <p v-if="auth.error" class="mb-4 text-sm text-danger">{{ auth.error }}</p>

      <button
        type="submit"
        class="w-full rounded-xl bg-brand py-2.5 text-sm font-semibold text-white transition hover:brightness-105 disabled:opacity-60"
        :disabled="auth.loading"
      >
        {{ auth.loading ? 'Входим…' : 'Войти' }}
      </button>

      <p class="mt-4 text-center text-xs text-muted">
        Демо: <span class="font-mono">admin@order-elite.local</span> /
        <span class="font-mono">demo</span>
      </p>
    </form>
  </div>
</template>
