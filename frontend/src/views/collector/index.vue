<template>
  <section class="page" data-module="collector">
    <header class="page-head">
      <div>
        <h2>集电线路管理</h2>
        <p class="page-desc">维护集电线路，围绕线路编号、电压等级、起止杆塔、线路长度做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记集电线路</button>
        <button class="btn" type="button" @click="openLedger">调度台账</button>
        <button class="btn" type="button" @click="exportRows">导出集电线路清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="search">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <!-- 命不中时保住已填内容，并说清是哪一步对不上 -->
    <div v-if="noMatchHint" class="hint-bar">{{ noMatchHint }}</div>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <button v-if="column === '线路编号'" class="link" type="button" @click="openDetail(row)">
              {{ row[column] ?? '—' }}
            </button>
            <span v-else>{{ row[column] ?? '—' }}</span>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              :disabled="pendingAction === String(row.id) + action"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!loading && !rows.length">
          <td :colspan="columns.length + 1" class="empty-state">
            {{ fetchError ? '列表未刷新，已清空旧数据，请稍后重试' : '当前条件下没有命中的集电线路' }}
          </td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span class="pager">
        <button class="btn" type="button" :disabled="page <= 1 || loading" @click="goPage(page - 1)">上一页</button>
        <span>第 {{ page }} / {{ totalPages }} 页</span>
        <button class="btn" type="button" :disabled="page >= totalPages || loading" @click="goPage(page + 1)">下一页</button>
      </span>
      <span>共 {{ total }} 条集电线路记录</span>
      <span v-if="fetchError" class="error-text">{{ fetchError }}</span>
    </footer>

    <!-- 详情弹窗：线路长度、线路状态与列表取同一个接口口径 -->
    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal">
        <h3>集电线路详情</h3>
        <dl class="detail-list">
          <template v-for="column in columns" :key="column">
            <dt>{{ column }}</dt>
            <dd>{{ detail[column] ?? '—' }}</dd>
          </template>
        </dl>
        <div class="modal-foot">
          <button class="btn" type="button" @click="detail = null">关闭</button>
        </div>
      </div>
    </div>

    <!-- 登记弹窗 -->
    <div v-if="createOpen" class="modal-mask" @click.self="closeCreate">
      <div class="modal">
        <h3>登记集电线路</h3>
        <form @submit.prevent="submitCreate">
          <label v-for="field in createFields" :key="field.key" class="form-item">
            <span>{{ field.label }}{{ field.required ? ' *' : '' }}</span>
            <input v-model="createForm[field.key]" :placeholder="`请输入${field.label}`" />
          </label>
          <p v-if="createError" class="error-text">{{ createError }}</p>
          <div class="modal-foot">
            <button class="btn" type="button" @click="closeCreate">取消</button>
            <button class="btn primary" type="submit" :disabled="submitting">登记</button>
          </div>
        </form>
      </div>
    </div>

    <!-- 调度台账：处置结果按线路编号回写到这里 -->
    <div v-if="ledgerOpen" class="modal-mask" @click.self="ledgerOpen = false">
      <div class="modal modal-wide">
        <h3>调度台账（处置结果回写）</h3>
        <table class="data-table">
          <thead>
            <tr>
              <th>线路编号</th>
              <th>电压等级</th>
              <th>起止杆塔</th>
              <th>处置结果</th>
              <th>更新日期</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in ledgerRows" :key="String(item.id)">
              <td>{{ item['线路编号'] }}</td>
              <td>{{ item['电压等级'] }}</td>
              <td>{{ item['起止杆塔'] }}</td>
              <td>{{ item['处置结果'] }}</td>
              <td>{{ item['更新日期'] }}</td>
            </tr>
            <tr v-if="!ledgerRows.length">
              <td colspan="5" class="empty-state">台账暂无记录</td>
            </tr>
          </tbody>
        </table>
        <div class="modal-foot">
          <button class="btn" type="button" @click="ledgerOpen = false">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type Step = { field: string; keyword: string | null; matched: number; applied: boolean }

const ENDPOINT = '/api/collector'
const PAGE_SIZE = 20
const STORAGE_KEY = 'collector-ui-state'
const columns = ["线路编号", "电压等级", "起止杆塔", "线路长度", "所属场站", "上次巡视日", "缺陷数量", "线路状态"]
const actions = ["提交巡视", "登记缺陷", "停运线路"]
const stats = [{"label": "在运线路", "value": 0}, {"label": "存在缺陷线路", "value": 0}, {"label": "待巡视线段", "value": 0}]
const createFields = [
  { key: '线路编号', label: '线路编号', required: true },
  { key: '电压等级', label: '电压等级', required: true },
  { key: '起止杆塔', label: '起止杆塔', required: true },
  { key: '线路长度', label: '线路长度', required: false },
  { key: '所属场站', label: '所属场站', required: false },
] as const

