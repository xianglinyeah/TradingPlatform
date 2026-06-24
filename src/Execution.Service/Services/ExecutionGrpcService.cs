using ExecutionService.Models;
using ExecutionService.Core.Adapters;
using ExecutionService.Core.Services;
using ExecutionService.Core.MarketRules;
using ExecutionService.Core.Events;
using Grpc.Core;

namespace Execution.Service.Services;

public class ExecutionGrpcService : Execution.ExecutionBase
{
    private readonly IExecutionAdapter _executionAdapter;
    private readonly IPositionManager _positionManager;
    private readonly IAccountManager _accountManager;
    private readonly IPnLCalculator _pnlCalculator;
    private readonly IRiskManager _riskManager;
    private readonly IMarketRuleValidator _marketRuleValidator;
    private readonly OrderUpdateChannel _orderUpdateChannel;
    private readonly ILogger<ExecutionGrpcService> _logger;

    public ExecutionGrpcService(
        IExecutionAdapter executionAdapter,
        IPositionManager positionManager,
        IAccountManager accountManager,
        IPnLCalculator pnlCalculator,
        IRiskManager riskManager,
        IMarketRuleValidator marketRuleValidator,
        OrderUpdateChannel orderUpdateChannel,
        ILogger<ExecutionGrpcService> logger)
    {
        _executionAdapter = executionAdapter;
        _positionManager = positionManager;
        _accountManager = accountManager;
        _pnlCalculator = pnlCalculator;
        _riskManager = riskManager;
        _marketRuleValidator = marketRuleValidator;
        _orderUpdateChannel = orderUpdateChannel;
        _logger = logger;
    }

    private DateTime ParseTradeTime(string tradeTimeStr)
    {
        // trade_time is the historical market time at which the order was emitted.
        // It MUST be supplied — without it, T+1 validation, market-hours checks,
        // and backtest accuracy all break. We never silently fall back to Now().
        if (string.IsNullOrWhiteSpace(tradeTimeStr))
        {
            throw new RpcException(new Status(StatusCode.InvalidArgument,
                "trade_time is required (the market time at which the order was emitted)."));
        }

        try
        {
            return DateTime.Parse(tradeTimeStr, null, System.Globalization.DateTimeStyles.AssumeUniversal);
        }
        catch (Exception ex)
        {
            throw new RpcException(new Status(StatusCode.InvalidArgument,
                $"Invalid trade_time format: '{tradeTimeStr}'. Expected ISO 8601 (e.g. 2026-06-23T14:30:00Z). Error: {ex.Message}"));
        }
    }

