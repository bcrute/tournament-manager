export type AppStatus = "live" | "dev" | "planned";

export interface AppEntry {
  name: string;
  description: string;
  status: AppStatus;
  href?: string;
}

export const APPS: AppEntry[] = [
  {
    name: "Table",
    description:
      "Game-night companion — shared life tracker with a central table display, plus Treachery mode: secret identities, unveiling, betrayal.",
    status: "live",
    href: "/table",
  },
  {
    name: "Tournaments",
    description:
      "Run an event: roster, Swiss pods, seating, round timer and standings. Players scan one code and their phone follows them from table to table.",
    status: "live",
    href: "/tournament",
  },
];
