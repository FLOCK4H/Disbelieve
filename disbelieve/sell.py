try: from .libs import *
except: from libs import *
from solders.keypair import Keypair # type: ignore
import logging, traceback, argparse
import asyncio

class Sell:
    def __init__(self):
        self.privkey = Keypair.from_base58_string(PRIVATE_KEY)
        self.hook = SolHook(self, self.privkey)

    async def sell(self, mint: str, pct: float, fee_sol: float = GAS):
        try:
            sell = await self.hook.meteora_dbc_sell(mint, float(pct), fee_sol)
            return sell
        except Exception as e:
            logging.error(f"Error in sell: {e}")
            traceback.print_exc()
            return None

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mint", type=str)
    parser.add_argument("pct", type=float)
    args = parser.parse_args()

    sell = Sell()
    sell_tx = await sell.sell(args.mint, args.pct)
    cprint(f"{cc.LIGHT_MAGENTA}Waiting for transaction to be confirmed...{cc.RESET}")
    confirmed = await sell.hook.await_confirm_transaction(sell_tx)
    await sell.hook.close()
    if confirmed:
        cprint(f"{cc.LIGHT_GREEN}Sold {args.pct}% of {args.mint} at {sell_tx}.{cc.RESET}")
    else:
        cprint(f"{cc.LIGHT_RED}Failed to sell {args.pct}% of {args.mint} at {sell_tx}.{cc.RESET}")

def run():
    asyncio.run(main())

if __name__ == "__main__":
    asyncio.run(main())