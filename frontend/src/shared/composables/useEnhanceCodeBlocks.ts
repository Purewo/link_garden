/**
 * `useEnhanceCodeBlocks(rootRef)` — idempotent post-render decoration
 * for sanitised markdown HTML.
 *
 * The server emits fences as
 *
 *   <pre data-language="ts"><code class="hljs language-ts">…</code></pre>
 *
 * We walk every `pre[data-language]` under `rootRef` that has not been
 * processed yet, run highlight.js, then wrap it in a `.code-card`
 * shell with toolbar + copy button. The `data-hl-done="1"` flag kills
 * the legacy "decorate twice on re-render" bug (PROJECT_NOTES) so
 * remounting the article view never accumulates DOM cruft.
 */
import { nextTick, onMounted, onBeforeUnmount, watch, type Ref } from 'vue'
import hljs from 'highlight.js'

const DONE_FLAG = 'hlDone'

function decorateOne(pre: HTMLPreElement): void {
  if (pre.dataset[DONE_FLAG] === '1') return
  if (pre.parentElement?.classList.contains('code-card')) {
    pre.dataset[DONE_FLAG] = '1'
    return
  }
  const code = pre.querySelector('code')
  if (!code) return

  // Re-classify so highlight.js picks the right grammar even when the
  // server only set data-language (no language-* class is required).
  const lang = pre.dataset.language || ''
  if (lang && !code.classList.contains(`language-${lang}`)) {
    code.classList.add(`language-${lang}`)
  }
  try {
    hljs.highlightElement(code as HTMLElement)
  } catch {
    // Highlight failures shouldn't break the page; the raw code is
    // already readable in mono.
  }

  const wrapper = document.createElement('div')
  wrapper.className = 'code-card'

  const toolbar = document.createElement('div')
  toolbar.className = 'code-toolbar'

  const dots = document.createElement('div')
  dots.className = 'code-dots'
  dots.innerHTML = '<span></span><span></span><span></span>'

  const label = document.createElement('div')
  label.className = 'code-lang'
  label.textContent = (lang || 'code').toUpperCase()

  const copyBtn = document.createElement('button')
  copyBtn.className = 'code-copy'
  copyBtn.type = 'button'
  copyBtn.textContent = '复制'
  copyBtn.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(code.textContent ?? '')
      copyBtn.textContent = '已复制'
    } catch {
      copyBtn.textContent = '失败'
    }
    setTimeout(() => {
      copyBtn.textContent = '复制'
    }, 1400)
  })

  toolbar.append(dots, label, copyBtn)

  pre.parentNode?.insertBefore(wrapper, pre)
  wrapper.append(toolbar, pre)
  pre.dataset[DONE_FLAG] = '1'
}

function decorateAll(root: HTMLElement): void {
  const blocks = root.querySelectorAll<HTMLPreElement>('pre')
  blocks.forEach(decorateOne)
}

/**
 * Run highlight + decoration on mount and whenever the root element
 * reference changes (e.g., the article body re-renders after fetching
 * a different slug).
 */
export function useEnhanceCodeBlocks(
  rootRef: Ref<HTMLElement | null | undefined>,
): void {
  async function apply(): Promise<void> {
    await nextTick()
    const root = rootRef.value
    if (!root) return
    decorateAll(root)
  }

  let stop: (() => void) | null = null
  onMounted(() => {
    void apply()
    stop = watch(rootRef, () => {
      void apply()
    })
  })
  onBeforeUnmount(() => {
    stop?.()
  })
}
