import urllib.request, json

req = urllib.request.Request("http://localhost:8000/openapi.json")
with urllib.request.urlopen(req, timeout=10) as r:
    spec = json.loads(r.read())

paths = spec.get("paths", {})
auth_paths = [p for p in paths if "/auth/" in p]
billing_paths = [p for p in paths if "/billing/" in p]

print("AUTH routes:")
for p in sorted(auth_paths):
    methods = list(paths[p].keys())
    print(f"  {', '.join(m.upper() for m in methods)} {p}")

print("\nBILLING routes:")
for p in sorted(billing_paths):
    methods = list(paths[p].keys())
    print(f"  {', '.join(m.upper() for m in methods)} {p}")
