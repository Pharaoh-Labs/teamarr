/**
 * Template variable validation utilities.
 *
 * Validates template strings for:
 * 1. Invalid/unknown variables
 * 2. Suffixed variables in event templates (not allowed)
 *
 * Extraction mirrors the backend resolver's VARIABLE_PATTERN so the validator and
 * the engine agree on what counts as a variable — see VARIABLE_PATTERN below.
 */

import type { VariableCategory } from "@/api/variables"

export interface ValidationWarning {
  variable: string
  message: string
  type: "invalid" | "suffix_not_allowed"
}

export interface ValidationResult {
  isValid: boolean
  warnings: ValidationWarning[]
}

/**
 * Build a set of all valid variable names (with suffixes expanded).
 * Returns { validNames: Set of all valid full names, baseNames: Set of base names }
 */
export function buildValidVariableSet(categories: VariableCategory[]): {
  validNames: Set<string>
  baseNames: Set<string>
  variableSuffixes: Map<string, string[]>
} {
  const validNames = new Set<string>()
  const baseNames = new Set<string>()
  const variableSuffixes = new Map<string, string[]>()

  for (const category of categories) {
    for (const variable of category.variables) {
      baseNames.add(variable.name)
      variableSuffixes.set(variable.name, variable.suffixes)

      for (const suffix of variable.suffixes) {
        if (suffix === "base") {
          validNames.add(variable.name)
        } else {
          validNames.add(`${variable.name}${suffix}`)
        }
      }
    }
  }

  return { validNames, baseNames, variableSuffixes }
}

/**
 * Mirror of the backend resolver's VARIABLE_PATTERN (teamarr/templates/resolver.py).
 *
 * The engine only treats a braced token as a variable when it matches this shape:
 * a lowercase/underscore-led name (digits, `_`, `@` allowed — e.g. `vs_@`) with an
 * optional single dotted suffix. Anything else inside braces — `{2024}`, `{1-0}`,
 * `{Team Name}`, `{a.b.c}` — is literal text the resolver leaves untouched, so the
 * validator must ignore it too rather than cry "unknown variable". The backend
 * lowercases the captured name before lookup, so matching is case-insensitive.
 */
const VARIABLE_PATTERN = /\{([a-z_][a-z0-9_@]*(?:\.[a-z]+)?)\}/gi

/**
 * Extract variable references the engine would actually resolve, lowercased to
 * match the backend (which calls `.lower()` on each captured name).
 */
export function extractVariables(template: string): string[] {
  if (!template) return []
  const names: string[] = []
  for (const match of template.matchAll(VARIABLE_PATTERN)) {
    names.push(match[1].toLowerCase())
  }
  return names
}

/**
 * Check if a variable name ends with a real suffix (.next, .last). Anchored so it
 * only fires on a trailing suffix, not a substring (e.g. a name containing "next").
 */
export function hasSuffix(varName: string): boolean {
  return /\.(next|last)$/.test(varName)
}

/**
 * Validate a single template string.
 */
export function validateTemplate(
  template: string,
  validNames: Set<string>,
  baseNames: Set<string>,
  isEventTemplate: boolean
): ValidationWarning[] {
  const warnings: ValidationWarning[] = []
  const variables = extractVariables(template)

  for (const varName of variables) {
    // Check for suffixed variables in event templates
    if (isEventTemplate && hasSuffix(varName)) {
      // Extract base name to check if it's at least a known variable
      const baseName = varName.replace(/\.(next|last)$/, "")
      if (baseNames.has(baseName)) {
        warnings.push({
          variable: varName,
          message: `Suffixed variables like {${varName}} are not supported in event templates. Use {${baseName}} instead.`,
          type: "suffix_not_allowed",
        })
      } else {
        warnings.push({
          variable: varName,
          message: `Unknown variable: {${varName}}`,
          type: "invalid",
        })
      }
    }
    // Check if variable exists at all
    else if (!validNames.has(varName)) {
      // Check if it's a base name that exists but they used wrong suffix
      const baseName = varName.replace(/\.(next|last)$/, "")
      if (baseNames.has(baseName) && hasSuffix(varName)) {
        // Base name exists but this suffix combo is invalid
        warnings.push({
          variable: varName,
          message: `{${varName}} is not a valid suffix for this variable`,
          type: "invalid",
        })
      } else {
        warnings.push({
          variable: varName,
          message: `Unknown variable: {${varName}}`,
          type: "invalid",
        })
      }
    }
  }

  return warnings
}

/**
 * Validate multiple template fields and return combined warnings.
 */
export function validateTemplateFields(
  fields: Record<string, string | null | undefined>,
  validNames: Set<string>,
  baseNames: Set<string>,
  isEventTemplate: boolean
): Map<string, ValidationWarning[]> {
  const results = new Map<string, ValidationWarning[]>()

  for (const [fieldName, value] of Object.entries(fields)) {
    if (value) {
      const warnings = validateTemplate(value, validNames, baseNames, isEventTemplate)
      if (warnings.length > 0) {
        results.set(fieldName, warnings)
      }
    }
  }

  return results
}
