"""Build the standalone HTML guide and editable SVG from local documentation."""
from pathlib import Path
import html
import re

ROOT = Path(__file__).resolve().parent
lanes = [
    ('MOD AUTHOR', '#216e65', [
        ('1  Choose donor + unique prefix', ['Stock donor, replacement media OVL,', 'or custom WEMs using listed suffixes.']),
        ('2  Build species audio', ['Re-ID donor events and media.', 'Keep report.json for graph routing.']),
        ('3  Keep the complete output trio', ['<prefix>_events.bnk + _media.bnk', '<prefix>.wmetasb.add']),
        ('4  Edit the staged motiongraph', ['Rename owned events; retain shared ones.', 'Prefab AudioCore.Name stays on donor.']),
        ('5  Continue before another edit', ['Continue from staged result → new step.', 'Reload analysis; select and scan again.']),
        ('6  Verify and package the species', ['Ship graph/prefab assets + audio trio.', 'Do not ship the generated registry pair.']),
    ]),
    ('END USER', '#285d9e', [
        ('1  Set up the merge tools once', ['Python 3.11+ and merge requirements.', 'Configure compatible external Cobra.']),
        ('2  Close JWE3 and install', ['One root xinput1_4.dll + shared loader.', 'Species files go under Win64/ovldata.']),
        ('3  Check all three audio files', ['Both banks + fragment in <Mod>/Audio.', 'Use the finished author-provided assets.']),
        ('4  Run a normal registry merge', ['GUI: Merge registry, or merge BAT/CLI.', 'Check-only does not install a new pair.']),
        ('5  Require verified merge output', ['VLAudioLoader/Audio/audiometadata.ovl', '+ audio_manifest.sha256']),
        ('6  Launch and listen in a park', ['Check latest log, then creature actions.', 'Re-merge after audio update/removal.']),
    ]),
    ('WHAT THE SYSTEM DOES', '#805329', [
        ('A  Merge reads installed inputs', ['Stock registry + every mod fragment.', 'Validate banks, IDs, and declarations.']),
        ('B  Build and round-trip registry', ['Verify registry records after extraction.', 'Hash stock, merged output, and inputs.']),
        ('C  Proxy starts with the game', ['xinput1_4.dll beside JWE3.exe starts', 'the shared automatic loading path.']),
        ('D  Manifest freshness gate', ['Valid → use merged registry/load banks.', 'Stale → stock fallback; custom disabled.']),
        ('E  Banks + registry + graph agree', ['Media loads before event banks.', 'Graph requests a registered owned event.']),
        ('F  Creature action plays audio', ['Event resolves to the new media IDs.', 'Shared events retain their donor route.']),
    ]),
]
parts = ['''<svg xmlns="http://www.w3.org/2000/svg" width="1260" height="1130" viewBox="0 0 1260 1130" role="img" aria-labelledby="title desc">
<title id="title">JWE3 custom audio: author, installation, and runtime workflows</title>
<desc id="desc">Three columns show how authors build banks and route events, users install and merge, and the runtime checks the manifest before loading custom audio.</desc>
<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6" fill="none" stroke="#75848c" stroke-width="1.4"/></marker></defs>
<rect width="1260" height="1130" rx="18" fill="#f3f6f8"/>
<g font-family="Segoe UI,Arial,sans-serif"><text x="36" y="48" font-size="27" font-weight="700" fill="#152b3c">JWE3 CUSTOM AUDIO</text>
<text x="36" y="78" font-size="16" fill="#526372">Three workflows • Read each column top to bottom • Loader v6.1 / 7 Sep 2026</text>''']
for col, (title, color, nodes) in enumerate(lanes):
    x = 30 + col * 410
    parts.append(f'<rect x="{x}" y="103" width="380" height="44" rx="9" fill="{color}"/><text x="{x+18}" y="131" fill="white" font-size="17" font-weight="700">{html.escape(title)}</text>')
    for row, (title, lines) in enumerate(nodes):
        y = 164 + row * 133
        parts.append(f'<rect x="{x}" y="{y}" width="380" height="109" rx="9" fill="white" stroke="#d6dfe5"/><rect x="{x}" y="{y+12}" width="4" height="85" fill="{color}"/>')
        parts.append(f'<text x="{x+17}" y="{y+29}" fill="#152b3c" font-size="17" font-weight="700">{html.escape(title)}</text>')
        for j, line in enumerate(lines):
            parts.append(f'<text x="{x+17}" y="{y+58+j*24}" fill="#445968" font-size="15">{html.escape(line)}</text>')
        if row < 5:
            parts.append(f'<path d="M{x+190},{y+112} V{y+130}" stroke="#75848c" stroke-width="2" marker-end="url(#arrow)"/>')
parts.append('''<rect x="30" y="972" width="1200" height="124" rx="10" fill="#152b3c"/>
<text x="52" y="1004" fill="#ffffff" font-size="18" font-weight="700">THE HANDOFF</text>
<text x="52" y="1035" fill="#e1edf2" font-size="17">Author ships species assets + 2 banks + 1 fragment → User installs and merges → Game resolves creature events.</text>
<text x="52" y="1065" fill="#e1edf2" font-size="17">Every bank/fragment change needs a new merge. A successful bank load alone does not prove audible playback.</text>
</g></svg>''')
svg = '\n'.join(parts)
(ROOT/'CUSTOM_AUDIO_WORKFLOW.svg').write_text(svg, encoding='utf-8')

