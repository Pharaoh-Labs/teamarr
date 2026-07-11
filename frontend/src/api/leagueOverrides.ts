/**
 * Gracenote category overrides (#371).
 *
 * User overrides for the {gracenote_category} template variable. They live
 * in their own table so the leagues seed (whole-row INSERT OR REPLACE on
 * every startup) can't wipe them, and they win over the curated value.
 */
import { api } from "./client"

export interface GracenoteOverride {
  league_code: string
  gracenote_category: string
  /** The curated/derived value that clearing the override restores. */
  default: string
}

export interface GracenoteCategoryState {
  league_code: string
  override: string | null
  default: string
  effective: string
}

export function listGracenoteOverrides(): Promise<{ overrides: GracenoteOverride[] }> {
  return api.get("/leagues/overrides/gracenote")
}

export function getGracenoteCategory(leagueCode: string): Promise<GracenoteCategoryState> {
  return api.get(`/leagues/${encodeURIComponent(leagueCode)}/gracenote-category`)
}

/** Null/empty value clears the override back to the default. */
export function putGracenoteCategory(
  leagueCode: string,
  value: string | null,
): Promise<GracenoteCategoryState> {
  return api.put(`/leagues/${encodeURIComponent(leagueCode)}/gracenote-category`, { value })
}
