"""Вшивает events.json в index.html (строка `const EVENTS = [...]`), чтобы дашборд работал без сервера."""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
html_path, data_path = os.path.join(HERE, "index.html"), os.path.join(HERE, "events.json")

with open(data_path, encoding="utf-8") as f:
    data = f.read().strip()
with open(html_path, encoding="utf-8") as f:
    lines = f.read().split("\n")

idx = [i for i, l in enumerate(lines) if l.startswith("const EVENTS = [")]
assert len(idx) == 1, "в index.html должна быть ровно одна строка `const EVENTS = [...]`"
lines[idx[0]] = f"const EVENTS = {data};"

with open(html_path, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("events.json вшит в index.html")
