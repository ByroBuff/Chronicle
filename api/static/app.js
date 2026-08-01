const SVGNS = "http://www.w3.org/2000/svg";
const ENTITY_TYPES = ["ALL", "PERSON", "LOCATION", "EMAIL"];

const state = {
  view: localStorage.getItem("chronicle:view") || "data",
  paused: false,
  up: false,
  pipelineWindow: 120, pipelineBucket: 10,
  entityType: null,
  articleQuery: "",
  seenArticleIds: new Set(),
  timers: {},
};

function setStatus(up, text){
  state.up = up;
  const el = $("status");
  el.className = "status " + (up ? "up" : "down");
  $("statusText").textContent = text;
}

/* ---------------------------------------------------------------- tabs */

function switchView(view){
  state.view = view;
  localStorage.setItem("chronicle:view", view);
  document.querySelectorAll(".tab").forEach(b =>
    b.setAttribute("aria-selected", b.dataset.view === view ? "true" : "false"));
  $("view-data").hidden = view !== "data";
  $("view-pipeline").hidden = view !== "pipeline";
  restartTimers();
}

function clearTimers(){
  Object.values(state.timers).forEach(clearInterval);
  state.timers = {};
}

function restartTimers(){
  clearTimers();
  if(state.view === "data"){
    dataTick();
    state.timers.data = setInterval(dataTick, 5000);
  } else {
    pipelineTick();
    state.timers.pipeline = setInterval(pipelineTick, 3000);
  }
}

document.querySelectorAll(".tab").forEach(btn =>
  btn.addEventListener("click", () => switchView(btn.dataset.view)));

$("pause").addEventListener("click", e => {
  state.paused = !state.paused;
  e.target.setAttribute("aria-pressed", state.paused ? "true" : "false");
  e.target.textContent = state.paused ? "▶ resume" : "⏸ pause";
  if(!state.paused){ state.view === "data" ? dataTick() : pipelineTick(); }
  else setStatus(state.up, "paused");
});

/* --------------------------------------------------------- ingest form */

function showIngestMsg(text, kind){
  const el = $("ingestMsg");
  if(!text){ el.className = "ingest-msg"; el.textContent = ""; return; }
  el.className = `ingest-msg show ${kind || ""}`;
  el.textContent = text;
}

$("ingestForm").addEventListener("submit", async e => {
  e.preventDefault();
  const input = $("ingestUrl");
  const url = input.value.trim();
  if(!url) return;

  const btn = $("ingestBtn");
  btn.disabled = true;
  btn.textContent = "Ingesting…";
  showIngestMsg("", null);

  try{
    const res = await fetch("/api/ingest", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url}),
    });
    const data = await res.json().catch(() => ({}));
    if(!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);

    showIngestMsg(
      `Article #${data.article_id} ${data.created ? "ingested" : "already existed"} — opening…`,
      "ok",
    );
    input.value = "";
    setTimeout(() => { window.location.href = `/dashboard/article/${data.article_id}`; }, 500);
  }catch(err){
    showIngestMsg(err.message, "err");
  }finally{
    btn.disabled = false;
    btn.textContent = "Ingest";
  }
});

/* ------------------------------------------------------- article feed */

async function loadArticles(){
  const q = state.articleQuery ? `&q=${encodeURIComponent(state.articleQuery)}` : "";
  const data = await getJSON(`/api/articles?limit=25${q}`);
  renderArticles(data.items);
}

function renderArticles(items){
  const el = $("liveArticles");
  if(!items.length){
    el.innerHTML = `<div class="empty">no articles yet — ingest one above or wait for the collector</div>`;
    return;
  }

  const firstLoad = state.seenArticleIds.size === 0;
  el.innerHTML = renderArticleRows(items, a => !firstLoad && !state.seenArticleIds.has(a.article_id));
  state.seenArticleIds = new Set(items.map(a => a.article_id));
}

let searchDebounce;
$("articleSearch").addEventListener("input", e => {
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(() => {
    state.articleQuery = e.target.value.trim();
    loadArticles();
  }, 350);
});

/* ------------------------------------------------------------ stories */

async function loadStories(){
  const data = await getJSON("/api/stories?limit=12");
  renderStories(data.items);
}

