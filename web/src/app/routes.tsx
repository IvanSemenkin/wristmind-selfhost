import { TalkPage } from '@/pages/talk/TalkPage';
import type { RouteDefinition } from './router';
import { OverviewPage } from '@/pages/overview/OverviewPage';
import { ChatsPage } from '@/pages/chats/ChatsPage';
import { ModesPage } from '@/pages/modes/ModesPage';
import { ModeDetailPage } from '@/pages/modes/ModeDetailPage';
import { KnowledgePage } from '@/pages/knowledge/KnowledgePage';
import { SourceDetailPage } from '@/pages/knowledge/SourceDetailPage';
import { DevicesPage } from '@/pages/devices/DevicesPage';
import { SettingsPage } from '@/pages/settings/SettingsPage';
import { PromptsPage } from '@/pages/prompts/PromptsPage';

/* =============================================================================
   Route table.

   Paths mirror the URLs the production WristMind shell exposes:

     /main                 dashboard
     /chats                chat list
     /chats/new            new chat flow
     /chats/:chatId        a conversation
     /modes                modes
     /modes/:modeId        mode detail (tabs for chats / knowledge / settings)
     /knowledge            knowledge base
     /knowledge/sources/:sourceId
     /devices              connected devices & pairing
     /settings             console settings

   Porting to another router means translating this table and nothing else.
   ========================================================================== */

export const ROUTES: RouteDefinition[] = [
  { path: '/', redirect: '/main' },
  { path: '/talk', render: () => <TalkPage /> },
  { path: '/talk/history', render: () => <TalkPage history /> },
  { path: '/talk/:chatId', render: () => <TalkPage /> },
  { path: '/main', render: () => <OverviewPage /> },

  { path: '/chats', render: () => <ChatsPage /> },
  { path: '/chats/new', render: () => <ChatsPage /> },
  { path: '/chats/:chatId', render: (params) => <ChatsPage key={params.chatId} /> },

  { path: '/modes', render: () => <ModesPage /> },
  { path: '/modes/:modeId', render: (params) => <ModeDetailPage key={params.modeId} /> },

  { path: '/knowledge', render: () => <KnowledgePage /> },
  {
    path: '/knowledge/sources/:sourceId',
    render: (params) => <SourceDetailPage key={params.sourceId} />,
  },

  { path: '/devices', render: () => <DevicesPage /> },
  { path: '/settings', render: () => <SettingsPage /> },
  { path: '/prompts', render: () => <PromptsPage /> },
];
