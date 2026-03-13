import { useState, useEffect, useCallback, useRef } from "react";

/* ═══════════════════════════════════════════════════════════════════
   CONFIG — live API, no mock
═══════════════════════════════════════════════════════════════════ */
const API_BASE = "https://jdas-digiclone-1.onrender.com";

async function apiFetch(endpoint, options = {}) {
  const res = await fetch(`${API_BASE}${endpoint}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${res.status}${body ? ": " + body.slice(0, 120) : ""}`);
  }
  return res.json();
}

/* ═══════════════════════════════════════════════════════════════════
   DESIGN TOKENS
═══════════════════════════════════════════════════════════════════ */
const T = {
  bg:"#f4ede4", bgSub:"#ede4d8", bgCard:"#faf7f3", bgDeep:"#e8ddd0",
  bgDark:"#1c2b1e", bgDarkMid:"#243228", bgDarkSub:"#2e3d32",
  border:"#d4c4ae", borderMid:"#b8a48e", borderDark:"#3d5240",
  green:"#2d6a4f", greenMid:"#40916c", greenLight:"#74c69d",
  greenPale:"#d8f3dc", greenGlow:"#52b788",
  gold:"#b5600a", goldMid:"#d4820f", goldLight:"#f4a261", goldPale:"#fdebd0",
  red:"#9b2226", redMid:"#ae2012", redLight:"#e63946", redPale:"#fde8e8",
  blue:"#1d3557", bluePale:"#dde8f0",
  textDark:"#1a1208", textMid:"#4a3728", textSoft:"#7a6352", textLight:"#a08878",
  white:"#fffcf8", shadow:"rgba(40,20,8,0.10)", shadowMd:"rgba(40,20,8,0.16)",
  shadowLg:"rgba(40,20,8,0.26)",
};

/* ═══════════════════════════════════════════════════════════════════
   STATUS HELPERS
═══════════════════════════════════════════════════════════════════ */
const statusColor = s =>
  s==="bad"||s==="NEGATIVE CASH"||s==="OVERLOADED"||s==="High"||s==="critical" ? T.red :
  s==="warn"||s==="LOW"||s==="TIGHT"||s==="Medium" ? T.gold : T.green;
const statusPale  = s =>
  s==="bad"||s==="NEGATIVE CASH"||s==="OVERLOADED"||s==="High"||s==="critical" ? T.redPale :
  s==="warn"||s==="LOW"||s==="TIGHT"||s==="Medium" ? T.goldPale : T.greenPale;
const cashStatus  = d => d?.cash?.status==="NEGATIVE CASH"||d?.cash?.status==="CRITICAL" ? "bad" : d?.cash?.status==="LOW" ? "warn" : "good";
const workStatus  = d => (d?.workload?.stress_score||0)>70 ? "bad" : (d?.workload?.stress_score||0)>40 ? "warn" : "good";
const qualStatus  = d => (d?.quality?.score||0)<60 ? "bad" : (d?.quality?.score||0)<80 ? "warn" : "good";
const pipeStatus  = d => (d?.pipeline?.win_rate||0)<0.35 ? "bad" : (d?.pipeline?.win_rate||0)<0.45 ? "warn" : "good";

function xpLevel(xp) {
  if (xp>=90) return { level:5, title:"Business Legend",   color:T.goldMid  };
  if (xp>=70) return { level:4, title:"Running Smooth",    color:T.greenMid };
  if (xp>=50) return { level:3, title:"Getting Traction",  color:T.greenMid };
  if (xp>=30) return { level:2, title:"Finding Your Feet", color:T.goldMid  };
  return             { level:1, title:"Tough Week",         color:T.redMid   };
}

const ACHIEVEMENTS = [
  { id:"cash_pos",  icon:"💰", name:"In the Green",     desc:"More coming in than going out"       },
  { id:"regular",   icon:"🤝", name:"First Regular",    desc:"Signed your first regular client"    },
  { id:"helper",    icon:"🧰", name:"Not Alone",        desc:"Hired your first helper"             },
  { id:"happy",     icon:"😊", name:"Happy Customers",  desc:"Customer happiness hit 80+"          },
  { id:"breathing", icon:"🌬️", name:"Room to Breathe", desc:"Work pile under control"             },
  { id:"pipeline",  icon:"🔧", name:"Jobs Coming In",   desc:"Landing more than 1 job/week"        },
  { id:"steady",    icon:"📅", name:"Steady Income",    desc:"Recurring covers half your costs"    },
  { id:"legend",    icon:"🏆", name:"Business Legend",  desc:"Business score hit 90"               },
];

/* ═══════════════════════════════════════════════════════════════════
   SHARED PRIMITIVES
═══════════════════════════════════════════════════════════════════ */
function HealthBar({ val, max=100, invert=false, size="md" }) {
  const pct = Math.min(100, Math.max(0, (val/max)*100));
  const eff = invert ? 100-pct : pct;
  const col = eff>66 ? T.green : eff>33 ? T.gold : T.red;
  const h   = size==="lg" ? 20 : size==="md" ? 13 : 8;
  return (
    <div style={{height:h,background:T.bgDeep,borderRadius:h,overflow:"hidden",
      border:`1.5px solid ${col}33`,boxShadow:`inset 0 2px 4px ${T.shadow}`}}>
      <div style={{height:"100%",width:`${eff}%`,
        background:`linear-gradient(90deg,${col}bb,${col})`,
        borderRadius:h,boxShadow:`0 0 10px ${col}55`,
        transition:"width 0.8s cubic-bezier(0.34,1.56,0.64,1)",position:"relative"}}>
        <div style={{position:"absolute",top:"15%",left:"6%",width:"28%",height:"40%",
          background:"rgba(255,255,255,0.28)",borderRadius:h}}/>
      </div>
    </div>
  );
}

function XPStrip({ xp }) {
  const { level, title, color } = xpLevel(xp);
  return (
    <div style={{display:"flex",flexDirection:"column",gap:7}}>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center"}}>
        <div style={{display:"flex",gap:5}}>
          {Array.from({length:5},(_,i) => (
            <span key={i} style={{fontSize:19,lineHeight:1,
              filter:i<level?"none":"grayscale(1) opacity(0.15)",
              transition:`filter 0.4s ${i*0.1}s`}}>⭐</span>
          ))}
        </div>
        <span style={{fontSize:12,fontWeight:800,color,letterSpacing:0.3}}>{title}</span>
      </div>
      <div style={{height:9,background:T.bgDeep,borderRadius:9,overflow:"hidden",
        border:`1.5px solid ${color}33`}}>
        <div style={{height:"100%",width:`${xp}%`,borderRadius:9,
          background:`linear-gradient(90deg,${color}88,${color})`,
          boxShadow:`0 0 10px ${color}66`,
          transition:"width 1s cubic-bezier(0.34,1.56,0.64,1)"}}/>
      </div>
      <div style={{fontSize:10,color:T.textLight,textAlign:"right",fontWeight:600}}>
        Business Score: {xp} / 100
      </div>
    </div>
  );
}

