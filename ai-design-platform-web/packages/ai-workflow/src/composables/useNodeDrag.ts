import { useCallback } from 'react';
import { useAppDispatch } from '../store';
import { addNode } from '../store/slices/workflowSlice';
import type { NodeDef } from '../types/workflow';

const NODE_TYPE_TEMPLATES: Record<string, { type: string; config: Record<string, unknown> }> = {
  llm: { type: 'llm', config: { model: 'glm-5.2', system_prompt: '', user_prompt: '', temperature: 0.7, max_tokens: 4096, output_key: 'output' } },
  router: { type: 'router', config: { branches: [{ label: 'pass', condition: 'state.ok == True' }, { label: 'fail', condition: 'default' }] } },
  human_confirm: { type: 'human_confirm', config: { message: '请审核并确认', fields: [{ key: 'approved', label: '已通过', type: 'boolean' }], timeout: 300 } },
  code: { type: 'code', config: { language: 'python', code: '# Access state via `state` dict\nresult = {"processed": state.get("input")}\n', timeout: 30, output_key: 'code_output' } },
};

export function useNodeDrag() {
  const dispatch = useAppDispatch();

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  const onDrop = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    const nodeType = event.dataTransfer.getData('application/workflow-node-type');
    if (!nodeType || !NODE_TYPE_TEMPLATES[nodeType]) return;
    const template = NODE_TYPE_TEMPLATES[nodeType];
    const newNode: NodeDef = {
      id: `node-${Date.now()}`,
      type: template.type,
      label: `${template.type} node`,
      position: { x: event.clientX - 300, y: event.clientY - 100 },
      config: { ...template.config },
    };
    dispatch(addNode(newNode));
  }, [dispatch]);

  return { onDragOver, onDrop };
}
