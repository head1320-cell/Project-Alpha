"""
Safe SQL Expression Builder
=============================
Converts client alphabet logic like `(A AND B) OR C` into parameterized
SQL WHERE clauses. All filtering happens in PostgreSQL — zero Pandas.

Security layers:
  1. Factor (column name) whitelist — no user-controlled identifiers in SQL
  2. Operator whitelist — only 5 allowed comparison operators
  3. Value bound via SQLAlchemy params (:val_A), no string interpolation
  4. Expression parsed as AST — only labels, AND/OR/NOT, parentheses allowed

Output: (sql_where_clause, params_dict)
"""

import re
import string

from src.screener_models import ALLOWED_FACTORS, TABLE_NAMES

ALLOWED_OPERATORS = {">", ">=", "<", "<=", "=", "==", "!="}
ALLOWED_SORT_DIRECTIONS = {"ASC", "DESC"}


def _normalize_operator(op: str) -> str:
    """Normalize user operator to SQL operator."""
    op = op.strip()
    if op == "==":
        return "="
    return op


def build_condition_clause(
    label: str,
    condition: dict,
    universe: str,
) -> tuple[str, dict]:
    """
    Convert a single labeled condition to a parameterized SQL fragment.

    Input:
        label: "A"
        condition: {"field": "per", "operator": "<", "value": 15}
        universe: "equity" or "ficc"

    Output: ("(per < :val_A)", {"val_A": 15})

    Raises ValueError if field or operator is not in whitelist.
    """
    if universe not in ALLOWED_FACTORS:
        raise ValueError(f"Unknown universe '{universe}'. "
                         f"Allowed: {list(ALLOWED_FACTORS.keys())}")

    field = str(condition.get("field", "")).strip().lower()
    operator = _normalize_operator(str(condition.get("operator", ""))).strip()
    value = condition.get("value")

    # Whitelist: field
    allowed = ALLOWED_FACTORS[universe]
    if field not in allowed:
        raise ValueError(
            f"Field '{field}' not allowed for universe '{universe}'. "
            f"Allowed fields: {sorted(allowed)}"
        )

    # Whitelist: operator
    if operator not in ALLOWED_OPERATORS:
        raise ValueError(
            f"Operator '{operator}' not allowed. "
            f"Allowed: {sorted(ALLOWED_OPERATORS)}"
        )

    # Validate label
    if not re.match(r"^[A-Z]+$", label):
        raise ValueError(f"Invalid label '{label}'. Must be uppercase letters only.")

    # Validate value type
    if not isinstance(value, (int, float)):
        try:
            value = float(value)
        except (ValueError, TypeError):
            raise ValueError(f"Value '{value}' for {label} must be numeric")

    param_name = f"val_{label}"
    # field is whitelisted so safe to interpolate; operator whitelisted likewise
    clause = f"({field} {operator} :{param_name})"
    params = {param_name: value}

    return clause, params


def build_where_expression(
    conditions: dict[str, dict],
    logic_expression: str,
    universe: str,
) -> tuple[str, dict]:
    """
    Build the full WHERE clause from labeled conditions and a logic expression.

    Input:
        conditions: {"A": {"field": "per", "operator": "<", "value": 15},
                     "B": {"field": "roe", "operator": ">", "value": 12}}
        logic_expression: "A AND B"
        universe: "equity"

    Output:
        sql: "((per < :val_A) AND (roe > :val_B))"
        params: {"val_A": 15, "val_B": 12}
    """
    if not conditions:
        raise ValueError("No conditions provided")

    # Build individual clauses and collect params
    label_clauses = {}
    all_params = {}
    for label, cond in conditions.items():
        clause, params = build_condition_clause(label, cond, universe)
        label_clauses[label] = clause
        all_params.update(params)

    # Normalize logic expression
    expr = logic_expression.strip().upper()
    expr = re.sub(r"\bAND\b", " & ", expr)
    expr = re.sub(r"\bOR\b", " | ", expr)
    expr = re.sub(r"\bNOT\b", " ~ ", expr)

    # Validate: only allowed characters
    allowed_chars = set(string.ascii_uppercase + "&|~() \t")
    for ch in expr:
        if ch not in allowed_chars:
            raise ValueError(f"Illegal character in expression: '{ch}'")

    # Validate: only defined labels referenced
    labels_used = set(re.findall(r"[A-Z]+", expr))
    undefined = labels_used - set(conditions.keys())
    if undefined:
        raise ValueError(f"Undefined labels in expression: {undefined}")

    # Validate: parenthesis balance
    depth = 0
    for ch in expr:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("Unmatched closing parenthesis")
    if depth != 0:
        raise ValueError("Unmatched opening parenthesis")

    # Substitute labels with SQL clauses (longest first to avoid prefix conflicts)
    sorted_labels = sorted(labels_used, key=len, reverse=True)
    sql_expr = expr
    for label in sorted_labels:
        # Word boundary regex to avoid matching inside other labels
        pattern = r"\b" + re.escape(label) + r"\b"
        sql_expr = re.sub(pattern, label_clauses[label], sql_expr)

    # Translate logical operators
    sql_expr = sql_expr.replace("&", " AND ")
    sql_expr = sql_expr.replace("|", " OR ")
    sql_expr = sql_expr.replace("~", " NOT ")

    # Collapse whitespace
    sql_expr = re.sub(r"\s+", " ", sql_expr).strip()

    return sql_expr, all_params


def build_screener_sql(
    universe: str,
    conditions: dict[str, dict],
    logic_expression: str,
    sort_by: str | None = None,
    limit: int = 100,
) -> tuple[str, dict]:
    """
    Build the complete SELECT query.

    Returns: (sql_string, params_dict) ready for session.execute(text(sql), params).
    """
    if universe not in TABLE_NAMES:
        raise ValueError(f"Unknown universe '{universe}'")

    table = TABLE_NAMES[universe]
    where_sql, params = build_where_expression(conditions, logic_expression, universe)

    # ORDER BY with whitelist
    order_clause = ""
    if sort_by:
        # Parse "field ASC" or "field" (default ASC)
        parts = sort_by.strip().split()
        sort_field = parts[0].lower()
        sort_dir = parts[1].upper() if len(parts) > 1 else "ASC"

        if sort_field in ALLOWED_FACTORS[universe] and sort_dir in ALLOWED_SORT_DIRECTIONS:
            order_clause = f" ORDER BY {sort_field} {sort_dir} NULLS LAST"

    # LIMIT bounded
    limit = max(1, min(int(limit), 1000))

    sql = f"SELECT * FROM {table} WHERE {where_sql}{order_clause} LIMIT {limit}"
    return sql, params
