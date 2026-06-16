import { cn } from "@/lib/utils"

/**
 * RadioCards — a single-select group rendered as bordered, clickable option
 * cards (radio + bold label + optional description). Replaces the hand-rolled
 * `p-3 rounded-lg border-2 cursor-pointer` selectable-card pattern (e.g. the
 * Auto/Manual numbering toggle and the Consolidate/Separate mode toggle).
 */
export interface RadioCardOption<T extends string> {
  value: T
  label: string
  description?: string
}

export interface RadioCardsProps<T extends string> {
  value: T | undefined
  onChange: (value: T) => void
  options: RadioCardOption<T>[]
  /** Radio group name — must be unique on the page. */
  name: string
  /** Number of columns in the grid (1–3). Default 2. */
  columns?: 1 | 2 | 3
  className?: string
}

// Stack to a single column on phones, fan out at sm+ so cards don't cram.
const COLS: Record<number, string> = {
  1: "grid-cols-1",
  2: "grid-cols-1 sm:grid-cols-2",
  3: "grid-cols-1 sm:grid-cols-3",
}

export function RadioCards<T extends string>({
  value,
  onChange,
  options,
  name,
  columns = 2,
  className,
}: RadioCardsProps<T>) {
  return (
    <div className={cn("grid gap-3", COLS[columns], className)}>
      {options.map((opt) => {
        const selected = value === opt.value
        return (
          <label
            key={opt.value}
            className={cn(
              "flex flex-col p-3 rounded-lg border-2 cursor-pointer transition-colors",
              selected
                ? "border-primary bg-muted/30"
                : "border-border hover:border-muted-foreground/50"
            )}
          >
            <div className="flex items-center gap-2 mb-1">
              <input
                type="radio"
                name={name}
                value={opt.value}
                checked={selected}
                onChange={() => onChange(opt.value)}
                className="accent-primary"
              />
              <span className="font-medium text-sm">{opt.label}</span>
            </div>
            {opt.description && (
              <p className="text-xs text-muted-foreground leading-tight ml-5">
                {opt.description}
              </p>
            )}
          </label>
        )
      })}
    </div>
  )
}
