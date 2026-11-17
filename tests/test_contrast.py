"""WCAG 2.1 AA contrast check for every text/background pairing in theme.css."""
import re

from app.settings import ROOT

CSS = (ROOT / "app/static/css/theme.css").read_text()
T = {k: v for k, v in re.findall(r"--color-([a-z-]+):\s*(#[0-9a-fA-F]{6})", CSS)}


def lum(hexv):
    r, g, b = (int(hexv[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def ratio(a, b):
    la, lb = sorted((lum(T[a]), lum(T[b])), reverse=True)
    return (la + 0.05) / (lb + 0.05)


TEXT = [("text", "bg"), ("text", "surface"), ("muted", "bg"), ("muted", "surface"), ("accent", "bg"),
        ("accent", "surface"), ("accent-hover", "bg"), ("on-accent", "accent"), ("on-accent", "accent-hover"),
        ("on-danger", "danger"), ("danger", "bg"), ("danger", "danger-bg"), ("success", "bg"),
        ("warn-text", "warn-bg"), ("info-text", "info-bg"), ("accent", "info-bg"), ("danger-bg", "danger-bg"),
        ("info-text", "bg"),
        ("on-navy", "navy"), ("on-navy", "navy-alt"), ("on-navy", "slide-gold"), ("slide-gold-light", "navy"),
        ("slide-gold", "bg"), ("slide-gold", "cream"), ("slide-gold", "lane-auto"), ("navy", "cream"), ("navy", "bg"),
        ("navy", "lane-ai"), ("navy", "slide-gold-light"), ("navy", "lane-auto"), ("text", "lane-auto"), ("muted", "lane-auto"),
        ("navy", "info-bg"), ("accent", "lane-auto"),
        ("navy", "level-low-bg"), ("navy", "level-mid-bg"), ("slide-muted", "level-low-bg"), ("slide-muted", "level-mid-bg"),
        ("on-navy-muted", "navy"), ("on-navy", "navy"), ("slide-gold-light", "navy-alt"), ("navy", "bg")]
NONTEXT = [("border", "bg"), ("focus", "bg"), ("accent", "bg"), ("level-arrow", "bg"), ("level-arrow", "level-mid-bg")]


def test_text_contrast_aa():
    for fg, bg in TEXT:
        if fg == bg:
            continue
        assert ratio(fg, bg) >= 4.5, (fg, bg, ratio(fg, bg))


def test_nontext_contrast_aa():
    for fg, bg in NONTEXT:
        assert ratio(fg, bg) >= 3.0, (fg, bg, ratio(fg, bg))
