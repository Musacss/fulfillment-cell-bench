#!/usr/bin/env bash
# Sync evidence/{benchmark-v2,harbor-runs} from Verda and enforce fail-closed secret & opencode.db scrubbing.
set -euo pipefail
set +x

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

REMOTE_HOST="${VERDA_REMOTE:-verda-junction}"
REMOTE_DIR="${VERDA_REMOTE_DIR:-/root/bench}"
DEST_DIR="${REPO_ROOT}/evidence"
DRY_RUN=0
SMOKE_LOCAL_DIR=""

usage() {
  cat <<'EOF'
Usage: sync_evidence.sh [--remote <host>] [--remote-dir <path>] [--dest <dir>] [--dry-run] [--smoke-local <dir>] [--help]

Syncs `evidence/benchmark-v2/` and `evidence/harbor-runs/` from remote via `rsync`
(excluding binary `*/agent/opencode/`, `opencode.db`, `*.sqlite*`, and `.env*`),
redacts any residual API keys, Bearer tokens, PEM private keys, and SSH paths,
and fails non-zero if a post-scrub verification scan matches any secret pattern.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    --remote)
      REMOTE_HOST="$2"
      shift 2
      ;;
    --remote-dir)
      REMOTE_DIR="$2"
      shift 2
      ;;
    --dest)
      DEST_DIR="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --smoke-local)
      SMOKE_LOCAL_DIR="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

RSYNC_EXCLUDES=(
  "--no-links"
  "--exclude=*/agent/opencode/"
  "--exclude=agent/opencode/"
  "--exclude=opencode.db"
  "--exclude=opencode.db*"
  "--exclude=*.db"
  "--exclude=*.db-*"
  "--exclude=*.sqlite*"
  "--exclude=.env"
  "--exclude=.env.*"
  "--exclude=*.pem"
  "--exclude=*.key"
  "--exclude=id_ed25519*"
  "--exclude=id_rsa*"
)

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[sync-evidence] DRY-RUN rsync ${RSYNC_EXCLUDES[*]} ${REMOTE_HOST}:${REMOTE_DIR}/evidence/{benchmark-v2,harbor-runs} -> ${DEST_DIR}/"
  exit 0
fi

if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  PY_BIN="${REPO_ROOT}/.venv/bin/python"
elif [[ -x "${REPO_ROOT}/../../.venv/bin/python" ]]; then
  PY_BIN="${REPO_ROOT}/../../.venv/bin/python"
elif command -v python3.12 >/dev/null 2>&1; then
  PY_BIN="$(command -v python3.12)"
else
  PY_BIN="python3"
fi

TARGET_SCRUB_DIR="$SMOKE_LOCAL_DIR"
if [[ -z "$TARGET_SCRUB_DIR" ]]; then
  mkdir -p "${DEST_DIR}/benchmark-v2" "${DEST_DIR}/harbor-runs"
  rsync -avz "${RSYNC_EXCLUDES[@]}" \
    "${REMOTE_HOST}:${REMOTE_DIR}/evidence/benchmark-v2/" \
    "${DEST_DIR}/benchmark-v2/"
  rsync -avz "${RSYNC_EXCLUDES[@]}" \
    "${REMOTE_HOST}:${REMOTE_DIR}/evidence/harbor-runs/" \
    "${DEST_DIR}/harbor-runs/" || true
  TARGET_SCRUB_DIR="$DEST_DIR"
fi

"$PY_BIN" - "$TARGET_SCRUB_DIR" <<'PY'
import json
import os
from pathlib import Path
import re
import shutil
import sys

root = Path(sys.argv[1]).resolve()
if not root.exists():
    raise SystemExit(f"Target directory does not exist: {root}")

# 1. Remove symlinks and forbidden binary/secret directories & files
def is_forbidden_filename(fname: str) -> bool:
    low = fname.lower()
    return (
        low == "opencode.db"
        or low.startswith("opencode.db")
        or low.endswith(".db")
        or ".db-" in low
        or ".sqlite" in low
        or low == ".env"
        or low.startswith(".env.")
        or low.endswith(".env")
        or low.endswith((".pem", ".key"))
        or low.startswith(("id_ed25519", "id_rsa"))
    )


for current_root, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
    cur_path = Path(current_root)
    for d in list(dirnames):
        dpath = cur_path / d
        if dpath.is_symlink():
            dpath.unlink(missing_ok=True)
            dirnames.remove(d)
        elif d == "opencode" and cur_path.name == "agent":
            shutil.rmtree(dpath)
            dirnames.remove(d)
    for fname in list(filenames):
        fpath = cur_path / fname
        if fpath.is_symlink() or is_forbidden_filename(fname):
            fpath.unlink(missing_ok=True)

