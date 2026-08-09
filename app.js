const COLORS = ['#0b6b3a','#d5a737','#315c91','#d4473f','#8067a8','#4b8f8c','#9b6b43','#73824c','#d17a9b','#65717a'];
const partyColors = new Map();
let dashboard, candidateData, selectedCandidateKey;

const baseLayout = {
  paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
  font: {family: 'DM Sans, sans-serif', color: '#35453c', size: 12},
  margin: {t: 30, r: 28, b: 52, l: 58},
  hoverlabel: {bgcolor: '#15251d', bordercolor: '#15251d', font: {color: '#fff'}},
  xaxis: {gridcolor: '#e6e5dc', zerolinecolor: '#d6d7cd'},
  yaxis: {gridcolor: '#e6e5dc', zerolinecolor: '#d6d7cd'},
  legend: {orientation: 'h', y: 1.12, x: 0}
};
const plotConfig = {responsive: true, displayModeBar: false};

function colorForParty(party) {
  if (!partyColors.has(party)) partyColors.set(party, COLORS[partyColors.size % COLORS.length]);
  return partyColors.get(party);
}
function fmt(value, digits=0) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return Number(value).toLocaleString('en-GB', {minimumFractionDigits: digits, maximumFractionDigits: digits});
}
function esc(value) {
  return String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;');
}
function mean(values) {
  const clean = values.filter(value => value !== null && value !== undefined && !Number.isNaN(Number(value)));
  return clean.length ? clean.reduce((sum, value) => sum + Number(value), 0) / clean.length : null;
}
function kpi(label, value, note='') { return `<div class="kpi"><span>${esc(label)}</span><strong>${esc(value)}</strong>${note ? `<small>${esc(note)}</small>` : ''}</div>`; }

async function loadData() {
  const [dashboardResponse, candidateResponse] = await Promise.all([fetch('data/dashboard.json'), fetch('data/candidates.json')]);
  if (!dashboardResponse.ok || !candidateResponse.ok) throw new Error('Data files could not be loaded.');
  dashboard = await dashboardResponse.json();
  candidateData = await candidateResponse.json();
  dashboard.party_order.forEach(colorForParty);
  initialise();
}

function initialise() {
  const meta = dashboard.meta;
  document.getElementById('statElections').textContent = meta.years.length;
  document.getElementById('statCandidates').textContent = fmt(meta.candidate_profiles);
  document.getElementById('statRecords').textContent = fmt(meta.candidate_records);

  const yearSelect = document.getElementById('overviewYear');
  yearSelect.innerHTML = meta.years.map(year => `<option>${year}</option>`).join('');
  yearSelect.value = meta.years.at(-1);

  const constituencySelect = document.getElementById('constituencySelect');
  constituencySelect.innerHTML = Object.keys(dashboard.constituencies).map(Number).sort((a,b)=>a-b).map(number => `<option value="${number}">NA-${number}</option>`).join('');

  const parties = dashboard.party_order.filter(Boolean);
  const partySelect = document.getElementById('partySelect');
  partySelect.innerHTML = parties.map(party => `<option>${esc(party)}</option>`).join('');
  partySelect.value = parties.includes('PTI') ? 'PTI' : parties[0];

  const list = document.getElementById('candidateList');
  list.innerHTML = candidateData.index.map(item => `<option value="${esc(item.name)}"></option>`).join('');

  document.querySelectorAll('.tab').forEach(button => button.addEventListener('click', () => openView(button.dataset.view)));
  yearSelect.addEventListener('change', drawOverview);
  document.getElementById('overviewMetric').addEventListener('change', drawOverview);
  constituencySelect.addEventListener('change', drawConstituency);
  partySelect.addEventListener('change', drawParty);
  document.getElementById('candidateSearch').addEventListener('change', selectCandidateFromInput);
  document.getElementById('candidateSearch').addEventListener('input', event => {
    if (!event.target.value) return;
    const exact = candidateData.index.find(item => item.name.toLowerCase() === event.target.value.toLowerCase());
    if (exact) selectCandidate(exact.key);
  });

  constituencySelect.value = '1';
  const defaultCandidate = Object.values(candidateData.profiles)
    .filter(profile => profile.loyal && !profile.ambiguous_name && profile.contests > 0)
    .sort((a, b) => {
      const electionsA = new Set(a.timeline.filter(row => row.source_type === 'contest').map(row => row.year)).size;
      const electionsB = new Set(b.timeline.filter(row => row.source_type === 'contest').map(row => row.year)).size;
      return electionsB - electionsA || b.contests - a.contests || b.wins - a.wins || a.name.localeCompare(b.name);
    })[0];
  selectedCandidateKey = defaultCandidate?.key || candidateData.index[0]?.key;
  drawOverview(); drawConstituency(); drawParty(); fillSwitchLeaders();
  if (selectedCandidateKey) selectCandidate(selectedCandidateKey);
  document.getElementById('loading').remove();
}

