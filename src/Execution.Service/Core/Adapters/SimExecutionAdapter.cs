using ExecutionService.Models;
using ExecutionService.Core.Services;
using ExecutionService.Core.Adapters;
using ExecutionService.Core.Utils;
using Microsoft.Extensions.Options;

/// <summary>
/// Simulation execution adapter
/// Local matching, calculate simulated PnL
/// Used for backtesting and simulation trading
/// </summary>
public class SimExecutionAdapter : ExecutionAdapterBase
{
    private readonly IRiskManager _riskManager;
    private readonly IAccountManager _accountManager;
    private readonly ExecutionSettings _settings;
    private readonly ILogger<SimExecutionAdapter> _logger;

    public SimExecutionAdapter(
        IPnLCalculator pnlCalculator,
        IRiskManager riskManager,
        IAccountManager accountManager,
        IOptions<ExecutionSettings> settings,
        ILogger<SimExecutionAdapter> logger)
    {
        _riskManager = riskManager;
        _accountManager = accountManager;
        _settings = settings.Value;
        _logger = logger;
    }

    public async override Task<ExecutionResult> ExecuteOrderAsync(Order order, MarketData marketData)
    {
        try
        {
            _logger.LogInformation("[SIM_ADAPTER] Executing simulated order: {Side} {Quantity} {Symbol} @ {Price}, TIF={TIF}",
                order.Side, order.Quantity, order.Symbol, order.Price, order.TimeInForce);

            // Set execution mode
            order.ExecutionMode = ExecutionMode.SIMULATION;

            // Apply slippage simulation
            decimal executionPrice = ExecutionHelper.CalculateExecutionPriceWithSlippage(
                order, marketData, avgDailyVolume: (decimal)_settings.SimDefaultAvgDailyVolume);

            decimal slippage = Math.Abs(executionPrice - marketData.Close);
            if (slippage > 0.01m)
            {
                _logger.LogDebug("[SIM_ADAPTER] Slippage: {Price:F2} → {ExecutionPrice:F2} (Slippage: {Slippage:F2})",
                    marketData.Close, executionPrice, slippage);
            }

            // P1.1: Attempt partial fill splitting
            var partialFills = ExecutionHelper.GeneratePartialFills(
                order, marketData, executionPrice,
                avgDailyVolume: (decimal)_settings.SimDefaultAvgDailyVolume,
                enabled: _settings.SimEnablePartialFill,
                maxPartialFills: _settings.SimMaxPartialFills,
                largeOrderVolumeRatio: _settings.SimLargeOrderVolumeRatio);

            // P2.1: FOK — reject if cannot fully fill (split counts as unable to fully fill)
            if (order.TimeInForce == TimeInForce.FOK && partialFills != null)
            {
                order.Status = OrderStatus.Rejected;
                order.Reason = "FOK: insufficient liquidity for full fill";
                _logger.LogInformation("[SIM_ADAPTER] FOK rejected (insufficient liquidity): {OrderId}", order.OrderId);
                return new ExecutionResult { Order = order, Fills = Array.Empty<Fill>() };
            }

            List<Fill> fills;
            if (partialFills != null && partialFills.Count > 0)
            {
                // Split path: multiple fills
                fills = partialFills.Select(p => new Fill
                {
                    Quantity = p.Quantity,
                    Price = p.Price,
                    FillTime = p.FillTime,
                    BrokerFillId = null,
                    Commission = ExecutionHelper.CalculateCommission(new Order
                    {
                        Side = order.Side,
                        Quantity = p.Quantity,
                        Price = p.Price
                    })
                }).ToList();

                decimal totalQty = fills.Sum(f => f.Quantity);
                decimal totalNotional = fills.Sum(f => f.Quantity * f.Price);
                order.FillPrice = totalNotional / totalQty;
                order.FilledQuantity = totalQty;

                // P2.1: IOC — cancel the remainder immediately (simulated matching has no order book concept,
                // but if the partial fills sum < order.Quantity, treat it as IOC having cancelled the remainder)
                if (order.TimeInForce == TimeInForce.IOC && totalQty < order.Quantity)
                {
                    order.Status = OrderStatus.Cancelled;
                    order.Reason = "IOC: remaining cancelled after immediate partial fill";
                }
                else
                {
                    order.Status = totalQty >= order.Quantity ? OrderStatus.Filled : OrderStatus.Partial;
                }
                order.FilledAt = fills[^1].FillTime;
                order.Commission = fills.Sum(f => f.Commission);

                // Note: average price affects order.Price, used for fund calculation
                order.Price = order.FillPrice;

                _logger.LogInformation(
                    "[SIM_ADAPTER] Partial-filled: {OrderId} fills={Count} totalQty={Qty} avgPrice={Price:F2} status={Status}",
                    order.OrderId, fills.Count, totalQty, order.FillPrice, order.Status);
            }
            else
            {
                // Single full fill path (preserve original behavior)
                order.Price = executionPrice;
                ExecutionHelper.FillSimulatedOrder(order, marketData);

                fills = new List<Fill>
                {
                    new Fill
                    {
                        Quantity = order.FilledQuantity,
                        Price = order.FillPrice,
                        FillTime = order.FilledAt ?? marketData.Timestamp,
                        BrokerFillId = null,
                        Commission = order.Commission
                    }
                };

                _logger.LogInformation("[SIM_ADAPTER] Filled (single): {OrderId} Price: {Price:F2} Commission: {Commission:F2}",
                    order.OrderId, order.Price, order.Commission);
            }

            // Update account cash (simulated) — use actual average fill price and total quantity
            if (order.Side == OrderSide.Buy)
            {
                var cost = order.FilledQuantity * order.FillPrice + order.Commission;
                await _accountManager.UpdateCashAsync(order.SessionId, -cost);
            }
            else
            {
                var proceeds = order.FilledQuantity * order.FillPrice - order.Commission;
                await _accountManager.UpdateCashAsync(order.SessionId, proceeds);
            }

            // Update trade count and commission
            await _accountManager.AddCommissionAsync(order.SessionId, order.Commission);
            await _accountManager.IncrementTradeCountAsync(order.SessionId);

            return new ExecutionResult { Order = order, Fills = fills };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "[SIM_ADAPTER] Simulated order execution failed: {OrderId}", order.OrderId);
            order.Status = OrderStatus.Rejected;
            order.Reason = ex.Message;
            return new ExecutionResult { Order = order, Fills = Array.Empty<Fill>() };
        }
    }

    public async override Task<RiskCheckResult> CheckOrderRiskAsync(Order order)
    {
        return await _riskManager.CheckOrderRiskAsync(order);
    }

    public override Task<bool> CancelOrderAsync(string orderId, string sessionId)
    {
        // Simulated execution: always allow cancellation
        _logger.LogInformation("[SIM_ADAPTER] Cancelling simulated order: {OrderId}", orderId);
        return Task.FromResult(true);
    }

    public override string GetAdapterType()
    {
        return "SIMULATION";
    }
}
