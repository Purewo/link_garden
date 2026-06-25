/**
 * Covers feature API wrappers.
 *
 * Thin typed facade over the openapi-fetch client. Views never call the raw
 * client; they call these wrappers so we have one place to attach feature-
 * specific normalization and to mock in tests.
 */

import { api } from '@/shared/api/client'
import { mapResponseError } from '@/shared/api/errors'
import type { CardRead, CoverUploadResponse } from '@/shared/types/domain'

/**
 * POST /api/v1/covers — multipart upload, admin-only.
 *
 * The openapi-fetch client serializes FormData transparently when the body
 * type in the schema is multipart. We pass the File and card_id as a
 * FormData instance to ensure the boundary is set correctly by the browser.
 */
export async function uploadCover(
  file: File,
  cardId: string,
): Promise<CoverUploadResponse & { card: CardRead }> {
  const body = new FormData()
  body.append('file', file)
  body.append('card_id', cardId)

  // openapi-fetch's typed client expects a structured `body` for typed routes;
  // for multipart we pass FormData directly via the bodySerializer override.
  const { data, error, response } = await api.POST('/covers', {
    // @ts-expect-error openapi-typescript renders multipart bodies as
    // an object schema; we override the serializer so the FormData ships
    // correctly with the browser-set boundary.
    body,
    bodySerializer: (b: FormData) => b,
  })

  if (error || !data) {
    throw mapResponseError(error, response)
  }
  return data as CoverUploadResponse & { card: CardRead }
}
