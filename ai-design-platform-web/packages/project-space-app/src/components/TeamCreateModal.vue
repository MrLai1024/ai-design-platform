<template>
  <a-modal
    :open="open"
    title="创建团队"
    ok-text="创建"
    cancel-text="取消"
    :confirm-loading="submitting"
    :get-container="getAppContainer"
    @ok="submit"
    @cancel="emit('cancel')"
  >
    <a-form
      ref="formRef"
      :model="form"
      layout="vertical"
    >
      <a-form-item
        label="团队名称"
        name="name"
        :rules="[{ required: true, whitespace: true, message: '请输入团队名称', trigger: 'blur' }]"
      >
        <a-input
          v-model:value="form.name"
          placeholder="请输入团队名称"
          allow-clear
        />
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
import { createTeam } from '@ai-design/shared';
import type { Team } from '@ai-design/shared';
import { getAppRoot } from '../portal-root';

const props = withDefaults(defineProps<{ open?: boolean }>(), { open: false });

const emit = defineEmits<{
  cancel: [];
  created: [team: Team];
}>();

const formRef = ref<FormInstance>();

// Keep the modal inside the qiankun wrapper (see portal-root.ts) so qiankun's
// scopedCSS-prefixed rules still match teleported overlay content.
function getAppContainer(): HTMLElement {
  return getAppRoot();
}
const submitting = ref(false);
const submitError = ref('');

const form = reactive({ name: '' });

watch(
  () => props.open,
  (open) => {
    if (open) {
      form.name = '';
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
    const team = await createTeam({ name: form.name.trim() });
    emit('created', team);
  } catch {
    submitError.value = '创建团队失败,请稍后重试';
  } finally {
    submitting.value = false;
  }
}
</script>
