import json

d = json.load(open('D:/QA-test/AI-Test-Agent/output/test_cases.json', 'r', encoding='utf-8'))
cs = d['modules'][0]['testcases']
print(f"Total test cases: {len(cs)}")
print()

for i, c in enumerate(cs):
    cid = c.get('case_id', '?')
    cat = c.get('category', '?')
    title = c.get('title', '?')
    steps = c.get('steps', [])
    print(f"{i+1}. [{cid}] [{cat}] {title}")
    print(f"   Steps: {len(steps)}")
    for j, s in enumerate(steps):
        action = s.get('action', '')[:60]
        expected = s.get('expected', '')[:60]
        print(f"   Step {j+1}: action={action}")
        print(f"           expected={expected}")
    print()
