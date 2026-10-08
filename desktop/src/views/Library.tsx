import { useEffect, useState } from 'react';
import { api, fmtDate, fmtDur, Meeting } from '../api';
import { useT } from '../i18n';

export default function LibraryView({ open, newMeeting }: { open: (id: string) => void; newMeeting: () => void }) {
  const t = useT();
  const [items, setItems] = useState<Meeting[]>([]);
  const [q, setQ] = useState('');
  const [hits, setHits] = useState<any[] | null>(null);
  const [err, setErr] = useState('');

  useEffect(() => {
    const load = () => api.meetings().then(setItems).catch((e) => setErr(e.message));
    load();
    const iv = setInterval(load, 4000);
    return () => clearInterval(iv);
  }, []);

  useEffect(() => {
    if (!q.trim()) { setHits(null); return; }
    const h = setTimeout(() => api.search(q).then(setHits).catch(() => setHits([])), 220);
    return () => clearTimeout(h);
  }, [q]);

  return (
    <div className="page">
      <div className="head">
        <div><div className="kicker">{items.length} meetings</div><h1>{t.library}</h1></div>
        <div className="sp" />
        <input className="in" style={{ width: 420 }} placeholder={t.search} value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="btn gold" onClick={newMeeting}>+ {t.newMeeting}</button>
      </div>
      {err && <div className="err">{err}</div>}

      {hits ? (
        <div className="card">
          <h2>{hits.length} results</h2>
          {hits.map((h, i) => (
            <div key={i} className="hit" onClick={() => open(h.meeting_id)}>
              <div><b>{h.title}</b> <span className="badge">{h.kind}</span> <span className="dim">{fmtDate(h.started_at)}</span></div>
              <div className="muted">{h.snippet}</div>
            </div>
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="card empty">{t.noMeetings}</div>
      ) : (
        <div className="card" style={{ padding: 0 }}>
          <table className="t">
            <thead><tr><th>{t.title}</th><th>{t.platform}</th><th>{t.date}</th><th>{t.duration}</th><th>Lang</th><th>{t.status}</th></tr></thead>
            <tbody>
              {items.map((m) => (
                <tr key={m.id} className="click" onClick={() => open(m.id)}>
                  <td><b>{m.title}</b></td>
                  <td><span className="badge plat">{m.platform}</span></td>
                  <td className="muted">{fmtDate(m.started_at)}</td>
                  <td className="muted">{fmtDur(m.duration_s)}</td>
                  <td className="muted">{(m.language || '—').toUpperCase()}</td>
                  <td><span className={`badge ${m.status}`}>{m.status}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
