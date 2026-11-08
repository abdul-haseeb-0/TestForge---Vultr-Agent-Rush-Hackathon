import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, Download, FolderUp, LoaderCircle, RotateCcw, ShieldCheck, Upload, Wrench, XCircle } from 'lucide-react';

type Check = { id: string; name: string; status: string; detail: string; screenshot: string; seconds: number };
type Suite = { label: string; checks: Check[] };
type Patch = { id: string; path: string; explanation: string; risk: string; reason: string; status: string; diff: string; new_content: string; edited?: boolean };
type Iter = { n: number; diagnosis: string; patches: Patch[]; outcome: string; fixed: string[]; regressions: string[] };
type Job = { id: string; name: string; status: string; message: string; busy: boolean; stack: string[]; settings: { max_iterations: number; auto_low: boolean; sandbox: string }; suites: Suite[]; current?: Suite; iterations: Iter[] };

const STEPS = ['Upload', 'Baseline tests', 'AI diagnosis', 'Human approval', 'Apply & verify', 'Deliver'];
const stepOf = (s: string) => ({ queued: 0, analyzing: 1, diagnosing: 2, awaiting_approval: 3, applying: 4, verifying: 4 } as Record<string, number>)[s] ?? 5;
const shot = (id: string, f: string) => `/api/repair/${id}/files/shots/${f}`;

async function call(path: string, init?: RequestInit) {
  const r = await fetch(path, init);
  if (!r.ok) { const b = await r.json().catch(() => ({})); throw new Error(typeof b.detail === 'string' ? b.detail : `API error ${r.status}`); }
  return r.json();
}
const post = (path: string, body?: unknown) => call(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body ?? {}) });

