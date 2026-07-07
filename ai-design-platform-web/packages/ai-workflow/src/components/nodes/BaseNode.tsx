import React from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import type { WorkflowNodeData } from '../../types/workflow';

const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-gray-300',
  running: 'bg-blue-500 animate-pulse',
  done: 'bg-green-500',
  error: 'bg-red-500',
};

const TYPE_ICONS: Record<string, string> = {
  llm: '🧠',
  router: '🔀',
  human_confirm: '✋',
  code: '⚡',
};

export function BaseNode({ data, selected }: NodeProps) {
  const nodeData = data as unknown as WorkflowNodeData;
  const statusColor = STATUS_COLORS[nodeData.status] || STATUS_COLORS.pending;
  const icon = TYPE_ICONS[nodeData.nodeType] || '📦';

  return (
    <div className={`
      relative min-w-[180px] bg-white rounded-xl border-2 shadow-sm transition-all duration-200
      ${selected ? 'border-blue-500 shadow-blue-100 shadow-md' : 'border-gray-200'}
      ${nodeData.status === 'running' ? 'border-blue-400 shadow-blue-100 shadow-lg' : ''}
      ${nodeData.status === 'error' ? 'border-red-400 shadow-red-100' : ''}
    `}>
      <div className={`absolute -top-1.5 -right-1.5 w-3 h-3 rounded-full border-2 border-white ${statusColor}`} />
      <Handle type="target" position={Position.Top} className="!w-3 !h-3 !bg-gray-400 !border-2 !border-white" />
      <div className="px-4 py-3">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-lg">{icon}</span>
          <span className="font-semibold text-sm text-gray-800 truncate">{nodeData.label}</span>
        </div>
        <div className="text-xs text-gray-400 font-mono">{nodeData.nodeType}</div>
        {nodeData.summary && (
          <div className="mt-2 text-xs text-gray-500 line-clamp-2 border-t pt-2 border-gray-100">{nodeData.summary}</div>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} className="!w-3 !h-3 !bg-gray-400 !border-2 !border-white" />
    </div>
  );
}
