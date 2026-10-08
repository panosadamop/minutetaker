import { useEffect, useRef, useState } from 'react';
import { api, fmtTs, PLATFORM } from '../api';
import { I18n, PLATFORMS, useT } from '../i18n';
import { useContext } from 'react';

type Dev = { id: string; name: string; default?: boolean };

export default function RecordView({ recordingId, setRecording, open }: {
  recordingId: string | null; setRecording: (id: string | null) => void; open: (id: string) => void;
}) {
  const t = useT();
  const { lang } = useContext(I18n);
  const [devs, setDevs] = useState<{ microphones: Dev[]; system: Dev[]; error?: string; note?: string }>({ microphones: [], system: [] });
  const [form, setForm] = useState({ title: '', platform: 'MS Teams', participants_hint: '', agenda: '', mic_id: '', system_id: '', use_mic: true, use_system: true });
  const [templates, setTemplates] = useState<string[]>(['formal']);
  const [template, setTemplate] = useState('formal');
  const [status, setStatus] = useState<any>({ state: 'idle', elapsed: 0, levels: {} });
  const [consent, setConsent] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const [accept, setAccept] = useState('audio/*,video/*,.vtt,.srt,.txt,.docx,.pdf,.zip');
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasted, setPasted] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.devices().then(setDevs).catch((e) => setErr(e.message));
    api.settings().then((s) => {
      setTemplates(s.templates); setTemplate(s.settings.default_template);
      const types = s.import_types;
      if (types) setAccept(['audio/*', 'video/*', ...types.media, ...types.transcript].join(','));
    }).catch(() => undefined);
  }, []);

  // live levels / timer
  useEffect(() => {
    if (!recordingId) return;
    const ws = api.liveSocket();
    ws.onmessage = (e) => setStatus(JSON.parse(e.data));
    return () => ws.close();
  }, [recordingId]);

  const set = (k: string, v: any) => setForm((f) => ({ ...f, [k]: v }));
  // engine marks the device it will use when nothing is picked (mic: the headset's own mic if any)
  const dflt = (list: Dev[]) => { const d = list.find((x) => x.default); return d ? ` · ${d.name}` : ''; };

  async function askConsent() {
    setErr('');
    const { text } = await api.consent(lang);
    setConsent(text);
  }

  async function start() {
    setConsent(null); setBusy(true);
    try {
      const r = await api.startRec({ ...form, mic_id: form.mic_id || null, system_id: form.system_id || null });
      setRecording(r.meeting.id); setStatus(r.status);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  async function stop() {
    setBusy(true);
    try {
      const r = await api.stopRec(template);
      setRecording(null); open(r.meeting.id);
    } catch (e: any) { setErr(e.message); setRecording(null); } finally { setBusy(false); }
  }

  async function importFile(f: File) {
    setBusy(true); setErr('');
    const fd = new FormData();
    fd.append('file', f);
    fd.append('title', form.title || f.name.replace(/\.[^.]+$/, ''));
    fd.append('platform', form.platform);
    fd.append('participants_hint', form.participants_hint);
    fd.append('agenda', form.agenda);
    fd.append('template', template);
    try { const r = await api.importFile(fd); open(r.meeting.id); } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  async function importText() {
    setBusy(true); setErr('');
    try {
      const r = await api.importText({ text: pasted, title: form.title, platform: form.platform,
        participants_hint: form.participants_hint, agenda: form.agenda, template });
      setPasted(''); open(r.meeting.id);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  const live = status.state === 'recording' || status.state === 'paused';
  const lv = (k: string) => Math.min(100, Math.sqrt(status.levels?.[k] || 0) * 260);

  return (
    <div className="page">
      <div className="head"><div><div className="kicker">{t.newMeeting}</div><h1>{t.record}</h1></div></div>
      {err && <div className="err">{err}</div>}
      <div className="grid2">
        <div>
          <div className="card">
            <h2>Meeting</h2>
            <div className="row">
              <label className="f"><span>{t.title}</span><input className="in" value={form.title} onChange={(e) => set('title', e.target.value)} placeholder="Weekly steering committee" disabled={live} /></label>
              <label className="f" style={{ flex: '0 0 170px' }}><span>{t.platform}</span>
                <select className="in" value={form.platform} onChange={(e) => set('platform', e.target.value)}>{PLATFORMS.map((p) => <option key={p}>{p}</option>)}</select></label>
            </div>
            <label className="f"><span>{t.participants}</span><input className="in" value={form.participants_hint} onChange={(e) => set('participants_hint', e.target.value)} placeholder={t.participantsHint} /></label>
            <label className="f"><span>{t.agenda}</span><textarea className="in" rows={2} value={form.agenda} onChange={(e) => set('agenda', e.target.value)} /></label>
            <label className="f" style={{ marginBottom: 0 }}><span>{t.template}</span>
              <select className="in" value={template} onChange={(e) => setTemplate(e.target.value)}>{templates.map((x) => <option key={x}>{x}</option>)}</select></label>
          </div>

          <div className="card">
            <h2>Audio sources</h2>
            {devs.error && <div className="err">{devs.error}</div>}
            <div className="row">
              <label className="f"><span><label className="chk"><input type="checkbox" checked={form.use_mic} onChange={(e) => set('use_mic', e.target.checked)} disabled={live} />{t.microphone}</label></span>
                <select className="in" value={form.mic_id} onChange={(e) => set('mic_id', e.target.value)} disabled={live || !form.use_mic}>
                  <option value="">{t.defaultDevice}{dflt(devs.microphones)}</option>{devs.microphones.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label>
              <label className="f"><span><label className="chk"><input type="checkbox" checked={form.use_system} onChange={(e) => set('use_system', e.target.checked)} disabled={live} />{t.systemAudio}</label></span>
                <select className="in" value={form.system_id} onChange={(e) => set('system_id', e.target.value)} disabled={live || !form.use_system}>
                  <option value="">{t.defaultDevice}{dflt(devs.system)}</option>{devs.system.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label>
            </div>
            {PLATFORM === 'darwin' && <div className="dim">{t.macNote}</div>}
          </div>
        </div>

        <div>
          <div className="card recbox">
            <div className={`timer ${status.state === 'recording' ? 'live' : ''}`}>{fmtTs(live ? status.elapsed : 0)}</div>
            <div className="muted">{status.state === 'recording' ? <><span className="dot" style={{ display: 'inline-block', marginRight: 6 }} />{t.recording}</> : status.state === 'paused' ? t.paused : ' '}</div>
            <div className="meters">
              <span>MIC</span><div className="meter mic"><i style={{ width: `${live ? lv('mic') : 0}%` }} /></div>
              <span>SYSTEM</span><div className="meter"><i style={{ width: `${live ? lv('system') : 0}%` }} /></div>
            </div>
            {status.errors && Object.keys(status.errors).length > 0 && <div className="err">{JSON.stringify(status.errors)}</div>}
            {!live ? (
              <button className="btn gold big" onClick={askConsent} disabled={busy || (!form.use_mic && !form.use_system)}>● {t.start}</button>
            ) : (
              <div className="row tight">
                {status.state === 'recording'
                  ? <button className="btn" onClick={() => api.pauseRec().then(setStatus)}>❚❚ {t.pause}</button>
                  : <button className="btn" onClick={() => api.resumeRec().then(setStatus)}>▶ {t.resume}</button>}
                <button className="btn gold" onClick={stop} disabled={busy}>■ {t.stop}</button>
              </div>
            )}
          </div>

          <div className="card">
            <h2>{t.importFile}</h2>
            <div className={`drop ${over ? 'over' : ''}`} onClick={() => fileRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
              onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f) importFile(f); }}>
              {busy ? t.processing + '…' : t.importHint}
            </div>
            <input ref={fileRef} type="file" hidden accept={accept}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) importFile(f); e.target.value = ''; }} />
            {!pasteOpen ? (
              <button className="btn ghost sm" style={{ marginTop: 8 }} onClick={() => setPasteOpen(true)}>✎ {t.pasteTranscript}</button>
            ) : (
              <div style={{ marginTop: 10 }}>
                <textarea className="in" rows={8} value={pasted} onChange={(e) => setPasted(e.target.value)}
                  placeholder={t.pastePlaceholder} autoFocus />
                <div className="row tight" style={{ justifyContent: 'flex-end', marginTop: 8 }}>
                  <button className="btn ghost" onClick={() => { setPasteOpen(false); setPasted(''); }}>{t.cancel}</button>
                  <button className="btn gold" disabled={busy || !pasted.trim()} onClick={importText}>{busy ? t.processing + '…' : t.importText}</button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {consent !== null && (
        <div className="modal-bg" onClick={() => setConsent(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>⚠ {t.consentTitle}</h3>
            <div className="muted">{t.consentBody}</div>
            <div className="notice">{consent}</div>
            <div className="row tight" style={{ justifyContent: 'flex-end' }}>
              <button className="btn" onClick={() => { navigator.clipboard.writeText(consent); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>{copied ? t.copied : t.copy}</button>
              <button className="btn ghost" onClick={() => setConsent(null)}>{t.cancel}</button>
              <button className="btn gold" onClick={start}>{t.confirmConsent}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
