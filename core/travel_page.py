"""
Generate a self-contained HTML travel-page / slideshow from a media folder.

JS libraries (Leaflet, Leaflet.heat, Chart.js) are downloaded once and cached
in AppData so the generated page works offline afterwards.
Media files are referenced by relative path — keep the HTML in the same folder.
"""

from __future__ import annotations

import json
import math
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from core.metadata import extract_metadata
from core.scanner import scan_folder
from utils.formats import VIDEO_EXTENSIONS


# ── JS / CSS library cache ─────────────────────────────────────────────────

_LIBS: dict[str, str] = {
    'leaflet_css':  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
    'leaflet_js':   'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
    'leaflet_heat': 'https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js',
    'chart_js':     'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js',
}


def _js_cache_dir() -> Path:
    appdata = os.environ.get('APPDATA', str(Path.home()))
    return Path(appdata) / 'Media File Renamer' / 'js_cache'


def _fetch_lib(name: str, url: str) -> str:
    path = _js_cache_dir() / f'{name}.txt'
    if path.exists():
        return path.read_text(encoding='utf-8')
    _js_cache_dir().mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=20) as resp:
        content = resp.read().decode('utf-8')
    path.write_text(content, encoding='utf-8')
    return content


def libs_cached() -> bool:
    return all((_js_cache_dir() / f'{k}.txt').exists() for k in _LIBS)


def fetch_all_libs(on_status: Callable[[str], None] = None) -> None:
    for name, url in _LIBS.items():
        if on_status:
            on_status(f"Downloading {name}…")
        _fetch_lib(name, url)


# ── Data model ─────────────────────────────────────────────────────────────

@dataclass
class _Entry:
    rel_path: str
    dt: Optional[datetime]
    device: str
    lat: Optional[float]
    lon: Optional[float]
    loc_label: str
    is_video: bool

    def as_dict(self) -> dict:
        return {
            'path':   self.rel_path,
            'date':   self.dt.strftime('%b %d %Y  ·  %H:%M') if self.dt else '',
            'ts':     int(self.dt.timestamp() * 1000) if self.dt else 0,
            'device': self.device,
            'lat':    self.lat,
            'lon':    self.lon,
            'loc':    self.loc_label,
            'video':  self.is_video,
        }


# ── Helpers ────────────────────────────────────────────────────────────────

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    p = math.pi / 180
    a = (0.5
         - math.cos((lat2 - lat1) * p) / 2
         + math.cos(lat1 * p) * math.cos(lat2 * p)
         * (1 - math.cos((lon2 - lon1) * p)) / 2)
    return R * 2 * math.asin(math.sqrt(min(a, 1.0)))


# ── Scanning ────────────────────────────────────────────────────────────────

def _scan(folder: Path, on_progress: Callable = None, cancel_event=None) -> List[_Entry]:
    files = list(scan_folder(str(folder)))
    total = len(files)
    entries: List[_Entry] = []

    def _extract(path: Path) -> _Entry:
        dt, device, gps = extract_metadata(path)
        return _Entry(
            rel_path=path.relative_to(folder).as_posix(),
            dt=dt,
            device=device if device != 'UNKNOWN' else '',
            lat=gps[0] if gps else None,
            lon=gps[1] if gps else None,
            loc_label='',
            is_video=path.suffix.lower() in VIDEO_EXTENSIONS,
        )

    done = 0
    max_workers = min(8, (os.cpu_count() or 2) * 2)
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        fmap = {ex.submit(_extract, p): p for p in files}
        for fut in as_completed(fmap):
            if cancel_event and cancel_event.is_set():
                ex.shutdown(wait=False, cancel_futures=True)
                raise InterruptedError("Cancelled")
            done += 1
            if on_progress:
                on_progress(done, total, fmap[fut].name)
            try:
                entries.append(fut.result())
            except Exception:
                pass

    # Dedup by path, then sort: dated first (by dt), undated after (by filename)
    seen: set[str] = set()
    unique: list[_Entry] = []
    for e in entries:
        if e.rel_path not in seen:
            seen.add(e.rel_path)
            unique.append(e)
    entries = unique
    entries.sort(key=lambda e: (e.dt is None, e.dt or datetime.min, e.rel_path))

    # Batch GPS → location label (one rg.search call)
    gps_idx = [(i, e) for i, e in enumerate(entries) if e.lat is not None]
    if gps_idx:
        try:
            import reverse_geocoder as rg
            results = rg.search([(e.lat, e.lon) for _, e in gps_idx], verbose=False)
            for (i, e), res in zip(gps_idx, results):
                city = res.get('name', '').strip()
                cc   = res.get('cc', '').strip()
                entries[i].loc_label = f"{city}, {cc}" if city else cc
        except Exception:
            for _, e in gps_idx:
                e.loc_label = f"{e.lat:.4f}°, {e.lon:.4f}°"

    return entries


