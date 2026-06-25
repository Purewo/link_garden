<script setup lang="ts">
/**
 * CoverUploader — drag/drop + click + paste cover image picker.
 *
 * Emits `update:modelValue` with the persisted URL after a successful upload.
 * The component is a thin shell over `useCoverUpload(cardId)`; all of the
 * validation + preview revocation + upload state lives in the composable so
 * the UI stays declarative.
 *
 * Two modes:
 *   - With a cardId: clicking "上传" calls POST /covers immediately.
 *   - Without a cardId (e.g. when creating a brand new card): the picker
 *     stages the file and emits `staged` so the parent form can persist it
 *     after the card is created.
 */
import { computed, ref, toRef, watch } from 'vue'
import { useCoverUpload } from '@/features/covers/composables/useCoverUpload'

const props = withDefaults(
  defineProps<{
    /** Currently persisted cover URL (or null). */
    modelValue: string | null
    /** The card id once it exists; null before the card is published. */
    cardId: string | null
    /** Disable the picker (e.g., during sibling form submission). */
    disabled?: boolean
  }>(),
  { disabled: false },
)

const emit = defineEmits<{
  (e: 'update:modelValue', url: string): void
  (e: 'staged', file: File): void
  (e: 'error', message: string): void
}>()

const cardIdRef = toRef(props, 'cardId')
const {
  file,
  previewUrl,
  uploading,
  error,
  hasStagedFile,
  selectFile,
  upload,
  reset,
} = useCoverUpload(cardIdRef)

const dropping = ref(false)
const inputEl = ref<HTMLInputElement | null>(null)

const displayedUrl = computed(() => previewUrl.value ?? props.modelValue ?? null)

// Surface composable-level errors as toast-friendly events for the parent.
watch(error, (err) => {
  if (err) emit('error', err.message)
})

async function pickFromInput(event: Event) {
  const target = event.target as HTMLInputElement
  const picked = target.files?.[0] ?? null
  if (!picked) return
  await selectFile(picked)
  if (file.value) emit('staged', file.value)
  // Allow re-selecting the same file later by clearing the input.
  target.value = ''
}

async function handleDrop(event: DragEvent) {
  dropping.value = false
  const picked = event.dataTransfer?.files?.[0] ?? null
  if (!picked) return
  await selectFile(picked)
  if (file.value) emit('staged', file.value)
}

async function handlePaste(event: ClipboardEvent) {
  const items = event.clipboardData?.items
  if (!items) return
  for (const item of items) {
    if (item.kind === 'file') {
      const picked = item.getAsFile()
      if (picked) {
        await selectFile(picked)
        if (file.value) emit('staged', file.value)
        return
      }
    }
  }
}

async function handleUpload() {
  if (!hasStagedFile.value) return
  try {
    const result = await upload()
    emit('update:modelValue', result.url)
  } catch {
    // error already surfaced via the watcher above
  }
}

function handleClear() {
  reset()
  emit('update:modelValue', '')
}

function openPicker() {
  if (!props.disabled) inputEl.value?.click()
}
</script>

<template>
  <div
    class="cover-uploader"
    :class="{ 'is-dropping': dropping, 'is-disabled': disabled }"
    role="button"
    tabindex="0"
    aria-label="封面图片"
    @dragover.prevent="dropping = true"
    @dragleave.prevent="dropping = false"
    @drop.prevent="handleDrop"
    @paste="handlePaste"
    @keydown.enter.prevent="openPicker"
    @keydown.space.prevent="openPicker"
  >
    <input
      ref="inputEl"
      type="file"
      accept="image/png,image/jpeg,image/webp"
      class="cover-uploader__input"
      :disabled="disabled"
      @change="pickFromInput"
    />

    <div class="cover-uploader__preview" @click="openPicker">
      <img v-if="displayedUrl" :src="displayedUrl" alt="封面预览" />
      <div v-else class="cover-uploader__placeholder">
        <span>点击 / 拖拽 / 粘贴上传封面</span>
        <small>PNG · JPEG · WebP，最大 5 MiB</small>
      </div>
    </div>

    <div class="cover-uploader__actions">
      <button
        type="button"
        class="cover-uploader__btn"
        :disabled="disabled || uploading"
        @click="openPicker"
      >
        选择文件
      </button>
      <button
        type="button"
        class="cover-uploader__btn primary"
        :disabled="!hasStagedFile || !cardId || disabled || uploading"
        @click="handleUpload"
      >
        {{ uploading ? '上传中…' : '上传' }}
      </button>
      <button
        v-if="modelValue || hasStagedFile"
        type="button"
        class="cover-uploader__btn ghost"
        :disabled="disabled || uploading"
        @click="handleClear"
      >
        清除
      </button>
    </div>

    <p v-if="error" class="cover-uploader__error" role="alert">
      {{ error.message }}
    </p>
    <p v-else-if="hasStagedFile && !cardId" class="cover-uploader__hint">
      将在文章创建后自动上传
    </p>
  </div>
</template>

<style scoped>
.cover-uploader {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
  border: 1px dashed var(--lg-border, #2a2f3a);
  border-radius: 12px;
  outline: none;
  transition: border-color 0.15s ease;
}
.cover-uploader:focus-visible,
.cover-uploader.is-dropping {
  border-color: var(--lg-accent, #4fa3ff);
}
.cover-uploader.is-disabled {
  opacity: 0.6;
  pointer-events: none;
}
.cover-uploader__input {
  display: none;
}
.cover-uploader__preview {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  border-radius: 8px;
  overflow: hidden;
  background: var(--lg-surface-2, #161a23);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.cover-uploader__preview img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.cover-uploader__placeholder {
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: center;
  color: var(--lg-text-muted, #8a93a3);
  font-size: 13px;
}
.cover-uploader__placeholder small {
  font-size: 11px;
  opacity: 0.7;
}
.cover-uploader__actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.cover-uploader__btn {
  padding: 6px 12px;
  border-radius: 8px;
  border: 1px solid var(--lg-border, #2a2f3a);
  background: var(--lg-surface, #1c2230);
  color: var(--lg-text, #d8dee9);
  cursor: pointer;
  font-size: 13px;
}
.cover-uploader__btn.primary {
  background: var(--lg-accent, #4fa3ff);
  color: #0b0d12;
  border-color: transparent;
}
.cover-uploader__btn.ghost {
  background: transparent;
}
.cover-uploader__btn:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
.cover-uploader__error {
  color: var(--lg-danger, #ff6b6b);
  font-size: 12px;
  margin: 0;
}
.cover-uploader__hint {
  color: var(--lg-text-muted, #8a93a3);
  font-size: 12px;
  margin: 0;
}
</style>
