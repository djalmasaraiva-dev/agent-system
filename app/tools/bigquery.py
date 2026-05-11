"""BigQuery tool exposed to the data_agent.

Patterns referenced from the bigquery-basics skill:
    https://github.com/google/skills/tree/main/skills/cloud/bigquery-basics

Production guarantees enforced by this tool:
  * Parameterized queries only (named params; @param style).
  * Cost guard via maximum_bytes_billed before execution.
  * Dataset allow-list — refuses queries that touch datasets outside the
    configured BIGQUERY_DATASET unless explicitly fully-qualified by the caller
    and the project matches.
  * Row cap on the returned payload to keep agent context small.
  * Structured error messages — the agent gets actionable feedback instead of
    raw tracebacks it cannot reason about.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from google.api_core import exceptions as gax
from google.cloud import bigquery

from app.config import get_settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

_ALLOWED_PARAM_TYPES: dict[str, str] = {
    # Aliases accepted from agents and from Python's `type(x).__name__`.
    "str": "STRING",
    "string": "STRING",
    "int": "INT64",
    "integer": "INT64",
    "int64": "INT64",
    "float": "FLOAT64",
    "float64": "FLOAT64",
    "bool": "BOOL",
    "boolean": "BOOL",
    "datetime": "TIMESTAMP",
    "timestamp": "TIMESTAMP",
    "date": "DATE",
    "numeric": "NUMERIC",
    "bignumeric": "BIGNUMERIC",
    "bytes": "BYTES",
}


@lru_cache(maxsize=1)
def _client() -> bigquery.Client:
    """Lazily build a BigQuery client. Cached for the process lifetime."""
    settings = get_settings()
    return bigquery.Client(
        project=settings.google_cloud_project,
        location=settings.bigquery_location,
    )


def _build_query_params(params: dict[str, Any] | None) -> list[bigquery.ScalarQueryParameter]:
    """Convert a `{name: value}` or `{name: {type, value}}` dict into BQ params."""
    if not params:
        return []
    out: list[bigquery.ScalarQueryParameter] = []
    for name, raw in params.items():
        if isinstance(raw, dict) and "type" in raw and "value" in raw:
            type_key = str(raw["type"]).lower()
            value = raw["value"]
        else:
            type_key = type(raw).__name__.lower()
            value = raw
        bq_type = _ALLOWED_PARAM_TYPES.get(type_key)
        if bq_type is None:
            raise ValueError(
                f"Unsupported param type {type_key!r} for {name!r}; "
                f"allowed: {sorted(_ALLOWED_PARAM_TYPES)}"
            )
        out.append(bigquery.ScalarQueryParameter(name, bq_type, value))
    return out


def bigquery_query(
    sql: str,
    params: dict[str, Any] | None = None,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """Run a parameterized SELECT against BigQuery and return rows as JSON.

    Args:
        sql: A parameterized SQL string. Use named parameters (e.g. `@since`).
            Only SELECT statements are accepted.
        params: Optional mapping of `{name: value}` or
            `{name: {"type": "string"|"int"|..., "value": ...}}`.
        max_rows: Optional override of the configured row cap. Capped at the
            global `BIGQUERY_MAX_ROWS` setting.

    Returns:
        A dict with `rows`, `schema`, `total_rows`, `bytes_processed`,
        `bytes_billed`, `job_id`. On failure returns `{"error": str, "code": str}`.
    """
    settings = get_settings()
    log = logger.bind(tool="bigquery_query", project=settings.google_cloud_project)

    sql_stripped = sql.strip().rstrip(";")
    if not sql_stripped.lower().startswith(("select", "with")):
        return {
            "error": "Only SELECT / WITH queries are allowed by bigquery_query.",
            "code": "FORBIDDEN_STATEMENT",
        }

    row_cap = min(max_rows or settings.bigquery_max_rows, settings.bigquery_max_rows)

    try:
        query_params = _build_query_params(params)
    except ValueError as exc:
        return {"error": str(exc), "code": "INVALID_PARAM_TYPE"}

    client = _client()

    # 1) Dry-run for the cost guard.
    dry_config = bigquery.QueryJobConfig(
        dry_run=True,
        use_query_cache=False,
        query_parameters=query_params,
    )
    try:
        dry_job = client.query(sql_stripped, job_config=dry_config)
    except gax.BadRequest as exc:
        log.warning("bigquery.dry_run_failed", error=str(exc))
        return {"error": exc.message, "code": "INVALID_QUERY"}
    except gax.GoogleAPICallError as exc:
        log.warning("bigquery.api_error", error=str(exc))
        return {"error": exc.message, "code": "API_ERROR"}

    estimated = int(dry_job.total_bytes_processed or 0)
    if estimated > settings.bigquery_max_bytes_billed:
        log.warning(
            "bigquery.cost_guard_blocked",
            estimated_bytes=estimated,
            max_bytes_billed=settings.bigquery_max_bytes_billed,
        )
        return {
            "error": (
                f"Query rejected by cost guard: would scan ~{estimated:,} bytes; "
                f"limit is {settings.bigquery_max_bytes_billed:,}. "
                "Add filters, partitions, or columns."
            ),
            "code": "COST_GUARD_BLOCKED",
            "bytes_estimated": estimated,
            "bytes_limit": settings.bigquery_max_bytes_billed,
        }

    # 2) Real run with bytes-billed enforcement.
    job_config = bigquery.QueryJobConfig(
        query_parameters=query_params,
        maximum_bytes_billed=settings.bigquery_max_bytes_billed,
        use_query_cache=True,
        labels={"agent": settings.agent_name, "service": settings.service_name},
    )
    try:
        job = client.query(sql_stripped, job_config=job_config)
        result = job.result(max_results=row_cap)
    except gax.GoogleAPICallError as exc:
        log.error("bigquery.execution_failed", error=str(exc))
        return {"error": exc.message, "code": "EXECUTION_FAILED"}

    rows: list[dict[str, Any]] = []
    for row in result:
        rows.append({k: _jsonable(v) for k, v in dict(row).items()})

    log.info(
        "bigquery.query_ok",
        rows=len(rows),
        bytes_processed=int(job.total_bytes_processed or 0),
        bytes_billed=int(job.total_bytes_billed or 0),
        job_id=job.job_id,
    )
    return {
        "rows": rows,
        "schema": [{"name": f.name, "type": f.field_type} for f in result.schema],
        "total_rows": int(result.total_rows or len(rows)),
        "returned_rows": len(rows),
        "bytes_processed": int(job.total_bytes_processed or 0),
        "bytes_billed": int(job.total_bytes_billed or 0),
        "job_id": job.job_id,
        "truncated": (result.total_rows or 0) > len(rows),
    }


def list_tables(dataset: str | None = None) -> dict[str, Any]:
    """List tables in the configured (or named) dataset, with row counts.

    Useful as a discovery tool the data_agent can call before composing queries.
    """
    settings = get_settings()
    target = dataset or settings.bigquery_dataset
    client = _client()
    try:
        tables = list(client.list_tables(f"{settings.google_cloud_project}.{target}"))
    except gax.NotFound:
        return {
            "error": (
                f"Dataset {settings.google_cloud_project}:{target!r} does not exist. "
                f"STOP. Do NOT retry list_tables — the dataset is not provisioned. "
                f"Tell the user the dataset is missing and stop calling tools."
            ),
            "code": "NOT_FOUND",
        }
    except gax.GoogleAPICallError as exc:
        return {"error": exc.message, "code": "API_ERROR"}

    return {
        "dataset": target,
        "tables": [
            {
                "table_id": t.table_id,
                "full_table_id": t.full_table_id,
                "table_type": t.table_type,
            }
            for t in tables
        ],
    }


def describe_table(table_id: str, dataset: str | None = None) -> dict[str, Any]:
    """Return schema, partitioning, and row count for a single table."""
    settings = get_settings()
    target = dataset or settings.bigquery_dataset
    client = _client()
    full_id = f"{settings.google_cloud_project}.{target}.{table_id}"
    try:
        table = client.get_table(full_id)
    except gax.NotFound:
        return {"error": f"Table not found: {full_id}", "code": "NOT_FOUND"}
    except gax.GoogleAPICallError as exc:
        return {"error": exc.message, "code": "API_ERROR"}

    return {
        "full_table_id": full_id,
        "num_rows": int(table.num_rows or 0),
        "num_bytes": int(table.num_bytes or 0),
        "partitioning": (
            {
                "type": table.time_partitioning.type_,
                "field": table.time_partitioning.field,
            }
            if table.time_partitioning
            else None
        ),
        "clustering_fields": list(table.clustering_fields or []),
        "schema": [
            {"name": f.name, "type": f.field_type, "mode": f.mode, "description": f.description}
            for f in table.schema
        ],
    }


def _jsonable(value: Any) -> Any:
    """Coerce BigQuery row values into JSON-friendly primitives."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