# ── Stats ───────────────────────────────────────────────────────────────────

def _calc_stats(entries: List[_Entry], folder_name: str) -> dict:
    dated = [e for e in entries if e.dt]
    gps_e = [e for e in entries if e.lat is not None]

    first_dt = min(e.dt for e in dated) if dated else None
    last_dt  = max(e.dt for e in dated) if dated else None
    duration = (last_dt - first_dt).days + 1 if first_dt and last_dt else 0

    dist_km = 0.0
    prev = None
    for e in entries:
        if e.lat is not None:
            if prev:
                dist_km += _haversine(prev[0], prev[1], e.lat, e.lon)
            prev = (e.lat, e.lon)

    timestamps = [int(e.dt.timestamp() * 1000) for e in dated]

    seen_locs: list[str] = []
    for e in gps_e:
        if e.loc_label and e.loc_label not in seen_locs:
            seen_locs.append(e.loc_label)

    return {
        'title':       folder_name,
        'first_date':  first_dt.strftime('%b %d %Y') if first_dt else '–',
        'last_date':   last_dt.strftime('%b %d %Y')  if last_dt  else '–',
        'duration':    duration,
        'total':       len(entries),
        'photos':      sum(1 for e in entries if not e.is_video),
        'videos':      sum(1 for e in entries if e.is_video),
        'gps_count':   len(gps_e),
        'devices':     sorted({e.device for e in entries if e.device}),
        'locations':   seen_locs[:12],
        'distance_km': round(dist_km),
        'timestamps':  timestamps,
    }


# ── HTML template ───────────────────────────────────────────────────────────

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TMPL_TITLE</title>
<style>TMPL_LEAFLET_CSS</style>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0d1117;--surf:#161b22;--border:#30363d;--text:#c9d1d9;--muted:#8b949e;--accent:#f0883e;--cur:#ff7b72;--font:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
html,body{height:100%;background:var(--bg);color:var(--text);font-family:var(--font);overflow:hidden}
#app{display:grid;grid-template-rows:56px 1fr 90px 50px;height:100vh}
#header{display:flex;align-items:center;gap:20px;padding:0 20px;background:var(--surf);border-bottom:1px solid var(--border);overflow:hidden}
#trip-title{font-size:1.05rem;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex-shrink:0}
#stats-pills{display:flex;gap:6px;overflow:hidden;flex-wrap:nowrap}
.pill{background:var(--bg);border:1px solid var(--border);border-radius:20px;padding:3px 10px;font-size:.72rem;color:var(--muted);white-space:nowrap}
#main{display:grid;grid-template-columns:3fr 2fr;overflow:hidden}
#media-panel{display:flex;flex-direction:column;border-right:1px solid var(--border);overflow:hidden}
#media-display{flex:1;background:#000;display:flex;align-items:center;justify-content:center;overflow:hidden}
#media-display img{max-width:100%;max-height:100%;object-fit:contain}
#media-display video{width:100%;height:100%;object-fit:contain}
#media-info{padding:8px 16px;background:var(--surf);border-top:1px solid var(--border);display:flex;gap:12px;align-items:center;flex-shrink:0;min-height:40px;overflow:hidden}
.i-date{font-size:.85rem;font-weight:500;white-space:nowrap}
.i-device{font-size:.75rem;color:var(--accent);background:rgba(240,136,62,.12);padding:2px 8px;border-radius:4px;white-space:nowrap}
.i-loc{font-size:.78rem;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#side-panel{display:flex;flex-direction:column;overflow:hidden}
#map{flex:1}
#loc-bar{padding:6px 12px;background:var(--surf);border-top:1px solid var(--border);font-size:.78rem;color:var(--muted);display:flex;align-items:center;gap:6px;flex-shrink:0;min-height:40px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--cur);flex-shrink:0}
#timeline-panel{background:var(--surf);border-top:1px solid var(--border);padding:5px 16px 3px;overflow:hidden}
#tl-chart{width:100%!important;height:82px!important}
#controls{display:flex;align-items:center;justify-content:center;gap:10px;background:var(--surf);border-top:1px solid var(--border);padding:0 16px}
.cb{background:none;border:1px solid var(--border);color:var(--text);border-radius:6px;padding:5px 11px;cursor:pointer;font-size:.95rem;transition:background .12s}
.cb:hover{background:var(--border)}
#btn-play{background:var(--accent);border-color:var(--accent);color:#000;font-size:1.05rem}
#btn-play:hover{opacity:.85}
#counter{font-size:.82rem;color:var(--muted);min-width:72px;text-align:center}
#speed{background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:6px;padding:4px 6px;font-size:.78rem;cursor:pointer}
</style>
</head>
<body>
<div id="app">
  <div id="header">
    <div id="trip-title">TMPL_TITLE</div>
    <div id="stats-pills"></div>
  </div>
  <div id="main">
    <div id="media-panel">
      <div id="media-display">
        <img id="m-img" alt=""/>
        <video id="m-vid" controls style="display:none"></video>
      </div>
      <div id="media-info">
        <span class="i-date" id="i-date"></span>
        <span class="i-device" id="i-device"></span>
        <span class="i-loc" id="i-loc"></span>
      </div>
    </div>
    <div id="side-panel">
      <div id="map"></div>
      <div id="loc-bar"><span class="dot"></span><span id="loc-text">No location</span></div>
    </div>
  </div>
  <div id="timeline-panel"><canvas id="tl-chart"></canvas></div>
  <div id="controls">
    <button class="cb" id="btn-first" title="First">&#x23EE;</button>
    <button class="cb" id="btn-prev"  title="Prev (&#x2190;)">&#x25C0;</button>
    <button class="cb" id="btn-play"  title="Play/Pause (Space)">&#x25B6;</button>
    <button class="cb" id="btn-next"  title="Next (&#x2192;)">&#x25B7;</button>
    <button class="cb" id="btn-last"  title="Last">&#x23ED;</button>
    <span id="counter">– / –</span>
    <select id="speed" title="Slide delay">
      <option value="1000">1 s</option>
      <option value="2000" selected>2 s</option>
      <option value="3000">3 s</option>
      <option value="5000">5 s</option>
      <option value="8000">8 s</option>
    </select>
    <select id="bin-size" title="Timeline bin size">
      <option value="1">1 h</option>
      <option value="3" selected>3 h</option>
      <option value="6">6 h</option>
      <option value="24">Day</option>
    </select>
  </div>
</div>
<script>TMPL_LEAFLET_JS</script>
<script>TMPL_LEAFLET_HEAT</script>
<script>TMPL_CHART_JS</script>
<script>
const PHOTOS=TMPL_PHOTOS_JSON;
const STATS=TMPL_STATS_JSON;

// ── Map ────────────────────────────────────────────────────────────────────
const map=L.map('map',{zoomControl:true});
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{
  attribution:'&copy; <a href="https://openstreetmap.org">OSM</a> &copy; <a href="https://carto.com">CARTO</a>',
  maxZoom:19
}).addTo(map);
let heatLayer=null,curPin=null;