export default function Repair({ onOpenSettings }: { onOpenSettings: () => void }) {
  const [aiOk, setAiOk] = useState(true);
  const [jobs, setJobs] = useState<{ id: string; name: string; status: string }[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [gitUrl, setGitUrl] = useState('');
  const [maxIter, setMaxIter] = useState(5);
  const [auto, setAuto] = useState(false);
  const [start, setStart] = useState('');
  const [port, setPort] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const folder = useRef<HTMLInputElement>(null);
  const sel = useRef('');

  const refresh = async () => {
    try {
      const l = await call('/api/repair'); setJobs(l.items || []);
      call('/api/settings/ai').then(s => setAiOk(!!s.configured)).catch(() => undefined);
      if (!sel.current && l.items?.[0]) sel.current = l.items[0].id;
      if (sel.current) setJob(await call(`/api/repair/${sel.current}`));
    } catch { /* backend offline: keep last state */ }
  };
  useEffect(() => { void refresh(); const t = window.setInterval(() => void refresh(), 2000); return () => window.clearInterval(t); }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setErr('');
    try {
      const fd = new FormData();
      files.forEach(f => { fd.append('files', f); fd.append('paths', (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name); });
      fd.append('git_url', gitUrl); fd.append('max_iterations', String(maxIter)); fd.append('auto_approve_low_risk', String(auto));
      fd.append('start_command', start); fd.append('port', port || '0');
      const j = await call('/api/repair', { method: 'POST', body: fd });
      sel.current = j.id; setJob(j); setFiles([]); setGitUrl('');
    } catch (x) { setErr(x instanceof Error ? x.message : 'Upload failed'); } finally { setBusy(false); }
  }
  const act = async (fn: () => Promise<unknown>) => { setErr(''); try { await fn(); await refresh(); } catch (x) { setErr(x instanceof Error ? x.message : 'Action failed'); } };

  const working = job && (job.busy || ['queued', 'analyzing', 'diagnosing', 'applying', 'verifying'].includes(job.status));
  const last = job?.iterations[job.iterations.length - 1];
  const waiting = job?.status === 'awaiting_approval' && !job.busy;
  const undecided = last?.patches.filter(p => p.status === 'proposed').length ?? 0;

  return <>
    <div className="heading"><div><small>TESTFORGE WORKSPACE</small><h1>AI Repair & Verification</h1><p>Upload a project. TestForge runs it in a sandbox, finds failures, proposes fixes you approve, re-runs everything, and delivers evidence.</p></div></div>
    <section className="panel"><div className="panel-head"><div><b>New repair job</b><small>ZIP, files, a folder, or a public Git URL</small></div><label>HUMAN-IN-THE-LOOP</label></div>
      <form className="rp-form" onSubmit={create}>
        <div className="rp-pick">
          <label className="rp-btn"><Upload size={14} /> ZIP / files<input type="file" multiple hidden onChange={e => setFiles(Array.from(e.target.files || []))} /></label>
          <label className="rp-btn"><FolderUp size={14} /> Folder<input ref={folder} type="file" multiple hidden {...({ webkitdirectory: '' } as object)} onChange={e => setFiles(Array.from(e.target.files || []))} /></label>
          <input className="rp-in" placeholder="…or https://github.com/user/repo" value={gitUrl} onChange={e => setGitUrl(e.target.value)} />
        </div>
        {files.length > 0 && <small className="rp-note">{files.length} file(s) selected</small>}
        <div className="rp-pick">
          <label className="rp-lbl">Max repair loops<input className="rp-in sm" type="number" min={1} max={10} value={maxIter} onChange={e => setMaxIter(+e.target.value)} /></label>
          <label className="rp-lbl">Start command (optional)<input className="rp-in" placeholder="npm run dev -- --host 0.0.0.0" value={start} onChange={e => setStart(e.target.value)} /></label>
          <label className="rp-lbl">Port<input className="rp-in sm" value={port} onChange={e => setPort(e.target.value.replace(/\D/g, ''))} placeholder="3000" /></label>
        </div>
        <label className="rp-check"><input type="checkbox" checked={auto} onChange={e => setAuto(e.target.checked)} /> Auto-approve low-risk patches (config, dependency, schema and test-file changes always need your approval)</label>
        <div className="scan-bottom"><span><ShieldCheck size={13} /> Runs only inside the Docker sandbox; original is preserved for rollback</span><button disabled={busy || (!files.length && !gitUrl)}>{busy ? <><LoaderCircle className="spin" /> Uploading</> : <><Wrench size={14} /> Start repair</>}</button></div>
      </form>
    </section>
    {!aiOk && <p className="error">No AI API key yet. Tests will run, but fixes can’t be proposed until you add your key. <button type="button" className="rp-btn" onClick={onOpenSettings}>Open Settings</button></p>}
    {err && <p className="error">{err}</p>}
    {jobs.length > 1 && <div className="rp-jobs">{jobs.map(j => <button key={j.id} className={j.id === job?.id ? 'chosen' : ''} onClick={() => { sel.current = j.id; void refresh(); }}>{j.name.slice(0, 28)} · {j.status}</button>)}</div>}

    {job && <>
      <section className="panel"><div className="panel-head"><div><b>{job.name}</b><small>{job.stack.join(' · ') || 'Detecting stack…'} · iteration {job.iterations.length}/{job.settings.max_iterations} · sandbox: {job.settings.sandbox}</small></div><label className={`rp-status ${job.status}`}>{job.status.replace('_', ' ').toUpperCase()}</label></div>
        <div className="rp-steps">{STEPS.map((s, i) => <span key={s} className={i < stepOf(job.status) ? 'done' : i === stepOf(job.status) ? 'now' : ''}>{i + 1}. {s}</span>)}</div>
        <p className="summary">{working && <LoaderCircle className="spin" size={13} />} {job.message}</p>
        <div className="panel-actions">
          {waiting && <button disabled={undecided > 0} onClick={() => act(() => post(`/api/repair/${job.id}/apply`))}>Apply approved patches & re-verify {undecided > 0 && `(${undecided} undecided)`}</button>}
          {!working && ['exhausted', 'stalled', 'needs_attention', 'rolled_back'].includes(job.status) && <button onClick={() => act(() => post(`/api/repair/${job.id}/continue`))}>Continue repair loop</button>}
          {!working && job.iterations.some(i => i.patches.some(p => p.status === 'applied')) && <button onClick={() => act(() => post(`/api/repair/${job.id}/rollback`, { to_iteration: 0 }))}><RotateCcw size={13} /> Roll back to original</button>}
          {!working && job.suites.length > 0 && <a className="rp-dl" href={`/api/repair/${job.id}/download`}><Download size={13} /> {job.status === 'verified' ? 'Download corrected project' : 'Download partial (unverified) package'}</a>}
        </div>
      </section>

      {waiting && last && <section className="panel"><div className="panel-head"><div><b>Patch review — iteration {last.n}</b><small>{last.diagnosis}</small></div><label>{last.patches.length} PATCHES</label></div>
        {last.patches.map(p => <PatchCard key={p.id + p.status + p.diff.length} p={p} onDecide={(d, content, confirm) => act(() => post(`/api/repair/${job.id}/patches/${p.id}`, { decision: d, edited_content: content, confirm_sensitive: confirm }))} />)}
      </section>}

      {job.current && <section className="panel"><div className="panel-head"><div><b>Checks & screenshot evidence</b><small>Before vs latest accepted state. Only executed checks appear; nothing is assumed passed.</small></div></div>
        {job.current.checks.map(c => { const b = job.suites[0]?.checks.find(x => x.id === c.id);
          return <div className="rp-check-row" key={c.id}><div><b>{c.id} · {c.name}</b><small>before: <i className={`rp-dot ${b?.status}`} />{b?.status || '-'} → now: <i className={`rp-dot ${c.status}`} />{c.status} · {c.seconds}s</small>
            {c.status !== 'passed' && <pre>{c.detail.slice(-900)}</pre>}</div>
            <div className="rp-shots">{b?.screenshot && <a href={shot(job.id, b.screenshot)} target="_blank" rel="noreferrer"><img src={shot(job.id, b.screenshot)} alt="before" /><span>before</span></a>}{c.screenshot && c.screenshot !== b?.screenshot && <a href={shot(job.id, c.screenshot)} target="_blank" rel="noreferrer"><img src={shot(job.id, c.screenshot)} alt="after" /><span>latest</span></a>}</div></div>; })}
      </section>}

      {job.iterations.length > 0 && <section className="panel"><div className="panel-head"><div><b>Repair history</b><small>Every loop, its outcome, and what was caught</small></div></div>
        {job.iterations.map(i => <div className="rp-hist" key={i.n}><b>Iteration {i.n}: {i.outcome || 'awaiting decision'}</b><small>{i.diagnosis.slice(0, 220)}</small>
          <small>{i.patches.map(p => `${p.path} [${p.status}]`).join(' · ')}</small>{i.fixed.length > 0 && <small className="ok"><CheckCircle2 size={12} /> fixed: {i.fixed.join(', ')}</small>}{i.regressions.length > 0 && <small className="bad"><XCircle size={12} /> regression caught & rolled back: {i.regressions.join(', ')}</small>}</div>)}
      </section>}
    </>}
  </>;
}

function PatchCard({ p, onDecide }: { p: Patch; onDecide: (d: string, content?: string, confirm?: boolean) => void }) {
  const [edit, setEdit] = useState(false); const [text, setText] = useState(p.new_content); const [ok, setOk] = useState(false);
  const sens = p.risk === 'sensitive';
  return <article className="finding"><span className={`severity ${sens ? 'high' : 'low'}`}>{sens ? 'sensitive' : 'low risk'}</span><div style={{ flex: 1, minWidth: 0 }}>
    <b>{p.path} <small>[{p.status}]</small></b><p>{p.explanation}</p>
    {sens && <label className="rp-check"><input type="checkbox" checked={ok} onChange={e => setOk(e.target.checked)} /> I understand: {p.reason}</label>}
    {edit ? <textarea className="rp-edit" rows={14} value={text} onChange={e => setText(e.target.value)} /> : <pre className="rp-diff">{p.diff.split('\n').map((l, i) => <div key={i} className={l.startsWith('+') && !l.startsWith('+++') ? 'add' : l.startsWith('-') && !l.startsWith('---') ? 'del' : ''}>{l || ' '}</div>)}</pre>}
    <div className="panel-actions">
      <button disabled={sens && !ok} onClick={() => onDecide(edit ? 'edit' : 'approve', edit ? text : undefined, ok)}>{edit ? 'Approve edited version' : 'Approve'}</button>
      <button onClick={() => onDecide('reject')}>Reject</button>
      <button onClick={() => setEdit(!edit)}>{edit ? 'Show diff' : 'Edit'}</button>
    </div></div></article>;
}
