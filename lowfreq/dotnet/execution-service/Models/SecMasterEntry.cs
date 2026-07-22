namespace ExecutionService.Models;

/// <summary>
/// Mirror of <c>market_ref.sec_master</c>. Read-only reference data populated
/// by the data-ingestion <c>sec_master_sync</c> mode. Drives instrument
/// classification in <c>MarketRuleFactory</c> and price-limit computation in
/// <c>PriceLimitChecker</c>.
/// </summary>
public class SecMasterEntry
{
    /// <summary>TS-format symbol, e.g. <c>600000.SH</c>. Primary key.</summary>
    public string Symbol { get; set; } = string.Empty;

    /// <summary>Original GM-format symbol, e.g. <c>SHSE.600000</c>.</summary>
    public string GmSymbol { get; set; } = string.Empty;

    /// <summary>Normalized class: stock | convertible_bond | etf | reit | ...</summary>
    public string SecType { get; set; } = string.Empty;

    /// <summary>Raw GM SDK <c>sec_type1</c> integer.</summary>
    public int? SecTypeCode { get; set; }

    /// <summary>Trading board: main | chinext | star | beijing | null.</summary>
    public string? Board { get; set; }

    /// <summary>Security display name (used for ST detection at ingestion time).</summary>
    public string? Name { get; set; }

    /// <summary>True if the security is currently ST/*ST (±5% price limit).</summary>
    public bool IsSt { get; set; }

    /// <summary>Listing exchange: SHSE | SZSE | BSE.</summary>
    public string? Exchange { get; set; }

    /// <summary>UTC timestamp of the ingestion run that last updated this row.</summary>
    public DateTime UpdatedAt { get; set; }
}
