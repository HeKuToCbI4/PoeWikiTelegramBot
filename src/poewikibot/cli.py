import typer
import asyncio
from poewikibot.api import query_items
from typing import Optional

app = typer.Typer()

@app.command()
def search(
    name: str = typer.Argument(..., help="Item name to search for"),
    limit: int = typer.Option(10, "--limit", "-l", help="Number of results to return"),
    detailed: bool = typer.Option(False, "--detailed", "-d", help="Show detailed information")
):
    """
    Search for items on Path of Exile Wiki.
    """
    typer.echo(f"Searching for '{name}'...")
    try:
        results = asyncio.run(query_items(name, limit, detailed=detailed))
        if not results:
            typer.echo("No items found.")
            return

        for i, item in enumerate(results, 1):
            details = f"{i}. {item.name} ({item.rarity}) - {item.item_class}"
            if item.required_level:
                details += f" (Level {item.required_level})"
            typer.echo(details)
            if item.flavour_text:
                typer.echo(f"   \"{item.flavour_text}\"")
            
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)

@app.command()
def bot():
    """
    Start the Telegram Bot.
    """
    from poewikibot.bot import run_bot
    run_bot()

if __name__ == "__main__":
    app()
