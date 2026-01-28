import httpx
import logging
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from poewikibot.config import settings
from poewikibot.models import get_table_for_class, get_fields_for_table, validate_field

@dataclass
class Item:
    name: str
    rarity: str
    item_class: str
    required_level: Optional[str] = None
    flavour_text: Optional[str] = None
    description: Optional[str] = None
    implicit_mods: Optional[str] = None
    explicit_mods: Optional[str] = None
    image_url: Optional[str] = None
    # Base stats and extra data from supplementary tables
    stats: Dict[str, Any] = field(default_factory=dict)

    # Helper properties for legacy code compatibility
    @property
    def physical_damage_min(self): return self.stats.get("physical_damage_min")
    @property
    def physical_damage_max(self): return self.stats.get("physical_damage_max")
    @property
    def attack_speed(self): return self.stats.get("attack_speed")
    @property
    def critical_strike_chance(self): return self.stats.get("critical_strike_chance")
    @property
    def weapon_range(self): return self.stats.get("weapon_range")
    @property
    def armour(self): return self.stats.get("armour")
    @property
    def evasion(self): return self.stats.get("evasion")
    @property
    def energy_shield(self): return self.stats.get("energy_shield")

async def get_image_urls(file_names: List[str], client: httpx.AsyncClient) -> Dict[str, str]:
    """
    Resolves multiple Wiki file names to their full URLs in a single request.
    """
    if not file_names:
        return {}
    
    # MediaWiki API allows batching up to 50 titles
    # We'll do it in chunks just in case, though usually we only have 10
    results = {}
    for i in range(0, len(file_names), 50):
        chunk = file_names[i:i+50]
        params = {
            "action": "query",
            "titles": "|".join(chunk),
            "prop": "imageinfo",
            "iiprop": "url",
            "format": "json"
        }
        try:
            logging.debug(f"Batch fetching image URLs for {len(chunk)} files")
            response = await client.get(settings.poe_wiki_api_url, params=params)
            response.raise_for_status()
            data = response.json()
            pages = data.get("query", {}).get("pages", {})
            for page_id in pages:
                page = pages[page_id]
                title = page.get("title")
                image_info = page.get("imageinfo", [])
                if image_info and title:
                    url = image_info[0].get("url")
                    results[title] = url
        except Exception as e:
            logging.error(f"Failed to batch fetch image URLs: {e}")
    
    return results

async def get_image_url(file_name: str, client: httpx.AsyncClient) -> Optional[str]:
    """
    Resolves a Wiki file name (e.g. 'File:Starforge inventory icon.png') to its full URL.
    """
    urls = await get_image_urls([file_name], client)
    return urls.get(file_name)

