using ExecutionService.Data.IRepositories;
using ExecutionService.Models;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;

namespace ExecutionService.Controllers;

/// <summary>
/// Read-only REST query API for orders. Used by the dashboard to surface
/// live rejected / filled / pending orders without going through gRPC.
///
/// Reads directly from <see cref="IOrderRepository"/> (PostgreSQL). Optional
/// <c>?status=rejected|filled|partial|cancelled|pending|expired</c> filter
/// (case-insensitive) lets the dashboard fetch only the slice it needs.
/// </summary>
[ApiController]
[Route("api/[controller]")]
public class OrdersController : ControllerBase
{
    private readonly IOrderRepository _orderRepo;
    private readonly ILogger<OrdersController> _logger;

    public OrdersController(IOrderRepository orderRepo, ILogger<OrdersController> logger)
    {
        _orderRepo = orderRepo;
        _logger = logger;
    }

    /// <summary>
    /// List orders for a session. Optional status filter:
    /// <c>GET /api/Orders/{sessionId}?status=rejected</c>.
    /// </summary>
    [HttpGet("{sessionId}")]
    public async Task<ActionResult<IEnumerable<Order>>> GetOrders(
        string sessionId,
        [FromQuery] string? status = null)
    {
        try
        {
            var orders = await _orderRepo.GetOrdersBySessionAsync(sessionId);

            if (!string.IsNullOrWhiteSpace(status))
            {
                if (!Enum.TryParse<OrderStatus>(status, ignoreCase: true, out var wanted))
                {
                    return BadRequest(new
                    {
                        error = $"Unknown status '{status}'. Valid: {string.Join(", ", Enum.GetNames<OrderStatus>())}"
                    });
                }
                orders = orders.Where(o => o.Status == wanted).ToList();
            }

            return Ok(orders);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to query orders for session {SessionId}", sessionId);
            return BadRequest(new { error = ex.Message });
        }
    }

    /// <summary>Fetch a single order by its client order id.</summary>
    [HttpGet("{sessionId}/{orderId}")]
    public async Task<ActionResult<Order>> GetOne(string sessionId, string orderId)
    {
        try
        {
            var order = await _orderRepo.GetOrderAsync(sessionId, orderId);
            if (order == null)
                return NotFound(new { error = $"No order {orderId} in session {sessionId}" });
            return Ok(order);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to query order {OrderId} for session {SessionId}", orderId, sessionId);
            return BadRequest(new { error = ex.Message });
        }
    }
}
