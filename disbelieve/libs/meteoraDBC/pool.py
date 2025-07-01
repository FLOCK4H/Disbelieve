# pool.py
from solana.rpc.types import MemcmpOpts, DataSliceOpts
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey # type: ignore

DBC  = Pubkey.from_string("dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN")
BASE_MINT_OFFSET = 136

async def pools_for_mint(mint_pk: str, ctx: AsyncClient):
    resp = await ctx.get_program_accounts(
        DBC,
        commitment="confirmed",
        encoding="base64",
        data_slice=DataSliceOpts(offset=0,
                                    length=BASE_MINT_OFFSET + 32),
        filters=[MemcmpOpts(offset=BASE_MINT_OFFSET,
                            bytes=str(mint_pk))]
    )
    return [str(acc.pubkey) for acc in resp.value]

async def find_pool(mint_pk: str, ctx: AsyncClient):
    pools = await pools_for_mint(mint_pk, ctx)
    if len(pools) == 0:
        raise ValueError("No pools found")
    return pools[0]