async def get_mods_fallback(item_name: str, client: httpx.AsyncClient) -> Dict[str, List[str]]:
    """
    Fallback method to fetch mods using item_mods and mods tables.
    Useful when the items table returns MWException for mod fields.
    """
    logging.info(f"Using fallback mod fetching for: {item_name}")
    safe_name = item_name.replace("'", "''")
    
    # 1. Get mod IDs and types from item_mods
    params = {
        "action": "cargoquery",
        "tables": "item_mods",
        "fields": "id,is_implicit,is_explicit",
        "where": f"_pageName='{safe_name}'",
        "format": "json"
    }
    
    implicits = []
    explicits = []
    
    try:
        response = await client.get(settings.poe_wiki_api_url, params=params)
        data = response.json()
        raw_mods = data.get("cargoquery", [])
        
        mod_info_map = {} # mod_id -> {is_implicit, is_explicit}
        for rm in raw_mods:
            mod_title = rm["title"]
            mod_id = mod_title.get("id")
            if mod_id:
                mod_info_map[mod_id] = {
                    "is_implicit": mod_title.get("is implicit") == "1",
                    "is_explicit": mod_title.get("is explicit") == "1"
                }

        if not mod_info_map:
            return {"implicit": [], "explicit": []}

        # 2. Get stat_text from mods table (BATCHED)
        mod_ids = list(mod_info_map.keys())
        stat_texts = {} # mod_id -> stat_text
        
        # Batch mods query
        m_where = "id IN ('" + "','".join(mod_ids) + "')"
        m_params = {
            "action": "cargoquery",
            "tables": "mods",
            "fields": "id,stat_text",
            "where": m_where,
            "format": "json"
        }
        m_res = await client.get(settings.poe_wiki_api_url, params=m_params)
        m_data = m_res.json()
        for mq in m_data.get("cargoquery", []):
            m_title = mq["title"]
            m_id = m_title.get("id")
            m_text = m_title.get("stat text")
            if m_id and m_text:
                if "(Hidden)" in m_text:
                    continue
                stat_texts[m_id] = m_text

        # 3. Get values from item_stats to replace placeholders (BATCHED)
        s_where = f"_pageName='{safe_name}' AND mod_id IN ('" + "','".join(mod_ids) + "')"
        s_params = {
            "action": "cargoquery",
            "tables": "item_stats",
            "fields": "mod_id,min,max,avg",
            "where": s_where,
            "format": "json"
        }
        item_stats_map = {} # mod_id -> list of stats
        try:
            s_res = await client.get(settings.poe_wiki_api_url, params=s_params)
            s_data = s_res.json()
            for sq in s_data.get("cargoquery", []):
                s_title = sq["title"]
                s_mod_id = s_title.get("mod id")
                if s_mod_id not in item_stats_map:
                    item_stats_map[s_mod_id] = []
                item_stats_map[s_mod_id].append(s_title)
        except Exception as e:
            logging.warning(f"Failed to batch fetch item_stats: {e}")

        # Assemble mods
        for mod_id, stat_text in stat_texts.items():
            # Replace placeholders with values from item_stats
            if mod_id in item_stats_map:
                for stat in item_stats_map[mod_id]:
                    s_min = stat.get("min")
                    s_max = stat.get("max")
                    if s_min and s_max:
                        if s_min == s_max:
                            stat_text = re.sub(r'\(\d+-\d+\)', s_min, stat_text)
                            stat_text = stat_text.replace('#', s_min)
                        else:
                            stat_text = re.sub(r'\(\d+-\d+\)', f"({s_min}-{s_max})", stat_text)
            
            # Clean up wiki links
            stat_text = re.sub(r'\[\[(?:[^|\]]*\|)?([^\]]+)\]\]', r'\1', stat_text)
            
            info = mod_info_map[mod_id]
            if info["is_implicit"]:
                implicits.append(stat_text)
            elif info["is_explicit"]:
                explicits.append(stat_text)
                        
    except Exception as e:
        logging.error(f"Fallback mod fetching failed for {item_name}: {e}")
        
    return {"implicit": implicits, "explicit": explicits}

