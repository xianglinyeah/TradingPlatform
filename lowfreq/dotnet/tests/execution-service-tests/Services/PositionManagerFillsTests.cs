using Moq;
using Microsoft.Extensions.Logging;
using ExecutionService.Models;
using ExecutionService.Core.Services;
using ExecutionService.Core.Events;
using ExecutionService.Data.IRepositories;
using Xunit;

namespace ExecutionService.Tests.Services;

/// <summary>
/// PositionManager fills loop logic unit test (P0.3)
///
/// Covers new signature UpdatePositionAsync(sessionId, order, fills):
///   - Empty fills: only save order + push OrderUpdate, no Trade created
///   - Single fill: 1 Trade, fill_seq=1
///   - Multi fill: N Trades, fill_seq=1..N
///   - Invariant: order.FilledQuantity=Sum(fills), order.FillPrice=weighted average price
///   - Buy/sell direction: position.Add / position.Reduce
///   - OrderUpdate event push count = fills.Count + 1 (each fill + terminal state)
/// </summary>
public class PositionManagerFillsTests
{
    private readonly Mock<IPositionRepository> _mockPositionRepo;
    private readonly Mock<IOrderRepository> _mockOrderRepo;
    private readonly Mock<ITradeRepository> _mockTradeRepo;
    private readonly OrderUpdateChannel _channel;
    private readonly PositionManager _pm;

    public PositionManagerFillsTests()
    {
        _mockPositionRepo = new Mock<IPositionRepository>();
        _mockOrderRepo = new Mock<IOrderRepository>();
        _mockTradeRepo = new Mock<ITradeRepository>();
        _channel = new OrderUpdateChannel();
        _pm = new PositionManager(
            Mock.Of<ILogger<PositionManager>>(),
            _mockPositionRepo.Object,
            _mockOrderRepo.Object,
            _mockTradeRepo.Object,
            _channel);

        // Default: CreateOrderAsync sets Id for Trade reference
        _mockOrderRepo
            .Setup(r => r.CreateOrderAsync(It.IsAny<Order>()))
            .ReturnsAsync((Order o) => { o.Id = 42; return o; });
        _mockPositionRepo
            .Setup(r => r.GetPositionAsync(It.IsAny<string>(), It.IsAny<string>()))
            .ReturnsAsync((Position?)null);
    }

    private static Order MakeOrder(int qty = 1000, OrderSide side = OrderSide.Buy) => new()
    {
        OrderId = "order-1",
        SessionId = "session-1",
        Symbol = "600000.SH",
        Side = side,
        Quantity = qty,
        Price = 10m,
        Status = OrderStatus.Filled
    };

    private static Fill Fill(decimal qty, decimal price, decimal commission = 0m, DateTime? time = null) => new()
    {
        Quantity = qty,
        Price = price,
        Commission = commission,
        FillTime = time ?? DateTime.UtcNow,
        BrokerFillId = null
    };

    // ===== Empty fills =====

    [Fact]
    public async Task EmptyFills_CreatesOrder_NoTrade_PublishesUpdate()
    {
        var order = MakeOrder();
        order.Status = OrderStatus.Cancelled; // terminal state, no fill
        var tradesCaptured = new List<Trade>();
        _mockTradeRepo
            .Setup(r => r.CreateTradeAsync(It.IsAny<Trade>()))
            .Callback<Trade>(t => tradesCaptured.Add(t))
            .ReturnsAsync((Trade t) => t);

        await _pm.UpdatePositionAsync("session-1", order, Array.Empty<Fill>());

        // 1. Order saved
        _mockOrderRepo.Verify(r => r.CreateOrderAsync(order), Times.Once);
        // 2. No Trade created
        Assert.Empty(tradesCaptured);
        // 3. Push an OrderUpdate (terminal event)
        var update = await ReadNextUpdateAsync();
        Assert.Equal("session-1", update.SessionId);
        Assert.Equal("order-1", update.OrderId);
        Assert.Equal((int)OrderStatus.Cancelled, update.Status);
    }

    // ===== Single fill =====