function updateMap(i){
  const p=PHOTOS[i];
  const pts=[];
  for(let j=0;j<=i;j++) if(PHOTOS[j].lat!==null) pts.push([PHOTOS[j].lat,PHOTOS[j].lon,1]);
  if(heatLayer){map.removeLayer(heatLayer);heatLayer=null;}
  if(pts.length) heatLayer=L.heatLayer(pts,{radius:22,blur:18,maxZoom:12,
    gradient:{0.3:'#3b82f6',0.65:'#f59e0b',1.0:'#ef4444'}}).addTo(map);
  if(curPin){map.removeLayer(curPin);curPin=null;}
  if(p.lat!==null){
    curPin=L.circleMarker([p.lat,p.lon],{color:'#ff7b72',fillColor:'#ff7b72',
      fillOpacity:1,radius:9,weight:2})
      .bindPopup('<b>'+p.date+'</b><br>'+(p.loc||'')).addTo(map);
    map.setView([p.lat,p.lon],Math.max(map.getZoom(),9),{animate:true});
    document.getElementById('loc-text').textContent=p.loc||(p.lat.toFixed(4)+'°, '+p.lon.toFixed(4)+'°');
  } else {
    document.getElementById('loc-text').textContent='No GPS data';
  }
}

// ── Timeline ───────────────────────────────────────────────────────────────
// Dynamic binning — recomputed when bin-size selector changes.
// Each bin key is the bin-start unix-ms; label is human-readable.
let tlBins=[], tlLabels=[], tlCounts=[], tlChart=null;

function buildBins(binHours){
  const ms=binHours*3600000;
  const map={};
  STATS.timestamps.forEach(ts=>{
    const k=Math.floor(ts/ms)*ms;
    map[k]=(map[k]||0)+1;
  });
  tlBins=Object.keys(map).map(Number).sort((a,b)=>a-b);
  tlCounts=tlBins.map(k=>map[k]);
  tlLabels=tlBins.map(k=>{
    const d=new Date(k);
    const mo=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][d.getMonth()];
    if(binHours>=24) return mo+' '+d.getDate();
    return mo+' '+d.getDate()+' '+String(d.getHours()).padStart(2,'0')+'h';
  });
}

