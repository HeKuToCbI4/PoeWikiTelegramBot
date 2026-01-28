import logging
import html
from urllib.parse import quote
from telegram import Update, InlineQueryResultArticle, InputTextMessageContent, LinkPreviewOptions, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, InlineQueryHandler, ChosenInlineResultHandler, MessageHandler, CallbackQueryHandler, filters
from poewikibot.api import query_items, get_item_details
from poewikibot.config import settings
import uuid

# Enable logging
def setup_logging():
    level_str = settings.log_level.upper()
    level = getattr(logging, level_str, logging.INFO)
    
    # Clear existing handlers
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
        
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=level
    )
    logging.info(f"Logging initialized with level: {level_str}")

setup_logging()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="I'm a PoE Wiki Bot! Use inline mode to search for items."
    )

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query
    logging.info(f"Inline query: {query}")
    if not query:
        return

    try:
        results = await query_items(query, limit=10)
        logging.info(f"Found {len(results)} results for query '{query}'")
    except Exception as e:
        logging.error(f"Error querying items: {e}")
        return
    
    # Deduplicate results by name and class to avoid "Result_id_duplicate" errors
    seen_items = set()
    unique_results = []
    for item in results:
        # Include rarity in the key to ensure we don't deduplicate different rarities of the same name (e.g. Starforge vs Replica)
        item_key = (item.name, item.item_class, item.rarity)
        if item_key not in seen_items:
            seen_items.add(item_key)
            unique_results.append(item)
    
    logging.info(f"Unique results count: {len(unique_results)}")
    
    articles = []
    for i, item in enumerate(unique_results):
        name = item.name
        rarity = item.rarity
        item_class = item.item_class
        # Construct the Wiki URL based on the item name
        wiki_url = f"https://www.poewiki.net/wiki/{quote(name.replace(' ', '_'))}"
        
        description = f"{rarity} {item_class}"
        # Initial content - brief
        # Include a hidden link to the image if available to show it in the preview
        content = ""
        if item.image_url:
            content += f'<a href="{html.escape(item.image_url)}">&#8205;</a>'
        
        content += (
            f"<b><a href=\"{html.escape(wiki_url)}\">{html.escape(name)}</a></b>\n"
            f"<i>{html.escape(item_class)}</i>\n\n"
            f"<b><i>Loading full details...</i></b>"
        )
    
        # Use a random UUID for ID to avoid any potential caching or duplicate issues in Telegram's feedback
        result_id = f"{name}|{uuid.uuid4().hex[:8]}"
        
        articles.append(
            InlineQueryResultArticle(
                id=result_id,
                title=name,
                description=description,
                input_message_content=InputTextMessageContent(
                    content, 
                    parse_mode="HTML",
                    link_preview_options=LinkPreviewOptions(is_disabled=False, show_above_text=True)
                ),
                url=wiki_url,
                thumbnail_url=item.image_url if item.image_url else "https://www.poewiki.net/w/resources/assets/wiki.png",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📖 View on Wiki", url=wiki_url),
                    InlineKeyboardButton("🔄 Load Details", callback_data=f"resolve|{name}")
                ]])
            )
        )

    await update.inline_query.answer(articles, cache_time=0)

