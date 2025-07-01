import os
import traceback
try: from .libs import (
    SolHook,
    BELIEVE, WSOL_MINT,
    cc, cprint, cinput, 
    WS_RPC_URL, HTTP_RPC_URL, PRIVATE_KEY, 
    ASYNC_CLIENT, 
    GAS,
    FIRST_BUY_AMOUNT,
    NEXT_BUY_AMOUNT
)
except: from libs import (
    SolHook,
    BELIEVE, WSOL_MINT,
    cc, cprint, cinput, 
    WS_RPC_URL, HTTP_RPC_URL, PRIVATE_KEY, 
    ASYNC_CLIENT, 
    GAS,
    FIRST_BUY_AMOUNT,
    NEXT_BUY_AMOUNT
)
from solders.keypair import Keypair # type: ignore
from solders.pubkey import Pubkey # type: ignore
import json, asyncio, sys, logging
from collections import defaultdict
import time
import gc

for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

logging.basicConfig(
    level=logging.INFO,
    format=f'%(asctime)s - {cc.AQUA}☆ Disbelieve ☆ {cc.LIGHT_GRAY}┃{cc.RESET} {cc.WHITE}%(message)s{cc.RESET}',
    datefmt='%H:%M:%S',
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True
)

gc.enable()

class Settings:
    def __init__(self):
        self.target_profit = float(os.getenv("TARGET_PROFIT") or 4.00)
        self.max_loss = float(os.getenv("MAX_LOSS") or 0.9)
        self.checkpoint_balance_percentage = float(os.getenv("CHECKPOINT_BALANCE_PERCENTAGE") or 0.5)
        self.no_activity_threshold = int(os.getenv("NO_ACTIVITY_IN_SECONDS") or 10)
        self.max_loss_from_peak = float(os.getenv("MAX_LOSS_FROM_PEAK_PERCENTAGE") or 0.1)
        self.min_buys_threshold = int(os.getenv("MIN_BUYS_THRESHOLD") or 15)
        self.debug_sensitivity = int(os.getenv("DEBUG_SENSITIVITY") or 1)
        self.disable_first_buy = bool(os.getenv("DISABLE_FIRST_BUY") or False)

