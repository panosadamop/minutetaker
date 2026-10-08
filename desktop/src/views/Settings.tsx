import { useEffect, useState } from 'react';
import { api } from '../api';
import { Lang, useT } from '../i18n';

export default function SettingsView({ onLang }: { onLang: (l: Lang) => void }) {
  const t = useT();
  const [data, setData] = useState<any>(null);
  const [s, setS] = useState<any>(null);
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');
  const [tplName, setTplName] = useState('formal');

  const load = () => api.settings().then((x) => { setData(x); setS(x.settings); });
  useEffect(() => { load().catch((e) => setErr(e.message)); }, []);
  if (!s) return <div className="page">{err ? <div className="err">{err}</div> : '…'}</div>;

  const set = (k: string, v: any) => setS((x: any) => ({ ...x, [k]: v }));
  const flash = (m: string) => { setMsg(m); setTimeout(() => setMsg(''), 2000); };

  async function save() {
    try {
      await api.saveSettings(s);
      for (const [k, v] of Object.entries(keys)) if (v.trim()) await api.saveSecret(k, v);
      setKeys({}); await load(); onLang(s.ui_language); flash(t.saved);
    } catch (e: any) { setErr(e.message); }
  }

  const sel = (k: string, opts: [string, string][]) => (
    <select className="in" value={s[k] ?? ''} onChange={(e) => set(k, e.target.value)}>{opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>);
  const inp = (k: string, ph = '') => <input className="in" value={s[k] ?? ''} placeholder={ph} onChange={(e) => set(k, e.target.value)} />;
  const key = (name: string, label: string) => (
    <label className="f"><span>{label} · <span className={data.secrets[name] ? 'cyan' : 'red'}>{data.secrets[name] ? t.keySet : t.keyMissing}</span></span>
      <input className="in" type="password" value={keys[name] || ''} placeholder={data.secrets[name] ? '••••••••••••' : ''}
        onChange={(e) => setKeys({ ...keys, [name]: e.target.value })} /></label>);

  const sttDest = s.stt_provider === 'openai' ? 'OpenAI' : null;
  const llmDest = { claude: 'Anthropic', openai: 'OpenAI', ollama: null, mock: null }[s.llm_provider as string];
  const tplText = s.custom_templates[tplName] ?? data.template_text[tplName] ?? '';

  return (
    <div className="page">
      <div className="head"><div><div className="kicker">{data.settings && 'Engine'}</div><h1>{t.settings}</h1></div><div className="sp" />
        {msg && <span className="cyan">{msg}</span>}<button className="btn gold" onClick={save}>{t.save}</button></div>
      {err && <div className="err">{err}</div>}
      <div className="grid2">
        <div>
          <div className="card">
            <h2>{t.stt}<span className="sp" /><span className={sttDest ? 'gold' : 'cyan'}>{sttDest ? `${t.dataGoesTo} ${sttDest}` : t.localOnly}</span></h2>
            <div className="row">
              <label className="f"><span>Engine</span>{sel('stt_provider', [['local', 'Local · faster-whisper'], ['openai', 'Cloud · OpenAI'], ['mock', 'Demo (no model)']])}</label>
              <label className="f"><span>{t.meetingLanguage}</span>{sel('language', [['auto', 'Auto-detect'], ['el', t.greek], ['en', t.english]])}</label>
            </div>
            {s.stt_provider === 'local' && <div className="row">
              <label className="f"><span>Model</span>{sel('whisper_model', [['auto', 'Auto · base on CPU, small on GPU'], ['tiny', 'tiny · fastest'], ['base', 'base · fast'], ['small', 'small · more accurate'], ['medium', 'medium · better Greek'], ['large-v3', 'large-v3 · best (GPU)']])}</label>
              <label className="f"><span>Device</span>{sel('whisper_device', [['auto', 'Auto'], ['cpu', 'CPU'], ['cuda', 'NVIDIA GPU']])}</label>
            </div>}
            {s.stt_provider === 'openai' && <label className="f"><span>Model</span>{inp('openai_stt_model')}</label>}
            <label className="f"><span>Speaker separation</span>{sel('diarization', [['auto', 'Auto (pyannote if installed)'], ['pyannote', 'pyannote.audio'], ['tracks', 'Me vs. participants only']])}</label>
          </div>
          <div className="card">
            <h2>{t.llm}<span className="sp" /><span className={llmDest ? 'gold' : 'cyan'}>{llmDest ? `${t.dataGoesTo} ${llmDest}` : t.localOnly}</span></h2>
            <label className="f"><span>Provider</span>{sel('llm_provider', [['claude', 'Claude (Anthropic)'], ['openai', 'OpenAI'], ['ollama', 'Ollama (local)'], ['mock', 'Demo (heuristic)']])}</label>
            {s.llm_provider === 'claude' && <label className="f"><span>Model</span>{inp('claude_model')}</label>}
            {s.llm_provider === 'openai' && <label className="f"><span>Model</span>{inp('openai_model')}</label>}
            {s.llm_provider === 'ollama' && <div className="row"><label className="f"><span>Model</span>{inp('ollama_model')}</label><label className="f"><span>URL</span>{inp('ollama_url')}</label></div>}
            <div className="row">
              <label className="f"><span>{t.outputLanguage}</span>{sel('output_language', [['same', t.same], ['el', t.greek], ['en', t.english]])}</label>
              <label className="f"><span>Default {t.template}</span>{sel('default_template', data.templates.map((x: string) => [x, x]))}</label>
            </div>
          </div>
          <div className="card">
            <h2>{t.apiKeys}</h2>
            {key('anthropic_api_key', 'Anthropic (Claude)')}
            {key('openai_api_key', 'OpenAI')}
            {key('hf_token', 'Hugging Face (pyannote)')}
            <div className="dim">Keys are stored in the OS keychain when available.</div>
          </div>
        </div>
        <div>
          <div className="card">
            <h2>{t.templates}</h2>
            <div className="row" style={{ marginBottom: 8 }}>
              <select className="in" value={tplName} onChange={(e) => setTplName(e.target.value)}>{data.templates.map((x: string) => <option key={x}>{x}</option>)}</select>
              <button className="btn sm" style={{ flex: '0 0 auto' }} onClick={() => { const n = prompt('Template name')?.trim(); if (n) { set('custom_templates', { ...s.custom_templates, [n]: tplText }); setData({ ...data, templates: [...data.templates, n] }); setTplName(n); } }}>+ New</button>
            </div>
            <textarea className="in" rows={6} value={tplText} onChange={(e) => set('custom_templates', { ...s.custom_templates, [tplName]: e.target.value })} />
            <div className="dim">Instruction given to the LLM. The output structure (attendees, decisions, actions…) stays fixed.</div>
          </div>
          <div className="card">
            <h2>{t.branding}</h2>
            <label className="f"><span>{t.company}</span>{inp('company_name', 'Netcompany')}</label>
            <label className="f"><span>{t.logo}</span>
              <div className="row"><input className="in" value={s.logo_path || ''} readOnly />
                {window.mt && <button className="btn sm" style={{ flex: '0 0 auto' }} onClick={async () => { const p = await window.mt!.pickImage(); if (p) set('logo_path', p); }}>{t.choose}</button>}
                {s.logo_path && <button className="btn sm ghost" style={{ flex: '0 0 auto' }} onClick={() => set('logo_path', null)}>✕</button>}</div></label>
            <div className="dim">PDF export {data.pdf_available ? 'available (LibreOffice found)' : 'needs LibreOffice installed'}.</div>
          </div>
          <div className="card">
            <h2>{t.storage}</h2>
            <label className="f"><span>{t.retention}</span><input className="in" type="number" min={0} value={s.retention_days} onChange={(e) => set('retention_days', Number(e.target.value))} /></label>
            <label className="f"><span>{t.uiLanguage}</span>{sel('ui_language', [['en', 'English'], ['el', 'Ελληνικά']])}</label>
          </div>
        </div>
      </div>
    </div>
  );
}
