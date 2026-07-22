using ExecutionService.Models;

namespace ExecutionService.Core.Services;

public interface IRiskManager
{
    Task<RiskCheckResult> CheckOrderRiskAsync(Order order);
    Task<bool> CheckPositionRiskAsync(Position position);
    bool WithinRiskLimits(Account account);
    Task MonitorPositionsAsync(IEnumerable<Position> positions);
}

public interface IAccountManager
{
    Task<Account> GetAccountAsync(string sessionId);
    Task UpdateCashAsync(string sessionId, decimal amount);
    Task UpdateEquityAsync(string sessionId);
    Task AddCommissionAsync(string sessionId, decimal commission);
    Task<int> IncrementTradeCountAsync(string sessionId);
}

public interface IPositionManager
{
    Task<Position?> GetPositionAsync(string sessionId, string symbol);
    Task<List<Position>> GetAllPositionsAsync(string sessionId);
    // P0.3: New signature — accepts a list of fills; each fill generates 1 Trade row + 1 OrderUpdate event
    Task UpdatePositionAsync(string sessionId, Order order, IReadOnlyList<ExecutionService.Models.Fill> fills);
    Task CloseAllPositionsAsync(string sessionId);
    Task<Order?> GetOrderAsync(string sessionId, string orderId);
    Task<List<Order>> GetAllOrdersAsync(string sessionId);
}