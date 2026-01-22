"""Knowledge module for document understanding and information extraction."""

from .document_reader import (
    DocumentReader,
    get_document_reader,
    read_document,
)

__all__ = [
    'DocumentReader',
    'get_document_reader', 
    'read_document',
]
