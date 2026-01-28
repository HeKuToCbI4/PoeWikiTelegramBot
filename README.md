# PoEWikiBot 🛡️🤖

![Tests](https://github.com/yourusername/PoeWikiBot/actions/workflows/tests.yml/badge.svg)

A simple tool to search the [Path of Exile Wiki](https://www.poewiki.net/) from your terminal or Telegram. It uses the Wiki's Cargo query system to find item details quickly.

You can use it as a command-line tool for quick lookups or run it as a Telegram bot with inline search support.

---

## ✨ What it does

- **CLI Search**: Quick item lookups (name, rarity, class) without leaving your terminal.
- **Telegram Bot**: Search for items in any chat using inline queries. Now with "dynamic resolving" — pick an item to see its full stats, mods, and flavour text.
- **Currency Support**: Detailed descriptions for currency items (e.g., Chaos Orb effects).
- **Fast & Async**: Built with Python 3.12, Poetry, and `httpx` for high-performance asynchronous data fetching.
- **Dockerized**: Ready to run in a container.
- **Developer Friendly**: Clean code structure using the `src` layout.

---

## 🛠️ Installation

### Prerequisites
- Python 3.12+
- [Poetry](https://python-poetry.org/docs/#installation)

### Local Setup
1. **Clone the repository**:
   ```bash
   git clone https://github.com/yourusername/PoeWikiBot.git
   cd PoeWikiBot
   ```

2. **Install dependencies**:
   ```bash
   poetry install
   ```

3. **Configure environment**:
   Copy the example environment file and add your Telegram token (if using the bot):
   ```bash
   cp .env.example .env
   ```
   Edit `.env`:
   ```env
   TELEGRAM_BOT_TOKEN=your_secret_token_here
   ```

4. **Generate Cargo Mapping**:
   The bot uses a dynamic mapping of Wiki tables and fields to ensure query accuracy. Generate it before running:
   ```bash
   poetry run python scripts/scrape_cargo.py
   ```

---

## 🚀 How to use it

### Command Line
The fastest way to search for items.

```bash
# Search for items with "Star" in the name
poetry run poewiki search "Star"

# Search with detailed information
poetry run poewiki search "Starforge" --detailed

# Limit results
poetry run poewiki search "Dagger" --limit 5

# See all commands
poetry run poewiki --help
```

### Telegram Bot
Search for items while chatting.

1. **Start it up**:
   ```bash
   poetry run poewiki bot
   ```
2. **Use it**:
   - `/start` to check if it's working.
   - **Inline Search**: Type `@YourBotName <item_name>` in any chat (e.g., `@PoeWikiBot Starforge`).
   - **Dynamic Resolving**: When you select an item from the list, the bot initially sends basic info and then automatically "resolves" it with more details like base stats, mods, and flavour text.

### 🔍 Troubleshooting Dynamic Resolving

If items are not updating after you select them:

1. **Enable Inline Feedback**: 
   - Open [@BotFather](https://t.me/botfather).
   - Select your bot using `/mybots`.
   - Go to **Bot Settings** > **Inline Mode** > **Inline Feedback**.
   - Set it to **100%**.

2. **Check Privacy Mode**:
   - In [@BotFather](https://t.me/botfather), go to **Bot Settings** > **Group Privacy**.
   - Set it to **Disabled**. This ensures the bot can see messages sent "via" it in groups and DMs.

3. **Check for Multiple Instances**: Ensure you don't have another instance of the bot running with the same token. If two instances are polling, they will "steal" updates from each other.

4. **Check Logs**: The bot logs when it receives a "chosen result" event. If you don't see `Chosen inline result received: ...` in your console, Telegram is not sending the feedback.

---

## 🐳 Docker

Run it without worrying about your local Python environment.

### Build
```bash
docker build -t poewikibot .
```

### Run CLI
```bash
docker run --rm poewikibot search "Star"
```

### Run Bot
```bash
# Recommended for production: use --env-file to pass credentials securely
docker run -d --name poewikibot --restart unless-stopped --env-file .env poewikibot
```

### Passing Credentials
To keep your `TELEGRAM_BOT_TOKEN` out of the image and `history`:
1. Create a `.env` file (see [Installation](#local-setup)).
2. Use the `--env-file` flag as shown above.
3. Alternatively, pass individual variables: `docker run -e TELEGRAM_BOT_TOKEN="your_token" poewikibot`.

---

## 🧪 Development

### Tests
We use `pytest`.
```bash
poetry run pytest
```

### File Structure
- `src/poewikibot/`: Main package source.
  - `api.py`: Logic for Cargo queries to the PoE Wiki.
  - `bot.py`: Telegram bot implementation (Handlers & Inline Mode).
  - `cli.py`: Typer CLI definition.
  - `config.py`: Configuration management using Pydantic.
- `tests/`: Automated tests.
- `Dockerfile`: Production-ready multi-stage build.

---

## 📜 License
This project is licensed under the **MIT License**. See the [LICENSE](LICENSE) file for details.

### Disclaimer
This tool is not affiliated with Grinding Gear Games or the Path of Exile Wiki. Data is provided by the [PoE Wiki](https://www.poewiki.net/) under [CC BY-NC-SA 3.0](https://creativecommons.org/licenses/by-nc-sa/3.0/).
