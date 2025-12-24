import { BrowserRouter, Routes, Route } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MainLayout } from "@/layouts/MainLayout"
import { GenerationProvider } from "@/contexts/GenerationContext"
import {
  Dashboard,
  Templates,
  TemplateForm,
  Teams,
  TeamImport,
  TeamAliases,
  EventGroups,
  EventGroupForm,
  EventGroupImport,
  EPG,
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

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <GenerationProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<MainLayout />}>
            <Route index element={<Dashboard />} />
            <Route path="templates" element={<Templates />} />
            <Route path="templates/new" element={<TemplateForm />} />
            <Route path="templates/:templateId" element={<TemplateForm />} />
            <Route path="teams" element={<Teams />} />
            <Route path="teams/import" element={<TeamImport />} />
            <Route path="teams/aliases" element={<TeamAliases />} />
            <Route path="event-groups" element={<EventGroups />} />
            <Route path="event-groups/new" element={<EventGroupForm />} />
            <Route path="event-groups/:groupId" element={<EventGroupForm />} />
            <Route path="event-groups/import" element={<EventGroupImport />} />
            <Route path="epg" element={<EPG />} />
            <Route path="channels" element={<Channels />} />
            <Route path="settings" element={<Settings />} />
          </Route>
        </Routes>
      </BrowserRouter>
      </GenerationProvider>
    </QueryClientProvider>
  )
}

export default App
