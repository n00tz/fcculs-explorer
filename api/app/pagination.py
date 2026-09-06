"""Small pagination helper shared by browse/list endpoints."""
from fastapi import HTTPException, Query
from pydantic import BaseModel


class PageParams:
    def __init__(
        self,
        page: int = Query(1, ge=1),
        page_size: int = Query(25, ge=1, le=100),
    ):
        self.page = page
        self.page_size = page_size

    @property
    def limit(self) -> int:
        return self.page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class Page(BaseModel):
    items: list
    page: int
    page_size: int
    total: int


def resolve_sort(
    sort: str | None, order: str | None, allowed_columns: dict[str, str], default_column: str
) -> tuple[str, str]:
    """Validate `sort`/`order` query params against an endpoint-specific
    allow-list mapping displayed column names -> real SQL expressions
    (never interpolating the raw query param into SQL), and return the
    real `(sql_expression, "ASC"|"DESC")` to embed in an ORDER BY clause.
    """
    column_key = sort or default_column
    sql_expr = allowed_columns.get(column_key)
    if sql_expr is None:
        raise HTTPException(
            status_code=400, detail=f"sort must be one of {sorted(allowed_columns)}"
        )
    direction = (order or "asc").strip().lower()
    if direction not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="order must be 'asc' or 'desc'")
    return sql_expr, direction.upper()
