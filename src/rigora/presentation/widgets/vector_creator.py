"""Animal entry point to the independent visual Character Creation collection."""

from typing import Any

from rigora.presentation.widgets.character_wizard import CharacterWizard


class VectorCreator(CharacterWizard):
    """Reuse the shared preview, source format and portable creation workflow."""

    def __init__(self, parent: Any, kind: str = "Animals", source_format: str = "SVG") -> None:
        """Open authored animal identities without loading the retired object catalogs."""
        super().__init__(parent, source_format, kind="Animals")