    [Fact]
    public async Task SingleFill_CreatesOneTrade_WithFillSeq1()
    {
        var order = MakeOrder();
        var tradesCaptured = new List<Trade>();
        _mockTradeRepo
            .Setup(r => r.CreateTradeAsync(It.IsAny<Trade>()))
            .Callback<Trade>(t => tradesCaptured.Add(t))
            .ReturnsAsync((Trade t) => t);

        await _pm.UpdatePositionAsync("session-1", order,
            new[] { Fill(1000, 10.5m, commission: 5m) });

        Assert.Single(tradesCaptured);
        Assert.Equal(1, tradesCaptured[0].FillSeq);
        Assert.Equal(1000m, tradesCaptured[0].Quantity);
        Assert.Equal(10.5m, tradesCaptured[0].Price);
        Assert.Equal(5m, tradesCaptured[0].Commission);
        Assert.Equal(42L, tradesCaptured[0].OrderId); // references savedOrder.Id
    }

    // ===== Multi fill =====

    [Fact]
    public async Task MultiFill_CreatesNTrades_WithSequentialFillSeq()
    {
        var order = MakeOrder(qty: 3000);
        var tradesCaptured = new List<Trade>();
        _mockTradeRepo
            .Setup(r => r.CreateTradeAsync(It.IsAny<Trade>()))
            .Callback<Trade>(t => tradesCaptured.Add(t))
            .ReturnsAsync((Trade t) => t);

        var fills = new[]
        {
            Fill(1000, 10.0m, commission: 2m),
            Fill(1000, 10.1m, commission: 2m),
            Fill(1000, 10.2m, commission: 2m)
        };

        await _pm.UpdatePositionAsync("session-1", order, fills);

        Assert.Equal(3, tradesCaptured.Count);
        Assert.Equal(new[] { 1, 2, 3 }, tradesCaptured.Select(t => t.FillSeq).ToArray());
        Assert.Equal(10.0m, tradesCaptured[0].Price);
        Assert.Equal(10.1m, tradesCaptured[1].Price);
        Assert.Equal(10.2m, tradesCaptured[2].Price);
    }

    // ===== Invariant: order cumulative fields =====

    [Fact]
    public async Task AfterUpdate_OrderFilledQuantity_EqualsSumOfFills()
    {
        // Before entry order.FilledQuantity may have a value (adapter single-fill path sets it)
        // PositionManager zeroes it on entry then accumulates, final = Sum(fills)
        var order = MakeOrder(qty: 5000);
        order.FilledQuantity = 5000; // simulate adapter having set it
        order.FillPrice = 10.5m;

        var fills = new[]
        {
            Fill(2000, 10.0m),
            Fill(1500, 10.5m),
            Fill(1500, 11.0m)
        };

        await _pm.UpdatePositionAsync("session-1", order, fills);

        // FilledQuantity should equal Sum(fills.Quantity), not order.Quantity
        Assert.Equal(5000m, order.FilledQuantity);
        // RemainingQuantity should equal Quantity - FilledQuantity
        Assert.Equal(0m, order.RemainingQuantity);
    }

    [Fact]
    public async Task AfterUpdate_OrderFillPrice_IsWeightedAverage()
    {
        var order = MakeOrder(qty: 3000);

        var fills = new[]
        {
            Fill(1000, 10.0m),  // 10000
            Fill(1000, 11.0m),  // 11000
            Fill(1000, 12.0m)   // 12000
        };
        // weighted average price = (10*1000 + 11*1000 + 12*1000) / 3000 = 33000/3000 = 11.0

        await _pm.UpdatePositionAsync("session-1", order, fills);

        Assert.Equal(11.0m, order.FillPrice);
    }

    [Fact]
    public async Task AfterUpdate_OrderCommission_IsSumOfFillCommissions()
    {
        var order = MakeOrder(qty: 2000);

        var fills = new[]
        {
            Fill(1000, 10.0m, commission: 3m),
            Fill(1000, 10.5m, commission: 4m)
        };

        await _pm.UpdatePositionAsync("session-1", order, fills);

        Assert.Equal(7m, order.Commission);
    }

    // ===== Buy/sell direction =====

    [Fact]
    public async Task BuyFill_IncreasesPositionQuantity()
    {
        var existingPosition = new Position
        {
            Id = 1,
            SessionId = "session-1",
            Symbol = "600000.SH",
            Quantity = 1000,
            AvgPrice = 10m,
            Side = PositionSide.Long
        };
        _mockPositionRepo
            .Setup(r => r.GetPositionAsync("session-1", "600000.SH"))
            .ReturnsAsync(existingPosition);

        var order = MakeOrder(qty: 500, OrderSide.Buy);
        await _pm.UpdatePositionAsync("session-1", order, new[] { Fill(500, 12.0m, commission: 1m) });

        Assert.Equal(1500m, existingPosition.Quantity);
        _mockPositionRepo.Verify(r => r.UpdatePositionAsync(existingPosition), Times.Once);
    }

