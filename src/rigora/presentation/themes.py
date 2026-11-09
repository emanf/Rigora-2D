"""Neutral charcoal and complete light palettes, including dialogs and popups."""

from functools import lru_cache

from PySide6.QtGui import QBrush, QColor, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication

from rigora.presentation.icons import IconProvider, MaterialStyle
from rigora.resources import asset_path

PALETTES = {
    "dark": {
        "window": "#080808",
        "panel": "#111111",
        "raised": "#222222",
        "canvas": "#111111",
        "text": "#ffffff",
        "muted": "#b8b8b8",
        "border": "#303030",
        "divider": "#242424",
        "hover": "#303030",
        "selected": "#222222",
        "field_selection": "#b8b8b8",
        "field_selection_text": "#080808",
        "disabled": "#777777",
        "checker_a": "#a6a6a6",
        "checker_b": "#bcbcbc",
        "preview_ink": "#303030",
        "grid": "#888888",
    },
    "light": {
        "window": "#ededed",
        "panel": "#f5f5f5",
        "raised": "#ffffff",
        "canvas": "#d2d2d2",
        "text": "#202020",
        "muted": "#606060",
        "border": "#c8c8c8",
        "divider": "#d8d8d8",
        "hover": "#e0e0e0",
        "selected": "#cecece",
        "field_selection": "#505050",
        "field_selection_text": "#ffffff",
        "disabled": "#909090",
        "checker_a": "#e4e4e4",
        "checker_b": "#f4f4f4",
        "preview_ink": "#303030",
        "grid": "#c4c4c4",
    },
}


def palette_colors(palette: QPalette) -> dict[str, str]:
    """Resolve shared surfaces from the live widget palette, including open preview dialogs."""
    return PALETTES[
        "light" if palette.color(QPalette.ColorRole.Window).lightness() >= 128 else "dark"
    ]


@lru_cache(maxsize=16)
def _checker_brush(first: str, second: str, cell: int) -> QBrush:
    """Cache a small reusable tile without including transparency in exported artwork."""
    tile = QPixmap(cell * 2, cell * 2)
    tile.fill(QColor(first))
    painter = QPainter(tile)
    painter.fillRect(cell, 0, cell, cell, QColor(second))
    painter.fillRect(0, cell, cell, cell, QColor(second))
    painter.end()
    return QBrush(tile)


def transparency_brush(palette: QPalette, cell: int = 12) -> QBrush:
    """Use one theme-aware transparency pattern for viewports and artwork thumbnails."""
    colors = palette_colors(palette)
    return _checker_brush(colors["checker_a"], colors["checker_b"], cell)


