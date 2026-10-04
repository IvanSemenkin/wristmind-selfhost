import { createContext, useContext, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import type { Mode } from '@/types';
import { NewChatDialog } from '@/pages/chats/NewChatDialog';
import { UploadSourceDialog } from '@/pages/knowledge/UploadSourceDialog';
import { ModeFormDialog } from '@/pages/modes/ModeFormDialog';

interface QuickActionsValue {
  /** Opens the "new chat" flow, optionally pinned to a mode. */
  newChat: (modeId?: string | null) => void;
  /** Opens the mode form; pass a mode to edit it. */
  editMode: (mode: Mode) => void;
  createMode: () => void;
  uploadSource: (modeId?: string | null) => void;
  openCommandPalette: () => void;
}

const QuickActionsContext = createContext<QuickActionsValue | null>(null);

export function useQuickActions(): QuickActionsValue {
  const context = useContext(QuickActionsContext);
  if (!context) throw new Error('useQuickActions должен использоваться внутри QuickActionsProvider');
  return context;
}

/**
 * Hosts the globally reachable creation flows. Any screen can open them without
 * duplicating dialog state, which keeps "create" always one click away.
 */
export function QuickActionsProvider({
  children,
  onCommandPaletteOpenChange,
}: {
  children: ReactNode;
  onCommandPaletteOpenChange: (open: boolean) => void;
}) {
  const [chatDialog, setChatDialog] = useState<{ open: boolean; modeId: string | null }>({
    open: false,
    modeId: null,
  });
  const [modeDialog, setModeDialog] = useState<{ open: boolean; mode: Mode | null }>({
    open: false,
    mode: null,
  });
  const [uploadDialog, setUploadDialog] = useState<{ open: boolean; modeId: string | null }>({
    open: false,
    modeId: null,
  });

  const value = useMemo<QuickActionsValue>(
    () => ({
      newChat: (modeId = null) => setChatDialog({ open: true, modeId }),
      createMode: () => setModeDialog({ open: true, mode: null }),
      editMode: (mode) => setModeDialog({ open: true, mode }),
      uploadSource: (modeId = null) => setUploadDialog({ open: true, modeId }),
      openCommandPalette: () => onCommandPaletteOpenChange(true),
    }),
    [onCommandPaletteOpenChange],
  );

  return (
    <QuickActionsContext.Provider value={value}>
      {children}
      <NewChatDialog
        open={chatDialog.open}
        initialModeId={chatDialog.modeId}
        onClose={() => setChatDialog((s) => ({ ...s, open: false }))}
      />
      <ModeFormDialog
        open={modeDialog.open}
        mode={modeDialog.mode}
        onClose={() => setModeDialog((s) => ({ ...s, open: false }))}
      />
      <UploadSourceDialog
        open={uploadDialog.open}
        initialModeId={uploadDialog.modeId}
        onClose={() => setUploadDialog((s) => ({ ...s, open: false }))}
      />
    </QuickActionsContext.Provider>
  );
}
