import React, { useCallback, useMemo, useRef, useEffect } from 'react';
import { ReactFlow, Background, Controls, MiniMap, useNodesState, useEdgesState, addEdge as rfAddEdge, type Connection, type Node, type Edge, BackgroundVariant } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { LLMNode } from './nodes/LLMNode';
import { RouterNode } from './nodes/RouterNode';
import { HumanNode } from './nodes/HumanNode';
import { CodeNode } from './nodes/CodeNode';
import { WorkflowEdge } from './edges/WorkflowEdge';
import { useAppSelector, useAppDispatch } from '../store';
import { addNode, addEdge, removeEdge, setSelectedNode, updateNode } from '../store/slices/workflowSlice';
import type { WorkflowNodeData, WorkflowEdgeData, NodeDef } from '../types/workflow';

const nodeTypes = { llm: LLMNode, router: RouterNode, human_confirm: HumanNode, code: CodeNode };
const edgeTypes = { workflow: WorkflowEdge };

const NODE_TYPE_TEMPLATES: Record<string, { type: string; config: Record<string, unknown> }> = {
  llm: { type: 'llm', config: { model: 'deepseek-v4-pro', system_prompt: '', user_prompt: '', temperature: 0.7, max_tokens: 4096, output_key: 'output' } },
  router: { type: 'router', config: { branches: [{ label: 'pass', condition: 'state.ok == True' }, { label: 'fail', condition: 'default' }] } },
  human_confirm: { type: 'human_confirm', config: { message: '请审核并确认', fields: [{ key: 'approved', label: '已通过', type: 'boolean' }], timeout: 300 } },
  code: { type: 'code', config: { language: 'python', code: '# Access state via `state` dict\nresult = {"processed": state.get("input")}\n', timeout: 30, output_key: 'code_output' } },
};

export function WorkflowCanvas() {
  const dispatch = useAppDispatch();
  const workflow = useAppSelector(s => s.workflow.currentWorkflow);
  const nodeStatuses = useAppSelector(s => s.workflow.nodeStatuses);
  const isRunning = useAppSelector(s => s.workflow.isRunning);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const rfInstance = useRef<any>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);

  const initialNodes: Node<WorkflowNodeData>[] = useMemo(() =>
    (workflow?.nodes || []).map(n => ({
      id: n.id, type: n.type, position: n.position,
      data: { label: n.label, nodeType: n.type, config: n.config, status: nodeStatuses[n.id] || 'pending' },
    })), [workflow?.nodes, nodeStatuses]);

  const initialEdges: Edge<WorkflowEdgeData>[] = useMemo(() =>
    (workflow?.edges || []).map(e => ({
      id: e.id, source: e.source, target: e.target, type: 'workflow',
      data: { condition: e.condition },
    })), [workflow?.edges]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  // Sync React Flow from Redux
  const nodesJson = JSON.stringify(workflow?.nodes);
  const edgesJson = JSON.stringify(workflow?.edges);
  useEffect(() => {
    setNodes(initialNodes);
    setEdges(initialEdges);
  }, [nodesJson, edgesJson, nodeStatuses]);

  const onConnect = useCallback((connection: Connection) => {
    if (!connection.source || !connection.target || isRunning) return;
    const edgeId = `e-${connection.source}-${connection.target}-${Date.now()}`;
    dispatch(addEdge({ id: edgeId, source: connection.source, target: connection.target }));
    setEdges(eds => rfAddEdge({ ...connection, id: edgeId, type: 'workflow' }, eds));
  }, [dispatch, setEdges, isRunning]);

  const onNodeClick = useCallback((_e: React.MouseEvent, node: Node) => {
    dispatch(setSelectedNode(node.id));
  }, [dispatch]);

  const onNodeDragStop = useCallback((_e: MouseEvent | TouchEvent, node: Node) => {
    dispatch(updateNode({ id: node.id, changes: { position: node.position } }));
  }, [dispatch]);

  // Drag-and-drop: native DOM listeners on the wrapper div.
  // We use native events because ReactFlow's pane may intercept React synthetic events.
  // We use a stable callback ref so the handler always reads the latest rfInstance.
  const dropHandlerRef = useRef<(e: DragEvent) => void>(() => {});

  dropHandlerRef.current = (e: DragEvent) => {
    e.preventDefault();
    const nodeType = e.dataTransfer?.getData('application/workflow-node-type');
    console.log('[WorkflowCanvas] drop:', nodeType);
    if (!nodeType || !NODE_TYPE_TEMPLATES[nodeType]) return;

    const template = NODE_TYPE_TEMPLATES[nodeType];
    const position = rfInstance.current
      ? rfInstance.current.screenToFlowPosition({ x: e.clientX, y: e.clientY })
      : { x: e.clientX, y: e.clientY };

    console.log('[WorkflowCanvas] position:', position);

    const newNode: NodeDef = {
      id: `node-${Date.now()}`,
      type: template.type,
      label: template.type,
      position,
      config: { ...template.config },
    };
    dispatch(addNode(newNode));
    console.log('[WorkflowCanvas] dispatched addNode:', newNode.id);
  };

  useEffect(() => {
    const el = wrapperRef.current;
    if (!el) return;

    const onDragOver = (e: DragEvent) => {
      e.preventDefault();
    };

    const onDrop = (e: DragEvent) => {
      dropHandlerRef.current(e);
    };

    el.addEventListener('dragover', onDragOver);
    el.addEventListener('drop', onDrop);
    console.log('[WorkflowCanvas] attached native drag listeners');
    return () => {
      el.removeEventListener('dragover', onDragOver);
      el.removeEventListener('drop', onDrop);
    };
  }, []);

  return (
    <div ref={wrapperRef} style={{ flex: 1, width: '100%', height: '100%', position: 'relative' }}>
      <ReactFlow
        nodes={nodes} edges={edges}
        onInit={(instance) => { rfInstance.current = instance; }}
        onNodesChange={isRunning ? undefined : onNodesChange}
        onEdgesChange={isRunning ? undefined : onEdgesChange}
        onConnect={isRunning ? undefined : onConnect}
        onNodeClick={onNodeClick}
        onNodeDragStop={onNodeDragStop}
        nodeTypes={nodeTypes} edgeTypes={edgeTypes}
        fitView deleteKeyCode={isRunning ? null : ['Backspace', 'Delete']}
        onEdgesDelete={deleted => deleted.forEach(e => dispatch(removeEdge(e.id)))}
        style={{ width: '100%', height: '100%' }}
        className="bg-gray-50"
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
        <Controls />
        <MiniMap nodeColor={n => {
          const d = n.data as Record<string, unknown>;
          const t = d?.nodeType as string | undefined;
          return t === 'llm' ? '#3b82f6' : t === 'router' ? '#f59e0b' : t === 'human_confirm' ? '#8b5cf6' : t === 'code' ? '#10b981' : '#6b7280';
        }} />
      </ReactFlow>
    </div>
  );
}
