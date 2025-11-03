// Minimal client-side CSV parser + scoring heuristic and UI wiring.
// Not a drop-in model runner. Heuristic:
// - expects an 'anomaly_score' column where higher means more normal.
// - if absent, we'll fabricate anomaly_score from clicks/impressions heuristics.
// - fraud_probability = 1 - scaled_anomaly_score (so 1 = max fraud)

// ---------- Utility helpers ----------
function el(id){ return document.getElementById(id); }
function parseCSV(text){
  const lines = text.split(/\r?\n/).filter(l=>l.trim().length>0);
  if(lines.length===0) return {fields:[], rows:[]};
  const fields = lines[0].split(',').map(f=>f.trim());
  const rows = [];
  for(let i=1;i<lines.length;i++){
    const cols = lines[i].split(',');
    if(cols.length !== fields.length) continue;
    const obj = {};
    for(let j=0;j<fields.length;j++){
      const v = cols[j].trim();
      // try number
      const n = Number(v);
      obj[fields[j]] = isNaN(n) ? v : n;
    }
    rows.push(obj);
  }
  return {fields, rows};
}
function clamp01(x){ return Math.max(0, Math.min(1, x)); }

// ---------- Scoring logic ----------
function compute_scores(rows){
  if(rows.length===0) return rows;

  // find anomaly_score column
  const hasAS = rows[0].hasOwnProperty('anomaly_score');
  let values = [];
  if(hasAS){
    values = rows.map(r => Number(r.anomaly_score || 0));
  } else {
    // fabricate using click_rate or clicks/impressions
    values = rows.map(r => {
      const impressions = Number(r.impressions || r.impr || 0);
      const clicks = Number(r.clicks || r.click || 0);
      const rate = impressions>0 ? clicks/impressions : 0;
      // heuristic: higher click rate (esp near 1) and very low interclick => suspicious -> lower anomaly_score
      const interclick = Number(r.interclick_mean || r.interclick || 5);
      // create score roughly between -1 and +1 where higher = normal
      let score = (1 - rate) * 0.6 + Math.tanh(interclick/10) * 0.4;
      // small random jitter for demo
      score = (score - 0.5) * 2; // map to roughly -1..1
      return Number(score.toFixed(3));
    });
  }

  // compute min/max for scaling
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(1e-6, max - min);

  // attach computed columns
  for(let i=0;i<rows.length;i++){
    const as = Number(values[i]);
    rows[i].anomaly_score = as;
    // fraud_probability = 1 - scaled(as) where scaled(as) maps min->0 max->1
    const scaled = (as - min) / range;
    rows[i].fraud_probability = Number((1 - clamp01(scaled)).toFixed(4));
    // is_outlier: treat as outlier if fraud_probability > 0.6 (tunable)
    rows[i].is_outlier = rows[i].fraud_probability > 0.6 ? 1 : 0;
  }
  return rows;
}

// ---------- UI helpers ----------
let currentRows = [];
let currentFields = [];

function renderMetrics(){
  const total = currentRows.length;
  const suspicious = currentRows.filter(r=>r.is_outlier===1).length;
  const avgFraud = total ? (currentRows.reduce((s,r)=>s + Number(r.fraud_probability || 0),0)/total) : 0;
  el('total-sessions').innerText = total;
  el('suspicious-sessions').innerText = suspicious;
  el('avg-fraud').innerText = avgFraud.toFixed(2);
}

function renderTable(){
  const filter = el('filter-select').value;
  const head = el('table-head');
  const body = el('table-body');
  head.innerHTML = '';
  body.innerHTML = '';

  const fieldsToShow = currentFields.slice(0, 12); // avoid huge tables; show first 12 cols
  // ensure important cols present
  if(!fieldsToShow.includes('anomaly_score')) fieldsToShow.push('anomaly_score');
  if(!fieldsToShow.includes('fraud_probability')) fieldsToShow.push('fraud_probability');
  if(!fieldsToShow.includes('is_outlier')) fieldsToShow.push('is_outlier');

  // head
  const trh = document.createElement('tr');
  fieldsToShow.forEach(f=>{
    const th = document.createElement('th');
    th.innerText = f;
    trh.appendChild(th);
  });
  head.appendChild(trh);

  // body rows
  let rowsToShow = currentRows.slice();
  if(filter==='suspicious') rowsToShow = rowsToShow.filter(r=>r.is_outlier===1);
  if(filter==='normal') rowsToShow = rowsToShow.filter(r=>r.is_outlier===0);

  // show first 50
  rowsToShow.slice(0,50).forEach(r=>{
    const tr = document.createElement('tr');
    fieldsToShow.forEach(f=>{
      const td = document.createElement('td');
      td.innerText = (r[f] === undefined) ? '' : r[f];
      tr.appendChild(td);
    });
    // color suspicious rows
    if(r.is_outlier===1) tr.style.background = '#fff3f3';
    body.appendChild(tr);
  });
}

