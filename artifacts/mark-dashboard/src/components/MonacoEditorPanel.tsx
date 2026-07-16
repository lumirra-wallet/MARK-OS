import { useMarkStore } from '@/store/markStore';
import { X, FileCode } from 'lucide-react';
import Editor, { DiffEditor } from '@monaco-editor/react';

export function MonacoEditorPanel() {
  const { openFiles, activeFileTab, setActiveFileTab, closeFile } = useMarkStore();

  if (openFiles.length === 0) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center text-muted-foreground bg-card/10">
        <FileCode className="w-12 h-12 mb-4 opacity-20" />
        <p>Select a file from the list to view contents</p>
      </div>
    );
  }

  const activeFile = openFiles.find(f => f.path === activeFileTab) || openFiles[0];

  return (
    <div className="h-full flex flex-col bg-background">
      {/* Tabs */}
      <div className="h-10 bg-muted/30 border-b border-border/50 flex items-end px-2 gap-1 overflow-x-auto shrink-0">
        {openFiles.map(file => (
          <div 
            key={file.path}
            className={`
              h-8 px-4 flex items-center gap-2 rounded-t-lg border border-b-0 border-border/50 text-xs font-mono cursor-pointer min-w-[120px] max-w-[200px]
              ${activeFileTab === file.path 
                ? 'bg-background text-foreground z-10 relative shadow-[0_-2px_10px_rgba(0,0,0,0.05)] border-b-background translate-y-[1px]' 
                : 'bg-muted/50 text-muted-foreground hover:bg-muted/80'}
            `}
            onClick={() => setActiveFileTab(file.path)}
          >
            <span className="truncate flex-1">{file.path.split('/').pop()}</span>
            <button 
              className="hover:text-destructive shrink-0 opacity-50 hover:opacity-100 transition-opacity p-0.5 rounded-sm hover:bg-destructive/10"
              onClick={(e) => {
                e.stopPropagation();
                closeFile(file.path);
              }}
            >
              <X className="w-3 h-3" />
            </button>
          </div>
        ))}
      </div>

      {/* Editor Area */}
      <div className="flex-1 bg-background pt-2">
        {activeFile.isDiff && activeFile.originalContent ? (
          <DiffEditor
            height="100%"
            language={getLanguage(activeFile.path)}
            original={activeFile.originalContent}
            modified={activeFile.content}
            theme="vs-dark"
            options={{
              readOnly: true,
              minimap: { enabled: false },
              fontFamily: 'var(--app-font-mono), monospace',
              fontSize: 13,
              renderSideBySide: false,
            }}
          />
        ) : (
          <Editor
            height="100%"
            language={getLanguage(activeFile.path)}
            value={activeFile.content}
            theme="vs-dark"
            options={{
              readOnly: true,
              minimap: { enabled: false },
              fontFamily: 'var(--app-font-mono), monospace',
              fontSize: 13,
              wordWrap: 'on',
            }}
          />
        )}
      </div>
    </div>
  );
}

function getLanguage(path: string) {
  const ext = path.split('.').pop()?.toLowerCase();
  switch (ext) {
    case 'ts':
    case 'tsx': return 'typescript';
    case 'js':
    case 'jsx': return 'javascript';
    case 'py': return 'python';
    case 'json': return 'json';
    case 'html': return 'html';
    case 'css': return 'css';
    case 'md': return 'markdown';
    case 'yaml':
    case 'yml': return 'yaml';
    default: return 'plaintext';
  }
}