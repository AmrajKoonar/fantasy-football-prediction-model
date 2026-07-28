import { readFile } from "node:fs/promises";
import path from "node:path";
import {
  MetadataSchema,
  ModelPerformanceSchema,
  ProjectionsFileSchema,
  RankingsFileSchema,
  SCHEMA_VERSION,
  type ExportMetadata,
  type PlayerProjection,
  type RankingEntry,
} from "./schemas";

const dataDir = path.join(process.cwd(), "public", "data");

async function readJson(name: string): Promise<unknown | null> {
  try {
    const raw = await readFile(path.join(dataDir, name), "utf8");
    return JSON.parse(raw) as unknown;
  } catch {
    return null;
  }
}

export async function loadMetadata(): Promise<ExportMetadata | null> {
  const raw = await readJson("metadata.json");
  if (!raw) return null;
  const parsed = MetadataSchema.safeParse(raw);
  return parsed.success ? parsed.data : null;
}

export async function loadProjections(): Promise<{
  players: PlayerProjection[];
  schemaMismatch: boolean;
  dataMode: "production" | "fixture" | null;
}> {
  const raw = await readJson("projections.json");
  if (!raw) return { players: [], schemaMismatch: false, dataMode: null };
  const parsed = ProjectionsFileSchema.safeParse(raw);
  if (!parsed.success) {
    return { players: [], schemaMismatch: true, dataMode: null };
  }
  return {
    players: parsed.data.players,
    schemaMismatch: parsed.data.schemaVersion !== SCHEMA_VERSION,
    dataMode: parsed.data.dataMode,
  };
}

export async function loadRankings(): Promise<RankingEntry[]> {
  const raw = await readJson("rankings.json");
  if (!raw) return [];
  const parsed = RankingsFileSchema.safeParse(raw);
  return parsed.success ? parsed.data.entries : [];
}

export async function loadPlayerBySlug(slug: string): Promise<PlayerProjection | null> {
  const { players } = await loadProjections();
  return players.find((player) => player.slug === slug) ?? null;
}

export async function loadPerformance() {
  const raw = await readJson("model-performance.json");
  if (!raw) return null;
  const parsed = ModelPerformanceSchema.safeParse(raw);
  return parsed.success ? parsed.data : null;
}
