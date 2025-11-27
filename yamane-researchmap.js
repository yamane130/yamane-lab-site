// yamane-researchmap.js
// ---------------------------------------------
// researchmap_data.json（Pythonで取得したローカルJSON）を読み込み、
// 論文 / 競争的資金 / 受賞 をページに表示するスクリプト
// ---------------------------------------------

const DATA_URL = "researchmap_data.json";

/** JSON ファイルを 1 回読む */
async function loadResearchmapData() {
  const res = await fetch(DATA_URL);
  if (!res.ok) {
    console.error("Failed to load", DATA_URL, res.status, res.statusText);
    return null;
  }
  const data = await res.json();
  console.log("researchmap_data.json loaded");
  return data;
}

/** 日本語優先でフィールドを文字列にする */
function pickText(field) {
  if (!field) return "";
  if (typeof field === "string") return field;
  if (field.ja && typeof field.ja === "string" && field.ja.trim() !== "") {
    return field.ja;
  }
  if (field.en && typeof field.en === "string" && field.en.trim() !== "") {
    return field.en;
  }
  return field.ja || field.en || "";
}

/** 著者配列を "Yamane, T., Chun, P. J." みたいな文字列に */
function formatAuthors(authors) {
  if (!authors) return "";
  let list = [];

  if (Array.isArray(authors)) {
    list = authors;
  } else if (Array.isArray(authors.ja)) {
    list = authors.ja;
  } else if (Array.isArray(authors.en)) {
    list = authors.en;
  } else {
    return "";
  }

  const names = list
    .map((a) => {
      if (!a) return "";
      if (a.name) return a.name;
      const parts = [];
      if (a.family_name) parts.push(a.family_name);
      if (a.given_name) parts.push(a.given_name);
      if (parts.length) return parts.join(" ");
      return Object.values(a).join(" ");
    })
    .filter((s) => s && s.trim() !== "");

  return names.join(", ");
}

/** "YYYY-MM-DD" から年だけ取り出す */
function extractYear(dateStr) {
  if (!dateStr || typeof dateStr !== "string") return "";
  return dateStr.slice(0, 4);
}

/** DOI をいい感じに拾う */
function getDoi(item) {
  if (!item) return "";
  if (item.doi && typeof item.doi === "string") return item.doi;
  if (
    item.identifiers &&
    item.identifiers.doi &&
    Array.isArray(item.identifiers.doi) &&
    item.identifiers.doi.length > 0
  ) {
    return item.identifiers.doi[0];
  }
  return "";
}

/** 論文の描画 */
function renderPublications(items) {
  const allUl = document.getElementById("publist-all");
  const selUl = document.getElementById("publist-selected");
  if (!allUl && !selUl) return;

  if (!Array.isArray(items)) items = [];

  // 一旦全部そのまま使う
  let filtered = items.slice();

  // 発行日の新しい順（date が無いものは後ろへ）
  filtered.sort((a, b) => {
    const da = a.publication_date || "";
    const db = b.publication_date || "";
    return db.localeCompare(da);
  });

  console.log("publications:", filtered.length);

  // li を作る
  const makeLi = (item) => {
    const li = document.createElement("li");

    const title = pickText(item.paper_title || item.title);
    const journal = pickText(item.publication_name || item.journal);
    const date = item.publication_date || "";
    const year = extractYear(date);
    const volume = item.volume || "";
    const number = item.number || item.issue || "";
    const authors = formatAuthors(item.authors || item.author);
    const doi = getDoi(item);

    // ページ情報（いくつかのパターンを試す）
    let pages = "";
    if (item.page_range) {
      pages = item.page_range;
    } else if (item.starting_page || item.ending_page) {
      const sp = item.starting_page || "";
      const ep = item.ending_page || "";
      pages = sp && ep ? `${sp}–${ep}` : sp || ep;
    } else if (item.pages) {
      pages = item.pages;
    }

    let html = "";

    if (authors) html += `${authors}, `;
    if (title) html += `“${title}”`;
    if (journal) html += `, <em>${journal}</em>`;
    if (volume) {
      html += `, ${volume}`;
      if (number) html += `(${number})`;
    }
    if (year) html += `, ${year}`;
    if (pages) html += `, pp.${pages}`;
    if (doi) {
      const url = `https://doi.org/${doi}`;
      html += `, <a href="${url}" target="_blank" rel="noopener">doi:${doi}</a>`;
    }

    li.innerHTML = html;
    return li;
  };

  // 代表的な論文: major_achievement が true のものがあればそれを、なければ上位 6 件
  if (selUl) {
    let selected = filtered.filter((it) => it.major_achievement === true);
    if (!selected.length) selected = filtered.slice(0, 6);
    selected.forEach((item) => selUl.appendChild(makeLi(item)));
  }

  // 最近の論文: 上位 30 件
  if (allUl) {
    filtered.slice(0, 30).forEach((item) => allUl.appendChild(makeLi(item)));
  }
}

