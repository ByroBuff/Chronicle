const storyId = location.pathname.split("/").filter(Boolean).pop();

function renderHeader(s){
  const title = s.label || `Story #${s.story_id}`;
  document.title = `Chronicle · ${title}`;

  $("storyHeader").innerHTML = `
    <div class="eyebrow">story #${esc(s.story_id)}</div>
    <h1 class="article-title">${esc(title)}</h1>
    <div class="article-meta">
      <span>${s.article_count} article${s.article_count === 1 ? "" : "s"}</span>
      <span>created ${new Date(s.created_at).toLocaleString()}</span>
      <span>updated ${new Date(s.updated_at).toLocaleString()}</span>
    </div>`;
}

function renderArticles(items){
  const el = $("storyArticles");
  if(!items.length){
    el.innerHTML = `<div class="empty">no articles in this story</div>`;
    return;
  }
  el.innerHTML = renderArticleRows(items);
}

async function load(){
  try{
    const story = await getJSON(`/api/stories/${storyId}`);
    renderHeader(story);
    renderArticles(story.articles);
  }catch(e){
    $("storyHeader").innerHTML = `<div class="empty">Story #${esc(storyId)} not found.</div>`;
  }
}

load();
