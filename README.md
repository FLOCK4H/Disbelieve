<div align="center">

  <img src="https://github.com/user-attachments/assets/719beb23-dc3b-4f01-ada7-8ea1992e938c" width=256 />

</div>

> [!NOTE]
> This project is open-sourced, and completely free of any charges, or transaction fees.

# Disbelieve

Believe platform uses **Meteora Dynamic Bonding Curve** market to create tokens for users' projects. 
Fortunately, tokens released on believe end with `BLV`, and are also minted by `Believe: Token Authority` - this allows for easy identification of new tokens.
Snipe, scalp, trade, and more... as soon as a new token is released.

# Features

- Automatically Buy & Sell -> fresh tokens released via Believe platform
- Speed: Local transaction construction, zero reliance on routers
- Real-time price monitoring
- Easy config system
- Script for selling manually

# Setup

1. Download this repository

```
$ git clone https://github.com/FLOCK4H/Disbelieve
```

2. Navigate to the repository & Install Disbelieve

```
$ cd Disbelieve
$ pip install .
```

3. Ensure `.env` is configured properly and URLs are set

<h5>If the `.env` file doesn't exist create it, preferably at the path you will launch the script from.</h5>

```
# env file needs to contain everything below

HTTP_RPC_URL=https://mainnet.helius-rpc.com/?api-key= # can be any other rpc provider
WS_RPC_URL=wss://mainnet.helius-rpc.com/?api-key= # can be any other rpc provider
PRIVATE_KEY= # in Phantom format, so base58 (manage accounts -> account X -> show private key)

DISABLE_FIRST_BUY=True # FIRST_BUY_AMOUNT becomes useless if True, use NEXT_BUY_AMOUNT to set buy amount
FIRST_BUY_AMOUNT=0.0001
NEXT_BUY_AMOUNT=0.001
GAS=0.00002 # SOL; includes priority

MIN_TARGET_PROFIT=2.00 # minimum profit to exit trade
MAX_LOSS=0.9 # max loss from buy price <--! This may be confusing to some people as it's the other way around, set max loss by the rule of 1: 1-0.9=0.1 -> 10% max loss from buy price
NO_ACTIVITY_IN_SECONDS=15 # no activity == no price change
MAX_LOSS_FROM_PEAK_PERCENTAGE=0.3 # maximum price drop from token's highest price
MIN_BUYS_THRESHOLD=15 # minimum buys to enter the token
DEBUG_SENSITIVITY=1 # 0, 1, 2 - 0 is lowest, for debug prints
```

4. Run the app

```
$ disbelieve
```

![image](https://github.com/user-attachments/assets/720cdccb-e5e0-4066-b80a-d2c50e65c1b4)

**That's it, you can start trading.**

# Contact

TG Priv: @dubskii420

TG Group: https://t.me/flock4hcave

Discord Group: https://discord.gg/thREUECv2a

Tip Wallet: FL4CKfetEWBMXFs15ZAz4peyGbCuzVaoszRKcoVt3WfC
