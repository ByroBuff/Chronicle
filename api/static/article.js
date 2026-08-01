const articleId = location.pathname.split("/").filter(Boolean).pop();

function renderHeader(a){
  document.title = `Chronicle · ${a.title || a.url}`;

  const langBadge = a.language ? `<span class="badge lang">${esc(a.language)}</span>` : "";
  const storyBadge = a.story_id ? `<a class="badge story" href="/dashboard/story/${a.story_id}">story #${a.story_id}</a>` : "";

  $("articleHeader").innerHTML = `
    <div class="eyebrow">article #${esc(a.article_id)}</div>
    <h1 class="article-title">${esc(a.title || a.url)}</h1>
    <div class="article-meta">
      <a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.url)}</a>
      <span>${esc(a.published ?? "no publish date")}</span>
      ${langBadge}
      ${storyBadge}
    </div>`;

  $("articleBody").textContent = a.clean_text || "(no extracted text)";
}

function renderEntities(entities){
  const el = $("articleEntities");
  if(!entities || !entities.length){
    el.innerHTML = `<div class="empty">no entities extracted</div>`;
    return;
  }
  el.innerHTML = renderEntityRows(entities);
}

async function loadSimilar(){
  const el = $("similarArticles");
  try{
    const data = await getJSON(`/api/articles/${articleId}/similar?limit=8`);
    if(!data.items.length){
      el.innerHTML = `<div class="empty">no similar articles yet</div>`;
      return;
    }
    el.innerHTML = data.items.map(s => `
      <div class="sim-item">
        <a href="/dashboard/article/${s.article_id}">${esc(articleTitle(s))}</a>
        <span class="sim-score">${Math.round(s.similarity * 100)}%</span>
      </div>`).join("");
  }catch(e){
    el.innerHTML = `<div class="empty">similarity not available yet</div>`;
  }
}

async function loadStory(){
  try{
    const story = await getJSON(`/api/articles/${articleId}/story`);
    const others = story.articles.filter(a => String(a.article_id) !== String(articleId));

    if(!others.length) return;

    $("storySection").hidden = false;
    $("storyMeta").textContent =
      `${story.article_count} article${story.article_count === 1 ? "" : "s"} · updated ${new Date(story.updated_at).toLocaleString()}`;
    $("storyLink").href = `/dashboard/story/${story.story_id}`;

    $("storyArticles").innerHTML = renderArticleRows(others);
  }catch(e){
    // Not clustered into a story yet — nothing to show.
  }
}

async function load(){
  try{
    const article = await getJSON(`/api/articles/${articleId}`);
    renderHeader(article);
    renderEntities(article.entities);
  }catch(e){
    $("articleHeader").innerHTML = `<div class="empty">Article #${esc(articleId)} not found.</div>`;
    $("articleBody").textContent = "";
    return;
  }

  loadSimilar();
  loadStory();
}

load();
