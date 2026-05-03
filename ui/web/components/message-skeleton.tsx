/**
 * Three-line pulsing placeholder shown in the assistant slot while we're
 * waiting for the first token to arrive. Replaces the "Thinking…" dot
 * once the user has submitted but the stream hasn't started returning
 * prose yet.
 *
 * The widths (60% / 80% / 50%) are deliberate — uneven widths read as
 * "text is forming" rather than a uniform loading bar.
 */
export function MessageSkeleton() {
  return (
    <div
      className="flex flex-col gap-2.5 py-1"
      role="status"
      aria-label="Assistant is preparing a response"
    >
      <div className="h-3 w-3/5 animate-pulse rounded-full bg-gray-200" />
      <div className="h-3 w-4/5 animate-pulse rounded-full bg-gray-200" />
      <div className="h-3 w-2/5 animate-pulse rounded-full bg-gray-200" />
    </div>
  );
}
