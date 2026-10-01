<template>
  <section class="page" data-module="collector">
    <header class="page-head">
      <div>
        <h2>集电线路管理</h2>
        <p class="page-desc">维护集电线路，围绕线路编号、电压等级、起止杆塔、线路长度做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记集电线路</button>
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
      <label v-for="field in filterFields" :key="field.key" class="filter-item">
        <span>{{ field.label }}</span>
        <input v-model="filters[field.key]" :placeholder="`按${field.label}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">查看明细</button>
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">
            {{ errorMessage || notice || '暂无集电线路数据，可先登记集电线路' }}
          </td>
        </tr>
      </tbody>
    </table>

    <div class="pager">
      <button class="btn" type="button" :disabled="page <= 1 || loading" @click="goPage(page - 1)">上一页</button>
      <span>第 {{ page }} / {{ totalPages }} 页（每页
        <select v-model.number="size" :disabled="loading" @change="onSizeChange">
          <option :value="10">10</option>
          <option :value="20">20</option>
          <option :value="50">50</option>
        </select> 条）</span>
      <button class="btn" type="button" :disabled="page >= totalPages || loading" @click="goPage(page + 1)">下一页</button>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条集电线路记录</span>
      <span v-if="successMessage" class="ok-text">{{ successMessage }}</span>
      <span v-if="notice" class="warn-text">{{ notice }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="showCreate" class="modal-mask" @click.self="showCreate = false">
      <div class="modal">
        <h3>登记集电线路</h3>
        <p class="modal-tip">线路编号沿用调度台账既有字段，只能从已建档编号中选择。</p>
        <div class="form-grid">
          <label>
            <span>线路编号 *</span>
            <input v-model="form['线路编号']" list="ledger-line-nos" placeholder="选择台账中已建档的线路编号" />
            <datalist id="ledger-line-nos">
              <option v-for="item in ledger" :key="String(item['线路编号'])" :value="String(item['线路编号'])"></option>
            </datalist>
          </label>
          <label v-for="field in createFields.slice(1)" :key="field">
            <span>{{ field }}{{ requiredFields.includes(field) ? ' *' : '' }}</span>
            <input v-model="form[field]" />
          </label>
        </div>
        <p v-if="formError" class="error-text">{{ formError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitCreate">
            {{ submitting ? '提交中…' : '提交登记' }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal">
        <h3>集电线路明细</h3>
        <table class="detail-table">
          <tbody>
            <tr v-for="column in columns" :key="column">
              <th>{{ column }}</th>
              <td>{{ detail[column] ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
        <p class="modal-tip">明细中的线路长度、线路状态与列表取同一份数据。</p>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="detail = null">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/collector'
const columns = ['线路编号', '电压等级', '起止杆塔', '线路长度', '所属场站', '上次巡视日', '缺陷数量', '线路状态']
const actions = ['提交巡视', '登记缺陷', '停运线路']
const stats = [
  { label: '在运线路', value: 0 },
  { label: '存在缺陷线路', value: 0 },
  { label: '待巡视线段', value: 0 },
]
// 筛选字段固定对齐后端入参，避免中文字段名直接当 query 参数导致后端收不到条件。
const filterFields = [
  { key: 'line_no', label: '线路编号' },
  { key: 'voltage', label: '电压等级' },
  { key: 'towers', label: '起止杆塔' },
] as const

const createFields = ['线路编号', '电压等级', '起止杆塔', '线路长度', '所属场站', '上次巡视日']
const requiredFields = ['线路编号', '电压等级', '起止杆塔']

const FILTER_STORAGE_KEY = 'collector:filters'
const DRAFT_STORAGE_KEY = 'collector:draft'

function readStorage<T>(key: string): T | null {
  try {
    return JSON.parse(localStorage.getItem(key) ?? 'null') as T | null
  } catch {
    return null
  }
}

const rows = ref<Row[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const loading = ref(false)
const errorMessage = ref('')
const notice = ref('')
const successMessage = ref('')

// 重新进入页面时，上一次填的筛选条件要留住（排序仍走后端默认的 id 升序，页码回第一页）。
const filters = reactive<Record<string, string>>({ line_no: '', voltage: '', towers: '' })
const savedFilters = readStorage<Record<string, string>>(FILTER_STORAGE_KEY)
if (savedFilters) {
  for (const field of filterFields) {
    if (typeof savedFilters[field.key] === 'string') {
      filters[field.key] = savedFilters[field.key]
    }
  }
}
watch(filters, (value) => localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify(value)), { deep: true })

// 登记草稿同样留住：提交失败或关掉弹窗后再打开，已填内容不丢。
const emptyForm = (): Record<string, string> =>
  Object.fromEntries(createFields.map((field) => [field, '']))
const form = reactive<Record<string, string>>(emptyForm())
const savedDraft = readStorage<Record<string, string>>(DRAFT_STORAGE_KEY)
if (savedDraft) {
  for (const field of createFields) {
    if (typeof savedDraft[field] === 'string') {
      form[field] = savedDraft[field]
    }
  }
}
watch(form, (value) => localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(value)), { deep: true })

const showCreate = ref(false)
const submitting = ref(false)
const formError = ref('')
const ledger = ref<Row[]>([])
const detail = ref<Row | null>(null)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / size.value)))

function search() {
  page.value = 1
  void reload()
}

function resetFilters() {
  filters.line_no = ''
  filters.voltage = ''
  filters.towers = ''
  page.value = 1
  void reload()
}

function goPage(target: number) {
  page.value = Math.min(Math.max(1, target), totalPages.value)
  void reload()
}

function onSizeChange() {
  page.value = 1
  void reload()
}

function exportRows() {
  const params = new URLSearchParams()
  for (const field of filterFields) {
    const value = filters[field.key].trim()
    if (value) {
      params.set(field.key, value)
    }
  }
  window.open(`${ENDPOINT}/export?${params.toString()}`, '_blank')
}

async function openCreate() {
  formError.value = ''
  successMessage.value = ''
  showCreate.value = true
  if (!ledger.value.length) {
    try {
      const response = await request(`${ENDPOINT}/dispatch-ledger`)
      if (response.ok) {
        const payload = await response.json()
        ledger.value = Array.isArray(payload.items) ? payload.items : []
      }
    } catch {
      // 台账取数失败只影响编号候选，不挡住登记弹窗（提交时后端还会再校验一次）。
      ledger.value = []
    }
  }
}

async function submitCreate() {
  formError.value = ''
  const values: Record<string, string> = {}
  for (const field of createFields) {
    values[field] = form[field].trim()
  }
  submitting.value = true
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    if (!response.ok) {
      throw new Error('集电线路登记请求未送达，请稍后重试')
    }
    const payload = await response.json()
    if (!payload.ok) {
      // 校验没过（缺字段、编号不在台账、重复提交等）：弹窗保留，已填内容原样留住。
      formError.value = payload.message || '登记未通过校验'
      return
    }
    successMessage.value = payload.message || '集电线路已登记'
    showCreate.value = false
    for (const field of createFields) {
      form[field] = ''
    }
    page.value = 1
    await reload()
  } catch (error) {
    formError.value = error instanceof Error ? error.message : '集电线路登记失败'
  } finally {
    submitting.value = false
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('集电线路明细读取失败')
    }
    detail.value = (await response.json()) as Row
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '集电线路明细读取失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error('集电线路动作未生效，请稍后重试')
    }
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message || '集电线路操作未生效')
    }
    successMessage.value = payload.message || '操作已生效'
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '集电线路操作失败'
  }
}

