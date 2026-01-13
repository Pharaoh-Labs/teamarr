import { BrowserRouter, Routes, Route } from "react-router-dom"
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query"
import { MainLayout } from "@/layouts/MainLayout"
import { GenerationProvider } from "@/contexts/GenerationContext"
import { StartupOverlay } from "@/components/StartupOverlay"
import {
  Dashboard,
  Templates,
  TemplateForm,
  Teams,
  TeamImport,
  EventGroups,
  EventGroupForm,
  EventGroupImport,
  EPG,
  Channels,
  Settings,
  V1UpgradePage,
} from "@/pages"

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60, // 1 minute
      retry: 1,
    },
  },
})

interface MigrationStatus {
  is_v1_database: boolean
  has_archived_backup: boolean
  database_path: string
  backup_path: string | null
}

async function fetchMigrationStatus(): Promise<MigrationStatus> {
  const response = await fetch("/api/v1/migration/status")
  if (!response.ok) {
    throw new Error("Failed to fetch migration status")
  }
  return response.json()
}

function AppContent() {
  const { data: migrationStatus, isLoading } = useQuery({
    queryKey: ["migration-status"],
    queryFn: fetchMigrationStatus,
    retry: false,
    staleTime: Infinity, // Only check once per session
  })

  // Show V1 upgrade page if V1 database detected
  if (!isLoading && migrationStatus?.is_v1_database) {
    return <V1UpgradePage />
  }

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
            <Route path="epg" element={<EPG />} />
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
