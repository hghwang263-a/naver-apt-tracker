async function loadData() {
  const res = await fetch("data.json?ts=" + Date.now());
  return await res.json();
}

function eok(v) {
  if (v == null || Number.isNaN(Number(v))) return "-";
  return Number(v).toFixed(2) + "억";
}

function latestByComplex(snapshots) {
  const map = {};
  for (const s of snapshots) map[s.complex_name] = s;
  return Object.values(map);
}

function getPrevious(snapshots, name, current) {
  const list = snapshots
    .filter(x => x.complex_name === name && x.collected_at !== current.collected_at)
    .sort((a,b) => a.collected_at.localeCompare(b.collected_at));
  return list.length ? list[list.length - 1] : null;
}

function minPrice(snapshot) {
  const prices = (snapshot?.listings || [])
    .map(x => x.price_eok)
    .filter(x => x != null);
  return prices.length ? Math.min(...prices) : null;
}

function belowTarget(snapshot, target) {
  return (snapshot?.listings || [])
    .filter(x => x.price_eok != null && x.price_eok <= target).length;
}

function renderCards(latest, snapshots, target) {
  const el = document.getElementById("summary");
  el.innerHTML = latest.map(s => {
    const prev = getPrevious(snapshots, s.complex_name, s);
    const diff = prev ? s.listing_count - prev.listing_count : null;
    const sign = diff > 0 ? "+" : "";
    return `
      <div class="card">
        <div class="name">${s.complex_name}</div>
        <div class="value">${s.listing_count}건</div>
        <div class="sub">
          최저 ${eok(minPrice(s))} · ${target}억 이하 ${belowTarget(s, target)}건
          ${diff == null ? "" : ` · 전회 대비 ${sign}${diff}`}
        </div>
      </div>
    `;
  }).join("");
}

function renderChart(latest, snapshots) {
  const canvas = document.getElementById("countChart");
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth || 800;
  const height = 260;
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  ctx.scale(dpr, dpr);

  const all = latest.map(s => s.listing_count);
  const max = Math.max(...all, 1);
  const left = 180;
  const top = 25;
  const row = 48;
  const barMax = width - left - 40;

  ctx.font = "13px sans-serif";
  latest.forEach((s, i) => {
    const y = top + i * row;
    const w = (s.listing_count / max) * barMax;

    ctx.fillStyle = "#6b7280";
    ctx.fillText(s.complex_name, 0, y + 18);

    ctx.fillStyle = "#111827";
    ctx.fillRect(left, y + 3, Math.max(w, 2), 22);

    ctx.fillStyle = "#202124";
    ctx.fillText(`${s.listing_count}건`, left + w + 8, y + 19);
  });
}

function renderChanges(latest) {
  const price = [];
  const added = [];
  const removed = [];

  for (const s of latest) {
    const c = s.changes_from_previous || {};
    for (const x of c.price_changes || []) price.push(x);
    for (const x of c.added || []) added.push(x);
    for (const x of c.removed || []) removed.push(x);
  }

  const priceEl = document.getElementById("priceChanges");
  priceEl.innerHTML = price.length ? price.slice(-20).reverse().map(x => `
    <div class="item">
      <div class="item-title">${x.complex_name} · ${x.area_exclusive ?? "-"}㎡ · ${x.floor ?? "-"}</div>
      <div class="item-meta">
        <span class="${x.direction === "down" ? "down" : "up"}">
          ${eok(x.old_price_eok)} → ${eok(x.new_price_eok)}
        </span>
        · ${x.direction === "down" ? "인하" : "인상"}
      </div>
    </div>
  `).join("") : '<div class="empty">최근 가격 변경이 없습니다.</div>';

  document.getElementById("newListings").innerHTML = added.length ? added.slice(-20).reverse().map(x => `
    <div class="item">
      <div class="item-title">${x.complex_name} · ${eok(x.price_eok)}</div>
      <div class="item-meta">${x.area_exclusive ?? "-"}㎡ · ${x.floor ?? "-"} · ${x.direction ?? "-"}</div>
    </div>
  `).join("") : '<div class="empty">최근 신규 매물이 없습니다.</div>';

  document.getElementById("removedListings").innerHTML = removed.length ? removed.slice(-20).reverse().map(x => `
    <div class="item">
      <div class="item-title">${x.complex_name} · ${eok(x.price_eok)}</div>
      <div class="item-meta">${x.area_exclusive ?? "-"}㎡ · ${x.floor ?? "-"} · 마지막 관측 매물</div>
    </div>
  `).join("") : '<div class="empty">최근 사라진 매물이 없습니다.</div>';
}

function renderTable(latest, target) {
  const rows = latest
    .sort((a,b) => a.complex_name.localeCompare(b.complex_name))
    .map(s => `
      <tr>
        <td>${s.complex_name}</td>
        <td>${s.collected_at.replace("T", " ")}</td>
        <td>${s.listing_count}</td>
        <td>${eok(minPrice(s))}</td>
        <td>${belowTarget(s, target)}</td>
      </tr>
    `).join("");
  document.getElementById("snapshotTable").innerHTML = rows;
}

(async () => {
  try {
    const data = await loadData();
    const snapshots = data.snapshots || [];
    const latest = latestByComplex(snapshots);
    const target = data.target_price_eok ?? 10.3;

    document.getElementById("updated").textContent =
      `마지막 수집: ${data.updated_at ? data.updated_at.replace("T", " ") : "-"}`;

    renderCards(latest, snapshots, target);
    renderChart(latest, snapshots);
    renderChanges(latest);
    renderTable(latest, target);
  } catch (err) {
    document.getElementById("updated").textContent =
      "데이터를 불러오지 못했습니다. GitHub Actions가 한 번 실행되었는지 확인하세요.";
    console.error(err);
  }
})();
