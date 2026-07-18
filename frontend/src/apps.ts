export type AppStatus = "live" | "dev" | "planned";

export interface AppEntry {
  name: string;
  description: string;
  status: AppStatus;
  href?: string;
}

export const APPS: AppEntry[] = [
  {
    name: "Treachery",
    description:
      "Hidden-role Commander variant — deal secret identities, unveil, betray your friends. A homegrown take on mtgtreachery.net.",
    status: "live",
    href: "/treachery",
  },
  {
    name: "Oracle Draw",
    description: "Random card from Scryfall. The pipeline hello-world, kept around because it's fun.",
    status: "live",
  },
];
