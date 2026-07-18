export interface CardInfo {
  id: number;
  name: string;
  role: string;
  rarity: string;
  text: string;
  uri: string;
  image: string;
}

export interface PlayerInfo {
  name: string;
  isHost: boolean;
  revealed: boolean;
  left: boolean;
  isMe: boolean;
  card: CardInfo | null;
}

export type RoomStatus = "lobby" | "dealt" | "ended";

export interface RoomState {
  room: {
    code: string;
    status: RoomStatus;
    options: { rarities?: string[] };
    distribution: Record<string, number>;
  };
  players: PlayerInfo[];
  me: {
    name: string;
    isHost: boolean;
    revealed: boolean;
    card: CardInfo | null;
  };
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const BASE = "/api/treachery";

export async function api<T>(
  path: string,
  opts: { method?: string; token?: string; body?: unknown } = {},
): Promise<T> {
  const r = await fetch(BASE + path, {
    method: opts.method ?? "GET",
    headers: {
      ...(opts.body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(opts.token ? { "X-Player-Token": opts.token } : {}),
    },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (!r.ok) {
    const detail = await r
      .json()
      .then((d: { detail?: string }) => d.detail)
      .catch(() => undefined);
    throw new ApiError(r.status, detail ?? r.statusText);
  }
  return r.json() as Promise<T>;
}
