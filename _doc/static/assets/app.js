
function ready(fn){ document.readyState!='loading' ? fn() : document.addEventListener('DOMContentLoaded',fn) }
function toggleLight(el){ document.body.classList.toggle('light', !el.checked) }
function rand(a,b){ return a + Math.random()*(b-a) }
function sparkline(canvasId, points, color){
  const ctx = document.getElementById(canvasId).getContext('2d');
  const w = ctx.canvas.width, h = ctx.canvas.height, pad=10;
  const max = Math.max(...points), min = Math.min(...points);
  ctx.clearRect(0,0,w,h);
  ctx.globalAlpha=.15; ctx.strokeStyle='#9aa4b2';
  for(let i=0;i<4;i++){ ctx.beginPath(); const y=pad+(h-2*pad)*i/3; ctx.moveTo(pad,y); ctx.lineTo(w-pad,y); ctx.stroke() }
  ctx.globalAlpha=1; ctx.strokeStyle=color; ctx.lineWidth=2; ctx.beginPath();
  points.forEach((v,i)=>{
     const x = pad + (w-2*pad)*i/(points.length-1);
     const y = pad + (h-2*pad)*(1-(v-min)/(max-min+1e-6));
     i?ctx.lineTo(x,y):ctx.moveTo(x,y);
  });
  ctx.stroke();
}
// Logout + show user chip (static demo)
function logout(){
  try{ localStorage.removeItem('onebox_user'); }catch(e){}
  location.href = 'login.html';
}
ready(()=>{
  const act = document.querySelector('header.top .actions');
  if(act && !act.querySelector('.btn.logout')){
    const btn = document.createElement('button');
    btn.className = 'btn logout';
    btn.textContent = '退出';
    btn.onclick = logout;
    act.appendChild(btn);
  }
  try{
    const data = JSON.parse(localStorage.getItem('onebox_user')||'{}');
    if(data.u){
      const chip = document.createElement('div');
      chip.className = 'tag';
      chip.textContent = '用户: ' + data.u;
      const act2 = document.querySelector('header.top .actions');
      act2 && act2.appendChild(chip);
    }
  }catch(e){}
});
if(!CanvasRenderingContext2D.prototype.roundRect){
  CanvasRenderingContext2D.prototype.roundRect=function(x,y,w,h,r){r=Math.min(r,w/2,h/2);this.beginPath();this.moveTo(x+r,y);this.arcTo(x+w,y,x+w,y+h,r);this.arcTo(x+w,y+h,x,y+h,r);this.arcTo(x,y+h,x,y,r);this.arcTo(x,y,x+w,y,r);this.closePath();return this;}
}
