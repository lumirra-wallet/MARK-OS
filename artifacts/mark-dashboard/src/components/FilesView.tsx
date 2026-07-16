import { useMarkStore } from '@/store/markStore';
import { ScrollArea } from '@/components/ui/scroll-area';
import { FileCode, FilePlus, FileMinus, FileEdit } from 'lucide-react';
import { MonacoEditorPanel } from './MonacoEditorPanel';
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels';

export function FilesView() {
  const { filesInRun, fetchFileContent } = useMarkStore();

  const getIcon = (op: string) => {
    switch (op) {
      case 'created': return <FilePlus className="w-4 h-4 text-emerald-500" />;
      case 'modified': return <FileEdit className="w-4 h-4 text-amber-500" />;
      case 'deleted': return <FileMinus className="w-4 h-4 text-destructive" />;
      default: return <FileCode className="w-4 h-4 text-muted-foreground" />;
    }
  };

  return (
    <PanelGroup direction="horizontal" className="h-full">
      <Panel defaultSize={30} minSize={20} className="border-r border-border/50 bg-sidebar/30 flex flex-col">
        <div className="p-4 border-b border-border/50 shrink-0">
          <h2 className="text-sm font-semibold tracking-wide uppercase text-muted-foreground">Files Changed in Run</h2>
        </div>
        
        <ScrollArea className="flex-1">
          <div className="p-2 flex flex-col gap-1">
            {filesInRun.length === 0 ? (
              <div className="text-center p-8 text-muted-foreground text-sm italic">
                No files modified yet.
              </div>
            ) : (
              filesInRun.map((file, i) => (
                <button 
                  key={i}
                  onClick={() => fetchFileContent(file.path, file.operation === 'modified')}
                  className="flex items-center gap-3 px-3 py-2 rounded-md hover:bg-muted text-left transition-colors"
                >
                  {getIcon(file.operation)}
                  <div className="flex-1 overflow-hidden">
                    <div className="text-sm truncate font-mono">{file.path.split('/').pop()}</div>
                    <div className="text-[10px] text-muted-foreground truncate">{file.path}</div>
                  </div>
                </button>
              ))
            )}
          </div>
        </ScrollArea>
      </Panel>
      
      <PanelResizeHandle className="w-1 bg-border hover:bg-accent cursor-col-resize transition-colors" />
      
      <Panel defaultSize={70} minSize={30} className="bg-background">
        <MonacoEditorPanel />
      </Panel>
    </PanelGroup>
  );
}