function BadgeShelf({ badges }) {
  const [hov, setHov] = useState(null);
  return (
    <div style={{display:"flex",gap:9,flexWrap:"wrap"}}>
      {ACHIEVEMENTS.map(a => {
        const earned = badges?.[a.id] || false;
        return (
          <div key={a.id}
            onMouseEnter={()=>setHov(a.id)}
            onMouseLeave={()=>setHov(null)}
            style={{position:"relative",width:50,height:50,borderRadius:13,
              background:earned?T.goldPale:T.bgDeep,
              border:`2px solid ${earned?T.goldMid:T.border}`,
              display:"flex",alignItems:"center",justifyContent:"center",
              fontSize:23,cursor:"default",
              filter:earned?"none":"grayscale(1) opacity(0.2)",
              boxShadow:earned?`0 3px 12px ${T.goldMid}44`:"none",
              transition:"all 0.3s",
              transform:hov===a.id?"scale(1.14) translateY(-2px)":"scale(1)"}}>
            {a.icon}
            {hov===a.id && (
              <div style={{position:"absolute",bottom:"115%",left:"50%",
                transform:"translateX(-50%)",background:T.bgDark,color:T.white,
                borderRadius:10,padding:"8px 13px",fontSize:11,whiteSpace:"nowrap",
                zIndex:30,pointerEvents:"none",boxShadow:`0 6px 24px ${T.shadowMd}`,minWidth:164}}>
                <div style={{fontWeight:800,marginBottom:3}}>{a.name}</div>
                <div style={{opacity:0.65,fontSize:10}}>{a.desc}</div>
                <div style={{marginTop:4,fontSize:10,color:earned?T.greenLight:"#ff9a8b"}}>
                  {earned?"✓ Earned":"🔒 Not yet"}
                </div>
                <div style={{position:"absolute",bottom:-6,left:"50%",transform:"translateX(-50%)",
                  width:0,height:0,borderLeft:"6px solid transparent",
                  borderRight:"6px solid transparent",borderTop:`6px solid ${T.bgDark}`}}/>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function MetricCard({ icon, title, status, children }) {
  const col = statusColor(status);
  const pale = statusPale(status);
  return (
    <div style={{background:T.bgCard,borderRadius:18,border:`1.5px solid ${T.border}`,
      borderTop:`4px solid ${col}`,padding:"18px 20px",
      boxShadow:`0 2px 14px ${T.shadow}`}}>
      <div style={{display:"flex",alignItems:"center",gap:9,marginBottom:14}}>
        <div style={{width:35,height:35,borderRadius:11,background:pale,
          border:`1.5px solid ${col}33`,display:"flex",alignItems:"center",
          justifyContent:"center",fontSize:17,flexShrink:0}}>{icon}</div>
        <span style={{fontSize:13,fontWeight:800,color:T.textMid,
          textTransform:"uppercase",letterSpacing:0.8}}>{title}</span>
        <div style={{marginLeft:"auto",width:9,height:9,borderRadius:"50%",
          background:col,boxShadow:`0 0 8px ${col}88`,flexShrink:0}}/>
      </div>
      {children}
    </div>
  );
}

function MiniStat({ label, val, status }) {
  return (
    <div style={{background:T.bgDeep,borderRadius:10,padding:"9px 12px",
      border:`1px solid ${T.border}55`}}>
      <div style={{fontSize:10,color:T.textLight,marginBottom:3,fontWeight:600}}>{label}</div>
      <div style={{fontSize:15,fontWeight:800,color:status?statusColor(status):T.textDark}}>{val}</div>
    </div>
  );
}

function Spinner({ size=32 }) {
  return (
    <div style={{width:size,height:size,border:`3px solid ${T.border}`,
      borderTop:`3px solid ${T.greenMid}`,borderRadius:"50%",
      animation:"spin 0.8s linear infinite",flexShrink:0}}/>
  );
}

function StatusBanner({ banner }) {
  if (!banner) return null;
  const issues = banner.issues || [];
  const wins   = banner.wins   || [];
  const s   = issues.length>=2 ? "bad" : issues.length===1 ? "warn" : "good";
  const col  = statusColor(s);
  const pale = statusPale(s);
  return (
    <div style={{background:pale,border:`2px solid ${col}44`,
      borderLeft:`5px solid ${col}`,borderRadius:14,padding:"14px 20px"}}>
      <div style={{fontSize:15,fontWeight:800,marginBottom:7,fontFamily:"'Playfair Display',serif",
        color:s==="bad"?T.redMid:s==="warn"?T.goldMid:T.greenMid}}>
        {banner.headline}
      </div>
      {issues.map((t,i) => (
        <div key={i} style={{fontSize:13,color:T.textMid,display:"flex",gap:8,
          alignItems:"flex-start",marginBottom:4}}>
          <span style={{color:col,flexShrink:0,marginTop:1}}>▸</span>{t}
        </div>
      ))}
      {wins.length>0 && (
        <div style={{display:"flex",gap:14,flexWrap:"wrap",
          marginTop:issues.length>0?10:0}}>
          {wins.map((t,i) => (
            <div key={i} style={{fontSize:12,color:T.green,display:"flex",gap:6,fontWeight:600}}>
              <span>✓</span>{t}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   EMPTY STATE — shown when no data yet in Dataverse
═══════════════════════════════════════════════════════════════════ */
function EmptyState({ onOpenWizard }) {
  return (
    <div style={{display:"flex",flexDirection:"column",alignItems:"center",
      justifyContent:"center",padding:"60px 40px",textAlign:"center",gap:24}}>
      <div style={{width:88,height:88,borderRadius:24,background:T.bgDeep,
        border:`2px dashed ${T.borderMid}`,display:"flex",alignItems:"center",
        justifyContent:"center",fontSize:42}}>
        📋
      </div>
      <div>
        <div style={{fontSize:22,fontWeight:900,color:T.textDark,
          fontFamily:"'Playfair Display',serif",marginBottom:10}}>
          No data yet
        </div>
        <div style={{fontSize:14,color:T.textSoft,lineHeight:1.7,maxWidth:420}}>
          The dashboard is connected and ready. Run the weekly check-in to
          enter your first set of numbers — the engine will calculate everything
          from there.
        </div>
      </div>
      <button onClick={onOpenWizard}
        style={{padding:"14px 32px",borderRadius:12,background:T.green,border:"none",
          color:T.white,fontSize:14,fontWeight:800,cursor:"pointer",fontFamily:"inherit",
          boxShadow:`0 6px 20px ${T.green}44`,letterSpacing:0.3,
          transition:"transform 0.2s, box-shadow 0.2s"}}
        onMouseEnter={e=>{e.currentTarget.style.transform="translateY(-2px)";e.currentTarget.style.boxShadow=`0 10px 28px ${T.green}55`;}}
        onMouseLeave={e=>{e.currentTarget.style.transform="";e.currentTarget.style.boxShadow=`0 6px 20px ${T.green}44`;}}>
        ✏️ Start Weekly Check-In
      </button>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   BADGE TOAST
═══════════════════════════════════════════════════════════════════ */
function BadgeToast({ badge, onDone }) {
  useEffect(() => { const t = setTimeout(onDone, 3800); return () => clearTimeout(t); }, []);
  return (
    <div style={{position:"fixed",top:82,right:24,zIndex:500,
      background:T.bgDark,color:T.white,borderRadius:18,padding:"14px 22px",
      boxShadow:`0 14px 40px ${T.shadowLg}`,border:`1.5px solid ${T.goldMid}66`,
      display:"flex",alignItems:"center",gap:14,
      animation:"toastIn 0.38s cubic-bezier(0.34,1.56,0.64,1) forwards",maxWidth:310}}>
      <div style={{fontSize:34}}>{badge.icon}</div>
      <div>
        <div style={{fontSize:11,color:T.goldLight,fontWeight:700,letterSpacing:1,
          textTransform:"uppercase",marginBottom:3}}>Badge Unlocked</div>
        <div style={{fontSize:15,fontWeight:800}}>{badge.name}</div>
        <div style={{fontSize:11,color:"#9ab09e",marginTop:2}}>{badge.desc}</div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   WEEKLY CHECK-IN WIZARD
═══════════════════════════════════════════════════════════════════ */
const WIZARD_STEPS = [
  { id:"cash",     icon:"💵", title:"Money",          subtitle:"Cash on hand + monthly expenses"   },
  { id:"projects", icon:"📋", title:"Active Work",    subtitle:"Projects + hours remaining"         },
  { id:"team",     icon:"👷", title:"Your Team",      subtitle:"Capacity, rate, helpers"            },
  { id:"leads",    icon:"📣", title:"Leads & Clients",subtitle:"New enquiries + regular clients"    },
  { id:"review",   icon:"✅", title:"Review & Save",  subtitle:"Confirm and push to dashboard"      },
];

function WizardField({ label, hint, children }) {
  return (
    <div>
      <label style={{fontSize:12,fontWeight:700,color:T.textMid,display:"block",marginBottom:6}}>
        {label}
        {hint && <span style={{fontSize:11,color:T.textLight,fontWeight:400,marginLeft:8}}>{hint}</span>}
      </label>
      {children}
    </div>
  );
}

function WizardInput({ prefix, suffix, type="number", placeholder, value, onChange }) {
  return (
    <div style={{display:"flex",alignItems:"center",background:T.bgCard,
      border:`2px solid ${T.border}`,borderRadius:12,overflow:"hidden",
      focusWithin:`border-color:${T.greenMid}`}}>
      {prefix && (
        <span style={{padding:"0 13px",fontSize:15,color:T.textSoft,fontWeight:700,
          background:T.bgDeep,alignSelf:"stretch",display:"flex",alignItems:"center",
          borderRight:`1px solid ${T.border}`}}>{prefix}</span>
      )}
      <input type={type} placeholder={placeholder} value={value||""}
        onChange={onChange}
        style={{flex:1,padding:"12px 14px",fontSize:15,fontWeight:700,
          background:"transparent",border:"none",outline:"none",
          fontFamily:"'Playfair Display',serif",color:T.textDark}}/>
      {suffix && (
        <span style={{padding:"0 13px",fontSize:12,color:T.textLight,
          background:T.bgDeep,alignSelf:"stretch",display:"flex",alignItems:"center",
          borderLeft:`1px solid ${T.border}`}}>{suffix}</span>
      )}
    </div>
  );
}

function StepCash({ data, onChange }) {
  return (
    <div style={{display:"flex",flexDirection:"column",gap:18}}>
      <div style={{fontSize:13,color:T.textSoft,lineHeight:1.65,background:T.greenPale,
        borderRadius:10,padding:"11px 15px",border:`1px solid ${T.green}33`}}>
        💡 Open your bank account and enter what you see right now. This drives the most critical outputs on the dashboard.
      </div>
      {[
        { label:"Cash in the bank right now",             hint:"Check your account balance",                              key:"starting_cash",             prefix:"$",  placeholder:"0"   },
        { label:"Monthly take-home pay (owner draw)",     hint:"What you pay yourself",                                  key:"owner_draw_monthly",        prefix:"$",  placeholder:"0"   },
        { label:"Fixed monthly costs",                    hint:"Rent, software, insurance, phone",                       key:"fixed_monthly_expenses",    prefix:"$",  placeholder:"0"   },
        { label:"Variable monthly costs",                 hint:"Materials, fuel, marketing",                             key:"variable_monthly_expenses", prefix:"$",  placeholder:"0"   },
      ].map(f => (
        <WizardField key={f.key} label={f.label} hint={f.hint}>
          <WizardInput prefix={f.prefix} placeholder={f.placeholder}
            value={data[f.key]}
            onChange={e => onChange(f.key, +e.target.value)}/>
        </WizardField>
      ))}
    </div>
  );
}

function StepProjects({ projects, onUpdate, onAdd, onRemove }) {
  const STATUS_OPTIONS = ["Active","On Hold","Completed"];
  return (
    <div style={{display:"flex",flexDirection:"column",gap:14}}>
      <div style={{fontSize:13,color:T.textSoft,lineHeight:1.65,background:T.bluePale,
        borderRadius:10,padding:"11px 15px",border:`1px solid ${T.blue}33`}}>
        💡 List every project you're currently working on or have on hold. Hours remaining directly calculate your backlog and customer wait time.
      </div>
      {projects.length===0 && (
        <div style={{textAlign:"center",padding:"20px",color:T.textLight,fontSize:13}}>
          No projects added yet. Click below to add one.
        </div>
      )}
      {projects.map((p,idx) => (
        <div key={p.id} style={{background:T.bgCard,border:`1.5px solid ${T.border}`,
          borderRadius:14,padding:"15px 17px"}}>
          <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:12}}>
            <span style={{fontSize:12,fontWeight:800,color:T.textMid}}>Project {idx+1}</span>
            <button onClick={()=>onRemove(p.id)}
              style={{background:T.redPale,border:`1px solid ${T.red}33`,color:T.red,
                borderRadius:8,padding:"4px 11px",fontSize:11,cursor:"pointer",
                fontFamily:"inherit",fontWeight:700}}>Remove</button>
          </div>
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:11}}>
            {[
              { label:"Client name", key:"client", placeholder:"Client name", type:"text" },
              { label:"Project name",key:"name",   placeholder:"Project name",type:"text" },
            ].map(f => (
              <div key={f.key}>
                <label style={{fontSize:11,fontWeight:700,color:T.textMid,display:"block",marginBottom:5}}>{f.label}</label>
                <input type={f.type} value={p[f.key]||""} placeholder={f.placeholder}
                  onChange={e=>onUpdate(p.id,f.key,e.target.value)}
                  style={{width:"100%",padding:"10px 13px",background:T.bgDeep,
                    border:`1.5px solid ${T.border}`,borderRadius:10,fontSize:13,
                    fontWeight:600,color:T.textDark,outline:"none",
                    fontFamily:"inherit",boxSizing:"border-box"}}/>
              </div>
            ))}
            <div>
              <label style={{fontSize:11,fontWeight:700,color:T.textMid,display:"block",marginBottom:5}}>Hours remaining</label>
              <input type="number" value={p.hrs_remaining||""} placeholder="0"
                onChange={e=>onUpdate(p.id,"hrs_remaining",+e.target.value)}
                style={{width:"100%",padding:"10px 13px",background:T.bgDeep,
                  border:`1.5px solid ${T.border}`,borderRadius:10,fontSize:13,
                  fontWeight:700,color:T.textDark,outline:"none",
                  fontFamily:"'Playfair Display',serif",boxSizing:"border-box"}}/>
            </div>
            <div>
              <label style={{fontSize:11,fontWeight:700,color:T.textMid,display:"block",marginBottom:5}}>Billing rate ($/hr)</label>
              <input type="number" value={p.billing_rate||""} placeholder="0"
                onChange={e=>onUpdate(p.id,"billing_rate",+e.target.value)}
                style={{width:"100%",padding:"10px 13px",background:T.bgDeep,
                  border:`1.5px solid ${T.border}`,borderRadius:10,fontSize:13,
                  fontWeight:700,color:T.textDark,outline:"none",
                  fontFamily:"'Playfair Display',serif",boxSizing:"border-box"}}/>
            </div>
            <div style={{gridColumn:"span 2"}}>
              <label style={{fontSize:11,fontWeight:700,color:T.textMid,display:"block",marginBottom:5}}>Status</label>
              <div style={{display:"flex",gap:8}}>
                {STATUS_OPTIONS.map(s => (
                  <button key={s} onClick={()=>onUpdate(p.id,"status",s)}
                    style={{flex:1,padding:"8px",borderRadius:9,
                      border:`1.5px solid ${p.status===s?T.greenMid:T.border}`,
                      background:p.status===s?T.greenPale:T.bgDeep,
                      color:p.status===s?T.green:T.textSoft,
                      fontWeight:700,fontSize:11,cursor:"pointer",
                      fontFamily:"inherit",transition:"all 0.2s"}}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      ))}
      <button onClick={onAdd}
        style={{background:"transparent",border:`2px dashed ${T.borderMid}`,
          borderRadius:14,padding:"14px",color:T.textSoft,fontSize:13,
          fontWeight:700,cursor:"pointer",fontFamily:"inherit",transition:"all 0.2s",
          display:"flex",alignItems:"center",justifyContent:"center",gap:9}}
        onMouseEnter={e=>{e.currentTarget.style.borderColor=T.greenMid;e.currentTarget.style.color=T.green;}}
        onMouseLeave={e=>{e.currentTarget.style.borderColor=T.borderMid;e.currentTarget.style.color=T.textSoft;}}>
        + Add Project
      </button>
    </div>
  );
}

function StepTeam({ data, onChange }) {
  return (
    <div style={{display:"flex",flexDirection:"column",gap:18}}>
      <div style={{fontSize:13,color:T.textSoft,lineHeight:1.65,background:T.goldPale,
        borderRadius:10,padding:"11px 15px",border:`1px solid ${T.gold}33`}}>
        💡 Be honest about admin time — email, scheduling, and bookkeeping eat more hours than people expect. This drives your sustainable weekly capacity.
      </div>
      {[
        { label:"Total available hours per week",            hint:"Your full week before admin",          key:"owner_total_hours_week", suffix:"hrs/wk", placeholder:"0" },
        { label:"Admin hours per week",                      hint:"Email, scheduling, bookkeeping",        key:"admin_hours_week",       suffix:"hrs/wk", placeholder:"0" },
        { label:"Your hourly billing rate",                  hint:"What you charge clients",              key:"base_hourly_rate",       prefix:"$",      placeholder:"0" },
        { label:"Active subcontractors / helpers right now", hint:"People working under you currently",   key:"num_subcontractors",     suffix:"people", placeholder:"0" },
      ].map(f => (
        <WizardField key={f.key} label={f.label} hint={f.hint}>
          <WizardInput prefix={f.prefix} suffix={f.suffix} placeholder={f.placeholder}
            value={data[f.key]}
            onChange={e => onChange(f.key, +e.target.value)}/>
        </WizardField>
      ))}
    </div>
  );
}

function StepLeads({ data, onChange }) {
  return (
    <div style={{display:"flex",flexDirection:"column",gap:18}}>
      <div style={{fontSize:13,color:T.textSoft,lineHeight:1.65,background:T.greenPale,
        borderRadius:10,padding:"11px 15px",border:`1px solid ${T.green}33`}}>
        💡 Think about the last few weeks — how many people reached out asking about your services on average per week? Regular clients are people who pay you a fixed amount every month.
      </div>
      {[
        { label:"Interested people reaching out per week",    hint:"Average over the last month",          key:"base_leads_per_week",          suffix:"people/wk", placeholder:"0"   },
        { label:"Current regular / retainer clients",         hint:"Pay a fixed amount monthly",           key:"current_retainer_clients",     suffix:"clients",   placeholder:"0"   },
        { label:"What each regular client pays per month",    hint:"Average if they differ",               key:"avg_retainer_value_monthly",   prefix:"$",         placeholder:"0"   },
        { label:"Current month",                              hint:"1–12",                                 key:"current_month",                suffix:"month",     placeholder:String(new Date().getMonth()+1) },
      ].map(f => (
        <WizardField key={f.key} label={f.label} hint={f.hint}>
          <WizardInput prefix={f.prefix} suffix={f.suffix} placeholder={f.placeholder}
            value={data[f.key]}
            onChange={e => onChange(f.key, +e.target.value)}/>
        </WizardField>
      ))}
    </div>
  );
}

function StepReview({ formData, projects, isSaving, saveResult, saveError }) {
  const activeProjects = projects.filter(p=>p.status!=="Completed");
  const totalHrs = activeProjects.reduce((s,p)=>s+(p.hrs_remaining||0),0);
  const totalMrr = (formData.current_retainer_clients||0)*(formData.avg_retainer_value_monthly||0);
  const sustainCap = ((formData.owner_total_hours_week||0)-(formData.admin_hours_week||0))*0.85;
  const monthlyOut = (formData.owner_draw_monthly||0)+(formData.fixed_monthly_expenses||0)+(formData.variable_monthly_expenses||0);

  const rows = [
    { label:"💵 Cash on hand",           val:`$${(formData.starting_cash||0).toLocaleString()}`                          },
    { label:"📤 Monthly going out",      val:`$${monthlyOut.toLocaleString()}/mo`                                         },
    { label:"⏱️ Active project hours",  val:`${totalHrs} hrs across ${activeProjects.length} project${activeProjects.length!==1?"s":""}` },
    { label:"⚡ Weekly capacity",        val:`${sustainCap.toFixed(1)} hrs/wk sustainable`                                },
    { label:"💲 Billing rate",           val:`$${formData.base_hourly_rate||0}/hr`                                        },
    { label:"👷 Helpers",                val:`${formData.num_subcontractors||0}`                                          },
    { label:"📣 Leads per week",         val:`${formData.base_leads_per_week||0} people/wk`                               },
    { label:"📅 Regular clients",        val:`${formData.current_retainer_clients||0} · $${totalMrr.toLocaleString()}/mo` },
  ];

  return (
    <div style={{display:"flex",flexDirection:"column",gap:13}}>
      {saveResult==="success" && (
        <div style={{background:T.greenPale,border:`2px solid ${T.green}44`,borderRadius:12,
          padding:"14px 18px",fontSize:13,color:T.green,fontWeight:700,
          display:"flex",gap:10,alignItems:"center"}}>
          ✅ Saved to Dataverse. Dashboard is refreshing…
        </div>
      )}
      {saveResult==="error" && (
        <div style={{background:T.redPale,border:`2px solid ${T.red}44`,borderRadius:12,
          padding:"13px 17px",fontSize:13,color:T.red,fontWeight:700}}>
          ⚠️ Save failed: {saveError||"Unknown error"}. Check your Dataverse connection and try again.
        </div>
      )}
      <div style={{fontSize:13,color:T.textSoft,lineHeight:1.6}}>
        Review what you entered. Go back to fix anything before saving.
      </div>
      {rows.map(({ label, val }) => (
        <div key={label} style={{display:"flex",justifyContent:"space-between",
          alignItems:"center",padding:"10px 15px",background:T.bgCard,
          borderRadius:10,border:`1px solid ${T.border}`}}>
          <span style={{fontSize:12,color:T.textMid,fontWeight:600}}>{label}</span>
          <span style={{fontSize:14,fontWeight:800,color:T.textDark,
            fontFamily:"'Playfair Display',serif"}}>{val}</span>
        </div>
      ))}
      {isSaving && (
        <div style={{display:"flex",alignItems:"center",gap:13,padding:"12px 16px",
          background:T.bgDeep,borderRadius:10}}>
          <Spinner size={28}/>
          <span style={{fontSize:13,color:T.textMid,fontWeight:600}}>Saving to Dataverse…</span>
        </div>
      )}
    </div>
  );
}

function WeeklyWizard({ onClose, onSaved }) {
  const [step, setStep]           = useState(0);
  const [isSaving, setIsSaving]   = useState(false);
  const [saveResult, setSaveResult] = useState(null);
  const [saveError, setSaveError] = useState(null);
  const [formData, setFormData]   = useState({
    starting_cash:              0,
    owner_draw_monthly:         0,
    fixed_monthly_expenses:     0,
    variable_monthly_expenses:  0,
    owner_total_hours_week:     0,
    admin_hours_week:           0,
    base_hourly_rate:           0,
    num_subcontractors:         0,
    base_leads_per_week:        0,
    current_retainer_clients:   0,
    avg_retainer_value_monthly: 0,
    current_month:              new Date().getMonth()+1,
  });
  const [projects, setProjects] = useState([]);

  const updateField   = useCallback((k,v) => setFormData(d=>({...d,[k]:v})), []);
  const updateProject = useCallback((id,k,v) => setProjects(ps=>ps.map(p=>p.id===id?{...p,[k]:v}:p)), []);
  const addProject    = useCallback(() => setProjects(ps=>[...ps,{
    id:Date.now(), code:`P-${String(ps.length+1).padStart(3,"0")}`,
    client:"", name:"", hrs_remaining:0, billing_rate:0, status:"Active"
  }]), []);
  const removeProject = useCallback((id) => setProjects(ps=>ps.filter(p=>p.id!==id)), []);

  const canAdvance = () => {
    if (step===0) return (formData.starting_cash||0) >= 0 && (formData.owner_draw_monthly||0) >= 0;
    return true;
  };

  const handleSave = async () => {
    setIsSaving(true); setSaveResult(null); setSaveError(null);
    try {
      const activeHrs = projects.filter(p=>p.status!=="Completed").reduce((s,p)=>s+(p.hrs_remaining||0),0);
      const payload = {
        ...formData,
        active_workload_hrs:  activeHrs,
        num_active_projects:  projects.filter(p=>p.status!=="Completed").length,
        projects:             projects,
      };
      await apiFetch("/update-inputs", { method:"POST", body:JSON.stringify(payload) });
      setSaveResult("success");
      setTimeout(() => onSaved(), 1800);
    } catch(e) {
      setSaveResult("error");
      setSaveError(e.message);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div style={{position:"fixed",inset:0,background:"rgba(28,43,30,0.60)",zIndex:200,
      display:"flex",alignItems:"center",justifyContent:"center",
      padding:20,backdropFilter:"blur(5px)"}}>
      <div style={{background:T.bgCard,borderRadius:24,width:"100%",maxWidth:560,
        maxHeight:"92vh",display:"flex",flexDirection:"column",
        boxShadow:`0 28px 72px ${T.shadowLg}`,overflow:"hidden"}}>

        {/* Wizard header */}
        <div style={{background:T.bgDark,padding:"18px 26px",display:"flex",
          justifyContent:"space-between",alignItems:"center",flexShrink:0}}>
          <div>
            <div style={{fontSize:17,fontWeight:900,color:T.white,
              fontFamily:"'Playfair Display',serif"}}>Weekly Check-In</div>
            <div style={{fontSize:11,color:"#6a8a6e",marginTop:3}}>
              {new Date().toLocaleDateString("en-US",{weekday:"long",month:"long",day:"numeric",year:"numeric"})}
            </div>
          </div>
          <button onClick={onClose}
            style={{background:"#1a2a1c",border:`1px solid ${T.borderDark}`,
              color:"#6a8a6e",width:34,height:34,borderRadius:9,cursor:"pointer",
              fontSize:16,display:"flex",alignItems:"center",justifyContent:"center"}}>✕</button>
        </div>

        {/* Step indicator */}
        <div style={{padding:"14px 26px",borderBottom:`1px solid ${T.border}`,
          background:T.bg,flexShrink:0}}>
          <div style={{display:"flex",gap:6}}>
            {WIZARD_STEPS.map((s,i) => {
              const done=i<step; const active=i===step;
              return (
                <div key={s.id} onClick={()=>done&&setStep(i)}
                  style={{flex:1,display:"flex",flexDirection:"column",alignItems:"center",
                    gap:5,cursor:done?"pointer":"default"}}>
                  <div style={{width:34,height:34,borderRadius:10,
                    background:done?T.green:active?T.greenPale:T.bgDeep,
                    border:`2px solid ${done||active?T.green:T.border}`,
                    display:"flex",alignItems:"center",justifyContent:"center",
                    fontSize:done?14:17,fontWeight:700,
                    color:done?T.white:active?T.green:T.textLight,
                    transition:"all 0.3s"}}>
                    {done?"✓":s.icon}
                  </div>
                  <div style={{fontSize:9,textAlign:"center",lineHeight:1.2,
                    color:active?T.green:done?T.greenMid:T.textLight,
                    fontWeight:active||done?700:400}}>{s.title}</div>
                </div>
              );
            })}
          </div>
          <div style={{marginTop:11,height:3,background:T.bgDeep,borderRadius:3,overflow:"hidden"}}>
            <div style={{height:"100%",borderRadius:3,
              width:`${(step/(WIZARD_STEPS.length-1))*100}%`,
              background:`linear-gradient(90deg,${T.greenMid},${T.greenLight})`,
              transition:"width 0.4s ease"}}/>
          </div>
        </div>

        {/* Step content */}
        <div style={{flex:1,overflow:"auto",padding:"22px 26px"}}>
          <div style={{marginBottom:18}}>
            <div style={{fontSize:18,fontWeight:800,color:T.textDark,
              fontFamily:"'Playfair Display',serif"}}>{WIZARD_STEPS[step].title}</div>
            <div style={{fontSize:12,color:T.textLight,marginTop:3}}>{WIZARD_STEPS[step].subtitle}</div>
          </div>
          {step===0 && <StepCash data={formData} onChange={updateField}/>}
          {step===1 && <StepProjects projects={projects} onUpdate={updateProject} onAdd={addProject} onRemove={removeProject}/>}
          {step===2 && <StepTeam data={formData} onChange={updateField}/>}
          {step===3 && <StepLeads data={formData} onChange={updateField}/>}
          {step===4 && <StepReview formData={formData} projects={projects} isSaving={isSaving} saveResult={saveResult} saveError={saveError}/>}
        </div>

        {/* Footer */}
        <div style={{padding:"14px 26px",borderTop:`1px solid ${T.border}`,
          display:"flex",justifyContent:"space-between",alignItems:"center",
          flexShrink:0,background:T.bg}}>
          <button onClick={()=>step>0&&setStep(s=>s-1)} disabled={step===0}
            style={{padding:"10px 22px",borderRadius:10,border:`1.5px solid ${T.border}`,
              background:"transparent",color:step===0?T.textLight:T.textMid,
              fontSize:13,fontWeight:700,cursor:step===0?"default":"pointer",
              fontFamily:"inherit",opacity:step===0?0.35:1}}>← Back</button>
          <span style={{fontSize:11,color:T.textLight}}>Step {step+1} of {WIZARD_STEPS.length}</span>
          {step<WIZARD_STEPS.length-1 ? (
            <button onClick={()=>canAdvance()&&setStep(s=>s+1)} disabled={!canAdvance()}
              style={{padding:"10px 26px",borderRadius:10,border:"none",
                background:canAdvance()?T.green:"#ccc",color:T.white,
                fontSize:13,fontWeight:700,cursor:canAdvance()?"pointer":"default",
                fontFamily:"inherit",
                boxShadow:canAdvance()?`0 4px 14px ${T.green}44`:"none",
                transition:"all 0.2s"}}>Next →</button>
          ) : (
            <button onClick={handleSave}
              disabled={isSaving||saveResult==="success"}
              style={{padding:"10px 26px",borderRadius:10,border:"none",
                background:saveResult==="success"?T.green:T.gold,color:T.white,
                fontSize:13,fontWeight:700,
                cursor:isSaving||saveResult==="success"?"default":"pointer",
                fontFamily:"inherit",
                boxShadow:`0 4px 14px ${T.gold}44`,transition:"all 0.2s",
                display:"flex",alignItems:"center",gap:9}}>
              {isSaving?"Saving…":saveResult==="success"?"✓ Saved!":"💾 Save to Dashboard"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   SNAPSHOT VIEW
═══════════════════════════════════════════════════════════════════ */
function SnapshotView({ data, onOpenWizard }) {
  const d = data;
  return (
    <div style={{padding:"22px 28px",maxWidth:1280,margin:"0 auto",
      animation:"fadeIn 0.4s ease"}}>
      <StatusBanner banner={d.status_banner}/>

      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:14,margin:"16px 0"}}>
        <div style={{background:T.bgCard,border:`1.5px solid ${T.border}`,borderRadius:18,
          padding:"20px 24px",boxShadow:`0 2px 14px ${T.shadow}`}}>
          <div style={{fontSize:12,fontWeight:800,color:T.textMid,textTransform:"uppercase",
            letterSpacing:0.8,marginBottom:14}}>Your Business Score</div>
          <XPStrip xp={d.score?.xp||0}/>
        </div>
        <div style={{background:T.bgCard,border:`1.5px solid ${T.border}`,borderRadius:18,
          padding:"20px 24px",boxShadow:`0 2px 14px ${T.shadow}`}}>
          <div style={{fontSize:12,fontWeight:800,color:T.textMid,textTransform:"uppercase",
            letterSpacing:0.8,marginBottom:14}}>Achievements</div>
          <BadgeShelf badges={d.badges}/>
        </div>
      </div>

      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:14,marginBottom:14}}>
        {/* Cash */}
        <MetricCard icon="💵" title="Your Money" status={cashStatus(d)}>
          <div style={{marginBottom:14}}>
            <div style={{fontSize:11,color:T.textLight,marginBottom:4}}>Cash in the bank right now</div>
            <div style={{fontSize:38,fontWeight:900,color:statusColor(cashStatus(d)),
              letterSpacing:-1,fontFamily:"'Playfair Display',serif"}}>
              ${(d.cash?.amount||0).toLocaleString()}
            </div>
          </div>
          <div style={{marginBottom:13}}>
            <div style={{display:"flex",justifyContent:"space-between",marginBottom:6}}>
              <span style={{fontSize:11,color:T.textSoft,fontWeight:700}}>How long it lasts</span>
              <span style={{fontSize:11,color:T.textLight}}>~{(d.cash?.weeks_left||0).toFixed(1)} weeks</span>
            </div>
            <HealthBar val={Math.round((d.cash?.weeks_left||0)*10)} max={80}/>
          </div>
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10}}>
            <div style={{background:T.redPale,borderRadius:12,padding:"10px 14px",
              border:`1px solid ${T.red}33`}}>
              <div style={{fontSize:10,color:T.textLight,marginBottom:3}}>Going out / week</div>
              <div style={{fontSize:22,fontWeight:900,color:T.red,
                fontFamily:"'Playfair Display',serif"}}>${(d.cash?.weekly_out||0).toLocaleString()}</div>
            </div>
            <div style={{background:(d.cash?.weekly_in||0)>(d.cash?.weekly_out||0)?T.greenPale:T.redPale,
              borderRadius:12,padding:"10px 14px",
              border:`1px solid ${(d.cash?.weekly_in||0)>(d.cash?.weekly_out||0)?T.green:T.red}33`}}>
              <div style={{fontSize:10,color:T.textLight,marginBottom:3}}>Coming in / week</div>
              <div style={{fontSize:22,fontWeight:900,
                color:(d.cash?.weekly_in||0)>(d.cash?.weekly_out||0)?T.green:T.red,
                fontFamily:"'Playfair Display',serif"}}>${(d.cash?.weekly_in||0).toLocaleString()}</div>
            </div>
          </div>
        </MetricCard>

        {/* Workload */}
        <MetricCard icon="📋" title="How Slammed Are You?" status={workStatus(d)}>
          <div style={{marginBottom:14}}>
            <div style={{display:"flex",justifyContent:"space-between",marginBottom:6}}>
              <span style={{fontSize:11,color:T.textSoft,fontWeight:700}}>Breathing room</span>
              <span style={{fontSize:11,color:T.textLight}}>100 = totally free</span>
            </div>
            <HealthBar val={100-(d.workload?.stress_score||0)} max={100} size="lg"/>
          </div>
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10}}>
            <MiniStat label="Hours backed up"  val={`${d.workload?.backlog_hrs||0} hrs`}  status={(d.workload?.backlog_hrs||0)>20?"bad":undefined}/>
            <MiniStat label="Customer wait"    val={`${d.workload?.wait_days||0} days`}   status={(d.workload?.wait_days||0)>7?"bad":undefined}/>
            <MiniStat label="Capacity / week"  val={`${d.workload?.sustainable_cap||0} hrs`}/>
            <MiniStat label="Helpers"          val={d.labor?.num_subs===0?"None":d.labor?.num_subs}
              status={d.labor?.num_subs===0&&(d.workload?.stress_score||0)>70?"bad":undefined}/>
          </div>
        </MetricCard>

        {/* Pipeline */}
        <MetricCard icon="🔧" title="Jobs Coming In" status={pipeStatus(d)}>
          <div style={{marginBottom:14}}>
            <div style={{display:"flex",justifyContent:"space-between",marginBottom:6}}>
              <span style={{fontSize:11,color:T.textSoft,fontWeight:700}}>How often you land the job</span>
              <span style={{fontSize:11,color:T.textLight}}>
                {Math.round((d.pipeline?.win_rate||0)*10)} out of every 10 quotes
              </span>
            </div>
            <HealthBar val={Math.round((d.pipeline?.win_rate||0)*100)} max={100}/>
          </div>
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:8,marginBottom:12}}>
            <MiniStat label="Interested/wk"  val={d.pipeline?.leads_per_week||0}/>
            <MiniStat label="Jobs won/wk"    val={(d.pipeline?.closes_12w/12||0).toFixed(2)}/>
            <MiniStat label="Avg job size"   val={`$${(d.pipeline?.avg_project_value||0).toLocaleString()}`}/>
          </div>
          <div style={{background:T.greenPale,borderRadius:12,padding:"10px 14px",
            border:`1px solid ${T.green}44`,display:"flex",justifyContent:"space-between",alignItems:"center"}}>
            <span style={{fontSize:12,color:T.textMid,fontWeight:600}}>Expected next 3 months</span>
            <span style={{fontSize:24,fontWeight:900,color:T.green,
              fontFamily:"'Playfair Display',serif"}}>
              ${(d.pipeline?.revenue_12w||0).toLocaleString()}
            </span>
          </div>
        </MetricCard>

        {/* Quality */}
        <MetricCard icon="😊" title="Are Customers Happy?" status={qualStatus(d)}>
          <div style={{marginBottom:14}}>
            <div style={{display:"flex",justifyContent:"space-between",marginBottom:6}}>
              <span style={{fontSize:11,color:T.textSoft,fontWeight:700}}>Happiness level</span>
              <span style={{fontSize:11,color:T.textLight}}>
                {(d.quality?.score||0)<60?"Delays frustrating people":(d.quality?.score||0)<80?"Room to improve":"They love the work"}
              </span>
            </div>
            <HealthBar val={d.quality?.score||0} max={100} size="lg"/>
          </div>
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12}}>
            <div>
              <div style={{fontSize:10,color:T.textLight,marginBottom:6,fontWeight:600}}>Chance they come back</div>
              <HealthBar val={Math.round((d.quality?.retention_likelihood||0)*100)} max={100} size="sm"/>
              <div style={{fontSize:10,color:T.textLight,marginTop:3,textAlign:"right"}}>
                {Math.round((d.quality?.retention_likelihood||0)*100)}%
              </div>
            </div>
            <div>
              <div style={{fontSize:10,color:T.textLight,marginBottom:6,fontWeight:600}}>Chance they tell friends</div>
              <HealthBar val={Math.round((d.quality?.referral_likelihood||0)*100)} max={100} size="sm"/>
              <div style={{fontSize:10,color:T.textLight,marginTop:3,textAlign:"right"}}>
                {Math.round((d.quality?.referral_likelihood||0)*100)}%
              </div>
            </div>
          </div>
        </MetricCard>
      </div>

      {/* Bottom strip */}
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:14}}>
        <div style={{background:T.bgCard,border:`1.5px solid ${T.border}`,borderRadius:18,
          padding:"16px 22px",boxShadow:`0 2px 14px ${T.shadow}`}}>
          <div style={{fontSize:12,fontWeight:800,color:T.textMid,textTransform:"uppercase",
            letterSpacing:0.8,marginBottom:10}}>📅 Steady Monthly Income</div>
          <div style={{fontSize:30,fontWeight:900,
            color:(d.recurring?.mrr||0)===0?T.red:T.green,
            fontFamily:"'Playfair Display',serif"}}>
            ${(d.recurring?.mrr||0).toLocaleString()}
          </div>
          <div style={{fontSize:11,color:T.textLight,marginTop:7,lineHeight:1.6}}>
            {(d.recurring?.retainer_clients||0)===0
              ?"No regular clients yet. Every dollar depends on landing new jobs."
              :`${d.recurring.retainer_clients} regular client${d.recurring.retainer_clients!==1?"s":""} · $${(d.recurring?.mrr_month12||0).toLocaleString()} by month 12`}
          </div>
        </div>
        <div style={{background:T.bgCard,border:`1.5px solid ${T.border}`,borderRadius:18,
          padding:"16px 22px",boxShadow:`0 2px 14px ${T.shadow}`}}>
          <div style={{fontSize:12,fontWeight:800,color:T.textMid,textTransform:"uppercase",
            letterSpacing:0.8,marginBottom:10}}>👷 Team & Owner</div>
          <div style={{fontSize:30,fontWeight:900,color:T.textDark,
            fontFamily:"'Playfair Display',serif"}}>
            {(d.labor?.num_subs||0)===0?"Solo":`You + ${d.labor.num_subs}`}
          </div>
          <div style={{fontSize:11,color:T.textLight,marginTop:7,lineHeight:1.6}}>
            {(d.labor?.num_subs||0)===0
              ?"Just you right now."
              :`${d.labor.num_subs} helper${d.labor.num_subs!==1?"s":""} active · ${Math.round((d.labor?.gross_margin||0)*100)}% gross margin`}
          </div>
        </div>
        <div onClick={onOpenWizard}
          style={{background:T.bgDark,borderRadius:18,padding:"16px 22px",cursor:"pointer",
            display:"flex",flexDirection:"column",justifyContent:"center",alignItems:"center",
            gap:11,border:`1.5px solid ${T.borderDark}`,
            boxShadow:`0 4px 24px ${T.shadowMd}`,transition:"transform 0.15s ease"}}
          onMouseEnter={e=>e.currentTarget.style.transform="translateY(-3px)"}
          onMouseLeave={e=>e.currentTarget.style.transform=""}>
          <span style={{fontSize:32}}>✏️</span>
          <div style={{fontSize:15,fontWeight:900,color:T.white,
            fontFamily:"'Playfair Display',serif"}}>Update My Numbers</div>
          <div style={{fontSize:11,color:"#4a6a4e",textAlign:"center",lineHeight:1.5}}>
            Weekly check-in · 5 steps · 2 minutes
          </div>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   PREDICTION PANEL — wired to live API /predict
═══════════════════════════════════════════════════════════════════ */
const DEFAULT_SLIDERS = { moreLeads:0, raiseRate:0, ownerPay:0, hireHelp:0, addRegulars:0 };

function PredictionPanel({ liveData }) {
  const [sliders, setSliders]   = useState(null); // null until live data loads
  const [pred, setPred]         = useState(null);
  const [loading, setLoading]   = useState(false);
  const debounceRef             = useRef(null);

  // Seed sliders from live data once available
  useEffect(() => {
    if (liveData && !sliders) {
      setSliders({
        moreLeads:  liveData.pipeline?.leads_per_week || 0,
        raiseRate:  liveData.pipeline?.avg_project_value ? Math.round(liveData.pipeline.avg_project_value/15) : 0,
        ownerPay:   0,
        hireHelp:   liveData.labor?.num_subs || 0,
        addRegulars:liveData.recurring?.retainer_clients || 0,
      });
    }
  }, [liveData]);

  const set = (k,v) => setSliders(s=>({...s,[k]:v}));

  useEffect(() => {
    if (!sliders) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const res = await apiFetch("/predict", {
          method:"POST",
          body: JSON.stringify({
            base_leads_per_week:       sliders.moreLeads,
            base_hourly_rate:          sliders.raiseRate,
            owner_draw_monthly:        sliders.ownerPay,
            num_subcontractors:        sliders.hireHelp,
            current_retainer_clients:  sliders.addRegulars,
          }),
        });
        setPred(res);
      } catch(e) { console.error("Predict error:", e); }
      finally { setLoading(false); }
    }, 420);
  }, [sliders]);

  const live = liveData;
  const p    = pred?.predicted || live;

  if (!sliders) return (
    <div style={{display:"flex",alignItems:"center",justifyContent:"center",padding:60,gap:16}}>
      <Spinner/><span style={{fontSize:14,color:T.textMid,fontWeight:600}}>Loading live data…</span>
    </div>
  );

  const CmpRow = ({label,lv,pv,fmt=v=>v,inv=false}) => {
    const diff=pv-lv; const chg=Math.abs(diff)>=0.5;
    const good=chg?((diff>0)!==inv):false; const col=good?T.green:T.red;
    const sign=diff>0?"+":"";
    return (
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",
        padding:"7px 0",borderBottom:`1px solid ${T.border}44`}}>
        <span style={{fontSize:12,color:T.textSoft,flex:1}}>{label}</span>
        <div style={{display:"flex",alignItems:"center",gap:8}}>
          <span style={{fontSize:11,color:T.textLight,textDecoration:chg?"line-through":"none"}}>{fmt(lv)}</span>
          {chg && <>
            <span style={{fontSize:10,color:T.textLight}}>→</span>
            <span style={{fontSize:13,fontWeight:800,color:col}}>{fmt(pv)}</span>
            <span style={{fontSize:10,fontWeight:700,color:col,
              background:good?T.greenPale:T.redPale,
              border:`1px solid ${col}44`,borderRadius:5,padding:"1px 7px"}}>
              {sign}{fmt(diff)}
            </span>
          </>}
          {!chg && <span style={{fontSize:12,fontWeight:700,color:T.textDark}}>{fmt(pv)}</span>}
        </div>
      </div>
    );
  };

  const SliderCard = ({label,detail,k,min,max,step,prefix="",suffix=""}) => (
    <div style={{background:T.bgCard,border:`1.5px solid ${T.border}`,borderRadius:14,
      padding:"13px 16px",boxShadow:`0 2px 8px ${T.shadow}`}}>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",
        marginBottom:9,gap:12}}>
        <div style={{flex:1}}>
          <div style={{fontSize:13,fontWeight:800,color:T.textDark,lineHeight:1.3}}>{label}</div>
          {detail&&<div style={{fontSize:10,color:T.textLight,marginTop:2}}>{detail}</div>}
        </div>
        <div style={{fontSize:17,fontWeight:900,color:T.bgDark,background:T.goldPale,
          border:`1.5px solid ${T.goldMid}55`,borderRadius:10,padding:"3px 13px",
          minWidth:64,textAlign:"center",fontFamily:"'Playfair Display',serif"}}>
          {prefix}{typeof sliders[k]==="number"&&sliders[k]>999?sliders[k].toLocaleString():sliders[k]}{suffix}
        </div>
      </div>
      <input type="range" min={min} max={max} step={step} value={sliders[k]}
        onChange={e=>set(k,+e.target.value)}
        style={{width:"100%",accentColor:T.greenMid,cursor:"pointer"}}/>
    </div>
  );

  return (
    <div style={{display:"flex",flexDirection:"column",height:"calc(100vh - 66px)",overflow:"hidden"}}>
      {/* Live baseline strip */}
      <div style={{background:T.bgDark,borderBottom:`3px solid ${T.greenMid}`,
        padding:"12px 28px",flexShrink:0}}>
        <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:10}}>
          <span style={{fontSize:11,fontWeight:700,color:T.greenLight,
            textTransform:"uppercase",letterSpacing:1.5}}>
            📍 Your numbers right now — this doesn't change
          </span>
          <span style={{fontSize:10,color:"#4a6a4e"}}>Adjust sliders below to test different decisions</span>
        </div>
        <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:10}}>
          {[
            {icon:"💵",label:"Cash in the bank",    val:`$${(live?.cash?.amount||0).toLocaleString()}`,       col:cashStatus(live)==="bad"?T.redLight:T.greenLight},
            {icon:"📋",label:"Work backed up",       val:`${live?.workload?.backlog_hrs||0} hrs`,              col:workStatus(live)==="bad"?T.redLight:T.goldLight},
            {icon:"🔧",label:"Win rate",             val:`${Math.round((live?.pipeline?.win_rate||0)*100)}%`,  col:pipeStatus(live)==="bad"?T.redLight:T.goldLight},
            {icon:"😊",label:"Customer happiness",   val:`${live?.quality?.score||0} / 100`,                  col:qualStatus(live)==="bad"?T.redLight:T.greenLight},
          ].map(({icon,label,val,col}) => (
            <div key={label} style={{background:"#1a2a1c",border:`1px solid ${T.borderDark}`,
              borderRadius:12,padding:"10px 14px"}}>
              <div style={{fontSize:10,color:"#4a6a4e",marginBottom:4,fontWeight:600}}>{icon} {label}</div>
              <div style={{fontSize:19,fontWeight:900,color:col,
                fontFamily:"'Playfair Display',serif",lineHeight:1.1}}>{val}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Lab */}
      <div style={{flex:1,overflow:"auto",padding:"20px 28px",background:T.bg}}>
        <div style={{display:"grid",gridTemplateColumns:"290px 1fr",gap:22,alignItems:"start"}}>
          {/* Sliders */}
          <div style={{display:"flex",flexDirection:"column",gap:10}}>
            <span style={{fontSize:15,fontWeight:800,color:T.textDark,marginBottom:2}}>🎮 What if I…</span>
            <SliderCard label="…got more people interested?" detail="Potential customers per week" k="moreLeads" min={0} max={15} step={0.5}/>
            <SliderCard label="…charged more per hour?"      detail="Hourly billing rate"          k="raiseRate" min={0} max={300} step={5} prefix="$"/>
            <SliderCard label="…reduced my monthly draw?"    detail="Temporary pay cut"            k="ownerPay"  min={0} max={10000} step={250} prefix="$" suffix="/mo"/>
            <SliderCard label="…hired a helper?"             detail="Each adds ~20 billable hrs/wk" k="hireHelp" min={0} max={5} step={1} suffix={` helper${sliders.hireHelp!==1?"s":""}`}/>
            <SliderCard label="…signed regular clients?"     detail="Fixed monthly retainers"      k="addRegulars" min={0} max={10} step={1} suffix={` client${sliders.addRegulars!==1?"s":""}`}/>
            {loading && (
              <div style={{display:"flex",alignItems:"center",gap:10,padding:"10px 14px",
                background:T.bgDeep,borderRadius:10,fontSize:12,color:T.textMid}}>
                <Spinner size={22}/>Recalculating…
              </div>
            )}
          </div>

          {/* Results */}
          <div style={{display:"flex",flexDirection:"column",gap:14}}>
            {/* Score comparison */}
            <div style={{background:T.bgCard,border:`1.5px solid ${T.border}`,borderRadius:18,
              padding:"18px 22px",boxShadow:`0 2px 14px ${T.shadow}`}}>
              <div style={{fontSize:12,fontWeight:800,color:T.textMid,textTransform:"uppercase",
                letterSpacing:0.8,marginBottom:14}}>Business Score — Before vs After</div>
              <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:24}}>
                <div>
                  <div style={{fontSize:11,color:T.textLight,marginBottom:9,fontWeight:600}}>Right now</div>
                  <XPStrip xp={live?.score?.xp||0}/>
                </div>
                <div>
                  <div style={{fontSize:11,color:T.textLight,marginBottom:9,fontWeight:600}}>With your changes</div>
                  <XPStrip xp={p?.score?.xp||0}/>
                </div>
              </div>
              {(p?.score?.xp||0)>(live?.score?.xp||0) && (
                <div style={{marginTop:13,background:T.greenPale,border:`1px solid ${T.green}44`,
                  borderRadius:10,padding:"9px 15px",fontSize:12,color:T.green,fontWeight:700,
                  display:"flex",alignItems:"center",gap:9}}>
                  <span style={{fontSize:18}}>🌱</span>
                  +{(p.score.xp)-(live.score.xp)} point improvement · {p.score.title}
                </div>
              )}
            </div>

            {/* 4 compare blocks */}
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12}}>
              {[
                {icon:"💵",title:"Money",rows:[
                  {label:"Cash after 3 months", lv:live?.cash?.net_12w||0,              pv:p?.cash?.net_12w||0,              fmt:v=>`$${Math.round(v).toLocaleString()}`},
                  {label:"Coming in / week",    lv:live?.cash?.weekly_in||0,            pv:p?.cash?.weekly_in||0,            fmt:v=>`$${Math.round(v).toLocaleString()}`},
                  {label:"Going out / week",    lv:live?.cash?.weekly_out||0,           pv:p?.cash?.weekly_out||0,           fmt:v=>`$${Math.round(v).toLocaleString()}`,inv:true},
                ]},
                {icon:"📋",title:"Workload",rows:[
                  {label:"Hours backed up",     lv:live?.workload?.backlog_hrs||0,      pv:p?.workload?.backlog_hrs||0,      fmt:v=>`${Math.round(v)}h`,inv:true},
                  {label:"Customer wait",       lv:live?.workload?.wait_days||0,        pv:p?.workload?.wait_days||0,        fmt:v=>`${Math.round(v)} days`,inv:true},
                  {label:"How slammed",         lv:live?.workload?.stress_score||0,     pv:p?.workload?.stress_score||0,     fmt:v=>`${Math.round(v)}%`,inv:true},
                ]},
                {icon:"🔧",title:"Jobs",rows:[
                  {label:"Revenue (3 mo.)",     lv:live?.pipeline?.revenue_12w||0,      pv:p?.pipeline?.revenue_12w||0,     fmt:v=>`$${Math.round(v).toLocaleString()}`},
                  {label:"Win rate",            lv:(live?.pipeline?.win_rate||0)*100,   pv:(p?.pipeline?.win_rate||0)*100,  fmt:v=>`${Math.round(v)}%`},
                  {label:"Avg job size",        lv:live?.pipeline?.avg_project_value||0,pv:p?.pipeline?.avg_project_value||0,fmt:v=>`$${Math.round(v).toLocaleString()}`},
                ]},
                {icon:"😊",title:"Customers",rows:[
                  {label:"Happiness score",     lv:live?.quality?.score||0,             pv:p?.quality?.score||0,            fmt:v=>`${Math.round(v)}/100`},
                  {label:"Will come back",      lv:(live?.quality?.retention_likelihood||0)*100,pv:(p?.quality?.retention_likelihood||0)*100,fmt:v=>`${Math.round(v)}%`},
                  {label:"Monthly recurring",   lv:live?.recurring?.mrr||0,             pv:p?.recurring?.mrr||0,            fmt:v=>`$${Math.round(v).toLocaleString()}`},
                ]},
              ].map(({icon,title,rows})=>(
                <div key={title} style={{background:T.bgCard,border:`1.5px solid ${T.border}`,
                  borderRadius:14,padding:"14px 18px",boxShadow:`0 2px 8px ${T.shadow}`}}>
                  <div style={{fontSize:12,fontWeight:800,color:T.textMid,marginBottom:10,
                    display:"flex",gap:8,alignItems:"center"}}><span>{icon}</span>{title}</div>
                  {rows.map(r=><CmpRow key={r.label} label={r.label} lv={r.lv} pv={r.pv} fmt={r.fmt} inv={r.inv}/>)}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   ROOT
═══════════════════════════════════════════════════════════════════ */
export default function Dashboard() {
  const [mode, setMode]             = useState("snapshot");
  const [data, setData]             = useState(null);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState(null);
  const [showWizard, setShowWizard] = useState(false);
  const [pulse, setPulse]           = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [newBadge, setNewBadge]     = useState(null);
  const prevBadges                  = useRef({});

  const loadDashboard = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const res = await apiFetch("/dashboard");
      // Badge unlock detection
      if (res.badges && Object.keys(prevBadges.current).length > 0) {
        const fresh = ACHIEVEMENTS.filter(a => res.badges[a.id] && !prevBadges.current[a.id]);
        if (fresh.length) setNewBadge(fresh[0]);
      }
      prevBadges.current = res.badges || {};
      setData(res);
      setLastUpdated(new Date());
    } catch(e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadDashboard(); }, []);
  useEffect(() => { const t = setInterval(()=>setPulse(p=>!p), 2400); return ()=>clearInterval(t); }, []);

  const handleWizardSaved = useCallback(() => {
    setShowWizard(false);
    loadDashboard();
  }, [loadDashboard]);

  const isEmpty = !loading && !error && !data;

  return (
    <div style={{minHeight:"100vh",background:T.bg,
      fontFamily:"'DM Sans',system-ui,sans-serif",color:T.textDark}}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=Playfair+Display:wght@700;900&display=swap');
        *{box-sizing:border-box;margin:0;padding:0;}
        input[type=range]{-webkit-appearance:none;height:6px;border-radius:3px;background:${T.bgDeep};outline:none;}
        input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:19px;height:19px;border-radius:50%;background:${T.bgDark};cursor:pointer;border:3px solid ${T.greenGlow};box-shadow:0 2px 6px ${T.shadowMd};}
        @keyframes spin{to{transform:rotate(360deg)}}
        @keyframes toastIn{from{transform:translateX(110%);opacity:0}to{transform:translateX(0);opacity:1}}
        @keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
        ::-webkit-scrollbar{width:6px}
        ::-webkit-scrollbar-track{background:${T.bgDeep}}
        ::-webkit-scrollbar-thumb{background:${T.borderMid};border-radius:3px}
      `}</style>

      {/* Badge toast */}
      {newBadge && <BadgeToast badge={newBadge} onDone={()=>setNewBadge(null)}/>}

      {/* Weekly wizard */}
      {showWizard && (
        <WeeklyWizard
          onClose={()=>setShowWizard(false)}
          onSaved={handleWizardSaved}/>
      )}

      {/* ── Header ── */}
      <div style={{background:T.bgDark,padding:"13px 28px",display:"flex",
        justifyContent:"space-between",alignItems:"center",
        boxShadow:`0 4px 24px ${T.shadowLg}`,position:"sticky",top:0,zIndex:100}}>

        {/* Logo */}
        <div style={{display:"flex",alignItems:"center",gap:14}}>
          <div style={{width:48,height:48,borderRadius:12,background:"#e8eef4",
            boxShadow:`0 4px 16px rgba(0,0,0,0.4)`,border:`1.5px solid #3d5240`,
            display:"flex",alignItems:"center",justifyContent:"center"}}>
            <svg width="38" height="38" viewBox="0 0 100 100" fill="none">
              <path d="M 18 72 A 42 42 0 1 1 82 72" stroke="#4a7fa5" strokeWidth="7" strokeLinecap="round" fill="none"/>
              <path d="M 28 75 A 30 30 0 1 1 72 75" stroke="#2d5f80" strokeWidth="4.5" strokeLinecap="round" fill="none"/>
              <rect x="32" y="58" width="7" height="16" rx="2" fill="#2d5f80"/>
              <rect x="42" y="50" width="7" height="24" rx="2" fill="#3a7aa8"/>
              <rect x="52" y="41" width="7" height="33" rx="2" fill="#4a8fbf"/>
              <rect x="62" y="33" width="7" height="41" rx="2" fill="#5aa3d4"/>
              <circle cx="65.5" cy="30" r="4" fill="#7ec8e3"/>
            </svg>
          </div>
          <div>
            <div style={{fontSize:17,fontWeight:900,color:T.white,letterSpacing:-0.2,
              fontFamily:"'Playfair Display',serif",lineHeight:1.1}}>
              JD Analytics & Solutions
            </div>
            <div style={{fontSize:10,color:"#6a8a6e",marginTop:2,letterSpacing:0.4}}>
              Digital Clone · Business Intelligence
            </div>
          </div>
        </div>

        {/* Tabs */}
        <div style={{display:"flex",gap:4,background:"#111a12",borderRadius:14,padding:4,
          boxShadow:`inset 0 2px 10px rgba(0,0,0,0.4)`}}>
          {[
            {id:"snapshot",icon:"📊",label:"Real Time Status"},
            {id:"whatif",  icon:"🎮",label:"Predictive Playground"},
          ].map(({id,icon,label}) => (
            <button key={id} onClick={()=>setMode(id)}
              style={{padding:"9px 20px",borderRadius:10,fontSize:12,fontWeight:700,
                cursor:"pointer",border:"none",fontFamily:"inherit",letterSpacing:0.2,
                background:mode===id?T.green:"transparent",
                color:mode===id?T.white:"#4a6a4e",
                boxShadow:mode===id?`0 3px 12px rgba(0,0,0,0.3)`:"none",
                transition:"all 0.2s",display:"flex",alignItems:"center",gap:7}}>
              <span>{icon}</span><span>{label}</span>
            </button>
          ))}
        </div>

        {/* Right */}
        <div style={{display:"flex",alignItems:"center",gap:14}}>
          <button onClick={()=>setShowWizard(true)}
            style={{padding:"9px 20px",borderRadius:10,background:T.gold,border:"none",
              color:T.white,fontSize:12,fontWeight:800,cursor:"pointer",
              fontFamily:"inherit",boxShadow:`0 4px 14px ${T.gold}44`,
              display:"flex",alignItems:"center",gap:7,transition:"transform 0.2s"}}
            onMouseEnter={e=>e.currentTarget.style.transform="translateY(-1px)"}
            onMouseLeave={e=>e.currentTarget.style.transform=""}>
            ✏️ Update Numbers
          </button>
          <div style={{display:"flex",flexDirection:"column",alignItems:"flex-end",gap:3}}>
            <div style={{display:"flex",alignItems:"center",gap:7}}>
              <div style={{width:8,height:8,borderRadius:"50%",
                background:loading?T.gold:error?T.red:T.greenGlow,
                boxShadow:`0 0 ${pulse?10:5}px ${loading?T.gold:error?T.red:T.greenGlow}`,
                transition:"box-shadow 1.5s"}}/>
              <span style={{fontSize:11,color:"#4a6a4e",fontWeight:600}}>
                {loading?"Loading…":error?"Error":"Live · Dataverse"}
              </span>
            </div>
            {lastUpdated && (
              <span style={{fontSize:9,color:"#3a5a3e"}}>
                Updated {lastUpdated.toLocaleTimeString()}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* ── Error banner ── */}
      {error && !loading && (
        <div style={{margin:"16px 28px",background:T.redPale,
          border:`2px solid ${T.red}44`,borderRadius:12,padding:"12px 18px",
          display:"flex",justifyContent:"space-between",alignItems:"center"}}>
          <span style={{fontSize:13,color:T.red,fontWeight:700}}>
            ⚠️ Could not reach the API: {error}
          </span>
          <button onClick={loadDashboard}
            style={{background:T.red,color:"#fff",border:"none",borderRadius:8,
              padding:"7px 16px",cursor:"pointer",fontFamily:"inherit",
              fontWeight:700,fontSize:12}}>
            Retry
          </button>
        </div>
      )}

      {/* ── Loading ── */}
      {loading && (
        <div style={{display:"flex",alignItems:"center",justifyContent:"center",
          padding:72,gap:16}}>
          <Spinner/>
          <span style={{fontSize:14,color:T.textMid,fontWeight:600}}>
            Loading from Dataverse…
          </span>
        </div>
      )}

      {/* ── Empty state ── */}
      {isEmpty && (
        <EmptyState onOpenWizard={()=>setShowWizard(true)}/>
      )}

      {/* ── Real Time Status ── */}
      {!loading && !error && data && mode==="snapshot" && (
        <SnapshotView data={data} onOpenWizard={()=>setShowWizard(true)}/>
      )}

      {/* ── Predictive Playground ── */}
      {!loading && !error && data && mode==="whatif" && (
        <PredictionPanel liveData={data}/>
      )}
    </div>
  );
}
