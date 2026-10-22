/** A time in the given IANA zone with its abbreviation, e.g. "Thu, 3:25 PM CDT". */
export function formatInZone(isoUtc: string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-US", {
    timeZone,
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(new Date(isoUtc));
}

export function formatDuration(seconds: number): string {
  const totalMinutes = Math.round(seconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours ? `${hours} h ${minutes.toString().padStart(2, "0")} min` : `${minutes} min`;
}

export function formatMiles(miles: number): string {
  return `${miles.toLocaleString("en-US", { maximumFractionDigits: 1 })} mi`;
}

/** "-0500" → "UTC−05:00" */
export function formatOffset(offset: string): string {
  const match = /^([+-])(\d{2})(\d{2})$/.exec(offset);
  if (!match) return offset;
  return `UTC${match[1] === "-" ? "−" : "+"}${match[2]}:${match[3]}`;
}
