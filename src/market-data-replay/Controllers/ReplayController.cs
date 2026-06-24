using Microsoft.AspNetCore.Mvc;
using MarketData.Replay.Core;
using MarketData.Replay.Models;
using MarketData.Replay.Utils;
using Microsoft.Extensions.Logging;

namespace MarketData.Replay.Controllers;

[ApiController]
[Route("api/[controller]")]
public class ReplayController : ControllerBase
{
    private readonly IReplayEngine _engine;
    private readonly ILogger<ReplayController> _logger;

    public ReplayController(IReplayEngine engine, ILogger<ReplayController> logger)
    {
        _engine = engine;
        _logger = logger;
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
            var config = new ReplayConfig
            {
                StartTime = request.StartTime,
                EndTime = request.EndTime,
                Symbols = request.Symbols,
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
    public List<string> Symbols { get; set; } = new();
    public DateTime StartTime { get; set; }
    public DateTime EndTime { get; set; }
    public double SpeedFactor { get; set; }
}
