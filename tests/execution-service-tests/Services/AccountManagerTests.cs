using Moq;
using Microsoft.Extensions.Logging;
using ExecutionService.Models;
using ExecutionService.Core.Services;
using ExecutionService.Data.IRepositories;
using Xunit;

namespace ExecutionService.Tests.Services;

public class AccountManagerTests
{
    private readonly Mock<IAccountRepository> _mockAccountRepo;
    private readonly AccountManager _accountManager;

    public AccountManagerTests()
    {
        _mockAccountRepo = new Mock<IAccountRepository>();
        _accountManager = new AccountManager(
            Mock.Of<ILogger<AccountManager>>(),
            _mockAccountRepo.Object
        );
    }

    [Fact]
    public async Task GetAccountAsync_ExistingAccount_ReturnsAccount()
    {
        // Arrange
        var sessionId = "test-session";
        var expectedAccount = new Account
        {
            SessionId = sessionId,
            Cash = 50000m,
            Equity = 60000m,
            InitialCapital = 100000m
        };

        _mockAccountRepo
            .Setup(r => r.GetAccountAsync(sessionId))
            .ReturnsAsync(expectedAccount);

        // Act
        var result = await _accountManager.GetAccountAsync(sessionId);

        // Assert
        Assert.NotNull(result);
        Assert.Equal(sessionId, result.SessionId);
        Assert.Equal(50000m, result.Cash);
        _mockAccountRepo.Verify(r => r.GetAccountAsync(sessionId), Times.Once);
        _mockAccountRepo.Verify(r => r.GetOrCreateAccountAsync(It.IsAny<string>(), It.IsAny<decimal>()), Times.Never);
    }

    [Fact]
    public async Task GetAccountAsync_NoAccount_CreatesNewWithDefaultCapital()
    {
        // Arrange
        var sessionId = "new-session";
        Account? capturedAccount = null;

        _mockAccountRepo
            .Setup(r => r.GetAccountAsync(sessionId))
            .ReturnsAsync((Account?)null);

        _mockAccountRepo
            .Setup(r => r.GetOrCreateAccountAsync(sessionId, It.IsAny<decimal>()))
            .Callback<string, decimal>((id, capital) =>
            {
                capturedAccount = new Account
                {
                    SessionId = id,
                    InitialCapital = capital
                };
            })
            .ReturnsAsync((string id, decimal capital) => capturedAccount!);

        // Act
        var result = await _accountManager.GetAccountAsync(sessionId);

        // Assert
        Assert.NotNull(result);
        Assert.Equal(sessionId, result.SessionId);
        Assert.Equal(1000000m, result.InitialCapital); // AccountConstants.DEFAULT_INITIAL_CAPITAL
        _mockAccountRepo.Verify(r => r.GetOrCreateAccountAsync(sessionId, 1000000m), Times.Once);
    }

    [Fact]
    public async Task UpdateCashAsync_AddingCash_IncreasesCashBalance()
    {
        // Arrange
        var sessionId = "test-session";
        var account = new Account
        {
            SessionId = sessionId,
            Cash = 50000m
        };

        _mockAccountRepo
            .Setup(r => r.GetAccountAsync(sessionId))
            .ReturnsAsync(account);

        // Act
        await _accountManager.UpdateCashAsync(sessionId, 10000m);

        // Assert
        Assert.Equal(60000m, account.Cash);
        _mockAccountRepo.Verify(r => r.UpdateAccountAsync(account), Times.Once);
    }

    [Fact]
    public async Task UpdateCashAsync_DeductingCash_DecreasesCashBalance()
    {
        // Arrange
        var account = new Account
        {
            SessionId = "test-session",
            Cash = 50000m
        };

        _mockAccountRepo
            .Setup(r => r.GetAccountAsync("test-session"))
            .ReturnsAsync(account);

        // Act
        await _accountManager.UpdateCashAsync("test-session", -15000m);

        // Assert
        Assert.Equal(35000m, account.Cash);
        _mockAccountRepo.Verify(r => r.UpdateAccountAsync(account), Times.Once);
    }

    [Fact]
    public async Task UpdateCashAsync_NoAccount_DoesNothing()
    {
        // Arrange
        _mockAccountRepo
            .Setup(r => r.GetAccountAsync(It.IsAny<string>()))
            .ReturnsAsync((Account?)null);

        // Act
        await _accountManager.UpdateCashAsync("nonexistent", 10000m);

        // Assert
        _mockAccountRepo.Verify(r => r.UpdateAccountAsync(It.IsAny<Account>()), Times.Never);
    }

