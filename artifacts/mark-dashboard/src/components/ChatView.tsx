/**
 * ChatView — MARK's live conversation. The only conversational surface in
 * the system; workers never speak here directly (see ContentBlock's
 * 'worker' variant — a status chip, never free text).
 *
 * Layout
 * ──────
 * ┌─────────────────────────────────────────────────────┐
 * │ Header: workspace selector + controls                │
 * ├─────────────────────────────────────────────────────┤
 * │                                                      │
 * │   [message thread, auto-scrolls to bottom]          │
 * │                                                      │
 * │   MARK  ·  blocks: text, worker, file, tests…       │
 * │                              User ·  goal text      │
 * │                                                      │
 * ├─────────────────────────────────────────────────────┤
 * │ [text input…]                            [SEND ▶]  │
 * └─────────────────────────────────────────────────────┘
 */
import React, {
  useCallback, useEffect, useRef, useState,
} from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Send, Square, FolderOpen,
  CheckCircle2, XCircle, Loader2, FileCode2, FileMinus, FilePlus,
  TestTube2, Zap, Trash2,
  Sparkles, Code2, Eye, CircleDashed,
  GitBranch, Plus, X,
  Bug, Shield, FileText, Camera,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useMarkStore, ChatMessage, ContentBlock } from '@/store/markStore';
import { MarkAvatar } from './MarkAvatar';
import { markApi } from '@/lib/markApi';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { format } from 'date-fns';

// ── Worker icon map ───────────────────────────────────────────────────────────

const WORKER_ICONS: Record<string, React.ComponentType<any>> = {
  Engineer: Code2,
  QA:       TestTube2,
  Debugger: Bug,
  Reviewer: Eye,
  Git:      GitBranch,
  Research: Sparkles,
  Security: Shield,
  Docs:     FileText,
  Preview:  Camera,
};

// ── Block renderers ───────────────────────────────────────────────────────────

function TextBlock({ text, streaming }: { text: string; streaming?: boolean }) {
  return (
    <div className="text-sm leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Inline code
          code: ({ children, className, ...props }: any) => {
            const isBlock = className?.startsWith('language-');
            if (!isBlock) {
              return (
                <code className="text-accent bg-muted/50 px-1 py-0.5 rounded text-[11px] font-mono" {...props}>
                  {children}
                </code>
              );
            }
            return (
              <pre className="bg-muted/30 border border-border/50 rounded-lg p-3 overflow-x-auto my-2 text-xs">
                <code className="font-mono text-foreground" {...props}>{children}</code>
              </pre>
            );
          },
          p:      ({ children }) => <p className="mb-1.5 last:mb-0 text-foreground/90">{children}</p>,
          ul:     ({ children }) => <ul className="list-disc list-inside space-y-0.5 my-1.5 pl-1">{children}</ul>,
          ol:     ({ children }) => <ol className="list-decimal list-inside space-y-0.5 my-1.5 pl-1">{children}</ol>,
          li:     ({ children }) => <li className="text-foreground/90">{children}</li>,
          a:      ({ href, children }) => <a href={href} target="_blank" rel="noreferrer" className="text-accent hover:underline">{children}</a>,
          strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
          em:     ({ children }) => <em className="italic text-foreground/80">{children}</em>,
          h1:     ({ children }) => <h1 className="text-base font-bold mt-2 mb-1">{children}</h1>,
          h2:     ({ children }) => <h2 className="text-sm font-bold mt-2 mb-1">{children}</h2>,
          h3:     ({ children }) => <h3 className="text-sm font-semibold mt-1.5 mb-0.5">{children}</h3>,
          hr:     () => <hr className="border-border/40 my-2" />,
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-accent/40 pl-3 my-1.5 text-muted-foreground italic">
              {children}
            </blockquote>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
      {streaming && (
        <motion.span
          className="inline-block w-[2px] h-[1em] bg-accent ml-0.5 align-middle"
          animate={{ opacity: [1, 0, 1] }}
          transition={{ duration: 0.8, repeat: Infinity }}
        />
      )}
    </div>
  );
}

