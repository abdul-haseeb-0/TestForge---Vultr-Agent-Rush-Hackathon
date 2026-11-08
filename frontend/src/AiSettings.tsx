import { useEffect, useState } from 'react';
import { CheckCircle2, KeyRound, LoaderCircle, ShieldCheck, Trash2 } from 'lucide-react';

type AiState = { configured: boolean; last4: string; source: string; base_url: string; model: string };
const PRESETS: [string, string][] = [['Vultr Inference', 'https://api.vultrinference.com/v1'], ['OpenAI', 'https://api.openai.com/v1'], ['OpenRouter', 'https://openrouter.ai/api/v1']];

const TOKEN_KEY = 'testforge_admin_token';
async function call(path: string, method = 'GET', body?: unknown) {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  const token = sessionStorage.getItem(TOKEN_KEY); if (token) headers['X-Admin-Token'] = token;
  const r = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  const j = await r.json().catch(() => ({}));
  if (r.status === 401) throw new Error('ADMIN_TOKEN_REQUIRED');
  if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : `API error ${r.status}`);
  return j;
}

export default function AiSettings({ onChange }: { onChange?: () => void }) {
  const [st, setSt] = useState<AiState | null>(null);
  const [key, setKey] = useState(''); const [url, setUrl] = useState(''); const [model, setModel] = useState('');
  const [needToken, setNeedToken] = useState(false); const [token, setToken] = useState('');
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null); const [busy, setBusy] = useState('');

  const load = async () => { try { const s: AiState = await call('/api/settings/ai'); setSt(s); setUrl(s.base_url); setModel(s.model); } catch (e) { if (e instanceof Error && e.message === 'ADMIN_TOKEN_REQUIRED') setNeedToken(true); } };
  useEffect(() => { void load(); }, []);
  const run = async (name: string, fn: () => Promise<void>) => { setBusy(name); setMsg(null); try { await fn(); } catch (e) { if (e instanceof Error && e.message === 'ADMIN_TOKEN_REQUIRED') { setNeedToken(true); setMsg({ ok: false, text: 'This server requires an admin token. Enter it below, then try again.' }); } else setMsg({ ok: false, text: e instanceof Error ? e.message : 'Failed' }); } finally { setBusy(''); } };

  const save = () => run('save', async () => { const s: AiState = await call('/api/settings/ai', 'PUT', { api_key: key || null, base_url: url, model }); setSt(s); setKey(''); setMsg({ ok: true, text: 'Saved. The key is encrypted in your PostgreSQL database and is never shown again.' }); onChange?.(); });
  const test = () => run('test', async () => { const r = await call('/api/settings/ai/test', 'POST'); setMsg({ ok: r.ok, text: r.message }); });
  const remove = () => run('remove', async () => { setSt(await call('/api/settings/ai', 'DELETE')); setMsg({ ok: true, text: 'API key removed.' }); onChange?.(); });

  return <section className="panel"><div className="panel-head"><div><b><KeyRound size={14} /> AI provider (your own API key)</b><small>Used for scan explanations and AI repair patches. Any OpenAI-compatible endpoint.</small></div>
    <label className={st?.configured ? 'ai-label' : ''}>{st?.configured ? `KEY ••••${st.last4} (${st.source})` : 'NOT CONFIGURED'}</label></div>
    <div className="rp-form">
      {needToken && <label className="rp-lbl">ADMIN TOKEN<input className="rp-in" type="password" autoComplete="off" value={token} onChange={e => { setToken(e.target.value); sessionStorage.setItem(TOKEN_KEY, e.target.value); }} onBlur={() => void load()} placeholder="SETTINGS_ADMIN_TOKEN from the server" /></label>}
      <label className="rp-lbl">API KEY<input className="rp-in" type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} placeholder={st?.configured ? 'Leave empty to keep the current key' : 'Paste your API key'} /></label>
      <div className="rp-pick">{PRESETS.map(p => <button type="button" className="rp-btn" key={p[0]} onClick={() => setUrl(p[1])}>{p[0]}</button>)}</div>
      <div className="rp-pick"><label className="rp-lbl">BASE URL<input className="rp-in" value={url} onChange={e => setUrl(e.target.value)} /></label><label className="rp-lbl">MODEL<input className="rp-in" value={model} onChange={e => setModel(e.target.value)} placeholder="model name from your provider" /></label></div>
      <div className="panel-actions">
        <button disabled={!!busy || (!key && !st?.configured)} onClick={save}>{busy === 'save' ? <LoaderCircle className="spin" size={13} /> : 'Save'}</button>
        <button disabled={!!busy || !st?.configured} onClick={test}>{busy === 'test' ? <LoaderCircle className="spin" size={13} /> : 'Test connection'}</button>
        {st?.source === 'ui' && <button disabled={!!busy} onClick={remove}><Trash2 size={13} /> Remove key</button>}
      </div>
      {msg && <p className={msg.ok ? 'rp-note' : 'error'}>{msg.ok && <CheckCircle2 size={12} />} {msg.text}</p>}
      <small className="rp-note"><ShieldCheck size={12} /> The key is sent only to this backend, stored encrypted (Fernet) in PostgreSQL, and never returned by the API. Uploaded projects never see it.</small>
    </div></section>;
}
