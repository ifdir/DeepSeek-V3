/** MATRIX10 Flask API client. Relative /api/... (Vite proxies to Flask except /api/auth|/api/rtc). */
import { BUILD_ID } from "@/lib/matrix/types";

export type ImportIdCompare = {
  preserved: boolean;
  remapped: unknown[];
  sourceIds?: Record<string, string[]>;
  targetIds?: Record<string, string[]>;
  missing?: Record<string, string[]>;
  skipped?: Record<string, string[]>;
  unresolved?: Record<string, string[]>;
  skippedBlocking?: Record<string, string[]>;
  notMigrated?: Record<string, string[]>;
  cutoverComplete?: boolean;
  cutoverStatus?: string;
};

export type ImportMccResult = {
  ok: boolean;
  sourceCounts?: Record<string, number | Record<string, unknown>>;
  targetCounts?: Record<string, number | Record<string, unknown>>;
  idCompare?: ImportIdCompare;
  classes?: Record<string, { source: number; target: number; action: string; notes?: string }>;
  warnings?: string[];
  error?: string;
  message?: string;
};

const ACTOR_SESSION_KEY = "matrix10.actor";
const ACTOR_LOCAL_KEY = "matrix10.actor";

export function rememberActor(actor: string): void {
  const a = (actor ?? "").trim();
  if (!a) return;
  try {
    if (typeof sessionStorage !== "undefined") sessionStorage.setItem(ACTOR_SESSION_KEY, a);
  } catch {
    /* ignore */
  }
  try {
    if (typeof localStorage !== "undefined") localStorage.setItem(ACTOR_LOCAL_KEY, a);
  } catch {
    /* ignore */
  }
}

export function readStoredActor(): string {
  try {
    if (typeof sessionStorage !== "undefined") {
      const s = (sessionStorage.getItem(ACTOR_SESSION_KEY) || "").trim();
      if (s) return s;
    }
  } catch {
    /* ignore */
  }
  try {
    if (typeof localStorage !== "undefined") {
      const s = (localStorage.getItem(ACTOR_LOCAL_KEY) || "").trim();
      if (s) return s;
    }
  } catch {
    /* ignore */
  }
  return "";
}

export function clearStoredActor(): void {
  try {
    if (typeof sessionStorage !== "undefined") sessionStorage.removeItem(ACTOR_SESSION_KEY);
  } catch {
    /* ignore */
  }
  try {
    if (typeof localStorage !== "undefined") localStorage.removeItem(ACTOR_LOCAL_KEY);
  } catch {
    /* ignore */
  }
}

export function actorHeader(actor?: string): Record<string, string> {
  let a = (actor ?? "").trim();
  if (!a) a = readStoredActor();
  if (!a) return {};
  return { "X-Matrix-Actor": a };
}

async function apiJson(path: string, init?: RequestInit): Promise<unknown> {
  const hasBody = init?.body !== undefined && init.body !== null;
  const r = await fetch(path, {
    ...init,
    headers: {
      // V65I (AMASTER §65): the server sees which app code the browser runs; a
      // different build is logged as CLIENT_BUILD (stale cached or open page).
      "X-Matrix-Client-Build": BUILD_ID,
      ...(hasBody ? { "Content-Type": "application/json" } : {}),
      ...actorHeader(),
      ...(init?.headers || {}),
    },
  });
  // Do not swallow AbortError while parsing a returned body: an aborted
  // POST cannot be treated as a successful empty server response.
  const data = (await r.json().catch((error) => {
    if (init?.signal?.aborted) throw error;
    return {};
  })) as { error?: string; message?: string; code?: string };
  if (!r.ok) {
    const code = data.code || data.error || "HTTP_ERROR";
    const reason = data.message && data.message !== code ? `${code}: ${data.message}` : code;
    // V92 Paket 16: the server's structured answer (e.g. the identity clarification) stays readable for the UI
    throw Object.assign(new Error(`${init?.method || "GET"} ${path} ${r.status} ${reason}`), { body: data });
  }
  return data;
}

