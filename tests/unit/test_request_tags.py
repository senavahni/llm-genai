"""LGW-V1-06: validasi header X-Request-Tags."""

import pytest

from app.services.context import MAX_REQUEST_TAGS, parse_request_tags


def test_valid_tags_parsed():
    tags, warnings = parse_request_tags(" job=ing-42 , kind=book,stage=chunk:3,agent=curator ")
    assert tags == {"job": "ing-42", "kind": "book", "stage": "chunk:3", "agent": "curator"}
    assert warnings == []


@pytest.mark.parametrize(
    "raw",
    [
        "job",  # tanpa '='
        "Job=x",  # kunci huruf besar
        "job=",  # nilai kosong
        "user=ana@contoh.id",  # '@' (email/PII) ditolak
        "name=Budi Santoso",  # spasi ditolak
        "usage_estimated=true",  # kunci internal gateway
        "job=" + "x" * 65,
    ],
)
def test_invalid_pair_ignored_with_warning(raw):
    tags, warnings = parse_request_tags(f"{raw},agent=curator")
    assert tags == {"agent": "curator"}
    assert warnings == ["request_tag_invalid"]


def test_more_than_five_pairs_truncated():
    raw = ",".join(f"k{i}=v{i}" for i in range(7))
    tags, warnings = parse_request_tags(raw)
    assert len(tags) == MAX_REQUEST_TAGS and "k6" not in tags
    assert warnings == ["request_tags_truncated"]


def test_empty_header():
    assert parse_request_tags(None) == ({}, [])
    assert parse_request_tags(" , ") == ({}, [])
