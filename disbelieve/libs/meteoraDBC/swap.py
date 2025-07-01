# swap.py 
from typing import Optional, Tuple
import struct
import base64
from solana.rpc.async_api import AsyncClient
from solders.pubkey      import Pubkey      # type: ignore                        
from solders.instruction import AccountMeta, Instruction       # type: ignore     
from spl.token.instructions import (
    get_associated_token_address,
    sync_native, SyncNativeParams,
    create_associated_token_account
)
from solders.system_program import transfer, TransferParams
from solders.transaction import VersionedTransaction # type: ignore
from solders.message    import MessageV0 # type: ignore
from solana.rpc.types import TxOpts
from solana.rpc.commitment import Processed
from solders.keypair import Keypair # type: ignore
from solders.compute_budget import set_compute_unit_price, set_compute_unit_limit # type: ignore
from spl.token.instructions import close_account, CloseAccountParams
from decimal import Decimal

def _token_prog(pool_type: int) -> Pubkey:
    return TOKEN_PROGRAM if pool_type == 0 else TOKEN_2022

def compute_unit_price_from_total_fee(
    total_lams: int,
    compute_units: int = 120_000
) -> int:
    lamports_per_cu = total_lams / float(compute_units)
    micro_lamports_per_cu = lamports_per_cu * 1_000_000
    return int(micro_lamports_per_cu)

DBC_PROGRAM_ID     = Pubkey.from_string("dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN")
POOL_AUTHORITY_PDA = Pubkey.from_string("FhVo3mqL8PW5pH5U2CN4XE33DokiyZnUwuGpH2hmHLuM")
EVENT_AUTH_SEED    = b"__event_authority"
EVENT_AUTHORITY_PDA, _ = Pubkey.find_program_address([EVENT_AUTH_SEED], DBC_PROGRAM_ID)

SWAP_DISCRIM = bytes([248, 198, 158, 145, 225, 117, 135, 200])
UNIT_COMPUTE_BUDGET = 200_000
LAMPORTS_PER_SOL = 1_000_000_000

TOKEN_PROGRAM = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
TOKEN_2022 = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")

