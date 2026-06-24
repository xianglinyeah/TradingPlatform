namespace ExecutionService.Models;

public class Account
{
    public string SessionId { get; set; } = string.Empty;
    public decimal InitialCapital { get; set; }
    public decimal Cash { get; set; }
    public decimal Equity { get; set; }
    public decimal MarketValue { get; set; }
    public decimal TotalPnL { get; set; }
    public decimal TotalCommission { get; set; }
    public int TotalTrades { get; set; }
    public DateTime UpdatedAt { get; set; } = DateTime.UtcNow;

    public decimal ReturnPercentage => InitialCapital > 0 ? (TotalPnL / InitialCapital) * 100 : 0;
}

public class Trade
{
    public long TradeId { get; set; }
    public long OrderId { get; set; }
    public string SessionId { get; set; } = string.Empty;
    public string Symbol { get; set; } = string.Empty;
    public string Side { get; set; } = string.Empty;
    public decimal Quantity { get; set; }
    public decimal Price { get; set; }
    public decimal Commission { get; set; }
    public DateTime TradeTime { get; set; } = DateTime.UtcNow;
    public string? SignalId { get; set; }
    public ExecutionMode ExecutionMode { get; set; } = ExecutionMode.SIMULATION; // Execution mode

    // P0.3 added: sequence number of this fill within the order (starting from 1)
    public int FillSeq { get; set; } = 1;

    // P0.3 added: broker execution id (live/GM matching detail); null in simulation
    public string? BrokerFillId { get; set; }
}

public class MarketData
{
    public string Symbol { get; set; } = string.Empty;
    public decimal Open { get; set; }
    public decimal High { get; set; }
    public decimal Low { get; set; }
    public decimal Close { get; set; }
    public decimal Volume { get; set; }
    public DateTime Timestamp { get; set; }
}