import { Outlet } from "react-router-dom"
import { ChannelsSubNav } from "@/components/ChannelsSubNav"

export function ChannelsLayout() {
  return (
    <div className="space-y-3">
      <h1 className="text-xl font-bold">Channels</h1>
      <ChannelsSubNav />
      <Outlet />
    </div>
  )
}
