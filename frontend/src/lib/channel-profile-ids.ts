/**
 * Convert selected IDs to API format.
 * - All profiles selected (no wildcards) → null (backend will use all)
 * - No selections at all → [] (no profiles)
 * - Any specific selections → those IDs/wildcards
 */
export function profileIdsToApi(
  selectedIds: (number | string)[],
  allProfileIds: number[]
): (number | string)[] | null {
  if (selectedIds.length === 0) {
    return [] // No profiles
  }

  // Separate numeric IDs from wildcards
  const numericIds = selectedIds.filter((x): x is number => typeof x === "number")
  const wildcardIds = selectedIds.filter((x): x is string => typeof x === "string")

  // Check if all profiles are selected AND no wildcards
  const selectedSet = new Set(numericIds)
  const allSelected = allProfileIds.length > 0 &&
    allProfileIds.every(id => selectedSet.has(id))

  // If all profiles selected with no wildcards, return null (meaning all)
  if (allSelected && wildcardIds.length === 0) {
    return null
  }

  return selectedIds
}

/**
 * Convert API format to selected IDs for display.
 * - null → select all profiles (no wildcards)
 * - [] → select none
 * - [...] → those specific IDs/wildcards
 */
export function apiToProfileIds(
  apiValue: (number | string)[] | null | undefined,
  allProfileIds: number[]
): (number | string)[] {
  if (apiValue === null || apiValue === undefined) {
    // null = all profiles (no wildcards)
    return [...allProfileIds]
  }
  if (apiValue.length === 1 && apiValue[0] === 0) {
    // [0] sentinel = all profiles (legacy format)
    return [...allProfileIds]
  }
  return apiValue
}
