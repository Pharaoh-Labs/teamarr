import { api } from "./client"

// =============================================================================
// Types
// =============================================================================

export interface SportsSubscription {
  id: number
  leagues: string[]
  soccer_mode: 'all' | 'teams' | 'manual' | null
  soccer_followed_teams: Array<{
    provider: string
    team_id: string
    name?: string | null
  }> | null
  // (#997) leagues / sports for which source discovery adds sources on its own
  auto_source_leagues: string[]
  auto_source_sports: string[]
  updated_at: string | null
}

export interface SubscriptionUpdate {
  leagues?: string[]
  soccer_mode?: 'all' | 'teams' | 'manual' | null
  soccer_followed_teams?: Array<{
    provider: string
    team_id: string
    name?: string | null
  }> | null
  auto_source_leagues?: string[]
  auto_source_sports?: string[]
}

export interface SubscriptionTemplate {
  id: number
  template_id: number
  sports: string[] | null
  leagues: string[] | null
  template_name: string | null
}

export interface SubscriptionTemplateCreate {
  template_id: number
  sports?: string[] | null
  leagues?: string[] | null
}

export interface SubscriptionTemplateUpdate {
  template_id?: number
  sports?: string[] | null
  leagues?: string[] | null
}

export interface SubscriptionTemplateListResponse {
  templates: SubscriptionTemplate[]
  total: number
}

// =============================================================================
// Subscription API
// =============================================================================

export async function getSubscription(): Promise<SportsSubscription> {
  return api.get("/sports-subscription")
}

export async function updateSubscription(
  data: SubscriptionUpdate
): Promise<SportsSubscription> {
  return api.put("/sports-subscription", data)
}

// =============================================================================
// Subscription Templates API
// =============================================================================

export async function getSubscriptionTemplates(): Promise<SubscriptionTemplateListResponse> {
  return api.get("/subscription-templates")
}

export async function createSubscriptionTemplate(
  data: SubscriptionTemplateCreate
): Promise<SubscriptionTemplate> {
  return api.post("/subscription-templates", data)
}

export async function updateSubscriptionTemplate(
  assignmentId: number,
  data: SubscriptionTemplateUpdate
): Promise<SubscriptionTemplate> {
  return api.put(`/subscription-templates/${assignmentId}`, data)
}

export async function deleteSubscriptionTemplate(
  assignmentId: number
): Promise<void> {
  return api.delete(`/subscription-templates/${assignmentId}`)
}
