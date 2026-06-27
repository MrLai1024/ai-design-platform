// src/composables/useMultiCompiler.ts
import { watch, ref } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { compileSFC } from '@/utils/compileSFC'

export function useMultiCompiler() {
  const store = useGenerationStore()
  const isCompiling = ref(false)
  let debounceTimer: ReturnType<typeof setTimeout> | null = null
  let compileGeneration = 0
  const DEBOUNCE_MS = 300

  // 监听 dirty 文件变化，触发 debounced 编译
  watch(
    () => store.dirtyFiles,
    () => {
      if (store.dirtyFiles.size === 0) return
      scheduleCompile()
    },
    { deep: true },
  )

  // 监听当前文件手动编辑（用户编辑后触发）
  watch(
    () => store.activeFileEntry?.content,
    () => {
      const entry = store.activeFileEntry
      if (entry && entry.source === 'user' && entry.isDirty) {
        scheduleCompile()
      }
    },
  )

  function scheduleCompile(): void {
    if (debounceTimer) clearTimeout(debounceTimer)
    debounceTimer = setTimeout(() => doCompile(), DEBOUNCE_MS)
  }

  async function doCompile(): Promise<void> {
    const gen = ++compileGeneration
    store.compileError = null
    isCompiling.value = true

    // 收集所有需要编译的文件
    const filesToCompile = Array.from(store.dirtyFiles)
    // 也加入当前活动文件（如果有的话），确保预览完整
    if (store.activeFile && !store.dirtyFiles.has(store.activeFile)) {
      filesToCompile.push(store.activeFile)
    }

    // 至少编译活动文件
    if (filesToCompile.length === 0 && store.activeFileEntry) {
      filesToCompile.push(store.activeFileEntry.filename)
    }

    const results: Array<{ filename: string; code: string | null; css: string }> = []

    for (const filename of filesToCompile) {
      const file = store.files.get(filename)
      if (!file || !file.content.trim()) continue

      try {
        const compiled = await compileSFC(file.content, { filename })
        if (gen !== compileGeneration) return // 过期编译，丢弃

        if (compiled.code) {
          results.push({ filename, code: compiled.code, css: compiled.css })
          store.markFileClean(filename)
        }
      } catch {
        if (gen !== compileGeneration) return
        // 编译失败静默处理——保持上次成功的结果
      }
    }

    if (gen !== compileGeneration) return
    isCompiling.value = false

    // 合并编译结果
    if (results.length === 0) {
      store.setCompiledOutput('')
      return
    }

    // 对于多文件，将活动文件作为主组件
    const activeResult = results.find((r) => r.filename === store.activeFile) || results[0]!
    const otherResults = results.filter((r) => r !== activeResult)

    const mergedCSS = results.map((r) => r.css).filter(Boolean).join('\n')

    // 生成可执行的 register 代码：主组件 + 子组件注册
    let finalCode = ''
    if (otherResults.length > 0) {
      finalCode += `// 注册子组件\n`
      for (const r of otherResults) {
        finalCode += `(function() { ${r.code} })();\n`
      }
    }
    finalCode += `\n// 主组件\n${activeResult.code || '// no compiled code'}`
    finalCode += '\n// CSS\n__CSS__ = ' + JSON.stringify(mergedCSS) + ';'

    store.setCompiledOutput(finalCode)
  }

  function compileNow(): void {
    if (debounceTimer) clearTimeout(debounceTimer)
    doCompile()
  }

  return { isCompiling, compileNow }
}
