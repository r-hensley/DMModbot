# DMModBot

### Cloning the Repo

This repo uses git submodules, so when cloning be sure to use:

```bash
git clone --recurse-submodules
```

### Running the bot

1. Create venv if you don't have it already
   ```bash
   python3 -m venv .venv
   ```
2. Activate
   ```bash
   source ./.venv/bin/activate
   ```
3. Install dependencies

   ```bash
   python3 -m pip install -r requirements.txt
   ```

   (When using the master branch of discord.py, you also need `python -m pip install -U git+https://github.com/Rapptz/discord.py`)

4. Copy the config sample file and fill it in
   ```bash
   cp config.example.py config.py
   ```
5. Run
   ```bash
   python3 Modbot.py
   ```
