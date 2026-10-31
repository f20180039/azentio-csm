import type {
  AuditEvent,
  AuditVerifyResult,
  CaseAction,
  CaseDetail,
  CaseStatus,
  CaseSummary,
  ExtractionSummary,
  Finding,
  FindingAction,
  Page,
  PageText,
  PackRule,
  Role,
  RulePackInfo,
  Stats,
  UploadResult,
} from './types';
import { Role as RoleName } from '../vocab';
import { mockApi } from './mock';
import { CoreApiPath } from './paths/core';
import { ApiError, toApiError } from './errors';

export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://localhost:8080/api/v1';
export const MOCK_MODE = import.meta.env.VITE_MOCK === '1';

export { ApiError, toApiError } from './errors';

export interface Credentials {
  username: string;
  password: string;
}

export interface Session extends Credentials {
  roles: Role[];
}

let credentials: Credentials | null = null;

export function setCredentials(c: Credentials | null) {
  credentials = c;
}

function authHeader(): Record<string, string> {
  if (!credentials) return {};
  return { Authorization: 'Basic ' + btoa(`${credentials.username}:${credentials.password}`) };
}

type Fetcher = typeof fetch;
let fetcher: Fetcher = (...args) => fetch(...args);
/** Test hook. */
export function setFetcher(f: Fetcher) {
  fetcher = f;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<{ data: T; res: Response }> {
  let res: Response;
  try {
    res = await fetcher(`${API_BASE}${path}`, {
      ...init,
      headers: { Accept: 'application/json, application/problem+json', ...authHeader(), ...(init.headers ?? {}) },
    });
  } catch (e) {
    throw new ApiError({
      status: 0,
      title: 'Cannot reach the API',
      detail: `Check that the API is running at ${API_BASE}.`,
    });
  }
  if (!res.ok) throw await toApiError(res);
  const text = await res.text();
  return { data: (text ? JSON.parse(text) : null) as T, res };
}

export async function get<T>(path: string): Promise<T> {
  return (await request<T>(path)).data;
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  return (
    await request<T>(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  ).data;
}

export async function patchJson<T>(path: string, body: unknown): Promise<T> {
  return (
    await request<T>(path, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  ).data;
}

export async function putJson<T>(path: string, body: unknown): Promise<T> {
  return (
    await request<T>(path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  ).data;
}

export async function del<T>(path: string): Promise<T> {
  return (await request<T>(path, { method: 'DELETE' })).data;
}

/** The signed-in username, for mock-mode authorship. */
export function currentUsername(): string | null {
  return credentials?.username ?? null;
}

/* ---------- normalisers: tolerate list vs Spring page, map vs list ---------- */

export function normalisePage<T>(raw: unknown): Page<T> {
  if (Array.isArray(raw)) return { items: raw as T[], total: raw.length };
  const r = raw as { content?: T[]; items?: T[]; totalElements?: number; total?: number } | null;
  const items = r?.content ?? r?.items ?? [];
  return { items, total: r?.totalElements ?? r?.total ?? items.length };
}

export function normalisePack(raw: Record<string, unknown>): RulePackInfo {
  const rulesRaw = raw.rules;
  let rules: PackRule[] = [];
  if (Array.isArray(rulesRaw)) {
    rules = rulesRaw as PackRule[];
  } else if (rulesRaw && typeof rulesRaw === 'object') {
    rules = Object.entries(rulesRaw as Record<string, Omit<PackRule, 'id'>>).map(([id, r]) => ({ id, ...r }));
  }
  return { ...(raw as unknown as RulePackInfo), rules };
}

function normaliseCase<T extends CaseSummary>(c: T & { findings?: Finding[]; openFindings?: number }): T {
  return {
    ...c,
    findingsCount: c.findingsCount ?? c.openFindings ?? c.findings?.length ?? 0,
  };
}

// The API nests each extraction as { documentId, extraction: {...} }.
function flattenExtraction(e: ExtractionSummary & { extraction?: ExtractionSummary }): ExtractionSummary {
  return e.extraction ? { documentId: e.documentId, ...e.extraction } : e;
}

/* ---------- the API ---------- */

export interface CaseQuery {
  status?: CaseStatus | '';
  caseType?: string;
  dateFrom?: string;
  dateTo?: string;
  page?: number;
  size?: number;
}

const liveApi = {
  async signIn(c: Credentials): Promise<Session> {
    setCredentials(c);
    try {
      // /me is optional on the API; fall back to probing role-gated endpoints.
      try {
        const me = await get<{ username?: string; roles?: string[] }>(CoreApiPath.ME);
        if (me?.roles?.length) {
          return { ...c, roles: me.roles.map((r) => r.replace(/^ROLE_/, '')) as Role[] };
        }
      } catch (e) {
        if (e instanceof ApiError && e.isUnauthorized) throw e;
      }
      await get(CoreApiPath.PACKS);
      const roles: Role[] = [RoleName.ANALYST];
      try {
        await get(CoreApiPath.AUDIT_VERIFY);
        roles.push(RoleName.REVIEWER, RoleName.ADMIN);
      } catch (e) {
        if (!(e instanceof ApiError && e.isForbidden)) throw e;
        if (c.username.toLowerCase().includes('review')) roles.push(RoleName.REVIEWER);
      }
      return { ...c, roles };
    } catch (e) {
      setCredentials(null);
      throw e;
    }
  },

  async listCases(q: CaseQuery = {}): Promise<Page<CaseSummary>> {
    const params = new URLSearchParams();
    if (q.status) params.set('status', q.status);
    if (q.caseType) params.set('caseType', q.caseType);
    if (q.dateFrom) params.set('dateFrom', q.dateFrom);
    if (q.dateTo) params.set('dateTo', q.dateTo);
    params.set('page', String(q.page ?? 0));
    params.set('size', String(q.size ?? 50));
    const page = normalisePage<CaseSummary>(await get(`${CoreApiPath.CASES}?${params}`));
    return { ...page, items: page.items.map(normaliseCase) };
  },

  async getCase(id: string): Promise<CaseDetail> {
    const c = await get<CaseDetail>(CoreApiPath.case(id));
    return normaliseCase({
      ...c,
      documents: c.documents ?? [],
      findings: c.findings ?? [],
      extractions: (c.extractions ?? []).map(flattenExtraction),
    });
  },

  async getPages(caseId: string, docId: string): Promise<PageText[]> {
    const raw = await get<PageText[] | { pages: PageText[] }>(CoreApiPath.casePages(caseId, docId));
    return Array.isArray(raw) ? raw : raw?.pages ?? [];
  },

  async uploadCase(files: File[], caseType: string, title?: string, attributes?: string): Promise<UploadResult> {
    const form = new FormData();
    files.forEach((f) => form.append('files', f));
    form.append('caseType', caseType);
    if (title) form.append('title', title);
    if (attributes) form.append('attributes', attributes);
    const { data, res } = await request<CaseSummary>(CoreApiPath.CASES, { method: 'POST', body: form });
    const header = res.headers.get('X-Cache');
    const cache = header === 'HIT' || (header === null && res.status === 200) ? 'HIT' : 'MISS';
    return { case: normaliseCase(data), cache };
  },

  decideFinding(caseId: string, findingId: string, body: { action: FindingAction; reason?: string; amount?: number }) {
    return postJson<Finding>(CoreApiPath.findingDecision(caseId, findingId), body);
  },

  decideCase(caseId: string, body: { action: CaseAction; reason: string }) {
    return postJson<CaseSummary>(CoreApiPath.caseDecision(caseId), body);
  },

  async getAudit(caseId: string): Promise<AuditEvent[]> {
    return normalisePage<AuditEvent>(await get(CoreApiPath.caseAudit(caseId))).items;
  },

  verifyAudit() {
    return get<AuditVerifyResult>(CoreApiPath.AUDIT_VERIFY);
  },

  async listPacks(): Promise<RulePackInfo[]> {
    const raw = await get<unknown>(CoreApiPath.PACKS);
    const list = Array.isArray(raw) ? raw : normalisePage<Record<string, unknown>>(raw).items;
    return (list as Record<string, unknown>[]).map(normalisePack);
  },

  getStats() {
    return get<Stats>(CoreApiPath.STATS);
  },
};

export type Api = typeof liveApi;

export const api: Api = MOCK_MODE ? (mockApi as Api) : liveApi;
