# meteora.py
import json
import asyncio

try: from .state import fetch_virtual_pool, VirtualPoolLayout, price_from_sqrt;
except: from state import fetch_virtual_pool, VirtualPoolLayout, price_from_sqrt;
try: from .pool import find_pool;
except: from pool import find_pool;
try: from .swap  import MeteoraDBCSwap;
except: from swap  import MeteoraDBCSwap;

try:
    from solana.rpc.async_api import AsyncClient
    from solders.keypair import Keypair # type: ignore
    from solders.pubkey import Pubkey # type: ignore
    import traceback
except Exception as e:
    print(f"Error, one or more of required modules are missing, install them with pip. {e}")

class MeteoraDBC:
    def __init__(self, async_client: AsyncClient, signer: Keypair | str):
        self.client = async_client
        self.payer = signer if isinstance(signer, Keypair) else Keypair.from_base58_string(signer)
        self.swap = MeteoraDBCSwap(self.client, self.payer)
        self.virtual_pool_layout = VirtualPoolLayout
        self.price_from_sqrt = price_from_sqrt
    
    async def fetch_state(self, mint: str | Pubkey):
        try:
            mint = str(mint) if isinstance(mint, Pubkey) else mint
            pool_addr = await find_pool(mint, self.client)
            state = await fetch_virtual_pool(pool_addr, self.client)
            state["_pubkey"] = pool_addr
            return (pool_addr, state)
        except RuntimeError as e:
            print(f"Error: {e}")
            return pool_addr, "NO_ACC"

    async def buy(self, mint: str, sol_amount: float, fee_sol: float = 0.00001):
        try:
            sol_lams = int(sol_amount * 1e9)
            pool, state = await self.fetch_state(mint)
            is_migrated = state["is_migrated"]
            if is_migrated == 1:
                return "migrated"

            if state == "NO_ACC":
                await asyncio.sleep(0.2)
                pool, state = await self.fetch_state(mint)
                if state == "NO_ACC":
                    raise RuntimeError(f"No account found for mint {mint}")

            buy_tx = await self.swap.buy(
                state=state,
                amount_in=sol_lams,
                min_amount_out=1,
                fee_sol=fee_sol,
            )
            return buy_tx
        except Exception as e:
            traceback.print_exc()
            return None

    async def sell(self, mint: str, percentage: float, fee_sol: float = 0.00001):
        try:
            assert (0 < percentage <= 100), "Percentage must be between 0 and 100"
            pool, state = await self.fetch_state(mint)
            is_migrated = state["is_migrated"]
            if is_migrated == 1:
                return "migrated"
            
            sell_tx = await self.swap.sell(
                state=state,
                pct=percentage,
                fee_sol=fee_sol,
            )
            return sell_tx
        except AssertionError as e:
            print(f"Error: {e}")
            return None
        except Exception as e:
            traceback.print_exc()
            return None

    async def close(self):
        await self.client.close()

__all__ = ["MeteoraDBC"]
