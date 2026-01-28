import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import Update, ChosenInlineResult, User
from telegram.ext import ContextTypes
from poewikibot.bot import on_chosen_inline_result, on_message
from poewikibot.api import Item

@pytest.mark.asyncio
async def test_on_chosen_inline_result_success():
    # Mock update
    update = MagicMock(spec=Update)
    update.chosen_inline_result = MagicMock(spec=ChosenInlineResult)
    update.chosen_inline_result.result_id = "Star of Wraeclast|12345678"
    update.chosen_inline_result.inline_message_id = "msg123"
    
    # Mock context
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.bot.edit_message_text = AsyncMock()
    
    # Mock API
    mock_item = Item(
        name="Star of Wraeclast",
        rarity="Unique",
        item_class="Amulet",
        required_level="28",
        flavour_text="Some flavour",
        implicit_mods="Implicit mod",
        explicit_mods="Explicit mod 1<br>Explicit mod 2",
        image_url="https://example.com/image.png",
        stats={}
    )
    
    with patch("poewikibot.bot.get_item_details", return_value=mock_item) as mock_get_details:
        await on_chosen_inline_result(update, context)
        
        # Now it's called twice (Phase 1 and Phase 2)
        assert mock_get_details.call_count == 2
        mock_get_details.assert_any_call("Star of Wraeclast", include_mods=False)
        mock_get_details.assert_any_call("Star of Wraeclast", include_mods=True)
        
        # Check if edit_message_text was called
        assert context.bot.edit_message_text.call_count >= 1
        
        # Check if the last call has the expected content
        args, kwargs = context.bot.edit_message_text.call_args
        assert kwargs["inline_message_id"] == "msg123"
        assert "Star of Wraeclast" in kwargs["text"]
        assert "Requires Level 28" in kwargs["text"]
        assert "Some flavour" in kwargs["text"]
        assert "Implicit mod" in kwargs["text"]
        assert "Explicit mod 1" in kwargs["text"]
        assert "Explicit mod 2" in kwargs["text"]
        assert "https://example.com/image.png" in kwargs["text"]
        assert kwargs.get("reply_markup") is not None
        assert "View on Wiki" in str(kwargs.get("reply_markup"))

@pytest.mark.asyncio
async def test_on_chosen_inline_result_no_inline_id():
    # Mock update without inline_message_id
    update = MagicMock(spec=Update)
    update.chosen_inline_result = MagicMock(spec=ChosenInlineResult)
    update.chosen_inline_result.result_id = "Star of Wraeclast|12345678"
    update.chosen_inline_result.inline_message_id = None
    
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.bot.edit_message_text = AsyncMock()
    
    await on_chosen_inline_result(update, context)
    
    context.bot.edit_message_text.assert_not_called()

@pytest.mark.asyncio
async def test_on_message_fallback():
    # Mock update
    update = MagicMock(spec=Update)
    update.message = MagicMock()
    update.message.via_bot = MagicMock()
    update.message.via_bot.id = 123
    update.message.text = "\u200dStarforge\nTwo-Handed Sword\n\nLoading full details..."
    update.effective_chat.id = 456
    update.effective_message.message_id = 789
    
    # Mock context
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.bot.id = 123
    context.bot.edit_message_text = AsyncMock()
    
    # Mock API
    mock_item = Item(
        name="Starforge",
        rarity="Unique",
        item_class="Two-Handed Sword",
        stats={}
    )
    
    with patch("poewikibot.bot.get_item_details", return_value=mock_item):
        await on_message(update, context)
        
        # Check if edit_message_text was called with chat_id and message_id
        assert context.bot.edit_message_text.call_count >= 1
        # It should be called twice (Phase 1 and Phase 2)
        
        # Check the calls
        call_args_list = context.bot.edit_message_text.call_args_list
        # Last call should have full details
        kwargs = call_args_list[-1].kwargs
        assert kwargs["chat_id"] == 456
        assert kwargs["message_id"] == 789
        assert "Starforge" in kwargs["text"]
        assert "Loading mods..." not in kwargs["text"]

@pytest.mark.asyncio
async def test_on_callback_query_success():
    # Mock update
    update = MagicMock(spec=Update)
    update.callback_query = MagicMock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.data = "resolve|Starforge"
    update.callback_query.inline_message_id = "inline123"
    update.effective_chat = None
    update.effective_message = None
    
    # Mock context
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.bot.edit_message_text = AsyncMock()
    
    # Mock API
    mock_item = Item(
        name="Starforge",
        rarity="Unique",
        item_class="Two-Handed Sword",
        stats={}
    )
    
    with patch("poewikibot.bot.get_item_details", return_value=mock_item):
        from poewikibot.bot import on_callback_query
        await on_callback_query(update, context)
        
        # Check if answer was called
        update.callback_query.answer.assert_called_once()
        
        # Check if edit_message_text was called with inline_message_id
        assert context.bot.edit_message_text.call_count >= 1
        kwargs = context.bot.edit_message_text.call_args.kwargs
        assert kwargs["inline_message_id"] == "inline123"
        assert "Starforge" in kwargs["text"]
