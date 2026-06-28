using Moq;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using ExecutionService.Models;
using ExecutionService.Core.Adapters;
using ExecutionService.Core.Services;
using ExecutionService.Core.Utils;
using Xunit;

namespace ExecutionService.Tests.Adapters;

public class SimExecutionAdapterTests
{
    private readonly Mock<IPnLCalculator> _mockPnLCalculator;
    private readonly Mock<IRiskManager> _mockRiskManager;
    private readonly Mock<IAccountManager> _mockAccountManager;
    private readonly Mock<ILogger<SimExecutionAdapter>> _mockLogger;
    private readonly SimExecutionAdapter _adapter;

    public SimExecutionAdapterTests()
    {
        _mockPnLCalculator = new Mock<IPnLCalculator>();
        _mockRiskManager = new Mock<IRiskManager>();
        _mockAccountManager = new Mock<IAccountManager>();
        _mockLogger = new Mock<ILogger<SimExecutionAdapter>>();

        // P1.1: disable partial fill in tests, keep single-fill behavior, avoid split interfering with assertions
        var settings = Options.Create(new ExecutionSettings
        {
            SimEnablePartialFill = false,
            SimDefaultAvgDailyVolume = 1_000_000,
            SimMaxPartialFills = 5,
            SimLargeOrderVolumeRatio = 0.001
        });

        _adapter = new SimExecutionAdapter(
            _mockPnLCalculator.Object,
            _mockRiskManager.Object,
            _mockAccountManager.Object,
            settings,
            priceLimitChecker: null,  // existing tests predate §4
            _mockLogger.Object
        );
    }

    [Fact]
    public async Task ExecuteOrderAsync_BuyOrder_UpdatesCashCorrectly()
    {
        // Arrange
        var order = new Order
        {
            OrderId = "test-order",
            SessionId = "test-session",
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            OrderType = OrderType.Market,
            Quantity = 1000,
            Price = 10m,
            Status = OrderStatus.Pending
        };

        var marketData = new MarketData
        {
            Symbol = "600000.SH",
            Close = 10m
        };

        var account = new Account
        {
            SessionId = "test-session",
            Cash = 50000m
        };

        _mockAccountManager
            .Setup(a => a.GetAccountAsync("test-session"))
            .ReturnsAsync(account);

        _mockRiskManager
            .Setup(r => r.CheckOrderRiskAsync(order))
            .ReturnsAsync(new RiskCheckResult(true));

        // Act
        var result = await _adapter.ExecuteOrderAsync(order, marketData);

        // Assert
        Assert.Equal(OrderStatus.Filled, result.Order.Status);
        Assert.Equal(1000, result.Order.FilledQuantity);
        Assert.NotNull(result.Order.FilledAt);

        // Should deduct cost = 1000 * price + commission
        var expectedCost = 1000 * result.Order.Price + result.Order.Commission;
        _mockAccountManager.Verify(a => a.UpdateCashAsync("test-session", -expectedCost), Times.Once);
    }

    [Fact]
    public async Task ExecuteOrderAsync_SellOrder_AddsProceedsToCash()
    {
        // Arrange
        var order = new Order
        {
            OrderId = "test-order",
            SessionId = "test-session",
            Symbol = "600000.SH",
            Side = OrderSide.Sell,
            OrderType = OrderType.Market,
            Quantity = 1000,
            Price = 10m,
            Status = OrderStatus.Pending
        };

        var marketData = new MarketData
        {
            Symbol = "600000.SH",
            Close = 10m
        };

        _mockRiskManager
            .Setup(r => r.CheckOrderRiskAsync(order))
            .ReturnsAsync(new RiskCheckResult(true));

        // Act
        var result = await _adapter.ExecuteOrderAsync(order, marketData);

        // Assert
        Assert.Equal(OrderStatus.Filled, result.Order.Status);

        // Sell should increase cash = quantity * price - commission
        var expectedProceeds = 1000 * result.Order.Price - result.Order.Commission;
        _mockAccountManager.Verify(a => a.UpdateCashAsync("test-session", expectedProceeds), Times.Once);
    }

    [Fact]
    public async Task ExecuteOrderAsync_AppliesSlippage_UsesSlippagedPrice()
    {
        // Arrange
        var order = new Order
        {
            OrderId = "test-order",
            SessionId = "test-session",
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            OrderType = OrderType.Market,
            Quantity = 1000,
            Price = 10m,
            Status = OrderStatus.Pending
        };

        var marketData = new MarketData
        {
            Symbol = "600000.SH",
            Close = 10m
        };

        _mockRiskManager
            .Setup(r => r.CheckOrderRiskAsync(order))
            .ReturnsAsync(new RiskCheckResult(true));

        // Act
        var result = await _adapter.ExecuteOrderAsync(order, marketData);

        // Assert
        // Buy should have positive slippage, price should be higher than 10m
        Assert.True(result.Order.Price > 10m);
        Assert.True(result.Order.Price < 10.05m); // should not exceed maximum slippage
        Assert.Equal(OrderStatus.Filled, result.Order.Status);
    }