# 2. Scrub text payloads while preserving clean JSON/JSONL byte formatting (so SHA-256 digests stay intact)
PEM_CLOSED_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----"
)
PEM_UNCLOSED_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*$")
GOOGLE_KEY_RE = re.compile(r"AIza[0-9A-Za-z_-]{16,}")
SK_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")
HF_TOKEN_RE = re.compile(r"\bhf_[A-Za-z0-9]{16,}")
GITHUB_TOKEN_RE = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"glpat-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})"
)
BEARER_RE = re.compile(r"\bbearer\s+(?!\[REDACTED)[A-Za-z0-9._~+/=-]{8,}", flags=re.IGNORECASE)
HEADER_SECRET_RE = re.compile(
    r"(\b(?:x-goog-api-key|x-api-key)\s*:\s*)(?!\[REDACTED)([^\s\"'\\;,)}\]]+)",
    flags=re.IGNORECASE,
)
ENV_ASSIGN_RE = re.compile(
    r"((?:export\s+)?(?!\b(?:total|prompt|completion|max|input|output|cached|reasoning|num|eval|train|stop|special|pad|eos|bos)[_-]?tokens?\b)"
    r"\b[A-Za-z0-9_]*(?:API_KEY|APIKEY|SECRET|TOKEN|PASSWORD|PASSWD|PRIVATE_KEY|CREDENTIAL)[A-Za-z0-9_]*\s*=\s*)"
    r"(?:\"([^\"\r\n]*)\"|\\\"([^\"\\\r\n]*)\\\"|'([^'\r\n]*)'|([^\s\"'\\;,)}\]]+))",
    flags=re.IGNORECASE,
)
SSH_PATH_RE = re.compile(
    r"(?:~|/root|/home/[^/\s\"'\\]+|/Users/[^/\s\"'\\]+)/\.ssh/[A-Za-z0-9._-]+|\bid_(?:ed25519|rsa)(?:\.pub)?\b"
)
SENSITIVE_KEY_RE = re.compile(
    r"\A(?!(?:total|prompt|completion|max|input|output|cached|reasoning|num|eval|train|stop|special|pad|eos|bos)[_-]?tokens?\Z)"
    r"[\s\S]*(?:^|[_-])(?:api[_-]?key|apikey|secret|token|password|passwd|pwd|private[_-]?key|credential|"
    r"authorization|bearer|access[_-]?key|client[_-]?secret)(?:$|[_-])",
    flags=re.IGNORECASE,
)


def _env_match_has_secret(match: re.Match[str]) -> bool:
    for g_idx in (2, 3, 4, 5):
        val = match.group(g_idx)
        if val is not None:
            cleaned_val = val.strip().strip("\"'\\")
            return bool(cleaned_val) and "[REDACTED" not in val
    return False


def _replace_env_assign(match: re.Match[str]) -> str:
    if not _env_match_has_secret(match):
        return match.group(0)
    return f"{match.group(1)}[REDACTED]"


def scrub_string(s: str) -> str:
    out = PEM_CLOSED_RE.sub("[REDACTED]", s)
    out = PEM_UNCLOSED_RE.sub("[REDACTED]", out)
    out = GOOGLE_KEY_RE.sub("[REDACTED]", out)
    out = SK_KEY_RE.sub("[REDACTED]", out)
    out = HF_TOKEN_RE.sub("[REDACTED]", out)
    out = GITHUB_TOKEN_RE.sub("[REDACTED]", out)
    out = BEARER_RE.sub("Bearer [REDACTED]", out)
    out = HEADER_SECRET_RE.sub(r"\1[REDACTED]", out)
    out = ENV_ASSIGN_RE.sub(_replace_env_assign, out)
    out = SSH_PATH_RE.sub("[REDACTED]", out)
    return out


def scrub_json_obj(obj):
    if isinstance(obj, str):
        return scrub_string(obj)
    if isinstance(obj, list):
        return [scrub_json_obj(x) for x in obj]
    if isinstance(obj, dict):
        out_dict = {}
        for k, v in obj.items():
            clean_k = scrub_string(str(k))
            if SENSITIVE_KEY_RE.search(clean_k) and isinstance(v, str) and v not in ("", "[REDACTED]"):
                out_dict[clean_k] = "[REDACTED]"
            else:
                out_dict[clean_k] = scrub_json_obj(v)
        return out_dict
    return obj


