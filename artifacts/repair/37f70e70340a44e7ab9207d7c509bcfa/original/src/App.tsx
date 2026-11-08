import { useEffect, useMemo, useState } from 'react';
import { Activity, ArrowUpRight, Bug, CheckCircle2, ExternalLink, FileText, Globe2, LoaderCircle, Play, Radar, ShieldCheck, Sparkles, Zap, Settings, Wrench } from 'lucide-react';
import Repair from './Repair';

type Finding = { id: number; severity: string; category: string; title: string; description: string; evidence: string; recommendation: string };
type Run = { id: string; target_url: string; status: string; created_at: string; finished_at?: string; summary: string; score: number; error: string; execution_mode: string; findings: Finding[]; evidence?: { pages?: { url: string; title: string; http_status?: number | null; screenshot: string; viewport_screenshot: string; forms: number }[]; coverage?: { pages_discovered: number; pages_visited: number; page_limit: number; crawl_truncated: boolean; forms_observed: number; workflow_steps: number }; workflow_checks?: { step: number; action: string; status: string; url?: string; error?: string; screenshot?: string }[] } };
type Config = { ai_configured: boolean; runner_mode: string; production_sandbox_configured?: boolean };
type Page = 'Overview' | 'AI Repair' | 'Test runs' | 'Fix proposals' | 'Reports' | 'Security & containment' | 'Integrations' | 'Settings';

async function api(path: string, init?: RequestInit) {
  const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...init });
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || `API error ${response.status}`); }
  return response.json();
}

const navigation: { label: Page; icon: React.ReactNode; group: string }[] = [
  { label: 'Overview', icon: <Activity />, group: 'WORKSPACE' },
  { label: 'AI Repair', icon: <Wrench />, group: 'WORKSPACE' },
  { label: 'Test runs', icon: <Bug />, group: 'WORKSPACE' },
  { label: 'Fix proposals', icon: <Sparkles />, group: 'WORKSPACE' },
  { label: 'Reports', icon: <FileText />, group: 'WORKSPACE' },
  { label: 'Security & containment', icon: <ShieldCheck />, group: 'SYSTEM' },
  { label: 'Integrations', icon: <Zap />, group: 'SYSTEM' },
  { label: 'Settings', icon: <Settings />, group: 'SYSTEM' },
];

