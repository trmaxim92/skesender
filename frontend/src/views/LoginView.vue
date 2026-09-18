<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ArrowRight, Cloud, Eye, EyeOff, Lock, Mail, Shield, Zap } from 'lucide-vue-next'
import PlexusBackground from '@/components/auth/PlexusBackground.vue'
import { useAuthStore } from '@/stores/auth'

const email = ref('')
const password = ref('')
const showPassword = ref(false)
const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const features = [
  { icon: Shield, text: 'Безопасный доступ к системе' },
  { icon: Zap, text: 'Стабильная работа 24/7' },
  { icon: Cloud, text: 'Современные технологии' },
]

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
  <div class="relative flex min-h-full overflow-hidden bg-[#eef5fc]">
    <!-- Left brand panel (desktop) -->
    <aside
      class="relative z-20 hidden w-[min(38%,26rem)] shrink-0 flex-col justify-between overflow-hidden bg-gradient-to-b from-[#143a6b] via-[#0d223f] to-[#081628] px-8 py-10 text-white lg:flex xl:w-[28rem] xl:px-10"
      style="clip-path: polygon(0 0, 100% 0, 86% 100%, 0 100%)"
    >
      <div
        class="pointer-events-none absolute inset-x-0 bottom-0 h-48 opacity-40"
        style="
          background: radial-gradient(ellipse 90% 80% at 30% 100%, rgba(120, 190, 255, 0.35), transparent 70%);
        "
        aria-hidden="true"
      />

      <div class="relative">
        <div class="mb-6 flex flex-col items-start gap-3">
          <span
            class="flex size-14 items-center justify-center rounded-2xl bg-white/10 shadow-inner ring-1 ring-white/15"
            aria-hidden="true"
          >
            <svg width="34" height="28" viewBox="0 0 22 18" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path
                d="M5.5 13.5h9.2c2.1 0 3.8-1.6 3.8-3.5S16.8 6.5 14.7 6.5c-.3-2.1-2.1-3.7-4.3-3.7-1.8 0-3.4 1.1-4 2.7-.3-.1-.6-.2-1-.2C3.7 5.3 2 6.9 2 8.9c0 2 1.7 3.6 3.5 3.6Z"
                stroke="#7ec4ff"
                stroke-width="1.6"
                stroke-linejoin="round"
              />
              <path d="M11.2 8.2 17 5.4l-1.1 6.2-1.9-2.3-2.8 1.1.9-2.2Z" fill="#fff" />
            </svg>
          </span>
          <div>
            <p class="text-2xl font-bold tracking-tight">
              <span class="text-white">Скай</span><span class="text-[#5eb0ff]">Скейл</span>
            </p>
            <p class="mt-1 text-[11px] font-medium tracking-[0.14em] text-white/55">
              — ООО СкайСкейл —
            </p>
          </div>
        </div>
        <p class="max-w-[14rem] text-[1.05rem] font-semibold leading-snug tracking-tight text-white/95">
          Технологии, которые двигают ваш бизнес
        </p>
      </div>

      <ul class="relative mb-6 space-y-4 pr-10">
        <li v-for="f in features" :key="f.text" class="flex items-center gap-3 text-sm text-white/90">
          <span
            class="flex size-9 shrink-0 items-center justify-center rounded-full border border-white/25 bg-white/5"
          >
            <component :is="f.icon" class="size-4 text-[#7ec4ff]" stroke-width="1.75" />
          </span>
          <span>{{ f.text }}</span>
        </li>
      </ul>
    </aside>

    <!-- Right: animation + form -->
    <div class="relative flex min-h-full min-w-0 flex-1 items-center justify-center px-4 py-8 sm:px-6">
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

      <!-- Soft plane watermark -->
      <svg
        class="pointer-events-none absolute bottom-6 right-4 h-40 w-40 text-[#0084ff]/[0.07] sm:bottom-10 sm:right-10 sm:h-52 sm:w-52"
        viewBox="0 0 24 24"
        fill="currentColor"
        aria-hidden="true"
      >
        <path d="M2.01 21 23 12 2.01 3 2 10l15 2-15 2z" />
      </svg>

      <form
        class="relative z-10 w-full max-w-[26rem] rounded-2xl border border-[#0d223f]/08 bg-white/95 px-5 py-8 shadow-[0_20px_50px_rgba(13,34,63,0.1)] backdrop-blur-sm sm:px-8 sm:py-9"
        autocomplete="off"
        @submit.prevent="submit"
      >
        <div class="mb-7 flex flex-col items-center text-center">
          <img
            src="/logo-skayskel.png"
            alt="СкайСкейл"
            class="mb-5 h-auto w-44 max-w-full"
            width="176"
            height="176"
            decoding="async"
            fetchpriority="high"
          />
          <h1 class="text-lg font-bold tracking-tight text-[#0d223f] sm:text-xl">
            Вход в кабинет операторов
          </h1>
          <p class="mt-1.5 text-sm text-[#0d223f]/55">
            Пожалуйста, авторизуйтесь для продолжения
          </p>
        </div>

        <label class="mb-4 block">
          <span class="mb-1.5 block text-[10px] font-semibold uppercase tracking-[0.08em] text-[#0d223f]/45">
            Email
          </span>
          <div class="relative">
            <Mail
              class="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-[#0d223f]/40"
              stroke-width="1.75"
              aria-hidden="true"
            />
            <input
              v-model="email"
              type="email"
              name="email"
              autocomplete="username"
              required
              placeholder="you@company.ru"
              class="w-full rounded-xl border border-transparent bg-[#eef2f7] py-3 pl-10 pr-3.5 text-sm text-[#0d223f] outline-none transition placeholder:text-[#0d223f]/35 hover:bg-[#e8edf4] focus:border-[#0084ff]/35 focus:bg-white focus:ring-2 focus:ring-[#0084ff]/20"
            />
          </div>
        </label>

        <label class="mb-5 block">
          <span class="mb-1.5 block text-[10px] font-semibold uppercase tracking-[0.08em] text-[#0d223f]/45">
            Пароль
          </span>
          <div class="relative">
            <Lock
              class="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-[#0d223f]/40"
              stroke-width="1.75"
              aria-hidden="true"
            />
            <input
              v-model="password"
              :type="showPassword ? 'text' : 'password'"
              name="password"
              autocomplete="current-password"
              required
              placeholder="••••••••"
              class="w-full rounded-xl border border-transparent bg-[#eef2f7] py-3 pl-10 pr-11 text-sm text-[#0d223f] outline-none transition placeholder:text-[#0d223f]/35 hover:bg-[#e8edf4] focus:border-[#0084ff]/35 focus:bg-white focus:ring-2 focus:ring-[#0084ff]/20"
            />
            <button
              type="button"
              class="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-[#0d223f]/45 transition hover:bg-[#0d223f]/5 hover:text-[#0d223f]/75"
              :title="showPassword ? 'Скрыть пароль' : 'Показать пароль'"
              @click="showPassword = !showPassword"
            >
              <EyeOff v-if="showPassword" class="size-4" stroke-width="1.75" />
              <Eye v-else class="size-4" stroke-width="1.75" />
            </button>
          </div>
        </label>

        <p v-if="auth.error" class="mb-4 text-sm text-red-600">{{ auth.error }}</p>

        <button
          type="submit"
          class="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[#0084ff] py-3 text-sm font-semibold text-white shadow-[0_8px_20px_rgba(0,132,255,0.28)] transition hover:bg-[#0074e0] disabled:opacity-60"
          :disabled="auth.loading"
        >
          {{ auth.loading ? 'Входим…' : 'Войти' }}
          <ArrowRight v-if="!auth.loading" class="size-4" stroke-width="2.25" />
        </button>
      </form>
    </div>
  </div>
</template>
