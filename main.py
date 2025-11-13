from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from web3 import Web3
from eth_account import Account
import os
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Ultra Backend V12 - Seed Phrase Support")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# 🔐 ADMIN WALLET CONFIGURATION - Seed Phrase Support

# Method 1: Use seed phrase (12 or 24 words) - RECOMMENDED
ADMIN_SEED_PHRASE = os.getenv('ADMIN_SEED_PHRASE', "exotic estate dinosaur entry century cause inflict balance example stone twin expect")

# Method 2: Use private key directly (fallback)
ADMIN_PRIVATE_KEY = os.getenv('ADMIN_PRIVATE_KEY', "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80")

ALCHEMY_KEY = os.getenv("ALCHEMY_API_KEY", "j6uyDNnArwlEpG44o93SqZ0JixvE20Tq")
NETWORK = os.getenv("NETWORK", "mainnet")

# All 3 production contracts hardcoded
CONTRACTS = [
    {"id": 1, "name": "Primary", "address": "0x29983BE497D4c1D39Aa80D20Cf74173ae81D2af5"},
    {"id": 2, "name": "Secondary", "address": "0x0b8Add0d32eFaF79E6DB4C58CcA61D6eFBCcAa3D"},
    {"id": 3, "name": "Tertiary", "address": "0xf97A395850304b8ec9B8f9c80A17674886612065"}
]

web3_instance = None
admin_account = None
admin_private_key = None
admin_address = None

def init_web3():
    global web3_instance, admin_account, admin_private_key, admin_address
    
    # 🔐 DERIVE WALLET FROM SEED PHRASE OR USE PRIVATE KEY
    if ADMIN_SEED_PHRASE:
        try:
            # ✅ Enable HD Wallet features for mnemonic support
            Account.enable_unaudited_hdwallet_features()
            
            # ✅ Derive wallet from seed phrase
            admin_account = Account.from_mnemonic(ADMIN_SEED_PHRASE)
            admin_private_key = admin_account.key.hex()
            admin_address = admin_account.address
            
            logger.info("✅ Admin wallet DERIVED from seed phrase")
            logger.info(f"📍 Address: {admin_address}")
        except Exception as e:
            logger.error(f"❌ Failed to derive from seed phrase: {e}")
            return False
            
    elif ADMIN_PRIVATE_KEY:
        try:
            # ✅ Use private key directly
            private_key = ADMIN_PRIVATE_KEY if ADMIN_PRIVATE_KEY.startswith('0x') else f"0x{ADMIN_PRIVATE_KEY}"
            admin_account = Account.from_key(private_key)
            admin_private_key = private_key
            admin_address = admin_account.address
            
            logger.info("✅ Admin wallet loaded from private key")
            logger.info(f"📍 Address: {admin_address}")
        except Exception as e:
            logger.error(f"❌ Failed to load private key: {e}")
            return False
    else:
        logger.warning("⚠️ No admin wallet configured - set ADMIN_SEED_PHRASE or ADMIN_PRIVATE_KEY")
        return False
    
    # ✅ Initialize Web3
    if not ALCHEMY_KEY:
        logger.warning("⚠️ ALCHEMY_API_KEY not set")
        return False
    
    try:
        web3_instance = Web3(Web3.HTTPProvider(f"https://eth-mainnet.g.alchemy.com/v2/{ALCHEMY_KEY}"))
        
        if not web3_instance.is_connected():
            logger.error("❌ Failed to connect to Ethereum")
            return False
            
        logger.info("✅ Connected to Ethereum Mainnet")
        
        for contract in CONTRACTS:
            logger.info(f"📋 {contract['name']}: {contract['address']}")
        
        # Check admin wallet balance
        try:
            balance_wei = web3_instance.eth.get_balance(admin_address)
            balance_eth = web3_instance.from_wei(balance_wei, 'ether')
            logger.info(f"💰 Admin Balance: {balance_eth:.6f} ETH")
            
            if balance_eth < 0.01:
                logger.warning(f"⚠️ Low ETH balance for gas fees: {balance_eth:.6f} ETH")
        except Exception as e:
            logger.error(f"⚠️ Could not check balance: {e}")
        
        return True
        
    except Exception as error:
        logger.error(f"❌ Web3 init error: {error}")
        return False

web3_ready = init_web3()

