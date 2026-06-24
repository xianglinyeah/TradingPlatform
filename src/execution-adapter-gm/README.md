# execution-adapter-gm (Python)

Python rewrite of the C# `execution_adapter_gm` service. Exposes the same
`gm_trading.proto` gRPC contract on port 5005 and routes trading calls to the
GM SDK.

## Why Python

The C# version depends on `gmsdk-net-x64` (Windows-only), which blocks
k8s/Linux deployment. The Python `gm` SDK is cross-platform.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  gRPC thread pool (PlaceOrder / CancelOrder / GetCash / ...)    │
│  PlaceOrder:  REQUEST_QUEUE.put(job); future.result(timeout=30) │
└────────────────────────┬────────────────────────────────────────┘
                         │ queue
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  GM Strategy thread (blocking run() event loop)                 │
│  on_schedule(context) drains REQUEST_QUEUE:                     │
│    order = order_volume(...)   ← must be called here            │
│    PENDING_ORDERS.register(order.cl_ord_id, future)             │
└────────────────────────┬────────────────────────────────────────┘
                         │ SDK order-state callback
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  GM SDK callback thread                                         │
│  on_order_status(context, order):                               │
│    PENDING_ORDERS.pop(order.cl_ord_id).set_result(order)        │
└─────────────────────────────────────────────────────────────────┘
```

Three threads, two shared structures (`REQUEST_QUEUE`, `PENDING_ORDERS`).

## Layout

```
main.py                  Entry point — starts GM thread + gRPC server
config.py / config.yaml  YAML config (replaces appsettings.json)
requirements.txt         gm, grpcio, grpcio-tools, protobuf, pyyaml
protos/
    gm_trading.proto     Copied verbatim from proto/gm_trading.proto
    gm_trading_pb2.py    Generated — DO NOT edit
    gm_trading_pb2_grpc.py
services/
    gm_strategy.py       init/on_schedule/on_order_status callbacks
    grpc_servicer.py     GMTradingServicer — 5 RPC handlers
    order_queue.py       REQUEST_QUEUE + PENDING_ORDERS
    order_enums.py       Proto ↔ GM SDK enum mapping
    symbol_converter.py  600000.SH ↔ SHSE.600000
    logger.py            RotatingFileHandler setup
```

## Run

```bash
pip install -r requirements.txt
# regenerate proto stubs if proto changes:
python -m grpc_tools.protoc -I protos --python_out=protos --grpc_python_out=protos \
    protos/gm_trading.proto
python main.py config.yaml
```

Smoke test:

```bash
grpcurl -plaintext -d '{
  "account_id": "<your_paper_account_id>"
}' localhost:5005 gmtrading.GMTrading/GetCash
```

## Differences from C#

| Aspect           | C#                                       | Python                                       |
|-------------------|------------------------------------------|----------------------------------------------|
| GM SDK thread     | `Strategy.Run()` on background task      | `gm.api.run()` on daemon thread              |
| gRPC server       | Kestrel on main thread                   | `grpc.server` on main thread                 |
| Pending tracking  | `TaskCompletionSource<Order>` + dict     | `concurrent.futures.Future` + locked dict    |
| Cross-thread call | `OrderVolume` called directly on gRPC    | Enqueued, drained by `schedule()` callback   |

## Git history

The original C# source (`Program.cs`, `Services/GMTradingGrpcService.cs`,
`Services/GMTradingServiceAdaptor.cs`, `Utils/`, `appsettings.json`) is
preserved in git history at the last commit before this rewrite.
