import os
from pathlib import Path
from dotenv import load_dotenv
from solana.rpc.async_api import AsyncClient
try: from .colors import cprint, cinput
except: from colors import cprint, cinput

load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)

REQUIRED_ENV_VARS = [
    "HTTP_RPC_URL",
    "WS_RPC_URL",
    "PRIVATE_KEY",
    "FIRST_BUY_AMOUNT",
    "NEXT_BUY_AMOUNT",
    "GAS",
    "MIN_TARGET_PROFIT",
    "MAX_LOSS",
    "NO_ACTIVITY_IN_SECONDS",
    "MAX_LOSS_FROM_PEAK_PERCENTAGE",
    "MIN_BUYS_THRESHOLD",
]

missing_keys = [key for key in REQUIRED_ENV_VARS if os.getenv(key) is None]

try:
    if missing_keys:
        cprint("Some environment variables are missing. Creating .env file interactively...")
        env_values = {}

        for key in missing_keys:
            value = cinput(f"Enter value for {key}").strip()
            env_values[key] = value

        env_path = Path(".env")
        if not env_path.exists():
            with env_path.open("w") as f:
                for k, v in env_values.items():
                    f.write(f"{k}={v}\n")
        else:
            with env_path.open("a") as f:
                for k, v in env_values.items():
                    f.write(f"{k}={v}\n")

        load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
except Exception as e:
    cprint(f"Error: {e}, make sure the .env file can be found and contains: {', '.join(REQUIRED_ENV_VARS)} fields")
    exit(1)

HTTP_RPC_URL = os.getenv("HTTP_RPC_URL")
WS_RPC_URL = os.getenv("WS_RPC_URL")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
ASYNC_CLIENT = AsyncClient(HTTP_RPC_URL)
FIRST_BUY_AMOUNT = float(os.getenv("FIRST_BUY_AMOUNT") or 0.00001)
NEXT_BUY_AMOUNT = float(os.getenv("NEXT_BUY_AMOUNT") or 0.00001)
GAS = float(os.getenv("GAS") or 0.00001)