async def on_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the 'Load Details' button click.
    Provides a manual fallback if chosen_inline_result is delayed or missing.
    """
    query = update.callback_query
    # Answer immediately to stop loading animation
    await query.answer()
    
    if not query.data or not query.data.startswith("resolve|"):
        return
        
    item_name = query.data.split("|")[1]
    logging.info(f"Manual resolution triggered via CallbackQuery for: {item_name}")
    
    await resolve_item_details(
        item_name, 
        context, 
        inline_message_id=query.inline_message_id,
        chat_id=update.effective_chat.id if update.effective_chat else None,
        message_id=update.effective_message.message_id if update.effective_message else None
    )

async def on_chosen_inline_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the event when a user selects an inline result.
    Updates the sent message with detailed item information.
    """
    logging.info("DEBUG: on_chosen_inline_result handler TRIGGERED")
    print("DEBUG: on_chosen_inline_result handler TRIGGERED")  # Force output to console
    
    # Check if we have the chosen_inline_result object
    chosen_result = update.chosen_inline_result
    if not chosen_result:
        logging.error("DEBUG: Update received by ChosenInlineResultHandler but update.chosen_inline_result is None")
        return
    
    result_id = chosen_result.result_id
    logging.info(f"Chosen inline result received: {result_id}")
    
    # Extract item name from result_id (format: "name|id")
    item_name = result_id.split('|')[0] if '|' in result_id else result_id
    inline_message_id = chosen_result.inline_message_id

    if not inline_message_id:
        logging.warning(f"No inline_message_id found for {item_name}. Automatic resolving will not work without an inline keyboard.")
        # We can't do much without the ID, but let's log everything we have
        logging.debug(f"Full chosen_result dict: {chosen_result.to_dict()}")
        return

    await resolve_item_details(item_name, context, inline_message_id=inline_message_id)

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Fallback handler for when Telegram doesn't send chosen_inline_result.
    Triggered when a message is sent via this bot in a chat the bot can see.
    """
    if not update.message:
        return
        
    via_bot = update.message.via_bot
    if via_bot:
        logging.debug(f"on_message: Message via bot {via_bot.id}. Current bot ID: {context.bot.id}")
        if via_bot.id != context.bot.id:
            return
    else:
        return
    
    text = update.message.text
    if text and "Loading full details..." in text:
        lines = text.split('\n')
        # First line is the item name, potentially with a leading zero-width space
        item_name = lines[0].strip(' \u200d')
        logging.info(f"Fallback resolution triggered via MessageHandler for: {item_name}")
        await resolve_item_details(
            item_name, 
            context, 
            chat_id=update.effective_chat.id, 
            message_id=update.effective_message.message_id
        )

async def resolve_item_details(
    item_name: str, 
    context: ContextTypes.DEFAULT_TYPE, 
    inline_message_id: str = None,
    chat_id: int = None,
    message_id: int = None
):
    """
    Shared logic to resolve item details and update an inline message.
    """
    try:
        msg_ref = inline_message_id or f"{chat_id}:{message_id}"
        logging.info(f"Phase 1: Resolving basic stats for: {item_name} (ref: {msg_ref})")
        # Phase 1: Fetch stats but skip mods for speed and reliability
        item = await get_item_details(item_name, include_mods=False)
        if not item:
            logging.warning(f"Could not find details for item: {item_name}. Attempting final fallback update.")
            try:
                await context.bot.edit_message_text(
                    inline_message_id=inline_message_id,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"<b>{html.escape(item_name)}</b>\n<i>Details could not be resolved.</i>",
                    parse_mode="HTML"
                )
            except Exception as e_final:
                logging.error(f"Final fallback update failed: {e_final}")
            return

        wiki_url = f"https://www.poewiki.net/wiki/{quote(item.name.replace(' ', '_'))}"
        
        def format_content(item_obj, loading_mods=False):
            logging.debug(f"Formatting content for {item_obj.name}, loading_mods={loading_mods}")
            # Build message parts
            parts = []
            
            # Link and title
            parts.append(f"<b><a href=\"{html.escape(wiki_url)}\">{html.escape(item_obj.name)}</a></b>")
            parts.append(f"<i>{html.escape(item_obj.item_class)}</i>")
            
            # Stats (Dynamic)
            stats = []
            
            # Use specific formatting for some common stats if present
            display_stats = item_obj.stats.copy()
            
            # Formatting physical damage
            if "physical_damage_range_text" in display_stats:
                stats.append(f"Physical Damage: {display_stats.pop('physical_damage_range_text')}")
                display_stats.pop("physical_damage_min", None)
                display_stats.pop("physical_damage_max", None)
            elif "physical_damage_min" in display_stats and "physical_damage_max" in display_stats:
                stats.append(f"Physical Damage: {display_stats.pop('physical_damage_min')}-{display_stats.pop('physical_damage_max')}")
            elif "physical_damage" in display_stats:
                stats.append(f"Physical Damage: {display_stats.pop('physical_damage')}")

            # Formatting common properties
            format_map = {
                "critical_strike_chance_range_text": "Critical Strike Chance: {}",
                "critical_strike_chance": "Critical Strike Chance: {}%",
                "attack_speed_range_text": "Attacks per Second: {}",
                "attack_speed": "Attacks per Second: {}",
                "weapon_range_range_text": "Weapon Range: {}",
                "weapon_range": "Weapon Range: {}",
                "armour_range_text": "Armour: {}",
                "armour": "Armour: {}",
                "evasion_range_text": "Evasion Rating: {}",
                "evasion": "Evasion Rating: {}",
                "energy_shield_range_text": "Energy Shield: {}",
                "energy_shield": "Energy Shield: {}",
                "ward_range_text": "Ward: {}",
                "ward": "Ward: {}",
                "map_tier": "Map Tier: {}",
                "gem_tags": "Tags: {}",
                "primary_attribute": "Primary Attribute: {}",
            }

            # Prioritize range text fields and remove redundant numeric fields
            for key, fmt in format_map.items():
                if key in display_stats:
                    val = display_stats.pop(key)
                    # Skip redundant numeric field if range_text was already processed or exists
                    base_key = key.replace("_range_text", "")
                    if "_range_text" in key:
                        # Remove the numeric counterpart if it exists
                        display_stats.pop(base_key, None)
                        # Also remove min/max counterparts
                        display_stats.pop(f"{base_key}_min", None)
                        display_stats.pop(f"{base_key}_max", None)

                    if key == "critical_strike_chance" and not key.endswith("_range_text"):
                        try:
                            val = f"{float(val):.2f}"
                        except: pass
                    stats.append(fmt.format(html.escape(str(val))))

            if item_obj.required_level:
                stats.append(f"Requires Level {html.escape(str(item_obj.required_level))}")
            
            # Add any remaining non-null stats that aren't internal or already handled
            for key, val in display_stats.items():
                if val and val != "0" and not key.startswith("_") and "html" not in key:
                    # Clean up key name (e.g. physical_damage_range_text -> Physical Damage)
                    label = key.replace("_range_text", "").replace("_", " ").title()
                    stats.append(f"{html.escape(label)}: {html.escape(str(val))}")

            if stats:
                parts.append("\n".join(stats))
            
            # Mods
            if item_obj.implicit_mods:
                mods = html.escape(item_obj.implicit_mods).replace('&lt;br&gt;', '\n').replace('&lt;br/&gt;', '\n')
                parts.append(f"{mods}")

            if item_obj.explicit_mods:
                mods = html.escape(item_obj.explicit_mods).replace('&lt;br&gt;', '\n').replace('&lt;br/&gt;', '\n')
                parts.append(f"{mods}")
            
            if loading_mods:
                parts.append("<b><i>Loading mods...</i></b>")

            # Description (for currency items, etc.)
            if item_obj.description:
                parts.append(f"{html.escape(item_obj.description)}")

            # Flavour text
            if item_obj.flavour_text:
                parts.append(f"<i>{html.escape(item_obj.flavour_text)}</i>")

            # Hidden image link for preview
            image_part = ""
            if item_obj.image_url:
                image_part = f'<a href="{html.escape(item_obj.image_url)}">&#8205;</a>'

            return image_part + "\n\n".join(parts)

        # Initial update with basic stats
        content = format_content(item, loading_mods=True)
        logging.info(f"Phase 1: Content generated for {item_name}, length: {len(content)}")
        
        # Ensure we don't exceed Telegram's message limit (4096 chars)
        if len(content) > 4000:
            logging.warning(f"Truncating Phase 1 content for {item_name} (length: {len(content)})")
            content = content[:4000] + "..."
        
        # Use the wiki_url for the button to keep dynamic resolution working
        reply_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("📖 View on Wiki", url=wiki_url)
        ]])

        try:
            logging.info(f"Phase 1: Editing message {msg_ref} for {item_name}")
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                chat_id=chat_id,
                message_id=message_id,
                text=content,
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=False, show_above_text=True),
                reply_markup=reply_markup
            )
            logging.info(f"Phase 1 update successful for {item_name}")
        except Exception as e:
            if "Message is not modified" in str(e):
                logging.info(f"Phase 1: Message already matches for {item_name}")
            else:
                logging.error(f"Failed to edit message in Phase 1 for {item_name}: {e}")
                # Retrying with plain text if HTML fails even in Phase 1
                try:
                    logging.info(f"Retrying Phase 1 with plain text for {item_name}")
                    await context.bot.edit_message_text(
                        inline_message_id=inline_message_id,
                        chat_id=chat_id,
                        message_id=message_id,
                        text=f"{item_name}\n{item.item_class}\n\n(Formatting error, retrying...)\n\nLoading mods...",
                        parse_mode=None,
                        reply_markup=reply_markup
                    )
                except Exception as e2:
                    logging.error(f"Plain text fallback failed in Phase 1: {e2}")

        # Phase 2: Fetch mods
        logging.info(f"Phase 2: Resolving mods for: {item_name}")
        full_item = await get_item_details(item_name, include_mods=True)
        if full_item:
            logging.debug(f"Phase 2: Found full details for {item_name}")
            content = format_content(full_item, loading_mods=False)
            logging.debug(f"Phase 2 content length: {len(content)}")
            if len(content) > 4000:
                logging.warning(f"Truncating Phase 2 content for {item_name} (length: {len(content)})")
                content = content[:4000] + "..."
            
            try:
                logging.info(f"Phase 2: Editing message {msg_ref} for {item_name}")
                await context.bot.edit_message_text(
                    inline_message_id=inline_message_id,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=content,
                    parse_mode="HTML",
                    link_preview_options=LinkPreviewOptions(is_disabled=False, show_above_text=True),
                    reply_markup=reply_markup # Keep the View on Wiki button
                )
                logging.info(f"Successfully resolved full details for {item_name}")
            except Exception as e:
                if "Message is not modified" in str(e):
                    logging.info(f"Phase 2: Message already matches for {item_name}")
                else:
                    logging.error(f"Failed to edit message in Phase 2 for {item_name}: {e}")
                    # Fallback: try plain text if Phase 2 fails due to HTML
                    if "can't parse" in str(e).lower() or "entities" in str(e).lower() or "bad request" in str(e).lower():
                        logging.info(f"Retrying Phase 2 with plain text for {item_name}")
                        # Simple stripping of HTML tags
                        import re
                        plain_content = re.sub('<[^<]+?>', '', content)
                        if "&#8205;" in content: # If we had a hidden link, it's already mostly stripped by above, but let's be sure
                             # hidden link is <a href='...'>&#8205;</a>
                             # stripping tags leaves just &#8205; and the rest of text
                             plain_content = plain_content.replace("&#8205;", "")
                        
                        try:
                            await context.bot.edit_message_text(
                                inline_message_id=inline_message_id,
                                chat_id=chat_id,
                                message_id=message_id,
                                text=plain_content[:4000],
                                parse_mode=None,
                                reply_markup=reply_markup
                            )
                            logging.info(f"Phase 2 plain text fallback successful for {item_name}")
                        except Exception as e3:
                            logging.error(f"Phase 2 plain text fallback failed for {item_name}: {e3}")
        else:
            logging.warning(f"Phase 2: get_item_details returned None for {item_name}")
    except Exception as e:
        logging.error(f"Error in resolving details for {item_name}: {e}", exc_info=True)
        # Final fallback to clear "Loading" if everything crashed
        try:
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                chat_id=chat_id,
                message_id=message_id,
                text=f"<b>{html.escape(item_name)}</b>\n(Error loading full details)",
                parse_mode="HTML"
            )
        except:
            pass

def run_bot():
    if not settings.telegram_bot_token:
        print("Error: TELEGRAM_BOT_TOKEN is not set in environment or .env file.")
        return

    application = ApplicationBuilder().token(settings.telegram_bot_token).build()
    
    # Register a global update logger to see ALL updates
    async def log_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
        update_dict = update.to_dict()
        update_type = next((k for k in update_dict.keys() if k != 'update_id'), 'unknown')
        logging.info(f"RECEIVED UPDATE: type={update_type}, content={update_dict}")
    
    # Logger in group -1 to process before handlers in group 0
    from telegram.ext import TypeHandler
    application.add_handler(TypeHandler(Update, log_update), group=-1)
    
    # Handlers in group 0
    application.add_handler(CommandHandler('start', start))
    application.add_handler(InlineQueryHandler(inline_query))
    application.add_handler(ChosenInlineResultHandler(on_chosen_inline_result))
    application.add_handler(CallbackQueryHandler(on_callback_query))
    application.add_handler(MessageHandler(filters.TEXT & filters.VIA_BOT, on_message))

    print("Bot is starting...")
    application.run_polling(allowed_updates=["message", "inline_query", "chosen_inline_result", "callback_query"])
