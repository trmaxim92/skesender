<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Plus, Trash2 } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
import { useChannelsStore } from '@/stores/channels'
import { listDepartmentsRequest, mapDepartment } from '@/api/settings'
import {
  DISPATCHER_TRIGGER_LABEL,
  createDispatcherGroupRequest,
  createDispatcherRuleRequest,
  deleteDispatcherGroupRequest,
  deleteDispatcherRuleRequest,
  listDispatcherGroupsRequest,
  listDispatcherRulesRequest,
  mapDispatcherGroup,
  mapDispatcherRule,
  updateDispatcherGroupRequest,
  updateDispatcherRuleRequest,
  type DispatcherAction,
  type DispatcherCondition,
  type DispatcherRule,
  type DispatcherRuleGroup,
} from '@/api/dispatcher'
import { ApiError } from '@/api/client'
import type { Department } from '@/types'
import { transportLabel, type ChannelTransport } from '@/types'

const auth = useAuthStore()
const channels = useChannelsStore()
const canWrite = computed(() => auth.can('action.write'))

const groups = ref<DispatcherRuleGroup[]>([])
const rules = ref<DispatcherRule[]>([])
const departments = ref<Department[]>([])
const selectedGroupId = ref<number | null>(null)
const selectedRuleId = ref<number | null>(null)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const newGroupName = ref('')

const formName = ref('')
const formDescription = ref('')
const formActive = ref(true)
const formTrigger = ref<'appeal.opened'>('appeal.opened')
const formReply = ref('')
const formTransportFilter = ref<'all' | ChannelTransport>('all')
const formChannelId = ref<number | null>(null)
const formDepartmentId = ref<number | null>(null)

const selectedGroup = computed(
  () => groups.value.find((g) => g.id === selectedGroupId.value) ?? null,
)
const selectedRule = computed(
  () => rules.value.find((r) => r.id === selectedRuleId.value) ?? null,
)
const groupRules = computed(() =>
  rules.value.filter((r) => r.groupId === selectedGroupId.value),
)

