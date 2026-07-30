import { DraftPlayerPoolSchema } from "./validation";
import type { DraftPlayer } from "./types";

export async function loadDraftPlayerPool(): Promise<DraftPlayer[]> {
  const response = await fetch("/data/mock-draft-player-pool.json", { cache: "force-cache" });
  if (!response.ok) throw new Error("The mock-draft player pool is unavailable.");
  const parsed = DraftPlayerPoolSchema.safeParse(await response.json());
  if (!parsed.success) throw new Error("The mock-draft player pool failed validation.");
  return parsed.data.players;
}

