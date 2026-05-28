import sys, json
d = json.load(sys.stdin)
for r in d["data"]["result"]:
    print(f'{r["metric"]["__name__"]}: {r["value"][1]}')
if not d["data"]["result"]:
    print("no data")