const rows = ref<Row[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const fetchError = ref('')
const steps = ref<Step[]>([])
const filterFields = columns.slice(0, 3)
// 重新进入页面时，留住上次填好的筛选内容与页码
const initialState = restoreState()
const filters = ref<Record<string, string>>(initialState.filters)
const initialPage = initialState.page

const detail = ref<Row | null>(null)
const pendingAction = ref('')
const createOpen = ref(false)
const submitting = ref(false)
const createError = ref('')
const createForm = ref<Record<string, string>>({})
const ledgerOpen = ref(false)
const ledgerRows = ref<Row[]>([])

const totalPages = computed(() => Math.max(Math.ceil(total.value / PAGE_SIZE), 1))

const activeSteps = computed(() => steps.value.filter((step) => step.applied))

// 命不中：按过滤管线的顺序，指出是哪一步把结果筛没的
const noMatchHint = computed(() => {
  if (loading.value || fetchError.value || total.value > 0 || activeSteps.value.length === 0) {
    return ''
  }
  const failed = activeSteps.value.find((step) => step.matched === 0)
  if (!failed) {
    return ''
  }
  const index = activeSteps.value.indexOf(failed)
  const before = index === 0 ? null : activeSteps.value[index - 1]
  const tail = before === null
    ? '没有任何线路对得上'
    : `前一步还剩 ${before.matched} 条，到这一步对不上了`
  return `未命中：「${failed.field}」按「${failed.keyword ?? ''}」过滤后为 0 条，${tail}。已保留您填写的筛选内容。`
})

function restoreState(): { filters: Record<string, string>; page: number } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) {
      return { filters: {}, page: 1 }
    }
    const saved = JSON.parse(raw) as { filters?: Record<string, string>; page?: number }
    return {
      filters: saved.filters ?? {},
      page: Number.isFinite(saved.page) && Number(saved.page) > 0 ? Number(saved.page) : 1,
    }
  } catch {
    return { filters: {}, page: 1 }
  }
}

function persistState() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ filters: filters.value, page: page.value }))
}

function activeQuery() {
  // 空白条件不下发，避免后端把空串当成检索值
  const params = new URLSearchParams()
  for (const field of filterFields) {
    const value = filters.value[field]?.trim()
    if (value) {
      params.set(field, value)
    }
  }
  params.set('page', String(page.value))
  params.set('size', String(PAGE_SIZE))
  return params.toString()
}

async function reload() {
  loading.value = true
  fetchError.value = ''
  try {
    const response = await request(`${ENDPOINT}?${activeQuery()}`)
    if (!response.ok) {
      throw new Error(`集电线路列表读取失败（HTTP ${response.status}）`)
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? 0
    steps.value = payload.steps ?? []
    // 页码超出范围（例如数据变少）时回到最后一页重新取
    if (page.value > totalPages.value && totalPages.value !== page.value) {
      page.value = totalPages.value
      persistState()
      await reload()
      return
    }
  } catch (error) {
    // 取数失败不拿旧的一批顶上：清空表格与总数，只留错误说明
    rows.value = []
    total.value = 0
    steps.value = []
    fetchError.value = error instanceof Error ? error.message : '集电线路列表读取失败'
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  persistState()
  void reload()
}

function goPage(target: number) {
  if (target < 1 || target > totalPages.value) {
    return
  }
  page.value = target
  persistState()
  void reload()
}

function resetFilters() {
  filters.value = {}
  page.value = 1
  persistState()
  void reload()
}

function exportRows() {
  const params = new URLSearchParams()
  for (const field of filterFields) {
    const value = filters.value[field]?.trim()
    if (value) {
      params.set(field, value)
    }
  }
  window.open(`${ENDPOINT}/export/all?${params.toString()}`, '_blank')
}

async function openDetail(row: Row) {
  detail.value = row
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (response.ok) {
      // 详情接口与列表共用同一序列化口径，线路长度、线路状态必然一致
      detail.value = await response.json()
    }
  } catch {
    // 详情取数失败时保留列表行兜底，不清空
  }
}

async function runAction(action: string, row: Row) {
  pendingAction.value = String(row.id) + action
  fetchError.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message ?? '集电线路动作未生效，请稍后重试')
    }
    fetchError.value = ''
    window.alert(payload.message)
    await reload()
  } catch (error) {
    fetchError.value = error instanceof Error ? error.message : '集电线路操作失败'
  } finally {
    pendingAction.value = ''
  }
}

function openCreate() {
  createForm.value = {}
  createError.value = ''
  createOpen.value = true
}

function closeCreate() {
  createOpen.value = false
  createError.value = ''
}

async function submitCreate() {
  submitting.value = true
  createError.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createForm.value }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message ?? '登记失败，请稍后重试')
    }
    closeCreate()
    window.alert(payload.message)
    await reload()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '登记失败，请稍后重试'
  } finally {
    submitting.value = false
  }
}

async function openLedger() {
  ledgerOpen.value = true
  ledgerRows.value = []
  try {
    const response = await request(`${ENDPOINT}/dispatch-ledger`)
    if (response.ok) {
      const payload = await response.json()
      ledgerRows.value = payload.items ?? []
    }
  } catch {
    ledgerRows.value = []
  }
}

onMounted(() => {
  page.value = initialPage
  void reload()
})
</script>

<style scoped>
.pager {
  display: flex;
  align-items: center;
  gap: 8px;
}

.hint-bar {
  margin-bottom: 10px;
  padding: 8px 12px;
  border: 1px solid #f0c36d;
  background: #fff8eb;
  border-radius: 6px;
  font-size: 13px;
  color: #8a5a00;
}

.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}

.modal {
  background: #fff;
  border-radius: 8px;
  padding: 18px 20px;
  width: 420px;
  max-height: 80vh;
  overflow: auto;
}

.modal-wide {
  width: 720px;
}

.modal h3 {
  margin: 0 0 14px;
}

.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}

.form-item {
  display: block;
  margin-bottom: 10px;
}

.form-item span {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 4px;
}

.form-item input {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
}

.detail-list {
  display: grid;
  grid-template-columns: 90px 1fr;
  gap: 6px 12px;
  margin: 0;
  font-size: 13px;
}

.detail-list dt {
  color: var(--muted);
}

.detail-list dd {
  margin: 0;
}

.link:disabled {
  color: var(--muted);
  cursor: wait;
}
</style>
