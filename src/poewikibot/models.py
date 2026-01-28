import json
import os
import logging
from typing import List, Dict, Optional

# Path to the dynamically generated mapping
MAPPING_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "cargo_mapping.json")

def load_cargo_mapping() -> Dict[str, List[str]]:
    """Loads the Cargo table mapping from the JSON file."""
    if os.path.exists(MAPPING_FILE):
        try:
            with open(MAPPING_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Failed to load cargo mapping: {e}")
    else:
        logging.warning(f"Cargo mapping file not found at {MAPPING_FILE}. Run scripts/scrape_cargo.py to generate it.")
    return {}

CARGO_MAPPING = load_cargo_mapping()

def update_cargo_mapping():
    """Updates the global CARGO_MAPPING by re-loading the file."""
    global CARGO_MAPPING
    CARGO_MAPPING = load_cargo_mapping()

# Mapping of item classes to their respective Cargo tables
CLASS_TO_TABLE = {
    # Weapons
    "One-Handed Axe": "weapons",
    "Two-Handed Axe": "weapons",
    "One-Handed Mace": "weapons",
    "Two-Handed Mace": "weapons",
    "One-Handed Sword": "weapons",
    "Two-Handed Sword": "weapons",
    "Bow": "weapons",
    "Claw": "weapons",
    "Dagger": "weapons",
    "Rune Dagger": "weapons",
    "Staff": "weapons",
    "Warstaff": "weapons",
    "Wand": "weapons",
    "Sceptre": "weapons",
    
    # Armours
    "Body Armour": "armours",
    "Helmet": "armours",
    "Boots": "armours",
    "Gloves": "armours",
    "Shield": "armours",
    
    # Other specific tables if they exist/are needed
    "Skill Gem": "skill_gems",
    "Support Gem": "skill_gems",
    "Map": "maps",
    "Jewel": "jewels",
    "Abyss Jewel": "jewels",
    "Flask": "flasks",
    "Amulet": "amulets",
    "Ring": "items", # Rings usually in items
    "Belt": "items", # Belts usually in items
    "Divination Card": "divination_cards",
    "Skill": "skill",
    "Monster": "monsters",
    "Pantheon": "pantheon",
    "Passive Skill": "passive_skills",
}

# Fields to fetch for each table
def get_table_for_class(item_class: str) -> Optional[str]:
    """Returns the primary supplementary table for a given item class."""
    return CLASS_TO_TABLE.get(item_class)

def get_fields_for_table(table: str) -> List[str]:
    """Returns all available fields for a given table from the cargo mapping."""
    return CARGO_MAPPING.get(table, [])

def validate_field(table: str, field: str) -> bool:
    """Checks if a field exists in a given table according to the cargo mapping."""
    if not CARGO_MAPPING:
        return True # Fallback if mapping is missing
    
    table_fields = CARGO_MAPPING.get(table, [])
    # Cargo allows both spaces and underscores in queries, 
    # but the mapping usually has underscores.
    field_normalized = field.replace(" ", "_")
    return field_normalized in table_fields or field in table_fields