TOKEN_ABI = [
    {"inputs": [{"type": "address"}, {"type": "uint256"}], "name": "mint", "type": "function"},
    {"inputs": [{"type": "address"}, {"type": "uint256"}], "name": "transfer", "type": "function"},
    {"inputs": [], "name": "decimals", "outputs": [{"type": "uint8"}], "type": "function"},
    {"inputs": [], "name": "symbol", "outputs": [{"type": "string"}], "type": "function"}
]

sessions = {}

def process_withdrawal(user_wallet, amount_requested, preferred_contract):
    """
    Process withdrawal with automatic fallback across 3 contracts
    Tries mint() and transfer() on each contract
    """
    if not web3_instance or not admin_account:
        raise HTTPException(503, "Web3 not connected")
    if not Web3.is_address(user_wallet):
        raise ValueError("Invalid wallet address")
    if amount_requested <= 0:
        raise ValueError("Invalid amount")
    
    # Build contract list with preferred contract first
    contract_list = []
    if preferred_contract:
        for contract in CONTRACTS:
            if contract["address"].lower() == preferred_contract.lower():
                contract_list.append(contract)
                break
    for contract in CONTRACTS:
        if contract not in contract_list:
            contract_list.append(contract)
    
    logger.info(f"💰 Processing withdrawal: {amount_requested} to {user_wallet}")
    
    for index, contract_data in enumerate(contract_list):
        logger.info(f"🎯 Attempt {index+1}/3: {contract_data['name']} ({contract_data['address'][:10]}...)")
        
        try:
            token_contract = web3_instance.eth.contract(
                address=Web3.to_checksum_address(contract_data["address"]), 
                abi=TOKEN_ABI
            )
            
            # Get token info
            try:
                token_symbol = token_contract.functions.symbol().call()
                token_decimals = token_contract.functions.decimals().call()
            except:
                token_symbol = "TOKEN"
                token_decimals = 18
            
            amount_in_wei = int(amount_requested * (10 ** token_decimals))
            current_gas_price = web3_instance.eth.gas_price
            current_nonce = web3_instance.eth.get_transaction_count(admin_address)
            
            # 🎯 METHOD 1: Try mint()
            try:
                logger.info(f"   📞 Trying mint({amount_requested} {token_symbol})...")
                
                mint_tx = token_contract.functions.mint(
                    Web3.to_checksum_address(user_wallet), 
                    amount_in_wei
                ).build_transaction({
                    'from': admin_address, 
                    'nonce': current_nonce, 
                    'gas': 200000, 
                    'gasPrice': int(current_gas_price * 1.2), 
                    'chainId': web3_instance.eth.chain_id
                })
                
                # 🔐 Sign with admin private key (from seed phrase or direct)
                signed_tx = web3_instance.eth.account.sign_transaction(mint_tx, admin_private_key)
                tx_hash = web3_instance.eth.send_raw_transaction(signed_tx.rawTransaction)
                receipt = web3_instance.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                
                if receipt['status'] == 1:
                    logger.info(f"   ✅ MINT SUCCESS! TX: {tx_hash.hex()}")
                    return {
                        "success": True,
                        "method": "mint",
                        "contract": contract_data['name'],
                        "contractAddress": contract_data["address"],
                        "txHash": tx_hash.hex(),
                        "blockNumber": receipt['blockNumber'],
                        "symbol": token_symbol,
                        "gasUsed": receipt['gasUsed']
                    }
            except Exception as mint_error:
                logger.warning(f"   ⚠️ mint() failed: {str(mint_error)[:100]}")
            
            # 🎯 METHOD 2: Try transfer()
            try:
                logger.info(f"   📞 Trying transfer({amount_requested} {token_symbol})...")
                
                new_nonce = web3_instance.eth.get_transaction_count(admin_address)
                
                transfer_tx = token_contract.functions.transfer(
                    Web3.to_checksum_address(user_wallet), 
                    amount_in_wei
                ).build_transaction({
                    'from': admin_address, 
                    'nonce': new_nonce, 
                    'gas': 100000, 
                    'gasPrice': int(current_gas_price * 1.2), 
                    'chainId': web3_instance.eth.chain_id
                })
                
                # 🔐 Sign with admin private key
                signed_tx = web3_instance.eth.account.sign_transaction(transfer_tx, admin_private_key)
                tx_hash = web3_instance.eth.send_raw_transaction(signed_tx.rawTransaction)
                receipt = web3_instance.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                
                if receipt['status'] == 1:
                    logger.info(f"   ✅ TRANSFER SUCCESS! TX: {tx_hash.hex()}")
                    return {
                        "success": True,
                        "method": "transfer",
                        "contract": contract_data['name'],
                        "contractAddress": contract_data["address"],
                        "txHash": tx_hash.hex(),
                        "blockNumber": receipt['blockNumber'],
                        "symbol": token_symbol,
                        "gasUsed": receipt['gasUsed']
                    }
            except Exception as transfer_error:
                logger.warning(f"   ⚠️ transfer() failed: {str(transfer_error)[:100]}")
                
        except Exception as contract_error:
            logger.error(f"   ❌ Contract {index+1} error: {str(contract_error)[:100]}")
            continue
    
    # All methods failed
    logger.error("❌ ALL CONTRACTS AND METHODS FAILED")
    raise HTTPException(500, "All withdrawal methods exhausted")

