import { BrowserRouter, Routes, Route, Navigate, useParams, useLocation } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MainLayout } from "@/layouts/MainLayout"
import { EpgLayout } from "@/components/EpgLayout"
import { ChannelsLayout } from "@/components/ChannelsLayout"
import { ChannelLifecycle } from "@/pages/channels/ChannelLifecycle"
import { ChannelConsolidation } from "@/pages/channels/ChannelConsolidation"
import { ChannelNumbering } from "@/pages/channels/ChannelNumbering"
import { ChannelStreamPriority } from "@/pages/channels/ChannelStreamPriority"
import { ChannelDispatcharrOutput } from "@/pages/channels/ChannelDispatcharrOutput"
import { GenerationProvider } from "@/contexts/GenerationContext"
import { StartupOverlay } from "@/components/StartupOverlay"
import {
  Dashboard,
  Subscriptions,
  DetectionLibrary,
  Templates,
  TemplateForm,
  EpgOutput,
  Teams,
  TeamImport,
  EventGroups,
  EventGroupForm,
  EventGroupImport,
  Settings,
} from "@/pages"

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60, // 1 minute
      retry: 1,
    },
  },
})

/**
 * Redirect that forwards :params and the query string from the matched
 * (legacy) URL to its new home, so bookmarks and in-app navigate() calls to
 * old paths keep working after the v2.7.0 IA route rename.
 */
function Redirect({ to }: { to: string }) {
  const params = useParams()
  const { search } = useLocation()
  let path = to
  for (const [key, value] of Object.entries(params)) {
    path = path.replace(`:${key}`, value ?? "")
  }
  return <Navigate to={path + search} replace />
}

function AppContent() {
  return (
    <>
      <StartupOverlay />
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<MainLayout />}>
            <Route index element={<Dashboard />} />

            {/* ① Sources (was Event Groups) */}
            <Route path="sources" element={<EventGroups />} />
            <Route path="sources/new" element={<EventGroupForm />} />
            <Route path="sources/:groupId" element={<EventGroupForm />} />
            <Route path="sources/import" element={<EventGroupImport />} />

            {/* ② Subscriptions (Global Defaults + Custom Leagues) */}
            <Route path="subscriptions" element={<Subscriptions />} />
            <Route path="subscriptions/leagues" element={<Redirect to="/subscriptions" />} />

            {/* ③ Matching (was Detection Library) */}
            <Route path="matching" element={<DetectionLibrary />} />

            {/* ④ EPG — Templates (default, with assignments folded in) + Team EPG + EPG Output */}
            <Route path="epg" element={<Redirect to="/epg/templates" />} />
            {/* Editor pages are standalone full-screen (no EPG header/SubNav) */}
            <Route path="epg/templates/new" element={<TemplateForm />} />
            <Route path="epg/templates/:templateId" element={<TemplateForm />} />
            <Route path="epg/teams/import" element={<TeamImport />} />
            {/* SubNav views share the EPG layout (fixed "EPG" header + SubNav) */}
            <Route element={<EpgLayout />}>
              <Route path="epg/templates" element={<Templates />} />
              <Route path="epg/assignments" element={<Redirect to="/epg/templates" />} />
              <Route path="epg/teams" element={<Teams />} />
              <Route path="epg/output" element={<EpgOutput />} />
            </Route>

            {/* ⑤ Channels — Lifecycle + Consolidation + Numbering + Stream Priority + Dispatcharr Output */}
            <Route path="channels" element={<Redirect to="/channels/lifecycle" />} />
            <Route element={<ChannelsLayout />}>
              <Route path="channels/lifecycle" element={<ChannelLifecycle />} />
              <Route path="channels/consolidation" element={<ChannelConsolidation />} />
              <Route path="channels/numbering" element={<ChannelNumbering />} />
              <Route path="channels/stream-priority" element={<ChannelStreamPriority />} />
              <Route path="channels/output" element={<ChannelDispatcharrOutput />} />
            </Route>

            {/* Settings (system/integration) */}
            <Route path="settings" element={<Settings />} />

            {/* Legacy URL redirects — keep bookmarks & in-app links working */}
            <Route path="event-groups" element={<Redirect to="/sources" />} />
            <Route path="event-groups/new" element={<Redirect to="/sources/new" />} />
            <Route path="event-groups/:groupId" element={<Redirect to="/sources/:groupId" />} />
            <Route path="event-groups/import" element={<Redirect to="/sources/import" />} />
            <Route path="teams" element={<Redirect to="/epg/teams" />} />
            <Route path="teams/import" element={<Redirect to="/epg/teams/import" />} />
            <Route path="custom-leagues" element={<Redirect to="/subscriptions/leagues" />} />
            <Route path="detection-library" element={<Redirect to="/matching" />} />
            <Route path="templates" element={<Redirect to="/epg/templates" />} />
            <Route path="templates/new" element={<Redirect to="/epg/templates/new" />} />
            <Route path="templates/:templateId" element={<Redirect to="/epg/templates/:templateId" />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </>
  )
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <GenerationProvider>
        <AppContent />
      </GenerationProvider>
    </QueryClientProvider>
  )
}

export default App
