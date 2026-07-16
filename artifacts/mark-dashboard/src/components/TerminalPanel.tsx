import { useEffect, useRef } from 'react';
import { useMarkStore } from '@/store/markStore';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { Terminal as TerminalIcon } from 'lucide-react';

export function TerminalPanel() {
  const terminalRef = useRef<HTMLDivElement>(null);
  const xtermRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const { streamingTokens, logs } = useMarkStore();
  const lastProcessedLength = useRef(0);

  useEffect(() => {
    if (!terminalRef.current) return;

    const term = new Terminal({
      theme: {
        background: '#0a0a0a',
        foreground: '#e5e5e5',
        cursor: '#4f46e5',
        selectionBackground: 'rgba(79, 70, 229, 0.3)',
      },
      fontFamily: 'var(--app-font-mono), monospace',
      fontSize: 13,
      lineHeight: 1.4,
      cursorBlink: true,
      disableStdin: true,
      convertEol: true,
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    
    term.open(terminalRef.current);
    fitAddon.fit();

    xtermRef.current = term;
    fitAddonRef.current = fitAddon;

    const handleResize = () => {
      fitAddon.fit();
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      term.dispose();
    };
  }, []);

  // Write new streaming tokens to terminal
  useEffect(() => {
    if (xtermRef.current) {
      if (streamingTokens.length === 0) {
        // Run was reset
        xtermRef.current.clear();
        lastProcessedLength.current = 0;
      } else if (streamingTokens.length > lastProcessedLength.current) {
        const newText = streamingTokens.slice(lastProcessedLength.current);
        xtermRef.current.write(newText);
        lastProcessedLength.current = streamingTokens.length;
      }
    }
  }, [streamingTokens]);

  return (
    <div className="h-full w-full flex flex-col bg-[#0a0a0a]">
      <div className="h-8 shrink-0 bg-[#111] border-b border-[#222] flex items-center px-3 gap-2 text-xs text-[#888] font-mono">
        <TerminalIcon className="w-3.5 h-3.5" />
        MARK TTY-1
      </div>
      <div className="flex-1 overflow-hidden p-2" ref={terminalRef}></div>
    </div>
  );
}