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
    name: "Oracle Draw",
    description: "Random card from Scryfall. The pipeline hello-world, kept around because it's fun.",
    status: "live",
  },
];
