import base64
import aiohttp
from typing import Optional
import websockets
import json
import asyncio
import logging
import traceback
import time
from solders.keypair import Keypair # type: ignore
from solders.pubkey import Pubkey # type: ignore
from solana.rpc.commitment import Processed, Confirmed

try: from .config import WS_RPC_URL, HTTP_RPC_URL, ASYNC_CLIENT, FIRST_BUY_AMOUNT, NEXT_BUY_AMOUNT, GAS
except: from config import WS_RPC_URL, HTTP_RPC_URL, ASYNC_CLIENT, FIRST_BUY_AMOUNT, NEXT_BUY_AMOUNT, GAS
try: from .colors import cc, cprint, cinput
except: from colors import cc, cprint, cinput
try: from .meteoraDBC import MeteoraDBC
except: from meteoraDBC import MeteoraDBC
try: from .common import WSOL_MINT
except: from common import WSOL_MINT

logging.basicConfig(level=logging.INFO)

suppress_logs = [
    "socks",
    "requests",
    "httpx",    
    "trio.async_generator_errors",
    "trio",
    "trio.abc.Instrument",
    "trio.abc",
    "trio.serve_listeners",
    "httpcore.http11",
    "httpcore",
    "httpcore.connection",
    "httpcore.proxy",
]

for log_name in suppress_logs:
    logging.getLogger(log_name).setLevel(logging.CRITICAL)
    logging.getLogger(log_name).handlers.clear()
    logging.getLogger(log_name).propagate = False