    [Fact]
    public async Task SellFill_ReducesPosition_AndUpdatesRealizedPnl()
    {
        var existingPosition = new Position
        {
            Id = 1,
            SessionId = "session-1",
            Symbol = "600000.SH",
            Quantity = 1000,
            AvgPrice = 10m,
            Side = PositionSide.Long,
            RealizedPnL = 0
        };
        _mockPositionRepo
            .Setup(r => r.GetPositionAsync("session-1", "600000.SH"))
            .ReturnsAsync(existingPosition);

        var order = MakeOrder(qty: 500, OrderSide.Sell);
        order.Side = OrderSide.Sell;
        await _pm.UpdatePositionAsync("session-1", order, new[] { Fill(500, 12.0m, commission: 1m) });

        Assert.Equal(500m, existingPosition.Quantity);
        // realized PnL = (12 * 500 - 1) - (10 * 500) = 5999 - 5000 = 999
        Assert.Equal(999m, existingPosition.RealizedPnL);
    }

    // ===== OrderUpdate push count =====

    [Fact]
    public async Task OrderUpdatePublished_ForEachFillPlusTerminalEvent()
    {
        var order = MakeOrder(qty: 3000);
        var fills = new[]
        {
            Fill(1000, 10.0m),
            Fill(1000, 10.5m),
            Fill(1000, 11.0m)
        };

        await _pm.UpdatePositionAsync("session-1", order, fills);

        // Should push fills.Count + 1 events (one per fill + terminal summary)
        var updates = await DrainAllUpdatesAsync();
        Assert.Equal(4, updates.Count);

        // First 3 should have last_fill
        Assert.NotNull(updates[0].LastFill);
        Assert.NotNull(updates[1].LastFill);
        Assert.NotNull(updates[2].LastFill);
        // Last one is terminal event, no last_fill
        Assert.Null(updates[3].LastFill);
        Assert.Contains("Terminal", updates[3].Message ?? "");
    }

    [Fact]
    public async Task OrderUpdate_LastFillCarries_BrokerFillId()
    {
        var order = MakeOrder(qty: 1000);
        var fills = new[]
        {
            new Fill { Quantity = 1000, Price = 10m, FillTime = DateTime.UtcNow, BrokerFillId = "GM-EXEC-12345", Commission = 5m }
        };

        await _pm.UpdatePositionAsync("session-1", order, fills);

        var updates = await DrainAllUpdatesAsync();
        Assert.NotEmpty(updates);
        var firstFillUpdate = updates.First(u => u.LastFill != null);
        Assert.Equal("GM-EXEC-12345", firstFillUpdate.LastFill!.BrokerFillId);
    }

    [Fact]
    public async Task Trade_Carries_BrokerFillId()
    {
        var tradesCaptured = new List<Trade>();
        _mockTradeRepo
            .Setup(r => r.CreateTradeAsync(It.IsAny<Trade>()))
            .Callback<Trade>(t => tradesCaptured.Add(t))
            .ReturnsAsync((Trade t) => t);

        var order = MakeOrder();
        var fills = new[]
        {
            new Fill { Quantity = 1000, Price = 10m, FillTime = DateTime.UtcNow, BrokerFillId = "GM-EXEC-67890", Commission = 5m }
        };

        await _pm.UpdatePositionAsync("session-1", order, fills);

        Assert.Single(tradesCaptured);
        Assert.Equal("GM-EXEC-67890", tradesCaptured[0].BrokerFillId);
    }

    // ===== Helper: read events from channel =====

    private async Task<OrderUpdateEvent> ReadNextUpdateAsync(TimeSpan? timeout = null)
    {
        using var cts = new CancellationTokenSource(timeout ?? TimeSpan.FromSeconds(2));
        await foreach (var u in _channel.ReadAllAsync(cts.Token))
            return u;
        throw new InvalidOperationException("No update event was published");
    }

    private async Task<List<OrderUpdateEvent>> DrainAllUpdatesAsync(TimeSpan? timeout = null)
    {
        var result = new List<OrderUpdateEvent>();
        using var cts = new CancellationTokenSource(timeout ?? TimeSpan.FromSeconds(2));
        try
        {
            await foreach (var u in _channel.ReadAllAsync(cts.Token))
            {
                result.Add(u);
                if (result.Count > 100) break; // safety
            }
        }
        catch (OperationCanceledException) { }
        // Channel is unbounded, needs active cancellation; here we give enough time for all events to be written
        // PositionManager has already await-ed all channel.WriteAsync before returning
        return result;
    }
}