function WorkerBlock({
  block,
}: {
  block: Extract<ContentBlock, { type: 'worker' }>;
}) {
  const Icon = WORKER_ICONS[block.name] ?? CircleDashed;
  const isRunning = block.status === 'running';
  const isDone    = block.status === 'success';
  const isFailed  = block.status === 'failed';

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn(
        'flex items-center gap-2.5 rounded-lg px-3 py-2 border text-sm font-medium my-1',
        isRunning && 'bg-accent/10 border-accent/30 text-accent',
        isDone    && 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400',
        isFailed  && 'bg-destructive/10 border-destructive/20 text-destructive',
      )}
    >
      {isRunning ? (
        <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" />
      ) : isDone ? (
        <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
      ) : isFailed ? (
        <XCircle className="w-3.5 h-3.5 shrink-0" />
      ) : (
        <Icon className="w-3.5 h-3.5 shrink-0" />
      )}

      <span>{block.name}</span>

      {block.task && (
        <span className="text-[11px] font-normal opacity-70 truncate max-w-[240px]">
          — {block.task}
        </span>
      )}

      {isRunning && (
        <motion.div
          className="ml-auto flex gap-0.5"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
        >
          {[0, 1, 2].map(i => (
            <motion.div
              key={i}
              className="w-1 h-1 rounded-full bg-current"
              animate={{ opacity: [0.3, 1, 0.3] }}
              transition={{ duration: 0.9, delay: i * 0.2, repeat: Infinity }}
            />
          ))}
        </motion.div>
      )}
    </motion.div>
  );
}

function FileBlock({
  block,
}: {
  block: Extract<ContentBlock, { type: 'file' }>;
}) {
  const { fetchFileContent } = useMarkStore();
  const Icon = block.op === 'created' ? FilePlus : block.op === 'modified' ? FileCode2 : FileMinus;
  const colors = {
    created:  'text-emerald-400',
    modified: 'text-blue-400',
    deleted:  'text-red-400',
  };

  return (
    <motion.button
      initial={{ opacity: 0, x: -4 }}
      animate={{ opacity: 1, x: 0 }}
      onClick={() => block.op !== 'deleted' && fetchFileContent(block.path)}
      className={cn(
        'flex items-center gap-2 text-[12px] font-mono rounded px-2 py-1 my-0.5',
        'hover:bg-muted/40 transition-colors text-left w-full',
        colors[block.op],
      )}
    >
      <Icon className="w-3.5 h-3.5 shrink-0" />
      <span className="truncate">{block.path.split('/').pop()}</span>
      <span className="text-muted-foreground/60 truncate ml-auto hidden sm:block">{block.path}</span>
    </motion.button>
  );
}

function TestsBlock({
  block,
}: {
  block: Extract<ContentBlock, { type: 'tests' }>;
}) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn(
        'flex items-center gap-2 rounded-lg px-3 py-2 border text-sm my-1',
        block.status === 'running' && 'bg-muted/30 border-border text-muted-foreground',
        block.status === 'passed'  && 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400',
        block.status === 'failed'  && 'bg-destructive/10 border-destructive/20 text-destructive',
      )}
    >
      {block.status === 'running' && <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" />}
      {block.status === 'passed'  && <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />}
      {block.status === 'failed'  && <XCircle className="w-3.5 h-3.5 shrink-0" />}
      <TestTube2 className="w-3.5 h-3.5 shrink-0" />
      <span className="font-medium">Tests</span>
      <span className="text-[11px] opacity-70 capitalize">{block.status}</span>
    </motion.div>
  );
}

function ApprovalBlock({
  block,
}: {
  block: Extract<ContentBlock, { type: 'approval' }>;
}) {
  const { approve, deny } = useMarkStore();
  const [decided, setDecided] = useState(false);

  const handleApprove = (always: boolean) => {
    setDecided(true);
    approve(block.requestId, always);
  };

  const handleDeny = () => {
    setDecided(true);
    deny(block.requestId);
  };

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.97 }}
      animate={{ opacity: 1, scale: 1 }}
      className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 my-2 space-y-3"
    >
      <div className="flex items-start gap-2">
        <div className="w-5 h-5 rounded-full bg-amber-500/20 flex items-center justify-center shrink-0 mt-0.5">
          <span className="text-amber-400 text-[10px]">!</span>
        </div>
        <div>
          <p className="text-sm font-semibold text-amber-400">Approval Required</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            MARK wants to <span className="text-foreground font-medium">{block.operation}</span>{' '}
            <code className="font-mono bg-muted px-1 rounded">{block.path.split('/').pop()}</code>
          </p>
          <p className="text-[10px] text-muted-foreground/60 font-mono mt-1">{block.path}</p>
        </div>
      </div>

      {!decided ? (
        <div className="flex gap-2">
          <Button size="sm" variant="outline" className="text-xs border-amber-500/30 text-amber-400 hover:bg-amber-500/10 flex-1" onClick={() => handleApprove(false)}>
            Approve Once
          </Button>
          <Button size="sm" variant="outline" className="text-xs border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10 flex-1" onClick={() => handleApprove(true)}>
            Always Allow
          </Button>
          <Button size="sm" variant="outline" className="text-xs border-destructive/30 text-destructive hover:bg-destructive/10" onClick={handleDeny}>
            Reject
          </Button>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground italic">Decision recorded.</p>
      )}
    </motion.div>
  );
}

