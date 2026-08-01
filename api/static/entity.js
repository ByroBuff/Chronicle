const entityId = location.pathname.split("/").filter(Boolean).pop();
const LIMIT = 20;

const state = { offset: 0, total: 0 };

function renderHeader(e){
  document.title = `Chronicle · ${e.canonical_name}`;

  $("entityHeader").innerHTML = `
    <div class="eyebrow">${esc(e.entity_type)}</div>
    <h1 class="article-title">${esc(e.canonical_name)}</h1>
    <div class="article-meta">
      <span>${e.article_count ?? 0} article${(e.article_count ?? 0) === 1 ? "" : "s"}</span>
    </div>`;
}

function renderArticles(data){
  state.total = data.total;
  const el = $("entityArticles");
  if(!data.items.length){
    el.innerHTML = `<div class="empty">no articles reference this entity yet</div>`;
    return;
  }
  el.innerHTML = renderArticleRows(data.items);
  renderPager();
}

function renderPager(){
  const el = $("entityPager");
  if(state.total <= LIMIT){ el.innerHTML = ""; return; }

  const from = state.offset + 1;
  const to = Math.min(state.offset + LIMIT, state.total);
  el.innerHTML = `
    <button type="button" id="pagerPrev" ${state.offset === 0 ? "disabled" : ""}>← prev</button>
    <span>${from}–${to} of ${state.total}</span>
    <button type="button" id="pagerNext" ${to >= state.total ? "disabled" : ""}>next →</button>`;

  $("pagerPrev").addEventListener("click", () => { state.offset = Math.max(0, state.offset - LIMIT); loadArticles(); });
  $("pagerNext").addEventListener("click", () => { state.offset += LIMIT; loadArticles(); });
}

async function loadArticles(){
  const data = await getJSON(`/api/entities/${entityId}/articles?limit=${LIMIT}&offset=${state.offset}`);
  renderArticles(data);
}

async function load(){
  try{
    const entity = await getJSON(`/api/entities/${entityId}`);
    renderHeader(entity);
  }catch(e){
    $("entityHeader").innerHTML = `<div class="empty">Entity #${esc(entityId)} not found.</div>`;
    $("entityArticles").innerHTML = "";
    return;
  }

  loadArticles();
}

load();