class ThemeManager:
    """Apply complete neutral palettes and shared widget styling to one Qt application."""

    def __init__(self, application: QApplication, icons: IconProvider) -> None:
        """Install the Material Fusion style and retain the application and icon provider."""
        self.application, self.icons = application, icons
        self.name = "dark"
        application.setStyle(MaterialStyle(icons))

    def apply(self, name: str) -> None:
        """Apply a supported palette to widgets, dialogs, tooltips, and icon colors."""
        self.name = name if name in PALETTES else "dark"
        self.icons.theme = self.name
        self.application.setWindowIcon(self.icons.branding(boxed=True))
        c = PALETTES[self.name]
        self.icons.foreground, self.icons.disabled = c["text"], c["disabled"]
        self.icons._cache.clear()
        palette = QPalette()
        role = QPalette.ColorRole
        for key, value in {
            role.Window: c["window"],
            role.WindowText: c["text"],
            role.Base: c["raised"],
            role.AlternateBase: c["panel"],
            role.ToolTipBase: c["raised"],
            role.ToolTipText: c["text"],
            role.Text: c["text"],
            role.Button: c["panel"],
            role.ButtonText: c["text"],
            role.BrightText: c["text"],
            role.Highlight: c["selected"],
            role.HighlightedText: c["text"],
            role.PlaceholderText: c["muted"],
            role.Link: c["text"],
            role.LinkVisited: c["muted"],
            role.Light: c["border"],
            role.Midlight: c["raised"],
            role.Dark: c["canvas"],
            role.Mid: c["border"],
            role.Shadow: c["canvas"],
        }.items():
            palette.setColor(role(key), QColor(value))
        for key in (role.WindowText, role.Text, role.ButtonText):
            palette.setColor(QPalette.ColorGroup.Disabled, key, QColor(c["disabled"]))
        self.application.setPalette(palette)
        arrow_up = asset_path(f"icons/controls/up-{self.name}.png").as_posix()
        arrow_down = asset_path(f"icons/controls/down-{self.name}.png").as_posix()
        menu_check = asset_path(f"icons/controls/check-{self.name}.png").as_posix()
        self.application.setStyleSheet(f"""
            QWidget {{ font-family: 'Segoe UI', 'Noto Sans', sans-serif; font-size: 12px;
                       color: {c["text"]}; }}
            QMainWindow, QDialog {{ background: {c["window"]}; }}
            QFrame#WindowOutline {{ background: transparent;
                border: 1px solid {c["muted"]}; }}
            QDockWidget {{ font-weight: 600; border: 0; }}
            QDockWidget[floating="true"] {{ border: 1px solid {c["muted"]}; }}
            QDockWidget::title {{ background: {c["panel"]}; padding: 9px 10px;
                                  border-bottom: 1px solid {c["divider"]}; }}
            QToolBar, QStatusBar {{ background: {c["window"]}; }}
            QMenuBar, QMenu {{ background: {c["canvas"]}; }}
            QMenuBar {{ padding: 0; border: 0; }}
            QMenuBar::item {{ padding: 6px 8px; background: {c["canvas"]}; border-radius: 6px; }}
            QMenuBar::item:selected, QMenu::item:selected {{ background: {c["selected"]}; }}
            QMenu {{ padding: 5px; border: 1px solid {c["border"]}; }}
            QMenu::item {{ padding: 7px 34px 7px 10px; }}
            QMenu::indicator {{ width: 16px; height: 16px; border: none;
                background: transparent; subcontrol-origin: padding;
                subcontrol-position: right center; position: absolute; right: 7px; }}
            QMenu::indicator:checked {{ image: url("{menu_check}"); }}
            QMenu::indicator:unchecked {{ image: none; }}
            QMenu::separator {{ height: 1px; background: {c["divider"]}; margin: 4px; }}
            QToolBar {{ spacing: 4px; padding: 8px; border-bottom: 1px solid {c["divider"]}; }}
            QToolBar::separator {{ background: {c["divider"]}; width: 1px; height: 1px;
                margin: 4px; }}
            QToolButton, QPushButton {{ background: transparent; border: 1px solid transparent;
                                      border-radius: 8px; padding: 6px; }}
            QToolButton:hover:enabled, QPushButton:hover:enabled {{ background: {c["hover"]}; }}
            QToolButton:checked, QToolButton:pressed, QPushButton:pressed {{
                background: {c["selected"]};
                                                       border-color: {c["border"]}; }}
            QToolBar QToolButton {{ min-width: 24px; min-height: 24px;
                padding: 8px; border-radius: 12px; border: 0; }}
            QToolBar QToolButton:checked {{ background: {c["selected"]}; }}
            QToolBar QToolButton:checked:hover {{ background: {c["hover"]}; }}
            QToolBar QToolButton:pressed {{ background: {c["selected"]}; }}
            QDockWidget#preview_tools {{ background: {c["panel"]};
                border: 0; border-radius: 0; }}
            QToolBar#toolbox {{ background: transparent; border: 0;
                spacing: 2px; padding: 2px 3px; }}
            QToolBar#toolbox QToolButton {{ min-width: 0; min-height: 0;
                padding: 0; border: 1px solid transparent; border-radius: 6px; }}
            QToolBar#toolbox QToolButton:hover:enabled {{
                background: {c["hover"]}; border-radius: 6px; }}
            QToolBar#toolbox QToolButton:checked,
            QToolBar#toolbox QToolButton:pressed:enabled {{
                background: {c["selected"]}; border-color: {c["border"]}; border-radius: 6px; }}
            QToolBar#toolbox QToolButton:checked:hover:enabled {{ background: {c["hover"]}; }}
            QToolBar#toolbox QToolButton:pressed:enabled {{ background: {c["selected"]}; }}
            QToolBar#toolbox::separator {{ height: 1px; margin: 4px 8px;
                background: {c["divider"]}; }}
            QFrame#main_tools {{ background: {c["window"]};
                border-bottom: 1px solid {c["divider"]}; }}
            QFrame#ToolbarSeparator {{ border: 0;
                background: {c["divider"]}; }}
            QFrame#main_tools QToolButton {{ min-width: 24px; min-height: 24px;
                padding: 6px; border-radius: 6px; }}
            QFrame#main_tools QToolButton#ToolbarGrip {{ min-width: 12px; min-height: 24px;
                padding: 0; border-radius: 4px; }}
            QToolButton:disabled {{ background: transparent; border-color: transparent; }}
            QWidget#TimelineTransport QToolButton {{ padding: 3px; border-radius: 4px; }}
            QToolButton#PanelAction {{ padding: 3px; border-radius: 4px; }}
            QToolButton#TimelineView {{ padding: 4px 24px 4px 8px; }}
            QToolButton#TimelineView::menu-indicator {{ image: url("{arrow_down}");
                subcontrol-origin: padding; subcontrol-position: center right;
                width: 16px; height: 16px; right: 3px; }}
            QPushButton {{ background: {c["raised"]};
                border-color: {c["border"]};
                padding: 7px 12px;
                }}
            QWidget:disabled {{ color: {c["disabled"]}; }}
            QLineEdit, QAbstractSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
                background: {c["raised"]};
                border: 1px solid {c["border"]};
                border-radius: 4px;
                padding: 6px;
                selection-background-color: {c["field_selection"]};
                selection-color: {c["field_selection_text"]};
                }}
            QLineEdit, QAbstractSpinBox, QComboBox {{
                min-height: 19px; padding: 3px 7px; }}
            QLineEdit:focus, QAbstractSpinBox:focus, QComboBox:focus,
            QPlainTextEdit:focus, QTextEdit:focus, QPushButton:focus,
            QToolButton:focus {{ border: 1px solid {c["muted"]}; }}
            QComboBox {{ padding-right: 26px; }}
            QComboBox::drop-down {{ subcontrol-origin: padding;
                subcontrol-position: top right; width: 24px;
                border: 0; background: transparent; }}
            QComboBox::down-arrow {{ image: url("{arrow_down}");
                width: 16px; height: 16px; }}
            QAbstractSpinBox {{ min-height: 16px; padding: 2px 23px 2px 7px;
                qproperty-alignment: 'AlignLeft | AlignVCenter'; }}
            QAbstractSpinBox QLineEdit, QComboBox QLineEdit {{
                background: transparent; border: 0; border-radius: 0;
                min-height: 0; padding: 0; margin: 0; }}
            QSpinBox::up-button, QDoubleSpinBox::up-button {{
                subcontrol-origin: border; subcontrol-position: top right;
                width: 18px; height: 10px; margin-top: 3px; margin-right: 3px;
                border: 0; border-radius: 2px; background: transparent; }}
            QSpinBox::down-button, QDoubleSpinBox::down-button {{
                subcontrol-origin: border; subcontrol-position: bottom right;
                width: 18px; height: 10px; margin-bottom: 3px; margin-right: 3px;
                border: 0; border-radius: 2px; background: transparent; }}
            QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
            QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
                background: {c["hover"]}; }}
            QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
            QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {{
                background: {c["selected"]}; }}
            QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
                image: url("{arrow_up}"); width: 16px; height: 14px; }}
            QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
                image: url("{arrow_down}"); width: 16px; height: 14px; }}
            QWidget#SliderField QSlider::groove:horizontal {{
                height: 4px; border: 0; border-radius: 2px;
                background: {c["border"]}; }}
            QWidget#SliderField QSlider::sub-page:horizontal {{
                background: {c["muted"]}; border-radius: 2px; }}
            QWidget#SliderField QSlider::handle:horizontal {{
                width: 12px; margin: -5px 0; border-radius: 6px;
                border: 1px solid {c["canvas"]}; background: {c["text"]}; }}
            QWidget#SliderField QSlider::handle:horizontal:hover,
            QWidget#SliderField QSlider::handle:horizontal:pressed {{
                border-color: {c["text"]}; background: {c["text"]}; }}
            QWidget#SliderField QSlider::sub-page:horizontal:disabled {{
                background: {c["border"]}; }}
            QWidget#SliderField QSlider::handle:horizontal:disabled {{
                background: {c["disabled"]}; border-color: {c["border"]}; }}
            QCheckBox {{ spacing: 7px; padding: 3px 0; }}
            QCheckBox::indicator {{ width: 17px; height: 17px; }}
            QFrame#SegmentedControl {{ border: 0; background: transparent; }}
            QFrame#SegmentedControl QToolButton {{ padding: 5px 8px;
                border: 1px solid {c["border"]}; border-radius: 0;
                background: {c["raised"]}; color: {c["muted"]}; }}
            QFrame#SegmentedControl QToolButton[segment="first"] {{
                border-top-left-radius: 4px; border-bottom-left-radius: 4px; }}
            QFrame#SegmentedControl QToolButton[segment="last"] {{
                border-top-right-radius: 4px; border-bottom-right-radius: 4px; }}
            QFrame#SegmentedControl QToolButton:checked {{ background: {c["selected"]};
                color: {c["text"]}; border-bottom: 2px solid {c["text"]}; }}
            QFrame#SegmentedControl QToolButton:hover {{ background: {c["hover"]};
                color: {c["text"]}; }}
            QTreeWidget, QListWidget, QScrollArea {{ background: {c["panel"]};
                border: 0;
                outline: none;
                }}
            QTreeWidget::item, QListWidget::item {{ padding: 7px 5px; }}
            QTreeWidget::item:selected, QListWidget::item:selected {{ background: {c["selected"]};
                }}
            QListWidget[cardGrid="true"] {{ background: {c["panel"]};
                border: 1px solid {c["border"]}; }}
            QFrame#CreatorPreviewBar {{ background: {c["panel"]};
                border: 1px solid {c["border"]}; border-radius: 5px; }}
            QFrame#CreatorTransport {{ background: {c["panel"]};
                border: 1px solid {c["muted"]}; border-radius: 18px; }}
            QFrame#CreatorTransport QToolButton {{ border: 0; border-radius: 12px; padding: 6px; }}
            QProgressBar#CreatorProgress {{ border: 0; background: {c["panel"]}; }}
            QProgressBar#CreatorProgress::chunk {{ background: {c["muted"]}; }}
            QPushButton[paintSwatch="true"] {{ border: 1px solid {c["border"]}; padding: 5px; }}
            QFrame#FaceCard {{ background: {c["panel"]};
                border: 1px solid {c["border"]}; border-radius: 8px; }}
            QLabel#FaceHeading {{ font-size: 15px; font-weight: 600; }}
            QLabel#FaceMuted {{ color: {c["muted"]}; }}
            QToolButton[faceChoice="true"] {{ background: {c["raised"]};
                border: 1px solid {c["border"]}; border-radius: 7px; padding: 5px; }}
            QToolButton[faceChoice="true"]:hover {{ background: {c["hover"]};
                border-color: {c["muted"]}; }}
            QToolButton[faceChoice="true"]:checked {{ background: {c["selected"]};
                border: 2px solid {c["text"]}; }}
            QHeaderView::section {{ background: {c["raised"]}; padding: 6px; border: 0;
                                   border-bottom: 1px solid {c["divider"]}; }}
            QTabWidget::pane {{ border: 0; background: {c["panel"]}; }}
            QTabBar::tab {{ background: {c["window"]}; padding: 9px 11px;
                            border-bottom: 2px solid transparent; color: {c["muted"]}; }}
            QTabBar::tab:selected {{ background: {c["panel"]};
                border-bottom-color: {c["text"]};
                color: {c["text"]};
                }}
            QTabBar::tab:hover {{ background: {c["hover"]}; }}
            QStatusBar {{ border-top: 1px solid {c["divider"]}; padding: 1px 6px; }}
            QStatusBar::item {{ border: 0; }}
            QSplitter::handle, QMainWindow::separator {{ background: {c["divider"]}; border: 0;
                width: 1px;
                height: 1px;
                }}
            QSplitter::handle:hover, QMainWindow::separator:hover {{
                background: {c["muted"]}; }}
            QWidget#DockResizeGrip {{ background: transparent; border: 0; }}
            QToolTip {{ background: {c["raised"]};
                color: {c["text"]};
                border: 1px solid {c["border"]};
                padding: 6px;
                }}
            QScrollBar:vertical {{ background: {c["panel"]}; width: 10px; }}
            QScrollBar:horizontal {{ background: {c["panel"]}; height: 10px; }}
            QScrollBar::handle {{ background: {c["border"]};
                border-radius: 3px;
                min-height: 22px;
                min-width: 22px;
                }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
            QFrame#TitleBar {{ background: {c["canvas"]};
                border-bottom: 1px solid {c["divider"]}; }}
            QFrame#TitleBar[panelCaption="true"] {{ background: {c["panel"]}; }}
            QLabel#PanelCaption {{ color: {c["text"]}; font-weight: 600; }}
            QMenuBar#TitleMenus {{ background: {c["canvas"]}; border: 0; padding: 0; }}
            QLabel#Muted {{ color: {c["muted"]}; }}
            QLabel#Eyebrow {{ color: {c["muted"]}; font-size: 10px; font-weight: 600; }}
            QLabel#Brand {{ font-size: 13px; font-weight: 700; letter-spacing: 2px; }}
            QFrame#ViewportHeader {{ background: {c["panel"]};
                border-bottom: 1px solid {c["divider"]};
                }}
            QFrame#StartSidebar {{ background: {c["panel"]};
                border-right: 1px solid {c["divider"]}; }}
            QLabel#StartHeading {{ font-size: 24px; font-weight: 600; }}
            QLabel#StartSectionHeading {{ font-size: 19px; font-weight: 600; }}
            QPushButton[startAction="true"] {{ text-align: left; padding: 8px 14px;
                border-radius: 6px; }}
            QListWidget#StartRecentProjects {{ background: transparent; border: 0; }}
            QListWidget#StartRecentProjects::item {{ background: {c["panel"]};
                border: 1px solid {c["divider"]}; border-radius: 6px; padding: 8px; }}
            QListWidget#StartRecentProjects::item:hover {{ background: {c["hover"]}; }}
            QListWidget#StartRecentProjects::item:selected {{ background: {c["selected"]};
                border-color: {c["muted"]}; }}
            QWidget#AboutBody {{ background: {c["window"]}; }}
            QLabel#AboutName {{ font-size: 24px; font-weight: 600; }}
            QLabel#AboutCreator {{ font-size: 15px; font-weight: 600; }}
            QFrame#AboutContacts {{ background: {c["panel"]};
                border: 1px solid {c["border"]}; border-radius: 8px; }}
            QLabel#AboutLink:focus {{ outline: 1px solid {c["muted"]}; }}
            QFrame#DialogFooter {{ background: {c["panel"]};
                border-top: 1px solid {c["divider"]}; }}
            QFrame#TitleBar QToolButton[windowControl="true"] {{
                border: 0; border-radius: 0; padding: 0; background: transparent; }}
            QFrame#TitleBar QToolButton[windowControl="true"]:hover,
            QFrame#TitleBar QToolButton[nativeHover="true"] {{ background: {c["hover"]}; }}
            QFrame#TitleBar QToolButton[windowControl="true"]:pressed {{
                background: {c["selected"]}; }}
            QFrame#TitleBar QToolButton#WindowClose:hover {{ background: #c42b1c; color: white; }}
            QFrame#TitleBar QToolButton#WindowClose:pressed {{ background: #a82216; color: white; }}
        """)
