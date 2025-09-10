export async function apiGet(url) {
  const r = await fetch(url, {credentials:'include'});
  if (r.status === 401) { location.href='/login'; return; }
  if (!r.ok) throw new Error(await r.text());
  return await r.json();
}
export async function apiPost(url, data) {
  const r = await fetch(url, { method:'POST', credentials:'include', headers:{'Content-Type':'application/json'}, body: JSON.stringify(data||{}) });
  if (r.status === 401) { location.href='/login'; return; }
  if (!r.ok) throw new Error(await r.text());
  return await r.json();
}
export async function apiDelete(url) {
  const r = await fetch(url, {method:'DELETE', credentials:'include'});
  if (r.status === 401) { location.href='/login'; return; }
  if (!r.ok) throw new Error(await r.text());
  return await r.json();
}
export function mountSSE(url, onmessage) {
  const es = new EventSource(url, {withCredentials: true});
  es.onmessage = (e)=>{ try { onmessage(JSON.parse(e.data), e); } catch(err) { console.warn(err); } };
  es.addEventListener('metrics', (e)=>{ try { onmessage(JSON.parse(e.data), e); } catch(err) { console.warn(err); } });
  es.addEventListener('log', (e)=>{ try { onmessage(JSON.parse(e.data), e); } catch(err) { console.warn(err); } });
  es.onerror = ()=>{};
  return es;
}
export function $(sel, parent) { return (parent||document).querySelector(sel); }
export function $all(sel, parent) { return Array.from((parent||document).querySelectorAll(sel)); }
export function formatBytes(n) { if (n==null) return '-'; const u=['B','KB','MB','GB','TB','PB']; let i=0; while (n>=1024 && i<u.length-1) { n/=1024; i++; } return n.toFixed(1)+' '+u[i]; }
export function ts(t){ const d=new Date(t*1000); return d.toLocaleString(); }
export function fmtUptime(sec){ const d=Math.floor(sec/86400); sec%=86400; const h=Math.floor(sec/3600); sec%=3600; const m=Math.floor(sec/60); const s=sec%60; return `${d}天 ${h}小时 ${m}分 ${s}秒`; }
export async function logout() { await apiPost('/api/logout', {}); location.href='/login'; }
