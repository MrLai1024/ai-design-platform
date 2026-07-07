import React from 'react';
import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from '@xyflow/react';

export function WorkflowEdge({
  id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, selected,
}: EdgeProps) {
  const [edgePath, labelX, labelY] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  const condition = (data as any)?.condition;
  return (
    <>
      <BaseEdge id={id} path={edgePath} className={selected ? '!stroke-blue-500' : '!stroke-gray-400'}
        style={{ strokeWidth: selected ? 2 : 1.5 }} />
      {condition && (
        <EdgeLabelRenderer>
          <div className="absolute px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 text-xs font-medium border border-amber-200"
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`, pointerEvents: 'all' }}>
            {condition}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
