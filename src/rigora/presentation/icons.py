"""Cached Material interface glyphs and separate theme-aware Rigora branding."""

import json

from PySide6.QtCore import QEvent, QFileInfo, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPalette, QPixmap, QRawFont
from PySide6.QtWidgets import (
    QFileIconProvider,
    QLabel,
    QProxyStyle,
    QStyle,
    QStyleFactory,
    QStyleOption,
    QWidget,
)

from rigora.resources import asset_path


class IconProvider:
    """Load bundled Material glyphs and cache theme-aware normal and disabled icons."""

    def __init__(self) -> None:
        """Register the packaged font and keep only codepoints actually present in its glyph set."""
        font_id = QFontDatabase.addApplicationFont(
            str(asset_path("fonts/material-icons/MaterialIconsOutlined.ttf"))
        )
        families = QFontDatabase.applicationFontFamilies(font_id)
        if not families:
            raise RuntimeError("The bundled Material Icons font could not be loaded.")
        self.family = families[0]
        supplied: dict[str, str] = json.loads(
            asset_path("fonts/material-icons/codepoints.json").read_text(encoding="utf-8")
        )
        raw = QRawFont.fromFont(QFont(self.family))
        self.codepoints = {
            name: code for name, code in supplied.items() if raw.supportsCharacter(int(code, 16))
        }
        self.foreground = "#d4d4d4"
        self.disabled = "#646464"
        self.theme = "dark"
        self._cache: dict[tuple[str, str, int], QIcon] = {}
        self._branding: dict[tuple[str, bool], QIcon] = {}

    def branding(self, *, boxed: bool = False) -> QIcon:
        """Reuse one of four packaged brand icons; SVG marks remain sharp at any DPI."""
        key = (self.theme, boxed)
        if key not in self._branding:
            suffix = ".ico" if boxed else "-mark.svg"
            self._branding[key] = QIcon(str(asset_path(f"icons/app/rigora-{self.theme}{suffix}")))
        return self._branding[key]

    def icon(self, name: str, size: int = 20, color: str | None = None) -> QIcon:
        """Render a supported named glyph at high DPI and reuse its cached icon variants."""
        if name not in self.codepoints:
            raise ValueError(f"Unknown Material icon: {name}")
        key = (name, color or self.foreground, size)
        if key not in self._cache:
            icon = QIcon()
            for mode, tone in ((QIcon.Mode.Normal, key[1]), (QIcon.Mode.Disabled, self.disabled)):
                pixmap = QPixmap(size * 2, size * 2)
                pixmap.setDevicePixelRatio(2)
                pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(pixmap)
                font = QFont(self.family)
                font.setPixelSize(size)
                font.setStyleStrategy(QFont.StyleStrategy.NoFontMerging)
                painter.setFont(font)
                painter.setPen(QColor(tone))
                painter.drawText(
                    0,
                    0,
                    size,
                    size,
                    Qt.AlignmentFlag.AlignCenter,
                    chr(int(self.codepoints[name], 16)),
                )
                painter.end()
                icon.addPixmap(pixmap, mode)
            self._cache[key] = icon
        return self._cache[key]


