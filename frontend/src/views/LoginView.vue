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
  <div class="relative flex min-h-full overflow-hidden bg-surface">
    <!-- Left brand panel (desktop) — same navy as cabinet sidebar -->
    <aside
      class="relative z-20 hidden w-[min(38%,26rem)] shrink-0 flex-col justify-between overflow-hidden bg-gradient-to-b from-[#1a2436] via-sidebar to-[#090d14] px-8 py-10 text-white lg:flex xl:w-[28rem] xl:px-10"
      style="clip-path: polygon(0 0, 100% 0, 86% 100%, 0 100%)"
    >
      <div
        class="pointer-events-none absolute inset-x-0 bottom-0 h-48 opacity-50"
        style="
          background: radial-gradient(ellipse 90% 80% at 30% 100%, rgba(161, 13, 33, 0.45), transparent 70%);
        "
        aria-hidden="true"
      />

      <div class="relative">
        <div class="mb-6 flex flex-col items-start gap-3">
          <span
            class="flex size-14 items-center justify-center rounded-2xl bg-brand shadow-sm shadow-black/30"
            aria-hidden="true"
          >
            <svg width="34" height="28" viewBox="0 0 22 18" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path
                d="M5.5 13.5h9.2c2.1 0 3.8-1.6 3.8-3.5S16.8 6.5 14.7 6.5c-.3-2.1-2.1-3.7-4.3-3.7-1.8 0-3.4 1.1-4 2.7-.3-.1-.6-.2-1-.2C3.7 5.3 2 6.9 2 8.9c0 2 1.7 3.6 3.5 3.6Z"
                stroke="#fff"
                stroke-width="1.6"
                stroke-linejoin="round"
              />
              <path d="M11.2 8.2 17 5.4l-1.1 6.2-1.9-2.3-2.8 1.1.9-2.2Z" fill="#fff" />
            </svg>
          </span>
          <div>
            <p class="text-2xl font-bold tracking-tight text-white">СкайСкейл</p>
            <p class="mt-1 text-[11px] font-medium tracking-[0.14em] text-white/45">
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
            class="flex size-9 shrink-0 items-center justify-center rounded-full border border-white/15 bg-white/5"
          >
            <component :is="f.icon" class="size-4 text-white/80" stroke-width="1.75" />
          </span>
          <span>{{ f.text }}</span>
        </li>
      </ul>
    </aside>

    <!-- Right: animation + form -->
    <div class="relative flex min-h-full min-w-0 flex-1 items-center justify-center px-4 py-8 sm:px-6">
      <div class="absolute inset-0 bg-surface" />
      <div
        class="pointer-events-none absolute inset-0"
        style="
          background:
            radial-gradient(ellipse 65% 50% at 50% 35%, rgba(161, 13, 33, 0.08) 0%, transparent 60%),
            radial-gradient(ellipse 40% 35% at 10% 90%, rgba(15, 22, 35, 0.06) 0%, transparent 55%),
            radial-gradient(ellipse 35% 30% at 92% 12%, rgba(161, 13, 33, 0.05) 0%, transparent 50%);
        "
      />
      <PlexusBackground />

      <svg
        class="pointer-events-none absolute bottom-6 right-4 h-40 w-40 text-brand/[0.06] sm:bottom-10 sm:right-10 sm:h-52 sm:w-52"
        viewBox="0 0 24 24"
        fill="currentColor"
        aria-hidden="true"
      >
        <path d="M2.01 21 23 12 2.01 3 2 10l15 2-15 2z" />
      </svg>

      <form
        class="relative z-10 w-full max-w-[26rem] rounded-2xl border border-line/80 bg-panel/95 px-5 py-8 shadow-[0_20px_50px_rgba(21,32,51,0.1)] backdrop-blur-sm sm:px-8 sm:py-9"
        autocomplete="off"
        @submit.prevent="submit"
      >
        <div class="mb-7 flex flex-col items-center text-center">
          <span
            class="mb-5 flex size-14 items-center justify-center rounded-2xl bg-brand shadow-sm shadow-brand/25"
            aria-hidden="true"
          >
            <svg width="34" height="28" viewBox="0 0 22 18" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path
                d="M5.5 13.5h9.2c2.1 0 3.8-1.6 3.8-3.5S16.8 6.5 14.7 6.5c-.3-2.1-2.1-3.7-4.3-3.7-1.8 0-3.4 1.1-4 2.7-.3-.1-.6-.2-1-.2C3.7 5.3 2 6.9 2 8.9c0 2 1.7 3.6 3.5 3.6Z"
                stroke="#fff"
                stroke-width="1.6"
                stroke-linejoin="round"
              />
              <path d="M11.2 8.2 17 5.4l-1.1 6.2-1.9-2.3-2.8 1.1.9-2.2Z" fill="#fff" />
            </svg>
          </span>
          <p class="mb-3 text-lg font-bold tracking-tight text-ink">СкайСкейл</p>
          <h1 class="text-lg font-bold tracking-tight text-ink sm:text-xl">
            Вход в кабинет операторов
          </h1>
          <p class="mt-1.5 text-sm text-muted">
            Пожалуйста, авторизуйтесь для продолжения
          </p>
        </div>

        <label class="mb-4 block">
          <span class="mb-1.5 block text-[10px] font-semibold uppercase tracking-[0.08em] text-muted">
            Email
          </span>
          <div class="relative">
            <Mail
              class="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted"
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
              class="w-full rounded-xl border border-transparent bg-[#eef1f5] py-3 pl-10 pr-3.5 text-sm text-ink outline-none transition placeholder:text-muted/60 hover:bg-[#e8ecf2] focus:border-brand/35 focus:bg-panel focus:ring-2 focus:ring-brand-soft"
            />
          </div>
        </label>

        <label class="mb-5 block">
          <span class="mb-1.5 block text-[10px] font-semibold uppercase tracking-[0.08em] text-muted">
            Пароль
          </span>
          <div class="relative">
            <Lock
              class="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted"
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
              class="w-full rounded-xl border border-transparent bg-[#eef1f5] py-3 pl-10 pr-11 text-sm text-ink outline-none transition placeholder:text-muted/60 hover:bg-[#e8ecf2] focus:border-brand/35 focus:bg-panel focus:ring-2 focus:ring-brand-soft"
            />
            <button
              type="button"
              class="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-muted transition hover:bg-surface hover:text-ink"
              :title="showPassword ? 'Скрыть пароль' : 'Показать пароль'"
              @click="showPassword = !showPassword"
            >
              <EyeOff v-if="showPassword" class="size-4" stroke-width="1.75" />
              <Eye v-else class="size-4" stroke-width="1.75" />
            </button>
          </div>
        </label>

        <p v-if="auth.error" class="mb-4 text-sm text-danger">{{ auth.error }}</p>

        <button
          type="submit"
          class="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-brand py-3 text-sm font-semibold text-white shadow-[0_8px_20px_rgba(161,13,33,0.28)] transition hover:brightness-110 disabled:opacity-60"
          :disabled="auth.loading"
        >
          {{ auth.loading ? 'Входим…' : 'Войти' }}
          <ArrowRight v-if="!auth.loading" class="size-4" stroke-width="2.25" />
        </button>
      </form>
    </div>
  </div>
</template>
