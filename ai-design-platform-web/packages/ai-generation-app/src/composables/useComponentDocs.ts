// src/composables/useComponentDocs.ts
import { ref } from 'vue'
import type { ComponentLibrary, LibraryConfig } from '@/types/generation'

const LIBRARY_CONFIGS: Record<ComponentLibrary, LibraryConfig> = {
  tailwind: {
    key: 'tailwind',
    label: 'Tailwind CSS',
    cdnUrls: ['https://cdn.tailwindcss.com'],
    docInjection: `样式使用 Tailwind CSS 工具类，直接写在 class 属性中。例如 class="flex items-center gap-4 p-6 bg-white rounded-lg shadow-md"。
不要使用 <style scoped> 写自定义 CSS，优先使用 Tailwind 工具类。`,
  },
  antd: {
    key: 'antd',
    label: 'Ant Design Vue',
    cdnUrls: [
      'https://unpkg.com/ant-design-vue@4/dist/antd.min.js',
      'https://unpkg.com/ant-design-vue@4/dist/reset.css',
    ],
    docInjection: `你可以使用 Ant Design Vue 4.x 组件库。可用组件包括：
- 通用: Button, Icon, Typography (Title, Text, Paragraph)
- 布局: Grid (Row, Col), Layout (Header, Footer, Sider, Content), Space, Divider
- 导航: Menu, Breadcrumb, Pagination, Steps, Tabs, Dropdown
- 数据录入: Form, FormItem, Input, InputNumber, Textarea, Select, Option, Checkbox, Radio, Switch, DatePicker, TimePicker, Upload, Rate, Slider
- 数据展示: Table, Tag, Card, List, Tree, Tooltip, Popover, Badge, Avatar, Calendar, Carousel, Collapse, Descriptions, Empty, Image, Statistic, Timeline
- 反馈: Modal, Drawer, Message, Notification, Popconfirm, Progress, Result, Skeleton, Spin, Alert
- 其他: ConfigProvider, Affix, Anchor, BackTop, Watermark

使用示例：
\`\`\`vue
<a-button type="primary" @click="handleClick">提交</a-button>
<a-table :columns="columns" :data-source="data" bordered />
<a-modal v-model:open="visible" title="标题">内容</a-modal>
\`\`\`

注意: 组件名前缀为 a-，如 <a-button>、<a-table>、<a-modal>。`,
  },
  element: {
    key: 'element',
    label: 'Element Plus',
    cdnUrls: [
      'https://unpkg.com/element-plus/dist/index.full.min.js',
      'https://unpkg.com/element-plus/dist/index.css',
    ],
    docInjection: `你可以使用 Element Plus 组件库。组件名前缀为 el-，如 <el-button>、<el-table>、<el-dialog>。
常用组件: Button, Table, Form, Dialog, Input, Select, DatePicker, Upload, Menu, Tabs, Card, Tag, Pagination, Popover, Tooltip, Drawer, Message, Notification, Tree, Cascader, Transfer 等。`,
  },
  echarts: {
    key: 'echarts',
    label: 'ECharts',
    cdnUrls: ['https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js'],
    docInjection: `你可以使用 ECharts 5.x 图表库。需要在 onMounted 中初始化图表：

\`\`\`vue
<script setup>
import { ref, onMounted } from 'vue'
const chartRef = ref(null)
onMounted(() => {
  const chart = echarts.init(chartRef.value)
  chart.setOption({
    title: { text: '图表标题' },
    xAxis: { data: ['A', 'B', 'C'] },
    yAxis: {},
    series: [{ data: [1, 2, 3], type: 'bar' }]
  })
})
</script>
<template>
  <div ref="chartRef" style="width:100%;height:400px"></div>
</template>
\`\`\`

注意: echarts 是全局变量，无需 import，直接使用 echarts.init()。同时需设置容器宽高。`,
  },
}

export function useComponentDocs() {
  const currentLib = ref<ComponentLibrary>('tailwind')

  function setLibrary(lib: ComponentLibrary): void {
    currentLib.value = lib
  }

  function getConfig(): LibraryConfig {
    return LIBRARY_CONFIGS[currentLib.value]
  }

  function getSystemPrompt(): string {
    const config = getConfig()
    const base = `你是一个专业的 Vue 3 单文件组件（SFC）生成助手。

你必须只生成 Vue SFC 代码，使用 <script setup lang="ts"> 语法。

输出格式要求：
- 如果需要生成多个文件，用 "## FileName.vue" 作为每个文件的标题
- 每个文件的代码放在 \`\`\`vue 代码块中
- 只输出代码块和文件标题，不要添加额外的解释说明
- 每个组件必须是完整可运行的 SFC（包含 template, script setup, style）
- 在 script 中 import 其他组件时，文件名必须与你输出的 ## 标题一致`

    const format = `

重要：你的回复必须只包含代码块和文件标题。不要输出任何解释性文字。`

    return [base, config.docInjection, format].join('\n\n')
  }

  return { currentLib, setLibrary, getConfig, getSystemPrompt, libraryConfigs: LIBRARY_CONFIGS }
}
