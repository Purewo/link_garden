/**
 * useCoverUpload — drives the CoverUploader for a given card id.
 *
 * Lifecycle:
 *   - selectFile(file) validates client-side (type, size, dims), generates a
 *     local preview via URL.createObjectURL, and stashes the File for upload.
 *   - upload() POSTs the staged file to /api/v1/covers, returns the new URL
 *     (with cache-buster) and the refreshed CardRead.
 *   - reset() revokes the object URL and clears state.
 *
 * The preview URL is always revoked before being overwritten or on reset,
 * which avoids the well-known memory leak pattern with createObjectURL.
 */

import { computed, onBeforeUnmount, ref } from 'vue'
import type { Ref } from 'vue'
// NOTE: cross-unit dependency — features/covers/api.ts is delivered by B12
// (this unit). We rely on the typed wrapper rather than calling the openapi
// client directly so tests can mock at the wrapper.
import { uploadCover } from '@/features/covers/api'
import type { CardRead } from '@/shared/types/domain'
import { AppError } from '@/shared/api/errors'

export interface UseCoverUploadOptions {
  /** Hard ceiling enforced client-side; the server is the source of truth. */
  maxBytes?: number
  /** Minimum side length to refuse blurry uploads early. */
  minDim?: number
  /** Maximum side length matching the server's MAX_COVER_DIM. */
  maxDim?: number
  /** Allowed MIME types. */
  acceptedTypes?: readonly string[]
}

const DEFAULTS: Required<UseCoverUploadOptions> = {
  maxBytes: 5 * 1024 * 1024,
  minDim: 200,
  maxDim: 4096,
  acceptedTypes: ['image/png', 'image/jpeg', 'image/webp'],
}

export interface UseCoverUploadReturn {
  file: Ref<File | null>
  previewUrl: Ref<string | null>
  uploading: Ref<boolean>
  error: Ref<AppError | Error | null>
  hasStagedFile: Ref<boolean>
  selectFile: (file: File) => Promise<void>
  upload: () => Promise<{ url: string; card: CardRead }>
  reset: () => void
}

/**
 * Read image dimensions client-side via a transient Image element.
 * Resolves to `null` if the browser cannot decode the file (e.g., corrupt).
 */
function readImageDimensions(
  url: string,
): Promise<{ width: number; height: number } | null> {
  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight })
    img.onerror = () => resolve(null)
    img.src = url
  })
}

export function useCoverUpload(
  cardId: Ref<string | null> | (() => string | null),
  options: UseCoverUploadOptions = {},
): UseCoverUploadReturn {
  const cfg = { ...DEFAULTS, ...options }
  const file = ref<File | null>(null)
  const previewUrl = ref<string | null>(null)
  const uploading = ref(false)
  const error = ref<AppError | Error | null>(null)

  const hasStagedFile = computed(() => file.value !== null)

  function revokePreview() {
    if (previewUrl.value) {
      URL.revokeObjectURL(previewUrl.value)
      previewUrl.value = null
    }
  }

  async function selectFile(picked: File): Promise<void> {
    error.value = null
    if (!cfg.acceptedTypes.includes(picked.type)) {
      error.value = new AppError(
        'cover_bad_type',
        `仅支持 ${cfg.acceptedTypes.join(', ')}`,
        415,
      )
      return
    }
    if (picked.size > cfg.maxBytes) {
      error.value = new AppError(
        'cover_too_large',
        `文件超过 ${(cfg.maxBytes / 1024 / 1024).toFixed(1)} MiB`,
        413,
      )
      return
    }

    const objectUrl = URL.createObjectURL(picked)
    const dims = await readImageDimensions(objectUrl)
    if (!dims) {
      URL.revokeObjectURL(objectUrl)
      error.value = new AppError('invalid_image', '无法解码该图片', 400)
      return
    }
    if (dims.width < cfg.minDim || dims.height < cfg.minDim) {
      URL.revokeObjectURL(objectUrl)
      error.value = new AppError(
        'invalid_image',
        `图片尺寸过小，最小 ${cfg.minDim}x${cfg.minDim}`,
        400,
      )
      return
    }
    if (dims.width > cfg.maxDim || dims.height > cfg.maxDim) {
      URL.revokeObjectURL(objectUrl)
      error.value = new AppError(
        'invalid_image',
        `图片尺寸过大，最大 ${cfg.maxDim}x${cfg.maxDim}`,
        400,
      )
      return
    }

    revokePreview()
    file.value = picked
    previewUrl.value = objectUrl
  }

  async function upload(): Promise<{ url: string; card: CardRead }> {
    if (!file.value) {
      throw new AppError('invalid_payload', '请先选择封面图片', 400)
    }
    const id = typeof cardId === 'function' ? cardId() : cardId.value
    if (!id) {
      throw new AppError('invalid_payload', '缺少 card_id', 400)
    }
    uploading.value = true
    error.value = null
    try {
      const response = await uploadCover(file.value, id)
      // Server returns the freshly cache-busted URL; downstream code should
      // prefer this over the local preview so other clients see the new file.
      revokePreview()
      file.value = null
      return { url: response.url, card: response.card }
    } catch (err) {
      const wrapped =
        err instanceof Error ? err : new Error('封面上传失败')
      error.value = wrapped
      throw wrapped
    } finally {
      uploading.value = false
    }
  }

  function reset() {
    revokePreview()
    file.value = null
    error.value = null
    uploading.value = false
  }

  onBeforeUnmount(revokePreview)

  return {
    file,
    previewUrl,
    uploading,
    error,
    hasStagedFile,
    selectFile,
    upload,
    reset,
  }
}