    [Fact]
    public async Task UpdateEquityAsync_CalculatesCorrectEquityAndPnL()
    {
        // Arrange
        var account = new Account
        {
            SessionId = "test-session",
            Cash = 60000m,
            MarketValue = 45000m,
            InitialCapital = 100000m
        };

        _mockAccountRepo
            .Setup(r => r.GetAccountAsync("test-session"))
            .ReturnsAsync(account);

        // Act
        await _accountManager.UpdateEquityAsync("test-session");

        // Assert
        Assert.Equal(105000m, account.Equity); // 60000 + 45000
        Assert.Equal(5000m, account.TotalPnL); // 105000 - 100000
        _mockAccountRepo.Verify(r => r.UpdateAccountAsync(account), Times.Once);
    }

    [Fact]
    public async Task UpdateEquityAsync_LossPosition_CalculatesNegativePnL()
    {
        // Arrange
        var account = new Account
        {
            SessionId = "test-session",
            Cash = 55000m,
            MarketValue = 40000m,
            InitialCapital = 100000m
        };

        _mockAccountRepo
            .Setup(r => r.GetAccountAsync("test-session"))
            .ReturnsAsync(account);

        // Act
        await _accountManager.UpdateEquityAsync("test-session");

        // Assert
        Assert.Equal(95000m, account.Equity); // 55000 + 40000
        Assert.Equal(-5000m, account.TotalPnL); // 95000 - 100000
        _mockAccountRepo.Verify(r => r.UpdateAccountAsync(account), Times.Once);
    }

    [Fact]
    public async Task AddCommissionAsync_AccumulatesCommission()
    {
        // Arrange
        var account = new Account
        {
            SessionId = "test-session",
            TotalCommission = 50m
        };

        _mockAccountRepo
            .Setup(r => r.GetAccountAsync("test-session"))
            .ReturnsAsync(account);

        // Act
        await _accountManager.AddCommissionAsync("test-session", 25m);

        // Assert
        Assert.Equal(75m, account.TotalCommission); // 50 + 25
        _mockAccountRepo.Verify(r => r.UpdateAccountAsync(account), Times.Once);
    }

    [Fact]
    public async Task AddCommissionAsync_MultipleAccumulations_AddsUpCorrectly()
    {
        // Arrange
        var account = new Account
        {
            SessionId = "test-session",
            TotalCommission = 100m
        };

        _mockAccountRepo
            .Setup(r => r.GetAccountAsync("test-session"))
            .ReturnsAsync(account);

        // Act
        await _accountManager.AddCommissionAsync("test-session", 30m);
        await _accountManager.AddCommissionAsync("test-session", 20m);
        await _accountManager.AddCommissionAsync("test-session", 50m);

        // Assert
        Assert.Equal(200m, account.TotalCommission); // 100 + 30 + 20 + 50
        _mockAccountRepo.Verify(r => r.UpdateAccountAsync(account), Times.Exactly(3));
    }

    [Fact]
    public async Task IncrementTradeCountAsync_IncreasesTradeCount()
    {
        // Arrange
        var account = new Account
        {
            SessionId = "test-session",
            TotalTrades = 5
        };

        _mockAccountRepo
            .Setup(r => r.GetAccountAsync("test-session"))
            .ReturnsAsync(account);

        // Act
        var result = await _accountManager.IncrementTradeCountAsync("test-session");

        // Assert
        Assert.Equal(6, result);
        Assert.Equal(6, account.TotalTrades);
        _mockAccountRepo.Verify(r => r.UpdateAccountAsync(account), Times.Once);
    }

    [Fact]
    public async Task IncrementTradeCountAsync_NewAccount_StartsFromOne()
    {
        // Arrange
        var account = new Account
        {
            SessionId = "test-session",
            TotalTrades = 0
        };

        _mockAccountRepo
            .Setup(r => r.GetAccountAsync("test-session"))
            .ReturnsAsync(account);

        // Act
        var result = await _accountManager.IncrementTradeCountAsync("test-session");

        // Assert
        Assert.Equal(1, result);
        Assert.Equal(1, account.TotalTrades);
    }

    [Fact]
    public async Task IncrementTradeCountAsync_NoAccount_ReturnsZero()
    {
        // Arrange
        _mockAccountRepo
            .Setup(r => r.GetAccountAsync(It.IsAny<string>()))
            .ReturnsAsync((Account?)null);

        // Act
        var result = await _accountManager.IncrementTradeCountAsync("nonexistent");

        // Assert
        Assert.Equal(0, result);
        _mockAccountRepo.Verify(r => r.UpdateAccountAsync(It.IsAny<Account>()), Times.Never);
    }
}
