/**
 * Client-side route paths. Norwegian, because the whole site is.
 *
 * The member "min side" is the site root (`/`) — no path suffix. `/login` and
 * `/auth/*` stay English on purpose: `/auth/*` is baked into links already sent
 * by email.
 */
export const ROUTES = {
  home: "/",
  members: "/medlemmer",
  memberDetail: (id: string | number) => `/medlemmer/${id}`,
  users: "/brukere",
  chargers: "/ladere",
  settlements: "/avregninger",
  settlementDetail: (id: string | number) => `/avregninger/${id}`,
  movements: "/bevegelser",
  audit: "/revisjonslogg",
  forecast: "/prognose",
  system: "/system",
  login: "/login",
} as const;

/** Paths (prefixes) that light up the "System" nav tab. */
export const SYSTEM_TAB_PATHS = [ROUTES.system, ROUTES.users, ROUTES.chargers];
