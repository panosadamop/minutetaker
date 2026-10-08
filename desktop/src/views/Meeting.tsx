import { useCallback, useEffect, useRef, useState } from 'react';
import { api, fmtDate, fmtDur, fmtTs, Job, MeetingDetail, Minutes, waitJob } from '../api';
import { PLATFORMS, useT } from '../i18n';

const COLORS = ['#e3b64a', '#3dd6e6', '#b48cff', '#4bd68a', '#ff8f6b', '#6ba8ff', '#ff6bb5', '#c9d65a'];

export default function MeetingView({ id, back }: { id: string; back: () => void }) {
  const t = useT();
  const [d, setD] = useState<MeetingDetail | null>(null);
  const [tab, setTab] = useState<'transcript' | 'minutes' | 'summary'>('minutes');
  const [job, setJob] = useState<Job | null>(null);
  const [err, setErr] = useState('');
  const [toast, setToast] = useState('');
  const [templates, setTemplates] = useState<string[]>(['formal']);
  const [template, setTemplate] = useState('');
  const [outLang, setOutLang] = useState('same');

  const load = useCallback(async () => {
    const x = await api.meeting(id);
    setD(x);
    return x;
  }, [id]);

  const track = useCallback(async (j: Job) => {
    setJob(j); setErr('');
    const done = await waitJob(j.id, setJob);
    setJob(null);
    if (done.status === 'error') setErr(done.error || 'Failed');
    await load();
  }, [load]);

  useEffect(() => {
    load().then((x) => {
      if (x.jobs[0]) track(x.jobs[0]);
      if (!x.minutes) setTab('transcript');
      setTemplate(x.minutes?.template || '');
    }).catch((e) => setErr(e.message));
    api.settings().then((s) => { setTemplates(s.templates); setTemplate((v) => v || s.settings.default_template); setOutLang(s.settings.output_language); });
  }, [id, load, track]);

  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(''), 2200); };
  if (!d) return <div className="page">{err ? <div className="err">{err}</div> : <span className="muted">…</span>}</div>;
  const m = d.meeting;

  const colorOf = (pid: string | null) => COLORS[Math.max(0, d.participants.findIndex((p) => p.id === pid)) % COLORS.length];

  async function del() {
    if (!confirm(t.confirmDelete)) return;
    await api.deleteMeeting(id); back();
  }

  return (
    <div className="page">
      <div className="head">
        <button className="btn ghost" onClick={back}>← {t.back}</button>
        <div style={{ flex: 1, minWidth: 260 }}>
          <div className="kicker">{fmtDate(m.started_at)} · {fmtDur(m.duration_s)} · {(m.language || '—').toUpperCase()}
            {m.source === 'transcript' && <> · {t.srcTranscript}</>}{m.source === 'chat' && <> · {t.srcChat}</>}</div>
          <input className="in" style={{ fontSize: 17, fontWeight: 800, background: 'transparent', border: 'none', padding: '2px 0' }}
            defaultValue={m.title} key={m.id} onBlur={(e) => e.target.value !== m.title && api.patchMeeting(id, { title: e.target.value }).then(load)} />
        </div>
        <select className="in" style={{ width: 140 }} value={m.platform} onChange={(e) => api.patchMeeting(id, { platform: e.target.value }).then(load)}>
          {PLATFORMS.map((p) => <option key={p}>{p}</option>)}</select>
        <span className={`badge ${m.status}`}>{m.status}</span>
        <select className="in" style={{ width: 120 }} value={template} onChange={(e) => setTemplate(e.target.value)} title={t.template}>
          {templates.map((x) => <option key={x}>{x}</option>)}</select>
        <select className="in" style={{ width: 150 }} value={outLang} onChange={(e) => setOutLang(e.target.value)} title={t.outputLanguage}>
          <option value="same">{t.same}</option><option value="el">{t.greek}</option><option value="en">{t.english}</option></select>
        <button className="btn gold" disabled={!!job || !d.segments.length}
          onClick={() => api.generate(id, template, outLang).then(track).catch((e) => setErr(e.message))}>
          ✦ {d.minutes ? t.regenerate : t.generate}</button>
        <ExportMenu id={id} onDone={flash} onErr={setErr} />
        <button className="btn danger" onClick={del} title={t.delete}>✕</button>
      </div>

      {job && <div className="jobbar"><div className="row"><span className="cyan">{t.processing}: {job.kind}</span><span className="muted" style={{ textAlign: 'right' }}>{job.message}</span></div>
        <div className="progress"><i style={{ width: `${Math.round(job.progress * 100)}%` }} /></div></div>}
      {(err || m.error) && <div className="err">{err || m.error}</div>}

      <div className="tabs">
        {(['minutes', 'summary', 'transcript'] as const).map((k) => (
          <button key={k} className={`tab ${tab === k ? 'on' : ''}`} onClick={() => setTab(k)}>{t[k]}</button>))}
      </div>

      {tab === 'transcript' && <Transcript d={d} colorOf={colorOf} reload={load} retranscribe={() => api.transcribe(id).then(track)} busy={!!job} />}
      {tab === 'minutes' && (d.minutes
        ? <MinutesEditor key={d.minutes.updated_at} id={id} value={d.minutes.content} busy={!!job}
            onSaved={() => { flash(t.saved); load(); }} onRegen={(s) => api.regenerate(id, s).then(track)} />
        : <div className="card empty">{t.noMinutes}</div>)}
      {tab === 'summary' && (d.minutes
        ? <SummaryEditor key={d.minutes.updated_at} id={id} value={d.minutes.content} onSaved={() => { flash(t.saved); load(); }} onRegen={(s) => api.regenerate(id, s).then(track)} busy={!!job} />
        : <div className="card empty">{t.noMinutes}</div>)}

      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}

