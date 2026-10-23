import { Outlet } from "react-router"
import { SourcesSubNav } from "@/components/SourcesSubNav"

export function SourcesLayout() {
  return (
    <div className="space-y-3">
      <h1 className="text-xl font-bold">Sources</h1>
      <SourcesSubNav />
      <Outlet />
    </div>
  )
}
