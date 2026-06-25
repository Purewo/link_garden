<script setup lang="ts">
/**
 * PublishForm — the publish/edit shell.
 *
 * Layout (per PROJECT_NOTES decisions):
 *   - Title input at the top.
 *   - md-editor-v3 occupies the main work area (no custom right-side preview;
 *     the editor's built-in preview toggle is sufficient).
 *   - Secondary fields (summary / tags / cover / group / slug) sink into a
 *     bottom 附加信息 region.
 *
 * The component is a controlled shell over the `useCardForm` composable;
 * parents pass it in so they can also call `loadFromDetail` for edit mode.
 */
import { computed } from 'vue'
import { MdEditor } from 'md-editor-v3'
import 'md-editor-v3/lib/style.css'
import CoverUploader from '@/features/covers/components/CoverUploader.vue'
import type { UseCardFormReturn } from '@/features/cards/composables/useCardForm'

const props = defineProps<{
  formCtl: UseCardFormReturn
}>()

const emit = defineEmits<{
  (e: 'submit'): void
  (e: 'cancel'): void
  (e: 'cover-error', message: string): void
}>()

const form = props.formCtl.form
const errors = props.formCtl.errors
const submitting = props.formCtl.submitting
const isEdit = props.formCtl.isEdit

const toolbars = [
  'bold',
  'italic',
  'strikeThrough',
  '-',
  'title',
  'quote',
  'unorderedList',
  'orderedList',
  '-',
  'link',
  'image',
  'table',
  'code',
  'codeRow',
  '-',
  'revoke',
  'next',
  'preview',
  'fullscreen',
] as const

// Slug preview is for display only; the server is the source of truth for
// uniqueness/auto-suffixing. We just hint at what the server will likely do.
const slugPreview = computed(() => {
  const explicit = form.slug.trim()
  if (explicit) return explicit
  const fromTitle = form.title
    .trim()
    .toLowerCase()
    .replace(/\s+/g, '-')
    .replace(/[^a-z0-9一-鿿-]/g, '')
  return fromTitle || '(自动生成)'
})

function onCoverUpdated(url: string) {
  form.cover = url
}

function onCoverError(message: string) {
  emit('cover-error', message)
}
</script>

<template>
  <form class="publish-form" @submit.prevent="emit('submit')">
    <header class="publish-form__topbar">
      <div class="publish-form__title-row">
        <span class="publish-form__kicker">{{ isEdit ? '编辑文章' : '新增文章' }}</span>
        <input
          v-model="form.title"
          class="publish-form__title-input"
          placeholder="输入文章标题"
          autocomplete="off"
          spellcheck="false"
        />
        <p v-if="errors.title" class="publish-form__error">{{ errors.title }}</p>
      </div>
      <div class="publish-form__actions">
        <button
          type="button"
          class="publish-form__btn ghost"
          :disabled="submitting"
          @click="emit('cancel')"
        >
          取消
        </button>
        <button type="submit" class="publish-form__btn primary" :disabled="submitting">
          {{ submitting ? '提交中…' : isEdit ? '保存' : '发布' }}
        </button>
      </div>
    </header>

    <section v-if="form.category === 'local'" class="publish-form__editor-card">
      <MdEditor
        v-model="form.body"
        class="publish-form__md-editor"
        :toolbars="(toolbars as unknown as never[])"
        preview-theme="github"
        language="zh-CN"
        theme="dark"
        placeholder="在这里开始写正文……"
      />
      <p v-if="errors.body" class="publish-form__error">{{ errors.body }}</p>
    </section>

    <section v-else class="publish-form__external-card">
      <label class="publish-form__field">
        <span>跳转链接</span>
        <input
          v-model="form.url"
          placeholder="https://example.com"
          autocomplete="off"
          spellcheck="false"
        />
      </label>
      <p v-if="errors.url" class="publish-form__error">{{ errors.url }}</p>
    </section>

    <section class="publish-form__settings-card">
      <header class="publish-form__settings-head">
        <span>附加信息</span>
        <small>填写摘要、标签、封面与分组</small>
      </header>

      <div class="publish-form__settings-grid">
        <label class="publish-form__field publish-form__field--full">
          <span>摘要</span>
          <textarea
            v-model="form.summary"
            rows="3"
            placeholder="写摘要（可后补）"
          ></textarea>
        </label>

        <label class="publish-form__field">
          <span>文章类型</span>
          <select v-model="form.category">
            <option value="local">本站文章</option>
            <option value="external">外部文章</option>
          </select>
          <p v-if="errors.category" class="publish-form__error">{{ errors.category }}</p>
        </label>

        <label class="publish-form__field">
          <span>内容分类</span>
          <select v-model="form.group">
            <option value="">不指定</option>
            <option value="技术类">技术类</option>
            <option value="随笔类">随笔类</option>
            <option value="生活类">生活类</option>
          </select>
        </label>

        <label class="publish-form__field publish-form__field--full">
          <span>标签</span>
          <input
            v-model="form.tagsText"
            placeholder="多个标签用英文逗号或空格分隔，最多 16 个"
            autocomplete="off"
          />
        </label>

        <label class="publish-form__field">
          <span>Slug</span>
          <input
            v-model="form.slug"
            placeholder="留空将由服务器从标题生成"
            autocomplete="off"
            spellcheck="false"
          />
          <small class="publish-form__hint">预览：{{ slugPreview }}</small>
        </label>

        <div class="publish-form__field">
          <span>封面</span>
          <CoverUploader
            v-model="form.cover"
            :card-id="form.id"
            :disabled="submitting"
            @error="onCoverError"
            @update:model-value="onCoverUpdated"
          />
          <p v-if="errors.cover" class="publish-form__error">{{ errors.cover }}</p>
        </div>
      </div>

      <p v-if="errors.general" class="publish-form__error" role="alert">
        {{ errors.general }}
      </p>
    </section>
  </form>
