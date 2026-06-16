import { Outlet } from "react-router-dom"
import { EpgSubNav } from "@/components/EpgSubNav"

export function EpgLayout() {
  return (
    <div className="space-y-3">
      <h1 className="text-xl font-bold">EPG</h1>
      <EpgSubNav />
      <Outlet />
    </div>
  )
}