function makeTlChart(){
  if(tlChart) tlChart.destroy();
  tlChart=new Chart(document.getElementById('tl-chart').getContext('2d'),{
    type:'bar',
    data:{labels:tlLabels,datasets:[{data:tlCounts,
      backgroundColor:tlBins.map(()=>'rgba(240,136,62,0.5)'),
      borderColor:tlBins.map(()=>'rgba(240,136,62,0.85)'),
      borderWidth:1,borderRadius:2}]},
    options:{responsive:true,maintainAspectRatio:false,animation:false,
      plugins:{legend:{display:false},tooltip:{callbacks:{
        title:i=>tlLabels[i[0].dataIndex],label:i=>i.raw+' file(s)'}}},
      scales:{
        x:{ticks:{color:'#8b949e',maxTicksLimit:16,maxRotation:0,font:{size:10}},
           grid:{color:'rgba(255,255,255,0.04)'}},
        y:{ticks:{color:'#8b949e',font:{size:10}},
           grid:{color:'rgba(255,255,255,0.04)'}}},
      onClick:(_e,els)=>{
        if(!els.length) return;
        const binStart=tlBins[els[0].dataIndex];
        const binEnd=binStart+parseInt(document.getElementById('bin-size').value,10)*3600000;
        const i=PHOTOS.findIndex(p=>p.ts>=binStart&&p.ts<binEnd);
        if(i>=0) show(i);
      }}
  });
}

function updateTimeline(i){
  if(!tlChart) return;
  const ts=PHOTOS[i]&&PHOTOS[i].ts;
  const binMs=parseInt(document.getElementById('bin-size').value,10)*3600000;
  const binKey=ts?Math.floor(ts/binMs)*binMs:null;
  const di=binKey!==null?tlBins.indexOf(binKey):-1;
  tlChart.data.datasets[0].backgroundColor=tlBins.map((_,j)=>
    j===di?'rgba(255,123,114,0.95)':j<di?'rgba(240,136,62,0.65)':'rgba(240,136,62,0.22)');
  tlChart.data.datasets[0].borderColor=tlBins.map((_,j)=>
    j===di?'#ff7b72':'rgba(240,136,62,0.8)');
  tlChart.update('none');
}

document.getElementById('bin-size').onchange=function(){
  buildBins(parseInt(this.value,10));makeTlChart();updateTimeline(idx);
};

// ── Slideshow ──────────────────────────────────────────────────────────────
let idx=0, slideTimer=null, isPlaying=false, showGen=0;

function show(i){
  if(!PHOTOS.length) return;
  i=Math.max(0,Math.min(PHOTOS.length-1,i));
  idx=i;
  const gen=++showGen; // every show() gets a unique stamp
  const p=PHOTOS[i];
  const img=document.getElementById('m-img');
  const vid=document.getElementById('m-vid');

  // Cancel any pending advance from the previous photo
  clearTimeout(slideTimer); slideTimer=null;
  vid.pause(); vid.onended=null;

  if(p.video){
    img.style.display='none'; vid.style.display='block';
    vid.src=p.path; vid.load();
    vid.play().catch(()=>{});
    // Only advance if this is still the active show() call
    vid.onended=()=>{ if(isPlaying && gen===showGen) scheduleAdvance(gen); };
  } else {
    vid.style.display='none'; img.style.display='block';
    img.src=p.path;
    if(isPlaying){
      const ms=parseInt(document.getElementById('speed').value,10);
      slideTimer=setTimeout(()=>{ if(gen===showGen) scheduleAdvance(gen); }, ms);
    }
  }

  document.getElementById('i-date').textContent=p.date;
  document.getElementById('i-device').textContent=p.device;
  document.getElementById('i-loc').textContent=p.loc||'';
  document.getElementById('counter').textContent=(i+1)+' / '+PHOTOS.length;
  updateMap(i);
  updateTimeline(i);
}

function scheduleAdvance(gen){
  if(gen!==showGen) return; // stale — another show() happened in between
  if(idx+1>=PHOTOS.length){ stopPlay(); return; }
  show(idx+1);
}

