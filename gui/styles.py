"""Cinematic JARVIS palette and frozen-safe stylesheet loading."""
from pathlib import Path

from config import RESOURCE_DIR

BG_DEEP = "#050A12"
BG_PANEL = "rgba(11, 19, 36, 236)"
BG_PANEL_SOLID = "#0B1324"
CYAN = "#00D1FF"
CYAN_DIM = "#2B718A"
CYAN_GLOW = "#8AECFF"
VIOLET = "#6A5CFF"
BLUE_WHITE = "#E7F4FF"
AMBER = "#F59E0B"
TEXT = "#D9EAF4"
TEXT_DIM = "#7FA2B4"
BORDER = "rgba(0, 209, 255, 105)"
DANGER = "#FF5F57"
SUCCESS = "#22E6A3"


FALLBACK_QSS = f"""
* {{ font-family: 'Segoe UI', sans-serif; color: {TEXT}; outline: none; }}
QMainWindow, QDialog {{ background: {BG_DEEP}; }}
QFrame#hudPanel {{ background: {BG_PANEL}; border: 1px solid {BORDER}; border-radius: 6px; }}
QLabel#panelTitle {{ color: {CYAN}; font: 700 10px 'Consolas'; letter-spacing: 1px; }}
QLabel#panelMarker {{ color: {CYAN_GLOW}; }}
QLabel#dataValue {{ color: {BLUE_WHITE}; font-size: 10px; }}
QPushButton {{ background: rgba(0,209,255,18); border: 1px solid {BORDER}; padding: 6px; border-radius: 5px; }}
QPushButton:hover {{ background: rgba(0,209,255,45); }}
QPushButton#danger {{ color: #FFE0DC; border-color: rgba(255,95,87,150); }}
QLineEdit, QListWidget, QTableWidget, QComboBox {{ background: rgba(5,10,18,220); border: 1px solid rgba(0,209,255,55); }}
"""

# Native Windows Qt can spend minutes re-evaluating the full design canvas
# stylesheet across the mission-control tree.  This runtime variant preserves
# the same visual identity with direct selectors and no universal/descendant
# matching, keeping the real application responsive.
RUNTIME_QSS = f"""
QWidget#windowRoot, QDialog {{
    background-color: {BG_DEEP}; color: {TEXT};
}}
QFrame#topFrame {{
    background: {BG_PANEL_SOLID}; border: 1px solid {BORDER};
    border-bottom-color: {VIOLET}; border-radius: 6px;
}}
QFrame#hudPanel {{
    background: {BG_PANEL}; border: 1px solid {BORDER}; border-radius: 6px;
}}
QWidget#panelBody, QScrollArea#subsystemRail, QScrollArea#dashboardScroll {{
    background: transparent; border: none;
}}
QLabel#title {{ color: {CYAN_GLOW}; font: 700 22px 'Consolas'; }}
QLabel#subtitle, QLabel#statusLabel, QLabel#statusName {{
    color: {TEXT_DIM}; font: 9px 'Consolas';
}}
QLabel#panelTitle {{ color: {CYAN}; font: 700 10px 'Consolas'; }}
QLabel#panelMarker, QLabel#clockDate {{ color: {CYAN_GLOW}; }}
QLabel#dataValue, QLabel#statusValue {{ color: {BLUE_WHITE}; font-size: 10px; }}
QLabel#clockTime {{ color: {BLUE_WHITE}; font: 700 27px 'Consolas'; }}
QLabel#statusChip, QLabel#stateBanner {{
    color: {CYAN_GLOW}; background: rgba(0,209,255,16);
    border: 1px solid {BORDER}; border-radius: 5px; padding: 5px 12px;
    font: 700 10px 'Consolas';
}}
QFrame#statusIndicator {{
    background: rgba(8,16,29,238); border: 1px solid rgba(0,209,255,55);
    border-radius: 5px;
}}
QFrame#statusIndicator[hudState="ready"] {{ border-color: {SUCCESS}; }}
QFrame#statusIndicator[hudState="warning"] {{ border-color: {AMBER}; }}
QFrame#statusIndicator[hudState="critical"] {{ border-color: {DANGER}; }}
QFrame#statusIndicator[hudState="disabled"] {{ border-color: #344556; }}
QLabel#statusDot, QLabel#statusState {{ color: {CYAN}; font: 700 9px 'Consolas'; }}
QPushButton {{
    color: {TEXT}; background: rgba(0,209,255,18);
    border: 1px solid {BORDER}; border-radius: 5px; padding: 6px 9px;
    font: 700 9px 'Consolas';
}}
QPushButton:hover {{ background: rgba(0,209,255,45); border-color: {CYAN_GLOW}; }}
QPushButton:pressed, QPushButton:checked {{ background: rgba(106,92,255,70); }}
QPushButton:disabled {{ color: #536675; border-color: #263744; }}
QPushButton#primary {{ color: #EFFFFF; border-color: {CYAN}; }}
QPushButton#danger {{ color: #FFE0DC; border-color: {DANGER}; }}
QPushButton#navButton:checked {{ color: {CYAN_GLOW}; border-color: {CYAN}; }}
QLineEdit, QListWidget, QTableWidget, QComboBox {{
    color: {TEXT}; background: rgba(5,10,18,235);
    border: 1px solid rgba(0,209,255,70); border-radius: 4px; padding: 5px;
}}
QLineEdit:focus, QListWidget:focus, QTableWidget:focus {{ border-color: {CYAN}; }}
QHeaderView::section {{
    color: {CYAN_GLOW}; background: {BG_PANEL_SOLID};
    border: none; border-bottom: 1px solid {BORDER}; padding: 5px;
}}
QProgressBar {{
    color: {TEXT}; background: #07101D; border: 1px solid {BORDER};
    border-radius: 4px; text-align: center;
}}
QProgressBar::chunk {{ background: {CYAN}; }}
QSplitter::handle {{ background: rgba(0,209,255,28); }}
QToolTip {{ color: {TEXT}; background: {BG_PANEL_SOLID}; border: 1px solid {BORDER}; }}
"""


def _theme_path(name):
    return Path(RESOURCE_DIR) / "gui" / "themes" / name


def theme_stylesheet(reduced_motion=False):
    try:
        base = _theme_path("cinematic.qss").read_text(encoding="utf-8")
    except OSError:
        base = FALLBACK_QSS
    if reduced_motion:
        try:
            base += "\n" + _theme_path("reduced_motion.qss").read_text(encoding="utf-8")
        except OSError:
            pass
    return base


def runtime_theme_stylesheet(reduced_motion=False):
    base = RUNTIME_QSS
    if reduced_motion:
        try:
            base += "\n" + _theme_path("reduced_motion.qss").read_text(encoding="utf-8")
        except OSError:
            pass
    return base


APP_QSS = theme_stylesheet(False)
