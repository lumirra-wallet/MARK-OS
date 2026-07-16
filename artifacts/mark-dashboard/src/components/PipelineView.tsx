/**
 * PipelineView — React Flow live execution graph.
 *
 * Each worker is a node. Edges connect them in sequence.
 * Nodes glow / animate based on live WorkerState from the store.
 */
import React, { useCallback, useEffect, useMemo } from 'react';
import '@xyflow/react/dist/style.css';
import {
  ReactFlow, Background, Controls, MiniMap,
  Node, Edge, Position, Handle,
  useNodesState, useEdgesState,
  BackgroundVariant,
} from '@xyflow/react';
import { motion } from 'framer-motion';
import {
  Sparkles, CircleDashed, Code2, TestTube2,
  BadgeCheck, Eye, CheckCircle2, XCircle, Loader2,
} from 'lucide-react';
import { useMarkStore, WorkerState } from '@/store/markStore';

// ── Icons ─────────────────────────────────────────────────────────────────────

const ICONS: Record<string, React.ComponentType<any>> = {
  Research: Sparkles,
  Planning: CircleDashed,
  Coding:   Code2,
  Testing:  TestTube2,
  Quality:  BadgeCheck,
  Review:   Eye,
};

// ── Custom node component ─────────────────────────────────────────────────────

function WorkerNode({ data }: { data: WorkerState & { isFirst?: boolean; isLast?: boolean } }) {
  const Icon = ICONS[data.name] ?? CircleDashed;
  const isRunning = data.status === 'running';
  const isDone    = data.status === 'success';
  const isFailed  = data.status === 'failed';
  const isIdle    = data.status === 'idle';

  const borderColor = isRunning ? '#8B5CF6'
    : isDone    ? '#10B981'
    : isFailed  ? '#EF4444'
    : '#374151';

  const bgColor = isRunning ? 'rgba(139,92,246,0.12)'
    : isDone    ? 'rgba(16,185,129,0.10)'
    : isFailed  ? 'rgba(239,68,68,0.10)'
    : 'rgba(17,24,39,0.6)';

  const textColor = isRunning ? '#A78BFA'
    : isDone    ? '#34D399'
    : isFailed  ? '#F87171'
    : '#6B7280';

  return (
    <div
      className="relative"
      style={{ width: 140, minHeight: 90 }}
    >
      {/* Glow ring when running */}
      {isRunning && (
        <motion.div
          className="absolute inset-0 rounded-xl"
          style={{ border: `2px solid ${borderColor}`, boxShadow: `0 0 20px ${borderColor}55` }}
          animate={{ opacity: [0.5, 1, 0.5] }}
          transition={{ duration: 1.5, repeat: Infinity }}
        />
      )}

      <div
        className="rounded-xl border p-4 flex flex-col items-center gap-2 text-center"
        style={{ background: bgColor, borderColor, borderWidth: isRunning ? 2 : 1 }}
      >
        {/* Status icon */}
        <div className="flex items-center justify-center w-8 h-8 rounded-full"
             style={{ background: `${borderColor}22` }}>
          {isRunning ? (
            <Loader2 className="w-4 h-4 animate-spin" style={{ color: textColor }} />
          ) : isDone ? (
            <CheckCircle2 className="w-4 h-4" style={{ color: textColor }} />
          ) : isFailed ? (
            <XCircle className="w-4 h-4" style={{ color: textColor }} />
          ) : (
            <Icon className="w-4 h-4" style={{ color: textColor }} />
          )}
        </div>

        <span className="text-xs font-semibold" style={{ color: textColor }}>
          {data.name}
        </span>

        {data.task && isRunning && (
          <span className="text-[9px] opacity-70 leading-tight max-w-[120px] truncate" style={{ color: textColor }}>
            {data.task}
          </span>
        )}

        {/* Thinking dots */}
        {isRunning && (
          <div className="flex gap-0.5">
            {[0, 1, 2].map(i => (
              <motion.div
                key={i}
                className="w-1 h-1 rounded-full"
                style={{ background: textColor }}
                animate={{ opacity: [0.3, 1, 0.3], scale: [0.8, 1.1, 0.8] }}
                transition={{ duration: 0.9, delay: i * 0.15, repeat: Infinity }}
              />
            ))}
          </div>
        )}
      </div>

      {!data.isFirst && (
        <Handle type="target" position={Position.Left} style={{ background: borderColor, border: 'none', width: 8, height: 8 }} />
      )}
      {!data.isLast && (
        <Handle type="source" position={Position.Right} style={{ background: borderColor, border: 'none', width: 8, height: 8 }} />
      )}
    </div>
  );
}

