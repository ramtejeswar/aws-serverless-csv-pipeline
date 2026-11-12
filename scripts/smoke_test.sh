#!/usr/bin/env bash
# End-to-end check of a deployed stack: request an upload, PUT the sample file to S3,
# wait for the background processing, then check the job and its stored records.
# Usage: scripts/smoke_test.sh https://abc123.execute-api.us-east-1.amazonaws.com
#    or: make smoke   (reads the URL from terraform output)
set -euo pipefail

API="${1:?usage: $0 <api_url>}"
API="${API%/}"
SAMPLE="$(cd "$(dirname "$0")/.." && pwd)/samples/orders.csv"
TIMEOUT_SECONDS="${SMOKE_TIMEOUT:-90}"
failures=0

check() {  # check <description> <expected> <actual>
  if [[ "$2" == "$3" ]]; then
    printf '  PASS  %s\n' "$1"
  else
    printf '  FAIL  %s (expected %s, got %s)\n' "$1" "$2" "$3"
    failures=$((failures + 1))
  fi
}

json_field() {  # json_field <python expression on d>  (reads JSON on stdin; no jq needed)
  python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"
}

echo "Smoke testing $API"

created=$(curl -sS -w '\n%{http_code}' -X POST "$API/uploads" \
  -H 'Content-Type: application/json' -d '{"filename": "orders.csv"}')
check "POST /uploads returns 201" 201 "$(tail -n1 <<<"$created")"
job_id=$(head -n1 <<<"$created" | json_field "d['job_id']")
upload_url=$(head -n1 <<<"$created" | json_field "d['upload_url']")
echo "        job: $job_id"

check "new job is PENDING_UPLOAD" PENDING_UPLOAD "$(curl -sS "$API/jobs/$job_id" | json_field "d['status']")"
check "PUT to the presigned URL returns 200" 200 \
  "$(curl -sS -o /dev/null -w '%{http_code}' -X PUT --upload-file "$SAMPLE" "$upload_url")"

status=PENDING_UPLOAD
deadline=$((SECONDS + TIMEOUT_SECONDS))
while [[ "$status" == PENDING_UPLOAD || "$status" == PROCESSING ]] && ((SECONDS < deadline)); do
  sleep 2
  status=$(curl -sS "$API/jobs/$job_id" | json_field "d['status']")
done
check "job finishes as COMPLETED_WITH_ERRORS" COMPLETED_WITH_ERRORS "$status"

job=$(curl -sS "$API/jobs/$job_id")
check "10 rows read, 5 stored, 5 rejected" "10 5 5" \
  "$(json_field "d.get('total_rows'), d.get('valid_rows'), d.get('error_rows')" <<<"$job" | tr -d "(,)")"

page=$(curl -sS "$API/jobs/$job_id/records?limit=3")
check "first page has 3 records" 3 "$(json_field "len(d['records'])" <<<"$page")"
next=$(json_field "d['next']" <<<"$page")
check "second page has the other 2" 2 \
  "$(curl -sS "$API/jobs/$job_id/records?limit=3&next=$next" | json_field "len(d['records'])")"

check "unknown job returns 404" 404 \
  "$(curl -sS -o /dev/null -w '%{http_code}' "$API/jobs/00000000-0000-4000-8000-000000000000")"

if ((failures)); then
  echo "$failures check(s) failed"
  exit 1
fi
echo "All checks passed"
