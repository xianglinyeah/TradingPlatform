using System.Collections.Concurrent;
using ExecutionService.Models;
using ExecutionService.Core.Services;
using ExecutionService.Core.Events;
using ExecutionService.Data.IRepositories;
using ExecutionService.Data.Repositories;
using ExecutionService.Core.Utils;

namespace ExecutionService.Core.Services;

/// <summary>
/// Position manager (refactored in P0.3 / P1.2)
///
/// Key changes:
///   - Each Fill is processed individually: position incremental update + 1 Trade row + 1 OrderUpdate event
///   - Old implementation aggregated all fills into a single Trade, losing per-fill detail; deprecated
/// </summary>
public class PositionManager : IPositionManager
{
    private readonly ILogger<PositionManager> _logger;
    private readonly IPositionRepository _positionRepository;
    private readonly IOrderRepository _orderRepository;
    private readonly ITradeRepository _tradeRepository;
    private readonly OrderUpdateChannel _orderUpdateChannel;
    // Per-(session, symbol) lock to serialise position updates. gRPC requests run
    // concurrently on separate threads; without this, two orders on the same symbol
    // would race on GetPosition → UpdatePosition and one overwrite the other.
    //
    // Bounded growth: when the waiters drop to zero we attempt to remove the
    // entry under a lock (only the last releaser may remove). This prevents
    // the dictionary from growing unboundedly across long runs that span
    // many sessions/symbols (the previous implementation leaked one
    // SemaphoreSlim per (session, symbol) tuple forever).
    private static readonly ConcurrentDictionary<(string SessionId, string Symbol), SemaphoreSlim> _locks = new();
    private static int _activeWaiters;

    private static SemaphoreSlim GetLock(string sessionId, string symbol)
        => _locks.GetOrAdd((sessionId, symbol), _ => new SemaphoreSlim(1, 1));

    private static void ReleaseAndMaybeCleanup(string sessionId, string symbol, SemaphoreSlim sem)
    {
        sem.Release();
        // Best-effort cleanup: only the last releaser (CurrentCount returns to 1)
        // attempts TryRemove. Race-safe because ConcurrentDictionary.TryRemove
        // is atomic; if a new GetLock happens concurrently we may remove an entry
        // that's about to be re-added — that's fine, GetOrAdd creates a fresh one.
        if (sem.CurrentCount == 1)
        {
            Interlocked.Increment(ref _activeWaiters);
            try
            {
                if (_locks.Count > 1024)  // hysteresis: don't churn on small dicts
                {
                    _locks.TryRemove((sessionId, symbol), out _);
                }
            }
            finally
            {
                Interlocked.Decrement(ref _activeWaiters);
            }
        }
    }

    public PositionManager(
        ILogger<PositionManager> logger,
        IPositionRepository positionRepository,
        IOrderRepository orderRepository,
        ITradeRepository tradeRepository,
        OrderUpdateChannel orderUpdateChannel)
    {
        _logger = logger;
        _positionRepository = positionRepository;
        _orderRepository = orderRepository;
        _tradeRepository = tradeRepository;
        _orderUpdateChannel = orderUpdateChannel;
    }

    public async Task<Position?> GetPositionAsync(string sessionId, string symbol)
    {
        _logger.LogInformation("GetPositionAsync called: SessionId={SessionId}, Symbol={Symbol}", sessionId, symbol);
        var position = await _positionRepository.GetPositionAsync(sessionId, symbol);

        if (position != null)
        {
            _logger.LogInformation("Position query result: Found=True, Qty={Qty}, AvgPrice={AvgPrice}",
                position.Quantity, position.AvgPrice);
        }
        else
        {
            _logger.LogInformation("Position query result: Found=False");
        }

        return position;
    }

    public async Task<List<Position>> GetAllPositionsAsync(string sessionId)
    {
        return await _positionRepository.GetPositionsBySessionAsync(sessionId);
    }

    /// <summary>
    /// Process order fills by looping over each fill (refactored in P0.3)
    ///
    /// Semantics: order.FilledQuantity ultimately = Sum(fills.Quantity)
    /// On entry, order.FilledQuantity is reset to zero and accumulated within the loop,
    /// to avoid duplicate setting between adapter and this method.
    /// </summary>
    public async Task UpdatePositionAsync(string sessionId, Order order, IReadOnlyList<Fill> fills)
    {
        _logger.LogInformation(
            "UpdatePositionAsync called: SessionId={SessionId}, Symbol={Symbol}, Side={Side}, OrderQty={OrderQty}, FillsCount={FillsCount}",
            sessionId, order.Symbol, order.Side, order.Quantity, fills.Count);

        // Terminal but no fills (Rejected/Cancelled-no-fill/Expired) — only save order + publish OrderUpdate
        if (fills.Count == 0)
        {
            order.RemainingQuantity = order.Quantity - order.FilledQuantity;
            await _orderRepository.CreateOrderAsync(order);
            await PublishOrderUpdateAsync(order, lastFill: null, message: order.Reason);
            return;
        }

        // Serialise updates per (session, symbol) to prevent lost updates when two
        // orders arrive concurrently on the same symbol.
        var sem = GetLock(sessionId, order.Symbol);
        await sem.WaitAsync();
        try
        {
            await UpdatePositionCoreAsync(sessionId, order, fills);
        }
        finally
        {
            ReleaseAndMaybeCleanup(sessionId, order.Symbol, sem);
        }
    }