// ------------------------------------------------------------------ export --
function ExportMenu({ id, onDone, onErr }: { id: string; onDone: (m: string) => void; onErr: (m: string) => void }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [fmt, setFmt] = useState('docx');
  const [o, setO] = useState({ transcript: true, summary: true, timestamps: true });
  const [busy, setBusy] = useState(false);

  async function go() {
    setBusy(true);
    try {
      const { name, data } = await api.export(id, fmt, o);
      if (window.mt) {
        const p = await window.mt.saveFile(name, data);
        if (p) { onDone(`✓ ${p}`); window.mt.showInFolder(p); }
      } else {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(new Blob([data])); a.download = name; a.click();
        onDone(`✓ ${name}`);
      }
      setOpen(false);
    } catch (e: any) { onErr(e.message); } finally { setBusy(false); }
  }

  return (
    <div className="rel">
      <button className="btn cyan" onClick={() => setOpen(!open)}>⇩ {t.export}</button>
      {open && (
        <div className="menu">
          <div className="fmt">{['docx', 'pdf', 'md', 'txt', 'srt'].map((f) =>
            <button key={f} className={fmt === f ? 'on' : ''} onClick={() => setFmt(f)}>{f.toUpperCase()}</button>)}</div>
          {(fmt === 'docx' || fmt === 'pdf' || fmt === 'md') && <>
            <label className="chk"><input type="checkbox" checked={o.summary} onChange={(e) => setO({ ...o, summary: e.target.checked })} />{t.includeSummary}</label>
            <label className="chk"><input type="checkbox" checked={o.transcript} onChange={(e) => setO({ ...o, transcript: e.target.checked })} />{t.includeTranscript}</label>
            <label className="chk"><input type="checkbox" checked={o.timestamps} onChange={(e) => setO({ ...o, timestamps: e.target.checked })} />{t.includeTimestamps}</label>
          </>}
          <button className="btn gold" style={{ width: '100%', justifyContent: 'center', marginTop: 10 }} disabled={busy} onClick={go}>{busy ? '…' : t.download}</button>
        </div>
      )}
    </div>
  );
}

