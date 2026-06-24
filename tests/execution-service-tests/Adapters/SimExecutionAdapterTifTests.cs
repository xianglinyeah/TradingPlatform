using Moq;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using ExecutionService.Models;
using ExecutionService.Core.Adapters;
using ExecutionService.Core.Services;
using ExecutionService.Models;
using Xunit;

namespace ExecutionService.Tests.Adapters;

/// <summary>
/// SimExecutionAdapter TimeInForce behavior unit test (P2.1)
///
/// Covers:
///   - Day + small order -> Filled (single fill)
///   - Day + large order -> Partial or Filled (split but all filled)
///   - IOC + small order -> Filled (no remaining to cancel)
///   - IOC + large order -> Cancelled (cancel remaining immediately) - but simulated matching may fill all, could also be Filled
///   - FOK + small order -> Filled (sufficient liquidity)
///   - FOK + large order -> Rejected (insufficient liquidity)
///   - Default TIF (Day=0) behavior equivalent to explicit Day
///
/// Configuration: partial fill enabled in tests to reveal large/small order differences
/// </summary>
public class SimExecutionAdapterTifTests
{
    private readonly Mock<IPnLCalculator> _mockPnL;
    private readonly Mock<IRiskManager> _mockRisk;
    private readonly Mock<IAccountManager> _mockAccount;
    private readonly Mock<ILogger<SimExecutionAdapter>> _mockLogger;

    public SimExecutionAdapterTifTests()
    {
        _mockPnL = new Mock<IPnLCalculator>();
        _mockRisk = new Mock<IRiskManager>();
        _mockAccount = new Mock<IAccountManager>();
        _mockLogger = new Mock<ILogger<SimExecutionAdapter>>();

        // RiskCheck passes
        _mockRisk
            .Setup(r => r.CheckOrderRiskAsync(It.IsAny<Order>()))
            .ReturnsAsync(new RiskCheckResult(true));
    }

    /// <summary>
    /// Adapter with partial fill enabled (real algorithm behavior, can observe large order splitting)
    /// </summary>
    private SimExecutionAdapter CreateAdapter(int maxFills = 5)
    {
        var settings = Options.Create(new ExecutionSettings
        {
            SimEnablePartialFill = true,
            SimDefaultAvgDailyVolume = 1_000_000,
            SimMaxPartialFills = maxFills,
            SimLargeOrderVolumeRatio = 0.001
        });
        return new SimExecutionAdapter(
            _mockPnL.Object, _mockRisk.Object, _mockAccount.Object,
            settings, _mockLogger.Object);
    }

    private static MarketData Md(decimal close = 100m) => new()
    {
        Symbol = "600000.SH",
        Close = close,
        Timestamp = DateTime.UtcNow
    };

    private static Order Order(int qty, OrderSide side = OrderSide.Buy, TimeInForce tif = TimeInForce.Day) => new()
    {
        OrderId = "tif-test",
        SessionId = "session-1",
        Symbol = "600000.SH",
        Side = side,
        OrderType = OrderType.Market,
        Quantity = qty,
        Price = 100m,
        Status = OrderStatus.Pending,
        TimeInForce = tif
    };

    // ===== Day TIF =====

    [Fact]
    public async Task DayTif_SmallOrder_Filled_SingleFill()
    {
        // 100 shares / 1M = 0.01% < 0.1%, no split
        var adapter = CreateAdapter();
        var order = Order(100);

        var result = await adapter.ExecuteOrderAsync(order, Md());

        Assert.Equal(OrderStatus.Filled, result.Order.Status);
        Assert.Single(result.Fills);
        Assert.Equal(100m, result.Order.FilledQuantity);
        Assert.Equal(0m, result.Order.RemainingQuantity);
    }

    [Fact]
    public async Task DayTif_LargeOrder_PartialOrFilled_AllQuantityConsumed()
    {
        // 50000 / 1M = 5%, split into 5 fills, all filled -> Filled
        var adapter = CreateAdapter();
        var order = Order(50_000);

        var result = await adapter.ExecuteOrderAsync(order, Md());

        // After splitting, all can be filled (algorithm fallback absorbs remainder in last fill) -> Filled
        Assert.Equal(OrderStatus.Filled, result.Order.Status);
        Assert.True(result.Fills.Count >= 2, $"Should split into multiple fills, actual {result.Fills.Count}");
        Assert.Equal(50_000m, result.Fills.Sum(f => f.Quantity));
        Assert.Equal(50_000m, result.Order.FilledQuantity);
    }

    // ===== FOK TIF =====

    [Fact]
    public async Task FokTif_SmallOrder_Filled()
    {
        // Small order does not trigger split -> considered sufficient liquidity -> Filled
        var adapter = CreateAdapter();
        var order = Order(100, tif: TimeInForce.FOK);

        var result = await adapter.ExecuteOrderAsync(order, Md());

        Assert.Equal(OrderStatus.Filled, result.Order.Status);
        Assert.Single(result.Fills);
    }

    [Fact]
    public async Task FokTif_LargeOrder_Rejected_InsufficientLiquidity()
    {
        // Large order triggers split -> FOK considers liquidity insufficient for full fill -> Rejected
        // This is the core FOK semantic: fill all or reject all
        var adapter = CreateAdapter();
        var order = Order(50_000, tif: TimeInForce.FOK);

        var result = await adapter.ExecuteOrderAsync(order, Md());

        Assert.Equal(OrderStatus.Rejected, result.Order.Status);
        Assert.Empty(result.Fills);
        Assert.Contains("FOK", result.Order.Reason ?? "");
        Assert.Contains("liquidity", result.Order.Reason ?? "", StringComparison.OrdinalIgnoreCase);
    }