function startPlay(){
  if(isPlaying) return;
  isPlaying=true;
  document.getElementById('btn-play').innerHTML='&#x23F8;';
  const p=PHOTOS[idx];
  if(p&&!p.video){
    const ms=parseInt(document.getElementById('speed').value,10);
    const gen=showGen;
    slideTimer=setTimeout(()=>{ if(gen===showGen) scheduleAdvance(gen); }, ms);
  }
  // If current item is a video, onended is already wired up by show()
}
function stopPlay(){
  isPlaying=false;
  clearTimeout(slideTimer); slideTimer=null;
  const vid=document.getElementById('m-vid');
  vid.pause(); vid.onended=null;
  document.getElementById('btn-play').innerHTML='&#x25B6;';
}
function togglePlay(){ isPlaying?stopPlay():startPlay(); }

document.getElementById('btn-first').onclick=()=>{stopPlay();show(0);};
document.getElementById('btn-prev') .onclick=()=>{stopPlay();show(idx-1);};
document.getElementById('btn-play') .onclick=togglePlay;
document.getElementById('btn-next') .onclick=()=>{stopPlay();show(idx+1);};
document.getElementById('btn-last') .onclick=()=>{stopPlay();show(PHOTOS.length-1);};
document.getElementById('speed').onchange=()=>{if(isPlaying){stopPlay();startPlay();}};
document.addEventListener('keydown',e=>{
  if(e.key==='ArrowLeft'){stopPlay();show(idx-1);}
  if(e.key==='ArrowRight'){stopPlay();show(idx+1);}
  if(e.key===' '){e.preventDefault();togglePlay();}
});

// ── Stats pills ────────────────────────────────────────────────────────────
(function(){
  const pills=[
    ['&#x1F4C5;',STATS.first_date+' \u2013 '+STATS.last_date],
    ['&#x1F5D3;',STATS.duration+' day'+(STATS.duration!==1?'s':'')],
    ['&#x1F4F7;',STATS.photos+' photo'+(STATS.photos!==1?'s':'')],
    ['&#x1F3AC;',STATS.videos+' video'+(STATS.videos!==1?'s':'')],
    ['&#x1F4CD;',STATS.gps_count+' with GPS'],
  ];
  if(STATS.distance_km>0) pills.push(['&#x1F5FA;','~'+STATS.distance_km+' km']);
  if(STATS.devices.length) pills.push(['&#x1F4F1;',STATS.devices.join(' \u00B7 ')]);
  const c=document.getElementById('stats-pills');
  pills.forEach(function(pair){
    var el=document.createElement('div');el.className='pill';
    el.innerHTML=pair[0]+' '+pair[1];c.appendChild(el);
  });
})();

// ── Init ───────────────────────────────────────────────────────────────────
buildBins(3); makeTlChart();
if(PHOTOS.length){
  var gpts=PHOTOS.filter(function(p){return p.lat!==null;}).map(function(p){return[p.lat,p.lon];});
  if(gpts.length) map.fitBounds(gpts,{padding:[30,30]});
  else map.setView([20,0],2);
  show(0);
} else {
  map.setView([20,0],2);
  document.getElementById('counter').textContent='No media found';
}
</script>
</body>
</html>"""


def _build_html(entries: List[_Entry], stats: dict) -> str:
    libs = {k: _fetch_lib(k, url) for k, url in _LIBS.items()}
    return (
        _HTML
        .replace('TMPL_TITLE',        stats['title'])
        .replace('TMPL_LEAFLET_CSS',  libs['leaflet_css'])
        .replace('TMPL_LEAFLET_JS',   libs['leaflet_js'])
        .replace('TMPL_LEAFLET_HEAT', libs['leaflet_heat'])
        .replace('TMPL_CHART_JS',     libs['chart_js'])
        .replace('TMPL_PHOTOS_JSON',  json.dumps([e.as_dict() for e in entries], ensure_ascii=False))
        .replace('TMPL_STATS_JSON',   json.dumps(stats, ensure_ascii=False))
    )


# ── Public entry point ─────────────────────────────────────────────────────

def generate_travel_page(
    folder: str,
    on_progress: Callable[[int, int, str], None] = None,
    on_status: Callable[[str], None] = None,
    cancel_event=None,
) -> Path:
    """Scan folder, build HTML, write travel_page.html. Returns output path."""
    root = Path(folder)

    if on_status:
        on_status("Fetching map libraries…")
    fetch_all_libs(on_status)

    if cancel_event and cancel_event.is_set():
        raise InterruptedError("Cancelled")

    if on_status:
        on_status("Scanning and reading metadata…")
    entries = _scan(root, on_progress=on_progress, cancel_event=cancel_event)

    if on_status:
        on_status("Building page…")
    stats = _calc_stats(entries, root.name)
    html  = _build_html(entries, stats)

    out = root / 'travel_page.html'
    out.write_text(html, encoding='utf-8')
    return out
