const LIMIT = 20;

const FIELDS = {
  title: "fTitle",
  text: "fText",
  domain: "fDomain",
  language: "fLanguage",
  date_from: "fFrom",
  date_to: "fTo",
};

const state = { offset: 0, total: 0 };

function readForm(){
  const params = {};
  for(const [key, id] of Object.entries(FIELDS)){
    const value = $(id).value.trim();
    if(value) params[key] = value;
  }
  return params;
}

function fillForm(params){
  for(const [key, id] of Object.entries(FIELDS)){
    $(id).value = params[key] || "";
  }
}

function paramsFromLocation(){
  const search = new URLSearchParams(location.search);
  const params = {};
  for(const key of Object.keys(FIELDS)){
    const value = search.get(key);
    if(value) params[key] = value;
  }
  state.offset = parseInt(search.get("offset") || "0", 10) || 0;
  return params;
}

function pushLocation(params){
  const search = new URLSearchParams(params);
  if(state.offset) search.set("offset", state.offset);
  const qs = search.toString();
  history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
}

function renderResults(data){
  state.total = data.total;
  const el = $("searchResults");
  $("resultCount").textContent = data.total ? `${data.total} match${data.total === 1 ? "" : "es"}` : "";

  if(!data.items.length){
    el.innerHTML = `<div class="empty">no articles match those criteria</div>`;
    $("searchPager").innerHTML = "";
    return;
  }

  el.innerHTML = renderArticleRows(data.items);
  renderPager();
}

function renderPager(){
  const el = $("searchPager");
  if(state.total <= LIMIT){ el.innerHTML = ""; return; }

  const from = state.offset + 1;
  const to = Math.min(state.offset + LIMIT, state.total);
  el.innerHTML = `
    <button type="button" id="pagerPrev" ${state.offset === 0 ? "disabled" : ""}>← prev</button>
    <span>${from}–${to} of ${state.total}</span>
    <button type="button" id="pagerNext" ${to >= state.total ? "disabled" : ""}>next →</button>`;

  $("pagerPrev").addEventListener("click", () => { state.offset = Math.max(0, state.offset - LIMIT); runSearch(); });
  $("pagerNext").addEventListener("click", () => { state.offset += LIMIT; runSearch(); });
}

async function runSearch(){
  const params = readForm();
  pushLocation(params);

  const el = $("searchResults");
  el.innerHTML = `<div class="empty">searching…</div>`;

  const query = new URLSearchParams({ ...params, limit: LIMIT, offset: state.offset });

  try{
    const data = await getJSON(`/api/articles?${query}`);
    renderResults(data);
  }catch(e){
    el.innerHTML = `<div class="empty">search failed: ${esc(e.message)}</div>`;
    $("searchPager").innerHTML = "";
  }
}

$("searchForm").addEventListener("submit", e => {
  e.preventDefault();
  state.offset = 0;
  runSearch();
});

$("searchReset").addEventListener("click", () => {
  fillForm({});
  state.offset = 0;
  history.replaceState(null, "", location.pathname);
  $("searchResults").innerHTML = `<div class="empty">enter search criteria above and hit search</div>`;
  $("resultCount").textContent = "";
  $("searchPager").innerHTML = "";
});

const initialParams = paramsFromLocation();
fillForm(initialParams);
if(Object.keys(initialParams).length) runSearch();
