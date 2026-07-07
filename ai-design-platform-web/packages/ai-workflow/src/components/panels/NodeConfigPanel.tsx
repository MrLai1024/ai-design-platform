import React from 'react';
import { useAppSelector, useAppDispatch } from '../../store';
import { updateNode } from '../../store/slices/workflowSlice';

export function NodeConfigPanel() {
  const dispatch = useAppDispatch();
  const workflow = useAppSelector(s => s.workflow.currentWorkflow);
  const selectedId = useAppSelector(s => s.workflow.selectedNodeId);
  const isRunning = useAppSelector(s => s.workflow.isRunning);
  const selectedNode = workflow?.nodes.find(n => n.id === selectedId);

  if (!selectedNode) {
    return <div className="w-80 bg-gray-50 border-l border-gray-200 p-4">
      <p className="text-sm text-gray-400 text-center mt-8">点击画布上的节点以编辑配置</p>
    </div>;
  }

  const handleConfigChange = (key: string, value: unknown) => {
    dispatch(updateNode({ id: selectedNode.id, changes: { config: { ...selectedNode.config, [key]: value } } }));
  };

  return (
    <div className="w-80 bg-gray-50 border-l border-gray-200 p-4 overflow-y-auto h-full">
      <h3 className="text-sm font-semibold text-gray-700 mb-4">{selectedNode.type.toUpperCase()} 配置</h3>

      <ConfigInput label="名称" value={selectedNode.label}
        onChange={v => dispatch(updateNode({ id: selectedNode.id, changes: { label: v } }))} disabled={isRunning} />

      {selectedNode.type === 'llm' && <>
        <ConfigInput label="模型" value={selectedNode.config.model as string || 'glm-5.2'} onChange={v => handleConfigChange('model', v)} disabled={isRunning} />
        <ConfigInput label="输出变量" value={selectedNode.config.output_key as string || 'output'} onChange={v => handleConfigChange('output_key', v)} disabled={isRunning} />
        <ConfigTextarea label="System Prompt" value={selectedNode.config.system_prompt as string || ''} onChange={v => handleConfigChange('system_prompt', v)} disabled={isRunning} />
        <ConfigTextarea label="User Prompt" value={selectedNode.config.user_prompt as string || ''} onChange={v => handleConfigChange('user_prompt', v)} disabled={isRunning} hint="使用 {state.xxx} 引用上游输出" />
      </>}

      {selectedNode.type === 'code' && <>
        <ConfigInput label="语言" value={selectedNode.config.language as string || 'python'} onChange={v => handleConfigChange('language', v)} disabled={isRunning} />
        <ConfigInput label="输出变量" value={selectedNode.config.output_key as string || 'code_output'} onChange={v => handleConfigChange('output_key', v)} disabled={isRunning} />
        <ConfigTextarea label="代码" value={selectedNode.config.code as string || ''} onChange={v => handleConfigChange('code', v)} disabled={isRunning} rows={10} />
        <ConfigInput label="超时(秒)" value={String(selectedNode.config.timeout || 30)} onChange={v => handleConfigChange('timeout', Number(v))} disabled={isRunning} type="number" />
      </>}

      {selectedNode.type === 'human_confirm' && <>
        <ConfigInput label="提示消息" value={selectedNode.config.message as string || ''} onChange={v => handleConfigChange('message', v)} disabled={isRunning} />
        <ConfigInput label="超时(秒)" value={String(selectedNode.config.timeout || 300)} onChange={v => handleConfigChange('timeout', Number(v))} disabled={isRunning} type="number" />
      </>}

      {selectedNode.type === 'router' && (
        <div className="text-sm text-gray-500 mt-2">
          <p>条件分支在连线上配置。将路由节点连接到目标节点后，在连线上设置条件。</p>
        </div>
      )}

      <div className="mt-6 pt-4 border-t border-gray-200 text-xs text-gray-400 font-mono">ID: {selectedNode.id}</div>
    </div>
  );
}

function ConfigInput({ label, value, onChange, disabled, type = 'text' }:
  { label: string; value: string; onChange: (v: string) => void; disabled: boolean; type?: string }) {
  return <div className="mb-3">
    <label className="block text-xs font-medium text-gray-500 mb-1">{label}</label>
    <input type={type} value={value} onChange={e => onChange(e.target.value)} disabled={disabled}
      className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:bg-gray-100" />
  </div>;
}

function ConfigTextarea({ label, value, onChange, disabled, rows = 4, hint }:
  { label: string; value: string; onChange: (v: string) => void; disabled: boolean; rows?: number; hint?: string }) {
  return <div className="mb-3">
    <label className="block text-xs font-medium text-gray-500 mb-1">{label}</label>
    <textarea value={value} onChange={e => onChange(e.target.value)} disabled={disabled} rows={rows}
      className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:bg-gray-100 font-mono resize-y" />
    {hint && <p className="text-xs text-gray-400 mt-1">{hint}</p>}
  </div>;
}
