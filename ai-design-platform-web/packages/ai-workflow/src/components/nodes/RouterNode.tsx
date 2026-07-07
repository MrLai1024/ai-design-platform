import React from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import { BaseNode } from './BaseNode';

export function RouterNode(props: NodeProps) {
  const data = props.data as any;
  const branches = data.config?.branches || [];
  return (
    <div className="relative">
      <BaseNode {...props} />
      {branches.length > 0 ? branches.map((b: any, i: number) => (
        <Handle
          key={b.label || i}
          type="source"
          position={Position.Bottom}
          id={b.label || `branch-${i}`}
          style={{ left: `${((i + 1) / (branches.length + 1)) * 100}%` }}
          className="!w-3 !h-3 !bg-amber-400 !border-2 !border-white"
          title={b.label}
        />
      )) : (
        <Handle type="source" position={Position.Bottom} className="!w-3 !h-3 !bg-amber-400 !border-2 !border-white" />
      )}
    </div>
  );
}