function drawHistogram(){
  const cvs = el('histogram');
  const ctx = cvs.getContext('2d');
  ctx.clearRect(0,0,cvs.width,cvs.height);
  if(currentRows.length===0){
    ctx.fillStyle='#6b7280';
    ctx.font = '14px Arial';
    ctx.fillText('Upload CSV to see distribution', 12, 40);
    return;
  }
  const values = currentRows.map(r=>Number(r.anomaly_score || 0));
  // compute bins
  const nbins = 30;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(1e-6, max-min);
  const bins = new Array(nbins).fill(0);
  values.forEach(v=>{
    let idx = Math.floor(((v - min) / range) * (nbins-1));
    idx = Math.max(0, Math.min(nbins-1, idx));
    bins[idx]++;
  });

  // draw bars
  const padding = 20;
  const w = cvs.width - padding*2;
  const h = cvs.height - padding*2;
  const maxCount = Math.max(...bins);
  const barW = w / bins.length;
  ctx.fillStyle = '#e8f0ff';
  ctx.fillRect(padding, padding, w, h);

  for(let i=0;i<bins.length;i++){
    const x = padding + i*barW;
    const barH = maxCount ? (bins[i] / maxCount) * (h - 10) : 0;
    ctx.fillStyle = '#ffb347';
    ctx.fillRect(x+2, padding + (h - barH), barW-4, barH);
  }

  // draw mean line
  const mean = values.reduce((a,b)=>a+b,0)/values.length;
  const meanX = padding + ((mean - min) / range) * w;
  ctx.strokeStyle = '#ff3b30';
  ctx.beginPath();
  ctx.moveTo(meanX, padding);
  ctx.lineTo(meanX, padding + h);
  ctx.stroke();

  // labels
  ctx.fillStyle = '#344054';
  ctx.font='12px Arial';
  ctx.fillText(min.toFixed(2), padding, padding + h + 14);
  ctx.fillText(max.toFixed(2), padding + w - 30, padding + h + 14);
  ctx.fillText('Mean', meanX + 4, padding + 12);
}

function drawPCAPlaceholder(){
  const cvs = el('pca');
  const ctx = cvs.getContext('2d');
  ctx.clearRect(0,0,cvs.width,cvs.height);
  ctx.fillStyle='#f8fafc';
  ctx.fillRect(0,0,cvs.width,cvs.height);
  ctx.fillStyle='#111827';
  ctx.font='13px Arial';
  ctx.fillText('PCA scatter (placeholder)', 10, 20);

  // simple scatter using anomaly flag
  if(currentRows.length===0) return;
  const sample = currentRows.slice(0,200);
  for(let i=0;i<sample.length;i++){
    const r = sample[i];
    // fake projection using anomaly_score and fraud_probability
    const x = (Number(r.anomaly_score||0) % 1 + 1) % 1;
    const y = Number(r.fraud_probability||0);
    const px = 20 + x * (cvs.width - 40);
    const py = 30 + (1 - y) * (cvs.height - 50);
    ctx.beginPath();
    ctx.arc(px, py, 3, 0, 2*Math.PI);
    ctx.fillStyle = r.is_outlier===1 ? '#ff0000' : '#2563eb';
    ctx.fill();
  }
}

// ---------- Event wiring ----------
el('csv-file').addEventListener('change', async (ev)=>{
  const f = ev.target.files[0];
  if(!f) return;
  el('upload-info').innerText = `Loading ${f.name}...`;
  const txt = await f.text();
  const parsed = parseCSV(txt);
  currentFields = parsed.fields;
  currentRows = compute_scores(parsed.rows);
  el('upload-info').innerText = `Loaded ${currentRows.length} rows from ${f.name}.`;
  renderMetrics();
  renderTable();
  drawHistogram();
  drawPCAPlaceholder();
});

el('filter-select').addEventListener('change', ()=>{
  renderTable();
});

el('refresh-btn').addEventListener('click', ()=>{
  if(currentRows.length===0) return;
  currentRows = compute_scores(currentRows); // recompute
  renderMetrics(); renderTable(); drawHistogram(); drawPCAPlaceholder();
});

// ---------- Simulator ----------
function simulateSession(spec){
  // reuse simple scoring rule similar to compute_scores
  const impressions = Number(spec.impressions || 0);
  const clicks = Number(spec.clicks || 0);
  const rate = impressions>0 ? clicks/impressions : 0;
  const interclick = Number(spec.interclick_mean || 3);
  let score = (1 - rate) * 0.6 + Math.tanh(interclick/10) * 0.4;
  score = (score - 0.5) * 2;
  const fraudProb = 1 - clamp01((score + 1) / 2); // map score (-1..1) -> 0..1
  const isOut = fraudProb > 0.6;
  return {score: Number(score.toFixed(3)), fraud_probability: Number(fraudProb.toFixed(3)), is_outlier: isOut};
}

el('simulate-human').addEventListener('click', ()=>{
  const human = {
    impressions:5, clicks:1, interclick_mean:45
  };
  const res = simulateSession(human);
  el('human-output').innerHTML = `<strong>${res.is_outlier ? 'Suspicious' : 'Normal'}</strong> — score ${res.score} — fraud_prob ${res.fraud_probability}`;
});
el('simulate-bot').addEventListener('click', ()=>{
  const bot = {impressions:50, clicks:45, interclick_mean:1};
  const res = simulateSession(bot);
  el('bot-output').innerHTML = `<strong>${res.is_outlier ? 'Suspicious' : 'Normal'}</strong> — score ${res.score} — fraud_prob ${res.fraud_probability}`;
});

// initial render placeholders
renderMetrics();
drawHistogram();
drawPCAPlaceholder();
