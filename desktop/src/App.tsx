import { useEffect, useState } from 'react';
import { api, init } from './api';
import { DICTS, I18n, Lang } from './i18n';
import RecordView from './views/Record';
import LibraryView from './views/Library';
import MeetingView from './views/Meeting';
import SettingsView from './views/Settings';

export type Route = { name: 'record' } | { name: 'library' } | { name: 'settings' } | { name: 'meeting'; id: string };

export default function App() {
  const [ready, setReady] = useState(false);
  const [bootErr, setBootErr] = useState('');
  const [route, setRoute] = useState<Route>({ name: 'library' });
  const [lang, setLang] = useState<Lang>('en');
  const [recording, setRecording] = useState<string | null>(null);
  const [engineDown, setEngineDown] = useState(false);

  useEffect(() => {
    init().then(async () => {
      const s = await api.settings();
      setLang(s.settings.ui_language === 'el' ? 'el' : 'en');
      const st = await api.recStatus();
      if (st.state === 'recording' || st.state === 'paused') { setRecording(st.meeting_id); setRoute({ name: 'record' }); }
      setReady(true);
    }).catch((e) => setBootErr(String(e.message || e)));
    window.mt?.onEngineExit(() => setEngineDown(true));
  }, []);

  const t = DICTS[lang];
  if (bootErr) return <div className="empty"><p className="red">{bootErr}</p></div>;
  if (!ready) return <div className="empty"><div className="brand"><b>MINUTE</b><i>TAKER</i></div><p className="muted">Starting engine…</p></div>;

  const nav = (r: Route, k: string, label: string) => (
    <button className={`nav ${route.name === r.name ? 'on' : ''}`} onClick={() => setRoute(r)}><span className="k">{k}</span>{label}</button>
  );

  return (
    <I18n.Provider value={{ t, lang }}>
      <div className="app">
        <aside className="side">
          <div className="brand"><b>MINUTE</b><i>TAKER</i></div>
          {nav({ name: 'record' }, '●', t.record)}
          {nav({ name: 'library' }, '≡', t.library)}
          {nav({ name: 'settings' }, '⚙', t.settings)}
          {recording && route.name !== 'record' && (
            <button className="rec-pill" onClick={() => setRoute({ name: 'record' })}><span className="dot" />{t.recording}</button>
          )}
          <div className="foot">v1.0 · local-first<br />Teams · Meet · Zoom · Viber · WhatsApp</div>
        </aside>
        <main className="main">
          {engineDown && <div className="err" style={{ margin: 12 }}>{t.engineDown}</div>}
          {route.name === 'record' && <RecordView recordingId={recording} setRecording={setRecording} open={(id) => setRoute({ name: 'meeting', id })} />}
          {route.name === 'library' && <LibraryView open={(id) => setRoute({ name: 'meeting', id })} newMeeting={() => setRoute({ name: 'record' })} />}
          {route.name === 'meeting' && <MeetingView id={route.id} back={() => setRoute({ name: 'library' })} />}
          {route.name === 'settings' && <SettingsView onLang={setLang} />}
        </main>
      </div>
    </I18n.Provider>
  );
}
