import { BrowserRouter, Routes, Route } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MainLayout } from "@/layouts/MainLayout"
import { GenerationProvider } from "@/contexts/GenerationContext"
import { StartupOverlay } from "@/components/StartupOverlay"
import {
  Dashboard,
  DetectionLibrary,
  Templates,
  TemplateForm,
  Teams,
  TeamImport,
  EventGroups,
  EventGroupForm,
  EventGroupImport,
  EPG,
  EPGSources,
  Channels,
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

function AppContent() {
  return (
    <>
      <StartupOverlay />
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<MainLayout />}>
            <Route index element={<Dashboard />} />
            <Route path="templates" element={<Templates />} />
            <Route path="templates/new" element={<TemplateForm />} />
            <Route path="templates/:templateId" element={<TemplateForm />} />
            <Route path="teams" element={<Teams />} />
            <Route path="teams/import" element={<TeamImport />} />
            <Route path="event-groups" element={<EventGroups />} />
            <Route path="event-groups/new" element={<EventGroupForm />} />
            <Route path="event-groups/:groupId" element={<EventGroupForm />} />
            <Route path="event-groups/import" element={<EventGroupImport />} />
            <Route path="detection-library" element={<DetectionLibrary />} />
            <Route path="epg" element={<EPG />} />
            <Route path="epg-sources" element={<EPGSources />} />
            <Route path="channels" element={<Channels />} />
            <Route path="settings" element={<Settings />} />
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
