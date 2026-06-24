using Execution.Service.Models;
using ExecutionService.Models;
using ExecutionService.Core.Services;
using Microsoft.Extensions.Options;
using Grpc.Net.Client;
using Gmtrading;
using ExecutionService.Core.Utils;

namespace ExecutionService.Core.Adapters;

/// <summary>
/// Paper Trading execution adapter
/// Execute simulated trading through gRPC calls to GM Trading Adapter service
/// </summary>
public class PaperExecutionAdapter : ExecutionAdapterBase
{
    private readonly ILogger<PaperExecutionAdapter> _logger;
    private readonly GMSettings _gmSettings;
    private GrpcChannel? _grpcChannel;
    private GMTrading.GMTradingClient? _grpcClient;

    public PaperExecutionAdapter(
        ILogger<PaperExecutionAdapter> logger,
        IOptions<GMSettings> gmSettings)
    {
        _logger = logger;
        _gmSettings = gmSettings.Value;

        // Initialize gRPC connection
        InitializeGrpcConnection();
    }

    private void InitializeGrpcConnection()
    {
        try
        {
            _logger.LogInformation("[PAPER_ADAPTER] Initializing GM Trading Adapter gRPC connection");

            var grpcAddress = _gmSettings.GrpcServerAddress ?? "http://localhost:5005";
            _grpcChannel = GrpcChannel.ForAddress(grpcAddress);
            _grpcClient = new GMTrading.GMTradingClient(_grpcChannel);

            _logger.LogInformation("[PAPER_ADAPTER] gRPC connection established: {Address}", grpcAddress);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "[PAPER_ADAPTER] gRPC connection initialization failed");
            _grpcChannel = null;
            _grpcClient = null;
        }
    }

    public async override Task<ExecutionResult> ExecuteOrderAsync(Order order, MarketData marketData)
    {
        try
        {
            _logger.LogInformation("[PAPER_ADAPTER] Submitting Paper Trading order: {Side} {Quantity} {Symbol} @ {Price}",
                order.Side, order.Quantity, order.Symbol, order.Price);

            // Set execution mode
            order.ExecutionMode = ExecutionMode.PAPER_BROKER;

            // If gRPC client is available, call GM Trading Adaptor
            if (_grpcClient != null)
            {
                _logger.LogInformation("[PAPER_ADAPTER] Calling GM Trading Adaptor gRPC service");
                _logger.LogInformation("[PAPER_ADAPTER] Using AccountId: {AccountId}", _gmSettings.PaperAccountId);

                var request = new PlaceOrderRequest
                {
                    OrderId = order.OrderId,
                    Symbol = order.Symbol,
                    Side = ConvertSideToInt(order.Side),
                    OrderType = ConvertOrderTypeToInt(order.OrderType),
                    Quantity = (double)order.Quantity,
                    Price = (double)order.Price,
                    AccountId = _gmSettings.PaperAccountId,
                    TimeInForce = (int)order.TimeInForce
                };

                var response = await _grpcClient.PlaceOrderAsync(request);

                if (response.Success)
                {
                    order.Status = ConvertProtoToOrderStatus(response.Status);
                    order.FilledQuantity = (decimal)response.FilledQuantity;
                    order.FillPrice = (decimal)response.FillPrice;
                    order.Commission = (decimal)response.Commission;

                    if (!string.IsNullOrEmpty(response.FilledAt))
                    {
                        order.FilledAt = DateTime.Parse(response.FilledAt);
                    }

                    _logger.LogInformation("[PAPER_ADAPTER] Paper Trading order completed: {OrderId}, Status: {Status}",
                        order.OrderId, order.Status);
                }
                else
                {
                    order.Status = OrderStatus.Rejected;
                    order.Reason = response.Message;
                    _logger.LogWarning("[PAPER_ADAPTER] Paper Trading order rejected: {Message}", response.Message);
                }

                // P0.3: PAPER/GM single-fill fallback (used when GM gRPC does not expose GetOrderFills, uses overall fill summary)
                // broker_fill_id left empty; will be filled when GM exposes SubscribeFills/GetOrderFills in the future
                var fills = BuildFillsFromOrder(order);
                return new ExecutionResult { Order = order, Fills = fills };
            }
            else
            {
                // gRPC service unavailable, use simulated execution
                _logger.LogWarning("[PAPER_ADAPTER] gRPC service unavailable, using simulated execution");

                order.ExecutionMode = ExecutionMode.SIMULATION;
                order.Price = marketData.Close;
                ExecutionHelper.FillSimulatedOrder(order, marketData, 5m); // Fixed 5 yuan commission

                _logger.LogInformation("[PAPER_ADAPTER] Simulated order executed successfully: {OrderId}", order.OrderId);

                var fallbackFill = new Fill
                {
                    Quantity = order.FilledQuantity,
                    Price = order.FillPrice,
                    FillTime = order.FilledAt ?? marketData.Timestamp,
                    BrokerFillId = null,
                    Commission = order.Commission
                };
                return new ExecutionResult { Order = order, Fills = new[] { fallbackFill } };
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "[PAPER_ADAPTER] Paper Trading order execution failed: {OrderId}", order.OrderId);
            order.Status = OrderStatus.Rejected;
            order.Reason = ex.Message;
            return new ExecutionResult { Order = order, Fills = Array.Empty<Fill>() };
        }
    }

    /// <summary>
    /// Build fills list from the order terminal status:
    ///   Filled/Partial/Cancelled → 1 placeholder fill (broker_fill_id=null, refined when GM exposes a fill detail RPC)
    ///   Rejected/Pending/Expired → empty
    /// </summary>
    private static IReadOnlyList<Fill> BuildFillsFromOrder(Order order)
    {
        if (order.FilledQuantity <= 0)
            return Array.Empty<Fill>();

        return new[]
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
    }

    public async override Task<RiskCheckResult> CheckOrderRiskAsync(Order order)
    {
        // Get account balance from GM Trading Adaptor for risk control check
        if (_grpcClient != null)
        {
            try
            {
                var request = new GetCashRequest { AccountId = _gmSettings.PaperAccountId };
                var response = await _grpcClient.GetCashAsync(request);

                if (response.Success && response.CashList.Count > 0)
                {
                    var availableCash = (decimal)response.CashList[0].Available;
                    var requiredCash = order.Quantity * order.Price;

                    if (requiredCash > availableCash)
                    {
                        return new RiskCheckResult(IsAllowed: false,
                            Reason: $"Insufficient funds: Required {requiredCash:C2}, Available {availableCash:C2}");
                    }
                }
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "[PAPER_ADAPTER] GM fund query failed");
            }
        }

        return new RiskCheckResult(IsAllowed: true, Reason: "");
    }

    public async override Task<bool> CancelOrderAsync(string orderId, string sessionId)
    {
        // Call GM Trading Adaptor to cancel order
        if (_grpcClient != null)
        {
            _logger.LogInformation("[PAPER_ADAPTER] Cancelling Paper Trading order: {OrderId}", orderId);
            try
            {
                var request = new CancelOrderRequest
                {
                    OrderId = orderId,
                    AccountId = _gmSettings.PaperAccountId
                };
                var response = await _grpcClient.CancelOrderAsync(request);
                return response.Success;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "[PAPER_ADAPTER] gRPC order cancellation failed");
                return false;
            }
        }

        _logger.LogInformation("[PAPER_ADAPTER] Simulated order cancellation: {OrderId}", orderId);
        return true;
    }

    public override string GetAdapterType()
    {
        return "PAPER_BROKER";
    }

    private int ConvertSideToInt(OrderSide side)
    {
        return side switch
        {
            OrderSide.Buy => 0,
            OrderSide.Sell => 1,
            _ => 0
        };
    }

    private int ConvertOrderTypeToInt(ExecutionService.Models.OrderType orderType)
    {
        return orderType switch
        {
            ExecutionService.Models.OrderType.Market => 0,
            ExecutionService.Models.OrderType.Limit => 1,
            ExecutionService.Models.OrderType.Stop => 2,
            _ => 1
        };
    }

    private ExecutionService.Models.OrderStatus ConvertProtoToOrderStatus(int protoStatus)
    {
        // Aligns with gm_trading.proto: 0=Pending, 1=Filled, 2=Rejected, 3=Cancelled, 4=Partial, 5=Expired
        return protoStatus switch
        {
            0 => ExecutionService.Models.OrderStatus.Pending,
            1 => ExecutionService.Models.OrderStatus.Filled,
            2 => ExecutionService.Models.OrderStatus.Rejected,
            3 => ExecutionService.Models.OrderStatus.Cancelled,
            4 => ExecutionService.Models.OrderStatus.Partial,    // Fixed in P0.1
            5 => ExecutionService.Models.OrderStatus.Expired,    // Added in P2.3
            _ => ExecutionService.Models.OrderStatus.Pending
        };
    }
}
