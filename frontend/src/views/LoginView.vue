<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import PlexusBackground from '@/components/auth/PlexusBackground.vue'

const email = ref('')
const password = ref('')
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
  <div class="relative flex min-h-full items-center justify-center overflow-hidden px-4">
    <!-- Deep navy base matching reference -->
    <div class="absolute inset-0 bg-[#020b1a]" />
    <div
      class="pointer-events-none absolute inset-0"
      style="
        background:
          radial-gradient(ellipse 70% 55% at 50% 40%, rgba(12, 55, 95, 0.55) 0%, transparent 60%),
          radial-gradient(ellipse 40% 35% at 15% 85%, rgba(0, 90, 120, 0.25) 0%, transparent 55%),
          radial-gradient(ellipse 35% 30% at 90% 15%, rgba(20, 70, 110, 0.3) 0%, transparent 50%);
      "
    />
    <PlexusBackground />

    <form
      class="relative w-full max-w-md rounded-2xl border border-white/10 bg-[#071526]/78 p-8 shadow-[0_20px_60px_rgba(0,0,0,0.45)] backdrop-blur-md"
      autocomplete="off"
      @submit.prevent="submit"
    >
      <div class="mb-6 flex flex-col items-center text-center">
        <img
          src="/logo-skayskel.png"
          alt="СкайСкел"
          class="mb-4 h-auto w-48 max-w-full rounded-2xl bg-white p-3 shadow-[0_8px_28px_rgba(0,0,0,0.35)]"
          width="192"
          height="192"
        />
        <p class="text-sm text-cyan-100/70">Вход в кабинет операторов</p>
      </div>

      <label class="mb-4 block">
        <span class="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-cyan-100/55">
          Email
        </span>
        <input
          v-model="email"
          type="email"
          name="email"
          autocomplete="username"
          required
          class="w-full rounded-xl border border-white/15 bg-white/5 px-3.5 py-2.5 text-white outline-none placeholder:text-white/30 ring-cyan-400/40 focus:border-cyan-300/40 focus:ring-2"
        />
      </label>

      <label class="mb-4 block">
        <span class="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-cyan-100/55">
          Пароль
        </span>
        <input
          v-model="password"
          type="password"
          name="password"
          autocomplete="current-password"
          required
          class="w-full rounded-xl border border-white/15 bg-white/5 px-3.5 py-2.5 text-white outline-none placeholder:text-white/30 ring-cyan-400/40 focus:border-cyan-300/40 focus:ring-2"
        />
      </label>

      <p v-if="auth.error" class="mb-4 text-sm text-red-300">{{ auth.error }}</p>

      <button
        type="submit"
        class="w-full rounded-xl bg-gradient-to-r from-cyan-500 to-sky-500 py-2.5 text-sm font-semibold text-white shadow-[0_8px_24px_rgba(14,165,233,0.35)] transition hover:brightness-110 disabled:opacity-60"
        :disabled="auth.loading"
      >
        {{ auth.loading ? 'Входим…' : 'Войти' }}
      </button>
    </form>
  </div>
</template>
