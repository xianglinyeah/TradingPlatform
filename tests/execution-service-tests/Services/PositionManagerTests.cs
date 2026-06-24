using Moq;
using Microsoft.Extensions.Logging;
using ExecutionService.Models;
using ExecutionService.Core.Services;
using ExecutionService.Core.Services;
using ExecutionService.Core.Events;
using ExecutionService.Models;
using ExecutionService.Data.IRepositories;
using Xunit;

namespace ExecutionService.Tests.Services;

public class PositionManagerTests
{
    private readonly Mock<IPositionRepository> _mockPositionRepo;
    private readonly Mock<IOrderRepository> _mockOrderRepo;
    private readonly Mock<ITradeRepository> _mockTradeRepo;
    private readonly OrderUpdateChannel _orderUpdateChannel;
    private readonly PositionManager _positionManager;

    public PositionManagerTests()
    {
        _mockPositionRepo = new Mock<IPositionRepository>();
        _mockOrderRepo = new Mock<IOrderRepository>();
        _mockTradeRepo = new Mock<ITradeRepository>();
        _orderUpdateChannel = new OrderUpdateChannel();
        _positionManager = new PositionManager(
            Mock.Of<ILogger<PositionManager>>(),
            _mockPositionRepo.Object,
            _mockOrderRepo.Object,
            _mockTradeRepo.Object,
            _orderUpdateChannel
        );

        // Set default Mock return values for all tests
        _mockOrderRepo
            .Setup(r => r.CreateOrderAsync(It.IsAny<Order>()))
            .ReturnsAsync((Order o) => { o.Id = 1; return o; });

        _mockTradeRepo
            .Setup(r => r.CreateTradeAsync(It.IsAny<Trade>()))
            .ReturnsAsync((Trade t) => t);
    }

    /// <summary>
    /// Helper: build a single Fill list (compatible with legacy "single fill" test scenarios)
    /// </summary>
    private static IReadOnlyList<Fill> SingleFill(Order order) => new[]
    {
        new Fill
        {
            Quantity = order.FilledQuantity,
            Price = order.FillPrice,
            FillTime = order.FilledAt ?? DateTime.UtcNow,
            BrokerFillId = null,
            Commission = order.Commission
        }
    };

    [Fact]
    public async Task GetPositionAsync_ExistingPosition_ReturnsPosition()
    {
        // Arrange
        var sessionId = "test-session";
        var symbol = "600000.SH";
        var expectedPosition = new Position
        {
            Id = 1,
            SessionId = sessionId,
            Symbol = symbol,
            Quantity = 100,
            AvgPrice = 10.5m
        };

        _mockPositionRepo
            .Setup(r => r.GetPositionAsync(sessionId, symbol))
            .ReturnsAsync(expectedPosition);

        // Act
        var result = await _positionManager.GetPositionAsync(sessionId, symbol);

        // Assert
        Assert.NotNull(result);
        Assert.Equal(expectedPosition.Id, result.Id);
        Assert.Equal(expectedPosition.Symbol, result.Symbol);
        Assert.Equal(expectedPosition.Quantity, result.Quantity);
    }

    [Fact]
    public async Task GetPositionAsync_NoPosition_ReturnsNull()
    {
        // Arrange
        _mockPositionRepo
            .Setup(r => r.GetPositionAsync(It.IsAny<string>(), It.IsAny<string>()))
            .ReturnsAsync((Position?)null);

        // Act
        var result = await _positionManager.GetPositionAsync("test", "600000.SH");

        // Assert
        Assert.Null(result);
    }

    [Fact]
    public async Task GetAllPositionsAsync_ReturnsAllPositions()
    {
        // Arrange
        var sessionId = "test-session";
        var expectedPositions = new List<Position>
        {
            new Position { Symbol = "600000.SH", Quantity = 100 },
            new Position { Symbol = "000001.SZ", Quantity = 200 }
        };

        _mockPositionRepo
            .Setup(r => r.GetPositionsBySessionAsync(sessionId))
            .ReturnsAsync(expectedPositions);

        // Act
        var result = await _positionManager.GetAllPositionsAsync(sessionId);

        // Assert
        Assert.Equal(2, result.Count);
    }

    [Fact]
    public async Task UpdatePositionAsync_NewBuyOrder_CreatesNewPosition()
    {
        // Arrange
        var order = new Order
        {
            SessionId = "test-session",
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            Quantity = 100,
            Price = 10.50m,
            Commission = 5m,
            FilledQuantity = 100,
            FillPrice = 10.50m
        };

        _mockPositionRepo
            .Setup(r => r.GetPositionAsync(order.SessionId, order.Symbol))
            .ReturnsAsync((Position?)null);

        Position? capturedPosition = null;
        _mockPositionRepo
            .Setup(r => r.CreatePositionAsync(It.IsAny<Position>()))
            .Callback<Position>(p => capturedPosition = p)
            .ReturnsAsync((Position p) => { p.Id = 1; return p; });

        _mockTradeRepo
            .Setup(r => r.CreateTradeAsync(It.IsAny<Trade>()))
            .ReturnsAsync((Trade t) => t);

        // Act
        await _positionManager.UpdatePositionAsync(order.SessionId, order, SingleFill(order));

        // Assert
        Assert.NotNull(capturedPosition);
        Assert.Equal(100, capturedPosition.Quantity);
        Assert.Equal(10.55m, capturedPosition.AvgPrice); // (10.50 * 100 + 5) / 100 = 10.55

        _mockPositionRepo.Verify(r => r.CreatePositionAsync(It.IsAny<Position>()), Times.Once);
        _mockOrderRepo.Verify(r => r.CreateOrderAsync(order), Times.Once);
        _mockTradeRepo.Verify(r => r.CreateTradeAsync(It.IsAny<Trade>()), Times.Once);
    }

