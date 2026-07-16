---
name: MARK Web Dashboard
description: Architecture decisions and key paths for the React+Vite dashboard that connects to the MARK Python FastAPI server.
---

## Key paths
- Artifact: `artifacts/mark-dashboard/`
- Zustand store: `src/store/markStore.ts` — holds WS connection, run state, workers, permissions, timeline, streaming tokens, open files
- REST helpers: `src/lib/markApi.ts` — typed wrappers for all MARK server endpoints
- Main layout: `src/Dashboard.tsx` — five-region layout (TopNav, LeftSidebar, CenterPanel, ApprovalsSidebar, TerminalPanel)
- Components: `src/components/` — ExecutionView, ApprovalsSidebar, MonacoEditorPanel, TerminalPanel, PerformanceView, SettingsView, WorkersView, FilesView, LogsView

## Connection architecture
- Connects to the MARK Python FastAPI server (separate process, NOT part of this artifact)
- Server URL stored in localStorage under key `mark_server_url`, default `http://localhost:8000`
- WebSocket: `<serverUrl>/ws` — auto-reconnects on disconnect
- REST calls go directly to the server URL (not proxied through Vite)

## Why no Vite proxy
The MARK server is a user-started Python process on a configurable port. Proxying through Vite would hardcode the port and break when the user changes the server URL in Settings. Direct client-side connection with configurable URL is the correct pattern here.

## Packages added to scaffold
- `zustand` — state management
- `@monaco-editor/react` — file/diff viewing
- `@xterm/xterm` + `@xterm/addon-fit` — read-only terminal panel (StreamingToken events)

## Design
- Blueprint / Industrial UI aesthetic
- Dark background (hsl 220 20% 6%), electric indigo/cyan accents (hsl 250 85% 65%)
- Spline Sans Mono for data/code, Inter for UI text
- framer-motion animations on worker pipeline nodes and approval cards
