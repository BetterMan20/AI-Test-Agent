import json

d = json.load(open('D:/QA-test/AI-Test-Agent/output/test_design.json', 'r', encoding='utf-8'))
tds = d['modules'][0]['test_designs']
print(f"Total designs: {len(tds)}")
print()
for i, td in enumerate(tds):
    print(f"D{i+1}: {td.get('design_id','?')} | {td.get('test_goal','?')[:60]}")
    print(f"   methods: {td.get('test_methods', [])}")
    print(f"   scenario: {td.get('scenario','?')[:60]}")
    print()