/** 競争的資金の描画 */
function renderGrants(items) {
  const ul = document.getElementById("grants-list");
  if (!ul) return;

  if (!Array.isArray(items)) items = [];

  let filtered = items.slice();

  filtered.sort((a, b) => {
    const da = a.from_date || "";
    const db = b.from_date || "";
    return db.localeCompare(da);
  });

  console.log("grants:", filtered.length);

  filtered.forEach((item) => {
    const li = document.createElement("li");

    const title = pickText(item.research_project_title || item.title);
    const offerOrg = pickText(item.offer_organization);
    const systemName = pickText(item.system_name);
    const category = pickText(item.category);
    const instName = pickText(item.institution_name);
    const from = item.from_date || "";
    const to = item.to_date || "";
    const role =
      pickText(item.research_project_owner_role) ||
      pickText(item.research_project_roles);

    let html = "";
    if (title) html += `<strong>${title}</strong>`;

    const meta = [];
    if (offerOrg) meta.push(offerOrg);
    if (systemName) meta.push(systemName);
    if (category) meta.push(category);
    if (instName) meta.push(instName);
    if (from || to) meta.push(`${from} – ${to}`);
    if (role) meta.push(role);

    if (meta.length) {
      html += `<br><span class="muted">${meta.join(" / ")}</span>`;
    }

    li.innerHTML = html;
    ul.appendChild(li);
  });
}

/** 受賞の描画 */
function renderAwards(items) {
  const ul = document.getElementById("awards-list");
  if (!ul) return;

  if (!Array.isArray(items)) items = [];

  let filtered = items.slice();

  filtered.sort((a, b) => {
    const da = a.award_date || "";
    const db = b.award_date || "";
    return db.localeCompare(da);
  });

  console.log("awards:", filtered.length);

  filtered.forEach((item) => {
    const li = document.createElement("li");

    const awardName = pickText(item.award_name || item.name);
    const awardTitle = pickText(item.award_title || item.title);
    const assoc = pickText(item.association || item.organization);
    const date = item.award_date || "";

    let html = "";
    if (awardName) html += `<strong>${awardName}</strong>`;
    if (awardTitle) html += ` – ${awardTitle}`;

    const meta = [];
    if (assoc) meta.push(assoc);
    if (date) meta.push(date);

    if (meta.length) {
      html += `<br><span class="muted">${meta.join(" / ")}</span>`;
    }

    li.innerHTML = html;
    ul.appendChild(li);
  });
}

/** すべてをまとめて実行 */
async function renderAllFromLocalJson() {
  try {
    const data = await loadResearchmapData();
    if (!data) return;

    renderPublications(data.published_papers || []);
    renderGrants(data.research_projects || []);
    renderAwards(data.awards || []);
  } catch (e) {
    console.error("Failed to render from researchmap_data.json", e);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  renderAllFromLocalJson();
});