class MeteoraDBCSwap:
    def __init__(self, client: AsyncClient, payer: Keypair):
        self.client = client
        self.payer = payer

    async def mint_of_token_account(self, ata_or_vault: str) -> Pubkey:
        info = (await self.client.get_account_info(Pubkey.from_string(ata_or_vault), encoding="base64")).value
        if info is None:
            raise RuntimeError("account not found")
        raw = base64.b64decode(info.data[0])[0:32]
        return Pubkey.from_bytes(raw)

    async def create_ata_if_needed(self, owner: Pubkey, mint: Pubkey):
        ata = get_associated_token_address(owner, mint)
        resp = await self.client.get_account_info(ata, commitment=Processed)
        if resp.value is None:
            return create_associated_token_account(
                payer=owner,
                owner=owner,
                mint=mint
            )
        return None

    def build_dbc_swap_ix(
        self,
        state: dict,
        user: Pubkey,
        amount_in: int,
        min_amount_out: int,
        *,
        quote_mint: Pubkey | str = "So11111111111111111111111111111111111111112",
        buy_base: bool = True,
        referral_ata: Optional[Pubkey] = None,
    ) -> Tuple[Instruction, Pubkey]:

        base_mint   = Pubkey.from_string(state["base_mint"])
        if isinstance(quote_mint, str):
            quote_mint  = Pubkey.from_string(quote_mint)

        base_vault  = Pubkey.from_string(state["base_vault"])
        quote_vault = Pubkey.from_string(state["quote_vault"])
        pool_pk     = Pubkey.from_string(state["_pubkey"] if "_pubkey" in state else "ERROR") \
                        if "_pubkey" in state else None
        if pool_pk is None:
            raise ValueError("state dict must include '_pubkey' with pool address")

        config_pk   = Pubkey.from_string(state["config"])
        pool_type   = state["pool_type"]

        if buy_base:
            in_mint,  out_mint  = quote_mint, base_mint
        else:
            in_mint,  out_mint  = base_mint, quote_mint

        user_in_ata  = get_associated_token_address(user,  in_mint)
        user_out_ata = get_associated_token_address(user,  out_mint)

        metas = [
            AccountMeta(Pubkey.from_string(str(POOL_AUTHORITY_PDA)), False, False),
            AccountMeta(config_pk, False, False),
            AccountMeta(pool_pk,   False, True),           # writable
            AccountMeta(user_in_ata,  False, True),
            AccountMeta(user_out_ata, False, True),
            AccountMeta(base_vault,  False, True),
            AccountMeta(quote_vault, False, True),
            AccountMeta(base_mint,   False, False),
            AccountMeta(quote_mint,  False, False),
            AccountMeta(user,        True,  True),         # payer / signer
            AccountMeta(_token_prog(pool_type), False, False),   # token_base_program
            AccountMeta(_token_prog(pool_type), False, False),   # token_quote_program
        ]

        if referral_ata is None:
            referral_ata = DBC_PROGRAM_ID

        metas.extend([
            AccountMeta(referral_ata, False, True),        # slot 12
            AccountMeta(EVENT_AUTHORITY_PDA, False, False),# slot 13
            AccountMeta(DBC_PROGRAM_ID, False, False),     # slot 14
        ])

        data = SWAP_DISCRIM + struct.pack("<QQ", amount_in, min_amount_out)

        ix = Instruction(program_id=DBC_PROGRAM_ID, data=data, accounts=metas)
        return ix

    async def buy(
            self,
            state: dict, 
            amount_in: int, 
            min_amount_out: int, 
            quote_mint: Pubkey | str = "So11111111111111111111111111111111111111112", 
            fee_sol: float = 0.00001,
            referral_ata: Optional[Pubkey] = None
        ):

        instructions = []

        lamports_fee = int(fee_sol * LAMPORTS_PER_SOL)
        micro_lamports = compute_unit_price_from_total_fee(
            lamports_fee,
            compute_units=UNIT_COMPUTE_BUDGET
        )

        instructions.append(set_compute_unit_limit(UNIT_COMPUTE_BUDGET))
        instructions.append(set_compute_unit_price(micro_lamports))

        user = self.payer.pubkey()

        quote_mint = Pubkey.from_string(quote_mint)

        wsol_ata = get_associated_token_address(user, quote_mint)

        wsol_ata_ix = await self.create_ata_if_needed(user, quote_mint)
        if wsol_ata_ix:
            instructions.append(wsol_ata_ix)

        base_ata_ix = await self.create_ata_if_needed(user, Pubkey.from_string(state["base_mint"]))
        if base_ata_ix:
            instructions.append(base_ata_ix)

        instructions.append(
            transfer(
                TransferParams(
                    from_pubkey = user,
                    to_pubkey   = wsol_ata,
                    lamports    = amount_in 
                )
            )
        )
        instructions.append(
            sync_native(
                SyncNativeParams(
                    program_id = TOKEN_PROGRAM,
                    account    = wsol_ata
                )
            )
        )

        swap_ix = self.build_dbc_swap_ix(
            state,
            user,
            amount_in,
            min_amount_out,
            quote_mint=quote_mint,
            buy_base=True,
            referral_ata=referral_ata
        )

        instructions.append(swap_ix)

        bh   = (await self.client.get_latest_blockhash(commitment=Processed)).value.blockhash
        msg  = MessageV0.try_compile(
            payer = user,
            instructions = instructions,
            address_lookup_table_accounts = [],
            recent_blockhash = bh,
        )
        tx = VersionedTransaction(msg, [self.payer])
        opts = TxOpts(skip_preflight=True, max_retries=0)
        sig = await self.client.send_transaction(tx, opts=opts)
        print("sent tx:", sig.value)
        return sig.value

    async def sell(
        self,
        state: dict,
        pct: float,
        slippage_pct: float = 5.0,
        fee_sol: float = 0.00001,
        quote_mint: str = "So11111111111111111111111111111111111111112",
        referral_ata: Pubkey | None = None,
    ):

        assert 0 < pct <= 100, "pct must be between 0 and 100"

        user      = self.payer.pubkey()
        base_mint = Pubkey.from_string(state["base_mint"])
        quote_mnt = Pubkey.from_string(quote_mint)
        base_ata  = get_associated_token_address(user, base_mint)
        wsol_ata  = get_associated_token_address(user, quote_mnt)

        acc = (await self.client.get_account_info_json_parsed(base_ata, commitment=Processed)).value
        if acc is None:
            raise RuntimeError(f"Base ATA empty – nothing to sell {base_ata}")
        raw_bal = int(acc.data.parsed['info']['tokenAmount']['amount'])

        amount_in = int(raw_bal * (pct / 100.0))
        if amount_in == 0:
            raise RuntimeError("Chosen percentage rounds to zero tokens")

        price      = Decimal(state["quote_reserve"]) / Decimal(state["base_reserve"])
        min_quote  = int(Decimal(amount_in) * price * Decimal(1 - slippage_pct / 100))

        lamports_fee    = int(fee_sol * LAMPORTS_PER_SOL)
        micro_lamports  = compute_unit_price_from_total_fee(lamports_fee,
                                                            compute_units=UNIT_COMPUTE_BUDGET)
        ix = [
            set_compute_unit_limit(UNIT_COMPUTE_BUDGET),
            set_compute_unit_price(micro_lamports),
        ]

        if await self.create_ata_if_needed(user, quote_mnt):
            ix.append(await self.create_ata_if_needed(user, quote_mnt))

        swap_ix = self.build_dbc_swap_ix(
            state       = state,
            user        = user,
            amount_in   = amount_in,
            min_amount_out = min_quote,
            quote_mint  = quote_mnt,
            buy_base    = False,
            referral_ata= referral_ata,
        )
        ix.append(swap_ix)

        ix.append(
            close_account(
                CloseAccountParams(
                    program_id = TOKEN_PROGRAM,
                    account    = wsol_ata,
                    dest       = user,
                    owner      = user,
                )
            )
        )

        bh = (await self.client.get_latest_blockhash()).value.blockhash
        msg = MessageV0.try_compile(
            payer        = user,
            instructions = ix,
            recent_blockhash = bh,
            address_lookup_table_accounts = [],
        )
        tx  = VersionedTransaction(msg, [self.payer])
        sig = await self.client.send_transaction(tx, opts=TxOpts(skip_preflight=True))
        print("sent sell tx:", sig.value)
        return sig.value

__all__ = ["MeteoraDBCSwap"]