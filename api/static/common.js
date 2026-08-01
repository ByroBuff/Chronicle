const $ = id => document.getElementById(id);

function esc(s){
  return String(s ?? "").replace(/[&<>"']/g, c =>
    ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

const fmt = n => (n ?? 0).toLocaleString();
const pct = f => (f == null ? "–" : Math.round(f * 100) + "%");
const perSec = n => (n == null ? "–" : n.toFixed(1) + "/s");

async function getJSON(path){
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), 8000);
  try{
    const r = await fetch(path, {signal: ctrl.signal, cache: "no-store"});
    if(!r.ok){
      let detail;
      try{ detail = (await r.json()).detail; }catch{ /* no JSON body */ }
      throw new Error(detail || ("HTTP " + r.status));
    }
    return await r.json();
  } finally { clearTimeout(t); }
}

function articleTitle(a){
  return a.title && a.title !== a.url ? a.title : a.url;
}

function articleBadges(a){
  const lang = a.language && a.language !== "en"
    ? `<span class="badge lang">${esc(a.language)}</span>` : "";
  const story = a.story_id
    ? `<a class="badge story" href="/dashboard/story/${a.story_id}">story #${a.story_id}</a>`
    : "";
  return lang + story;
}

function renderArticleRows(items, isNewFn){
  return items.map(a => {
    const flash = isNewFn && isNewFn(a) ? " flash" : "";
    return `<div class="art${flash}">
      <span class="id">#${a.article_id}</span>
      <span class="t"><a href="/dashboard/article/${a.article_id}">${esc(articleTitle(a))}</a></span>
      <span class="domain">${esc(a.domain || "—")}</span>
      <span class="badges">${articleBadges(a)}</span>
      <span class="d">${esc(a.published ?? "—")}</span>
    </div>`;
  }).join("");
}

function renderEntityRows(items){
  return items.map(e => `
    <div class="ent">
      <span class="name" title="${esc(e.canonical_name)}"><span class="type">${esc(e.entity_type)}</span> <a href="/dashboard/entity/${e.entity_id}">${esc(e.canonical_name)}</a></span>
      ${e.article_count != null ? `<span class="cnt">×${e.article_count}</span>` : ""}
    </div>`).join("");
}
