<template>
  <div class="h-full">
    <PRDGeneratorView
      @edit="onEditPRD"
      @next="onGoNextStage"
      @export="onExportPRD"
    />
  </div>
</template>

<script setup lang="ts">
import { useGenerationStore } from '@/stores/generation'
import PRDGeneratorView from './PRDGeneratorView.vue'

const store = useGenerationStore()

function onEditPRD() {}
function onGoNextStage() {}
function onExportPRD() {
  const blob = new Blob([store.prdStreamingContent], { type: 'text/markdown' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = 'PRD.md'
  a.click()
  URL.revokeObjectURL(a.href)
}
</script>
