/** IANA zone ids that map to India Standard Time. */
const INDIA_TIMEZONES = ["Asia/Kolkata", "Asia/Calcutta"];

/**
 * True when the user's browser timezone resolves to India. Used to skip the
 * "You're ready" onboarding-session finale (the Calendly CTA) for Indian
 * users. Best-effort: falls back to false if Intl is unavailable.
 */
export function isIndiaTimezone(): boolean {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return INDIA_TIMEZONES.includes(tz);
  } catch {
    return false;
  }
}
