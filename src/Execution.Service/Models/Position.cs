namespace ExecutionService.Models;

public enum PositionSide
{
    Long,
    Short
}

public class Position
{
    public long Id { get; set; }
    public string SessionId { get; set; } = string.Empty;
    public string Symbol { get; set; } = string.Empty;
    public PositionSide Side { get; set; }
    public decimal Quantity { get; set; }
    public decimal AvgPrice { get; set; }
    public decimal CurrentPrice { get; set; }
    public decimal MarketValue { get; set; }
    public decimal UnrealizedPnL { get; set; }
    public decimal RealizedPnL { get; set; }

    public void Add(decimal quantity, decimal price, decimal commission = 0)
    {
        if (Side == PositionSide.Long)
        {
            // Long increase (buy more): cost basis is the weighted average of
            // (price paid + commission per share). Commission raises break-even.
            var totalCost = AvgPrice * Quantity + price * quantity + commission;
            Quantity += quantity;
            AvgPrice = Quantity > 0 ? totalCost / Quantity : price;
        }
        else
        {
            // Short increase (short more): the "cost basis" here represents the
            // effective sale proceeds per share. Commission reduces those proceeds,
            // so it is subtracted (not added) — otherwise PnL on close is overstated.
            var totalEffectiveSale = AvgPrice * Quantity + price * quantity - commission;
            Quantity += quantity;
            AvgPrice = Quantity > 0 ? totalEffectiveSale / Quantity : price;
        }
    }

    public void Reduce(decimal quantity, decimal price, decimal commission = 0)
    {
        if (quantity > Quantity)
        {
            quantity = Quantity; // Cannot sell more than held
        }

        if (Side == PositionSide.Long)
        {
            // Long position reduction: calculate realized PnL
            var costBasis = AvgPrice * quantity;
            var saleValue = price * quantity - commission;
            RealizedPnL += saleValue - costBasis;
        }
        else
        {
            // Short position reduction
            var costBasis = AvgPrice * quantity;
            var saleValue = price * quantity + commission;
            RealizedPnL += costBasis - saleValue;
        }

        Quantity -= quantity;
    }

    public decimal CalculateMarketValue()
    {
        return Quantity * CurrentPrice;
    }

    public decimal UpdateUnrealizedPnL(decimal currentPrice)
    {
        CurrentPrice = currentPrice;
        MarketValue = CalculateMarketValue();

        if (Side == PositionSide.Long)
        {
            UnrealizedPnL = (CurrentPrice - AvgPrice) * Quantity;
        }
        else
        {
            UnrealizedPnL = (AvgPrice - CurrentPrice) * Quantity;
        }

        return UnrealizedPnL;
    }

    public bool HasPosition => Quantity > 0;
}