    [Fact]
    public async Task ExecuteOrderAsync_UpdatesCommissionAndTradeCount()
    {
        // Arrange
        var order = new Order
        {
            OrderId = "test-order",
            SessionId = "test-session",
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            OrderType = OrderType.Market,
            Quantity = 1000,
            Price = 10m,
            Status = OrderStatus.Pending
        };

        var marketData = new MarketData
        {
            Symbol = "600000.SH",
            Close = 10m
        };

        _mockRiskManager
            .Setup(r => r.CheckOrderRiskAsync(order))
            .ReturnsAsync(new RiskCheckResult(true));

        // Act
        var result = await _adapter.ExecuteOrderAsync(order, marketData);

        // Assert
        _mockAccountManager.Verify(a => a.AddCommissionAsync("test-session", result.Order.Commission), Times.Once);
        _mockAccountManager.Verify(a => a.IncrementTradeCountAsync("test-session"), Times.Once);
    }

    [Fact]
    public async Task ExecuteOrderAsync_RiskCheckReject_StillExecutesDueToDisabledRiskControl()
    {
        // Arrange
        var order = new Order
        {
            OrderId = "test-order",
            SessionId = "test-session",
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            OrderType = OrderType.Market,
            Quantity = 1000,
            Price = 10m,
            Status = OrderStatus.Pending
        };

        var marketData = new MarketData
        {
            Symbol = "600000.SH",
            Close = 10m
        };

        _mockRiskManager
            .Setup(r => r.CheckOrderRiskAsync(order))
            .ReturnsAsync(new RiskCheckResult(false, "Insufficient funds"));

        // Act
        var result = await _adapter.ExecuteOrderAsync(order, marketData);

        // Assert
        // Risk control is currently temporarily disabled, even if risk check returns reject, order will still execute
        Assert.Equal(OrderStatus.Filled, result.Order.Status);
    }

    [Fact]
    public async Task ExecuteOrderAsync_SetsExecutionModeToSimulation()
    {
        // Arrange
        var order = new Order
        {
            OrderId = "test-order",
            SessionId = "test-session",
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            OrderType = OrderType.Market,
            Quantity = 1000,
            Price = 10m,
            Status = OrderStatus.Pending
        };

        var marketData = new MarketData
        {
            Symbol = "600000.SH",
            Close = 10m
        };

        _mockRiskManager
            .Setup(r => r.CheckOrderRiskAsync(order))
            .ReturnsAsync(new RiskCheckResult(true));

        // Act
        var result = await _adapter.ExecuteOrderAsync(order, marketData);

        // Assert
        Assert.Equal(ExecutionMode.SIMULATION, result.Order.ExecutionMode);
    }

    [Fact]
    public async Task ValidateOrderAsync_ValidOrder_ReturnsTrue()
    {
        // Arrange
        var order = new Order
        {
            OrderId = "test-order",
            Symbol = "600000.SH",
            Quantity = 1000,
            Price = 10m
        };

        // Act
        var result = await _adapter.ValidateOrderAsync(order);

        // Assert
        Assert.True(result);
    }

    [Fact]
    public async Task ValidateOrderAsync_ZeroQuantity_ReturnsFalse()
    {
        // Arrange
        var order = new Order
        {
            OrderId = "test-order",
            Symbol = "600000.SH",
            Quantity = 0,
            Price = 10m
        };

        // Act
        var result = await _adapter.ValidateOrderAsync(order);

        // Assert
        Assert.False(result);
    }

    [Fact]
    public async Task ValidateOrderAsync_NegativeQuantity_ReturnsFalse()
    {
        // Arrange
        var order = new Order
        {
            OrderId = "test-order",
            Symbol = "600000.SH",
            Quantity = -100,
            Price = 10m
        };

        // Act
        var result = await _adapter.ValidateOrderAsync(order);

        // Assert
        Assert.False(result);
    }

    [Fact]
    public async Task ValidateOrderAsync_EmptySymbol_ReturnsFalse()
    {
        // Arrange
        var order = new Order
        {
            OrderId = "test-order",
            Symbol = "",
            Quantity = 1000,
            Price = 10m
        };

        // Act
        var result = await _adapter.ValidateOrderAsync(order);

        // Assert
        Assert.False(result);
    }

    [Fact]
    public async Task ValidateOrderAsync_NullSymbol_ReturnsFalse()
    {
        // Arrange
        var order = new Order
        {
            OrderId = "test-order",
            Symbol = null!,
            Quantity = 1000,
            Price = 10m
        };

        // Act
        var result = await _adapter.ValidateOrderAsync(order);

        // Assert
        Assert.False(result);
    }

    [Fact]
    public async Task CancelOrderAsync_AlwaysReturnsTrue()
    {
        // Act
        var result = await _adapter.CancelOrderAsync("test-order", "test-session");

        // Assert
        Assert.True(result);
    }

    [Fact]
    public void GetAdapterType_ReturnsSimulation()
    {
        // Act
        var adapterType = _adapter.GetAdapterType();

        // Assert
        Assert.Equal("SIMULATION", adapterType);
    }

    [Fact]
    public async Task CheckOrderRiskAsync_DelegatesToRiskManager()
    {
        // Arrange
        var order = new Order
        {
            OrderId = "test-order",
            SessionId = "test-session",
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            Quantity = 1000,
            Price = 10m
        };

        var expectedResult = new RiskCheckResult(true, "OK");
        _mockRiskManager
            .Setup(r => r.CheckOrderRiskAsync(order))
            .ReturnsAsync(expectedResult);

        // Act
        var result = await _adapter.CheckOrderRiskAsync(order);

        // Assert
        Assert.Equal(expectedResult, result);
        _mockRiskManager.Verify(r => r.CheckOrderRiskAsync(order), Times.Once);
    }
}
