/** Download the share-safe support bundle without using the JSON API client. */
export async function downloadSupportBundle(): Promise<void> {
  const response = await fetch("/api/v1/support/bundle")
  if (!response.ok) {
    throw new Error("Failed to create support bundle")
  }

  const disposition = response.headers.get("Content-Disposition")
  const filename = disposition?.match(/filename="?([^";]+)"?/)?.[1] ?? "teamarr-support.zip"
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement("a")
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}
