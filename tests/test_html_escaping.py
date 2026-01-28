import pytest
import html
from urllib.parse import quote
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import Update, InlineQuery
from telegram.ext import ContextTypes
from poewikibot.bot import inline_query, resolve_item_details
from poewikibot.api import Item

@pytest.mark.asyncio
async def test_inline_query_html_escaping():
    """Verifies that inline query results have properly escaped HTML and encoded URLs."""
    # Mock update with a query that would return an item with quotes
    update = MagicMock(spec=Update)
    update.inline_query = MagicMock(spec=InlineQuery)
    update.inline_query.query = "Atziri's Promise"
    update.inline_query.answer = AsyncMock()
    
    # Mock API response
    mock_item = Item(
        name="Atziri's Promise",
        rarity="Unique",
        item_class="Flask",
        image_url="https://example.com/Atziri's_Promise.png"
    )
    
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    
    with patch("poewikibot.bot.query_items", return_value=[mock_item]):
        await inline_query(update, context)
        
        # Check if answer was called
        update.inline_query.answer.assert_called_once()
        args, kwargs = update.inline_query.answer.call_args
        results = args[0]
        
        assert len(results) == 1
        article = results[0]
        content = article.input_message_content.message_text
        
        # Verify name is escaped: Atziri's Promise -> Atziri&#x27;s Promise or Atziri&#39;s Promise
        # html.escape by default escapes ' to &#x27; (python 3.12)
        expected_escaped_name = html.escape("Atziri's Promise")
        assert expected_escaped_name in content
        
        # Verify URL is quoted and attributes are double-quoted
        wiki_url = f"https://www.poewiki.net/wiki/{quote('Atziri_s_Promise')}"
        # Wait, name.replace(' ', '_') is done before quote
        # quote("Atziri's_Promise") -> Atziri%27s_Promise
        expected_wiki_url = f"https://www.poewiki.net/wiki/{quote('Atziri\'s_Promise'.replace(' ', '_'))}"
        assert f'href="{html.escape(expected_wiki_url)}"' in content
        
        # Verify image URL is escaped in attribute
        assert f'href="{html.escape(mock_item.image_url)}"' in content

@pytest.mark.asyncio
async def test_resolve_item_details_html_escaping():
    """Verifies that resolved details have properly escaped HTML for items with special characters."""
    item_name = "Atziri's Promise"
    
    # Mock context
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.bot.edit_message_text = AsyncMock()
    
    # Mock API
    mock_item = Item(
        name="Atziri's Promise",
        rarity="Unique",
        item_class="Flask",
        required_level="68",
        flavour_text="Death is but a 'promise' kept.",
        implicit_mods="Gain 10% of Elemental Damage as Extra Chaos Damage during Effect",
        explicit_mods="Gain 15% of Physical Damage as Extra Chaos Damage during Effect",
        image_url="https://example.com/image.png",
        stats={"dummy_stat": "value 'with' quotes"}
    )
    
    with patch("poewikibot.bot.get_item_details", return_value=mock_item):
        await resolve_item_details(item_name, context, inline_message_id="msg123")
        
        # We care about the final Phase 2 call (include_mods=True)
        assert context.bot.edit_message_text.call_count >= 1
        call_args_list = context.bot.edit_message_text.call_args_list
        final_call_kwargs = call_args_list[-1].kwargs
        text = final_call_kwargs["text"]
        
        # Check escaping of all parts
        assert html.escape(mock_item.name) in text
        assert html.escape(mock_item.flavour_text) in text
        assert html.escape("value 'with' quotes") in text
        assert html.escape("Dummy Stat") in text # key is normalized
        
        # Verify attributes use double quotes and are escaped
        wiki_url = f"https://www.poewiki.net/wiki/{quote(mock_item.name.replace(' ', '_'))}"
        assert f'href="{html.escape(wiki_url)}"' in text
        assert f'href="{html.escape(mock_item.image_url)}"' in text

@pytest.mark.asyncio
async def test_html_escaping_with_ampersand():
    """Verifies that ampersands in item names or mods are escaped."""
    item_name = "Black & White"
    
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.bot.edit_message_text = AsyncMock()
    
    mock_item = Item(
        name=item_name,
        rarity="Normal",
        item_class="Currency",
        explicit_mods="10% more damage & speed"
    )
    
    with patch("poewikibot.bot.get_item_details", return_value=mock_item):
        await resolve_item_details(item_name, context, inline_message_id="msg123")
        
        final_text = context.bot.edit_message_text.call_args_list[-1].kwargs["text"]
        
        assert html.escape(item_name) in final_text
        assert "Black &amp; White" in final_text
        assert "damage &amp; speed" in final_text
