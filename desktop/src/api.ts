// Thin client for the local engine API.
export type Meeting = {
  id: string; title: string; platform: string; started_at: string; duration_s: number;
  language: string | null; status: string; audio_path: string | null; mic_path: string | null;
  system_path: string | null; participants_hint: string; agenda: string; error: string | null; created_at: string;
  source: '' | 'recording' | 'media' | 'transcript' | 'chat';
};
export type TextImport = { text: string; title?: string; platform?: string; participants_hint?: string; agenda?: string;
  template?: string; auto_process?: boolean };
export type Participant = { id: string; label: string; display_name: string; is_self: number };
export type Segment = { id: string; participant_id: string | null; start_s: number; end_s: number; text: string;
  edited: number; speaker: string | null; is_self: number | null; media: string | null };
export type ActionItem = { task: string; owner: string; due: string };
export type Minutes = {
  title: string; language: string; attendees: { name: string; role: string }[]; agenda: string[];
  discussion: { topic: string; points: string[] }[]; decisions: string[]; action_items: ActionItem[];
  open_issues: string[]; next_meeting: string; tldr: string[]; executive_summary: string;
};
export type Job = { id: string; kind: string; meeting_id: string; status: 'queued' | 'running' | 'done' | 'error';
  progress: number; message: string; error: string | null };
export type MeetingDetail = { meeting: Meeting; participants: Participant[]; segments: Segment[];
  minutes: { template: string; language: string; content: Minutes; updated_at: string } | null;
  summaries: Record<string, string>; jobs: Job[] };

declare global {
  interface Window {
    mt?: {
      engineInfo: () => Promise<{ base: string; token: string; platform: string }>;
      saveFile: (name: string, data: ArrayBuffer) => Promise<string | null>;
      openPath: (p: string) => Promise<string>;
      showInFolder: (p: string) => Promise<void>;
      pickImage: () => Promise<string | null>;
      onEngineExit: (cb: (code: number) => void) => void;
    };
  }
}

let BASE = 'http://127.0.0.1:8765';
let TOKEN = '';
export let PLATFORM = 'web';

export async function init(): Promise<void> {
  if (window.mt) {
    const info = await window.mt.engineInfo();
    BASE = info.base; TOKEN = info.token; PLATFORM = info.platform;
  } else {
    const q = new URLSearchParams(location.search);
    BASE = q.get('engine') || BASE; TOKEN = q.get('token') || '';
  }
  // wait for engine to come up (it is spawned together with the window)
  for (let i = 0; i < 120; i++) {
    try { const r = await fetch(`${BASE}/health`); if (r.ok) return; } catch { /* starting */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error('Engine did not start. Check that Python and the engine dependencies are installed.');
}

async function req<T>(method: string, path: string, body?: unknown, raw = false): Promise<T> {
  const headers: Record<string, string> = { 'X-MT-Token': TOKEN };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
  const r = await fetch(`${BASE}${path}`, { method, headers, body: payload });
  if (!r.ok) {
    let msg = await r.text();
    try { msg = JSON.parse(msg).detail ?? msg; } catch { /* plain text */ }
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return (raw ? r : r.json()) as Promise<T>;
}

export const api = {
  settings: () => req<any>('GET', '/settings'),
  saveSettings: (v: any) => req<any>('PUT', '/settings', v),
  saveSecret: (name: string, value: string) => req<{ stored_in: string }>('PUT', '/secrets', { name, value }),
  consent: (lang: string) => req<{ text: string }>('GET', `/consent-notice?lang=${lang}`),
  devices: () => req<any>('GET', '/devices'),
  startRec: (b: any) => req<any>('POST', '/recordings/start', b),
  pauseRec: () => req<any>('POST', '/recordings/pause'),
  resumeRec: () => req<any>('POST', '/recordings/resume'),
  stopRec: (template?: string) => req<{ meeting: Meeting; job: Job | null }>('POST', `/recordings/stop?auto_process=true${template ? `&template=${template}` : ''}`),
  recStatus: () => req<any>('GET', '/recordings/status'),
  liveSocket: () => new WebSocket(`${BASE.replace(/^http/, 'ws')}/recordings/live?token=${encodeURIComponent(TOKEN)}`),
  meetings: () => req<Meeting[]>('GET', '/meetings'),
  importFile: (fd: FormData) => req<{ meeting: Meeting; job: Job | null }>('POST', '/meetings/import', fd),
  importText: (b: TextImport) => req<{ meeting: Meeting; job: Job | null }>('POST', '/meetings/import-text', b),
  meeting: (id: string) => req<MeetingDetail>('GET', `/meetings/${id}`),
  patchMeeting: (id: string, v: Partial<Meeting>) => req<Meeting>('PATCH', `/meetings/${id}`, v),
  deleteMeeting: (id: string) => req<any>('DELETE', `/meetings/${id}`),
  transcribe: (id: string) => req<Job>('POST', `/meetings/${id}/transcribe`),
  rename: (id: string, pid: string, display_name: string) => req<Participant[]>('PATCH', `/meetings/${id}/participants/${pid}`, { display_name }),
  editSegment: (id: string, sid: string, v: { text?: string; participant_id?: string }) => req<any>('PATCH', `/meetings/${id}/segments/${sid}`, v),
  generate: (id: string, template?: string, output_language?: string) => req<Job>('POST', `/meetings/${id}/minutes`, { template, output_language }),
  regenerate: (id: string, section: string) => req<Job>('POST', `/meetings/${id}/minutes/regenerate/${section}`),
  saveMinutes: (id: string, m: Minutes) => req<Minutes>('PUT', `/meetings/${id}/minutes`, m),
  job: (jid: string) => req<Job>('GET', `/jobs/${jid}`),
  search: (q: string) => req<any[]>('GET', `/search?q=${encodeURIComponent(q)}`),
  audioUrl: (id: string) => `${BASE}/meetings/${id}/audio?token=${encodeURIComponent(TOKEN)}`,
  mediaUrl: (id: string, sid: string) => `${BASE}/meetings/${id}/segments/${sid}/media?token=${encodeURIComponent(TOKEN)}`,
  async export(id: string, format: string, opts: { transcript: boolean; summary: boolean; timestamps: boolean }) {
    const q = new URLSearchParams({ format, transcript: String(opts.transcript), summary: String(opts.summary), timestamps: String(opts.timestamps) });
    const r = await req<Response>('GET', `/meetings/${id}/export?${q}`, undefined, true);
    const name = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(r.headers.get('content-disposition') || '')?.[1];
    return { name: name ? decodeURIComponent(name) : `minutes.${format}`, data: await r.arrayBuffer() };
  },
};

export async function waitJob(jid: string, onTick?: (j: Job) => void): Promise<Job> {
  for (;;) {
    const j = await api.job(jid);
    onTick?.(j);
    if (j.status === 'done' || j.status === 'error') return j;
    await new Promise((r) => setTimeout(r, 700));
  }
}

export const fmtTs = (s: number) => {
  s = Math.floor(s); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}` : `${m}:${String(sec).padStart(2, '0')}`;
};
export const fmtDur = (s: number) => { s = Math.floor(s || 0); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60); return h ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m ${String(s % 60).padStart(2, '0')}s`; };
export const fmtDate = (iso: string) => { try { return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }); } catch { return iso; } };