function ErrorBlock({ block }: { block: Extract<ContentBlock, { type: 'error' }> }) {
  return (
    <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 my-1">
      <div className="flex gap-2">
        <XCircle className="w-4 h-4 text-destructive shrink-0 mt-0.5" />
        <p className="text-sm text-destructive">{block.text}</p>
      </div>
    </div>
  );
}

function SummaryBlock({ block }: { block: Extract<ContentBlock, { type: 'summary' }> }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn(
        'rounded-xl border p-4 my-2 space-y-2',
        block.success
          ? 'bg-emerald-500/10 border-emerald-500/20'
          : 'bg-destructive/10 border-destructive/20',
      )}
    >
      <div className="flex items-center gap-2">
        {block.success
          ? <CheckCircle2 className="w-5 h-5 text-emerald-400" />
          : <XCircle className="w-5 h-5 text-destructive" />
        }
        <span className={cn('font-semibold text-sm', block.success ? 'text-emerald-400' : 'text-destructive')}>
          {block.text}
        </span>
        <span className="ml-auto text-xs font-mono text-muted-foreground">
          {block.elapsed < 1 ? '< 1s' : `${Math.round(block.elapsed)}s`}
        </span>
      </div>

      {(block.filesCreated.length > 0 || block.filesModified.length > 0) && (
        <div className="space-y-1 pt-1">
          {block.filesCreated.map(f => (
            <div key={f} className="flex items-center gap-1.5 text-[11px] font-mono text-emerald-400">
              <FilePlus className="w-3 h-3 shrink-0" />
              {f.split('/').pop()}
            </div>
          ))}
          {block.filesModified.map(f => (
            <div key={f} className="flex items-center gap-1.5 text-[11px] font-mono text-blue-400">
              <FileCode2 className="w-3 h-3 shrink-0" />
              {f.split('/').pop()}
            </div>
          ))}
        </div>
      )}
    </motion.div>
  );
}

function BlockRenderer({ block }: { block: ContentBlock }) {
  switch (block.type) {
    case 'text':     return <TextBlock text={block.text} />;
    case 'streaming': return <TextBlock text={block.text} streaming />;
    case 'worker':   return <WorkerBlock block={block} />;
    case 'file':     return <FileBlock block={block} />;
    case 'tests':    return <TestsBlock block={block} />;
    case 'approval': return <ApprovalBlock block={block} />;
    case 'error':    return <ErrorBlock block={block} />;
    case 'summary':  return <SummaryBlock block={block} />;
    default:         return null;
  }
}

// ── Message bubbles ───────────────────────────────────────────────────────────

function UserBubble({ msg }: { msg: ChatMessage }) {
  return (
    <motion.div
      initial={{ opacity: 0, x: 16 }}
      animate={{ opacity: 1, x: 0 }}
      className="flex flex-col items-end gap-1 max-w-[75%] ml-auto"
    >
      <div className="bg-accent text-accent-foreground rounded-2xl rounded-br-sm px-4 py-3 text-sm leading-relaxed shadow-sm">
        {msg.text}
      </div>
      <span className="text-[10px] text-muted-foreground px-1">
        {format(new Date(msg.timestamp), 'HH:mm')}
      </span>
    </motion.div>
  );
}

function MarkBubble({ msg }: { msg: ChatMessage }) {
  return (
    <motion.div
      initial={{ opacity: 0, x: -16 }}
      animate={{ opacity: 1, x: 0 }}
      className="flex flex-col items-start gap-1 max-w-[85%]"
    >
      <div className="flex items-center gap-2 px-1 mb-1">
        <MarkAvatar state={msg.isActive ? 'speaking' : 'idle'} size={24} />
        <span className="text-[11px] font-semibold text-accent">MARK</span>
        <span className="text-[10px] text-muted-foreground">
          {format(new Date(msg.timestamp), 'HH:mm')}
        </span>
      </div>

      <div className="bg-card/80 border border-border/50 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm w-full space-y-1">
        {msg.blocks.length === 0 && msg.isActive && (
          <div className="flex items-center gap-2 text-muted-foreground text-sm">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            <span>Thinking…</span>
          </div>
        )}
        {msg.blocks.map((block, i) => (
          <BlockRenderer key={i} block={block} />
        ))}
      </div>
    </motion.div>
  );
}