    public override async Task<OrderResponse> SubmitOrder(OrderRequest request, ServerCallContext context)
    {
        var timestamp = DateTime.Now.ToString("HH:mm:ss.fff");
        _logger.LogInformation("[{Timestamp}] 🔔 Received gRPC order request: Session={Session}, Symbol={Symbol}, Side={Side}, Qty={Qty}, Price={Price}",
            timestamp, request.SessionId, request.Symbol, request.Side, request.Quantity, request.Price);

        try
        {
            var order = new Order
            {
                OrderId = Guid.NewGuid().ToString(),
                SessionId = request.SessionId,
                Symbol = request.Symbol,
                Side = (OrderSide)request.Side,
                OrderType = (OrderType)request.Type,
                Quantity = (decimal)request.Quantity,
                Price = (decimal)request.Price,
                Status = OrderStatus.Pending,
                CreatedAt = ParseTradeTime(request.TradeTime),  // Use historical trade time
                TimeInForce = (TimeInForce)request.TimeInForce  // Added in P2.1
            };

            _logger.LogInformation("[TIMESTAMP_CHECK] Request trade_time={TradeTime}, Parsed CreatedAt={CreatedAt}, Date={Date}",
                request.TradeTime ?? "(empty)", order.CreatedAt.ToString("s"), order.CreatedAt.ToString("yyyy-MM-dd"));

            _logger.LogInformation("[{Timestamp}] 📝 Created order: OrderId={OrderId}, SessionId={SessionId}, Symbol={Symbol}, Side={Side}, Quantity={Quantity}, Price={Price}",
                DateTime.Now.ToString("HH:mm:ss.fff"), order.OrderId, order.SessionId, order.Symbol, order.Side, order.Quantity, order.Price);

            // Market Rules Check (exchange mandatory rules, e.g. T+1 settlement rule, no naked short selling)
            var marketRuleResult = await _marketRuleValidator.ValidateOrderAsync(order, DateOnly.FromDateTime(order.CreatedAt));
            if (!marketRuleResult.Passed)
            {
                order.Status = OrderStatus.Rejected;
                order.Reason = $"Rejected by market rules: {marketRuleResult.RuleName} - {marketRuleResult.Reason}";
                _logger.LogWarning("Order rejected by market rules: {OrderId}, Rule: {Rule}, Reason: {Reason}",
                    order.OrderId, marketRuleResult.RuleName, marketRuleResult.Reason);
                return MapOrderResponse(order);
            }

            // Risk check (user-configured risk control rules)
            var riskResult = await _executionAdapter.CheckOrderRiskAsync(order);
            if (!riskResult.IsAllowed)
            {
                order.Status = OrderStatus.Rejected;
                order.Reason = riskResult.Reason;
                _logger.LogWarning("Order rejected by risk control: {OrderId}, Reason: {Reason}", order.OrderId, riskResult.Reason);
                return MapOrderResponse(order);
            }

            // Validate order
            var isValid = await _executionAdapter.ValidateOrderAsync(order);
            if (!isValid)
            {
                order.Status = OrderStatus.Rejected;
                order.Reason = "Invalid order parameters";
                return MapOrderResponse(order);
            }

            // Execute order
            var marketData = new ExecutionService.Models.MarketData
            {
                Symbol = order.Symbol,
                Close = order.Price,
                Timestamp = order.CreatedAt  // Use historical trade time for T+1 validation
            };

            var result = await _executionAdapter.ExecuteOrderAsync(order, marketData);
            order = result.Order;

            // P0.3: Filled/Partial both need to update position; Rejected only saves order + publishes event via PositionManager
            if (order.Status == OrderStatus.Filled || order.Status == OrderStatus.Partial ||
                order.Status == OrderStatus.Cancelled || order.Status == OrderStatus.Rejected)
            {
                _logger.LogInformation(
                    "Order terminal={Status}, updating position: {SessionId} {Symbol}, fills={FillCount}",
                    order.Status, order.SessionId, order.Symbol, result.Fills.Count);
                await _positionManager.UpdatePositionAsync(order.SessionId, order, result.Fills.ToList());

                if (order.Status == OrderStatus.Filled || order.Status == OrderStatus.Partial)
                {
                    // Update account equity
                    var account = await _accountManager.GetAccountAsync(order.SessionId);
                    _logger.LogInformation("Account info: Cash={Cash}, Equity={Equity}, MarketValue={MarketValue}",
                        account.Cash, account.Equity, account.MarketValue);
                    await _accountManager.UpdateEquityAsync(order.SessionId);
                }
            }

            return MapOrderResponse(order, result.Fills.Count);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to process order");
            return new OrderResponse
            {
                OrderId = "",
                Status = (int)OrderStatus.Rejected,
                Message = ex.Message
            };
        }
    }

    public override async Task<OrderStatusResponse> GetOrderStatus(OrderStatusRequest request, ServerCallContext context)
    {
        var order = await _positionManager.GetOrderAsync(request.SessionId, request.OrderId);

        if (order == null)
        {
            return new OrderStatusResponse
            {
                Exists = false,
                Message = "Order does not exist"
            };
        }

        return new OrderStatusResponse
        {
            Exists = true,
            OrderId = order.OrderId,
            Status = (int)order.Status,
            FilledQuantity = (double)order.FilledQuantity,
            FillPrice = (double)order.FillPrice,
            FilledAt = order.FilledAt?.ToString("O") ?? "",
            Message = "Order status query successful"
        };
    }

    public override async Task<PositionResponse> GetPosition(PositionRequest request, ServerCallContext context)
    {
        var position = await _positionManager.GetPositionAsync(request.SessionId, request.Symbol);

        if (position == null)
        {
            return new PositionResponse
            {
                Quantity = 0,
                AvgPrice = 0,
                UnrealizedPnl = 0,
                RealizedPnl = 0,
                MarketValue = 0,
                HasPosition = false
            };
        }

        return new PositionResponse
        {
            Quantity = (double)position.Quantity,
            AvgPrice = (double)position.AvgPrice,
            UnrealizedPnl = (double)position.UnrealizedPnL,
            RealizedPnl = (double)position.RealizedPnL,
            MarketValue = (double)position.MarketValue,
            HasPosition = position.HasPosition
        };
    }

    public override async Task<AllPositionsResponse> GetAllPositions(AllPositionsRequest request, ServerCallContext context)
    {
        var positions = await _positionManager.GetAllPositionsAsync(request.SessionId);

        var response = new AllPositionsResponse();
        foreach (var position in positions)
        {
            response.Positions.Add(new PositionResponse
            {
                Quantity = (double)position.Quantity,
                AvgPrice = (double)position.AvgPrice,
                UnrealizedPnl = (double)position.UnrealizedPnL,
                RealizedPnl = (double)position.RealizedPnL,
                MarketValue = (double)position.MarketValue,
                HasPosition = position.HasPosition
            });
        }

        return response;
    }