const nodeTypes = { worker: WorkerNode };

// ── Pipeline layout ───────────────────────────────────────────────────────────

const WORKER_ORDER = ['Research', 'Planning', 'Coding', 'Testing', 'Quality', 'Review'];
const X_GAP = 200;
const Y_CENTER = 150;

function buildGraph(workers: WorkerState[]): { nodes: Node[]; edges: Edge[] } {
  const ordered = WORKER_ORDER.map(name =>
    workers.find(w => w.name === name) ?? { name, status: 'idle' as const }
  );

  const nodes: Node[] = ordered.map((w, i) => ({
    id: w.name,
    type: 'worker',
    position: { x: 80 + i * X_GAP, y: Y_CENTER },
    data: { ...w, isFirst: i === 0, isLast: i === ordered.length - 1 },
    draggable: false,
    selectable: false,
  }));

  const edges: Edge[] = ordered.slice(0, -1).map((w, i) => {
    const src   = w;
    const tgt   = ordered[i + 1];
    const done  = src.status === 'success';
    const color = done ? '#10B981' : '#374151';
    return {
      id:          `${src.name}->${tgt.name}`,
      source:      src.name,
      target:      tgt.name,
      animated:    tgt.status === 'running',
      style:       { stroke: color, strokeWidth: done ? 2 : 1.5 },
      type:        'smoothstep',
    };
  });

  return { nodes, edges };
}

// ── Main component ────────────────────────────────────────────────────────────

export function PipelineView() {
  const { workers, running } = useMarkStore();

  const initial = useMemo(() => buildGraph(workers), []); // eslint-disable-line
  const [nodes, setNodes, onNodesChange] = useNodesState(initial.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initial.edges);

  // Re-derive graph whenever worker states change
  useEffect(() => {
    const { nodes: n, edges: e } = buildGraph(workers);
    setNodes(n);
    setEdges(e);
  }, [workers, setNodes, setEdges]);

  return (
    <div className="h-full w-full flex flex-col bg-background">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border/50 bg-card/40 shrink-0">
        <div>
          <h2 className="text-sm font-semibold">Execution Pipeline</h2>
          <p className="text-[11px] text-muted-foreground mt-0.5">
            {running ? 'Run in progress — nodes glow while active' : 'Idle — nodes activate when a run starts'}
          </p>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-purple-500 inline-block" /> Running</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" /> Done</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500 inline-block" /> Failed</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-gray-600 inline-block" /> Idle</span>
        </div>
      </div>

      {/* React Flow canvas */}
      <div className="flex-1">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.35 }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          panOnDrag
          zoomOnScroll
          style={{ background: 'hsl(var(--background))' }}
        >
          <Background
            variant={BackgroundVariant.Dots}
            gap={20}
            size={1}
            color="rgba(255,255,255,0.04)"
          />
          <Controls
            showInteractive={false}
            className="[&_button]:bg-card [&_button]:border-border [&_button]:text-foreground"
          />
          <MiniMap
            nodeColor={n => {
              const status = (n.data as unknown as WorkerState).status;
              return status === 'running' ? '#8B5CF6' : status === 'success' ? '#10B981' : status === 'failed' ? '#EF4444' : '#374151';
            }}
            maskColor="rgba(0,0,0,0.4)"
            className="!bg-card !border-border/50 rounded-lg overflow-hidden"
          />
        </ReactFlow>
      </div>
    </div>
  );
}
