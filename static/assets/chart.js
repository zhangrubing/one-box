
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
    if (!this.noop){
      const dpr = window.devicePixelRatio||1; this.el.width=this.el.clientWidth*dpr; this.el.height=this.el.clientHeight*dpr; this.c.scale(dpr,dpr);
      window.addEventListener('resize', ()=>{ const dpr=window.devicePixelRatio||1; this.el.width=this.el.clientWidth*dpr; this.el.height=this.el.clientHeight*dpr; this.c.setTransform(1,0,0,1,0,0); this.c.scale(dpr,dpr); this.draw(); });
    } else {
      // soft warn, but don't crash
      console.warn('[MiniLine] canvas not found, drawing disabled.');
    }
  }
  push(v){ if(this.noop) return; this.data.push({t:Date.now(), v}); if(this.data.length>this.max) this.data.shift(); this.draw(); }
  setRange(a,b){ if(this.noop) return; this.yMin=a; this.yMax=b; this.draw(); }
  setXLabels(lbls){ if(this.noop) return; if(Array.isArray(lbls)) this.xLabels = lbls; this.draw(); }
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
      const labels = this.xLabels || ["-60s","-30s","now"];
      [0, 0.5, 1].forEach((p,i)=>{ const x = padL + p*w; c.fillText(labels[i]||"", x-12, padT+h+14); });
    }
    c.strokeStyle=brand; c.lineWidth=2;
    if(!this.data.length) return;
    const n=this.data.length, dx=w/Math.max(1,n-1); const ymin=this.yMin, ymax=this.yMax||100; const yr=(ymax-ymin)||1;
    c.beginPath();
    for(let i=0;i<n;i++){ const x=padL + i*dx; const y=padT + h - ((this.data[i].v - ymin) / yr) * h; if(i===0)c.moveTo(x,y); else c.lineTo(x,y); }
    c.stroke();
  }
}
