import { useEffect, useMemo, useState } from "react"
import { AlertTriangle, ImageOff, Loader2 } from "lucide-react"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { validateTemplate } from "@/utils/templateValidation"
import { useEPGSettings } from "@/hooks/useSettings"
import type { TemplateFieldProps } from "./types"

// Default resolver that just returns the template unchanged
const defaultResolver = (template: string) => template

const ABSOLUTE_URL = /^[a-z][a-z0-9+.-]*:\/\//i

/**
 * Mirror of the backend apply_art_base_url (epic z02s): prefix a relative art
 * path with the configured base URL so the live preview matches generated EPG.
 * Absolute URLs and empty values pass through unchanged.
 */
function applyArtBase(value: string, base: string): string {
  if (!value || !base || ABSOLUTE_URL.test(value)) return value
  return `${base.replace(/\/+$/, "")}/${value.replace(/^\/+/, "")}`
}

// Debounce before the live image actually fetches — typing a URL would otherwise
// fire a request per keystroke and hit the game-thumbs rate limit / Cloudflare.
const IMAGE_PREVIEW_DEBOUNCE_MS = 700

function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(t)
  }, [value, delayMs])
  return debounced
}

// Fixed-size preview box so the layout never shifts between states.
const PREVIEW_BOX = "relative mt-1 flex h-28 w-44 items-center justify-center overflow-hidden rounded border border-border bg-muted/30"

/**
 * Live preview of an art/gamethumb URL — actually fetches and renders the image
 * so the user can confirm the resolved link works, in a fixed-size box with
 * explicit loading and broken-link states (a 200-shaped string preview alone
 * can't prove that). The error state uses the universally-understood broken-image
 * glyph. Keyed by url at the call site so it remounts fresh when the URL changes.
 */
function ImagePreview({ url }: { url: string }) {
  const [status, setStatus] = useState<"loading" | "ok" | "error">("loading")

  if (status === "error") {
    return (
      <div
        className={`${PREVIEW_BOX} flex-col gap-1 border-destructive/40 text-destructive`}
        title="Image failed to load — the URL doesn't resolve"
      >
        <ImageOff className="h-7 w-7" />
        <span className="text-[10px] font-medium">Bad URL</span>
      </div>
    )
  }

  return (
    <div className={PREVIEW_BOX}>
      {status === "loading" && (
        <Loader2 className="absolute left-1/2 top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 animate-spin text-muted-foreground" />
      )}
      <img
        src={url}
        alt="Art preview"
        onLoad={() => setStatus("ok")}
        onError={() => setStatus("error")}
        className="h-full w-full object-contain"
      />
    </div>
  )
}

export function TemplateField({
  id,
  label,
  value,
  onChange,
  placeholder,
  helpText,
  fieldRefs,
  setLastFocusedField,
  multiline = false,
  resolveTemplate = defaultResolver,
  validationData,
  isEventTemplate = false,
  isImageField = false,
}: TemplateFieldProps) {
  const preview = resolveTemplate(value)
  // Art fields: apply the game-thumbs base URL so the preview matches generated
  // EPG (templates now store relative paths — z02s).
  const { data: epgSettings } = useEPGSettings()
  const artBaseUrl = epgSettings?.art_base_url ?? ""
  const previewUrl = isImageField ? applyArtBase(preview, artBaseUrl) : preview
  // Debounced URL drives the actual <img> fetch (rate-limit / Cloudflare safety).
  const debouncedPreview = useDebounced(previewUrl, IMAGE_PREVIEW_DEBOUNCE_MS)
  // Only render a live image when the (base-applied) value is an absolute URL.
  const showImage = isImageField && /^https?:\/\//i.test(debouncedPreview)

  // Compute validation warnings
  const warnings = useMemo(() => {
    if (!validationData || !value) return []
    return validateTemplate(
      value,
      validationData.validNames,
      validationData.baseNames,
      isEventTemplate
    )
  }, [value, validationData, isEventTemplate])

  const hasWarnings = warnings.length > 0

  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      {multiline ? (
        <Textarea
          id={id}
          ref={(el) => {
            if (fieldRefs) fieldRefs.current[id] = el
          }}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onFocus={() => setLastFocusedField?.(id)}
          placeholder={placeholder}
          className={`font-mono text-sm min-h-[80px] ${hasWarnings ? "border-amber-500/50 focus:border-amber-500" : ""}`}
        />
      ) : (
        <Input
          id={id}
          ref={(el) => {
            if (fieldRefs) fieldRefs.current[id] = el
          }}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onFocus={() => setLastFocusedField?.(id)}
          placeholder={placeholder}
          className={`font-mono text-sm ${hasWarnings ? "border-amber-500/50 focus:border-amber-500" : ""}`}
        />
      )}
      {/* Validation Warnings */}
      {hasWarnings && (
        <div className="mt-1 px-2 py-1.5 bg-amber-500/10 border border-amber-500/30 rounded-sm">
          <div className="flex items-start gap-1.5">
            <AlertTriangle className="h-3.5 w-3.5 text-amber-500 flex-shrink-0 mt-0.5" />
            <div className="space-y-0.5">
              {warnings.map((w, i) => (
                <p key={i} className="text-xs text-amber-400">
                  {w.message}
                </p>
              ))}
            </div>
          </div>
        </div>
      )}
      {value && (
        <div className="mt-1 px-2 py-1 bg-secondary/50 border-l-2 border-primary rounded-sm">
          <span className="text-[10px] text-muted-foreground uppercase font-semibold mr-2">Preview:</span>
          <span className="text-sm italic break-all">{(isImageField ? previewUrl : preview) || "(empty)"}</span>
        </div>
      )}
      {showImage && <ImagePreview key={debouncedPreview} url={debouncedPreview} />}
      {helpText && <p className="text-xs text-muted-foreground">{helpText}</p>}
    </div>
  )
}