export default function App() {
  const [url, setUrl] = useState('https://example.com');
  const [depth, setDepth] = useState('standard');
  const [workflowText, setWorkflowText] = useState('');
  const [runs, setRuns] = useState<Run[]>([]);
  const [selected, setSelected] = useState('');
  const [cfg, setCfg] = useState<Config | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [online, setOnline] = useState(false);
  const [shots, setShots] = useState<{ filename: string; url: string }[]>([]);
  const [page, setPage] = useState<Page>('Overview');
  const [reportError, setReportError] = useState('');

  const refresh = async () => {
    try { const [list, config] = await Promise.all([api('/api/runs'), api('/api/config')]); setRuns(list.items || []); setCfg(config); setOnline(true); }
    catch { setOnline(false); }
  };
  useEffect(() => { void refresh(); const timer = window.setInterval(() => void refresh(), 2500); return () => window.clearInterval(timer); }, []);

  const active = runs.filter(run => ['queued', 'running'].includes(run.status)).length;
  const findings = runs.reduce((sum, run) => sum + (run.findings?.length || 0), 0);
  const completed = runs.filter(run => run.status === 'completed');
  const average = completed.length ? Math.round(completed.reduce((sum, run) => sum + run.score, 0) / completed.length) : null;
  const chosen = runs.find(run => run.id === selected) || runs[0];
  const allFindings = useMemo(() => runs.flatMap(run => (run.findings || []).map(finding => ({ ...finding, runId: run.id, target: run.target_url }))), [runs]);

  useEffect(() => {
    if (!chosen || chosen.status !== 'completed') { setShots([]); return; }
    api(`/api/runs/${chosen.id}/artifacts`).then(result => setShots(result.items || [])).catch(() => setShots([]));
  }, [chosen?.id, chosen?.status]);

  async function start(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try { const workflow = workflowText.trim() ? JSON.parse(workflowText) : []; if (!Array.isArray(workflow)) throw new Error('Workflow must be a JSON array'); const result = await api('/api/runs', { method: 'POST', body: JSON.stringify({ target_url: url, depth, workflow }) }); setSelected(result.id); setPage('Overview'); await refresh(); }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to start run'); }
    finally { setBusy(false); }
  }

  async function exportReport() {
    if (!chosen) return;
    setReportError('');
    try {
      const report = await api(`/api/runs/${chosen.id}/report`);
      const blob = new Blob([JSON.stringify({ ...report, findings: chosen.findings }, null, 2)], { type: 'application/json' });
      const href = URL.createObjectURL(blob); const anchor = document.createElement('a');
      anchor.href = href; anchor.download = `testforge-${chosen.id}.json`; anchor.click(); URL.revokeObjectURL(href);
    } catch (err) { setReportError(err instanceof Error ? err.message : 'Report export failed'); }
  }

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><span className="logo"><Radar /></span><span><b>TESTFORGE</b><small>BUILD. TEST. DETECT. FIX.</small></span></div>
      <div className="workspace"><i /> Personal workspace <span>⌄</span></div>
      {(['WORKSPACE', 'SYSTEM'] as const).map(group => <div key={group}>
        <label>{group}</label>
        {navigation.filter(item => item.group === group).map(item => <button key={item.label} className={`nav ${page === item.label ? 'active' : ''}`} onClick={() => setPage(item.label)}>{item.icon}{item.label}{item.label === 'Test runs' && <small>{runs.length}</small>}</button>)}
      </div>)}
      <div className="side-bottom"><div className="connection"><i className={online ? '' : 'off'} />{online ? 'API connected' : 'API disconnected'}<small>{cfg?.runner_mode || 'waiting for backend'} runner</small></div><div className="profile"><b>TF</b><span>TestForge workspace<small>Developer workspace</small></span></div></div>
    </aside>
    <main>
      <header><span>Workspace <i>/</i> <b>{page}</b></span><span className="health"><i className={online ? '' : 'off'} />{online ? 'API connected' : 'Backend unavailable'}</span></header>
      <div className="content">
        {page === 'Overview' ? <>
          <div className="heading"><div><small>✦ &nbsp; BUILD. TEST. DETECT. FIX.</small><h1>Test smarter. Build better.</h1><p>Autonomous website testing with real browser evidence and actionable fixes.</p></div><span className="live">◷ &nbsp; Live workspace</span></div>
          <section className="hero"><div className="hero-copy"><small>✧ &nbsp; AI-POWERED QA</small><h2>Test smarter.<br /><em>Build better.</em></h2><p>Build confidence in every release. TestForge explores real pages, checks behavior, captures evidence, and turns verified observations into actionable recommendations.</p><div className="ticks"><span>✓ Real browser execution</span><span>✓ Issue-specific screenshots</span><span>✓ AI-assisted diagnosis</span></div></div>
            <div className="scan"><div className="scan-head"><b><Globe2 /> New website scan</b><small>✦ SAFE MODE</small></div><form onSubmit={start}><label>WEBSITE URL</label><div className="url"><Globe2 /><input value={url} onChange={event => setUrl(event.target.value)} type="url" required placeholder="https://yourwebsite.com" /></div><label>TEST DEPTH</label><div className="depth">{[['quick', 'Quick', 'Core health'], ['standard', 'Standard', 'Links + safe buttons'], ['deep', 'Deep', 'More safe interactions']].map(item => <button type="button" className={depth === item[0] ? 'chosen' : ''} onClick={() => setDepth(item[0])} key={item[0]}><b>{item[1]}</b><small>{item[2]}</small></button>)}</div><details className="workflow-editor"><summary>Advanced: test a CRUD workflow (optional)</summary><p>Use only a staging site and dedicated test data. Steps run in order and may create or delete records when explicitly configured.</p><textarea value={workflowText} onChange={event => setWorkflowText(event.target.value)} rows={7} placeholder={'[\n  {"action":"navigate","value":"/items"},\n  {"action":"click","selector":"[data-testid=\"add-item\"]"},\n  {"action":"fill","selector":"input[name=\"name\"]","value":"TestForge QA record"},\n  {"action":"click","selector":"button[type=\"submit\"]"},\n  {"action":"assert_text","selector":"body","value":"TestForge QA record"}\n]'} /></details><div className="scan-bottom"><span>◈ Automatic scan is read-only</span><button disabled={busy || !online}>{busy ? <><LoaderCircle className="spin" /> Starting</> : <><Play size={14} fill="currentColor" /> Run test</>}</button></div>{error && <p className="error">{error}</p>}</form></div>
          </section>
          <div className="metrics"><Metric icon={<Activity />} label="TOTAL TEST RUNS" value={String(runs.length).padStart(2, '0')} note="Across this workspace" /><Metric icon={<Zap />} label="ACTIVE RUNS" value={String(active).padStart(2, '0')} note="Queued or executing" /><Metric icon={<Bug />} label="FINDINGS" value={String(findings).padStart(2, '0')} note="Observed and classified" /><Metric icon={<ShieldCheck />} label="AVG. QUALITY SCORE" value={average === null ? '—' : `${average}%`} note="Completed runs only" /></div>
          <div className="columns"><section className="panel"><div className="panel-head"><div><b>Recent test runs</b><small>Your latest website quality checks</small></div><label>{runs.length} RUNS</label></div>{!runs.length ? <Empty title="No test runs yet" text="Enter a public website URL above to start your first browser scan." /> : runs.slice(0, 10).map(run => <RunRow key={run.id} run={run} selected={chosen?.id === run.id} onClick={() => setSelected(run.id)} />)}</section>
            <section className="panel"><div className="panel-head"><div><b>Run intelligence</b><small>{chosen ? 'Selected scan analysis' : 'Waiting for first scan'}</small></div><label className="ai-label">✧ AI INSIGHTS</label></div>{chosen ? <><div className="target"><Globe2 />{chosen.target_url}<a href={chosen.target_url} target="_blank" rel="noreferrer"><ExternalLink /></a></div><div className="score"><div><small>QUALITY SCORE</small><b>{chosen.status === 'completed' ? chosen.score : '—'}<i>{chosen.status === 'completed' ? '/100' : ''}</i></b></div><div className="ring"><span>{chosen.status === 'completed' ? chosen.score : '…'}</span></div></div><p className="summary">{chosen.summary || chosen.error || 'Browser test is running...'}</p><div className="mode">◈ Execution mode: <b>{chosen.execution_mode}</b></div><div className="panel-actions"><button onClick={() => setPage('Reports')}>Open report <ArrowUpRight size={14} /></button></div></> : <Empty title="No selected scan" text="Start a test to inspect its evidence and findings." />}</section></div>
          {chosen && chosen.evidence?.coverage && <section className="panel findings"><div className="panel-head"><div><b>Website page coverage</b><small>Pages actually visited by the browser crawler</small></div><label>{chosen.evidence.coverage.pages_visited}/{chosen.evidence.coverage.page_limit} VISITED</label></div><div className="coverage-stats"><InfoRow label="Pages discovered" value={String(chosen.evidence.coverage.pages_discovered)} /><InfoRow label="Pages visited" value={String(chosen.evidence.coverage.pages_visited)} /><InfoRow label="Forms observed" value={String(chosen.evidence.coverage.forms_observed)} /><InfoRow label="Crawl status" value={chosen.evidence.coverage.crawl_truncated ? 'Page limit reached, incomplete' : 'Queue exhausted'} /></div>{(chosen.evidence.pages || []).map((item, index) => { const shot = shots.find(x => x.filename === item.screenshot); return <div className="page-coverage-row" key={item.url}><div><b>{index + 1}. {item.title || new URL(item.url).pathname}</b><small>{item.url} · HTTP {item.http_status ?? 'unknown'} · {item.forms} form(s)</small></div>{shot && <a href={shot.url} target="_blank" rel="noreferrer">Open page screenshot <ExternalLink size={12}/></a>}</div>; })}</section>}
          {chosen && <FindingsPanel run={chosen} shots={shots} />}
          {chosen && chosen.evidence?.workflow_checks?.length ? <section className="panel findings"><div className="panel-head"><div><b>CRUD / custom workflow execution</b><small>Explicitly configured browser steps</small></div><label>{chosen.evidence.workflow_checks.filter(x => x.status === 'passed').length}/{chosen.evidence.workflow_checks.length} PASSED</label></div>{chosen.evidence.workflow_checks.map(step => <div className="page-coverage-row" key={step.step}><div><b>Step {step.step}: {step.action}</b><small>{step.url || ''} {step.error || ''}</small></div><span className={`state ${step.status === 'passed' ? 'completed' : 'failed'}`}>{step.status}</span></div>)}</section> : null}
          {chosen && shots.length > 0 && <section className="panel findings"><div className="panel-head"><div><b>Browser screenshots</b><small>Captured during the actual Playwright run</small></div><label>{shots.length} ARTIFACTS</label></div><div className="screenshots">{shots.map(shot => <a key={shot.url} href={shot.url} target="_blank" rel="noreferrer"><img src={shot.url} alt={shot.filename} /><span>{shot.filename}</span></a>)}</div></section>}
        </> : page === 'AI Repair' ? <Repair /> : <OtherPage page={page} runs={runs} findings={allFindings} cfg={cfg} online={online} onSelectRun={id => { setSelected(id); setPage('Overview'); }} onExport={exportReport} reportError={reportError} />}
        <footer>TESTFORGE AI · BUILD 1.5.0 <span>VULTR SERVERLESS INFERENCE · {cfg?.ai_configured ? 'CONNECTED' : 'AI KEY NOT CONFIGURED'}</span></footer>
      </div>
    </main>
  </div>;
}