    // ===== IOC TIF =====

    [Fact]
    public async Task IocTif_SmallOrder_Filled()
    {
        // Small order no split -> no remaining to cancel -> Filled
        var adapter = CreateAdapter();
        var order = Order(100, tif: TimeInForce.IOC);

        var result = await adapter.ExecuteOrderAsync(order, Md());

        Assert.Equal(OrderStatus.Filled, result.Order.Status);
        Assert.Single(result.Fills);
    }

    [Fact]
    public async Task IocTif_NeverPending()
    {
        // IOC should never be Pending: either Filled, Partial, or Cancelled
        // Test both small and large order scenarios
        var adapter = CreateAdapter();

        var smallOrder = Order(100, tif: TimeInForce.IOC);
        var smallResult = await adapter.ExecuteOrderAsync(smallOrder, Md());
        Assert.NotEqual(OrderStatus.Pending, smallResult.Order.Status);

        var largeOrder = Order(50_000, tif: TimeInForce.IOC);
        var largeResult = await adapter.ExecuteOrderAsync(largeOrder, Md());
        Assert.NotEqual(OrderStatus.Pending, largeResult.Order.Status);
    }

    // ===== Default TIF =====

    [Fact]
    public async Task DefaultTif_BehavesLikeDay()
    {
        // Not explicitly setting TIF (default Day=0) should be equivalent to explicit Day
        var adapter = CreateAdapter();
        var order = Order(100); // default TimeInForce.Day

        Assert.Equal(TimeInForce.Day, order.TimeInForce); // sanity check

        var result = await adapter.ExecuteOrderAsync(order, Md());

        Assert.Equal(OrderStatus.Filled, result.Order.Status);
    }

    // ===== Cash ledger interaction =====

    [Fact]
    public async Task BuyOrder_DecreasesCash_ByFullNotionalPlusCommission()
    {
        // Regardless of splitting, cash deduction = FilledQuantity * FillPrice + Commission
        var adapter = CreateAdapter();
        var order = Order(1000);

        var result = await adapter.ExecuteOrderAsync(order, Md());

        decimal expectedCost = result.Order.FilledQuantity * result.Order.FillPrice + result.Order.Commission;
        _mockAccount.Verify(a => a.UpdateCashAsync("session-1", -expectedCost), Times.Once);
    }

    [Fact]
    public async Task SellOrder_IncreasesCash_ByNotionalMinusCommission()
    {
        var adapter = CreateAdapter();
        var order = Order(1000, side: OrderSide.Sell);

        var result = await adapter.ExecuteOrderAsync(order, Md());

        decimal expectedProceeds = result.Order.FilledQuantity * result.Order.FillPrice - result.Order.Commission;
        _mockAccount.Verify(a => a.UpdateCashAsync("session-1", expectedProceeds), Times.Once);
    }

    [Fact]
    public async Task Execution_AlwaysIncrementsTradeCount_AndCommission()
    {
        // Each order (regardless of fill count) counts as 1 trade, commission accumulates to account
        var adapter = CreateAdapter();
        var order = Order(50_000);

        var result = await adapter.ExecuteOrderAsync(order, Md());

        _mockAccount.Verify(a => a.IncrementTradeCountAsync("session-1"), Times.Once);
        _mockAccount.Verify(a => a.AddCommissionAsync("session-1", result.Order.Commission), Times.Once);
    }

    [Fact]
    public async Task FokRejected_DoesNotTouchCash()
    {
        // FOK rejected -> no fill -> should not deduct cash, no commission, no trade count increment
        var adapter = CreateAdapter();
        var order = Order(50_000, tif: TimeInForce.FOK);

        var result = await adapter.ExecuteOrderAsync(order, Md());

        Assert.Equal(OrderStatus.Rejected, result.Order.Status);
        _mockAccount.Verify(a => a.UpdateCashAsync(It.IsAny<string>(), It.IsAny<decimal>()), Times.Never);
        _mockAccount.Verify(a => a.AddCommissionAsync(It.IsAny<string>(), It.IsAny<decimal>()), Times.Never);
        _mockAccount.Verify(a => a.IncrementTradeCountAsync(It.IsAny<string>()), Times.Never);
    }

    // ===== Split price increment =====

    [Fact]
    public async Task LargeOrder_PartialFills_PricesIncreasing_ForBuy()
    {
        // Large buy order: each fill price should increase (market impact)
        // Note: algorithm rounds to 2 decimals, use close=100 to make impact visible
        var adapter = CreateAdapter();
        var order = Order(50_000);

        var result = await adapter.ExecuteOrderAsync(order, Md(close: 100m));

        Assert.True(result.Fills.Count >= 2);
        for (int i = 1; i < result.Fills.Count; i++)
        {
            Assert.True(result.Fills[i].Price >= result.Fills[i - 1].Price,
                $"Buy split prices should be increasing: fill[{i - 1}]={result.Fills[i - 1].Price} > fill[{i}]={result.Fills[i].Price}");
        }
    }
}