// -------------------------------------------------------------- transcript --
function Transcript({ d, colorOf, reload, retranscribe, busy }: {
  d: MeetingDetail; colorOf: (pid: string | null) => string; reload: () => Promise<any>; retranscribe: () => void; busy: boolean;
}) {
  const t = useT();
  const audio = useRef<HTMLAudioElement>(null);
  const id = d.meeting.id;
  const seek = (s: number) => { if (audio.current) { audio.current.currentTime = s; audio.current.play(); } };
  const voice = useRef<HTMLAudioElement | null>(null);
  const playNote = (sid: string) => { voice.current?.pause(); voice.current = new Audio(api.mediaUrl(id, sid)); voice.current.play(); };
  const hasVoice = d.segments.some((s) => s.media);
  // chats span hours or days: show each message's real send time instead of an offset
  const chatStart = d.meeting.source === 'chat' ? new Date(d.meeting.started_at).getTime() : NaN;
  const stamp = (s: number) => {
    if (Number.isNaN(chatStart)) return fmtTs(s);
    const at = new Date(chatStart + s * 1000);
    return `${at.toLocaleDateString(undefined, { day: '2-digit', month: '2-digit' })} ${at.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })}`;
  };

  return (
    <div className={`tx ${Number.isNaN(chatStart) ? '' : 'chat'}`}>
      <div>
        <div className="card">
          <h2>{t.speakers}</h2>
          {d.participants.map((p) => (
            <div className="spk" key={p.id}>
              <span className="sw" style={{ background: colorOf(p.id) }} />
              <input className="in" defaultValue={p.display_name} key={p.display_name}
                onBlur={(e) => e.target.value.trim() && e.target.value !== p.display_name && api.rename(id, p.id, e.target.value).then(reload)} />
            </div>
          ))}
          {!d.participants.length && <div className="dim">—</div>}
        </div>
        {(d.meeting.audio_path || hasVoice) && (
          <div className="card">
            <button className="btn" style={{ width: '100%', justifyContent: 'center' }} disabled={busy} onClick={retranscribe}>↻ {t.retranscribe}</button>
          </div>
        )}
      </div>
      <div className="card">
        {d.meeting.audio_path && <audio ref={audio} controls preload="none" src={api.audioUrl(id)} />}
        {!d.segments.length && <div className="empty">{t.noTranscript}</div>}
        {d.segments.map((s) => (
          <div className="seg" key={s.id}>
            <span className="ts" onClick={() => s.media ? playNote(s.id) : seek(s.start_s)}
              title={s.media ? t.playVoiceNote : undefined}>{s.media ? '▶ ' : ''}{stamp(s.start_s)}</span>
            <select value={s.participant_id || ''} style={{ color: colorOf(s.participant_id) }}
              onChange={(e) => api.editSegment(id, s.id, { participant_id: e.target.value }).then(reload)}>
              {d.participants.map((p) => <option key={p.id} value={p.id}>{p.display_name}</option>)}
            </select>
            <div className={`txt ${s.edited ? 'edited' : ''}`} contentEditable suppressContentEditableWarning
              onBlur={(e) => { const v = e.currentTarget.innerText.trim(); if (v !== s.text) api.editSegment(id, s.id, { text: v }); }}>{s.text}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ editors --
const lines = (a: string[]) => a.join('\n');
const unlines = (s: string) => s.split('\n').map((x) => x.trim()).filter(Boolean);

function Section({ title, onRegen, busy, children }: { title: string; onRegen?: () => void; busy?: boolean; children: React.ReactNode }) {
  const t = useT();
  return (
    <div className="sec">
      <div className="sec-h"><h3>{title}</h3><span className="sp" />
        {onRegen && <button className="btn sm ghost" disabled={busy} onClick={onRegen}>↻ {t.regenerate}</button>}</div>
      {children}
    </div>
  );
}

function ListArea({ value, onChange, rows = 3 }: { value: string[]; onChange: (v: string[]) => void; rows?: number }) {
  const t = useT();
  const [txt, setTxt] = useState(lines(value));
  return <textarea className="in" rows={Math.max(rows, value.length + 1)} value={txt} placeholder={t.onePerLine}
    onChange={(e) => { setTxt(e.target.value); onChange(unlines(e.target.value)); }} />;
}

function MinutesEditor({ id, value, onSaved, onRegen, busy }: {
  id: string; value: Minutes; onSaved: () => void; onRegen: (s: string) => void; busy: boolean;
}) {
  const t = useT();
  const [m, setM] = useState<Minutes>(value);
  const [dirty, setDirty] = useState(false);
  const up = (patch: Partial<Minutes>) => { setM((x) => ({ ...x, ...patch })); setDirty(true); };
  const save = () => api.saveMinutes(id, m).then(() => { setDirty(false); onSaved(); });

  return (
    <div className="grid2">
      <div className="card">
        <Section title={t.discussion} onRegen={() => onRegen('discussion')} busy={busy}>
          {m.discussion.map((dsc, i) => (
            <div className="topic" key={i}>
              <div className="row" style={{ marginBottom: 4 }}>
                <input className="in" style={{ fontWeight: 700 }} value={dsc.topic}
                  onChange={(e) => up({ discussion: m.discussion.map((x, j) => j === i ? { ...x, topic: e.target.value } : x) })} />
                <button className="btn sm ghost" style={{ flex: '0 0 auto' }} onClick={() => up({ discussion: m.discussion.filter((_, j) => j !== i) })}>✕</button>
              </div>
              <ListArea value={dsc.points} onChange={(v) => up({ discussion: m.discussion.map((x, j) => j === i ? { ...x, points: v } : x) })} />
            </div>
          ))}
          <button className="btn sm" onClick={() => up({ discussion: [...m.discussion, { topic: '', points: [] }] })}>+ {t.topic}</button>
        </Section>
        <Section title={t.decisions} onRegen={() => onRegen('decisions')} busy={busy}>
          <ListArea value={m.decisions} onChange={(v) => up({ decisions: v })} />
        </Section>
        <Section title={t.actions} onRegen={() => onRegen('action_items')} busy={busy}>
          <table className="t">
            <thead><tr><th>#</th><th>{t.task}</th><th style={{ width: 150 }}>{t.owner}</th><th style={{ width: 120 }}>{t.due}</th><th /></tr></thead>
            <tbody>{m.action_items.map((a, i) => (
              <tr key={i}><td className="gold">A{i + 1}</td>
                {(['task', 'owner', 'due'] as const).map((k) => (
                  <td key={k}><input className="in" value={a[k]} onChange={(e) => up({ action_items: m.action_items.map((x, j) => j === i ? { ...x, [k]: e.target.value } : x) })} /></td>))}
                <td><button className="btn sm ghost" onClick={() => up({ action_items: m.action_items.filter((_, j) => j !== i) })}>✕</button></td></tr>))}
            </tbody>
          </table>
          <button className="btn sm" style={{ marginTop: 6 }} onClick={() => up({ action_items: [...m.action_items, { task: '', owner: '', due: '' }] })}>+ {t.addRow}</button>
        </Section>
      </div>
      <div>
        <div className="card">
          <div className="row" style={{ marginBottom: 10 }}>
            <span className={dirty ? 'gold' : 'dim'}>{dirty ? '● unsaved' : '✓'}</span>
            <button className="btn gold" style={{ flex: '0 0 auto' }} disabled={!dirty} onClick={save}>{t.save}</button>
          </div>
          <Section title={t.attendees} onRegen={() => onRegen('attendees')} busy={busy}>
            <ListArea value={m.attendees.map((a) => a.role ? `${a.name} — ${a.role}` : a.name)}
              onChange={(v) => up({ attendees: v.map((s) => { const [name, ...r] = s.split(' — '); return { name, role: r.join(' — ') }; }) })} />
          </Section>
          <Section title="Agenda" onRegen={() => onRegen('agenda')} busy={busy}><ListArea value={m.agenda} onChange={(v) => up({ agenda: v })} /></Section>
          <Section title={t.issues} onRegen={() => onRegen('open_issues')} busy={busy}><ListArea value={m.open_issues} onChange={(v) => up({ open_issues: v })} /></Section>
          <Section title={t.nextMeeting}><input className="in" value={m.next_meeting} onChange={(e) => up({ next_meeting: e.target.value })} /></Section>
        </div>
      </div>
    </div>
  );
}

function SummaryEditor({ id, value, onSaved, onRegen, busy }: {
  id: string; value: Minutes; onSaved: () => void; onRegen: (s: string) => void; busy: boolean;
}) {
  const t = useT();
  const [m, setM] = useState(value);
  const [dirty, setDirty] = useState(false);
  return (
    <div className="card" style={{ maxWidth: 900 }}>
      <Section title={t.tldr} onRegen={() => onRegen('tldr')} busy={busy}>
        <ListArea value={m.tldr} onChange={(v) => { setM({ ...m, tldr: v }); setDirty(true); }} />
      </Section>
      <Section title={t.executive} onRegen={() => onRegen('executive_summary')} busy={busy}>
        <textarea className="in" rows={9} value={m.executive_summary} onChange={(e) => { setM({ ...m, executive_summary: e.target.value }); setDirty(true); }} />
      </Section>
      <button className="btn gold" disabled={!dirty} onClick={() => api.saveMinutes(id, m).then(() => { setDirty(false); onSaved(); })}>{t.save}</button>
    </div>
  );
}
