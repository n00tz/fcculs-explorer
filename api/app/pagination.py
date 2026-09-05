"""Small pagination helper shared by browse/list endpoints."""
from fastapi import Query
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