function renderStories(items){
  const el = $("stories");
  if(!items.length){
    el.innerHTML = `<div class="empty">no clustered stories yet</div>`;
    return;
  }
  el.innerHTML = items.map(s => `
    <div class="story-row">
      <a href="/dashboard/story/${s.story_id}">${esc(s.label || `Story #${s.story_id}`)}</a>
      <span class="count">${s.article_count} article${s.article_count === 1 ? "" : "s"}</span>
      <span class="time">${new Date(s.updated_at).toLocaleString()}</span>
    </div>`).join("");
}

/* ----------------------------------------------------------- entities */

function buildChips(){
  const box = $("chips");
  box.innerHTML = "";
  ENTITY_TYPES.forEach(t => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.textContent = t.toLowerCase();
    const active = (t === "ALL" && !state.entityType) || t === state.entityType;
    b.setAttribute("aria-pressed", active ? "true" : "false");
    b.onclick = () => { state.entityType = (t === "ALL") ? null : t; buildChips(); loadEntities(); };
    box.appendChild(b);
  });
}

async function loadEntities(){
  const q = state.entityType ? `&entity_type=${state.entityType}` : "";
  const data = await getJSON(`/api/entities?limit=18${q}`);
  renderEntities(data);
}

function renderEntities(d){
  const el = $("entities");
  if(!d.items || !d.items.length){
    el.innerHTML = `<div class="empty">no entities for this filter yet</div>`;
    return;
  }
  el.innerHTML = renderEntityRows(d.items);
}

/* -------------------------------------------------------- data ticker */

async function dataTick(){
  if(state.paused) return;
  try{
    await Promise.all([loadArticles(), loadStories(), loadEntities()]);
    setStatus(true, "live");
    $("dataUpdated").textContent = "last update " + new Date().toLocaleTimeString();
  }catch(e){
    setStatus(false, "disconnected — retrying");
  }
}

/* ----------------------------------------------------- pipeline chart */

function getCSS(v){ return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }

function renderChart(series){
  const svg = $("chart");
  svg.innerHTML = "";
  const W = 1000, H = 260, padL = 44, padR = 12, padT = 14, padB = 22;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const n = series.length;
  const maxRate = Math.max(0.001, ...series.flatMap(b => [b.scraped_per_second, b.ingested_per_second]));
  const niceMax = maxRate <= 1 ? Math.ceil(maxRate*10)/10 : Math.ceil(maxRate);
  const x = i => padL + (n <= 1 ? 0 : (i/(n-1))*(W-padL-padR));
  const y = v => padT + (1 - v/niceMax)*(H-padT-padB);

  const mk = (tag, attrs) => { const e = document.createElementNS(SVGNS, tag);
    for(const k in attrs) e.setAttribute(k, attrs[k]); return e; };

  const defs = mk("defs",{});
  defs.innerHTML = `<pattern id="hatch" width="6" height="6" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
    <rect width="6" height="6" fill="rgba(239,68,68,0.05)"/>
    <line x1="0" y1="0" x2="0" y2="6" stroke="rgba(239,68,68,0.35)" stroke-width="1.2"/></pattern>`;
  svg.appendChild(defs);

  [0, niceMax/2, niceMax].forEach(v => {
    svg.appendChild(mk("line",{x1:padL,y1:y(v),x2:W-padR,y2:y(v),stroke:getCSS("--border"),"stroke-width":1}));
    const lab = mk("text",{x:padL-8,y:y(v)+3,fill:getCSS("--faint"),"font-size":11,"text-anchor":"end","font-family":"IBM Plex Mono, monospace"});
    lab.textContent = (niceMax<=1 ? v.toFixed(1) : Math.round(v));
    svg.appendChild(lab);
  });

  if(n === 0) return;

  const sPts = series.map((b,i) => [x(i), y(b.scraped_per_second)]);
  const iPts = series.map((b,i) => [x(i), y(b.ingested_per_second)]);

  const band = sPts.map(p=>p.join(",")).join(" ") + " " +
               iPts.slice().reverse().map(p=>p.join(",")).join(" ");
  svg.appendChild(mk("polygon",{points:band,fill:"url(#hatch)"}));

  const iArea = `${padL},${y(0)} ` + iPts.map(p=>p.join(",")).join(" ") + ` ${x(n-1)},${y(0)}`;
  svg.appendChild(mk("polygon",{points:iArea,fill:"rgba(245,165,36,0.10)"}));

  const line = (pts,color) => mk("polyline",{points:pts.map(p=>p.join(",")).join(" "),
    fill:"none",stroke:color,"stroke-width":2,"stroke-linejoin":"round","stroke-linecap":"round"});
  svg.appendChild(line(iPts, getCSS("--ingested")));
  svg.appendChild(line(sPts, getCSS("--scraped")));

  [[sPts.at(-1),getCSS("--scraped")],[iPts.at(-1),getCSS("--ingested")]].forEach(([p,c])=>{
    svg.appendChild(mk("circle",{cx:p[0],cy:p[1],r:3.2,fill:c}));
  });
}

function renderSnapshot(d){
  const t = d.throughput, tot = d.totals, q = d.queue, w = d.workers;
  $("fScraped").textContent = perSec(t.scraped_per_second);
  $("fIngested").textContent = perSec(t.ingested_per_second);
  const inWin = t.totals_in_window;
  const loss = inWin.scraped ? Math.max(0,(inWin.scraped - inWin.ingested)/inWin.scraped) : 0;
  $("fLoss").textContent = pct(loss);
  $("fLoss").style.color = loss > 0.5 ? "var(--down)" : loss > 0.2 ? "var(--warn)" : "var(--fg)";
  $("fBatch").textContent = t.avg_batch_seconds ? t.avg_batch_seconds.toFixed(2)+"s" : "–";
  $("fBps").textContent = perSec(t.batches_per_second);

  $("kIngested").textContent = fmt(tot.ingested);
  $("kScraped").textContent = "scraped " + fmt(tot.scraped);
  $("kQueue").textContent = fmt(q.queued);
  $("kRunning").textContent = "running " + fmt(q.started);
  $("kWorkers").textContent = fmt(w.total);
  $("kWorkerSub").textContent = `busy ${w.busy} · idle ${w.idle}`;
  $("kSuccess").textContent = pct(tot.scrape_success_rate);
  $("kFailed").textContent = "failed " + fmt(q.failed);
  $("kFailed").style.color = q.failed > 0 ? "var(--down)" : "var(--muted)";

  renderWorkers(w.workers);
  renderQueue(q);
  $("fGenerated").textContent = "snapshot " + new Date(d.generated_at).toLocaleTimeString();
}

function renderWorkers(list){
  const el = $("workers");
  if(!list || !list.length){ el.innerHTML = `<div class="empty">no workers attached to the queue — start one with <span style="color:var(--fg)">docker compose up -d worker</span></div>`; return; }
  el.innerHTML = list.map(w => {
    const stale = w.heartbeat_age_seconds != null && w.heartbeat_age_seconds > 60;
    const cls = stale ? "stale" : (w.state === "busy" ? "busy" : "idle");
    const label = stale ? "stale" : w.state;
    const hb = w.heartbeat_age_seconds != null ? `${w.heartbeat_age_seconds}s ago` : "–";
    const job = w.current_job_id ? `job ${w.current_job_id.slice(0,8)}` : "no active job";
    return `<div class="worker">
      <span class="badge ${cls}">${label}</span>
      <span class="wname">${esc(w.name)}</span>
      <span class="num" style="color:var(--muted);font-size:11.5px">▲${w.working_time_seconds}s</span>
      <span class="wmeta">${job} · ok ${w.successful_jobs} · fail ${w.failed_jobs} · heartbeat ${hb}</span>
    </div>`;
  }).join("");
}

function renderQueue(q){
  const rows = [
    ["Queued", q.queued, false],
    ["Running", q.started, false],
    ["Finished (rolling)", q.finished, false],
    ["Failed", q.failed, q.failed > 0],
  ];
  $("queue").innerHTML = rows.map(([k,v,bad]) =>
    `<div class="qrow ${bad?'bad':''}"><span class="k">${k}</span><span class="v num">${fmt(v)}</span></div>`
  ).join("");
}

async function pipelineTick(){
  if(state.paused) return;
  try{
    const [snap, ts] = await Promise.all([
      getJSON(`/api/metrics?window=${state.pipelineWindow}`),
      getJSON(`/api/metrics/timeseries?window=${state.pipelineWindow}&bucket=${state.pipelineBucket}`),
    ]);
    renderSnapshot(snap);
    renderChart(ts.series);
    setStatus(true, "live");
    $("fUpdated").textContent = "last update " + new Date().toLocaleTimeString();
  }catch(e){
    setStatus(false, "disconnected — retrying");
  }
}

$("pipelineWindow").addEventListener("change", e => {
  const [w,b] = e.target.value.split(",").map(Number);
  state.pipelineWindow = w; state.pipelineBucket = b;
  pipelineTick();
});

/* ------------------------------------------------------------- start */

switchView(state.view);
buildChips();
