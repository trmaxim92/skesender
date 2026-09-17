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
    <div class="absolute inset-0 bg-[#eef5fc]" />
    <div
      class="pointer-events-none absolute inset-0"
      style="
        background:
          radial-gradient(ellipse 65% 50% at 50% 35%, rgba(120, 190, 255, 0.35) 0%, transparent 60%),
          radial-gradient(ellipse 40% 35% at 10% 90%, rgba(0, 132, 255, 0.12) 0%, transparent 55%),
          radial-gradient(ellipse 35% 30% at 92% 12%, rgba(13, 34, 63, 0.06) 0%, transparent 50%);
      "
    />
    <PlexusBackground />

    <form
      class="relative w-full max-w-md rounded-2xl border border-[#0d223f]/10 bg-white/90 p-8 shadow-[0_16px_40px_rgba(13,34,63,0.08)]"
      autocomplete="off"
      @submit.prevent="submit"
    >
      <div class="mb-6 flex flex-col items-center text-center">
        <img
          src="/logo-skayskel.png"
          alt="СкайСкейл"
          class="mb-4 h-auto w-48 max-w-full"
          width="192"
          height="192"
          decoding="async"
          fetchpriority="high"
        />
        <p class="text-sm text-[#0d223f]/65">Вход в кабинет операторов</p>
      </div>

      <label class="mb-4 block">
        <span class="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-[#0d223f]/45">
          Email
        </span>
        <input
          v-model="email"
          type="email"
          name="email"
          autocomplete="username"
          required
          class="w-full rounded-xl border border-[#0d223f]/12 bg-white px-3.5 py-2.5 text-[#0d223f] outline-none placeholder:text-[#0d223f]/30 ring-[#0084ff]/25 focus:border-[#0084ff]/50 focus:ring-2"
        />
      </label>

      <label class="mb-4 block">
        <span class="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-[#0d223f]/45">
          Пароль
        </span>
        <input
          v-model="password"
          type="password"
          name="password"
          autocomplete="current-password"
          required
          class="w-full rounded-xl border border-[#0d223f]/12 bg-white px-3.5 py-2.5 text-[#0d223f] outline-none placeholder:text-[#0d223f]/30 ring-[#0084ff]/25 focus:border-[#0084ff]/50 focus:ring-2"
        />
      </label>

      <p v-if="auth.error" class="mb-4 text-sm text-red-600">{{ auth.error }}</p>

      <button
        type="submit"
        class="w-full rounded-xl bg-[#0084ff] py-2.5 text-sm font-semibold text-white shadow-[0_8px_20px_rgba(0,132,255,0.28)] transition hover:bg-[#0074e0] disabled:opacity-60"
        :disabled="auth.loading"
      >
        {{ auth.loading ? 'Входим…' : 'Войти' }}
      </button>
    </form>
  </div>
</template>