function Metric({ icon, label, value, note }: { icon: React.ReactNode; label: string; value: string; note: string }) { return <div className="metric"><div>{icon}<small>{label}</small></div><b>{value}</b><p>{note}</p></div>; }
function Empty({ title, text }: { title: string; text: string }) { return <div className="empty"><Radar /><b>{title}</b><p>{text}</p></div>; }
function RunRow({ run, selected, onClick }: { run: Run; selected: boolean; onClick: () => void }) { let host = run.target_url; try { host = new URL(run.target_url).hostname; } catch { /* keep original */ } return <button className={`run ${selected ? 'selected' : ''}`} onClick={onClick}><span className="site-icon"><Globe2 /></span><span className="run-name"><b>{host}</b><small>{new Date(run.created_at).toLocaleString()}</small></span><span className={`state ${run.status}`}>{run.status}</span><strong>{run.status === 'completed' ? `${run.score}%` : '—'}</strong><ArrowUpRight /></button>; }
function FindingsPanel({ run, shots }: { run: Run; shots: { filename: string; url: string }[] }) { return <section className="panel findings"><div className="panel-head"><div><b>Evidence & findings</b><small>Observed browser behavior, not invented results</small></div><label>{run.findings?.length || 0} FINDINGS</label></div>{run.status !== 'completed' ? <div className="empty"><LoaderCircle className="spin" /><b>Test execution {run.status}</b></div> : run.findings?.length ? run.findings.map(finding => { const evidenceShot = shots.find(shot => finding.evidence.includes(shot.filename)); return <article className="finding" key={finding.id}><span className={`severity ${finding.severity}`}>{finding.severity}</span><div><b>{finding.title}</b><p>{finding.description}</p><blockquote><small>EVIDENCE</small>{finding.evidence}</blockquote>{evidenceShot && <a className="evidence-link" href={evidenceShot.url} target="_blank" rel="noreferrer">Open issue screenshot: {evidenceShot.filename} <ExternalLink size={12} /></a>}<blockquote className="fix"><small>RECOMMENDED FIX</small>{finding.recommendation}</blockquote></div></article>; }) : <div className="clean"><CheckCircle2 /><span><b>No issues detected by the configured checks.</b><small>This does not guarantee every user journey is defect-free.</small></span></div>}</section>; }
function OtherPage({ page, runs, findings, cfg, online, onSelectRun, onExport, reportError }: { page: Page; runs: Run[]; findings: (Finding & { runId: string; target: string })[]; cfg: Config | null; online: boolean; onSelectRun: (id: string) => void; onExport: () => void; reportError: string }) {
  if (page === 'Test runs') return <><PageHeading title="Test runs" subtitle="Browse previous browser executions and open their evidence." /><section className="panel"><div className="panel-head"><div><b>All test runs</b><small>{runs.length} recorded executions</small></div></div>{runs.length ? runs.map(run => <RunRow key={run.id} run={run} selected={false} onClick={() => onSelectRun(run.id)} />) : <Empty title="No test runs" text="Your completed and active runs will appear here." />}</section></>;
  if (page === 'Fix proposals') return <><PageHeading title="Fix proposals" subtitle="Recommendations generated from observed browser findings." /><section className="panel"><div className="panel-head"><div><b>Recommended actions</b><small>These are suggestions, not automatically applied code changes.</small></div><label>{findings.length} ITEMS</label></div>{findings.length ? findings.map((finding, index) => <article className="finding" key={`${finding.runId}-${finding.id}-${index}`}><span className={`severity ${finding.severity}`}>{finding.severity}</span><div><b>{finding.title}</b><p>{finding.target}</p><blockquote className="fix"><small>RECOMMENDATION</small>{finding.recommendation}</blockquote></div></article>) : <Empty title="No proposals yet" text="Run a website test to generate evidence-based recommendations." />}</section></>;
  if (page === 'Reports') return <><PageHeading title="Reports" subtitle="Export a machine-readable report for the latest completed scan." /><section className="panel"><div className="panel-head"><div><b>Latest report</b><small>{runs[0]?.target_url || 'No report available'}</small></div></div><div className="report-action"><FileText /><div><b>{runs[0] ? `Run ${runs[0].id.slice(0, 8)}` : 'No completed runs'}</b><small>JSON export includes run metadata and findings.</small></div><button disabled={!runs.length || runs[0].status !== 'completed'} onClick={onExport}>Export JSON</button></div>{reportError && <p className="error">{reportError}</p>}</section></>;
  if (page === 'Security & containment') return <><PageHeading title="Security & containment" subtitle="Execution mode and current isolation configuration." /><section className="panel"><InfoRow label="Backend status" value={online ? 'Connected' : 'Disconnected'} /><InfoRow label="Current runner" value={cfg?.runner_mode || 'Unknown'} /><InfoRow label="Remote sandbox worker configured" value={cfg?.production_sandbox_configured ? 'Yes' : 'No'} /><div className="security-note"><ShieldCheck /><div><b>{cfg?.runner_mode === 'remote' && cfg?.production_sandbox_configured ? 'Remote worker configured' : 'Local development mode is not a security boundary'}</b><p>For hackathon production, execute every browser task in a disposable sandbox on Vultr. Verify the guest lifecycle, CPU and memory limits, network isolation, and teardown on the deployed VM before claiming containment.</p></div></div></section></>;
  if (page === 'Integrations') return <><PageHeading title="Integrations" subtitle="Connected services and execution providers." /><section className="panel"><InfoRow label="Vultr Serverless Inference" value={cfg?.ai_configured ? 'API key configured' : 'Not configured'} /><InfoRow label="Inference endpoint" value="https://api.vultrinference.com/v1" /><InfoRow label="Browser engine" value="Playwright + Chromium" /><InfoRow label="Sandbox worker" value={cfg?.production_sandbox_configured ? 'Configured' : 'Not configured'} /></section></>;
  return <><PageHeading title="Settings" subtitle="Workspace runtime information." /><section className="panel"><InfoRow label="Workspace" value="Personal workspace" /><InfoRow label="API connection" value={online ? 'Connected' : 'Disconnected'} /><InfoRow label="Runner mode" value={cfg?.runner_mode || 'Unknown'} /><InfoRow label="AI diagnosis" value={cfg?.ai_configured ? 'Enabled' : 'Disabled until API key is configured'} /></section></>;
}
function PageHeading({ title, subtitle }: { title: string; subtitle: string }) { return <div className="heading"><div><small>TESTFORGE WORKSPACE</small><h1>{title}</h1><p>{subtitle}</p></div></div>; }
function InfoRow({ label, value }: { label: string; value: string }) { return <div className="info-row"><span>{label}</span><b>{value}</b></div>; }
