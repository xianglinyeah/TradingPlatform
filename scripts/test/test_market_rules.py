#!/usr/bin/env python3
"""MarketRuleValidator functional test"""

import grpc
import sys
import os
from pathlib import Path
from datetime import date, datetime
import time

# Set console encoding
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add project path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src" / "strategy-engine"))
sys.path.insert(0, str(project_root / "src" / "strategy-engine" / "protos"))

# Import generated gRPC classes
import execution_pb2
import execution_pb2_grpc

def test_market_rules():
    """Test MarketRuleValidator functionality"""
    print("=" * 60)
    print("MarketRuleValidator Functional Test")
    print("=" * 60)

    # Connect to ExecutionService
    channel = grpc.insecure_channel('localhost:8084')
    client = execution_pb2_grpc.ExecutionStub(channel)

    session_id = f"market-rule-test-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    print(f"\n[Test 1] Test naked short selling prohibition rule")
    print(f"Session: {session_id}")

    try:
        # Attempt to sell without a position (should be rejected)
        print("  - Attempting to sell stock 600000.SH without a position...")
        response = client.SubmitOrder(execution_pb2.OrderRequest(
            session_id=session_id,
            symbol="600000.SH",
            side=1,  # Sell
            type=0,   # Market
            quantity=100,
            price=0.0,
            signal_id="test1",
            strategy_id="market-rule-test"
        ))

        print(f"  - Order status: {response.status}")
        print(f"  - Response message: {response.message}")

        if response.status == 4:  # Rejected (OrderStatus.Rejected = 4)
            if "naked short" in response.message or "position" in response.message:
                print("  [OK] Naked short prohibition rule works correctly!")
            else:
                print(f"  [FAIL] Rejection reason does not match expectation: {response.message}")
        else:
            print(f"  [FAIL] Order should be rejected (status 4) but actual status: {response.status}")

    except grpc.RpcError as e:
        print(f"  [FAIL] gRPC call failed: {e.code()} - {e.details()}")

    print(f"\n[Test 2] Test normal buy order")
    try:
        print("  - Attempting to buy 600000.SH...")
        buy_response = client.SubmitOrder(execution_pb2.OrderRequest(
            session_id=session_id,
            symbol="600000.SH",
            side=0,  # Buy
            type=0,   # Market
            quantity=100,
            price=10.0,
            signal_id="test2",
            strategy_id="market-rule-test"
        ))

        print(f"  - Order status: {buy_response.status}")
        print(f"  - Response message: {buy_response.message}")

        if buy_response.status == 1:  # Filled
            print("  [OK] Buy order executed successfully!")
        else:
            print(f"  [FAIL] Buy order execution failed: {buy_response.message}")

    except grpc.RpcError as e:
        print(f"  [FAIL] gRPC call failed: {e.code()} - {e.details()}")

    print(f"\n[Test 3] Test T+1 rule")
    try:
        print("  - Attempting to sell recently purchased stock on the same day...")
        # Note: A time gap is needed here to test T+1, or simulate same-day trading
        sell_response = client.SubmitOrder(execution_pb2.OrderRequest(
            session_id=session_id,
            symbol="600000.SH",
            side=1,  # Sell
            type=0,   # Market
            quantity=50,  # Sell a portion
            price=12.0,
            signal_id="test3",
            strategy_id="market-rule-test"
        ))

        print(f"  - Order status: {sell_response.status}")
        print(f"  - Response message: {sell_response.message}")

        if sell_response.status == 4:  # Rejected (OrderStatus.Rejected = 4)
            if "T+1" in sell_response.message:
                print("  [OK] T+1 rule works correctly!")
            else:
                print(f"  [FAIL] Rejection reason does not match expectation: {sell_response.message}")
        else:
            print(f"  [WARN] T+1 rule may not be in effect, order status: {sell_response.status}")

    except grpc.RpcError as e:
        print(f"  [FAIL] gRPC call failed: {e.code()} - {e.details()}")

    print(f"\n[Test 4] Query account status")
    try:
        account = client.GetAccount(execution_pb2.AccountRequest(
            session_id=session_id
        ))

        print(f"  - Cash: {account.cash}")
        print(f"  - Equity: {account.equity}")
        print(f"  - Market value: {account.market_value}")
        print(f"  - Total PnL: {account.total_pnl}")
        print("  [OK] Account query succeeded!")

    except grpc.RpcError as e:
        print(f"  [FAIL] Account query failed: {e.code()} - {e.details()}")

    print("\n" + "=" * 60)
    print("Test completed")
    print("=" * 60)

    channel.close()

if __name__ == "__main__":
    test_market_rules()