function openView(name) {
  document.querySelectorAll('.tab').forEach(tab => {
    const active = tab.dataset.view === name;
    tab.classList.toggle('active', active); tab.setAttribute('aria-selected', active);
  });
  document.querySelectorAll('.view').forEach(view => {
    const active = view.id === `view-${name}`;
    view.hidden = !active; view.classList.toggle('active', active);
  });
  setTimeout(() => document.querySelectorAll(`#view-${name} .js-plotly-plot`).forEach(chart => Plotly.Plots.resize(chart)), 0);
}

const metricInfo = {
  turnout: 'Votes polled',
  registered_electors: 'Registered electors',
  rejected_ballots: 'Rejected ballots'
};
function drawOverview() {
  const year = Number(document.getElementById('overviewYear').value);
  const metric = document.getElementById('overviewMetric').value;
  const label = metricInfo[metric];
  const rows = dashboard.overview.filter(row => row.year === year);
  const plotRows = rows.filter(row => row[metric] !== null && row[metric] !== undefined && Number.isFinite(Number(row.constituency_no)) && Number.isFinite(Number(row[metric])));
  document.getElementById('scatterTag').textContent = `${year} · ${label}`;
  document.getElementById('overviewKpis').innerHTML = [
    kpi('Average turnout', `${fmt(mean(rows.map(row => row.turnout_pct)),1)}%`, `${rows.length} constituencies`),
    kpi('Registered electors', fmt(rows.reduce((sum,row)=>sum+(row.registered_electors||0),0)), 'Available constituency totals'),
    kpi('Average winning margin', `${fmt(mean(rows.map(row => row.margin_pct_points)),1)} pp`, 'Winner vs runner-up'),
    kpi('Candidates recorded', fmt(dashboard.party_year.filter(row=>row.year===year).reduce((sum,row)=>sum+row.contests,0)), 'Individual candidacies')
  ].join('');
  Plotly.react('overviewScatter', [{
    x: plotRows.map(row=>Number(row.constituency_no)), y: plotRows.map(row=>Number(row[metric])), type:'scatter', mode:'markers',
    marker:{size:10, color:plotRows.map(row=>colorForParty(row.winner_party_group)), opacity:.84, line:{color:'#fffdf6',width:1}},
    customdata: plotRows.map(row=>[row.constituency_label,row.winner_candidate,row.winner_party_group,row.runner_up_candidate]),
    hovertemplate:`<b>%{customdata[0]}</b><br>${label}: %{y:,.0f}<br>Winner: %{customdata[1]} (%{customdata[2]})<br>Runner-up: %{customdata[3]}<extra></extra>`
  }], {...baseLayout, datarevision:`overview-${year}-${metric}`, xaxis:{...baseLayout.xaxis,type:'linear',autorange:true,title:'Current constituency number',dtick:10}, yaxis:{...baseLayout.yaxis,type:'linear',autorange:true,tickformat:',.0f',title:`${label} (count)`}}, plotConfig);

  const seatRows = dashboard.seat_counts.filter(row=>row.year===year).sort((a,b)=>b.seats-a.seats || a.party.localeCompare(b.party));
  document.getElementById('seatChartYear').textContent = year;
  Plotly.react('seatCounts',[{
    x:seatRows.map(row=>row.seats),y:seatRows.map(row=>row.party),type:'bar',orientation:'h',showlegend:false,
    marker:{color:seatRows.map(row=>colorForParty(row.party))},text:seatRows.map(row=>fmt(row.seats)),textposition:'outside',cliponaxis:false,
    customdata:seatRows.map(row=>[row.rank,row.result_stage,row.classification_note]),
    hovertemplate:`<b>%{y}</b><br>%{x} general seats<br>Rank %{customdata[0]}<br>%{customdata[1]}<br>%{customdata[2]}<extra></extra>`
  }],{...baseLayout,margin:{t:18,r:42,b:54,l:145},xaxis:{...baseLayout.xaxis,type:'linear',rangemode:'tozero',title:'Declared general seats'},yaxis:{...baseLayout.yaxis,type:'category',autorange:'reversed'},showlegend:false},plotConfig);

  const margins = [...rows].filter(row=>row.margin_pct_points!==null).sort((a,b)=>b.margin_pct_points-a.margin_pct_points).slice(0,12).reverse();
  Plotly.react('topMargins', [{x:margins.map(row=>row.margin_pct_points),y:margins.map(row=>row.constituency_label),type:'bar',orientation:'h',marker:{color:margins.map(row=>colorForParty(row.winner_party_group))},customdata:margins.map(row=>[row.winner_candidate,row.winner_party_group]),hovertemplate:'%{y}<br>%{x:.2f} pp<br>%{customdata[0]} (%{customdata[1]})<extra></extra>'}], {...baseLayout,margin:{t:20,r:20,b:48,l:115},xaxis:{...baseLayout.xaxis,title:'Margin (percentage points)'},yaxis:{...baseLayout.yaxis}}, plotConfig);
}

