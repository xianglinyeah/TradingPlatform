namespace MarketData.Replay.Models;

public class MarketDataEvent
{
    public string Symbol { get; set; } = string.Empty;
    public DateTime EventTime { get; set; }
    public DateTime ReplayTime { get; set; }
    public decimal Open { get; set; }
    public decimal High { get; set; }
    public decimal Low { get; set; }
    public decimal Close { get; set; }
    public decimal Volume { get; set; }
    public decimal Amount { get; set; }
    public string SessionId { get; set; } = string.Empty;
    public long SequenceNumber { get; set; }
    public string Source { get; set; } = string.Empty;
}