class AppLogo(QLabel):
    """Transparent Rigora mark that follows palette changes in existing windows."""

    def __init__(self, icons: IconProvider, size: int, parent: QWidget | None = None) -> None:
        """Keep shared branding ownership in the provider and display a high-DPI mark."""
        super().__init__(parent)
        self.icons, self.logo_size = icons, size
        self.setAccessibleName("Rigora 2D application icon")
        self.refresh()

    def refresh(self) -> None:
        """Render at twice the display resolution using Qt's cached SVG icon engine."""
        pixmap = self.icons.branding().pixmap(self.logo_size * 2, self.logo_size * 2)
        pixmap.setDevicePixelRatio(2)
        self.setPixmap(pixmap)

    def changeEvent(self, event: QEvent) -> None:
        """Update open About and Welcome marks after the shared palette changes."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "icons"):
            self.refresh()


class MaterialFileIconProvider(QFileIconProvider):
    """Use bundled glyphs for file-browser entries and location shortcuts."""

    def __init__(self, icons: IconProvider) -> None:
        """Retain the shared palette-aware icon provider for filesystem decoration."""
        super().__init__()
        self.icons = icons

    def icon(self, icon_type: QFileIconProvider.IconType | QFileInfo) -> QIcon:
        """Map filesystem metadata to local Material icons without requesting OS thumbnails."""
        if isinstance(icon_type, QFileInfo):
            name = (
                "storage"
                if icon_type.isRoot()
                else "folder"
                if icon_type.isDir()
                else "description"
            )
        else:
            name = {
                QFileIconProvider.IconType.Computer: "computer",
                QFileIconProvider.IconType.Desktop: "desktop_windows",
                QFileIconProvider.IconType.Trashcan: "delete_outline",
                QFileIconProvider.IconType.Network: "storage",
                QFileIconProvider.IconType.Drive: "storage",
                QFileIconProvider.IconType.Folder: "folder",
                QFileIconProvider.IconType.File: "description",
            }[icon_type]
        return self.icons.icon(name)


class MaterialStyle(QProxyStyle):
    """Fusion style adapter supplying Material icons for Qt-generated interface controls."""

    def __init__(self, icons: IconProvider) -> None:
        """Own a Fusion base style and reuse the application's icon provider."""
        super().__init__(QStyleFactory.create("Fusion"))
        self.icons = icons

    def standardIcon(
        self,
        standardIcon: QStyle.StandardPixmap,
        option: QStyleOption | None = None,
        widget: QWidget | None = None,
    ) -> QIcon:
        """Map Qt standard icon requests to the bundled Material glyph set."""
        names = {
            "SP_TitleBarCloseButton": "close",
            "SP_DockWidgetCloseButton": "close",
            "SP_TitleBarMinButton": "minimize",
            "SP_TitleBarMaxButton": "crop_square",
            "SP_TitleBarNormalButton": "filter_none",
            "SP_TitleBarMenuButton": "menu",
            "SP_MessageBoxInformation": "info",
            "SP_MessageBoxWarning": "warning_amber",
            "SP_MessageBoxCritical": "error_outline",
            "SP_MessageBoxQuestion": "help_outline",
            "SP_DirIcon": "folder",
            "SP_DirOpenIcon": "folder_open",
            "SP_FileIcon": "insert_drive_file",
            "SP_DialogOpenButton": "folder_open",
            "SP_DialogSaveButton": "save",
            "SP_DialogCancelButton": "close",
            "SP_DialogOkButton": "check",
            "SP_ArrowBack": "arrow_back",
            "SP_DialogCloseButton": "close",
            "SP_DialogApplyButton": "check",
            "SP_DialogDiscardButton": "delete_outline",
            "SP_DialogResetButton": "restart_alt",
            "SP_ArrowForward": "arrow_forward",
            "SP_ArrowUp": "arrow_upward",
            "SP_ArrowDown": "arrow_downward",
            "SP_FileDialogToParent": "drive_folder_upload",
            "SP_FileDialogNewFolder": "create_new_folder",
            "SP_FileDialogListView": "view_list",
            "SP_FileDialogDetailedView": "view_list",
            "SP_FileDialogBack": "arrow_back",
            "SP_DriveHDIcon": "storage",
            "SP_ComputerIcon": "computer",
            "SP_LineEditClearButton": "close",
            "SP_DirHomeIcon": "home",
            "SP_ToolBarHorizontalExtensionButton": "more_horiz",
            "SP_ToolBarVerticalExtensionButton": "more_vert",
        }
        return self.icons.icon(names.get(standardIcon.name, "insert_drive_file"))

    def drawPrimitive(
        self,
        element: QStyle.PrimitiveElement,
        option: QStyleOption,
        painter: QPainter,
        widget: QWidget | None = None,
    ) -> None:
        """Draw high-contrast Material checkboxes and arrows in either neutral palette."""
        if element == QStyle.PrimitiveElement.PE_IndicatorCheckBox:
            checked = bool(
                option.state & (QStyle.StateFlag.State_On | QStyle.StateFlag.State_NoChange)
            )
            enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
            palette = option.palette
            foreground = palette.color(
                QPalette.ColorRole.Text if enabled else QPalette.ColorRole.PlaceholderText
            )
            background = palette.color(QPalette.ColorRole.Base)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(foreground)
            painter.setBrush(foreground if checked else background)
            painter.drawRoundedRect(option.rect.adjusted(1, 1, -2, -2), 2, 2)
            if checked:
                name = "remove" if option.state & QStyle.StateFlag.State_NoChange else "check"
                self.icons.icon(name, 14, background.name()).paint(
                    painter, option.rect.adjusted(1, 1, -1, -1)
                )
            if option.state & (QStyle.StateFlag.State_HasFocus | QStyle.StateFlag.State_MouseOver):
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(option.rect.adjusted(0, 0, -1, -1), 3, 3)
            painter.restore()
            return
        arrows = {
            QStyle.PrimitiveElement.PE_IndicatorSpinUp: "expand_less",
            QStyle.PrimitiveElement.PE_IndicatorSpinDown: "expand_more",
            QStyle.PrimitiveElement.PE_IndicatorArrowDown: "expand_more",
            QStyle.PrimitiveElement.PE_IndicatorArrowUp: "expand_less",
            QStyle.PrimitiveElement.PE_IndicatorArrowLeft: "chevron_left",
            QStyle.PrimitiveElement.PE_IndicatorArrowRight: "chevron_right",
        }
        if element in arrows:
            mode = (
                QIcon.Mode.Normal
                if option.state & QStyle.StateFlag.State_Enabled
                else QIcon.Mode.Disabled
            )
            pixmap = self.icons.icon(arrows[element], 14).pixmap(QSize(14, 14), mode)
            point = option.rect.center()
            painter.drawPixmap(point.x() - 7, point.y() - 7, pixmap)
        else:
            super().drawPrimitive(element, option, painter, widget)