function drawConstituency() {
  const number = document.getElementById('constituencySelect').value;
  const data = dashboard.constituencies[number];
  document.getElementById('constituencyPeriods').innerHTML = data.periods.map(item=>`<span class="period-pill">${esc(item.period)} · ${esc(item.label)}</span>`).join('') || '<span class="period-pill">No historical mapping recorded</span>';
  Plotly.react('constituencyWinners', [{
    x:data.elections.map(row=>row.year), y:data.elections.map(row=>row.winner_party_group), type:'scatter',mode:'lines+markers+text',
    line:{color:'#9ca89f',width:2},marker:{size:data.elections.map(row=>Math.max(14,(row.winner_vote_pct||20)/2.6)),color:data.elections.map(row=>colorForParty(row.winner_party_group)),line:{color:'#fff',width:2}},
    text:data.elections.map(row=>row.winner_candidate),textposition:'top center',textfont:{size:10},customdata:data.elections.map(row=>[row.constituency_label,row.winner_vote_pct,row.margin_pct_points]),
    hovertemplate:'<b>%{x} · %{customdata[0]}</b><br>%{text}<br>%{y}<br>Vote share: %{customdata[1]:.2f}%<br>Margin: %{customdata[2]:.2f} pp<extra></extra>'
  }], {...baseLayout,margin:{t:50,r:35,b:50,l:85},xaxis:{...baseLayout.xaxis,tickmode:'array',tickvals:dashboard.meta.years},yaxis:{...baseLayout.yaxis,title:'Winning party'}}, plotConfig);

  const grouped = new Map();
  data.party_history.forEach(row=>{
    const key=`${row.year}|${row.party_group}`;
    if(!grouped.has(key)||row.candidate_rank<grouped.get(key).candidate_rank) grouped.set(key,row);
  });
  const appearances = new Map();
  grouped.forEach(row=>appearances.set(row.party_group,(appearances.get(row.party_group)||0)+1));
  const selectedParties=[...appearances.entries()].sort((a,b)=>b[1]-a[1]).slice(0,10).map(([party])=>party);
  const traces=selectedParties.map(party=>{
    const partyRows=[...grouped.values()].filter(row=>row.party_group===party).sort((a,b)=>a.year-b.year);
    return {x:partyRows.map(row=>row.year),y:partyRows.map(row=>row.candidate_rank),type:'scatter',mode:'lines+markers',name:party,line:{color:colorForParty(party),width:2},marker:{size:9},customdata:partyRows.map(row=>[row.candidate_name,row.vote_pct,row.constituency_label]),hovertemplate:'%{x} · %{customdata[2]}<br>%{customdata[0]}<br>Rank %{y} · %{customdata[1]:.2f}%<extra></extra>'};
  });
  Plotly.react('constituencyPartyRanks',traces,{...baseLayout,xaxis:{...baseLayout.xaxis,tickmode:'array',tickvals:dashboard.meta.years},yaxis:{...baseLayout.yaxis,title:'Best party candidate rank',autorange:'reversed',dtick:1}},plotConfig);
  document.querySelector('#constituencyTable tbody').innerHTML=data.elections.map(row=>`<tr><td>${row.year}</td><td>${esc(row.constituency_label)}</td><td><span class="status win">${esc(row.winner_candidate)}</span></td><td>${esc(row.winner_party_group)}</td><td>${esc(row.runner_up_candidate)}</td><td>${fmt(row.turnout_pct,1)}%</td><td>${fmt(row.margin_pct_points,1)} pp</td></tr>`).join('');
}