// P22: only the ordinary figure Prepare/Commit chain uses these bounded
// waits. A client abort does NOT prove that a server-side write was undone.
// For a timed-out Commit the caller MUST read back by sourceTurnId and must
// NOT automatically retry a mutating POST.
async function boundedKernelJson(path: string, init: RequestInit, timeoutMs: number, timeoutCode: string): Promise<unknown> {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), timeoutMs);
  try {
    return await apiJson(path, { ...init, signal: abort.signal });
  } catch (error) {
    if (abort.signal.aborted) {
      throw Object.assign(new Error(
        `Zeitgrenze bei ${path} (${Math.round(timeoutMs / 1000)} s). ` +
        "Der Server kann den Auftrag noch bearbeiten oder bereits gespeichert haben. " +
        "Status erst rücklesen; denselben Auftrag nicht ungeprüft nochmals senden."
      ), { code: timeoutCode, statusUnknown: true, timeoutMs });
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

export async function apiAllocateIds(items: Array<{ tempId: string; prefix: string }>): Promise<Array<{ tempId: string; prefix: string; id: string }>> {
  const data = (await apiJson("/api/ids/allocate", {
    method: "POST",
    body: JSON.stringify({ items }),
  })) as { allocations?: Array<{ tempId: string; prefix: string; id: string }> };
  return data.allocations ?? [];
}

export async function apiHealth(): Promise<{
  ok: boolean;
  db: string;
  build: string;
  buildId?: string;
  sqlite?: boolean;
  secondMaster?: boolean;
  pgliteRunning?: boolean;
  neonRunning?: boolean;
  productStore?: string;
  authInfra?: string;
  identitaet?: { art?: string; anmeldung?: boolean; nurLokal?: boolean; hinweis?: string };
  llmKeyPresent?: boolean;
  llmProvider?: string;
  llmModel?: string;
}> {
  const r = await fetch("/api/health");
  if (!r.ok) throw new Error(`GET /api/health ${r.status}`);
  return r.json();
}

export async function apiGetMcc(actor?: string): Promise<Record<string, unknown>> {
  const r = await fetch("/api/mcc", { headers: { ...actorHeader(actor) } });
  if (!r.ok) {
    // Stand 06a (M3): keep the server's code and message readable, like apiJson - a 503 of the consent core is a
    // technical failure and must be shown as such, never as an empty data set.
    const data = (await r.json().catch(() => ({}))) as { error?: string; message?: string; code?: string };
    const code = data.code || data.error || "HTTP_ERROR";
    const reason = data.message && data.message !== code ? `${code}: ${data.message}` : code;
    throw Object.assign(new Error(`GET /api/mcc ${r.status} ${reason}`), { body: data, status: r.status });
  }
  return r.json();
}

export async function apiImportMcc(payload: unknown): Promise<ImportMccResult> {
  const r = await fetch("/api/import/mcc", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...actorHeader() },
    body: JSON.stringify(payload),
  });
  const data = (await r.json().catch(() => ({}))) as ImportMccResult;
  if (!r.ok) {
    return {
      ok: false,
      error: data.error || "IMPORT_FAILED",
      message: data.message,
      sourceCounts: data.sourceCounts,
      targetCounts: data.targetCounts,
      idCompare: data.idCompare,
      classes: data.classes,
      warnings: data.warnings,
    };
  }
  return data;
}

