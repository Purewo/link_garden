<script setup lang="ts">
/**
 * `LoginForm` — admin login form.
 *
 * Owns the controlled username/password inputs and the submit button.
 * Delegates the network call to `useAuthStore.login()`. Surfaces
 * `AppError.code` to the parent via `update:error` so the host view
 * can decide how to render it (toast, inline banner, etc.).
 *
 * Contracts (B9 / B10):
 *   - `BaseInput` and `BaseButton` are simple primitives from B9's
 *     `shared/ui/`. They emit `update:modelValue` like any v-model peer.
 *     If they aren't wired up at integration time, the underlying
 *     `<input>` / `<button>` markup still works — these wrappers add
 *     styling and a11y but are not required for behaviour.
 *   - `useAuthStore` is the Pinia store from `./store.ts`.
 *   - The `AppError` envelope (B9) carries a `.code` machine-readable
 *     string and a `.message` human string; we forward both.
 */
import { reactive, ref } from 'vue'
import { useAuthStore } from '../store'
import { AppError } from '../../../shared/api/errors'
import BaseInput from '../../../shared/ui/BaseInput.vue'
import BaseButton from '../../../shared/ui/BaseButton.vue'

const emit = defineEmits<{
  /** Emitted on a successful login so the host view can redirect. */
  (e: 'success'): void
  /** Emitted on every login attempt outcome; `null` clears prior errors. */
  (e: 'update:error', err: AppError | null): void
}>()

const form = reactive({
  username: '',
  password: '',
})

const submitting = ref(false)
const fieldErrors = reactive<{ username: string | null; password: string | null }>({
  username: null,
  password: null,
})

const auth = useAuthStore()

/**
 * Cheap client-side validation. The server has the final say (and uses
 * a constant-time compare for the credential check itself), so this is
 * purely a UX gate to skip pointless round-trips.
 */
function validate(): boolean {
  fieldErrors.username = form.username.trim() === '' ? '请输入用户名' : null
  fieldErrors.password = form.password === '' ? '请输入密码' : null
  return fieldErrors.username === null && fieldErrors.password === null
}

async function handleSubmit(): Promise<void> {
  if (submitting.value) return
  emit('update:error', null)
  if (!validate()) return

  submitting.value = true
  try {
    await auth.login(form.username.trim(), form.password)
    form.password = '' // never keep the cleartext password around
    emit('success')
  } catch (err) {
    const appErr =
      err instanceof AppError ? err : AppError.fromUnknown(err)
    emit('update:error', appErr)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <form class="login-form" novalidate @submit.prevent="handleSubmit">
    <div class="login-form__field">
      <label for="login-username" class="login-form__label">用户名</label>
      <BaseInput
        id="login-username"
        v-model="form.username"
        name="username"
        type="text"
        autocomplete="username"
        :disabled="submitting"
        :aria-invalid="fieldErrors.username !== null"
        aria-describedby="login-username-error"
      />
      <p
        v-if="fieldErrors.username"
        id="login-username-error"
        class="login-form__error"
        role="alert"
      >
        {{ fieldErrors.username }}
      </p>
    </div>

    <div class="login-form__field">
      <label for="login-password" class="login-form__label">密码</label>
      <BaseInput
        id="login-password"
        v-model="form.password"
        name="password"
        type="password"
        autocomplete="current-password"
        :disabled="submitting"
        :aria-invalid="fieldErrors.password !== null"
        aria-describedby="login-password-error"
      />
      <p
        v-if="fieldErrors.password"
        id="login-password-error"
        class="login-form__error"
        role="alert"
      >
        {{ fieldErrors.password }}
      </p>
    </div>

    <BaseButton
      type="submit"
      class="login-form__submit"
      :disabled="submitting"
      :loading="submitting"
    >
      {{ submitting ? '登录中…' : '登录' }}
    </BaseButton>
  </form>
</template>

<style scoped>
.login-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  width: 100%;
  max-width: 22rem;
}

.login-form__field {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.login-form__label {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--lg-text-muted, #555);
}

.login-form__error {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--lg-color-danger, #c0392b);
}

.login-form__submit {
  margin-top: 0.5rem;
}
</style>
