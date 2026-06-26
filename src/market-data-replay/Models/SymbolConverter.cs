namespace MarketData.Replay.Models;

/// <summary>
/// Symbol code conversion between standard format (SZSE.000001) and GM format.
/// Keep in sync with the equivalent logic in other services.
/// </summary>
public static class SymbolConverter
{
    /// <summary>
    /// Convert standard format to GM API format
    /// Example: SH.600000 -> SHSE.600000
    /// </summary>
    public static string ToGMSymbol(string symbol)
    {
        if (string.IsNullOrEmpty(symbol))
            return symbol;

        var parts = symbol.Split('.');
        if (parts.Length == 2)
        {
            var code = parts[0];
            string exchange = parts[1] switch
            {
                "SH" => MarketData.Replay.Utils.ExchangeCodes.SHANGHAI_FULL,
                "SZ" => MarketData.Replay.Utils.ExchangeCodes.SHENZHEN_FULL,
                _ => parts[1]
            };
            return $"{exchange}.{code}";
        }
        return symbol;
    }

    /// <summary>
    /// Convert GM API format to standard format
    /// Example: SHSE.600000 -> SH.600000
    /// </summary>
    public static string FromGMSymbol(string symbol)
    {
        if (string.IsNullOrEmpty(symbol))
            return symbol;

        var parts = symbol.Split('.');
        if (parts.Length == 2)
        {
            var exchange = parts[0];
            var code = parts[1];
            string exchangeSuffix = exchange.ToUpper() switch
            {
                MarketData.Replay.Utils.ExchangeCodes.SHANGHAI_FULL => MarketData.Replay.Utils.ExchangeCodes.SHANGHAI,
                MarketData.Replay.Utils.ExchangeCodes.SHENZHEN_FULL => MarketData.Replay.Utils.ExchangeCodes.SHENZHEN,
                _ => exchange
            };
            return $"{code}.{exchangeSuffix}";
        }
        return symbol;
    }

    /// <summary>
    /// Batch convert standard format to GM format
    /// </summary>
    public static List<string> ToGMSymbols(List<string> symbols)
    {
        return symbols.Select(ToGMSymbol).ToList();
    }

    /// <summary>
    /// Batch convert GM format to standard format
    /// </summary>
    public static List<string> FromGMSymbols(List<string> symbols)
    {
        return symbols.Select(FromGMSymbol).ToList();
    }
}
