import { useMarkStore } from '@/store/markStore';
import { motion, AnimatePresence } from 'framer-motion';
import { Button } from '@/components/ui/button';
import { Shield, ShieldAlert, Check, X, FileDiff, AlertTriangle, GitCommit } from 'lucide-react';

export function ApprovalsSidebar() {
  const { pendingPermissions, approve, deny, lastError } = useMarkStore();

  return (
    <div className="h-full flex flex-col bg-card overflow-hidden">
      <div className="h-12 border-b border-border/50 flex items-center px-4 font-semibold text-sm shrink-0">
        Actions & Approvals
        {pendingPermissions.length > 0 && (
          <span className="ml-2 bg-accent text-accent-foreground text-xs px-2 py-0.5 rounded-full font-mono">
            {pendingPermissions.length}
          </span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-4">
        {lastError && (
          <motion.div 
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-lg border border-destructive/20 bg-destructive/5 p-3 flex flex-col gap-2"
          >
            <div className="flex items-center gap-2 text-destructive font-medium text-sm">
              <AlertTriangle className="w-4 h-4" />
              Runtime Error
            </div>
            <div className="text-xs text-muted-foreground font-mono whitespace-pre-wrap break-all">
              {lastError}
            </div>
          </motion.div>
        )}

        <AnimatePresence>
          {pendingPermissions.map((req) => (
            <motion.div
              key={req.request_id}
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95, height: 0, marginBottom: 0 }}
              className="rounded-xl border border-amber-500/30 bg-card shadow-sm overflow-hidden"
            >
              <div className="bg-amber-500/10 px-3 py-2 flex items-center gap-2 border-b border-amber-500/20">
                <ShieldAlert className="w-4 h-4 text-amber-500" />
                <span className="text-xs font-semibold text-amber-600 dark:text-amber-400 uppercase tracking-wider">
                  Permission Required
                </span>
              </div>
              
              <div className="p-3 flex flex-col gap-3">
                <div>
                  <div className="text-xs text-muted-foreground uppercase font-semibold mb-1">Operation</div>
                  <div className="text-sm font-mono bg-muted/50 px-2 py-1 rounded inline-block">
                    {req.operation}
                  </div>
                </div>

                <div>
                  <div className="text-xs text-muted-foreground uppercase font-semibold mb-1">Target</div>
                  <div className="text-xs font-mono break-all text-foreground">
                    {req.path}
                  </div>
                </div>

                {req.diff && (
                  <div>
                    <div className="text-xs text-muted-foreground uppercase font-semibold mb-1 flex items-center gap-1">
                      <FileDiff className="w-3 h-3" /> Diff Preview
                    </div>
                    <div className="text-[10px] font-mono bg-muted/50 p-2 rounded max-h-32 overflow-y-auto whitespace-pre">
                      {req.diff}
                    </div>
                  </div>
                )}

                <div className="grid grid-cols-2 gap-2 mt-1">
                  <Button 
                    size="sm" 
                    variant="outline" 
                    onClick={() => deny(req.request_id)}
                    className="text-xs h-8 border-destructive/20 hover:bg-destructive/10 hover:text-destructive"
                  >
                    <X className="w-3 h-3 mr-1" /> Reject
                  </Button>
                  <Button 
                    size="sm" 
                    onClick={() => approve(req.request_id, false)}
                    className="text-xs h-8 bg-amber-500 hover:bg-amber-600 text-white"
                  >
                    <Check className="w-3 h-3 mr-1" /> Approve
                  </Button>
                  <Button 
                    size="sm" 
                    variant="outline"
                    onClick={() => approve(req.request_id, true)}
                    className="col-span-2 text-xs h-8"
                  >
                    <Shield className="w-3 h-3 mr-1 text-muted-foreground" /> Always Approve
                  </Button>
                </div>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>

        {pendingPermissions.length === 0 && !lastError && (
          <div className="flex flex-col items-center justify-center text-center p-8 h-full opacity-50">
            <Shield className="w-12 h-12 text-muted-foreground mb-4 opacity-20" />
            <p className="text-sm text-muted-foreground">No pending actions</p>
            <p className="text-xs text-muted-foreground mt-1">Elena is running autonomously</p>
          </div>
        )}
      </div>
    </div>
  );
}