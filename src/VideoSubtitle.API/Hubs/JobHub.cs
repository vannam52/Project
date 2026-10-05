using Microsoft.AspNetCore.SignalR;

namespace VideoSubtitle.API.Hubs;

/// <summary>
/// SignalR Hub — đẩy real-time notification về trình duyệt khi job hoàn thành
/// </summary>
public class JobHub : Hub
{
    private readonly ILogger<JobHub> _logger;

    public JobHub(ILogger<JobHub> logger)
    {
        _logger = logger;
    }

    /// <summary>
    /// Client gọi để đăng ký theo dõi một job cụ thể
    /// </summary>
    public async Task WatchJob(string jobId)
    {
        await Groups.AddToGroupAsync(Context.ConnectionId, $"job_{jobId}");
        _logger.LogInformation("Client {ConnectionId} watching job {JobId}", Context.ConnectionId, jobId);
    }

    public async Task UnwatchJob(string jobId)
    {
        await Groups.RemoveFromGroupAsync(Context.ConnectionId, $"job_{jobId}");
    }

    public override async Task OnConnectedAsync()
    {
        _logger.LogInformation("Client connected: {ConnectionId}", Context.ConnectionId);
        await base.OnConnectedAsync();
    }

    public override async Task OnDisconnectedAsync(Exception? exception)
    {
        _logger.LogInformation("Client disconnected: {ConnectionId}", Context.ConnectionId);
        await base.OnDisconnectedAsync(exception);
    }
}

/// <summary>
/// Service dùng để push notification từ Worker4 (sau khi xong) về browser
/// </summary>
public interface IJobNotificationService
{
    Task NotifyJobStatusChangedAsync(Guid jobId, string status, object? data = null);
    Task NotifyJobCompletedAsync(Guid jobId, string outputVideoUrl, string outputSubtitleUrl);
    Task NotifyJobFailedAsync(Guid jobId, string errorMessage);
}

public class JobNotificationService : IJobNotificationService
{
    private readonly IHubContext<JobHub> _hubContext;

    public JobNotificationService(IHubContext<JobHub> hubContext)
    {
        _hubContext = hubContext;
    }

    public async Task NotifyJobStatusChangedAsync(Guid jobId, string status, object? data = null)
    {
        await _hubContext.Clients
            .Group($"job_{jobId}")
            .SendAsync("JobStatusChanged", new { jobId, status, data, timestamp = DateTime.UtcNow });
    }

    public async Task NotifyJobCompletedAsync(Guid jobId, string outputVideoUrl, string outputSubtitleUrl)
    {
        await _hubContext.Clients
            .Group($"job_{jobId}")
            .SendAsync("JobCompleted", new
            {
                jobId,
                status = "completed",
                outputVideoUrl,
                outputSubtitleUrl,
                timestamp = DateTime.UtcNow
            });
    }

    public async Task NotifyJobFailedAsync(Guid jobId, string errorMessage)
    {
        await _hubContext.Clients
            .Group($"job_{jobId}")
            .SendAsync("JobFailed", new { jobId, status = "failed", errorMessage, timestamp = DateTime.UtcNow });
    }
}
