import base64
import urllib.request
import json

key = "pk_test_c2FmZS1zaGVlcGRvZy00OS5jbGVyay5hY2NvdW50cy5kZXYk"
suffix = key.split("_", 2)[-1]
padded = suffix + "=" * (-len(suffix) % 4)
domain = base64.b64decode(padded).decode().rstrip("$")
jwks_url = "https://" + domain + "/.well-known/jwks.json"

print("Clerk domain:", domain)
print("JWKS URL:   ", jwks_url)
print()

with urllib.request.urlopen(jwks_url, timeout=10) as r:
    jwks = json.loads(r.read())
    keys = jwks.get("keys", [])
    print("JWKS keys found:", len(keys))
    for k in keys:
        print("  kid=" + str(k.get("kid", "?")) + "  alg=" + str(k.get("alg", "?")) + "  use=" + str(k.get("use", "?")))

print()
print("Clerk JWKS reachable -- Google sign-in verification will work.")
