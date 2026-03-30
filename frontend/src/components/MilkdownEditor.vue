<template>
  <div class="milkdown-host">
    <Milkdown />
  </div>
</template>

<script setup>
import { onMounted, watch } from 'vue'
import { Milkdown, useEditor } from '@milkdown/vue'
import { Editor, rootCtx, defaultValueCtx } from '@milkdown/kit/core'
import { commonmark } from '@milkdown/kit/preset/commonmark'
import { nord } from '@milkdown/theme-nord'

const props = defineProps({
  modelValue: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['update:modelValue'])

let editorInstance = null

useEditor((root) => {
  editorInstance = Editor.make()
    .config(nord)
    .config((ctx) => {
      ctx.set(rootCtx, root)
      ctx.set(defaultValueCtx, props.modelValue || '# 开始写作\n\n在这里输入 Markdown 内容。')
    })
    .use(commonmark)

  return editorInstance
})

watch(
  () => props.modelValue,
  (value) => {
    // 暂不做反向覆盖，避免编辑中光标跳动；当前主用场景是初始化+编辑。
  }
)

onMounted(() => {
  const tryBind = () => {
    const editable = document.querySelector('.milkdown .ProseMirror')
    if (!editable) {
      setTimeout(tryBind, 120)
      return
    }
    editable.addEventListener('input', () => {
      emit('update:modelValue', editable.innerText)
    })
  }
  tryBind()
})
</script>
