import pytest
from poewikibot.api import query_items, get_item_details

@pytest.mark.asyncio
async def test_query_items_structure():
    # This is a basic smoke test that hits the actual API
    # In a real project, you would mock the requests
    results = await query_items("Star of Wraeclast", limit=1)
    assert isinstance(results, list)
    if results:
        assert hasattr(results[0], "name")
        assert hasattr(results[0], "rarity")
        assert hasattr(results[0], "item_class")
        assert hasattr(results[0], "required_level")
        assert hasattr(results[0], "flavour_text")
        assert hasattr(results[0], "image_url")
        assert "Star of Wraeclast" in results[0].name

@pytest.mark.asyncio
async def test_get_item_details():
    item = await get_item_details("Starforge")
    assert item is not None
    assert "Starforge" in item.name
    # Starforge has a required level and flavour text
    assert item.required_level is not None
    assert item.flavour_text is not None
    assert item.image_url is not None
    assert item.image_url.startswith("https://")
