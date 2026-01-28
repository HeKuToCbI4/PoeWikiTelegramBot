import pytest
import logging
from poewikibot.api import get_item_details

# Configure logging
logging.basicConfig(level=logging.DEBUG)

@pytest.mark.asyncio
async def test_currency_description_resolution():
    """
    Verifies that currency items (like Chaos Orb) correctly resolve their description field.
    This hits the live Wiki API.
    """
    currency_items = [
        ("Chaos Orb", "Reforges a rare item with new random modifiers"),
        ("Mirror of Kalandra", "Creates a mirrored copy of an item"),
        ("Exalted Orb", "Augments a rare item with a new random modifier")
    ]
    
    for item_name, expected_text in currency_items:
        item = await get_item_details(item_name)
        assert item is not None, f"Could not find currency: {item_name}"
        assert "Currency" in item.item_class, f"Expected class Currency for {item_name}, got {item.item_class}"
        assert item.description is not None, f"Description is missing for {item_name}"
        assert expected_text.lower() in item.description.lower(), f"Expected text '{expected_text}' not found in description of {item_name}: {item.description}"
        logging.info(f"Verified currency: {item_name}, Description: {item.description}")