function drawParty() {
  const party=document.getElementById('partySelect').value;
  const records=dashboard.party_year.filter(row=>row.party===party).sort((a,b)=>a.year-b.year);
  const latest=records.at(-1);
  document.getElementById('partyKpis').innerHTML=[
    kpi('Latest seats',fmt(latest?.seats||0),String(latest?.year||'')),kpi('Latest candidates',fmt(latest?.candidates||0),'Exact normalized names'),
    kpi('Average vote share',`${fmt(latest?.mean_vote_pct,1)}%`,'Across party candidates'),kpi('Total recorded votes',fmt(records.reduce((sum,row)=>sum+(row.votes||0),0)),'Across all five elections')
  ].join('');
  Plotly.react('partyTrend',[
    {x:records.map(row=>row.year),y:records.map(row=>row.seats),type:'bar',name:'Seats',marker:{color:colorForParty(party)},hovertemplate:'%{x}: %{y} seats<extra></extra>'},
    {x:records.map(row=>row.year),y:records.map(row=>row.mean_vote_pct),type:'scatter',mode:'lines+markers+text',name:'Average vote %',yaxis:'y2',line:{color:'#d4473f',width:3},marker:{size:9},text:records.map(row=>`${fmt(row.mean_vote_pct,1)}%`),textposition:'top center',hovertemplate:'%{x}: %{y:.2f}% average vote<extra></extra>'}
  ],{...baseLayout,xaxis:{...baseLayout.xaxis,tickmode:'array',tickvals:dashboard.meta.years},yaxis:{...baseLayout.yaxis,title:'Seats'},yaxis2:{title:'Average vote share (%)',overlaying:'y',side:'right',gridcolor:'rgba(0,0,0,0)'},legend:{orientation:'h',y:1.12,x:0}},plotConfig);
  const latestYear=dashboard.meta.years.at(-1);const candidates=[];
  Object.values(dashboard.constituencies).forEach(item=>item.party_history.filter(row=>row.year===latestYear&&row.party_group===party).forEach(row=>candidates.push(row)));
  const strongest=candidates.filter(row=>row.vote_pct!==null).sort((a,b)=>b.vote_pct-a.vote_pct).slice(0,18).reverse();
  Plotly.react('partyStrongholds',[{x:strongest.map(row=>row.vote_pct),y:strongest.map(row=>row.constituency_label),type:'bar',orientation:'h',marker:{color:colorForParty(party)},customdata:strongest.map(row=>[row.candidate_name,row.candidate_rank]),hovertemplate:'%{y}<br>%{customdata[0]} · rank %{customdata[1]}<br>%{x:.2f}%<extra></extra>'}],{...baseLayout,margin:{t:20,r:25,b:48,l:120},xaxis:{...baseLayout.xaxis,title:`Candidate vote share in ${latestYear} (%)`}},plotConfig);
}