</template>

<style scoped>
.publish-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.publish-form__topbar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-end;
  justify-content: space-between;
}
.publish-form__title-row {
  flex: 1 1 320px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.publish-form__kicker {
  font-size: 12px;
  letter-spacing: 0.08em;
  color: var(--lg-text-muted, #8a93a3);
  text-transform: uppercase;
}
.publish-form__title-input {
  font-size: 22px;
  font-weight: 600;
  padding: 8px 10px;
  border: 1px solid var(--lg-border, #2a2f3a);
  border-radius: 8px;
  background: var(--lg-surface, #1c2230);
  color: var(--lg-text, #e6ebf5);
}
.publish-form__actions {
  display: flex;
  gap: 8px;
}
.publish-form__btn {
  padding: 8px 14px;
  border-radius: 8px;
  border: 1px solid var(--lg-border, #2a2f3a);
  background: var(--lg-surface, #1c2230);
  color: var(--lg-text, #d8dee9);
  cursor: pointer;
  font-size: 13px;
}
.publish-form__btn.primary {
  background: var(--lg-accent, #4fa3ff);
  color: #0b0d12;
  border-color: transparent;
}
.publish-form__btn.ghost {
  background: transparent;
}
.publish-form__btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.publish-form__editor-card,
.publish-form__external-card,
.publish-form__settings-card {
  background: var(--lg-surface, #1c2230);
  border: 1px solid var(--lg-border, #2a2f3a);
  border-radius: 12px;
  padding: 12px;
}
.publish-form__md-editor {
  height: 60vh;
  min-height: 360px;
}
.publish-form__settings-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px 4px 12px;
  border-bottom: 1px dashed var(--lg-border, #2a2f3a);
  margin-bottom: 12px;
}
.publish-form__settings-head span {
  font-size: 14px;
  font-weight: 600;
}
.publish-form__settings-head small {
  color: var(--lg-text-muted, #8a93a3);
  font-size: 12px;
}
.publish-form__settings-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}
.publish-form__field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  color: var(--lg-text-muted, #8a93a3);
}
.publish-form__field--full {
  grid-column: 1 / -1;
}
.publish-form__field input,
.publish-form__field select,
.publish-form__field textarea {
  font-size: 13px;
  padding: 6px 10px;
  border: 1px solid var(--lg-border, #2a2f3a);
  border-radius: 8px;
  background: var(--lg-surface-2, #161a23);
  color: var(--lg-text, #e6ebf5);
  font-family: inherit;
}
.publish-form__hint {
  color: var(--lg-text-muted, #8a93a3);
  font-size: 11px;
}
.publish-form__error {
  color: var(--lg-danger, #ff6b6b);
  font-size: 12px;
  margin: 0;
}
</style>