def _find_unredacted_json_keys(obj) -> list[str]:
    bad: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            ks = str(k)
            if SENSITIVE_KEY_RE.search(ks) and isinstance(v, str) and v not in ("", "[REDACTED]"):
                bad.append(ks)
            bad.extend(_find_unredacted_json_keys(v))
    elif isinstance(obj, list):
        for item in obj:
            bad.extend(_find_unredacted_json_keys(item))
    return bad


for file_path in sorted(root.rglob("*")):
    if file_path.is_symlink() or not file_path.is_file():
        continue
    try:
        raw_text = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue

    if file_path.suffix == ".json":
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            cleaned = scrub_string(raw_text)
            if cleaned != raw_text:
                file_path.write_text(cleaned, encoding="utf-8")
        else:
            scrubbed_obj = scrub_json_obj(parsed)
            if scrubbed_obj != parsed:
                file_path.write_text(json.dumps(scrubbed_obj, indent=2) + "\n", encoding="utf-8")
    elif file_path.suffix == ".jsonl":
        changed_any = False
        out_lines = []
        for ln in raw_text.splitlines():
            if not ln.strip():
                out_lines.append(ln)
                continue
            try:
                parsed_ln = json.loads(ln)
            except json.JSONDecodeError:
                scrubbed_ln = scrub_string(ln)
                if scrubbed_ln != ln:
                    changed_any = True
                out_lines.append(scrubbed_ln)
            else:
                scrubbed_ln_obj = scrub_json_obj(parsed_ln)
                if scrubbed_ln_obj != parsed_ln:
                    changed_any = True
                    out_lines.append(json.dumps(scrubbed_ln_obj))
                else:
                    out_lines.append(ln)
        if changed_any:
            trailing_nl = "\n" if raw_text.endswith("\n") or out_lines else ""
            file_path.write_text("\n".join(out_lines) + trailing_nl, encoding="utf-8")
    else:
        cleaned = scrub_string(raw_text)
        if cleaned != raw_text:
            file_path.write_text(cleaned, encoding="utf-8")

# 3. Fail-closed post-scrub verification scan
RESIDUAL_PATTERNS = [
    ("google_api_key", GOOGLE_KEY_RE),
    ("sk_secret_key", SK_KEY_RE),
    ("hf_token", HF_TOKEN_RE),
    ("github_pat_token", GITHUB_TOKEN_RE),
    ("pem_private_key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("ssh_private_key_path", SSH_PATH_RE),
    ("unredacted_bearer", BEARER_RE),
    ("unredacted_header_secret", HEADER_SECRET_RE),
]

violations: list[str] = []
for current_root, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
    cur_path = Path(current_root)
    for d in dirnames:
        dpath = cur_path / d
        if dpath.is_symlink():
            violations.append(f"forbidden_symlink:{dpath}")
        elif d == "opencode" and cur_path.name == "agent":
            violations.append(f"forbidden_dir:{dpath}")
    for fname in filenames:
        file_path = cur_path / fname
        if file_path.is_symlink():
            violations.append(f"forbidden_symlink:{file_path}")
            continue
        if is_forbidden_filename(fname):
            violations.append(f"forbidden_file:{file_path}")
            continue
        raw_bytes = file_path.read_bytes()
        if raw_bytes.startswith(b"SQLite format 3\x00"):
            violations.append(f"sqlite_magic_header:{file_path}")
            continue
        text_scan = raw_bytes.decode("utf-8", errors="ignore")
        for label, regex in RESIDUAL_PATTERNS:
            if regex.search(text_scan):
                violations.append(f"{label}:{file_path}")
        for env_m in ENV_ASSIGN_RE.finditer(text_scan):
            if _env_match_has_secret(env_m):
                violations.append(f"unredacted_env_secret:{file_path}")
                break
        if file_path.suffix == ".json":
            try:
                parsed_scan = json.loads(text_scan)
            except json.JSONDecodeError:
                pass
            else:
                for bad_k in _find_unredacted_json_keys(parsed_scan):
                    violations.append(f"unredacted_json_secret_key:{file_path}:{bad_k}")
        elif file_path.suffix == ".jsonl":
            for ln in text_scan.splitlines():
                if not ln.strip():
                    continue
                try:
                    parsed_ln_scan = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                for bad_k in _find_unredacted_json_keys(parsed_ln_scan):
                    violations.append(f"unredacted_json_secret_key:{file_path}:{bad_k}")

if violations:
    raise SystemExit("FAIL-CLOSED SECRET AUDIT VIOLATIONS:\n" + "\n".join(violations))

print(json.dumps({"status": "scrub_verified_clean", "target": str(root)}))
PY