function selectCandidateFromInput() {
  const value=document.getElementById('candidateSearch').value.trim().toLowerCase();
  const match=candidateData.index.find(item=>item.name.toLowerCase()===value)||candidateData.index.find(item=>item.name.toLowerCase().includes(value));
  if(match) selectCandidate(match.key);
}
function selectCandidate(key) {
  const profile=candidateData.profiles[key];if(!profile)return;selectedCandidateKey=key;
  const electionYears=[...new Set(profile.timeline.filter(row=>row.source_type==='contest').map(row=>row.year))].sort();
  document.getElementById('candidateSearch').value=profile.name;document.getElementById('candidateName').textContent=profile.name;
  document.getElementById('candidateSummary').textContent=`${profile.parties.join(' → ')} · ${profile.constituencies.length} historical constituency label${profile.constituencies.length===1?'':'s'}${profile.ambiguous_name?' · common-name profile separated by concurrent affiliation':''}`;
  const badge=document.getElementById('loyaltyBadge');badge.className=`loyalty-badge ${profile.loyal?'loyal':'switcher'}`;badge.textContent=profile.loyal?'● Consistent affiliation':`● ${profile.switches} recorded change${profile.switches===1?'':'s'}`;
  document.getElementById('candidateKpis').innerHTML=[kpi('Election years',fmt(electionYears.length),electionYears.join(', ')),kpi('Total contests',fmt(profile.contests),'Including multiple seats'),kpi('Wins',fmt(profile.wins),'Contest records'),kpi('Parties',fmt(profile.parties.length),profile.parties.join(', '))].join('');
  const timeline=profile.timeline;
  Plotly.react('candidateTimeline',[{
    x:timeline.map(row=>row.year),y:timeline.map(row=>row.party_std||row.party_group),type:'scatter',mode:'lines+markers+text',
    line:{color:'#aeb7b0',width:2,shape:'hv'},marker:{size:timeline.map(row=>row.is_winner?17:12),color:timeline.map(row=>row.party_switched?'#d4473f':'#16a064'),symbol:timeline.map(row=>row.is_winner?'diamond':'circle'),line:{color:'#fff',width:2}},
    text:timeline.map(row=>row.constituency_label),textposition:'top center',textfont:{size:10},customdata:timeline.map(row=>[row.votes,row.vote_pct,row.candidate_rank,row.source_type,row.party_switched]),
    hovertemplate:'<b>%{x} · %{text}</b><br>%{y}<br>Votes: %{customdata[0]:,}<br>Share: %{customdata[1]:.2f}%<br>Rank: %{customdata[2]}<br>Source: %{customdata[3]}<extra></extra>'
  }],{...baseLayout,margin:{t:50,r:35,b:55,l:105},xaxis:{...baseLayout.xaxis,title:'Election year',dtick:1},yaxis:{...baseLayout.yaxis,title:'Recorded affiliation'}},plotConfig);
  document.querySelector('#candidateTable tbody').innerHTML=timeline.map(row=>`<tr><td>${row.year}</td><td>${esc(row.constituency_label)}</td><td>${esc(row.party_std||row.party_group)}</td><td>${fmt(row.votes)}</td><td>${row.vote_pct===null?'—':`${fmt(row.vote_pct,1)}%`}</td><td class="status ${row.is_winner?'win':''}">${row.source_type==='member_history'?'Elected member':row.is_winner?'Winner':row.is_runner_up?'Runner-up':`Rank ${row.candidate_rank}`}</td><td class="status ${row.party_switched?'switch':''}">${row.party_switched?'Changed':'Unchanged / first'}</td></tr>`).join('');
}

function fillSwitchLeaders() {
  const tbody=document.querySelector('#switchLeaders tbody');
  tbody.innerHTML=dashboard.switch_leaders.slice(0,25).map(row=>`<tr data-key="${esc(row.key)}"><td><button class="candidate-link" type="button">${esc(row.name)}</button></td><td>${row.contests}</td><td>${esc(row.parties.join(', '))}</td><td><span class="status switch">${row.switches}</span></td><td>${esc(row.constituencies.slice(0,4).join(', '))}${row.constituencies.length>4?'…':''}</td></tr>`).join('');
  tbody.querySelectorAll('tr').forEach(row=>row.addEventListener('click',()=>{selectCandidate(row.dataset.key);window.scrollTo({top:document.getElementById('candidate-title').offsetTop-100,behavior:'smooth'});}));
}

loadData().catch(error=>{console.error(error);const loading=document.getElementById('loading');loading.classList.add('error');loading.textContent='Dashboard data failed to load.';});
