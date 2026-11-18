"""Audiobook discovery, staging, and metadata lookup."""

from stager_core.discovery import FlatBook, discover_books
from stager_core.staging import BookResult, stage_book_author_title

__all__ = [
    "FlatBook",
    "discover_books",
    "BookResult",
    "stage_book_author_title",
]