    public override async Task<AccountResponse> GetAccount(AccountRequest request, ServerCallContext context)
    {
        var account = await _accountManager.GetAccountAsync(request.SessionId);

        return new AccountResponse
        {
            SessionId = account.SessionId,
            Cash = (double)account.Cash,
            Equity = (double)account.Equity,
            MarketValue = (double)account.MarketValue,
            TotalPnl = (double)account.TotalPnL,
            TotalTrades = account.TotalTrades,
            TotalCommission = (double)account.TotalCommission,
            InitialCapital = (double)account.InitialCapital,
            Message = "Account info query successful"
        };
    }

    // P0.2: CancelOrder implementation
    public override async Task<CancelOrderResponse> CancelOrder(CancelOrderRequest request, ServerCallContext context)
    {
        var orderId = request.OrderId;
        var sessionId = request.SessionId;

        _logger.LogInformation("CancelOrder: Session={Session}, OrderId={OrderId}", sessionId, orderId);

        try
        {
            var order = await _positionManager.GetOrderAsync(sessionId, orderId);
            if (order == null)
            {
                return new CancelOrderResponse
                {
                    OrderId = orderId,
                    Status = (int)OrderStatus.Pending,
                    FilledQuantity = 0,
                    Message = "Order not found"
                };
            }

            // Terminal orders cannot be cancelled
            if (order.Status is OrderStatus.Filled or OrderStatus.Cancelled
                or OrderStatus.Rejected or OrderStatus.Expired)
            {
                return new CancelOrderResponse
                {
                    OrderId = order.OrderId,
                    Status = (int)order.Status,
                    FilledQuantity = (double)order.FilledQuantity,
                    Message = $"Cannot cancel order in terminal status {order.Status}"
                };
            }

            // Call adapter to cancel order
            var adapterOk = await _executionAdapter.CancelOrderAsync(order.OrderId, sessionId);
            if (!adapterOk)
            {
                return new CancelOrderResponse
                {
                    OrderId = order.OrderId,
                    Status = (int)order.Status,
                    FilledQuantity = (double)order.FilledQuantity,
                    Message = "Adapter refused cancel"
                };
            }

            // Update order status to Cancelled, preserve filled quantity
            var previouslyFilled = order.FilledQuantity;
            order.Status = OrderStatus.Cancelled;
            order.RemainingQuantity = order.Quantity - order.FilledQuantity;
            if (order.FilledAt == null && previouslyFilled > 0)
            {
                order.FilledAt = DateTime.UtcNow;
            }
            await _positionManager.UpdatePositionAsync(
                sessionId, order,
                fills: Array.Empty<ExecutionService.Models.Fill>());

            _logger.LogInformation(
                "Order cancelled: {OrderId}, previously filled={Filled}",
                order.OrderId, previouslyFilled);

            return new CancelOrderResponse
            {
                OrderId = order.OrderId,
                Status = (int)order.Status,
                FilledQuantity = (double)previouslyFilled,
                Message = "Cancelled"
            };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "CancelOrder failed: {OrderId}", orderId);
            return new CancelOrderResponse
            {
                OrderId = orderId,
                Status = (int)OrderStatus.Pending,
                Message = ex.Message
            };
        }
    }

    // P1.2: SubscribeOrderUpdates stream
    public override async Task SubscribeOrderUpdates(
        OrderUpdatesSubscribeRequest request,
        IServerStreamWriter<OrderUpdate> responseStream,
        ServerCallContext context)
    {
        _logger.LogInformation(
            "Client subscribed to OrderUpdates: Session={Session}, OrderIds={Count}",
            request.SessionId, request.OrderIds.Count);

        var filterOrderIds = request.OrderIds.ToList();
        try
        {
            await foreach (var evt in _orderUpdateChannel.ReadAllAsync(context.CancellationToken))
            {
                if (evt.SessionId != request.SessionId)
                    continue;
                if (filterOrderIds.Count > 0 && !filterOrderIds.Contains(evt.OrderId))
                    continue;

                var update = new OrderUpdate
                {
                    SessionId = evt.SessionId,
                    OrderId = evt.OrderId,
                    Status = evt.Status,
                    FilledQuantity = evt.FilledQuantity,
                    RemainingQuantity = evt.RemainingQuantity,
                    AvgFillPrice = evt.AvgFillPrice,
                    Message = evt.Message ?? "",
                    Timestamp = evt.Timestamp
                };

                if (evt.LastFill != null)
                {
                    update.LastFill = new FillDetail
                    {
                        Quantity = evt.LastFill.Quantity,
                        Price = evt.LastFill.Price,
                        BrokerFillId = evt.LastFill.BrokerFillId ?? ""
                    };
                }

                await responseStream.WriteAsync(update);
            }
        }
        catch (OperationCanceledException)
        {
            _logger.LogInformation("Client cancelled OrderUpdates subscription: {SessionId}", request.SessionId);
        }
    }

    // P2.2: ExpireDayOrders — no built-in scheduler, triggered externally
    public override async Task<ExpireDayOrdersResponse> ExpireDayOrders(
        ExpireDayOrdersRequest request, ServerCallContext context)
    {
        var sessionId = request.SessionId;
        DateOnly tradeDate = !string.IsNullOrEmpty(request.TradeDate)
            ? DateOnly.Parse(request.TradeDate)
            : DateOnly.FromDateTime(DateTime.UtcNow);

        _logger.LogInformation(
            "ExpireDayOrders: Session={Session}, TradeDate={Date}",
            string.IsNullOrEmpty(sessionId) ? "(all)" : sessionId, tradeDate);

        var allOrders = new List<Order>();
        if (string.IsNullOrEmpty(sessionId))
        {
            // All sessions: pull via each session. PositionManager currently only supports per-session lookup.
            // Simplified handling: if sessionId is empty, only query all visible orders.
            // True all-session scan requires interface extension; here we return 0 + warning.
            _logger.LogWarning("ExpireDayOrders with empty session_id is not supported via PositionManager; please specify session_id");
            return new ExpireDayOrdersResponse { ExpiredCount = 0 };
        }
        allOrders = await _positionManager.GetAllOrdersAsync(sessionId);

        var toExpire = allOrders
            .Where(o => o.Status is OrderStatus.Pending or OrderStatus.Partial)
            .Where(o => o.TimeInForce == TimeInForce.Day)
            .Where(o => DateOnly.FromDateTime(o.CreatedAt) <= tradeDate)
            .ToList();

        var expiredIds = new List<string>();
        foreach (var order in toExpire)
        {
            order.Status = OrderStatus.Expired;
            order.RemainingQuantity = order.Quantity - order.FilledQuantity;
            await _positionManager.UpdatePositionAsync(
                sessionId, order,
                fills: Array.Empty<ExecutionService.Models.Fill>());
            expiredIds.Add(order.OrderId);
        }

        _logger.LogInformation(
            "ExpireDayOrders done: expired {Count} orders, TradeDate={Date}",
            expiredIds.Count, tradeDate);

        return new ExpireDayOrdersResponse
        {
            ExpiredCount = expiredIds.Count,
            ExpiredOrderIds = { expiredIds }
        };
    }

    public override async Task<PnLUpdateResponse> SubscribePnLUpdates(PnLSubscribeRequest request,
        IServerStreamWriter<PnLUpdate> responseStream, ServerCallContext context)
    {
        _logger.LogInformation("Client subscribed to PnL updates: {SessionId}", request.SessionId);

        try
        {
            while (!context.CancellationToken.IsCancellationRequested)
            {
                await Task.Delay(request.IntervalMs > 0 ? request.IntervalMs : 1000, context.CancellationToken);

                var account = await _accountManager.GetAccountAsync(request.SessionId);
                var positions = await _positionManager.GetAllPositionsAsync(request.SessionId);

                var pnlUpdate = new PnLUpdate
                {
                    Timestamp = DateTime.UtcNow.ToString("O"),
                    TotalPnl = (double)account.TotalPnL,
                    UnrealizedPnl = (double)positions.Sum(p => p.UnrealizedPnL),
                    RealizedPnl = (double)positions.Sum(p => p.RealizedPnL),
                    Equity = (double)account.Equity
                };

                await responseStream.WriteAsync(pnlUpdate);
            }
        }
        catch (OperationCanceledException)
        {
            _logger.LogInformation("Client cancelled PnL subscription: {SessionId}", request.SessionId);
        }

        return new PnLUpdateResponse { Success = true, Message = "Subscription ended" };
    }

    private OrderResponse MapOrderResponse(Order order, int fillCount = 0)
    {
        return new OrderResponse
        {
            OrderId = order.OrderId,
            Status = (int)order.Status,
            FilledQuantity = (double)order.FilledQuantity,
            FillPrice = (double)order.FillPrice,
            Commission = (double)order.Commission,
            FilledAt = order.FilledAt?.ToString("O") ?? "",
            Message = order.Status == OrderStatus.Filled ? "Order filled" : order.Reason,
            RemainingQuantity = (double)Math.Max(0m, order.Quantity - order.FilledQuantity),
            FillCount = fillCount
        };
    }
}