export async function apiCreateUser(body: unknown): Promise<unknown> {
  const id =
    body && typeof body === "object" && "id" in body ? String((body as { id?: string }).id || "").trim() : "";
  return apiJson("/api/users", {
    method: "POST",
    body: JSON.stringify(body),
    headers: id ? actorHeader(id) : actorHeader(),
  });
}
export async function apiListUserDirectory(): Promise<{ ok?: boolean; users?: Array<{ id: string; name: string }>; directory?: boolean }> {
  const r = await fetch("/api/users");
  const data = (await r.json().catch(() => ({}))) as {
    ok?: boolean;
    users?: Array<{ id: string; name: string }>;
    directory?: boolean;
    error?: string;
    message?: string;
  };
  if (!r.ok) {
    throw new Error(`GET /api/users ${r.status} ${data.error || data.message || ""}`.trim());
  }
  return data;
}
export async function apiPatchUser(id: string, body: unknown): Promise<unknown> {
  const uid = (id || "").trim();
  if (!uid) throw new Error("PATCH /api/users missing id");
  return apiJson(`/api/users/${encodeURIComponent(uid)}`, { method: "PATCH", body: JSON.stringify(body) });
}
export async function apiDeleteUser(id: string): Promise<unknown> {
  return apiJson(`/api/users/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function apiImportWorldPack(body: unknown): Promise<{
  ok: boolean;
  world: Record<string, unknown>;
  characters: Array<Record<string, unknown>>;
  sourceDocumentIds: string[];
}> {
  return apiJson("/api/world-packs/import", { method: "POST", body: JSON.stringify(body) }) as Promise<{
    ok: boolean;
    world: Record<string, unknown>;
    characters: Array<Record<string, unknown>>;
    sourceDocumentIds: string[];
  }>;
}

export async function apiCreateWorld(body: unknown): Promise<unknown> {
  return apiJson("/api/worlds", { method: "POST", body: JSON.stringify(body) });
}
export async function apiPatchWorld(id: string, body: unknown): Promise<unknown> {
  return apiJson(`/api/worlds/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) });
}
export async function apiDeleteWorld(id: string): Promise<unknown> {
  return apiJson(`/api/worlds/${encodeURIComponent(id)}`, { method: "DELETE" });
}
export async function apiBackupWorld(id: string): Promise<{ ok?: boolean; backup?: { id?: string; name?: string } }> {
  return apiJson(`/api/worlds/${encodeURIComponent(id)}/backup`, { method: "POST", body: JSON.stringify({}) }) as Promise<{
    ok?: boolean;
    backup?: { id?: string; name?: string };
  }>;
}
export async function apiListWorldBackups(id: string): Promise<{ backups?: Array<{ id?: string; name?: string; createdAt?: string }> }> {
  return apiJson(`/api/worlds/${encodeURIComponent(id)}/backup`) as Promise<{
    backups?: Array<{ id?: string; name?: string; createdAt?: string }>;
  }>;
}
export async function apiRestoreWorldBackup(id: string, backupId: string): Promise<unknown> {
  return apiJson(`/api/worlds/${encodeURIComponent(id)}/restore-backup`, {
    method: "POST",
    body: JSON.stringify({ backupId }),
  });
}

