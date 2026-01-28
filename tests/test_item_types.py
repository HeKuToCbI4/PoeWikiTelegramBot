import pytest
import logging
from poewikibot.api import get_item_details
from poewikibot.models import CLASS_TO_TABLE

# Configure logging to see what's happening
logging.basicConfig(level=logging.DEBUG)

# A representative item for each major category to test field availability
TEST_ITEMS = [
    # Weapons
    ("Starforge", "Two-Handed Sword", ["physical_damage_range_text", "attack_speed"]),
    ("Voidforge", "Two-Handed Sword", ["physical_damage_range_text", "attack_speed"]),
    ("Driftwood Club", "One-Handed Mace", ["physical_damage_range_text", "attack_speed"]),
    ("Quill Rain", "Bow", ["physical_damage_range_text", "attack_speed"]),
    
    # Armours
    ("Tabula Rasa", "Body Armour", ["armour_range_text", "energy_shield_range_text"]),
    ("Goldrim", "Helmet", ["armour_range_text", "evasion_range_text", "energy_shield_range_text"]),
    ("Shavronne's Wrappings", "Body Armour", ["energy_shield_range_text"]),
    ("The Surrender", "Shield", ["armour_range_text"]),
    
    # Accessories (Usually in 'items' table, but we can check if they resolve)
    ("Astramentis", "Amulet", ["required_level"]),
    ("Headhunter", "Belt", ["required_level"]),
]

@pytest.mark.parametrize("item_name, expected_class, expected_fields", TEST_ITEMS)
@pytest.mark.asyncio
async def test_item_fields_resolution(item_name, expected_class, expected_fields):
    """
    Verifies that items of different classes correctly resolve their specific fields.
    This hits the live Wiki API.
    """
    item = await get_item_details(item_name)
    assert item is not None, f"Could not find item: {item_name}"
    assert item.item_class == expected_class, f"Expected class {expected_class}, got {item.item_class}"
    
    # Check if specific fields are populated (not necessarily non-zero, but present)
    # Note: NamedTuple fields are always present, but we want to see if they were fetched.
    # We'll check if at least one of the expected stats is non-None if the item should have it.
    
    any_field_populated = False
    for field in expected_fields:
        if field in item.stats:
            val = item.stats[field]
        else:
            val = getattr(item, field, None)
        logging.info(f"Item: {item_name}, Field: {field}, Value: {val}")
        if val is not None:
            any_field_populated = True
    
    if expected_fields:
        assert any_field_populated, f"No expected fields were populated for {item_name}"

def test_class_mapping_completeness():
    """Ensures our CLASS_TO_TABLE mapping covers common item classes."""
    common_classes = [
        "One-Handed Sword", "Two-Handed Sword", "Bow", "Dagger", "Staff", "Wand",
        "Body Armour", "Helmet", "Boots", "Gloves", "Shield",
        "Amulet", "Ring", "Belt", "Flask", "Jewel"
    ]
    for cls in common_classes:
        assert cls in CLASS_TO_TABLE, f"Missing mapping for class: {cls}"
