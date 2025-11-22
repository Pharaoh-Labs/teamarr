import sqlite3
import json

conn = sqlite3.connect('teamarr.db')
cursor = conn.cursor()

result = cursor.execute('SELECT description_options FROM templates WHERE id = 1').fetchone()
desc_opts = json.loads(result[0])

print(f'Total descriptions: {len(desc_opts)}')

fallbacks = [d for d in desc_opts if d.get("priority") == 100]
conditionals = [d for d in desc_opts if d.get("priority") != 100]

print(f'Fallbacks (priority 100): {len(fallbacks)}')
print(f'Conditionals (priority 1-99): {len(conditionals)}')

print(f'\nFallbacks:')
for fb in fallbacks:
    print(f'  - {fb}')

print(f'\nConditionals:')
for c in conditionals:
    print(f'  - Priority {c["priority"]}: {c.get("name", c.get("condition"))}')

conn.close()