// ── Composer ──────────────────────────────────────────────────────────────────

function Composer({ workspace }: { workspace: string }) {
  const { sendUserMessage, cancelRun, running } = useMarkStore();
  const [input, setInput] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea as content grows
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 120) + 'px';
  }, [input]);

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text || !workspace) return;
    sendUserMessage(text, workspace);
    setInput('');
  }, [input, workspace, sendUserMessage]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="border-t border-border/50 bg-card/60 backdrop-blur px-4 py-3 space-y-2">
      <div className="flex items-end gap-2 rounded-2xl border border-border/50 focus-within:border-accent/50 bg-background/80 p-2 transition-all">

        {/* Text input */}
        <textarea
          ref={textareaRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={!workspace ? 'Set a workspace above first…' : 'Type a goal for MARK — e.g. "Build a Flask API"'}
          rows={1}
          className="flex-1 resize-none bg-transparent text-sm placeholder:text-muted-foreground/50 focus:outline-none min-h-[36px] max-h-[120px] py-2 leading-relaxed"
        />

        {/* Send / Stop */}
        {running ? (
          <button
            onClick={cancelRun}
            className="shrink-0 w-9 h-9 rounded-xl bg-destructive/20 text-destructive flex items-center justify-center hover:bg-destructive/30 transition-colors"
            title="Stop run"
          >
            <Square className="w-3.5 h-3.5 fill-current" />
          </button>
        ) : (
          <button
            onClick={handleSend}
            disabled={!input.trim() || !workspace}
            className={cn(
              'shrink-0 w-9 h-9 rounded-xl flex items-center justify-center transition-all',
              input.trim() && workspace
                ? 'bg-accent text-accent-foreground shadow-md shadow-accent/20 hover:bg-accent/90'
                : 'bg-muted text-muted-foreground/40 cursor-not-allowed',
            )}
            title="Send (Enter)"
          >
            <Send className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Composer footer hint */}
      <div className="flex items-center gap-3 px-1">
        <span className="ml-auto text-[10px] text-muted-foreground/50">
          Enter to send · Shift+Enter for new line
        </span>
      </div>
    </div>
  );
}

// ── Main ChatView ─────────────────────────────────────────────────────────────

// ── Branch selector (Feature 9) ───────────────────────────────────────────────

function BranchBar() {
  const { branches, activeBranch, createBranch, switchBranch, deleteBranch } = useMarkStore();
  const [creating, setCreating] = useState(false);
  const [newName,  setNewName]  = useState('');

  const names = Object.keys(branches);

  const handleCreate = () => {
    const n = newName.trim();
    if (!n || branches[n]) return;
    createBranch(n);
    switchBranch(n);
    setNewName(''); setCreating(false);
  };

  return (
    <div className="flex items-center gap-1 px-4 py-1.5 border-b border-border/30 bg-card/20 shrink-0 overflow-x-auto">
      <GitBranch className="w-3 h-3 text-muted-foreground shrink-0" />
      {names.map(name => (
        <div key={name} className="flex items-center shrink-0">
          <button
            onClick={() => switchBranch(name)}
            className={cn(
              'text-[10px] px-2 py-0.5 rounded-l font-mono transition-colors',
              name === activeBranch
                ? 'bg-accent/20 text-accent'
                : 'bg-muted/30 text-muted-foreground hover:text-foreground',
            )}
          >
            {name}
          </button>
          {name !== 'main' && (
            <button
              onClick={() => deleteBranch(name)}
              className="text-[10px] px-1 py-0.5 rounded-r bg-muted/30 text-muted-foreground hover:text-red-400 transition-colors"
            >
              <X className="w-2.5 h-2.5" />
            </button>
          )}
        </div>
      ))}
      {creating ? (
        <form onSubmit={e => { e.preventDefault(); handleCreate(); }} className="flex items-center gap-1">
          <input
            autoFocus
            value={newName}
            onChange={e => setNewName(e.target.value)}
            onBlur={() => { if (!newName.trim()) setCreating(false); }}
            placeholder="branch name"
            className="text-[10px] font-mono bg-muted/30 border border-accent/30 rounded px-1.5 py-0.5 w-24 focus:outline-none"
          />
        </form>
      ) : (
        <button
          onClick={() => setCreating(true)}
          className="text-[10px] px-1.5 py-0.5 rounded bg-muted/20 text-muted-foreground hover:text-foreground flex items-center gap-0.5 shrink-0"
        >
          <Plus className="w-2.5 h-2.5" /> branch
        </button>
      )}
    </div>
  );
}