function formatApplied(iso: string | null) {
  if (!iso) return 'ещё не применялось'
  const d = new Date(iso)
  return d.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

async function reload() {
  loading.value = true
  error.value = ''
  try {
    const [gRows, rRows] = await Promise.all([
      listDispatcherGroupsRequest(),
      listDispatcherRulesRequest(),
    ])
    groups.value = gRows.map(mapDispatcherGroup)
    rules.value = rRows.map(mapDispatcherRule)
    if (
      selectedGroupId.value == null ||
      !groups.value.some((g) => g.id === selectedGroupId.value)
    ) {
      selectedGroupId.value = groups.value[0]?.id ?? null
    }
    if (
      selectedRuleId.value != null &&
      !rules.value.some((r) => r.id === selectedRuleId.value)
    ) {
      selectedRuleId.value = null
      resetForm()
    }
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось загрузить диспетчер'
  } finally {
    loading.value = false
  }
}

function resetForm() {
  formName.value = 'Приветствие'
  formDescription.value = ''
  formActive.value = true
  formTrigger.value = 'appeal.opened'
  formReply.value =
    'Здравствуйте! Вы обратились в поддержку. Напишите свой запрос — свободный менеджер подключится к диалогу.'
  formTransportFilter.value = 'all'
  formChannelId.value = null
  formDepartmentId.value = null
}

function loadRuleIntoForm(rule: DispatcherRule) {
  formName.value = rule.name
  formDescription.value = rule.description
  formActive.value = rule.active
  formTrigger.value = (rule.trigger as 'appeal.opened') || 'appeal.opened'
  const reply = rule.actions.find((a) => a.type === 'send_reply')
  formReply.value = reply?.text || ''
  formTransportFilter.value = 'all'
  formChannelId.value = null
  formDepartmentId.value = null
  for (const c of rule.conditions) {
    if (c.field === 'transport' && c.op === 'eq' && typeof c.value === 'string') {
      formTransportFilter.value = c.value as ChannelTransport | 'all'
    }
    if (c.field === 'channel_id' && c.op === 'eq' && typeof c.value === 'number') {
      formChannelId.value = c.value
    }
    if (c.field === 'department_id' && c.op === 'eq' && typeof c.value === 'number') {
      formDepartmentId.value = c.value
    }
  }
}

function buildConditions(): DispatcherCondition[] {
  const out: DispatcherCondition[] = []
  if (formTransportFilter.value !== 'all') {
    out.push({ field: 'transport', op: 'eq', value: formTransportFilter.value })
  }
  if (formChannelId.value != null) {
    out.push({ field: 'channel_id', op: 'eq', value: formChannelId.value })
  }
  if (formDepartmentId.value != null) {
    out.push({ field: 'department_id', op: 'eq', value: formDepartmentId.value })
  }
  return out
}

function buildActions(): DispatcherAction[] {
  return [{ type: 'send_reply', text: formReply.value.trim() }]
}

function selectRule(rule: DispatcherRule) {
  selectedRuleId.value = rule.id
  loadRuleIntoForm(rule)
}

function startCreateRule() {
  selectedRuleId.value = null
  resetForm()
}

async function saveRule() {
  if (!canWrite.value || !selectedGroupId.value) return
  if (!formName.value.trim() || !formReply.value.trim()) {
    error.value = 'Укажите название и текст ответа'
    return
  }
  saving.value = true
  error.value = ''
  try {
    const payload = {
      group_id: selectedGroupId.value,
      name: formName.value.trim(),
      description: formDescription.value.trim(),
      active: formActive.value,
      sort_order: selectedRule.value?.sortOrder ?? 0,
      trigger: formTrigger.value,
      conditions: buildConditions(),
      actions: buildActions(),
    }
    if (selectedRuleId.value == null) {
      const created = mapDispatcherRule(await createDispatcherRuleRequest(payload))
      rules.value.push(created)
      selectedRuleId.value = created.id
    } else {
      const updated = mapDispatcherRule(
        await updateDispatcherRuleRequest(selectedRuleId.value, {
          ...payload,
          active: formActive.value,
          sort_order: selectedRule.value?.sortOrder ?? 0,
          trigger: formTrigger.value,
          conditions: buildConditions(),
          actions: buildActions(),
        }),
      )
      const idx = rules.value.findIndex((r) => r.id === updated.id)
      if (idx >= 0) rules.value[idx] = updated
    }
    await reload()
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось сохранить правило'
  } finally {
    saving.value = false
  }
}

async function removeRule() {
  if (!canWrite.value || selectedRuleId.value == null) return
  if (!confirm('Удалить правило?')) return
  try {
    await deleteDispatcherRuleRequest(selectedRuleId.value)
    selectedRuleId.value = null
    resetForm()
    await reload()
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось удалить'
  }
}

async function toggleRuleActive(rule: DispatcherRule) {
  if (!canWrite.value) return
  try {
    const updated = mapDispatcherRule(
      await updateDispatcherRuleRequest(rule.id, {
        group_id: rule.groupId,
        name: rule.name,
        description: rule.description,
        active: !rule.active,
        sort_order: rule.sortOrder,
        trigger: rule.trigger,
        conditions: rule.conditions,
        actions: rule.actions,
      }),
    )
    const idx = rules.value.findIndex((r) => r.id === updated.id)
    if (idx >= 0) rules.value[idx] = updated
    if (selectedRuleId.value === updated.id) formActive.value = updated.active
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось переключить'
  }
}

async function addGroup() {
  if (!canWrite.value || !newGroupName.value.trim()) return
  try {
    const g = mapDispatcherGroup(
      await createDispatcherGroupRequest({ name: newGroupName.value.trim() }),
    )
    groups.value.push(g)
    selectedGroupId.value = g.id
    newGroupName.value = ''
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось создать группу'
  }
}

async function toggleGroupActive(group: DispatcherRuleGroup) {
  if (!canWrite.value) return
  try {
    const updated = mapDispatcherGroup(
      await updateDispatcherGroupRequest(group.id, {
        name: group.name,
        active: !group.active,
        sort_order: group.sortOrder,
      }),
    )
    const idx = groups.value.findIndex((g) => g.id === updated.id)
    if (idx >= 0) groups.value[idx] = updated
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось переключить группу'
  }
}

async function removeGroup(group: DispatcherRuleGroup) {
  if (!canWrite.value) return
  if (!confirm(`Удалить группу «${group.name}» и все её правила?`)) return
  try {
    await deleteDispatcherGroupRequest(group.id)
    if (selectedGroupId.value === group.id) selectedGroupId.value = null
    await reload()
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : 'Не удалось удалить группу'
  }
}

watch(selectedGroupId, () => {
  selectedRuleId.value = null
  resetForm()
})

onMounted(async () => {
  resetForm()
  void channels.fetchChannels()
  try {
    departments.value = (await listDepartmentsRequest()).map(mapDepartment)
  } catch {
    departments.value = []
  }
  await reload()
})
</script>

<template>
  <div class="flex h-full min-h-0 flex-col md:flex-row">
    <aside class="w-full shrink-0 border-b border-line bg-panel p-4 md:w-72 md:border-b-0 md:border-r">
      <div class="mb-3 flex items-center justify-between gap-2">
        <h2 class="text-sm font-bold uppercase tracking-wide text-muted">Группы правил</h2>
      </div>
      <ul class="space-y-1">
        <li v-for="g in groups" :key="g.id">
          <button
            type="button"
            class="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm transition"
            :class="
              selectedGroupId === g.id
                ? 'bg-brand-soft text-brand'
                : 'hover:bg-surface text-ink'
            "
            @click="selectedGroupId = g.id"
          >
            <span class="min-w-0 flex-1 truncate font-medium">{{ g.name }}</span>
            <span class="rounded-md bg-surface px-1.5 text-[10px] font-bold text-muted">
              {{ g.rulesCount }}
            </span>
          </button>
          <div class="mt-1 flex items-center gap-2 px-3 pb-2">
            <button
              type="button"
              class="text-[11px] font-semibold"
              :class="g.active ? 'text-ok' : 'text-muted'"
              :disabled="!canWrite"
              @click="toggleGroupActive(g)"
            >
              {{ g.active ? 'Вкл' : 'Выкл' }}
            </button>
            <button
              type="button"
              class="text-[11px] font-semibold text-danger disabled:opacity-40"
              :disabled="!canWrite || groups.length <= 1"
              @click="removeGroup(g)"
            >
              Удалить
            </button>
          </div>
        </li>
      </ul>
      <div v-if="canWrite" class="mt-3 flex gap-2">
        <input
          v-model="newGroupName"
          type="text"
          placeholder="Новая группа"
          class="min-w-0 flex-1 rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none ring-brand focus:ring-2"
          @keydown.enter="addGroup"
        />
        <button
          type="button"
          class="flex size-10 items-center justify-center rounded-xl bg-brand text-white"
          title="Добавить группу"
          @click="addGroup"
        >
          <Plus class="size-4" />
        </button>
      </div>
    </aside>

    <div class="flex min-w-0 flex-1 flex-col overflow-hidden">
      <div class="border-b border-line px-5 py-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 class="text-lg font-bold tracking-tight">Диспетчер</h1>
            <p class="mt-1 text-sm text-muted">
              Правила автоматизации: событие → условия → действия. MVP: новое обращение → ответ от
              системы.
            </p>
          </div>
          <button
            type="button"
            class="rounded-xl bg-brand px-3.5 py-2 text-sm font-semibold text-white disabled:opacity-40"
            :disabled="!canWrite || !selectedGroupId"
            @click="startCreateRule"
          >
            Добавить правило
          </button>
        </div>
        <p v-if="error" class="mt-2 text-sm text-danger">{{ error }}</p>
        <p v-if="loading" class="mt-2 text-sm text-muted">Загрузка…</p>
      </div>

      <div class="grid min-h-0 flex-1 gap-0 lg:grid-cols-[minmax(0,280px)_minmax(0,1fr)]">
        <div class="overflow-auto border-b border-line p-4 lg:border-b-0 lg:border-r">
          <p class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
            {{ selectedGroup?.name || 'Правила' }}
          </p>
          <p v-if="!groupRules.length" class="rounded-xl border border-dashed border-line p-4 text-sm text-muted">
            В группе пока нет правил.
          </p>
          <ul v-else class="space-y-2">
            <li
              v-for="rule in groupRules"
              :key="rule.id"
              class="rounded-xl border border-line bg-panel px-3 py-2.5"
              :class="selectedRuleId === rule.id ? 'border-brand/50 bg-brand-soft/40' : ''"
            >
              <button type="button" class="w-full text-left" @click="selectRule(rule)">
                <div class="text-sm font-semibold">{{ rule.name }}</div>
                <div class="mt-0.5 text-[11px] text-muted">
                  {{ DISPATCHER_TRIGGER_LABEL[rule.trigger] || rule.trigger }}
                </div>
              </button>
              <div class="mt-2 flex items-center justify-between gap-2">
                <button
                  type="button"
                  class="text-[11px] font-semibold"
                  :class="rule.active ? 'text-ok' : 'text-muted'"
                  :disabled="!canWrite"
                  @click="toggleRuleActive(rule)"
                >
                  {{ rule.active ? 'Активно' : 'Выкл' }}
                </button>
                <span class="text-[10px] text-muted">{{ formatApplied(rule.lastAppliedAt) }}</span>
              </div>
            </li>
          </ul>
        </div>

        <div class="overflow-auto p-5">
          <div v-if="!selectedGroupId" class="text-sm text-muted">Выберите группу слева.</div>
          <form
            v-else
            class="mx-auto max-w-2xl space-y-4"
            @submit.prevent="saveRule"
          >
            <div class="flex items-center justify-between gap-2">
              <h2 class="text-base font-bold">
                {{ selectedRuleId == null ? 'Новое правило' : 'Редактирование правила' }}
              </h2>
              <button
                v-if="selectedRuleId != null"
                type="button"
                class="rounded-lg p-2 text-danger hover:bg-danger-soft disabled:opacity-40"
                :disabled="!canWrite"
                title="Удалить"
                @click="removeRule"
              >
                <Trash2 class="size-4" />
              </button>
            </div>

            <label class="block">
              <span class="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">
                Название
              </span>
              <input
                v-model="formName"
                type="text"
                :readonly="!canWrite"
                class="w-full rounded-xl border border-line bg-panel px-3.5 py-2.5 text-sm outline-none ring-brand focus:ring-2"
              />
            </label>

            <label class="block">
              <span class="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted">
                Описание
              </span>
              <input
                v-model="formDescription"
                type="text"
                :readonly="!canWrite"
                class="w-full rounded-xl border border-line bg-panel px-3.5 py-2.5 text-sm outline-none ring-brand focus:ring-2"
              />
            </label>

            <label class="flex items-center gap-2 text-sm">
              <input v-model="formActive" type="checkbox" class="size-4" :disabled="!canWrite" />
              Активность
            </label>

            <div class="rounded-2xl border border-line bg-panel p-4">
              <h3 class="text-xs font-bold uppercase tracking-wide text-muted">
                Обязательное условие (триггер)
              </h3>
              <select
                v-model="formTrigger"
                class="mt-2 w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-sm"
                :disabled="!canWrite"
              >
                <option value="appeal.opened">Новое обращение</option>
              </select>
            </div>

            <div class="rounded-2xl border border-line bg-panel p-4 space-y-3">
              <h3 class="text-xs font-bold uppercase tracking-wide text-muted">
                Дополнительные условия
              </h3>
              <label class="block">
                <span class="mb-1 block text-[11px] text-muted">Транспорт</span>
                <select
                  v-model="formTransportFilter"
                  class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm"
                  :disabled="!canWrite"
                >
                  <option value="all">Все</option>
                  <option v-for="(label, key) in transportLabel" :key="key" :value="key">
                    {{ label }}
                  </option>
                </select>
              </label>
              <label class="block">
                <span class="mb-1 block text-[11px] text-muted">Канал</span>
                <select
                  v-model="formChannelId"
                  class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm"
                  :disabled="!canWrite"
                >
                  <option :value="null">Любой</option>
                  <option v-for="ch in channels.channels" :key="ch.id" :value="ch.id">
                    {{ ch.name }}
                  </option>
                </select>
              </label>
              <label class="block">
                <span class="mb-1 block text-[11px] text-muted">Отдел</span>
                <select
                  v-model="formDepartmentId"
                  class="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm"
                  :disabled="!canWrite"
                >
                  <option :value="null">Любой</option>
                  <option v-for="d in departments" :key="d.id" :value="d.id">
                    {{ d.name }}
                  </option>
                </select>
              </label>
            </div>

            <div class="rounded-2xl border border-line bg-panel p-4 space-y-3">
              <h3 class="text-xs font-bold uppercase tracking-wide text-muted">Действия</h3>
              <p class="text-sm text-ink">Добавить ответ · от имени системы</p>
              <textarea
                v-model="formReply"
                rows="5"
                :readonly="!canWrite"
                class="w-full resize-y rounded-xl border border-line bg-surface px-3.5 py-2.5 text-sm outline-none ring-brand focus:ring-2"
                placeholder="Текст клиенту"
              />
              <p class="text-[11px] text-muted">Плейсхолдер: <code v-pre>{{contact}}</code></p>
            </div>

            <button
              type="submit"
              class="rounded-xl bg-brand px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-40"
              :disabled="!canWrite || saving"
            >
              {{ saving ? 'Сохранение…' : 'Сохранить' }}
            </button>
          </form>
        </div>
      </div>
    </div>
  </div>
</template>
