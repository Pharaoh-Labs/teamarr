import { useNavigate } from "react-router"
import { ArrowRight, Circle, CircleCheckBig, Rocket } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useDismissGettingStarted, useSetupStatus } from "@/hooks/useSetup"
import type { SetupStatus } from "@/api/setup"

interface Step {
  n: number
  title: string
  hint: string
  to: string
  done: (s: SetupStatus) => boolean
  detail?: (s: SetupStatus) => string | null
}

/**
 * The six steps match the numbered nav items (Settings is step 0). Each one
 * reads a fact the backend already knows; nothing here guesses.
 */
const STEPS: Step[] = [
  {
    n: 0,
    title: "Connect Dispatcharr",
    hint: "Enter the Dispatcharr URL and credentials, then test the connection.",
    to: "/settings?tab=dispatcharr",
    done: (s) => s.dispatcharr_connected,
    detail: (s) =>
      s.dispatcharr_configured && !s.dispatcharr_connected ? "Configured but not reachable" : null,
  },
  {
    n: 1,
    title: "Add a source",
    hint: "Pick one M3U group from Dispatcharr that carries live sports streams.",
    to: "/sources",
    done: (s) => s.sources > 0,
    detail: (s) => (s.sources > 0 ? `${s.sources} source${s.sources === 1 ? "" : "s"}` : null),
  },
  {
    n: 2,
    title: "Subscribe to leagues",
    hint: "Choose the leagues you want channels for. One or two is plenty to start.",
    to: "/subscriptions",
    done: (s) => s.leagues > 0,
    detail: (s) => (s.leagues > 0 ? `${s.leagues} league${s.leagues === 1 ? "" : "s"}` : null),
  },
  {
    n: 3,
    title: "Check matching",
    hint: "After a generation, see which streams matched a game and why the rest did not.",
    to: "/matching",
    done: (s) => s.streams_matched > 0,
    detail: (s) => (s.streams_matched > 0 ? `${s.streams_matched} streams matched` : null),
  },
  {
    n: 4,
    title: "Generate the EPG",
    hint: "Run the first generation. It matches streams, creates channels and builds the guide.",
    to: "/epg",
    done: (s) => s.runs_completed > 0,
    detail: (s) => (s.runs_completed > 0 ? "First run completed" : null),
  },
  {
    n: 5,
    title: "See your channels",
    hint: "The channels Teamarr created in Dispatcharr, with their streams and guide.",
    to: "/channels",
    done: (s) => s.channels_active > 0,
    detail: (s) => (s.channels_active > 0 ? `${s.channels_active} active` : null),
  },
]

/**
 * Getting Started card for the Dashboard (#818). Shown only while an install
 * is still setting up: it disappears on its own once a generation has
 * created a channel, or when the user dismisses it (a per-install setting).
 */
export function GettingStarted() {
  const { data: status } = useSetupStatus()
  const dismiss = useDismissGettingStarted()
  const navigate = useNavigate()

  if (!status?.visible) return null

  const next = STEPS.find((step) => !step.done(status))

  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-semibold">
            <Rocket className="h-4 w-4" />
            Getting Started
          </h2>
          <p className="text-sm text-muted-foreground">
            Six steps to your first guide. They match the numbers on the menu above; this list
            ticks itself off as you go and disappears when you are done.
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="shrink-0 text-muted-foreground"
          onClick={() => dismiss.mutate()}
          disabled={dismiss.isPending}
        >
          Dismiss
        </Button>
      </div>

      <ol className="mt-3 divide-y">
        {STEPS.map((step) => {
          const done = step.done(status)
          const isNext = next?.n === step.n
          const detail = step.detail?.(status)
          return (
            <li key={step.n} className="flex items-center gap-3 py-2">
              {done ? (
                <CircleCheckBig className="h-5 w-5 shrink-0 text-emerald-500" />
              ) : (
                <Circle
                  className={`h-5 w-5 shrink-0 ${isNext ? "text-primary" : "text-muted-foreground/50"}`}
                />
              )}
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span
                    className={`text-sm font-medium ${done ? "text-muted-foreground line-through" : ""}`}
                  >
                    {step.n}. {step.title}
                  </span>
                  {detail && <span className="text-xs text-muted-foreground">{detail}</span>}
                </div>
                {!done && <p className="text-xs text-muted-foreground">{step.hint}</p>}
              </div>
              {!done && (
                <Button
                  variant={isNext ? "default" : "outline"}
                  size="sm"
                  onClick={() => navigate(step.to)}
                >
                  {isNext ? "Start" : "Open"}
                  <ArrowRight className="ml-1 h-3.5 w-3.5" />
                </Button>
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}
