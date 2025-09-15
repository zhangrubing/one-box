
// Global registry for redraw on theme changes
if (!globalThis.__MiniLineRegistry) globalThis.__MiniLineRegistry = new Set();
if (typeof globalThis.__MiniLineThemeObserverInstalled === 'undefined') globalThis.__MiniLineThemeObserverInstalled = false;
const __MiniLineRegistry = globalThis.__MiniLineRegistry;

export class MiniLine{
  constructor(el, opt={}){
    // el can be a canvas element or a string id
    if (typeof el === 'string') el = document.getElementById(el);
    this.el = el || null;
    this.noop = !this.el;
    this.c = this.noop ? null : this.el.getContext('2d');
    this.max = opt.max||300; this.data = []; this.yMin = opt.yMin ?? 0; this.yMax = opt.yMax ?? 100;
    this.axes = opt.axes || false; this.ticks = opt.ticks || [0,25,50,75,100];
    this.xLabels = opt.xLabels || ["-60s","-30s","now"];
    // optional xTicks generator for timeMode: function(t0, t1) -> [{p:0..1,label:""}, ...]
    this.xTicks = opt.xTicks || null;
    // time-mode: map points by ts within [t0, t1]
    this.timeMode = !!opt.timeMode; // if true, expect points as {ts, v}
    this.t0 = opt.t0 || 0; this.t1 = opt.t1 || 0; // seconds unix
    if (!this.noop){
      const dpr = window.devicePixelRatio||1; this.el.width=this.el.clientWidth*dpr; this.el.height=this.el.clientHeight*dpr; this.c.scale(dpr,dpr);
      window.addEventListener('resize', ()=>{ const dpr=window.devicePixelRatio||1; this.el.width=this.el.clientWidth*dpr; this.el.height=this.el.clientHeight*dpr; this.c.setTransform(1,0,0,1,0,0); this.c.scale(dpr,dpr); this.draw(); });
      // register for global redraw
      try{ __MiniLineRegistry.add(this); }catch(e){}
      if (!globalThis.__MiniLineThemeObserverInstalled){
        try{
          const mo = new MutationObserver((muts)=>{
            for (const m of muts){ if (m.attributeName === 'data-theme'){ requestAnimationFrame(()=>{
              __MiniLineRegistry.forEach(inst=>{ try{ inst.draw(); }catch(e){} });
            }); break; } }
          });
          mo.observe(document.documentElement, { attributes: true });
          globalThis.__MiniLineThemeObserverInstalled = true;
        }catch(e){}
      }
    } else {
      // soft warn, but don't crash
      console.warn('[MiniLine] canvas not found, drawing disabled.');
    }
  }
  push(v, tsSec){
    if(this.noop) return;
    if(this.timeMode){
      const ts = Number.isFinite(tsSec)? Number(tsSec) : Math.floor(Date.now()/1000);
      // dedupe: if last has same ts, overwrite
      const last = this.data[this.data.length-1];
      if(last && last.ts === ts){ last.v = v; }
      else { this.data.push({ts, v}); }
      // window trim if t0 set
      if(this.t0 && this.t1){ while(this.data.length && this.data[0].ts < this.t0) this.data.shift(); }
      // hard cap
      if(this.data.length>this.max) this.data.shift();
    }else{
      this.data.push({t:Date.now(), v}); if(this.data.length>this.max) this.data.shift();
    }
    this.draw();
  }
  setRange(a,b){ if(this.noop) return; this.yMin=a; this.yMax=b; this.draw(); }
  setXLabels(lbls){ if(this.noop) return; if(Array.isArray(lbls)) this.xLabels = lbls; this.draw(); }
  setWindow(t0, t1){ this.t0 = Number(t0)||0; this.t1 = Number(t1)||0; if(this.timeMode){ // trim to window
    while(this.data.length && this.data[0].ts < this.t0) this.data.shift(); }
    this.draw(); }
  clear(){ if(this.noop) return; this.c.clearRect(0,0,this.el.clientWidth,this.el.clientHeight); }
  draw(){
    if(this.noop) return;
    const {c,el}=this; const W=el.clientWidth, H=el.clientHeight; this.clear();
    const cs = getComputedStyle(document.documentElement);
    const brand = cs.getPropertyValue('--brand').trim()||'#3b82f6';
    const muted = cs.getPropertyValue('--muted').trim()||'#94a3b8';
    const border= cs.getPropertyValue('--border').trim()||'#24324a';
    const padL = this.axes ? 36 : 6, padB = this.axes ? 18 : 4, padT = 4, padR = 6;
    const w = Math.max(0, W - padL - padR), h = Math.max(0, H - padT - padB);
    if(this.axes){
      c.strokeStyle = border; c.lineWidth=1;
      c.beginPath(); c.moveTo(padL, padT); c.lineTo(padL, padT+h); c.lineTo(padL+w, padT+h); c.stroke();
      c.font="11px ui-sans-serif,system-ui"; c.fillStyle=muted;
      const yr = (this.yMax - this.yMin) || 1;
      this.ticks.forEach(t => {
        const y = padT + (1 - (t - this.yMin)/yr) * h;
        c.strokeStyle = border; c.beginPath(); c.moveTo(padL, y); c.lineTo(padL+w, y); c.stroke();
        c.fillText(String(t), 4, y+4);
      });
      // X axis ticks: prefer xTicks in timeMode, else fallback to labels
      if(this.timeMode && typeof this.xTicks === 'function' && this.t1>this.t0){
        const ticks = this.xTicks(this.t0, this.t1) || [];
        ticks.forEach(tk=>{
          const p = Math.min(1, Math.max(0, Number(tk.p)||0));
          const x = padL + p*w;
          c.fillText(String(tk.label||''), x-12, padT+h+14);
          c.strokeStyle = border; c.beginPath(); c.moveTo(x, padT+h-4); c.lineTo(x, padT+h); c.stroke();
        });
      } else {
        const labels = this.xLabels || ["-60s","-30s","now"];
        [0, 0.5, 1].forEach((p,i)=>{ const x = padL + p*w; c.fillText(labels[i]||"", x-12, padT+h+14); });
      }
    }
    c.strokeStyle=brand; c.lineWidth=2;
    if(!this.data.length) return;
    const ymin = this.yMin, ymax = this.yMax || 100; const yr = (ymax - ymin) || 1;
    c.beginPath();
    if(this.timeMode && this.t1>this.t0){
      const span = this.t1 - this.t0;
      for(let i=0;i<this.data.length;i++){
        const p = this.data[i];
        const ts = Math.min(Math.max(p.ts, this.t0), this.t1);
        const x = padL + ((ts - this.t0)/span) * w;
        const y = padT + h - ((p.v - ymin) / yr) * h;
        if(i===0) c.moveTo(x,y); else c.lineTo(x,y);
      }
    }else{
      // legacy index-based placement
      const n = this.data.length;
      const dx = w/Math.max(1,this.max-1);
      const start = this.max - n;
      for(let i=0;i<n;i++){
        const x = padL + (start + i)*dx;
        const y = padT + h - ((this.data[i].v - ymin) / yr) * h;
        if(i===0) c.moveTo(x,y); else c.lineTo(x,y);
      }
    }
    c.stroke();
  }
}

MiniLine.prototype.destroy = function(){ try{ __MiniLineRegistry.delete(this); }catch(e){} };
