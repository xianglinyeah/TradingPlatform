using Microsoft.AspNetCore.Mvc;
using MarketData.Replay.Core;
using MarketData.Replay.Models;
using MarketData.Replay.Utils;
using Microsoft.Extensions.Logging;
using Npgsql;

namespace MarketData.Replay.Controllers;

[ApiController]
[Route("api/[controller]")]
public class ReplayController : ControllerBase
{
    private readonly IReplayEngine _engine;
    private readonly ILogger<ReplayController> _logger;
    private readonly string _pgConnectionString;

    public ReplayController(IReplayEngine engine, ILogger<ReplayController> logger)
    {
        _engine = engine;
        _logger = logger;
        _pgConnectionString = Environment.GetEnvironmentVariable("UNIVERSE_PG_CONN")
            ?? "Host=postgres.infrastructure;Port=5432;Username=dev_user;Password=dev_pass;Database=dev";
    }

    /// <summary>
    /// Start replay
    /// </summary>
    /// <param name="request">Replay configuration request</param>
    /// <returns>Session information</returns>
    [HttpPost("start")]
    public async Task<ActionResult<ReplaySession>> StartReplay([FromBody] StartReplayApiRequest request)
    {
        try
        {
            // Resolve universe_id -> symbols list. Explicit Symbols list wins
            // for backward compatibility; universe_id is used only when Symbols
            // is empty. Point-in-time queries use the request's StartTime date
            // so the replay matches historical membership exactly.
            var symbols = request.Symbols;
            if ((symbols == null || symbols.Count == 0) && !string.IsNullOrWhiteSpace(request.UniverseId))
            {
                symbols = await ResolveUniverseMembersAsync(request.UniverseId, DateOnly.FromDateTime(request.StartTime));
                _logger.LogInformation("Resolved universe_id={UniverseId} -> {Count} symbols",
                    request.UniverseId, symbols.Count);
            }

            var config = new ReplayConfig
            {
                StartTime = request.StartTime,
                EndTime = request.EndTime,
                Symbols = symbols ?? new(),
                SpeedFactor = request.SpeedFactor
            };

            var sessionId = await _engine.StartAsync(config);
            var session = await _engine.GetStatusAsync(sessionId);

            _logger.LogInformation("Replay started: {SessionId}", sessionId);
            return CreatedAtAction(nameof(GetStatus), new { id = sessionId }, session);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to start replay");
            return BadRequest(new { error = ex.Message });
        }
    }

    /// <summary>
    /// Resolve active universe members as of a specific date from market_ref.
    /// </summary>
    private async Task<List<string>> ResolveUniverseMembersAsync(string universeId, DateOnly asOf)
    {
        var result = new List<string>();
        await using var conn = new NpgsqlConnection(_pgConnectionString);
        await conn.OpenAsync();
        await using var cmd = conn.CreateCommand();
        cmd.CommandText = @"
            SELECT symbol FROM market_ref.universe_member
            WHERE universe_id = @universe_id
              AND effective_from <= @as_of
              AND (effective_to IS NULL OR effective_to >= @as_of)
            ORDER BY symbol";
        cmd.Parameters.AddWithValue("universe_id", universeId);
        cmd.Parameters.AddWithValue("as_of", asOf);
        await using var reader = await cmd.ExecuteReaderAsync();
        while (await reader.ReadAsync())
        {
            result.Add(reader.GetString(0));
        }
        return result;
    }

    /// <summary>
    /// Get replay status
    /// </summary>
    /// <param name="id">Session ID</param>
    /// <returns>Session status</returns>
    [HttpGet("status/{id}")]
    public async Task<ActionResult<ReplaySession>> GetStatus(string id)
    {
        try
        {
            var session = await _engine.GetStatusAsync(id);
            if (session == null)
                return NotFound(new { error = ReplayErrorMessages.SESSION_NOT_FOUND });

            return Ok(session);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to get status");
            return BadRequest(new { error = ex.Message });
        }
    }

    /// <summary>
    /// Stop replay
    /// </summary>
    /// <param name="id">Session ID</param>
    /// <returns>Confirmation message</returns>
    [HttpPost("stop/{id}")]
    public async Task<ActionResult> StopReplay(string id)
    {
        try
        {
            await _engine.StopAsync(id);
            _logger.LogInformation("Replay stopped: {SessionId}", id);
            return Ok(new { message = ReplayErrorMessages.REPLAY_STOPPED, sessionId = id });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to stop replay");
            return BadRequest(new { error = ex.Message });
        }
    }

    /// <summary>
    /// Pause replay
    /// </summary>
    /// <param name="id">Session ID</param>
    /// <returns>Session status</returns>
    [HttpPost("pause/{id}")]
    public async Task<ActionResult<ReplaySession>> PauseReplay(string id)
    {
        try
        {
            await _engine.PauseAsync(id);
            var session = await _engine.GetStatusAsync(id);
            _logger.LogInformation("Replay paused: {SessionId}", id);
            return Ok(session);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to pause replay");
            return BadRequest(new { error = ex.Message });
        }
    }

    /// <summary>
    /// Resume replay
    /// </summary>
    /// <param name="id">Session ID</param>
    /// <returns>Session status</returns>
    [HttpPost("resume/{id}")]
    public async Task<ActionResult<ReplaySession>> ResumeReplay(string id)
    {
        try
        {
            await _engine.ResumeAsync(id);
            var session = await _engine.GetStatusAsync(id);
            _logger.LogInformation("Replay resumed: {SessionId}", id);
            return Ok(session);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to resume replay");
            return BadRequest(new { error = ex.Message });
        }
    }
}

// API request data transfer object
public class StartReplayApiRequest
{
    /// <summary>Explicit symbol list (TS format, e.g. "600000.SH"). Wins over UniverseId.</summary>
    public List<string> Symbols { get; set; } = new();
    /// <summary>Universe ID to resolve from market_ref.universe_member (e.g. "csi300").
    /// Used only when Symbols is empty.</summary>
    public string? UniverseId { get; set; }
    public DateTime StartTime { get; set; }
    public DateTime EndTime { get; set; }
    public double SpeedFactor { get; set; }
}
