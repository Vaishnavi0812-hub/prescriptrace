import { useSyncExternalStore } from "react";

import { API_BASE } from "../api";
import { decodePack, type Knowledge, type OfflinePack } from "./pack";

/**
 * The offline pack on this device. Downloaded only when the user asks (about 1.5 MB). Kept in
 * the browser's Cache Storage (too big for localStorage); a small status record sits in
 * localStorage. It holds drug data only, never anything about a patient.
 */

const CACHE_NAME = "prescriptrace-offline-pack";
const PACK_URL = `${API_BASE}/api/v1/offline-pack`;
const INFO_KEY = "prescriptrace.offline.v1";

export interface OfflineInfo {
  version: string;
  generated_at: string;
  saved_at: string;
}

export interface PackMeta {
  version: string;
  generated_at: string;
  download_bytes: number;
  raw_bytes: number;
}

export const offlineSupported = (): boolean => typeof caches !== "undefined";

function readInfo(): OfflineInfo | null {
  try {
    const raw = localStorage.getItem(INFO_KEY);
    return raw ? (JSON.parse(raw) as OfflineInfo) : null;
  } catch {
    return null;
  }
}

let info: OfflineInfo | null = readInfo();
let knowledge: Promise<Knowledge | null> | null = null;
const listeners = new Set<() => void>();

function setInfo(next: OfflineInfo | null): void {
  info = next;
  try {
    if (next) localStorage.setItem(INFO_KEY, JSON.stringify(next));
    else localStorage.removeItem(INFO_KEY);
  } catch {
    // storage blocked: the pack still works until the page is closed
  }
  listeners.forEach((l) => l());
}

export function useOfflineInfo(): OfflineInfo | null {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => info,
  );
}

export async function fetchPackMeta(signal?: AbortSignal): Promise<PackMeta> {
  const response = await fetch(`${PACK_URL}/meta`, { signal });
  if (!response.ok) throw new Error(`offline pack unavailable (${response.status})`);
  return (await response.json()) as PackMeta;
}

export async function downloadPack(): Promise<OfflineInfo> {
  if (!offlineSupported()) throw new Error("This browser cannot store data for offline use.");
  const response = await fetch(PACK_URL);
  if (!response.ok) throw new Error(`offline pack unavailable (${response.status})`);
  const text = await response.text();
  const pack = JSON.parse(text) as OfflinePack;
  const kb = decodePack(pack); // validates before anything is stored
  const cache = await caches.open(CACHE_NAME);
  await cache.put(PACK_URL, new Response(text, { headers: { "Content-Type": "application/json" } }));
  knowledge = Promise.resolve(kb);
  const saved = { version: pack.version, generated_at: pack.generated_at, saved_at: new Date().toISOString() };
  setInfo(saved);
  return saved;
}

export async function removePack(): Promise<void> {
  if (offlineSupported()) await caches.delete(CACHE_NAME);
  knowledge = null;
  setInfo(null);
}

/** The stored pack, decoded once per page load; null when none is stored (or it is unreadable). */
export function loadKnowledge(): Promise<Knowledge | null> {
  if (!info || !offlineSupported()) return Promise.resolve(null);
  knowledge ??= (async () => {
    try {
      const response = await caches.match(PACK_URL, { cacheName: CACHE_NAME });
      if (!response) {
        setInfo(null);
        return null;
      }
      return decodePack((await response.json()) as OfflinePack);
    } catch {
      return null;
    }
  })();
  return knowledge;
}

/** A failed request that never reached the server (as opposed to an error response). */
export const isNetworkError = (error: unknown): boolean =>
  error instanceof TypeError || (typeof navigator !== "undefined" && navigator.onLine === false);
