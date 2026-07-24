/**
 * MemoryPanel — Browse and read MARK's persistent memory files.
 *
 * Left: file list with preview snippets
 * Right: full file content rendered as Markdown
 */
import React, { useEffect, useState, useCallback } from 'react';
import { motion } from 'framer-motion';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Brain, RefreshCw, FileText, AlertCircle, FolderOpen,
} from 'lucide-react';
import { useMarkStore } from '@/store/markStore';
import { markApi } from '@/lib/markApi';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

interface MemoryFile {
  name:    string;
  path:    string;
  size:    number;
  preview: string;
}

export function MemoryPanel() {
  const { serverUrl, workspace } = useMarkStore();
  const [files,    setFiles]    = useState<MemoryFile[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [content,  setContent]  = useState<string>('');
  const [loading,  setLoading]  = useState(false);
  const [fileLoading, setFileLoading] = useState(false);
  const [memDir,   setMemDir]   = useState<string>('');
  const [exists,   setExists]   = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await markApi.getMemoryFiles(serverUrl, workspace || undefined);
      setFiles((data as any).files ?? []);
      setMemDir((data as any).memory_dir ?? '');
      setExists((data as any).exists ?? false);
      if (selected && !((data as any).files ?? []).find((f: MemoryFile) => f.path === selected)) {
        setSelected(null);
        setContent('');
      }
    } catch (err) {
      console.error('memory refresh', err);
    } finally {
      setLoading(false);
    }
  }, [serverUrl, workspace, selected]);

  useEffect(() => { refresh(); }, [refresh]);

  const openFile = async (path: string) => {
    if (selected === path) return;
    setSelected(path);
    setFileLoading(true);
    try {
      const data = await markApi.getMemoryFile(serverUrl, path, workspace || undefined);
      setContent(data.content);
    } catch {
      setContent('Failed to load file.');
    } finally {
      setFileLoading(false);
    }
  };

  const formatSize = (bytes: number) =>
    bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border/50 bg-card/40 shrink-0">
        <div className="flex items-center gap-2">
          <Brain className="w-4 h-4 text-accent" />
          <span className="text-sm font-semibold">Elena's Memory</span>
          {files.length > 0 && (
            <span className="text-xs text-muted-foreground">({files.length} files)</span>
          )}
        </div>
        <Button size="icon" variant="ghost" className="h-7 w-7" onClick={refresh} disabled={loading}>
          <RefreshCw className={cn('w-3.5 h-3.5', loading && 'animate-spin')} />
        </Button>
      </div>

      {!exists ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 text-center p-8">
          <FolderOpen className="w-10 h-10 text-muted-foreground/30" />
          <div>
            <p className="text-sm font-medium text-muted-foreground">No memory directory found</p>
            <p className="text-xs text-muted-foreground/60 mt-1 font-mono">{memDir}</p>
            <p className="text-xs text-muted-foreground/60 mt-2">
              Memory files are created automatically as Elena works on your project.
            </p>
          </div>
        </div>
      ) : (
        <div className="flex flex-1 overflow-hidden">
          {/* File list */}
          <div className="w-2/5 border-r border-border/50 flex flex-col overflow-hidden">
            <ScrollArea className="flex-1">
              <div className="py-2 space-y-0.5">
                {files.length === 0 ? (
                  <p className="text-xs text-muted-foreground text-center py-8 italic px-4">
                    No memory files yet
                  </p>
                ) : files.map(f => (
                  <motion.button
                    key={f.path}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    onClick={() => openFile(f.path)}
                    className={cn(
                      'w-full text-left px-4 py-2.5 hover:bg-muted/40 transition-colors border-b border-border/20',
                      selected === f.path && 'bg-accent/10 border-l-2 border-l-accent',
                    )}
                  >
                    <div className="flex items-start gap-2">
                      <FileText className="w-3.5 h-3.5 text-muted-foreground shrink-0 mt-0.5" />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium text-foreground truncate">{f.name}</p>
                        {f.preview && (
                          <p className="text-[10px] text-muted-foreground truncate mt-0.5 leading-snug">
                            {f.preview}
                          </p>
                        )}
                        <p className="text-[10px] text-muted-foreground/50 mt-0.5">{formatSize(f.size)}</p>
                      </div>
                    </div>
                  </motion.button>
                ))}
              </div>
            </ScrollArea>
          </div>

          {/* Content viewer */}
          <div className="flex-1 overflow-hidden bg-card/20">
            {fileLoading ? (
              <div className="flex items-center justify-center h-full">
                <RefreshCw className="w-5 h-5 animate-spin text-muted-foreground" />
              </div>
            ) : content ? (
              <ScrollArea className="h-full">
                <div className="p-5 prose prose-invert prose-sm max-w-none
                  prose-headings:text-foreground prose-headings:font-semibold
                  prose-p:text-foreground/90 prose-p:leading-relaxed
                  prose-code:text-accent prose-code:bg-muted/50 prose-code:px-1 prose-code:rounded prose-code:text-[11px]
                  prose-pre:bg-muted/30 prose-pre:border prose-pre:border-border/50
                  prose-a:text-accent prose-a:no-underline hover:prose-a:underline
                  prose-strong:text-foreground prose-strong:font-semibold
                  prose-li:text-foreground/90
                  prose-hr:border-border/50
                  prose-blockquote:border-l-accent prose-blockquote:text-muted-foreground
                ">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {content}
                  </ReactMarkdown>
                </div>
              </ScrollArea>
            ) : (
              <div className="flex-1 flex items-center justify-center h-full text-xs text-muted-foreground italic">
                Select a memory file to read it
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