export async function apiCreateCharacter(body: unknown): Promise<unknown> {
  return apiJson("/api/characters", { method: "POST", body: JSON.stringify(body) });
}
export async function apiPatchCharacter(id: string, body: unknown): Promise<unknown> {
  return apiJson(`/api/characters/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) });
}
export async function apiDeleteCharacter(id: string): Promise<{
  ok: boolean;
  deleted: string;
  detachedSessions: string[];
  sessionUpdates: Array<Record<string, unknown>>;
  world: Record<string, unknown>;
  user?: Record<string, unknown>;
  historyPreserved: boolean;
}> {
  return apiJson(`/api/characters/${encodeURIComponent(id)}`, { method: "DELETE" }) as Promise<{ ok: boolean; deleted: string; detachedSessions: string[]; sessionUpdates: Array<Record<string, unknown>>; world: Record<string, unknown>; user?: Record<string, unknown>; historyPreserved: boolean }>;
}
export async function apiBackupCharacter(id: string): Promise<{ ok?: boolean; backup?: { id?: string; name?: string } }> {
  return apiJson(`/api/characters/${encodeURIComponent(id)}/backup`, { method: "POST", body: JSON.stringify({}) }) as Promise<{
    ok?: boolean;
    backup?: { id?: string; name?: string };
  }>;
}
export async function apiListCharacterBackups(id: string): Promise<{ backups?: Array<{ id?: string; name?: string; createdAt?: string }> }> {
  return apiJson(`/api/characters/${encodeURIComponent(id)}/backup`) as Promise<{
    backups?: Array<{ id?: string; name?: string; createdAt?: string }>;
  }>;
}
export async function apiRestoreCharacterBackup(id: string, backupId: string): Promise<unknown> {
  return apiJson(`/api/characters/${encodeURIComponent(id)}/restore-backup`, {
    method: "POST",
    body: JSON.stringify({ backupId }),
  });
}

export async function apiCreateSession(body: unknown): Promise<unknown> {
  return apiJson("/api/sessions", { method: "POST", body: JSON.stringify(body) });
}
export async function apiPutSession(id: string, body: unknown): Promise<unknown> {
  return apiJson(`/api/sessions/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(body) });
}
export async function apiPatchSession(id: string, body: unknown): Promise<unknown> {
  return apiJson(`/api/sessions/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) });
}
export async function apiDeleteSession(id: string): Promise<unknown> {
  return apiJson(`/api/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
}
export async function apiResetSessionChat(id: string, body?: unknown): Promise<unknown> {
  return apiJson(`/api/sessions/${encodeURIComponent(id)}/reset-chat`, {
    method: "POST",
    body: JSON.stringify(body ?? {}),
  });
}
export async function apiResetSessionMemory(id: string): Promise<unknown> {
  return apiJson(`/api/sessions/${encodeURIComponent(id)}/reset-memory`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}
export async function apiResetSessionFull(id: string): Promise<unknown> {
  return apiJson(`/api/sessions/${encodeURIComponent(id)}/reset-full`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}
export async function apiResetSessionUploads(id: string): Promise<unknown> {
  return apiJson(`/api/sessions/${encodeURIComponent(id)}/reset-uploads`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function apiListSessionEvidence(sessionId: string): Promise<{
  ok?: boolean;
  sessionId?: string;
  evidence?: Array<Record<string, unknown>>;
}> {
  return apiJson(`/api/sessions/${encodeURIComponent(sessionId)}/evidence`) as Promise<{
    ok?: boolean;
    sessionId?: string;
    evidence?: Array<Record<string, unknown>>;
  }>;
}

export async function apiPostMemory(sessionId: string, body: unknown): Promise<unknown> {
  return apiJson(`/api/sessions/${encodeURIComponent(sessionId)}/memories`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}
export async function apiPutRelation(sessionId: string, body: unknown): Promise<unknown> {
  return apiJson(`/api/sessions/${encodeURIComponent(sessionId)}/relations`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}
export async function apiPostProposition(sessionId: string, body: unknown): Promise<unknown> {
  return apiJson(`/api/sessions/${encodeURIComponent(sessionId)}/propositions`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}
export async function apiPatchProposition(sessionId: string, propId: string, body: unknown): Promise<unknown> {
  return apiJson(
    `/api/sessions/${encodeURIComponent(sessionId)}/propositions/${encodeURIComponent(propId)}`,
    { method: "PATCH", body: JSON.stringify(body) },
  );
}
export async function apiPostGoal(sessionId: string, body: unknown): Promise<unknown> {
  return apiJson(`/api/sessions/${encodeURIComponent(sessionId)}/goals`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}
export async function apiPatchGoal(sessionId: string, goalId: string, body: unknown): Promise<unknown> {
  return apiJson(
    `/api/sessions/${encodeURIComponent(sessionId)}/goals/${encodeURIComponent(goalId)}`,
    { method: "PATCH", body: JSON.stringify(body) },
  );
}

export async function apiCreateUpload(body: unknown): Promise<unknown> {
  return apiJson("/api/uploads", { method: "POST", body: JSON.stringify(body) });
}
export async function apiPatchUpload(id: string, body: unknown): Promise<unknown> {
  return apiJson(`/api/uploads/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) });
}
export async function apiCommitUpload(id: string): Promise<unknown> {
  return apiJson(`/api/uploads/${encodeURIComponent(id)}/commit`, { method: "POST", body: JSON.stringify({}) });
}
export async function apiIngestUpload(id: string): Promise<unknown> {
  return apiJson(`/api/uploads/${encodeURIComponent(id)}/ingest`, { method: "POST", body: JSON.stringify({}) });
}
export async function apiDeleteUpload(id: string): Promise<unknown> {
  return apiJson(`/api/uploads/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function apiCreateReview(body: unknown): Promise<unknown> {
  return apiJson("/api/reviews", { method: "POST", body: JSON.stringify(body) });
}
export async function apiResolveReview(id: string, status: string, extra?: Record<string, unknown>): Promise<unknown> {
  return apiJson(`/api/reviews/${encodeURIComponent(id)}/resolve`, {
    method: "POST",
    body: JSON.stringify({ status, ...(extra || {}) }),
  });
}
export async function apiPatchReview(id: string, body: unknown): Promise<unknown> {
  return apiJson(`/api/reviews/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) });
}

type SnapshotRow = { id?: string; sessionId?: string; erfasst?: { durch?: string } };
export async function apiListSnapshots(): Promise<{ snapshots?: SnapshotRow[] }> {
  return apiJson("/api/snapshots") as Promise<{ snapshots?: SnapshotRow[] }>;
}
export async function apiCreateSessionSnapshot(sessionId: string, name?: string): Promise<unknown> {
  return apiJson(`/api/sessions/${encodeURIComponent(sessionId)}/snapshots`, {
    method: "POST",
    body: JSON.stringify({ name: name || "Stand" }),
  });
}
export async function apiRestoreSnapshot(id: string): Promise<unknown> {
  return apiJson(`/api/snapshots/${encodeURIComponent(id)}/restore`, { method: "POST", body: JSON.stringify({}) });
}
export async function apiDeleteSnapshot(id: string): Promise<unknown> {
  return apiJson(`/api/snapshots/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function apiCreateTrigger(body: unknown): Promise<unknown> {
  return apiJson("/api/triggers", { method: "POST", body: JSON.stringify(body) });
}
export async function apiPatchTrigger(id: string, body: unknown): Promise<unknown> {
  return apiJson(`/api/triggers/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) });
}
export async function apiDeleteTrigger(id: string): Promise<unknown> {
  return apiJson(`/api/triggers/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function apiCreatePreference(body: unknown): Promise<unknown> {
  return apiJson("/api/preferences", { method: "POST", body: JSON.stringify(body) });
}
export async function apiPatchPreference(id: string, body: unknown): Promise<unknown> {
  return apiJson(`/api/preferences/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) });
}
export async function apiDeletePreference(id: string): Promise<unknown> {
  return apiJson(`/api/preferences/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function apiPutConfig(body: unknown): Promise<unknown> {
  return apiJson("/api/config", { method: "PUT", body: JSON.stringify(body) });
}
export async function apiGetConfig(scope = "user", scopeId?: string): Promise<Record<string, unknown>> {
  const q = new URLSearchParams({ scope });
  if (scopeId) q.set("scope_id", scopeId);
  return apiJson(`/api/config?${q.toString()}`) as Promise<Record<string, unknown>>;
}

export async function apiPostLog(body: unknown): Promise<unknown> {
  return apiJson("/api/logs", { method: "POST", body: JSON.stringify(body) });
}
export async function apiGetLog(logId: string): Promise<Record<string, unknown>> {
  return apiJson(`/api/logs/${encodeURIComponent(logId)}`) as Promise<Record<string, unknown>>;
}
export async function apiProbeLogPut(logId: string): Promise<{ status: number; error?: string }> {
  const r = await fetch(`/api/logs/${encodeURIComponent(logId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...actorHeader() },
    body: JSON.stringify({}),
  });
  const data = (await r.json().catch(() => ({}))) as { error?: string };
  return { status: r.status, error: data.error };
}
export async function apiProbeLogDelete(logId: string): Promise<{ status: number; error?: string }> {
  const r = await fetch(`/api/logs/${encodeURIComponent(logId)}`, {
    method: "DELETE",
    headers: { ...actorHeader() },
  });
  const data = (await r.json().catch(() => ({}))) as { error?: string };
  return { status: r.status, error: data.error };
}
export async function apiPostLiveLog(body: Record<string, unknown>, signal?: AbortSignal): Promise<Record<string, unknown>> {
  return apiJson("/api/logs/live", { method: "POST", body: JSON.stringify(body), signal }) as Promise<Record<string, unknown>>;
}
export async function apiListLogs(): Promise<Record<string, unknown>> {
  return apiJson("/api/logs") as Promise<Record<string, unknown>>;
}
export async function apiLiveLog(): Promise<Record<string, unknown>> {
  return apiJson("/api/live-log") as Promise<Record<string, unknown>>;
}
export async function apiDeleteUserLogs(userId: string): Promise<unknown> {
  return apiJson(`/api/users/${encodeURIComponent(userId)}/logs`, { method: "DELETE" });
}
export async function apiHardResetUser(userId: string): Promise<unknown> {
  return apiJson(`/api/users/${encodeURIComponent(userId)}/hard-reset`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}
export async function apiResetUserSessions(userId: string): Promise<unknown> {
  return apiJson(`/api/users/${encodeURIComponent(userId)}/reset-sessions`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function apiGetSession(id: string, options?: { timeoutMs?: number }): Promise<{ ok: boolean; session: Record<string, unknown> }> {
  const path = `/api/sessions/${encodeURIComponent(id)}`;
  const request = { method: "GET" };
  return (options?.timeoutMs
    ? boundedKernelJson(path, request, options.timeoutMs, "SESSION_READ_TIMEOUT")
    : apiJson(path, request)) as Promise<{
    ok: boolean;
    session: Record<string, unknown>;
  }>;
}

export async function apiKernelCommit(body: unknown): Promise<{ ok: boolean; session: Record<string, unknown> }> {
  return boundedKernelJson("/api/kernel/commit", { method: "POST", body: JSON.stringify(body) },
    120000, "KERNEL_COMMIT_STATUS_UNGEWISS") as Promise<{
    ok: boolean;
    session: Record<string, unknown>;
  }>;
}
export async function apiKernelPrepare(body: unknown): Promise<{
  ok: boolean;
  writable?: boolean;
  truth?: Record<string, unknown>;
  brainContext?: Record<string, unknown>;
  session?: Record<string, unknown>;
  trace_id?: string;
}> {
  return boundedKernelJson("/api/kernel/prepare", { method: "POST", body: JSON.stringify(body) },
    120000, "KERNEL_PREPARE_STATUS_UNGEWISS") as Promise<{
    ok: boolean;
    writable?: boolean;
    truth?: Record<string, unknown>;
    brainContext?: Record<string, unknown>;
    session?: Record<string, unknown>;
    trace_id?: string;
  }>;
}
export async function apiKernelGod(body: unknown): Promise<{ ok: boolean; session: Record<string, unknown> }> {
  return apiJson("/api/kernel/god", { method: "POST", body: JSON.stringify(body) }) as Promise<{
    ok: boolean;
    session: Record<string, unknown>;
  }>;
}
export async function apiKernelRegie(body: unknown): Promise<{ ok: boolean; session: Record<string, unknown> }> {
  return apiJson("/api/kernel/regie", { method: "POST", body: JSON.stringify(body) }) as Promise<{
    ok: boolean;
    session: Record<string, unknown>;
  }>;
}
export async function apiKernelPuppet(body: unknown): Promise<{ ok: boolean; session: Record<string, unknown> }> {
  return apiJson("/api/kernel/puppet", { method: "POST", body: JSON.stringify(body) }) as Promise<{
    ok: boolean;
    session: Record<string, unknown>;
  }>;
}
export async function apiKernelMove(body: unknown): Promise<{ ok: boolean; session: Record<string, unknown> }> {
  return apiJson("/api/kernel/move", { method: "POST", body: JSON.stringify(body) }) as Promise<{
    ok: boolean;
    session: Record<string, unknown>;
  }>;
}
export async function apiKernelPresence(body: unknown): Promise<{ ok: boolean; session: Record<string, unknown> }> {
  return apiJson("/api/kernel/presence", { method: "POST", body: JSON.stringify(body) }) as Promise<{
    ok: boolean;
    session: Record<string, unknown>;
  }>;
}
export async function apiKernelFate(body: unknown): Promise<{ ok: boolean; session: Record<string, unknown> }> {
  return apiJson("/api/kernel/fate", { method: "POST", body: JSON.stringify(body) }) as Promise<{
    ok: boolean;
    session: Record<string, unknown>;
  }>;
}
export async function apiKernelAutochatGate(body: unknown): Promise<{
  ok: boolean;
  stop?: boolean;
  reason?: string | null;
  speakerId?: string;
  remaining?: number;
}> {
  return apiJson("/api/kernel/autochat-gate", { method: "POST", body: JSON.stringify(body) }) as Promise<{
    ok: boolean;
    stop?: boolean;
    reason?: string | null;
    speakerId?: string;
    remaining?: number;
  }>;
}
export async function apiKernelReset(body: unknown): Promise<{ ok: boolean; session: Record<string, unknown> }> {
  return apiJson("/api/kernel/reset", { method: "POST", body: JSON.stringify(body) }) as Promise<{
    ok: boolean;
    session: Record<string, unknown>;
  }>;
}
export async function apiKernelPerception(body: unknown): Promise<{ ok: boolean; session: Record<string, unknown> }> {
  return apiJson("/api/kernel/perception", { method: "POST", body: JSON.stringify(body) }) as Promise<{
    ok: boolean;
    session: Record<string, unknown>;
  }>;
}

export async function apiAnalyzeLocal(text: string, worldId?: string, title?: string): Promise<Record<string, unknown>> {
  return apiJson("/api/analyze", { method: "POST", body: JSON.stringify({ text, worldId, title }) }) as Promise<Record<string, unknown>>;
}

export function analyzeFailMessage(e: unknown): string {
  const s = e instanceof Error ? e.message : String(e || "");
  if (/524|502|504|timeout|abort|Failed to fetch|NetworkError/i.test(s)) {
    return "Die Analyse ist ins Zeitlimit gelaufen. Nochmal die gewählten Teile — die lokale Auswertung kommt jetzt sofort.";
  }
  return s.trim() || "Analyse fehlgeschlagen";
}

export async function apiCompleteProfiles(
  body: { text?: string; title?: string; candidates?: unknown[]; roster?: string[] },
  opts?: { timeoutMs?: number },
): Promise<Record<string, unknown>> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), opts?.timeoutMs ?? 40000);
  try {
    return (await apiJson("/api/llm/complete-profiles", {
      method: "POST",
      body: JSON.stringify(body),
      signal: ctrl.signal,
    })) as Record<string, unknown>;
  } catch {
    return { ok: false };
  } finally {
    clearTimeout(timer);
  }
}
export async function apiSearchLocal(q: string): Promise<Record<string, unknown>> {
  return apiJson("/api/search", { method: "POST", body: JSON.stringify({ q }) }) as Promise<Record<string, unknown>>;
}
export async function apiVectorSearch(q: string, limit = 20): Promise<Record<string, unknown>> {
  return apiJson("/api/vector/search", {
    method: "POST",
    body: JSON.stringify({ q, limit }),
  }) as Promise<Record<string, unknown>>;
}
export async function apiGenrePolicy(genre: string, text = ""): Promise<Record<string, unknown>> {
  return apiJson("/api/genre/policy", { method: "POST", body: JSON.stringify({ genre, text }) }) as Promise<Record<string, unknown>>;
}
export async function apiSystemLoop(): Promise<Record<string, unknown>> {
  return apiJson("/api/amaster/system-loop", { method: "POST", body: JSON.stringify({}) }) as Promise<Record<string, unknown>>;
}
export async function apiRecall(sessionId: string, cue: string): Promise<Record<string, unknown>> {
  return apiJson(`/api/sessions/${encodeURIComponent(sessionId)}/recall`, {
    method: "POST",
    body: JSON.stringify({ cue }),
  }) as Promise<Record<string, unknown>>;
}
export async function apiListAppointments(sessionId: string): Promise<Record<string, unknown>> {
  return apiJson(`/api/sessions/${encodeURIComponent(sessionId)}/appointments`) as Promise<Record<string, unknown>>;
}
export async function apiListGraph(sessionId: string): Promise<Record<string, unknown>> {
  return apiJson(`/api/sessions/${encodeURIComponent(sessionId)}/graph`) as Promise<Record<string, unknown>>;
}
export async function apiSpeechStt(body: unknown = {}): Promise<Record<string, unknown>> {
  return apiJson("/api/speech/stt", { method: "POST", body: JSON.stringify(body) }) as Promise<Record<string, unknown>>;
}
export async function apiSpeechTts(body: unknown = {}): Promise<Record<string, unknown>> {
  return apiJson("/api/speech/tts", { method: "POST", body: JSON.stringify(body) }) as Promise<Record<string, unknown>>;
}
export async function apiCreateDocument(body: unknown): Promise<Record<string, unknown>> {
  return apiJson("/api/documents", { method: "POST", body: JSON.stringify(body) }) as Promise<Record<string, unknown>>;
}
export async function apiListDocuments(): Promise<Record<string, unknown>> {
  return apiJson("/api/documents") as Promise<Record<string, unknown>>;
}
export async function apiListDocumentIndex(): Promise<Record<string, unknown>> {
  return apiJson("/api/document-index") as Promise<Record<string, unknown>>;
}
export async function apiSearchDocumentIndex(q: string): Promise<Record<string, unknown>> {
  return apiJson("/api/document-index/search", {
    method: "POST",
    body: JSON.stringify({ q }),
  }) as Promise<Record<string, unknown>>;
}
export async function apiGetDocument(id: string): Promise<Record<string, unknown>> {
  return apiJson(`/api/documents/${encodeURIComponent(id)}`) as Promise<Record<string, unknown>>;
}
export async function apiDeleteDocument(id: string): Promise<Record<string, unknown>> {
  return apiJson(`/api/documents/${encodeURIComponent(id)}`, { method: "DELETE" }) as Promise<Record<string, unknown>>;
}
export async function apiPatchDocument(id: string, body: unknown): Promise<Record<string, unknown>> {
  return apiJson(`/api/documents/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) }) as Promise<Record<string, unknown>>;
}
export async function apiFormulate(body: unknown, opts?: { timeoutMs?: number }): Promise<Record<string, unknown>> {
  const timeoutMs = opts?.timeoutMs ?? 20000;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    return (await apiJson("/api/llm/formulate", {
      method: "POST",
      body: JSON.stringify(body),
      signal: ctrl.signal,
    })) as Record<string, unknown>;
  } catch (err) {
    if (ctrl.signal.aborted) {
      return { ok: false, error: "FORMULATE_TIMEOUT", source: "synapse" };
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}
export async function apiCreateAppointment(sessionId: string, body: unknown): Promise<Record<string, unknown>> {
  return apiJson(`/api/sessions/${encodeURIComponent(sessionId)}/appointments`, {
    method: "POST",
    body: JSON.stringify(body),
  }) as Promise<Record<string, unknown>>;
}
export async function apiCreateGraph(sessionId: string, body: unknown): Promise<Record<string, unknown>> {
  return apiJson(`/api/sessions/${encodeURIComponent(sessionId)}/graph`, {
    method: "POST",
    body: JSON.stringify(body),
  }) as Promise<Record<string, unknown>>;
}

export async function apiGenerateWorld(body: unknown): Promise<Record<string, unknown>> {
  return apiJson("/api/llm/world", { method: "POST", body: JSON.stringify(body) }) as Promise<Record<string, unknown>>;
}
export async function apiGenerateCharacters(body: unknown): Promise<Record<string, unknown>> {
  return apiJson("/api/llm/characters", { method: "POST", body: JSON.stringify(body) }) as Promise<Record<string, unknown>>;
}
export async function apiSuggestProfile(body: unknown): Promise<Record<string, unknown>> {
  return apiJson("/api/llm/profile", { method: "POST", body: JSON.stringify(body) }) as Promise<Record<string, unknown>>;
}
export async function apiDeriveCompass(body: unknown): Promise<Record<string, unknown>> {
  return apiJson("/api/llm/compass", { method: "POST", body: JSON.stringify(body) }) as Promise<Record<string, unknown>>;
}
export async function apiPingProvider(body: unknown = {}): Promise<Record<string, unknown>> {
  return apiJson("/api/llm/ping", { method: "POST", body: JSON.stringify(body) }) as Promise<Record<string, unknown>>;
}
export async function apiListReviews(): Promise<Record<string, unknown>> {
  return apiJson("/api/reviews") as Promise<Record<string, unknown>>;
}

