"""Card output mode switches independently of an unchanged character and its export data."""

import pytest

from rigora.domain.character_recipe import CharacterRecipe


@pytest.mark.gui
def test_canonical_recipe_can_switch_png_svg_png_without_rebuilding_rig(qtbot, monkeypatch):
    """Equal static/adaptive recipes must not suppress a requested output-mode change."""
    from PySide6.QtWidgets import QWidget

    from rigora.presentation.viewmodels.character_wizard import CharacterWizardModel

    owner = QWidget()
    qtbot.addWidget(owner)
    model = CharacterWizardModel(owner)

    def prepared():
        assert not model.error
        return model.ready == model.recipe and not model.busy and model.cards_current()

    try:
        model.request(CharacterRecipe())
        model.ensure_prepared(immediate=True)
        qtbot.waitUntil(prepared, timeout=30000)
        baseline = model.full_built
        originals = {key: value[1] for key, value in model.option_images.items()}
        assert all(data.startswith(b"\x89PNG") for data in originals.values())

        def unexpected(*args, **kwargs):
            raise AssertionError("Card output mode must reuse the rig and animation")

        monkeypatch.setattr(
            "rigora.presentation.viewmodels.character_wizard.build_character", unexpected
        )
        for adaptive in (True, False):
            model.set_adaptive_cards(adaptive)
            qtbot.waitUntil(prepared, timeout=30000)
            assert model.recipe == CharacterRecipe()
            assert model.full_built is baseline
            prefix = b"<svg" if adaptive else b"\x89PNG"
            assert all(value[1].startswith(prefix) for value in model.option_images.values())
        assert {key: value[1] for key, value in model.option_images.items()} == originals
    finally:
        model.shutdown()
