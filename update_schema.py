import json

try:
    with open('data/linkedin_ledger.json', 'r') as f:
        data = json.load(f)
    
    profiles = data.get('messaged_profiles', [])
    for p in profiles:
        if 'variant' not in p:
            p['variant'] = 'Control' # Retroactively label our first runs
            
    with open('data/linkedin_ledger.json', 'w') as f:
        json.dump({"messaged_profiles": profiles}, f, indent=2)
except Exception as e:
    print(f"Error: {e}")
