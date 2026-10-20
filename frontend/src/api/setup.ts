import { api } from "./client"

/** The six facts behind the Getting Started checklist (#818). */
export interface SetupStatus {
  dispatcharr_configured: boolean
  dispatcharr_connected: boolean
  sources: number
  leagues: number
  streams_matched: number
  runs_completed: number
  channels_active: number
  dismissed: boolean
  complete: boolean
  visible: boolean
}

export async function getSetupStatus(): Promise<SetupStatus> {
  return api.get("/setup/status")
}

export async function dismissGettingStarted(): Promise<{ dismissed: boolean }> {
  return api.post("/setup/getting-started/dismiss")
}

export async function restoreGettingStarted(): Promise<{ dismissed: boolean }> {
  return api.post("/setup/getting-started/restore")
}
