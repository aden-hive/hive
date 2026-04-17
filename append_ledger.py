import json

with open('/home/timothy/aden/hive/x_rapid_ledger.json', 'r') as f:
    data = json.load(f)

data['replies'].append({
    'original_preview': 'Alright, I give in. Here’s my picture with the boss, courtesy of @johnkrausphotos. Oh, and hook ‘em!'
})

with open('/home/timothy/aden/hive/x_rapid_ledger.json', 'w') as f:
    json.dump(data, f, indent=2)
