/**
 * Template variable validation utilities.
 *
 * Validates template strings for:
 * 1. Invalid/unknown variables
 * 2. Suffixed variables in event templates (not allowed)
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
 * Extract all variable references from a template string.
 * Returns array of variable names (without braces).
 */
export function extractVariables(template: string): string[] {
  if (!template) return []
  const matches = template.match(/\{([^}]+)\}/g)
  if (!matches) return []
  return matches.map(m => m.slice(1, -1))
}

/**
 * Check if a variable name has a suffix (.next, .last).
 */
export function hasSuffix(varName: string): boolean {
  return varName.includes(".next") || varName.includes(".last")
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
