using ExecutionService.Data.IRepositories;
using ExecutionService.Models;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;

namespace Execution.Service.Controllers;

/// <summary>
/// Read-only REST query API for live position state.
///
/// Reads directly from <see cref="IPositionRepository"/> (PostgreSQL) rather
/// than from the in-memory <c>PositionManager</c>. The manager uses per-
/// (session, symbol) <c>SemaphoreSlim</c> locks for write coordination; REST
/// consumers must not contend on those locks for ad-hoc reads. PG reads see
/// the same committed state the dashboard needs, and in-flight fills write
/// to PG immediately on each gRPC terminal status, so the latency is bounded.
/// </summary>
[ApiController]
[Route("api/[controller]")]
public class PositionsController : ControllerBase
{
    private readonly IPositionRepository _positionRepo;
    private readonly ILogger<PositionsController> _logger;

    public PositionsController(IPositionRepository positionRepo, ILogger<PositionsController> logger)
    {
        _positionRepo = positionRepo;
        _logger = logger;
    }

    /// <summary>Get every position for a session, including flat (Quantity == 0) rows.</summary>
    [HttpGet("{sessionId}")]
    public async Task<ActionResult<IEnumerable<Position>>> GetAll(string sessionId)
    {
        try
        {
            var positions = await _positionRepo.GetPositionsBySessionAsync(sessionId);
            return Ok(positions);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to query positions for session {SessionId}", sessionId);
            return BadRequest(new { error = ex.Message });
        }
    }

    /// <summary>Get a single position by (session, symbol).</summary>
    [HttpGet("{sessionId}/{symbol}")]
    public async Task<ActionResult<Position>> GetOne(string sessionId, string symbol)
    {
        try
        {
            var position = await _positionRepo.GetPositionAsync(sessionId, symbol);
            if (position == null)
                return NotFound(new { error = $"No position for {symbol} in session {sessionId}" });
            return Ok(position);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to query position {Symbol} for session {SessionId}", symbol, sessionId);
            return BadRequest(new { error = ex.Message });
        }
    }
}
