<template>
  <section class="compose-page">
    <header class="compose-topbar">
      <router-link class="compose-back" to="/admin">← 返回管理</router-link>
      <div class="compose-title">{{ isEdit ? '编辑文章' : '新增文章' }}</div>
      <div class="compose-actions">
        <button class="admin-action ghost" @click="resetForm">清空</button>
        <button class="admin-action primary" @click="submitArticle">{{ isEdit ? '保存' : '发布' }}</button>
      </div>
    </header>

    <section class="title-first-card editor-card">
      <label class="field-block title-block">
        <span>标题</span>
        <input v-model="form.title" class="compose-title-input" placeholder="输入文章标题" />
      </label>
    </section>

    <section class="editor-single-card editor-card">
      <MdEditor
        v-model="form.content"
        class="md-editor-full"
        :toolbars="toolbars"
        :preview-theme="'github'"
        language="zh-CN"
        theme="dark"
        placeholder="在这里开始写正文……"
      />
    </section>

    <section class="compose-settings-card">
      <div class="compose-card-head">
        <span>附加信息</span>
        <span></span>
      </div>

      <div class="compose-settings-stack">
        <label class="field-block full-row">
          <span>摘要</span>
          <textarea v-model="form.summary" class="compose-summary-input" rows="4" placeholder="写摘要（可后补）"></textarea>
        </label>

        <div class="field-grid two-col compact-grid">
          <label class="field-block">
            <span>文章类型</span>
            <select v-model="form.category">
              <option value="local">本站文章</option>
              <option value="external">外部文章</option>
            </select>
          </label>
          <label class="field-block">
            <span>内容分类</span>
            <select v-model="form.group">
              <option value="技术类">技术类</option>
              <option value="随笔类">随笔类</option>
              <option value="生活类">生活类</option>
            </select>
          </label>
        </div>

        <div class="field-grid two-col compact-grid">
          <label class="field-block">
            <span>封面图</span>
            <input v-model="form.cover" placeholder="可选，填写封面图片 URL" />
          </label>
          <label class="field-block">
            <span>标签</span>
            <input v-model="form.tagsText" placeholder="多个标签用英文逗号分隔" />
          </label>
        </div>

        <label v-if="form.category === 'external'" class="field-block full-row">
          <span>跳转链接</span>
          <input v-model="form.url" placeholder="https://example.com" />
        </label>
      </div>
    </section>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive } from 'vue'
import axios from 'axios'
import { useRoute, useRouter } from 'vue-router'
import { MdEditor } from 'md-editor-v3'
import 'md-editor-v3/lib/style.css'

const apiBase = `/api`
const router = useRouter()
const route = useRoute()
const isEdit = computed(() => !!route.query.id)

const toolbars = [
  'bold', 'italic', 'strikeThrough', '-',
  'title', 'quote', 'unorderedList', 'orderedList', '-',
  'link', 'image', 'table', 'code', 'codeRow', '-',
  'revoke', 'next', 'preview', 'fullscreen'
]

const defaultForm = () => ({
  category: 'local',
  group: '技术类',
  title: '',
  summary: '',
  cover: '',
  tagsText: '',
  content: '',
  url: '',
})

const form = reactive(defaultForm())

function resetForm() {
  Object.assign(form, defaultForm())
}

async function loadForEdit() {
  if (!isEdit.value) return
  const res = await axios.get(`${apiBase}/cards/${route.query.id}`)
  const card = res.data
  form.category = card.category || 'local'
  form.group = '技术类'
  form.title = card.title || ''
  form.summary = card.summary || ''
  form.cover = card.cover || ''
  form.tagsText = (card.tags || []).join(', ')
  form.content = card.content || ''
  form.url = card.url || ''
}

onMounted(loadForEdit)

async function submitArticle() {
  const payload = {
    category: form.category,
    title: form.title,
    summary: form.summary,
    cover: form.cover,
    tags: form.tagsText.split(',').map(t => t.trim()).filter(Boolean),
  }
  if (form.category === 'local') payload.content = form.content
  if (form.category === 'external') payload.url = form.url

  try {
    const res = isEdit.value
      ? await axios.put(`${apiBase}/cards/${route.query.id}`, payload)
      : await axios.post(`${apiBase}/api/publish`, payload)
    if (res.data?.ok) {
      router.push('/admin')
    } else {
      alert(isEdit.value ? '保存失败' : '发布失败')
    }
  } catch (err) {
    alert(err?.response?.data?.error || (isEdit.value ? '保存失败，请检查输入' : '发布失败，请检查输入'))
  }
}
</script>