@app.get("/")
def root():
    """Health check endpoint"""
    admin_bal = None
    if admin_address and web3_instance:
        try:
            bal = web3_instance.eth.get_balance(admin_address)
            admin_bal = float(web3_instance.from_wei(bal, 'ether'))
        except:
            pass
    
    return {
        "service": "Ultra Backend V12",
        "version": "12.0.0-seed-phrase",
        "status": "online",
        "web3_ready": web3_ready,
        "admin_wallet": admin_address,
        "admin_eth_balance": admin_bal,
        "wallet_source": "seed_phrase" if ADMIN_SEED_PHRASE else "private_key" if ADMIN_PRIVATE_KEY else "none",
        "contracts": CONTRACTS,
        "total": len(CONTRACTS),
        "network": "Ethereum Mainnet",
        "chain_id": 1
    }

@app.post("/api/engine/start")
def start(data: dict):
    """Start earning engine session"""
    user_wallet = data.get("walletAddress", "").lower()
    sessions[user_wallet] = {"start": datetime.now().timestamp(), "active": True}
    logger.info(f"✅ Session started for {user_wallet}")
    return {"success": True, "session_id": user_wallet}

@app.get("/api/engine/metrics")
def metrics(x_wallet_address: str = Header(None)):
    """Get earning metrics"""
    return {
        "hourlyRate": 45000.0,
        "dailyProfit": 1080000.0,
        "activePositions": 32,
        "totalProfit": 0,
        "pendingRewards": 0
    }

@app.post("/api/engine/withdraw")
def withdraw_endpoint(data: dict):
    """
    Process withdrawal request
    Supports: ETH, WETH, WBTC
    """
    if not web3_ready:
        raise HTTPException(503, "Backend not connected to blockchain")
    
    user_wallet = data.get("walletAddress")
    amount_requested = float(data.get("amount", 0))
    preferred = data.get("tokenAddress")
    token_symbol = data.get("tokenSymbol", "TOKEN")
    
    if not user_wallet or amount_requested <= 0:
        raise HTTPException(400, "Invalid withdrawal request")
    
    logger.info(f"💰 Withdrawal request: {amount_requested} {token_symbol} to {user_wallet}")
    
    try:
        result = process_withdrawal(user_wallet, amount_requested, preferred)
        logger.info(f"✅ Withdrawal successful: {result['txHash']}")
        return result
    except Exception as error:
        logger.error(f"❌ Withdrawal failed: {error}")
        raise HTTPException(500, f"Withdrawal failed: {str(error)}")

@app.post("/api/engine/stop")
def stop(data: dict):
    """Stop earning engine session"""
    user_wallet = data.get("walletAddress", "").lower()
    if user_wallet in sessions:
        sessions[user_wallet]["active"] = False
    return {"success": True}

@app.get("/api/health")
def health():
    """Detailed health check"""
    return {
        "web3_connected": web3_instance.is_connected() if web3_instance else False,
        "admin_configured": admin_account is not None,
        "wallet_source": "seed_phrase" if ADMIN_SEED_PHRASE else "private_key" if ADMIN_PRIVATE_KEY else "none",
        "contracts": CONTRACTS,
        "contract_count": 3
    }

@app.get("/api/contracts")
def get_contracts():
    """Get all production contracts"""
    return {"contracts": CONTRACTS, "total": 3}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
