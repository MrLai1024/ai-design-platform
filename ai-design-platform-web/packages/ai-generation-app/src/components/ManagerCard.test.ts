// src/components/ManagerCard.test.ts
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ManagerCard from './ManagerCard.vue'
import type { ManagerCardMeta } from '@/types/generation'

function mountCard(meta: ManagerCardMeta) {
  return mount(ManagerCard, {
    props: { meta },
  })
}

describe('ManagerCard', () => {
  it('renders summary_card with title and content', () => {
    const wrapper = mountCard({
      card: 'summary_card',
      title: '需求分析阶段产出总结',
      content: 'PRD 前 200 字…',
    })
    expect(wrapper.text()).toContain('阶段总结')
    expect(wrapper.text()).toContain('需求分析阶段产出总结')
    expect(wrapper.text()).toContain('PRD 前 200 字…')
  })

  it('renders verdict_card pass state', () => {
    const wrapper = mountCard({
      card: 'verdict_card',
      title: 'Manager 把关裁决 · 需求分析',
      content: 'Manager 把关通过 · 需求分析',
      data: { decision: 'pass', passed: true, reason: '' },
    })
    expect(wrapper.text()).toContain('✓ 通过')
  })

  it('renders verdict_card fail state', () => {
    const wrapper = mountCard({
      card: 'verdict_card',
      content: 'Manager 把关未通过 · 功能实现',
      data: { decision: 'redo', passed: false, reason: '编译未通过（2 处错误）' },
    })
    expect(wrapper.text()).toContain('✗ 未通过')
  })

  it('renders diagnosis_card with suggestion and options', () => {
    const wrapper = mountCard({
      card: 'diagnosis_card',
      title: 'Manager 诊断 · 功能实现',
      content: '编译未通过（2 处错误）',
      options: ['继续自主', '转人工'],
      data: { suggestion: '将返工重做该阶段。' },
    })
    expect(wrapper.text()).toContain('问题诊断')
    expect(wrapper.text()).toContain('建议：将返工重做该阶段。')
    const buttons = wrapper.findAll('button')
    expect(buttons.map((b) => b.text())).toEqual(['继续自主', '转人工'])
  })

  it('renders coverage_matrix entries', () => {
    const wrapper = mountCard({
      card: 'coverage_matrix',
      title: 'E2E 覆盖矩阵 · E2E 验证',
      data: { matrix: { 'TC-001': 'pass', 'TC-002': 'fail' } },
    })
    expect(wrapper.text()).toContain('覆盖矩阵')
    expect(wrapper.text()).toContain('TC-001')
    expect(wrapper.text()).toContain('pass')
  })

  it('renders question_card options and emits option-click', async () => {
    const wrapper = mountCard({
      card: 'question_card',
      title: '提问',
      content: '你需要哪些功能模块？',
      options: ['用户管理', '订单管理'],
    })
    expect(wrapper.text()).toContain('你需要哪些功能模块？')
    const buttons = wrapper.findAll('button')
    await buttons[1]!.trigger('click')
    expect(wrapper.emitted('option-click')![0]).toEqual(['订单管理'])
  })

  it('does not render option buttons when options are empty', () => {
    const wrapper = mountCard({
      card: 'confirm_card',
      content: '确认继续？',
      options: [],
    })
    expect(wrapper.findAll('button').length).toBe(0)
  })

  it('renders feedback_card collapsed with summary and expands the disposition', async () => {
    // 10.2: 反馈处置结果卡片 — 默认折叠 (反馈摘要 + 处置动作 + 结果),
    // 点击展开处置过程 (分类、重派任务、验证结果)。
    const wrapper = mountCard({
      card: 'feedback_card',
      title: '反馈处置 · 功能实现',
      content: '反馈摘要：缺少订单列表组件\n处置动作：重派功能实现任务（携带反馈）\n结果：已重派功能实现任务',
      data: {
        node: 'code',
        feedback: '缺少订单列表组件',
        category: 'omission',
        category_label: '遗漏',
        reason: '需求已声明但未生成',
        action: '重派功能实现任务（携带反馈）',
        result: 'dispatched',
      },
    })
    // 折叠行: 反馈摘要 + 分类 + 结果 (展开内容不可见)
    expect(wrapper.text()).toContain('反馈处置')
    expect(wrapper.text()).toContain('缺少订单列表组件')
    expect(wrapper.text()).toContain('遗漏 · 已重派')
    expect(wrapper.text()).not.toContain('需求已声明但未生成')

    // 点击展开 → 处置过程可见
    await wrapper.find('[data-testid="feedback-card-toggle"]').trigger('click')
    expect(wrapper.text()).toContain('需求已声明但未生成')
    expect(wrapper.text()).toContain('处置动作：重派功能实现任务（携带反馈）')
    expect(wrapper.text()).toContain('验证结果')
  })

  it('feedback_card shows awaiting-confirm result label', () => {
    const wrapper = mountCard({
      card: 'feedback_card',
      title: '反馈处置 · 功能实现',
      data: {
        node: 'code',
        feedback: '新增导出 Excel 功能',
        category: 'scope_change',
        category_label: '范围变更',
        result: 'awaiting_confirm',
      },
    })
    expect(wrapper.text()).toContain('范围变更 · 待确认')
  })
})
