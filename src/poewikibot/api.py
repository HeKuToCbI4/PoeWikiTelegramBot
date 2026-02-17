import httpx
import logging
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from poewikibot.config import settings
from poewikibot.models import get_table_for_class, get_fields_for_table, validate_field

def dehtmlize(text: Optional[str]) -> Optional[str]:
    """
    Strips HTML tags and unescapes HTML entities.
    Example: '&quot;They said...&quot; - Klopek' -> '"They said..." - Klopek'
             'The wolf greeted the king,<br>In the light' -> 'The wolf greeted the king,\nIn the light'
    """
    if not text:
        return text
    
    # Replace common breaks with newlines before stripping other tags
    text = re.sub(r'<(br|BR)\s*/?>', '\n', text)
    
    # Strip all other HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Unescape HTML entities (e.g. &quot; -> ")
    import html
    text = html.unescape(text)
    
    return text.strip()

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
        
        item.implicit_mods = dehtmlize(implicit)
        item.explicit_mods = dehtmlize(explicit)

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
            item.flavour_text = dehtmlize(s_item.get("flavour text")) or item.flavour_text
            item.description = dehtmlize(s_item.get("description")) or item.description
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
                            item.stats[normalized_field] = dehtmlize(str(val)) if isinstance(val, str) else val
                    # Passive-specific enrichment: set description/icon if missing
                    if supplementary_table == "passive_skills":
                        # Prefer stat_text, then flavour_text, then reminder_text
                        desc_candidates = [
                            sup_item.get("stat text"),
                            sup_item.get("flavour text"),
                            sup_item.get("reminder text"),
                        ]
                        for dc in desc_candidates:
                            if dc:
                                item.description = dehtmlize(str(dc))
                                break
                        if not item.flavour_text and sup_item.get("flavour text"):
                            item.flavour_text = dehtmlize(str(sup_item.get("flavour text")))
                        if not item.image_url:
                            icon_val = sup_item.get("icon") or sup_item.get("inventory icon")
                            if icon_val:
                                icon_str = str(icon_val)
                                if icon_str.startswith("http://") or icon_str.startswith("https://"):
                                    item.image_url = icon_str
                                else:
                                    # Try resolving as File: title (use basename if needed)
                                    icon_title = icon_str if icon_str.startswith("File:") else None
                                    if not icon_title:
                                        import os
                                        base = os.path.basename(icon_str)
                                        if base:
                                            icon_title = f"File:{base}"
                                    if icon_title:
                                        try:
                                            resolved = await get_image_url(icon_title, client)
                                            if resolved:
                                                item.image_url = resolved
                                        except Exception as _:
                                            pass
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
                                item.stats[field_to_query.replace(" ", "_")] = dehtmlize(str(val)) if isinstance(val, str) else val
                    except: pass
    
    return item

