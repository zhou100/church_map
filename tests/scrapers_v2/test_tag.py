"""Deterministic name/denomination → language/cultural_background rules."""
from backend.scrapers_v2.tag import detect


def test_korean_church():
    lang, culture = detect("Korean Presbyterian Church", None)
    assert lang == "Korean"
    assert culture == "Korean"


def test_iglesia_spanish():
    lang, culture = detect("Iglesia Bautista Nueva Vida", None)
    assert lang == "Spanish"
    assert culture == "Hispanic/Latino"


def test_chinese_church():
    lang, culture = detect("Chinese Christian Church", None)
    assert lang == "Chinese"
    assert culture == "Chinese"


def test_unmatched_returns_nones():
    lang, culture = detect("First Baptist Church", "Southern Baptist")
    assert lang is None
    assert culture is None


def test_ame_zion_matches():
    lang, culture = detect("AME Zion Church of God", None)
    assert lang == "English"
    assert culture == "African American"
