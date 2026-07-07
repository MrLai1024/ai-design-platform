import React from 'react';
import { useAppSelector } from '../store';

interface Props { onSave: () => void; onRun: () => void; onCancel: () => void; }

export function WorkflowToolbar({ onSave, onRun, onCancel }: Props) {
  const isDirty = useAppSelector(s => s.workflow.isDirty);
  const isRunning = useAppSelector(s => s.workflow.isRunning);
  const name = useAppSelector(s => s.workflow.currentWorkflow?.name || '未命名');

  return (
    <div className="flex items-center justify-between px-4 py-2 bg-white border-b border-gray-200">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold text-gray-800">{name}</h2>
        {isDirty && <span className="text-xs bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded-full">未保存</span>}
      </div>
      <div className="flex items-center gap-2">
        {!isRunning ? <>
          <button onClick={onSave} disabled={!isDirty}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed">💾 保存</button>
          <button onClick={onRun}
            className="px-5 py-2 text-sm font-medium text-white bg-green-600 hover:bg-green-700 rounded-lg">▶ 运行</button>
        </> : (
          <button onClick={onCancel}
            className="px-5 py-2 text-sm font-medium text-white bg-red-500 hover:bg-red-600 rounded-lg animate-pulse">⏹ 停止</button>
        )}
      </div>
    </div>
  );
}
