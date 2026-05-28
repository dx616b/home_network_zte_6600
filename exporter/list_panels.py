import json
for name in ['zte-f6600p-full.json', 'zte-f6600p-wan.json', 'home-network.json']:
    d = json.load(open(f'c:\\Users\\U759339\\zte-wan-monitor\\grafana\\{name}'))
    print(f"\n=== {name} ===")
    print(f"Title: {d.get('title')}")
    for p in d['panels']:
        title = p.get('title', '')
        ptype = p.get('type', '')
        targets = p.get('targets', [])
        exprs = [t.get('expr','')[:80] for t in targets]
        print(f"  id={p['id']:3d} {ptype:12s} {title:40s} {exprs}")