def inline(text):
    text = html.escape(text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    return text

lines = (ROOT/'CUSTOM_AUDIO_GUIDE.md').read_text(encoding='utf-8').splitlines()
body, paragraph = [], []
code = None
list_type = None
table = False
def flush():
    if paragraph:
        body.append('<p>'+inline(' '.join(paragraph))+'</p>')
        paragraph.clear()
def close_list():
    global list_type
    if list_type:
        body.append(f'</{list_type}>')
        list_type = None
for line in lines + ['']:
    if line.startswith('```'):
        if code is None:
            flush(); close_list(); code = []
        else:
            body.append('<pre><code>'+html.escape('\n'.join(code))+'</code></pre>'); code = None
        continue
    if code is not None:
        code.append(line); continue
    if line.startswith('|'):
        flush(); close_list()
        if not table:
            body.append('<div class="table"><table>'); table = True
            tag = 'th'
        else:
            tag = 'td'
        cells = [s.strip() for s in line.strip('|').split('|')]
        if all(re.fullmatch(r'[- :]+', s) for s in cells): continue
        body.append('<tr>'+''.join(f'<{tag}>{inline(c)}</{tag}>' for c in cells)+'</tr>')
        continue
    if table:
        body.append('</table></div>'); table = False
    if not line:
        flush(); close_list(); continue
    if line.startswith('!['):
        flush(); body.append('<figure>'+svg+'<figcaption>Authoring → installation → runtime. Keep the audio trio together.</figcaption></figure>'); continue
    if line.startswith('#'):
        flush(); close_list()
        n = len(line)-len(line.lstrip('#'))
        title = line[n:].strip()
        anchor = 's'+re.match(r'\d+', title)[0] if re.match(r'\d+', title) else ''
        body.append(f'<h{n} id="{anchor}">{inline(title)}</h{n}>'); continue
    match = re.match(r'^(\d+\. |[-] )(.*)', line)
    if match:
        flush()
        kind = 'ul' if match[1].startswith('-') else 'ol'
        if kind != list_type:
            close_list(); body.append(f'<{kind}>'); list_type = kind
        body.append('<li>'+inline(match[2])+'</li>'); continue
    if line.startswith('> '):
        flush(); close_list(); body.append('<blockquote>'+inline(line[2:])+'</blockquote>'); continue
    if list_type and body[-1].endswith('</li>'):
        body[-1] = body[-1][:-5]+' '+inline(line.strip())+'</li>'
    else:
        paragraph.append(line.strip())
css = '''body{margin:0;background:#f3f6f8;color:#203647;font:17px/1.65 "Segoe UI",Arial,sans-serif}main{max-width:1050px;margin:35px auto;background:white;padding:48px 60px;border-radius:14px}h1{font-size:40px;line-height:1.2;letter-spacing:-1px;color:#152b3c}h2{margin-top:54px;border-top:2px solid #d8e7e9;padding-top:22px;color:#216e65;font-size:27px}h3{color:#285d9e;margin-top:28px}p,li{max-width:88ch}li{margin:9px 0}code{font-size:.9em;background:#edf2f5;padding:2px 5px;border-radius:4px}pre{background:#142c3c;color:#ecf6fc;padding:20px;border-radius:8px;white-space:pre-wrap;overflow-wrap:anywhere}pre code{background:none;padding:0}table{width:100%;border-collapse:collapse;font-size:15px}th{text-align:left;background:#e6f1ef;color:#194e47}td,th{padding:12px;border-bottom:1px solid #dce4e8;vertical-align:top}tr:nth-child(even){background:#f7f9fa}figure{margin:32px -20px}svg{width:100%;height:auto}figcaption{font-size:14px;color:#637480;text-align:center}blockquote{border-left:4px solid #216e65;margin:0;padding:8px 18px;background:#edf5f3}nav{display:flex;gap:20px;flex-wrap:wrap;background:#edf5f3;padding:16px;border-radius:8px}a{color:#285d9e}@media(max-width:720px){main{margin:0;padding:22px}h1{font-size:30px}.table{overflow:auto}figure{margin:20px 0}}@media print{body{background:white;font-size:10pt}main{margin:0;padding:0;max-width:none}h1{font-size:27pt}h2{font-size:18pt}h2,h3{break-after:avoid}figure,pre,tr{break-inside:avoid}figure{margin:10px 0}nav{display:none}pre{color:#203647;background:#edf2f5}a{color:inherit}svg{max-height:235mm}@page{size:A4;margin:15mm}}'''
doc = '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>JWE3 Custom Audio Guide</title><style>'+css+'</style></head><body><main><nav><a href="#s2">Install & setup</a><a href="#s6">Mod authoring</a><a href="#s11">Troubleshooting</a><span>Offline guide · Print / Save as PDF supported</span></nav>'+''.join(body)+'</main></body></html>'
(ROOT/'CUSTOM_AUDIO_GUIDE.html').write_text(doc, encoding='utf-8')
print('Built CUSTOM_AUDIO_GUIDE.html and CUSTOM_AUDIO_WORKFLOW.svg')