// 用序号丢弃过期响应：快速翻页/查询时只认最后一次请求。
let requestSeq = 0

async function reload() {
  const seq = ++requestSeq
  errorMessage.value = ''
  notice.value = ''
  loading.value = true
  const params = new URLSearchParams()
  for (const field of filterFields) {
    const value = filters[field.key].trim()
    if (value) {
      params.set(field.key, value)
    }
  }
  params.set('page', String(page.value))
  params.set('size', String(size.value))
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) {
      throw new Error('集电线路列表读取失败')
    }
    const payload = await response.json()
    if (seq !== requestSeq) {
      return
    }
    rows.value = Array.isArray(payload.items) ? payload.items : []
    total.value = typeof payload.total === 'number' ? payload.total : rows.value.length
    notice.value = payload.notice || ''
    // 筛选收紧后当前页可能超出范围：回到最后一页，而不是显示一片空白。
    if (!rows.value.length && total.value > 0 && page.value > 1) {
      page.value = Math.max(1, Math.ceil(total.value / size.value))
      loading.value = false
      void reload()
      return
    }
  } catch (error) {
    if (seq !== requestSeq) {
      return
    }
    // 取数失败时明确清空，不拿上一批旧数据顶上；筛选条件保留在输入框里。
    rows.value = []
    total.value = 0
    errorMessage.value = error instanceof Error ? error.message : '集电线路列表读取失败'
  } finally {
    if (seq === requestSeq) {
      loading.value = false
    }
  }
}

onMounted(reload)
</script>

<style scoped>
.pager {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 8px;
  font-size: 12px;
  color: var(--muted);
}
.pager select {
  padding: 2px 4px;
}
.ok-text {
  color: #067647;
}
.warn-text {
  color: #b54708;
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
  padding: 20px 24px;
  width: 560px;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 64px);
  overflow: auto;
}
.modal h3 {
  margin: 0 0 8px;
}
.modal-tip {
  color: var(--muted);
  font-size: 12px;
  margin: 0 0 12px;
}
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 16px;
}
.form-grid label span {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 2px;
}
.form-grid input {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}
.detail-table th,
.detail-table td {
  border: 1px solid var(--border);
  padding: 6px 10px;
  font-size: 13px;
  text-align: left;
}
.detail-table th {
  width: 120px;
  color: var(--muted);
  background: #f8fafc;
}
</style>
