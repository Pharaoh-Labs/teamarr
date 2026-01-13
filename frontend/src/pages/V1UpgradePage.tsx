/**
 * V1 to V2 Upgrade Landing Page
 *
 * Shown when a V1 database is detected. Offers users the choice to:
 * 1. Archive their V1 database and start fresh with V2
 * 2. Go back to V1 using the archived Docker tag
 */

import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import {
  AlertTriangle,
  Archive,
  ArrowLeft,
  CheckCircle2,
  Download,
  Loader2,
  Sparkles,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"

interface ArchiveResult {
  success: boolean
  message: string
  backup_path: string | null
}

async function archiveDatabase(): Promise<ArchiveResult> {
  const response = await fetch("/api/v1/migration/archive", {
    method: "POST",
  })
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || "Failed to archive database")
  }
  return response.json()
}

export function V1UpgradePage() {
  const queryClient = useQueryClient()
  const [archived, setArchived] = useState(false)

  const archiveMutation = useMutation({
    mutationFn: archiveDatabase,
    onSuccess: () => {
      setArchived(true)
      queryClient.invalidateQueries({ queryKey: ["migration-status"] })
    },
  })

  const handleDownloadBackup = () => {
    window.open("/api/v1/migration/download-backup", "_blank")
  }

  const handleRestart = () => {
    // Reload the page to trigger fresh V2 initialization
    window.location.reload()
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <div className="max-w-2xl w-full space-y-6">
        {/* Header */}
        <div className="text-center space-y-3">
          <div className="flex justify-center">
            <div className="h-16 w-16 rounded-full bg-primary/10 flex items-center justify-center">
              <Sparkles className="h-8 w-8 text-primary" />
            </div>
          </div>
          <h1 className="text-3xl font-bold">Welcome to Teamarr V2</h1>
          <p className="text-muted-foreground text-lg">
            We're excited you're upgrading to the next generation of Teamarr!
          </p>
        </div>

        {/* Notice Card */}
        <Card className="border-warning/50 bg-warning/5">
          <CardContent className="p-5">
            <div className="flex gap-4">
              <AlertTriangle className="h-6 w-6 text-warning shrink-0 mt-0.5" />
              <div className="space-y-2">
                <h2 className="font-semibold text-lg">V1 Database Detected</h2>
                <p className="text-muted-foreground text-sm leading-relaxed">
                  We've detected that your data directory contains a Teamarr V1
                  database. Unfortunately, <strong>there is no automatic migration
                  path</strong> from V1 to V2 due to significant architectural changes.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        {!archived ? (
          <>
            {/* Options */}
            <div className="space-y-3">
              <h3 className="font-medium text-center text-muted-foreground">
                Choose how you'd like to proceed:
              </h3>

              {/* Option 1: Start Fresh */}
              <Card className="hover:border-primary/50 transition-colors">
                <CardContent className="p-5">
                  <div className="flex gap-4">
                    <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                      <Archive className="h-5 w-5 text-primary" />
                    </div>
                    <div className="flex-1 space-y-3">
                      <div>
                        <h3 className="font-semibold">Start Fresh with V2</h3>
                        <p className="text-sm text-muted-foreground mt-1">
                          Archive your V1 database and begin with a clean V2 setup.
                          Your V1 data will be safely backed up and available for
                          download.
                        </p>
                      </div>
                      <ul className="text-xs text-muted-foreground space-y-1">
                        <li className="flex items-center gap-2">
                          <CheckCircle2 className="h-3.5 w-3.5 text-success" />
                          V1 database preserved as downloadable backup
                        </li>
                        <li className="flex items-center gap-2">
                          <CheckCircle2 className="h-3.5 w-3.5 text-success" />
                          Access all new V2 features and improvements
                        </li>
                        <li className="flex items-center gap-2">
                          <CheckCircle2 className="h-3.5 w-3.5 text-success" />
                          Reconfigure teams and templates from scratch
                        </li>
                      </ul>
                      <Button
                        onClick={() => archiveMutation.mutate()}
                        disabled={archiveMutation.isPending}
                        className="w-full"
                      >
                        {archiveMutation.isPending ? (
                          <>
                            <Loader2 className="h-4 w-4 animate-spin" />
                            Archiving...
                          </>
                        ) : (
                          <>
                            <Archive className="h-4 w-4" />
                            Archive V1 & Start Fresh
                          </>
                        )}
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* Option 2: Go Back to V1 */}
              <Card className="hover:border-secondary transition-colors">
                <CardContent className="p-5">
                  <div className="flex gap-4">
                    <div className="h-10 w-10 rounded-lg bg-secondary flex items-center justify-center shrink-0">
                      <ArrowLeft className="h-5 w-5 text-muted-foreground" />
                    </div>
                    <div className="flex-1 space-y-3">
                      <div>
                        <h3 className="font-semibold">Continue Using V1</h3>
                        <p className="text-sm text-muted-foreground mt-1">
                          If you're not ready to migrate, you can continue using
                          V1. Update your Docker compose file to use the archived
                          version tag.
                        </p>
                      </div>
                      <div className="bg-secondary/50 rounded-md p-3 font-mono text-xs">
                        <span className="text-muted-foreground">image:</span>{" "}
                        <span className="text-primary">ghcr.io/egyptiangio/teamarr:1.4.9-archive</span>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        Note: V1 will continue to function but will not receive
                        any future updates or bug fixes.
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>
          </>
        ) : (
          /* Success State */
          <Card className="border-success/50 bg-success/5">
            <CardContent className="p-6 text-center space-y-4">
              <div className="flex justify-center">
                <div className="h-12 w-12 rounded-full bg-success/10 flex items-center justify-center">
                  <CheckCircle2 className="h-6 w-6 text-success" />
                </div>
              </div>
              <div className="space-y-2">
                <h2 className="font-semibold text-lg">Database Archived Successfully</h2>
                <p className="text-sm text-muted-foreground">
                  Your V1 database has been safely archived. You can download a
                  copy for your records, then restart to initialize Teamarr V2.
                </p>
              </div>
              <div className="flex gap-3 justify-center pt-2">
                <Button variant="outline" onClick={handleDownloadBackup}>
                  <Download className="h-4 w-4" />
                  Download V1 Backup
                </Button>
                <Button onClick={handleRestart}>
                  <Sparkles className="h-4 w-4" />
                  Launch Teamarr V2
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Error State */}
        {archiveMutation.isError && (
          <Card className="border-destructive/50 bg-destructive/5">
            <CardContent className="p-4">
              <p className="text-sm text-destructive">
                {archiveMutation.error instanceof Error
                  ? archiveMutation.error.message
                  : "An error occurred while archiving the database"}
              </p>
            </CardContent>
          </Card>
        )}

        {/* Footer */}
        <p className="text-center text-xs text-muted-foreground">
          Questions or issues? Visit our{" "}
          <a
            href="https://github.com/egyptiangio/teamarr"
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary hover:underline"
          >
            GitHub repository
          </a>{" "}
          for documentation and support.
        </p>
      </div>
    </div>
  )
}