async def query_items(name_query: str, limit: int = 10, detailed: bool = False, include_mods: bool = True) -> List[Item]:
    """
    Queries the PoE Wiki Cargo database for items matching the name_query.
    Uses per-table configurations with correct fields and joins to avoid MWExceptions.
    """
    # Table-specific configurations
    # Each config provides: tables (with optional aliases/joins), fields, where (uses table-qualified fields),
    # and a default class to use when the result lacks a class field
    table_configs = [
        {
            "key": "items",
            "tables": "items",
            "fields": "name,rarity,class,inventory_icon",
            "where": "name LIKE \"%{q}%\"",
            "order by": "drop_enabled DESC, name",
            "default_class": None,
        },
        {
            "key": "skill",
            "tables": "skill",
            # Alias fields so downstream expects standard names
            "fields": "active_skill_name=name,skill_icon=inventory_icon",
            "where": "active_skill_name LIKE \"%{q}%\"",
            "default_class": "Skill",
        },
        {
            "key": "passive_skills",
            "tables": "passive_skills",
            "fields": "name,icon=inventory_icon,stat_text,flavour_text,reminder_text",
            "where": "name LIKE \"%{q}%\"",
            "default_class": "Passive Skill",
        },
        {
            "key": "atlas_nodes",
            # Join areas to fetch area name for user-facing search/display
            "tables": "atlas_nodes=an,areas=a",
            "join on": "an.area_id=a.id",
            "fields": "a.name=name",
            "where": "a.name LIKE \"%{q}%\"",
            "default_class": "Atlas Node",
        },
        {
            "key": "ascendancy_classes",
            "tables": "ascendancy_classes",
            "fields": "name",
            "where": "name LIKE \"%{q}%\"",
            "default_class": "Ascendancy Class",
        },
        {
            "key": "main_pages",
            "tables": "main_pages",
            "fields": "name",
            "where": "name LIKE \"%{q}%\"",
            "default_class": "Main Page",
        },
        {
            "key": "mastery_groups",
            "tables": "mastery_groups",
            "fields": "name,icon=inventory_icon",
            "where": "name LIKE \"%{q}%\"",
            "default_class": "Mastery Group",
        },
        {
            "key": "mastery_effects",
            "tables": "mastery_effects",
            "fields": "stat_text=name,stat_text",
            "where": "stat_text LIKE \"%{q}%\"",
            "default_class": "Mastery Effect",
        },
        {
            "key": "areas",
            "tables": "areas",
            "fields": "name",
            "where": "name LIKE \"%{q}%\"",
            "default_class": "Area",
        },
        {
            "key": "events",
            "tables": "events",
            "fields": "name",
            "where": "name LIKE \"%{q}%\"",
            "default_class": "Event",
        },
        {
            "key": "monsters",
            "tables": "monsters",
            "fields": "name",
            "where": "name LIKE \"%{q}%\"",
            "default_class": "Monster",
        },
        {
            "key": "pantheon_souls",
            "tables": "pantheon_souls",
            "fields": "name,stat_text",
            "where": "name LIKE \"%{q}%\"",
            "default_class": "Pantheon Soul",
        },
    ]

    async with httpx.AsyncClient() as client:
        all_results: List[tuple[Dict[str, Any], str]] = []
        seen_keys = set()

        for cfg in table_configs:
            if len(all_results) >= limit:
                break

            params = {
                "action": "cargoquery",
                "tables": cfg["tables"],
                "fields": cfg["fields"],
                "where": cfg["where"].format(q=name_query),
                "limit": limit - len(all_results),
                "format": "json",
            }
            if "join on" in cfg:
                params["join on"] = cfg["join on"]
            if "order by" in cfg:
                params["order by"] = cfg["order by"]

            try:
                response = await client.get(settings.poe_wiki_api_url, params=params)
                response.raise_for_status()
                data = response.json()
                if "error" in data:
                    logging.error(f"Cargo error in table {cfg['key']}: {data['error']}")
                    continue
                for res in data.get("cargoquery", []):
                    title = res.get("title", {})
                    nm = title.get("name")
                    if not nm:
                        continue
                    # Keep variants across tables (e.g., Idol vs Passive with same name)
                    dedupe_key = (nm, cfg["key"])  # name + table key
                    if dedupe_key not in seen_keys:
                        all_results.append((title, cfg["key"]))
                        seen_keys.add(dedupe_key)
            except Exception as e:
                logging.error(f"Failed to query table {cfg['key']}: {e}")

        # Batch resolve image URLs (works with aliased inventory_icon where provided)
        raw_icons = []
        for item_data, _ in all_results:
            val = item_data.get("inventory icon") or item_data.get("inventory_icon")
            if val:
                raw_icons.append(val)
        # Separate direct URLs and file titles
        direct_icon_map: Dict[str, str] = {}
        cargo_titles: List[str] = []
        for val in raw_icons:
            if not val:
                continue
            v = str(val)
            if v.startswith("http://") or v.startswith("https://"):
                direct_icon_map[v] = v
            elif v.startswith("File:"):
                cargo_titles.append(v)
            else:
                # Unknown format: attempt as a File: title using the basename
                import os
                basename = os.path.basename(v)
                if basename:
                    cargo_titles.append(f"File:{basename}")
        cargo_titles = list(sorted(set(cargo_titles)))
        image_urls = await get_image_urls(cargo_titles, client) if cargo_titles else {}
        # Build a case-insensitive fallback map to handle title case normalization from MediaWiki
        image_urls_ci = {k.casefold(): v for k, v in image_urls.items()}

        table_default_classes = {
            "items": None,
            "skill": "Skill",
            "passive_skills": "Passive Skill",
            "atlas_nodes": "Atlas Node",
            "ascendancy_classes": "Ascendancy Class",
            "main_pages": "Main Page",
            "mastery_groups": "Mastery Group",
            "mastery_effects": "Mastery Effect",
            "areas": "Area",
            "events": "Event",
            "monsters": "Monster",
            "pantheon_souls": "Pantheon Soul",
        }

        items: List[Item] = []
        for item_data, table_key in all_results:
            name = item_data.get("name") or "Unknown"
            derived_class = item_data.get("class") or table_default_classes.get(table_key) or "Unknown"
            inv_icon_val = item_data.get("inventory icon") or item_data.get("inventory_icon")
            image_url = None
            if inv_icon_val:
                inv_icon_str = str(inv_icon_val)
                image_url = (
                    direct_icon_map.get(inv_icon_str)
                    or image_urls.get(inv_icon_str)
                    or image_urls_ci.get(inv_icon_str.casefold())
                )
                if not image_url and not inv_icon_str.startswith("File:"):
                    # Try lookup by constructed File:basename
                    import os
                    basename = os.path.basename(inv_icon_str)
                    if basename:
                        image_url = image_urls.get(f"File:{basename}") or image_urls_ci.get(f"file:{basename}".casefold())
            item = Item(
                name=name,
                rarity=item_data.get("rarity") or "Normal",
                item_class=derived_class,
                image_url=image_url
            )

            # Enrich non-item entities with description/icon-derived info when available
            # Prefer meaningful text fields as description
            desc_candidates = [
                item_data.get("stat text"),
                item_data.get("flavour text"),
                item_data.get("description"),
                item_data.get("reminder text"),
            ]
            for dc in desc_candidates:
                if dc:
                    item.description = dehtmlize(str(dc))
                    break
            # Preserve flavour text specifically if present
            if item_data.get("flavour text"):
                item.flavour_text = dehtmlize(str(item_data.get("flavour text")))

            if detailed:
                await populate_item_details(item, client, include_mods=include_mods)

            items.append(item)

        return items

async def get_item_details(name: str, include_mods: bool = True, desired_class: Optional[str] = None) -> Optional[Item]:
    """
    Fetches full details for a single item.
    Optimized to only perform detailed queries for the target item.
    If desired_class is provided, prefers results whose item_class matches it.
    """
    async with httpx.AsyncClient() as client:
        # 1. Search for the item (undetailed) to find the exact match
        results = await query_items(name, limit=10, detailed=False)
        if not results:
            return None
        
        # 2. Find the best match
        target_item = None
        # Prefer exact name and matching class first
        if desired_class:
            for item in results:
                if item.name.lower() == name.lower() and item.item_class == desired_class:
                    target_item = item
                    break
        # Fallback: any exact name match
        if not target_item:
            for item in results:
                if item.name.lower() == name.lower():
                    target_item = item
                    break
        # Fallback: partial match with desired class
        if not target_item and desired_class:
            for item in results:
                if name.lower() in item.name.lower() and item.item_class == desired_class:
                    target_item = item
                    break
        # Final fallback: any partial match
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