// ── Main ChatView ─────────────────────────────────────────────────────────────

export function ChatView() {
  const {
    messages, running, workspace, goal, clearMessages,
    setWorkspace, connectionStatus,
  } = useMarkStore();

  const [editingWs, setEditingWs] = useState(false);
  const [wsInput,   setWsInput]   = useState(workspace);
  const bottomRef                  = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages or new blocks
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Auto-detect workspace on connect if none set
  const { serverUrl } = useMarkStore();
  useEffect(() => {
    if (workspace || connectionStatus !== 'connected') return;
    markApi.detectWorkspace(serverUrl).then(data => {
      const ws = data.git_root || data.workspace || data.cwd;
      if (ws) { setWorkspace(ws); setWsInput(ws); }
    }).catch(() => {});
  }, [connectionStatus]); // eslint-disable-line

  const handleWsSave = () => {
    setWorkspace(wsInput.trim() || workspace);
    setEditingWs(false);
  };

  return (
    <div className="flex flex-col h-full">

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-4 py-2.5 border-b border-border/50 bg-card/40 shrink-0 flex-wrap">
        {/* Workspace selector */}
        <FolderOpen className="w-4 h-4 text-muted-foreground shrink-0" />
        {editingWs ? (
          <form
            onSubmit={e => { e.preventDefault(); handleWsSave(); }}
            className="flex items-center gap-2 flex-1"
          >
            <input
              autoFocus
              value={wsInput}
              onChange={e => setWsInput(e.target.value)}
              onBlur={handleWsSave}
              placeholder="/home/user/projects/myapp"
              className="flex-1 text-xs font-mono bg-muted/50 border border-accent/30 rounded px-2 py-1 focus:outline-none"
            />
            <button type="submit" className="text-xs text-accent hover:underline">Save</button>
          </form>
        ) : (
          <button
            onClick={() => { setWsInput(workspace); setEditingWs(true); }}
            className="flex-1 text-left text-xs font-mono text-muted-foreground hover:text-foreground transition-colors truncate"
            title="Click to change workspace"
          >
            {workspace || <span className="italic text-muted-foreground/50">Click to set workspace path…</span>}
          </button>
        )}

        {/* Status dot */}
        <div className={cn(
          'w-2 h-2 rounded-full shrink-0',
          connectionStatus === 'connected'   && 'bg-emerald-400',
          connectionStatus === 'connecting'  && 'bg-amber-400 animate-pulse',
          connectionStatus === 'disconnected' && 'bg-muted-foreground/40',
        )} title={connectionStatus} />

        {/* Clear button */}
        <button
          onClick={clearMessages}
          className="shrink-0 text-muted-foreground/50 hover:text-muted-foreground transition-colors p-1 rounded"
          title="Clear conversation"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* ── Branch bar (Feature 9) ──────────────────────────────────────────── */}
      <BranchBar />

      {/* ── Message thread ──────────────────────────────────────────────────── */}
      <ScrollArea className="flex-1 overflow-y-auto">
        <div className="flex flex-col gap-6 px-4 py-6 max-w-3xl mx-auto">
          <AnimatePresence initial={false}>
            {messages.map(msg =>
              msg.role === 'user'
                ? <UserBubble key={msg.id} msg={msg} />
                : <MarkBubble key={msg.id} msg={msg} />
            )}
          </AnimatePresence>

          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 text-center gap-4">
              <div className="w-16 h-16 rounded-2xl bg-accent/10 border border-accent/20 flex items-center justify-center">
                <Zap className="w-8 h-8 text-accent" />
              </div>
              <div>
                <h2 className="font-semibold text-lg">Connecting to MARK…</h2>
                <p className="text-sm text-muted-foreground mt-1">
                  Make sure the MARK server is running on{' '}
                  <code className="font-mono text-xs bg-muted px-1 rounded">
                    {useMarkStore.getState().serverUrl}
                  </code>
                </p>
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>
      </ScrollArea>

      {/* ── Composer ─────────────────────────────────────────────────────────── */}
      <Composer workspace={workspace} />
    </div>
  );
}