    [Fact]
    public async Task UpdatePositionAsync_ExistingBuyOrder_AddsToPosition()
    {
        // Arrange
        var existingPosition = new Position
        {
            Id = 1,
            SessionId = "test-session",
            Symbol = "600000.SH",
            Quantity = 100,
            AvgPrice = 10.00m,
            Side = PositionSide.Long
        };

        var order = new Order
        {
            SessionId = "test-session",
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            Quantity = 100,
            Price = 11.00m,
            Commission = 5m,
            FilledQuantity = 100,
            FillPrice = 11.00m
        };

        _mockPositionRepo
            .Setup(r => r.GetPositionAsync(order.SessionId, order.Symbol))
            .ReturnsAsync(existingPosition);

        // Act
        await _positionManager.UpdatePositionAsync(order.SessionId, order, SingleFill(order));

        // Assert
        Assert.Equal(200, existingPosition.Quantity);
        // New average price = (10.00 * 100 + 11.00 * 100 + 5) / 200 = 10.525
        Assert.Equal(10.525m, existingPosition.AvgPrice);

        _mockPositionRepo.Verify(r => r.UpdatePositionAsync(existingPosition), Times.Once);
        _mockOrderRepo.Verify(r => r.CreateOrderAsync(order), Times.Once);
    }

    [Fact]
    public async Task UpdatePositionAsync_SellOrder_ReducesPosition()
    {
        // Arrange
        var existingPosition = new Position
        {
            Id = 1,
            SessionId = "test-session",
            Symbol = "600000.SH",
            Quantity = 200,
            AvgPrice = 10.00m,
            Side = PositionSide.Long,
            RealizedPnL = 0
        };

        var order = new Order
        {
            SessionId = "test-session",
            Symbol = "600000.SH",
            Side = OrderSide.Sell,
            Quantity = 100,
            Price = 12.00m,
            Commission = 5m,
            FilledQuantity = 100,
            FillPrice = 12.00m
        };

        _mockPositionRepo
            .Setup(r => r.GetPositionAsync(order.SessionId, order.Symbol))
            .ReturnsAsync(existingPosition);

        // Act
        await _positionManager.UpdatePositionAsync(order.SessionId, order, SingleFill(order));

        // Assert
        Assert.Equal(100, existingPosition.Quantity);
        Assert.Equal(10.00m, existingPosition.AvgPrice); // average price unchanged
        // realized PnL = (12.00 * 100 - 5) - (10.00 * 100) = 195
        Assert.Equal(195m, existingPosition.RealizedPnL);

        _mockPositionRepo.Verify(r => r.UpdatePositionAsync(existingPosition), Times.Once);
        _mockOrderRepo.Verify(r => r.CreateOrderAsync(order), Times.Once);
    }

    [Fact]
    public async Task UpdatePositionAsync_SellMoreThanQuantity_SellsAllAvailable()
    {
        // Arrange
        var existingPosition = new Position
        {
            Id = 1,
            SessionId = "test-session",
            Symbol = "600000.SH",
            Quantity = 100,
            AvgPrice = 10.00m,
            Side = PositionSide.Long,
            RealizedPnL = 0
        };

        var order = new Order
        {
            SessionId = "test-session",
            Symbol = "600000.SH",
            Side = OrderSide.Sell,
            Quantity = 150, // attempt to sell more than held
            Price = 12.00m,
            Commission = 5m,
            FilledQuantity = 150,
            FillPrice = 12.00m
        };

        _mockPositionRepo
            .Setup(r => r.GetPositionAsync(order.SessionId, order.Symbol))
            .ReturnsAsync(existingPosition);

        // Act
        await _positionManager.UpdatePositionAsync(order.SessionId, order, SingleFill(order));

        // Assert
        Assert.Equal(0, existingPosition.Quantity); // should sell all
        // realized PnL = (12.00 * 100 - 5) - (10.00 * 100) = 195
        Assert.Equal(195m, existingPosition.RealizedPnL);
    }

    [Fact]
    public async Task GetOrderAsync_ReturnsOrder()
    {
        // Arrange
        var sessionId = "test-session";
        var orderId = "order-123";
        var expectedOrder = new Order
        {
            OrderId = orderId,
            SessionId = sessionId,
            Symbol = "600000.SH"
        };

        _mockOrderRepo
            .Setup(r => r.GetOrderAsync(sessionId, orderId))
            .ReturnsAsync(expectedOrder);

        // Act
        var result = await _positionManager.GetOrderAsync(sessionId, orderId);

        // Assert
        Assert.NotNull(result);
        Assert.Equal(orderId, result.OrderId);
        Assert.Equal(sessionId, result.SessionId);
    }
}
