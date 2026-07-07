import React from 'react';
import { useAppSelector } from '../../store';

const NODE_TYPES = [
  { type: 'llm', label: 'LLM 调用', icon: '🧠', color: 'bg-blue-50 border-blue-200 text-blue-700' },
  { type: 'router', label: '条件路由', icon: '🔀', color: 'bg-amber-50 border-amber-200 text-amber-700' },
  { type: 'human_confirm', label: '人工确认', icon: '✋', color: 'bg-purple-50 border-purple-200 text-purple-700' },
  { type: 'code', label: '代码执行', icon: '⚡', color: 'bg-green-50 border-green-200 text-green-700' },
];

export function NodePalette() {
  const workflows = useAppSelector(s => s.workflow.workflows);

  const onDragStart = (event: React.DragEvent, nodeType: string) => {
    event.dataTransfer.setData('application/workflow-node-type', nodeType);
    event.dataTransfer.effectAllowed = 'move';
  };

  return (
    <div className="w-52 bg-gray-50 border-r border-gray-200 p-3 flex flex-col h-full overflow-y-auto">
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">节点类型</h3>
      <div className="space-y-2">
        {NODE_TYPES.map(nt => (
          <div key={nt.type} draggable onDragStart={e => onDragStart(e, nt.type)}
            className={`flex items-center gap-2 px-3 py-2.5 rounded-lg border cursor-grab active:cursor-grabbing transition-all hover:shadow-md ${nt.color}`}>
            <span className="text-lg">{nt.icon}</span>
            <span className="text-sm font-medium">{nt.label}</span>
          </div>
        ))}
      </div>
      <div className="mt-6 pt-4 border-t border-gray-200">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">工作流列表</h3>
        {workflows.length === 0 ? (
          <p className="text-xs text-gray-400">暂无工作流</p>
        ) : (
          <div className="space-y-1">
            {workflows.map(wf => (
              <div key={wf.id} className="text-sm text-gray-600 px-2 py-1 rounded hover:bg-gray-100 cursor-pointer truncate" title={wf.name}>{wf.name}</div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
