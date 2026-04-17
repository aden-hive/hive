import json, sys

with open('/home/timothy/aden/hive/x_rapid_ledger.json', 'r') as f:
    ledger = json.load(f)

text = sys.argv[1]
for r in ledger['replies']:
    if r.get('original_preview') == text:
        print("YES")
        sys.exit(0)
print("NO")
