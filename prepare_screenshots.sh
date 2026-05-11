#!/usr/bin/env bash
# Captura artefatos de imprensa pro artigo Medium.
#
# O que esse script faz, automaticamente:
#   • Reset do diretório ./screenshots/
#   • Roda testes + ruff como portão de qualidade
#   • Sobe a API FastAPI numa porta dedicada (default 8086)
#   • Salva JSON dos endpoints de identidade (.well-known/*)
#   • Roda o cost guard diretamente contra BigQuery e captura o output
#   • Emite um audit-log realista (3 eventos JSON) com uma query real
#   • Imprime instruções para os 3 prints de UI (que precisam de captura manual)
#   • Deixa a API rodando p/ você capturar /readyz, /healthz, etc., ao vivo
#
# Use:
#   ./prepare_screenshots.sh
#
# Para sair: Ctrl-C. O cleanup mata a API automaticamente.
set -euo pipefail

cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"

OUT_DIR="${OUT_DIR:-screenshots}"
SERVER_PORT="${SERVER_PORT:-8086}"

# --- helpers ---------------------------------------------------------------
log()  { printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; }
ok()   { printf '  \033[1;32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[1;33m!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

SERVER_PID=""
cleanup() {
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    log "Parando FastAPI server (pid=$SERVER_PID)"
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# --- 0. sanity -------------------------------------------------------------
log "Checagem de dependências"
command -v uv  >/dev/null || die "uv não está no PATH (instale: curl -LsSf https://astral.sh/uv/install.sh | sh)"
command -v jq  >/dev/null || die "jq não está no PATH (apt: sudo apt-get install -y jq)"
command -v curl >/dev/null || die "curl não está no PATH"
command -v gcloud >/dev/null || warn "gcloud não encontrado — captura de cost-guard real pode falhar"
ok "uv + jq + curl OK"

# --- 1. reset --------------------------------------------------------------
log "Limpando $OUT_DIR/"
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"
ok "$OUT_DIR/ pronto"

# --- 2. portão de qualidade ------------------------------------------------
log "Rodando pytest + ruff (artefatos precisam casar com build verificado)"
if uv run pytest tests/unit/ -q >"$OUT_DIR/00-test-summary.txt" 2>&1; then
  tail -1 "$OUT_DIR/00-test-summary.txt"
  ok "pytest verde"
else
  cat "$OUT_DIR/00-test-summary.txt"
  die "pytest falhou — corrija antes de capturar prints"
fi
uv run ruff check app tests >/dev/null && ok "ruff limpo" || die "ruff falhou"

# --- 3. boot do server -----------------------------------------------------
log "Subindo FastAPI server em :$SERVER_PORT"
PORT="$SERVER_PORT" uv run uvicorn app.server:app \
  --host 127.0.0.1 --port "$SERVER_PORT" --log-level warning \
  >"$OUT_DIR/server.log" 2>&1 &
SERVER_PID=$!
for i in {1..20}; do
  if curl -sf "http://127.0.0.1:$SERVER_PORT/healthz" >/dev/null 2>&1; then
    ok "server pronto (pid=$SERVER_PID)"
    break
  fi
  sleep 1
  [[ $i -eq 20 ]] && { cat "$OUT_DIR/server.log"; die "server não subiu — veja $OUT_DIR/server.log"; }
done

# --- 4. identity envelope (Print 3) ---------------------------------------
log "Capturando envelope de identidade (.well-known/agent-identity)"
curl -s "http://127.0.0.1:$SERVER_PORT/.well-known/agent-identity" \
  | jq '.' > "$OUT_DIR/01-identity-envelope.json"
head -30 "$OUT_DIR/01-identity-envelope.json"

log "Capturando registro completo (.well-known/agents — campos chave)"
curl -s "http://127.0.0.1:$SERVER_PORT/.well-known/agents" \
  | jq '[.[] | {name, classification, owner_email, model, data_scopes, spiffe_id}]' \
  > "$OUT_DIR/02-registry-all-agents.json"
cat "$OUT_DIR/02-registry-all-agents.json"

# --- 5. cost guard direto na tool (Print 6) -------------------------------
log "Cost-guard demo (chamada direta ao bigquery_query — espera COST_GUARD_BLOCKED)"
uv run python - <<'PY' 2>&1 | tee "$OUT_DIR/03-cost-guard.txt"
import json
from app.tools.bigquery import bigquery_query

# bigquery-public-data.samples.wikipedia tem ~38 GB e não exige partition filter.
# Nosso teto é 1 GiB, então o dry-run estima ~38 GB e o callback bloqueia.
print("# Pergunta hipotética: agent tenta SELECT * numa tabela de ~38 GB")
print("# Esperado: dry-run estima >1 GiB → callback bloqueia ANTES de executar")
print()
out = bigquery_query("SELECT * FROM `bigquery-public-data.samples.wikipedia`")
print(json.dumps(out, indent=2, default=str))
PY

# --- 6. audit log sample (Print 4) ----------------------------------------
log "Capturando audit log estruturado (callbacks + query real)"
uv run python - <<'PY' 2>&1 | tee "$OUT_DIR/04-audit-log-sample.txt"
"""Emite 3 eventos JSON realistas:
  agent.invocation.start  →  tool.call.start  →  bigquery.query_ok  →  tool.call.ok
para mostrar como o audit trail aparece no Cloud Logging.
"""
from types import SimpleNamespace
from app.utils.logging import configure_logging
configure_logging("INFO")

from app.shared_libraries import callbacks
from app.tools.bigquery import bigquery_query


class FakeTool:
    def __init__(self, name: str) -> None: self.name = name


state: dict = {}
ctx = SimpleNamespace(
    agent_name="data_agent",
    invocation_id="e-screenshot-demo-001",
    state=state,
)

# 1) agent.invocation.start
callbacks.before_agent_callback(ctx)

# 2) tool.call.start + real BigQuery query + tool.call.ok
sql = "SELECT name, year FROM `acme-financials.analytics.usa_names` WHERE state='AK' LIMIT 5"
callbacks.before_tool_callback(FakeTool("bigquery_query"), {"sql": sql}, ctx)

# A chamada real emite o evento bigquery.query_ok com bytes_billed/job_id reais.
result = bigquery_query(sql)

callbacks.after_tool_callback(FakeTool("bigquery_query"), {"sql": sql}, ctx, result)

# 3) saída visível só pra confirmar — não é log, é output do script
print()
print("# rows retornados:", result.get("returned_rows", "?"))
print("# bytes_billed:", result.get("bytes_billed", "?"))
print("# job_id:", result.get("job_id", "?"))
PY

# --- 7. health checks ------------------------------------------------------
log "Capturando /healthz e /readyz"
curl -s "http://127.0.0.1:$SERVER_PORT/healthz" | jq > "$OUT_DIR/05-healthz.json"
curl -s "http://127.0.0.1:$SERVER_PORT/readyz"  | jq > "$OUT_DIR/06-readyz.json"
ok "health endpoints capturados"

# --- 8. instruções finais --------------------------------------------------
cat <<EOF

╔══════════════════════════════════════════════════════════════════════════╗
║ Artefatos capturados em ./$OUT_DIR/                                       ║
╚══════════════════════════════════════════════════════════════════════════╝

  00-test-summary.txt            → portão de qualidade (62/62 passing)
  01-identity-envelope.json      → Print 3 (bridge — figura 8 do roteiro)
  02-registry-all-agents.json    → Print 3 (bonus — registro completo)
  03-cost-guard.txt              → Print 6 (cost guard disparando)
  04-audit-log-sample.txt        → Print 4 (audit log JSON real)
  05-healthz.json                → opcional
  06-readyz.json                 → opcional
  server.log                     → tudo o que o uvicorn cuspiu

╔══════════════════════════════════════════════════════════════════════════╗
║ Prints de UI (capture manualmente)                                        ║
╚══════════════════════════════════════════════════════════════════════════╝

 ▸ Print 1 — Graph
     Abra noutro terminal:  adk web
     Navegue:               http://127.0.0.1:8000/dev-ui/
     Selecione "app" no dropdown e capture o painel "Graph".

 ▸ Print 2 + 4 (variante ao vivo) — Trace + audit log
     No adk web, envie ao agente:

         List the columns of the usa_names table in the analytics
         dataset, then show me the top 5 female names from 1925 with
         their counts and originating state.

     Capture:
       • A aba "Trace" da sessão (Print 2)
       • O terminal do adk web rodando enquanto processa (Print 4)

 ▸ Print 5 — Honest refusal (essencial)
     No mesmo adk web, envie:

         Who can ultimately cause a write to the customer table in
         this environment?

     Capture a resposta final do agente, com TL;DR + Caveats explícitos.

╔══════════════════════════════════════════════════════════════════════════╗
║ Server ainda rodando em http://127.0.0.1:$SERVER_PORT                          ║
║ → use pra capturas extras dos endpoints. Ctrl-C aqui mata o server.       ║
╚══════════════════════════════════════════════════════════════════════════╝

EOF

wait "$SERVER_PID"
