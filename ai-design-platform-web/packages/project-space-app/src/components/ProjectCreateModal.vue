<template>
  <a-modal
    :open="open"
    title="新建项目"
    ok-text="创建"
    cancel-text="取消"
    :confirm-loading="submitting"
    :get-container="getAppContainer"
    @ok="submit"
    @cancel="emit('cancel')"
  >
    <a-form ref="formRef" :model="form" layout="vertical">
      <a-form-item
        label="项目名称"
        name="name"
        :rules="[{ required: true, whitespace: true, message: '请输入项目名称', trigger: 'blur' }]"
      >
        <a-input v-model:value="form.name" placeholder="请输入项目名称" allow-clear />
      </a-form-item>
      <a-form-item
        label="项目级别"
        name="level"
        :rules="[{ required: true, message: '请选择项目级别' }]"
      >
        <a-radio-group v-model:value="form.level" name="level">
          <a-radio value="demo"> 演示级 </a-radio>
          <a-radio value="production"> 生产级 </a-radio>
        </a-radio-group>
      </a-form-item>
      <a-form-item label="项目简介" name="description">
        <a-textarea v-model:value="form.description" placeholder="项目简介(选填)" :rows="3" />
      </a-form-item>
    </a-form>
    <a-alert
      v-if="submitError"
      type="error"
      :message="submitError"
      show-icon
      class="modal-submit-error"
    />
  </a-modal>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue';
import type { FormInstance } from 'ant-design-vue';
import { createProject } from '@ai-design/shared';
import type { Project } from '@ai-design/shared';
import { getAppRoot } from '../portal-root';

/**
 * Reusable create-project modal, shared by the personal project page (no
 * teamId) and the team projects page (teamId passed in).
 */
const props = withDefaults(
  defineProps<{
    open?: boolean;
    teamId?: string | null;
  }>(),
  { open: false, teamId: null },
);

const emit = defineEmits<{
  cancel: [];
  created: [project: Project];
}>();

const formRef = ref<FormInstance>();

/**
 * qiankun scopedCSS rewrites all selectors with a `div[data-qiankun="..."]`
 * prefix, so teleported overlays (rendered to document.body) can never match
 * the rewritten rules. Render the modal inside the mounted app root instead,
 * which lives inside the qiankun wrapper (see portal-root.ts).
 */
function getAppContainer(): HTMLElement {
  return getAppRoot();
}
const submitting = ref(false);
const submitError = ref('');

const form = reactive({
  name: '',
  description: '',
  level: 'demo' as 'demo' | 'production',
});

watch(
  () => props.open,
  (open) => {
    if (open) {
      form.name = '';
      form.description = '';
      form.level = 'demo';
      submitError.value = '';
      formRef.value?.clearValidate();
    }
  },
);

async function submit(): Promise<void> {
  try {
    await formRef.value?.validate();
  } catch {
    return;
  }
  submitting.value = true;
  submitError.value = '';
  try {
    // teamId is only attached for team projects — personal projects must omit the key
    const project = await createProject({
      name: form.name.trim(),
      description: form.description.trim() || undefined,
      level: form.level,
      ...(props.teamId ? { teamId: props.teamId } : {}),
    });
    emit('created', project);
  } catch {
    submitError.value = '创建项目失败,请稍后重试';
  } finally {
    submitting.value = false;
  }
}
</script>