class SolHook:
    def __init__(self, parent, privkey: Keypair):
        self.parent = parent
        self.stop_event = asyncio.Event()
        self.logs = asyncio.Queue()
        self.session = aiohttp.ClientSession()
        self.meteora_dbc = MeteoraDBC(ASYNC_CLIENT, privkey)
        self._dec_cache = {}
        self.updates = asyncio.Queue() # streaming price updates
        self.accounts = set()

    async def get_decimals(self, mint: str | Pubkey):
        mint = mint if isinstance(mint, Pubkey) else Pubkey.from_string(mint)
        if str(mint) == str(WSOL_MINT):
            return 9
        
        if mint in self._dec_cache:
            return self._dec_cache[mint]
        
        mint_info = await ASYNC_CLIENT.get_account_info_json_parsed(
            mint,
            commitment=Processed
        )

        if not mint_info:
            print("Error: Failed to fetch mint info (tried to fetch token decimals).")
            return
        
        dec_base = mint_info.value.data.parsed['info']['decimals']
        self._dec_cache[mint] = dec_base

        return self._dec_cache[mint]

    async def await_confirm_transaction(self, tx_signature: str, max_attempts: int = 20, retry_delay: int = 3) -> Optional[bool]:
        attempt = 1
        while attempt < max_attempts:
            try:
                txn_resp = await ASYNC_CLIENT.get_transaction(
                    tx_signature,
                    encoding="json",
                    commitment=Confirmed,
                    max_supported_transaction_version=0
                )
                txn_meta = json.loads(txn_resp.value.transaction.meta.to_json())
                if txn_meta['err'] is None:
                    return True
                if txn_meta['err']:
                    return False
            except Exception:
                attempt += 1
                await asyncio.sleep(retry_delay)
        logging.info("Max attempts reached. Transaction confirmation failed.")
        return None

    async def subscribe(self, program):
        """
            Subscribe to the Solana network for program logs.
        """
        while not self.stop_event.is_set():
            ws = None
            try:
                time_measure = time.time()
                async with websockets.connect(
                    WS_RPC_URL,
                    ping_interval=2,
                    ping_timeout=15,
                ) as ws:
                    await ws.send(json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "method": "logsSubscribe",
                            "id": 1,
                            "params": [
                                {"mentions": [str(program)]},
                                {"commitment": "processed"}
                            ]
                        }))
                    response = json.loads(await ws.recv())

                    if 'result' in response:
                        time_measure = time.time() - time_measure
                        logging.info(f"{cc.LIGHT_GRAY}Successfully connected to {program} in {time_measure:.10f}s{cc.RESET} ✔")

                    async for message in ws:
                        if self.stop_event.is_set():
                            break
                        hMessage = json.loads(message)
                        await self.logs.put([hMessage, program])

            except websockets.exceptions.ConnectionClosedError:
                logging.error(f"{cc.RED}Connection closed when subscribing to {program}.{cc.RESET}")
                await asyncio.sleep(5)
            except TimeoutError:
                logging.error(f"{cc.RED}TimeoutError when subscribing to {program}.{cc.RESET}")
                await asyncio.sleep(5)
            except Exception as e:
                logging.error(f"{cc.RED}Error when subscribing to {program}, {e}{cc.RESET}")
                await asyncio.sleep(5)
                traceback.print_exc()
            finally:
                if ws:
                    try:
                        await ws.close()
                    except RuntimeError:
                        break
                await asyncio.sleep(0.2)

    async def subscribe_state(self, pool_state, base_dec: int, quote_dec: int, mint: str | Pubkey):
        """
        Stream price updates from the Virtual-Pool account.
        """
        mint = mint if isinstance(mint, str) else str(mint)
        if isinstance(pool_state, tuple) and isinstance(pool_state[0], str):
            account_key = pool_state[0]
        else:
            raise TypeError(f"Pool state must be a tuple of (parsed_state): {type(pool_state)}")

        while mint not in self.parent.sold:
            try:
                if mint not in self.accounts:
                    self.accounts.add(mint)
                else:
                    logging.info(f"{cc.YELLOW}Already subscribed to {mint}{cc.RESET}")
                    return

                async with websockets.connect(WS_RPC_URL, ping_interval=2, ping_timeout=15) as ws:
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "accountSubscribe",
                        "params": [account_key, {"encoding": "base64", "commitment": Processed}]
                    }))
                    await ws.recv()
                    logging.info(f"{cc.LIGHT_GRAY}Started price monitoring for {mint} ✔{cc.RESET}")

                    async for raw in ws:
                        if mint in self.parent.sold:
                            break
                        data_b64 = json.loads(raw)["params"]["result"]["value"]["data"][0]
                        blob     = base64.b64decode(data_b64)[8:] # 8-byte discr.
                        vp       = self.meteora_dbc.virtual_pool_layout.parse(blob)
                        sqrt_q64 = int.from_bytes(vp.sqrt_price_raw, "little")
                        price    = self.meteora_dbc.price_from_sqrt(sqrt_q64, base_dec, quote_dec)
                        await self.updates.put(
                            {"mint": mint, "price": price, "sqrt": sqrt_q64, "ts": time.time()}
                        )

            except (websockets.exceptions.ConnectionClosedError, asyncio.TimeoutError):
                await asyncio.sleep(3)            # quick back-off reconnect
            except Exception as err:
                logging.error(f"{cc.RED}state-stream error {err}{cc.RESET}")
                traceback.print_exc()
                await asyncio.sleep(3)

    async def get_swap_tx(self, tx_id: str):
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTransaction",
                "params": [
                    tx_id,
                    {
                        "commitment": "confirmed",
                        "encoding": "json",
                        "maxSupportedTransactionVersion": 0
                    }
                ]
            }
            headers = {
                "Content-Type": "application/json"
            }

            async with self.session.post(HTTP_RPC_URL, json=payload, headers=headers, timeout=10) as response:
                if response.status != 200:
                    logging.error(f"HTTP Error {response.status}: {await response.text()}")
                    raise Exception(f"HTTP Error {response.status}")

                data = await response.json()

                if data and data.get('result') is not None:
                    result = data['result']
                    meta = result.get("meta", {})
                    return meta
                else:
                    logging.warning(f"Transaction result is None.")
        except Exception as e:
            logging.warning(f"Exception occurred: {e}")

    async def meteora_dbc_buy(self, mint: str, buy_amount: float = FIRST_BUY_AMOUNT, fee_sol: float = GAS):
        try:
            buy = await self.meteora_dbc.buy(mint, float(buy_amount), fee_sol)
            if buy == "migrated":
                return "migrated"
            logging.info(f"{cc.GREEN}Buy transaction sent: https://solscan.io/tx/{buy}{cc.RESET}")
            return buy
        except RuntimeError as e:
            if "is migrated" in str(e):
                logging.info(f"{cc.YELLOW}Pool {mint} is migrated, skipping buy{cc.RESET}")
                return "migrated"
        except Exception as e:
            logging.error(f"{cc.RED}Error when buying with Meteora DBC, {e}{cc.RESET}")
            traceback.print_exc()

    async def meteora_dbc_sell(self, mint: str, percentage: float, fee_sol: float = GAS):
        try:
            sell = await self.meteora_dbc.sell(mint, percentage, fee_sol)
            if sell == "migrated":
                return "migrated"
            logging.info(f"{cc.GREEN}Sell transaction sent: https://solscan.io/tx/{sell}{cc.RESET}")
            return sell
        except RuntimeError as e:
            if "is migrated" in str(e):
                logging.info(f"{cc.YELLOW}Pool {mint} is migrated, skipping sell{cc.RESET}")
                return "migrated"
        except Exception as e:
            logging.error(f"{cc.RED}Error when selling with Meteora DBC, {e}{cc.RESET}")
            traceback.print_exc()

    async def close(self):
        await self.session.close()