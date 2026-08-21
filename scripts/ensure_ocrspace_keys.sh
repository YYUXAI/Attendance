#!/usr/bin/env bash
# Inject OCR.space keys into attendance secret volumes (survives normal restage;
# re-run after volume wipe). Source: secrets/ux-extensions/ocrspace_api_keys
set -euo pipefail
SRC="${OCRSPACE_KEYS_FILE:-/srv/ux/environments/test/ux-assistant/secrets/ux-extensions/ocrspace_api_keys}"
KEYS="$(cat "$SRC")"
test -n "$KEYS"
for vol in \
  uxassistant-test-rootless_attendance-provider-secrets \
  uxassistant-test-rootless_attendance-scheduler-secrets \
  uxassistant-test-rootless_attendance-worker-secrets
do
  ux docker run --rm -v "${vol}:/out" alpine:3.20 \
    sh -c "printf '%s\n' '$KEYS' > /out/ocrspace_api_keys && chown 10003:10003 /out/ocrspace_api_keys && chmod 400 /out/ocrspace_api_keys"
  echo "ok $vol"
done