async def populate_item_details(item: Item, client: httpx.AsyncClient, include_mods: bool = True) -> Item:
    """
    Populates an existing Item object with detailed data from the Wiki.
    """
    name = item.name
    item_class = item.item_class
    safe_name = name.replace("'", "''")
    logging.info(f"Populating details for item: {name}")

    # 1. Fetch mods if requested
    if include_mods:
        implicit = None
        explicit = None
        for field_to_check in ["implicit_mods", "explicit_mods"]:
            if not validate_field("items", field_to_check):
                continue
                
            for field_name in [field_to_check, field_to_check.replace("_", " ")]:
                s_params = {
                    "action": "cargoquery",
                    "tables": "items",
                    "fields": field_name,
                    "where": f"name='{safe_name}'",
                    "format": "json"
                }
                try:
                    s_res = await client.get(settings.poe_wiki_api_url, params=s_params)
                    s_data = s_res.json()
                    if "error" in s_data:
                        continue
                    
                    cq = s_data.get("cargoquery", [])
                    if cq:
                        val = cq[0]["title"].get(field_name)
                        if field_to_check == "implicit_mods": implicit = val or implicit
                        if field_to_check == "explicit_mods": explicit = val or explicit
                        if val: break
                except Exception as e:
                    logging.warning(f"Failed to fetch {field_name} for {name}: {e}")

        if not implicit or not explicit:
            fallback_mods = await get_mods_fallback(name, client)
            if fallback_mods["implicit"] and not implicit:
                implicit = "<br>".join(fallback_mods["implicit"])
            if fallback_mods["explicit"] and not explicit:
                explicit = "<br>".join(fallback_mods["explicit"])
        
        item.implicit_mods = implicit
        item.explicit_mods = explicit

    # 2. Fetch metadata (required_level, flavour_text, description)
    s_params = {
        "action": "cargoquery",
        "tables": "items",
        "fields": "required_level,flavour_text,description",
        "where": f"name='{safe_name}'",
        "format": "json"
    }
    try:
        s_res = await client.get(settings.poe_wiki_api_url, params=s_params)
        s_data = s_res.json().get("cargoquery", [])
        if s_data:
            s_item = s_data[0]["title"]
            item.required_level = s_item.get("required level") or item.required_level
            item.flavour_text = s_item.get("flavour text") or item.flavour_text
            item.description = s_item.get("description") or item.description
    except Exception as e:
        logging.warning(f"Failed to fetch metadata for {name}: {e}")

    # 3. Fetch supplementary stats
    supplementary_table = get_table_for_class(item_class)
    if supplementary_table:
        all_fields = get_fields_for_table(supplementary_table)
        valid_fields = []
        for f in all_fields:
            if f in ["name", "item_class", "rarity", "implicit_mods", "explicit_mods", "flavour_text"]:
                continue
            if any(sub in f.lower() for sub in ["_min", "_max", "average", "color", "colour"]):
                continue
            if validate_field(supplementary_table, f):
                valid_fields.append(f)
        
        if valid_fields:
            # Batch query all valid fields
            sup_params = {
                "action": "cargoquery",
                "tables": supplementary_table,
                "fields": ",".join(valid_fields),
                "where": f"_pageName='{safe_name}'",
                "format": "json"
            }
            try:
                logging.debug(f"Batch querying {len(valid_fields)} fields from {supplementary_table} for {name}")
                sup_res = await client.get(settings.poe_wiki_api_url, params=sup_params)
                sup_data = sup_res.json()
                sup_items = sup_data.get("cargoquery", [])
                if sup_items:
                    sup_item = sup_items[0]["title"]
                    for f in valid_fields:
                        val = sup_item.get(f.replace("_", " "))
                        if val:
                            normalized_field = f.replace(" ", "_")
                            item.stats[normalized_field] = val
            except Exception as e:
                logging.warning(f"Batch supplementary query failed for {name}: {e}. Falling back to individual queries.")
                for field_to_query in valid_fields:
                    ind_params = {
                        "action": "cargoquery",
                        "tables": supplementary_table,
                        "fields": field_to_query,
                        "where": f"_pageName='{safe_name}'",
                        "format": "json"
                    }
                    try:
                        ind_res = await client.get(settings.poe_wiki_api_url, params=ind_params)
                        ind_data = ind_res.json()
                        ind_items = ind_data.get("cargoquery", [])
                        if ind_items:
                            val = ind_items[0]["title"].get(field_to_query.replace("_", " "))
                            if val:
                                item.stats[field_to_query.replace(" ", "_")] = val
                    except: pass
    
    return item

async def query_items(name_query: str, limit: int = 10, detailed: bool = False, include_mods: bool = True) -> List[Item]:
    """
    Queries the PoE Wiki Cargo database for items matching the name_query.
    """
    async with httpx.AsyncClient() as client:
        params = {
            "action": "cargoquery",
            "tables": "items",
            "fields": "name,rarity,class,inventory_icon",
            "where": f'name LIKE "%{name_query}%"',
            "order by": "drop_enabled DESC, name",
            "limit": limit,
            "format": "json"
        }
        
        logging.info(f"Cargo query params: {params}")
        response = await client.get(settings.poe_wiki_api_url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if "error" in data:
            logging.error(f"Cargo error: {data['error']}")
            return []
        
        raw_results = [item["title"] for item in data.get("cargoquery", [])]
        
        # Batch resolve image URLs
        icon_files = list(set(item.get("inventory icon") for item in raw_results if item.get("inventory icon")))
        image_urls = await get_image_urls(icon_files, client) if icon_files else {}
        
        items = []
        for item_data in raw_results:
            name = item_data.get("name") or "Unknown"
            item = Item(
                name=name,
                rarity=item_data.get("rarity") or "Unknown",
                item_class=item_data.get("class") or "Unknown",
                image_url=image_urls.get(item_data.get("inventory icon"))
            )
            
            if detailed:
                await populate_item_details(item, client, include_mods=include_mods)
            
            items.append(item)
        
        return items

async def get_item_details(name: str, include_mods: bool = True) -> Optional[Item]:
    """
    Fetches full details for a single item.
    Optimized to only perform detailed queries for the target item.
    """
    async with httpx.AsyncClient() as client:
        # 1. Search for the item (undetailed) to find the exact match
        results = await query_items(name, limit=10, detailed=False)
        if not results:
            return None
        
        # 2. Find the best match
        target_item = None
        for item in results:
            if item.name.lower() == name.lower():
                target_item = item
                break
        
        if not target_item:
            for item in results:
                if name.lower() in item.name.lower():
                    target_item = item
                    break
        
        if target_item:
            # 3. Populate details ONLY for the target item
            await populate_item_details(target_item, client, include_mods=include_mods)
            return target_item
            
        return None