class Disbelieve:
    def __init__(self):
        self.privkey = Keypair.from_base58_string(PRIVATE_KEY)
        self.pubkey = self.privkey.pubkey()
        self.client = ASYNC_CLIENT
        self.mint_queue = asyncio.Queue()
        self._prices = defaultdict(dict)
        self._open_prices = {}
        self.holdings_state = {}
        self.settings = Settings()
        self.sold = set()
        self.total_balance_sold = defaultdict(int)
        self.considers = defaultdict(dict)

    def is_mint(self, logs):
        c1, c2 = False, False
        try:
            for log in logs:
                if "VaultTransactionExecute" in log:
                    c1 = True
                elif "InitializeMint" in log:
                    c2 = True
            return True if c1 and c2 else False
        except Exception as e:
            return False

    async def monitor_believe(self):
        try:
            while True:
                message, _ = await self.hook.logs.get()
                params = message.get("params", {})
                result = params.get("result", {})
                value = result.get("value", {})
                err = value.get("err", {})
                if err:
                    continue

                is_mint = False
                if value:
                    sig = value.get("signature", "")
                    logs = value.get("logs", [])
                    is_mint = self.is_mint(logs)
                else:
                    continue

                if is_mint:
                    meta = await self.hook.get_swap_tx(sig)
                    post_token_balances = meta.get("postTokenBalances", [])
                    for side in post_token_balances:
                        mint = side.get("mint", "")
                        if mint != str(WSOL_MINT):
                            self.mint_queue.put_nowait(mint)
                            asyncio.create_task(self.subscribe_mint_updates(mint))
                            break

        except Exception as e:
            print(f"Error: {e}")
            traceback.print_exc()

    async def subscribe_mint_updates(self, mint: str | Pubkey):
        """
            We subscribe here to populate 'updates' dictionary.
        """
        state = await self.hook.meteora_dbc.fetch_state(mint)
        dec_base = await self.hook.get_decimals(mint)
        dec_quote = await self.hook.get_decimals(WSOL_MINT)

        await asyncio.gather(
            self.hook.subscribe_state(state, dec_base, dec_quote, mint),
        )

    async def handle_holdings(self, mint, price, peak_price, last_activity_time, just_buy=False):
        try:    
            if mint not in self.holdings_state or just_buy:
                if not self.settings.disable_first_buy and mint not in self.sold or just_buy:
                    if mint not in self.holdings_state:
                        self.holdings_state[mint] = {"state": "bought", "buy_price": 0}
                    if just_buy:
                        await self.hook.meteora_dbc_buy(mint, fee_sol=GAS, buy_amount=NEXT_BUY_AMOUNT)
                    else:
                        await self.hook.meteora_dbc_buy(mint, fee_sol=GAS, buy_amount=FIRST_BUY_AMOUNT)
                    price = self._prices[mint]["price"]
                    if self.holdings_state[mint]["state"] == "bought" and self.holdings_state[mint]["buy_price"] == 0:
                        self.holdings_state[mint]["buy_price"] = price
                    logging.info(f"{cc.LIGHT_CYAN}Bought {mint} at approx. {price:.10f} SOL{cc.RESET}")
                    if just_buy:
                        return
                    
            elif mint in self.holdings_state:
                is_sold = False
                price = self._prices[mint]["price"]
                if price <= peak_price * (1 - self.settings.max_loss_from_peak):
                    if mint not in self.considers or "peak_stabilizer_tick" not in self.considers[mint]:
                        self.considers[mint]["peak_stabilizer_tick"] = 1
                        await asyncio.sleep(1) # wait for the price to stabilize, this doesn't stop other sessions from selling
                        return
                    else:
                        sell_tx = await self.hook.meteora_dbc_sell(mint, 100, fee_sol=GAS)
                        if sell_tx == "migrated":
                            logging.info(f"{cc.LIGHT_WHITE}Pool {mint} is migrated, skipping sell{cc.RESET}")
                            return "migrated"
                        logging.info(f"{cc.LIGHT_GREEN}Sold {mint} due to max loss from peak{cc.RESET}")
                        is_sold = True

                elif price > (self.holdings_state[mint]["buy_price"] * self.settings.target_profit):
                    if mint not in self.total_balance_sold or self.total_balance_sold[mint] < 100:
                        sell_tx = await self.hook.meteora_dbc_sell(mint, self.settings.checkpoint_balance_percentage, fee_sol=GAS)
                        if sell_tx == "migrated":
                            logging.info(f"{cc.LIGHT_WHITE}Pool {mint} is migrated, skipping sell{cc.RESET}")
                            return "migrated"
                        logging.info(f"{cc.LIGHT_GREEN}Sold {mint} due to target profit being reached{cc.RESET}")
                        self.total_balance_sold[mint] += self.settings.checkpoint_balance_percentage
                    else:
                        logging.info(f"Already sold {mint} at {self.total_balance_sold[mint]}%")
                        is_sold = True

                elif price <= (self.holdings_state[mint]["buy_price"] * self.settings.max_loss):
                    sell_tx = await self.hook.meteora_dbc_sell(mint, 100, fee_sol=GAS)
                    if sell_tx == "migrated":
                        logging.info(f"{cc.LIGHT_WHITE}Pool {mint} is migrated, skipping sell{cc.RESET}")
                        return "migrated"
                    logging.info(f"{cc.LIGHT_GREEN}Sold {mint} due to max loss{cc.RESET}")
                    is_sold = True

                elif (time.time() - last_activity_time) >= self.settings.no_activity_threshold:
                    sell_tx = await self.hook.meteora_dbc_sell(mint, 100, fee_sol=GAS)
                    if sell_tx == "migrated":
                        logging.info(f"{cc.LIGHT_WHITE}Pool {mint} is migrated, skipping sell{cc.RESET}")
                        return "migrated"
                    logging.info(f"{cc.LIGHT_GREEN}Sold {mint} due to no activity, last activity time: {time.time() - last_activity_time}{cc.RESET}")
                    is_sold = True

                if is_sold:
                    self.holdings_state.pop(mint)
                    self.sold.add(mint)
                    if mint in self.considers:  
                        self.considers.pop(mint)
                    gc.collect()

        except Exception as e:
            print(f"Error in handle_holdings: {e}")
            traceback.print_exc()

    async def mint_updates_handler(self):
        """
            Update local dictionaries with new price data.
            Open price is static for each believe mint so a more accurate measure is implemented.
            Also, if we buy literally first then a big chunk of the balance is going to be eaten by fees.
        """
        try:
            while True:
                update = await self.hook.updates.get()
                mint = str(update["mint"])
                price = float(update["price"])
                self._prices[mint]["price"] = price
                if self.settings.debug_sensitivity in [1, 2]:
                    logging.info(f"{cc.LIGHT_MAGENTA}Price update: {price:.10f} | Mint: {mint}{cc.RESET}")

                if price > 0 and mint not in self._open_prices:
                    self._open_prices[mint] = price

        except Exception as e:
            print(f"Error in mint_updates_handler: {e}")
            traceback.print_exc()

    async def check_second_buy(self, mint, price, high_price, buys, last_activity_time):
        try:
            open_price = self._open_prices[mint]
            thresh = self.settings.target_profit * 0.05
            if price > open_price * (1 + thresh):
                if buys > self.settings.min_buys_threshold:
                    logging.info(f"{cc.LIGHT_MAGENTA}Buying {mint} due to min buys threshold{cc.RESET}")
                    await self.handle_holdings(mint, price, high_price, last_activity_time, just_buy=True)
                    return True
                else:
                    if self.settings.debug_sensitivity in [1, 2]:
                        if buys > 10:
                            if "buys" not in self.considers[mint]:
                                self.considers[mint]["buys"] = buys
                                logging.info(f"{cc.LIGHT_RED}Not enough buys to buy {mint} yet, {buys} < {self.settings.min_buys_threshold}{cc.RESET}")
            return False
        except Exception as e:
            logging.error(f"Error in react_to_measure: {e}")
            traceback.print_exc()

    async def handle_position(self, mint):
        try:
            if self.settings.debug_sensitivity in [1, 2]:
                logging.info(f"{cc.LIGHT_BLUE}Starting position handler for {mint}{cc.RESET}")
            initialized = False
            price, last_price, low_price, high_price = 0, 0, 0, 0
            buys, sells = 0, 0
            is_buy, has_second_buy = False, False
            last_activity_time = time.time()
            
            while mint not in self.sold:
                if not initialized:
                    if mint not in self._open_prices:
                        await asyncio.sleep(1)
                        continue
                    initialized = True

                if mint in self.sold:
                    break

                price = self._prices[mint]["price"]
                if price != last_price:
                    last_activity_time = time.time()
                    if price > last_price:
                        buys += 1
                        is_buy = True
                    elif price < last_price:
                        sells += 1
                        is_buy = False

                    if price < low_price:
                        low_price = price
                    if price > high_price:
                        high_price = price

                    if is_buy:
                        if self.settings.debug_sensitivity in [1, 2]:
                            logging.info(f"{cc.YELLOW}Price is increasing! {mint}: {price:.10f}{cc.RESET}")
                        if not has_second_buy:
                            has_second_buy = await self.check_second_buy(mint, price, high_price, buys, last_activity_time)
                    else:
                        if self.settings.debug_sensitivity in [1, 2]:
                            logging.info(f"{cc.LIGHT_CYAN}Price is decreasing! {mint}: {price:.10f}{cc.RESET}")

                    last_price = price

                migrated = await self.handle_holdings(mint, price, high_price, last_activity_time)
                if migrated == "migrated":
                    break
                await asyncio.sleep(0.1)
        except Exception as e:
            print(f"Error in handle_position: {e}")
            traceback.print_exc()

    async def mint_queue_processor(self):
        try:
            while True:
                mint = await self.mint_queue.get()
                print("")
                logging.info(f"{cc.LIGHT_GREEN}Mint detected! {mint}{cc.RESET}")
                asyncio.create_task(self.handle_position(mint))

        except Exception as e:
            print(f"Error in mint_queue_processor: {e}")
            traceback.print_exc()

    async def run(self):
        try:
            self.hook = SolHook(self, self.privkey)
            logging.info(f"{cc.MAGENTA}Starting Disbelieve...{cc.RESET}")
            await asyncio.gather(
                self.hook.subscribe(BELIEVE), 
                self.monitor_believe(),
                self.mint_queue_processor(),
                self.mint_updates_handler()
            )
        except asyncio.CancelledError:
            await self.close()
        except KeyboardInterrupt:
            await self.close()
        except Exception as e:
            print(f"Error: {e}")
            traceback.print_exc()

    async def close(self):
        try:
            self.hook.stop_event.set()
            await self.client.close()
            await self.hook.session.close()
            logging.info(f"{cc.RED}Program stopped by user.{cc.RESET}")
            sys.exit(0)
        except Exception as e:
            print(f"Error: {e}")
            traceback.print_exc()
            sys.exit(1)


def run():
    disbelieve = Disbelieve()
    asyncio.run(disbelieve.run())
            
if __name__ == "__main__":
    disbelieve = Disbelieve()
    asyncio.run(disbelieve.run())



