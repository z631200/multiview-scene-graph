"""Create a standalone interactive graph inspector; Python standard library only."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import webbrowser


RELATIONS = ("on", "inside", "image_left_of", "closer_to_camera")


def load_run(run_dir):
    """Load saved graphs and their measurements, validating references before display."""
    root = Path(run_dir).resolve()
    folder = root / "visible"
    if not folder.is_dir():
        raise ValueError(f"找不到正式圖目錄：{folder}。請指定 GT run 目錄。")
    graphs = []
    files = sorted(folder.glob("view_*.json"), key=lambda p: int(re.search(r"view_(\d+)", p.stem)[1])
                   if re.fullmatch(r"view_\d+", p.stem) else -1)
    for path in files:
        graph = json.loads(path.read_text(encoding="utf-8"))
        view = graph["view_id"]
        if not re.fullmatch(r"view_[1-9][0-9]*", view) or path.stem != view:
            raise ValueError(f"視角 ID 與檔名不一致：{path.name}")
        if graph.get("status") != "complete":
            raise ValueError(f"{view} 尚未定稿")
        nodes = {n["id"]: n for n in graph["nodes"]}
        if len(nodes) != len(graph["nodes"]):
            raise ValueError(f"{view} 有重複節點 ID")
        if len({e["id"] for e in graph["edges"]}) != len(graph["edges"]):
            raise ValueError(f"{view} 有重複邊 ID")
        for edge in graph["edges"]:
            if (edge["source"] not in nodes or edge["target"] not in nodes or
                    edge["source"] == edge["target"] or edge["relation"] not in RELATIONS):
                raise ValueError(f"{view} 的邊 {edge['id']} 有無效端點或關係")
        measurement = root / "measurements" / f"{view}.json"
        graph["measurements"] = json.loads(measurement.read_text(encoding="utf-8")) if measurement.is_file() else {}
        if graph["measurements"] and graph["measurements"].get("view_id") != view:
            raise ValueError(f"{view} 的測量檔視角不一致")
        graphs.append(graph)
    if not graphs:
        raise ValueError(f"{folder} 沒有 view_*.json")
    return {"run_dir": str(root), "graphs": graphs}


def render_html(data, *, view=None, types=(), relations=("on", "inside"), scope="between"):
    views = {g["view_id"] for g in data["graphs"]}
    view = view or data["graphs"][0]["view_id"]
    if view not in views:
        raise ValueError(f"沒有此視角：{view}，可選：{', '.join(sorted(views))}")
    available = {n["objectType"].lower(): n["objectType"] for g in data["graphs"] for n in g["nodes"]}
    unknown = [t for t in types if t.lower() not in available]
    if unknown:
        raise ValueError(f"找不到物件類型：{', '.join(unknown)}")
    if not set(relations) <= set(RELATIONS) or scope not in ("between", "connected"):
        raise ValueError("無效的關係或篩選範圍")
    payload = dict(data, initial={"view": view, "types": [available[t.lower()] for t in types],
                                "relations": list(relations), "scope": scope})
    # Prevent input text from terminating the embedded JSON script element.
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    return HTML.replace("__GRAPH_DATA__", encoded)


HTML = r'''<!doctype html>
<html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>場景圖檢查器</title>
<style>
*{box-sizing:border-box}[hidden]{display:none!important}body{margin:0;background:#f4f6f9;color:#182539;font:14px system-ui,sans-serif}
header{padding:20px 24px;background:#152b45;color:white}h1{font-size:22px;margin:0 0 8px}header p{margin:0;overflow-wrap:anywhere;color:#cbd9e8}
main{display:grid;grid-template-columns:260px minmax(0,1fr);gap:16px;padding:16px}aside,.card{background:white;border:1px solid #dbe1e9;border-radius:10px;padding:16px}
label.title{font-weight:700;display:block;margin:0 0 8px}.field{margin-bottom:22px}select,button,input{font:inherit}select,input[type=search]{width:100%;padding:8px;border:1px solid #b8c4d2;border-radius:5px}
button{background:#edf2f8;border:1px solid #b9c7d7;padding:6px 10px;border-radius:5px;cursor:pointer}button:hover{background:#dce8f5}button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #50a3ef}
.buttons{display:flex;gap:6px;margin:7px 0}.choice{display:flex;align-items:center;gap:6px;padding:4px 0;cursor:pointer}.choices{max-height:280px;overflow:auto}.help{color:#53677d;font-size:12px;line-height:1.6}.workspace{min-width:0;display:grid;gap:16px;align-content:start}
.toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}#summary{font-weight:600}#diagram{height:510px;background:#fafcfe;border:1px solid #e0e8f1;border-radius:7px;margin-top:12px;overflow:hidden;touch-action:none}
svg{width:100%;height:100%;user-select:none}svg text{font:12px system-ui;pointer-events:none}.node{cursor:pointer}.node circle{stroke:#2b4f78;stroke-width:2;fill:#e0ecf9}.node.context circle{fill:#f2f3f5;stroke:#8a98a8}.edge{cursor:pointer}.edge-hit{fill:none;stroke:transparent;stroke-width:15;pointer-events:stroke}.edge-line{fill:none;stroke-width:1.8;opacity:.7;pointer-events:none}.edge:hover .edge-line{stroke-width:4;opacity:1}
.legend{display:flex;gap:12px;flex-wrap:wrap;margin-top:8px}.legend span{font-size:12px}.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:4px}.table-wrap{max-height:370px;overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:8px;border-bottom:1px solid #e2e7ed;overflow-wrap:anywhere}th{position:sticky;top:0;background:#eff4fa}td small{color:#62758a}.detail{display:grid;grid-template-columns:1fr 1fr;gap:16px}pre{margin:8px 0 0;background:#f5f7fa;padding:12px;border-radius:5px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto;font-size:12px}h2{font-size:16px;margin:0 0 12px}#notice{color:#995513;min-height:20px}details{margin-top:12px}summary{cursor:pointer;font-weight:600}#status{color:#b12828;white-space:pre-wrap}#empty{margin:12px;color:#5d6e81}
@media(max-width:850px){main{grid-template-columns:1fr}aside{display:grid;grid-template-columns:1fr 1fr;gap:16px}.field{margin:0}.detail{grid-template-columns:1fr}#diagram{height:400px}}
</style>
<header><h1>場景圖檢查器</h1><p id="run"></p></header>
<main><aside>
<div class="field"><label class="title" for="view">視角</label><select id="view"></select><p id="view-info" class="help"></p></div>
<div class="field"><label class="title" for="type-search">物件類型（可多選）</label><input id="type-search" type="search" placeholder="搜尋，例如 Cup、Shelf">
<div class="buttons"><button id="all-types">全選</button><button id="clear-types">清除</button></div><div class="choices" id="types"></div><p class="help">同類型的不同實體各自保留 ID。灰色節點是連帶顯示的其他物件。</p></div>
<div class="field"><span class="title">顯示範圍</span><label class="choice"><input type="radio" name="scope" value="between" checked>只看所選物件之間</label><label class="choice"><input type="radio" name="scope" value="connected">包含與其他物件的關係</label></div>
<div class="field"><span class="title">關係（可多選）</span><div id="relations"></div></div>
</aside><section class="workspace">
<div class="card"><div class="toolbar"><span id="summary"></span><div><button id="zoom-in" aria-label="放大">＋</button> <button id="zoom-out" aria-label="縮小">－</button> <button id="reset">重設視野</button> <button id="export">匯出篩選 JSON</button></div></div>
<p class="help">箭頭由主體指向客體。拖曳背景平移，滾輪縮放；點箭頭或下方「證據」查看明細。物件位置為圖形排版，不代表照片或世界座標。</p>
<div id="notice"></div><div id="diagram"><svg id="svg" role="img" aria-label="篩選後的場景關係圖"></svg></div><div class="legend" id="legend"></div><p id="empty" hidden>沒有符合條件的關係。請檢查物件類型、關係與顯示範圍。</p><div id="status" role="alert"></div></div>
<div class="card"><h2>關係清單</h2><div class="table-wrap"><table><thead><tr><th>ID</th><th>主體</th><th>關係</th><th>客體</th><th>明細</th></tr></thead><tbody id="edges"></tbody></table></div></div>
<div class="detail"><div class="card"><h2>選取項目的證據</h2><pre id="evidence">點選箭頭、節點或清單中的「證據」。</pre></div><div class="card"><h2>篩選後的節點</h2><div class="table-wrap"><table><thead><tr><th>物件</th><th>objectId</th></tr></thead><tbody id="nodes"></tbody></table></div></div></div>
<div class="card"><h2>未建立邊的計算紀錄</h2><p class="help">同樣依物件類型與關係篩選。相等值不產生排序邊；不可見父物件的關係不在 Visible GT 中。</p><details><summary id="ties-title"></summary><pre id="ties"></pre></details><details><summary id="excluded-title"></summary><pre id="excluded"></pre></details></div>
</section></main>
<script type="application/json" id="data">__GRAPH_DATA__</script>
<script>
'use strict';
const DATA=JSON.parse(document.getElementById('data').textContent), $=id=>document.getElementById(id);
const COLORS={on:'#247356',inside:'#a35719',image_left_of:'#266bcc',closer_to_camera:'#8b4ca8'};
const PARENTS={CounterTop:'on',Floor:'on',Cabinet:'inside',Fridge:'inside',Drawer:'inside',Shelf:'inside'};
let graph, selectedTypes=new Set(DATA.initial.types), current, camera={x:0,y:0,w:1000,h:620};
const ns='http://www.w3.org/2000/svg', pretty=x=>JSON.stringify(x,null,2);
function el(tag,text){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;}
function svgEl(tag,attrs){const n=document.createElementNS(ns,tag);Object.entries(attrs||{}).forEach(([k,v])=>n.setAttribute(k,v));return n;}
function choices(container,values,selected,onchange){container.replaceChildren();values.forEach(value=>{const label=el('label');label.className='choice';const input=el('input');input.type='checkbox';input.value=value;input.checked=selected.has(value);input.addEventListener('change',()=>onchange(value,input.checked));label.append(input,document.createTextNode(value));container.append(label);});}
function relations(){return new Set([...$('relations').querySelectorAll('input:checked')].map(n=>n.value));}
function scope(){return document.querySelector('input[name=scope]:checked').value;}
function typeFor(id){return graph.nodes.find(n=>n.id===id)?.objectType||id.split('|')[0];}
function matches(a,b){const sa=selectedTypes.has(typeFor(a)),sb=selectedTypes.has(typeFor(b));return scope()==='between'?sa&&sb:sa||sb;}
function showTypes(){const types=[...new Set(graph.nodes.map(n=>n.objectType))].sort();choices($('types'),types,selectedTypes,(t,on)=>{on?selectedTypes.add(t):selectedTypes.delete(t);render();});filterTypes();}
function filterTypes(){const q=$('type-search').value.toLowerCase();[...$('types').children].forEach(n=>n.hidden=!n.textContent.toLowerCase().includes(q));}
function changeView(initial=false){graph=DATA.graphs.find(g=>g.view_id===$('view').value);if(!initial)selectedTypes=new Set([...selectedTypes].filter(t=>graph.nodes.some(n=>n.objectType===t)));showTypes();$('evidence').textContent='點選箭頭、節點或清單中的「證據」。';render();}
function nodeLabel(id){const n=graph.nodes.find(n=>n.id===id);const same=graph.nodes.filter(x=>x.objectType===n.objectType);return n.objectType+(same.length>1?' #'+(same.findIndex(x=>x.id===id)+1):'');}
function inspectEdge(edge){$('evidence').textContent=pretty({view_id:graph.view_id,...edge,source_measurement:graph.measurements?.objects?.[edge.source]||null,target_measurement:graph.measurements?.objects?.[edge.target]||null});}
function inspectNode(node){$('evidence').textContent=pretty({...node,measurement:graph.measurements?.objects?.[node.id]||null});}
function render(){
 const wanted=relations(), edges=graph.edges.filter(e=>wanted.has(e.relation)&&matches(e.source,e.target));
 const ids=new Set(graph.nodes.filter(n=>selectedTypes.has(n.objectType)).map(n=>n.id));edges.forEach(e=>{ids.add(e.source);ids.add(e.target);});
 const nodes=graph.nodes.filter(n=>ids.has(n.id));current={view_id:graph.view_id,scope:scope(),selected_types:[...selectedTypes],relations:[...wanted],nodes,edges};
 $('summary').textContent=graph.view_id+' · '+nodes.length+' 個節點 · '+edges.length+' 條關係';
 $('view-info').textContent='原圖：'+graph.nodes.length+' 個節點，'+graph.edges.length+' 條關係';
 $('notice').textContent=edges.length>500?'關係較多，建議縮小物件類型或關係範圍以便查看。':'';
 $('empty').hidden=edges.length!==0;$('status').textContent='';
 $('edges').replaceChildren();const fragment=document.createDocumentFragment();edges.forEach(edge=>{const tr=el('tr');[edge.id,nodeLabel(edge.source),edge.relation,nodeLabel(edge.target)].forEach(t=>tr.append(el('td',t)));const td=el('td'),button=el('button','證據');button.addEventListener('click',()=>inspectEdge(edge));td.append(button);tr.append(td);fragment.append(tr);});$('edges').append(fragment);
 $('nodes').replaceChildren();nodes.forEach(n=>{const tr=el('tr'),td=el('td'),button=el('button',nodeLabel(n.id));button.addEventListener('click',()=>inspectNode(n));td.append(button);tr.append(td,el('td',n.id));$('nodes').append(tr);});
 const ties=(graph.measurements?.equal_pairs||[]).filter(t=>wanted.has(t.relation)&&matches(...t.objects));
 const excluded=(graph.measurements?.excluded_parent_relations||[]).filter(e=>{const relation=PARENTS[typeFor(e.target)];return (relation?wanted.has(relation):(wanted.has('on')||wanted.has('inside')))&&matches(e.source,e.target);});
 current.equal_pairs=ties;current.excluded_parent_relations=excluded;
 $('ties-title').textContent='相等配對：'+ties.length;$('ties').textContent=pretty(ties);
 $('excluded-title').textContent='不可見父物件：'+excluded.length;$('excluded').textContent=pretty(excluded);
 draw(nodes,edges);reset();
}
function draw(nodes,edges){
 const svg=$('svg');svg.replaceChildren();const defs=svgEl('defs');Object.entries(COLORS).forEach(([r,color])=>{const marker=svgEl('marker',{id:'arrow-'+r,viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:7,markerHeight:7,orient:'auto'});marker.append(svgEl('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:color}));defs.append(marker);});svg.append(defs);
 const positions=new Map();nodes.forEach((n,i)=>{const angle=nodes.length===1?0:i*2*Math.PI/nodes.length-Math.PI/2;positions.set(n.id,{x:nodes.length===1?500:500+350*Math.cos(angle),y:nodes.length===1?310:310+235*Math.sin(angle)});});
 edges.forEach(edge=>{const a=positions.get(edge.source),b=positions.get(edge.target),dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy),ux=dx/len,uy=dy/len;
 const sx=a.x+ux*22,sy=a.y+uy*22,tx=b.x-ux*25,ty=b.y-uy*25;
 const offset={on:-18,inside:-6,image_left_of:6,closer_to_camera:18}[edge.relation],direction=edge.source<edge.target?1:-1;
 const cx=(sx+tx)/2-uy*offset*direction,cy=(sy+ty)/2+ux*offset*direction,d=`M ${sx} ${sy} Q ${cx} ${cy} ${tx} ${ty}`;
 const g=svgEl('g',{class:'edge'}),title=svgEl('title');title.textContent=nodeLabel(edge.source)+' → '+edge.relation+' → '+nodeLabel(edge.target);g.append(title,svgEl('path',{class:'edge-line',d,stroke:COLORS[edge.relation],'marker-end':'url(#arrow-'+edge.relation+')'}),svgEl('path',{class:'edge-hit',d}));g.addEventListener('click',()=>inspectEdge(edge));svg.append(g);});
 nodes.forEach(n=>{const p=positions.get(n.id),g=svgEl('g',{class:'node'+(selectedTypes.has(n.objectType)?'':' context'),transform:`translate(${p.x},${p.y})`});const title=svgEl('title');title.textContent=n.id;const label=svgEl('text',{'text-anchor':'middle',y:38});label.textContent=nodeLabel(n.id);g.append(title,svgEl('circle',{r:20}),label);g.addEventListener('click',()=>inspectNode(n));svg.append(g);});
}
function setCamera(){ $('svg').setAttribute('viewBox',`${camera.x} ${camera.y} ${camera.w} ${camera.h}`);}
function reset(){camera={x:0,y:0,w:1000,h:620};setCamera();}
function zoom(factor){camera.x+=camera.w*(1-factor)/2;camera.y+=camera.h*(1-factor)/2;camera.w*=factor;camera.h*=factor;setCamera();}
$('run').textContent=DATA.run_dir;DATA.graphs.forEach(g=>{const option=el('option',g.view_id);option.value=g.view_id;$('view').append(option);});$('view').value=DATA.initial.view;
if(!selectedTypes.size)selectedTypes=new Set(DATA.graphs.find(g=>g.view_id===DATA.initial.view).nodes.map(n=>n.objectType));
choices($('relations'),Object.keys(COLORS),new Set(DATA.initial.relations),()=>render());
Object.entries(COLORS).forEach(([r,color])=>{const span=el('span'),dot=el('i');dot.className='dot';dot.style.background=color;span.append(dot,document.createTextNode(r));$('legend').append(span);});
document.querySelector(`input[name=scope][value=${DATA.initial.scope}]`).checked=true;
$('view').addEventListener('change',()=>changeView());$('type-search').addEventListener('input',filterTypes);
$('all-types').addEventListener('click',()=>{selectedTypes=new Set(graph.nodes.map(n=>n.objectType));showTypes();render();});
$('clear-types').addEventListener('click',()=>{selectedTypes.clear();showTypes();render();});
document.querySelectorAll('input[name=scope]').forEach(n=>n.addEventListener('change',render));
$('reset').addEventListener('click',reset);$('zoom-in').addEventListener('click',()=>zoom(.8));$('zoom-out').addEventListener('click',()=>zoom(1.25));
$('svg').addEventListener('wheel',e=>{e.preventDefault();zoom(e.deltaY>0?1.1:1/1.1);},{passive:false});
let drag=null;$('svg').addEventListener('pointerdown',e=>{if(e.target.closest('.node,.edge'))return;const matrix=$('svg').getScreenCTM();drag={x:e.clientX,y:e.clientY,cx:camera.x,cy:camera.y,scale:matrix.a};$('svg').setPointerCapture(e.pointerId);});
$('svg').addEventListener('pointermove',e=>{if(drag){camera.x=drag.cx-(e.clientX-drag.x)/drag.scale;camera.y=drag.cy-(e.clientY-drag.y)/drag.scale;setCamera();}});['pointerup','pointercancel'].forEach(event=>$('svg').addEventListener(event,()=>drag=null));
$('export').addEventListener('click',()=>{const blob=new Blob([pretty({source_run:DATA.run_dir,definition_version:graph.definition_version,...current})],{type:'application/json'}),url=URL.createObjectURL(blob),a=el('a');a.href=url;a.download=graph.view_id+'_filtered.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
window.addEventListener('error',e=>$('status').textContent='顯示失敗：'+e.message);
changeView(true);document.body.dataset.ready='true';
</script></html>'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path, help="含 visible/ 的 GT run 目錄")
    parser.add_argument("--view", help="初始視角，例如 view_3")
    parser.add_argument("--types", nargs="*", default=[], help="初始物件類型，例如 Apple Bowl CounterTop")
    parser.add_argument("--relations", nargs="+", choices=RELATIONS, default=["on", "inside"])
    parser.add_argument("--scope", choices=("between", "connected"), default="between")
    parser.add_argument("--output", type=Path, help="輸出的 HTML 檔；預設 outputs/graph_inspection/<UTC>.html")
    parser.add_argument("--no-open", action="store_true", help="只產生檔案，不自動開啟瀏覽器")
    args = parser.parse_args(argv)
    try:
        data = load_run(args.run_dir)
        html = render_html(data, view=args.view, types=args.types, relations=args.relations, scope=args.scope)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        output = (args.output or Path("outputs/graph_inspection") / f"{stamp}.html").resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            handle.write(html)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, f"Graph inspector failed: {exc}\n")
    print(f"檢查器：{output}")
    if not args.no_open and not webbrowser.open(output.as_uri()):
        print("請手動用瀏覽器開啟上方 HTML 檔。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
