#!/bin/bash
# Generate a VAPID P-256 key pair for Web Push.
# Outputs:
#   ~/.claude/status/vapid_private.pem        — PEM private key (used by server.py)
#   ~/.claude/status/vapid_public.pem         — PEM public key
#   ~/.claude/status/vapid_keys.json          — base64url-encoded raw keys (used by clients)
#
# Run once during install. NEVER commit these files.

set -e

STATUS_DIR="${HOME}/.claude/status"
mkdir -p "$STATUS_DIR"
cd "$STATUS_DIR"

if [[ -f vapid_keys.json ]]; then
    echo "vapid_keys.json already exists — refusing to overwrite."
    echo "Delete it manually if you really want to regenerate."
    exit 1
fi

echo "Generating VAPID P-256 key pair..."
openssl ecparam -name prime256v1 -genkey -noout -out vapid_private.pem
openssl ec -in vapid_private.pem -pubout -out vapid_public.pem 2>/dev/null

PYBIN="$STATUS_DIR/.venv/bin/python"
if [[ ! -x "$PYBIN" ]]; then
    PYBIN=$(which python3)
fi

"$PYBIN" - <<'PY'
import json
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

priv = serialization.load_pem_private_key(open('vapid_private.pem','rb').read(), password=None, backend=default_backend())
pub = priv.public_key()
raw_pub = pub.public_bytes(encoding=serialization.Encoding.X962, format=serialization.PublicFormat.UncompressedPoint)
raw_priv = priv.private_numbers().private_value.to_bytes(32, 'big')

def b64url(b):
    return base64.urlsafe_b64encode(b).decode().rstrip('=')

with open('vapid_keys.json', 'w') as f:
    json.dump({'public_b64url': b64url(raw_pub), 'private_b64url': b64url(raw_priv)}, f, indent=2)

print("Public key:", b64url(raw_pub))
PY

chmod 600 vapid_private.pem vapid_keys.json
echo ""
echo "Done. Three files created with 600/644 permissions:"
ls -la vapid_*
echo ""
echo "Keep vapid_private.pem and vapid_keys.json secret. They are gitignored already."