    private async Task UpdatePositionCoreAsync(string sessionId, Order order, IReadOnlyList<Fill> fills)
    {
        // Key: reset to zero so the += in the loop does not double-count
        order.FilledQuantity = 0m;

        var position = await _positionRepository.GetPositionAsync(sessionId, order.Symbol);
        if (position == null)
        {
            position = new Position
            {
                Symbol = order.Symbol,
                SessionId = sessionId,
                Quantity = 0,
                AvgPrice = 0,
                Side = PositionSide.Long
            };
            _logger.LogInformation("Creating new position: {Symbol}", order.Symbol);
        }

        // Accumulate commission and weighted average price
        decimal accumulatedCommission = 0m;
        decimal weightedSum = 0m; // price * qty
        decimal totalFilledThisCall = 0m;

        // Save order first so Order.Id is available when creating Trades in the fill loop.
        // Update is called again at the end with final state.
        order.RemainingQuantity = order.Quantity - order.FilledQuantity;
        var savedOrder = await _orderRepository.CreateOrderAsync(order);

        int fillSeq = 0;
        foreach (var fill in fills)
        {
            fillSeq++;
            accumulatedCommission += fill.Commission;

            if (order.Side == OrderSide.Buy)
            {
                position.Add(fill.Quantity, fill.Price, fill.Commission);
            }
            else
            {
                position.Reduce(fill.Quantity, fill.Price, fill.Commission);
            }

            weightedSum += fill.Price * fill.Quantity;
            totalFilledThisCall += fill.Quantity;

            var trade = new Trade
            {
                SessionId = order.SessionId,
                OrderId = savedOrder.Id,
                Symbol = order.Symbol,
                Side = order.Side.ToString().ToLower(),
                Quantity = fill.Quantity,
                Price = fill.Price,
                Commission = fill.Commission,
                TradeTime = fill.FillTime,
                SignalId = order.OrderId,
                ExecutionMode = order.ExecutionMode,
                FillSeq = fillSeq,
                BrokerFillId = fill.BrokerFillId
            };
            await _tradeRepository.CreateTradeAsync(trade);

            _logger.LogInformation(
                "Created trade: TradeId={TradeId}, Symbol={Symbol}, Side={Side}, FillSeq={FillSeq}, Qty={Qty}, Price={Price}, BrokerFillId={BrokerFillId}",
                trade.TradeId, trade.Symbol, trade.Side, fillSeq, trade.Quantity, trade.Price, trade.BrokerFillId ?? "(null)");

            // Publish OrderUpdate for each fill
            order.FilledQuantity += fill.Quantity;
            order.RemainingQuantity = order.Quantity - order.FilledQuantity;
            // Terminal status is set by adapter; here only the per-fill event status is updated.
            await PublishOrderUpdateAsync(
                order,
                lastFill: new FillDetailEvent
                {
                    Quantity = (double)fill.Quantity,
                    Price = (double)fill.Price,
                    BrokerFillId = fill.BrokerFillId
                },
                message: $"Fill #{fillSeq}");
        }

        if (position.Id == 0)
        {
            await _positionRepository.CreatePositionAsync(position);
        }
        else
        {
            await _positionRepository.UpdatePositionAsync(position);
        }

        _logger.LogInformation(
            "Position update completed: {Symbol} FinalQty={FinalQty}, AvgPrice={AvgPrice}",
            order.Symbol, position.Quantity, position.AvgPrice);

        // Second verification: recompute average price / filled quantity from fills.
        if (totalFilledThisCall > 0)
        {
            order.FillPrice = weightedSum / totalFilledThisCall;
        }

        order.Commission = accumulatedCommission;
        // FilledQuantity already accumulated within the loop above.
        order.RemainingQuantity = order.Quantity - order.FilledQuantity;
        await _orderRepository.UpdateOrderAsync(order);

        // Publish terminal OrderUpdate (summary event)
        await PublishOrderUpdateAsync(order, lastFill: null, message: $"Terminal: {order.Status}");
    }

    public async Task CloseAllPositionsAsync(string sessionId)
    {
        var positions = await _positionRepository.GetPositionsBySessionAsync(sessionId);
        foreach (var position in positions)
        {
            await _positionRepository.DeletePositionAsync(sessionId, position.Symbol);
        }
        _logger.LogInformation("Closing all positions: {SessionId}", sessionId);
    }

    public async Task<Order?> GetOrderAsync(string sessionId, string orderId)
    {
        return await _orderRepository.GetOrderAsync(sessionId, orderId);
    }

    public async Task<List<Order>> GetAllOrdersAsync(string sessionId)
    {
        return await _orderRepository.GetOrdersBySessionAsync(sessionId);
    }

    /// <summary>
    /// Publish OrderUpdate event to channel (P1.2)
    /// </summary>
    private async Task PublishOrderUpdateAsync(Order order, FillDetailEvent? lastFill, string? message)
    {
        var evt = new OrderUpdateEvent
        {
            SessionId = order.SessionId,
            OrderId = order.OrderId,
            Status = (int)order.Status,
            FilledQuantity = (double)order.FilledQuantity,
            RemainingQuantity = (double)Math.Max(0m, order.Quantity - order.FilledQuantity),
            AvgFillPrice = (double)order.FillPrice,
            LastFill = lastFill,
            Message = message,
            Timestamp = DateTime.UtcNow.ToString("O")
        };
        try
        {
            await _orderUpdateChannel.WriteAsync(evt);
        }
        catch (Exception ex)
        {
            // Channel write failure should not affect order flow
            _logger.LogWarning(ex, "Failed to publish OrderUpdate for {OrderId}", order.OrderId);
        }
    }
}
