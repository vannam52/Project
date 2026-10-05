using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using VideoSubtitle.API.Data;
using VideoSubtitle.API.Hubs;
using VideoSubtitle.API.Services;

namespace VideoSubtitle.API.Controllers;

[ApiController]
[Route("api/[controller]")]
[Produces("application/json")]
public class JobsController : ControllerBase
{
    private readonly AppDbContext _db;
    private readonly IStorageService _storage;
    private readonly IJobNotificationService _notify;
    private readonly ILogger<JobsController> _logger;

    public JobsController(AppDbContext db, IStorageService storage, IJobNotificationService notify, ILogger<JobsController> logger)
    {
        _db = db;
        _storage = storage;
        _notify = notify;
        _logger = logger;
    }

    /// <summary>
    /// Kiểm tra trạng thái job
    /// GET /api/jobs/{jobId}/status
    /// </summary>
    [HttpGet("{jobId:guid}/status")]
    public async Task<IActionResult> GetJobStatus(Guid jobId)
    {
        var job = await _db.TranslationJobs
            .Include(j => j.Video)
            .Include(j => j.Steps.OrderBy(s => s.StartedAt))
            .FirstOrDefaultAsync(j => j.Id == jobId);

        if (job is null) return NotFound(new { error = $"Không tìm thấy job {jobId}" });

        // Tính % tiến độ dựa trên trạng thái
        float progress = job.Status switch
        {
            Models.JobStatus.Pending         => 0f,
            Models.JobStatus.ExtractingAudio => 20f,
            Models.JobStatus.Transcribing    => 40f,
            Models.JobStatus.Translating     => 65f,
            Models.JobStatus.Rendering       => 85f,
            Models.JobStatus.Completed       => 100f,
            Models.JobStatus.Failed          => 0f,
            _ => 0f
        };

        // Tạo presigned URL nếu đã xong
        string? videoUrl = null;
        string? subtitleUrl = null;

        if (job.Status == Models.JobStatus.Completed)
        {
            if (job.OutputVideoKey != null)
                videoUrl = await _storage.GetPresignedUrlAsync(job.OutputVideoKey);
            if (job.OutputSubtitleKey != null)
                subtitleUrl = await _storage.GetPresignedUrlAsync(job.OutputSubtitleKey);
        }

        return Ok(new
        {
            jobId = job.Id,
            videoId = job.VideoId,
            videoName = job.Video.OriginalName,
            status = job.Status.ToString().ToLower(),
            targetLanguage = job.TargetLanguage,
            progressPercent = progress,
            outputVideoUrl = videoUrl,
            outputSubtitleUrl = subtitleUrl,
            errorMessage = job.ErrorMessage,
            createdAt = job.CreatedAt,
            completedAt = job.CompletedAt,
            processingSecs = job.ProcessingSecs,
            steps = job.Steps.Select(s => new
            {
                stepName = s.StepName,
                status = s.Status,
                logMessage = s.LogMessage,
                startedAt = s.StartedAt,
                finishedAt = s.FinishedAt
            })
        });
    }

    /// <summary>
    /// Lấy tất cả segments phụ đề của job (phân trang)
    /// GET /api/jobs/{jobId}/segments
    /// </summary>
    [HttpGet("{jobId:guid}/segments")]
    public async Task<IActionResult> GetSegments(Guid jobId, [FromQuery] int page = 1, [FromQuery] int pageSize = 50)
    {
        if (!await _db.TranslationJobs.AnyAsync(j => j.Id == jobId))
            return NotFound();

        var total = await _db.SubtitleSegments.CountAsync(s => s.JobId == jobId);
        var segments = await _db.SubtitleSegments
            .Where(s => s.JobId == jobId)
            .OrderBy(s => s.SegmentIndex)
            .Skip((page - 1) * pageSize)
            .Take(pageSize)
            .Select(s => new
            {
                s.SegmentIndex,
                s.StartTimeMs,
                s.EndTimeMs,
                startFormatted = FormatTimestamp(s.StartTimeMs),
                endFormatted   = FormatTimestamp(s.EndTimeMs),
                s.OriginalText,
                s.TranslatedText,
                s.Confidence
            })
            .ToListAsync();

        return Ok(new { items = segments, totalCount = total, page, pageSize });
    }

    /// <summary>
    /// Tải file .srt/.vtt phụ đề trực tiếp
    /// GET /api/jobs/{jobId}/download/subtitle
    /// </summary>
    [HttpGet("{jobId:guid}/download/subtitle")]
    public async Task<IActionResult> DownloadSubtitle(Guid jobId, CancellationToken ct)
    {
        var job = await _db.TranslationJobs.FindAsync([jobId], ct);

        if (job is null) return NotFound();
        if (job.Status != Models.JobStatus.Completed || job.OutputSubtitleKey is null)
            return BadRequest(new { error = "Job chưa hoàn thành." });

        var stream = await _storage.DownloadFileAsync(job.OutputSubtitleKey, ct);
        var fileName = $"subtitle_{job.TargetLanguage}.{job.SubtitleFormat.ToString().ToLower()}";
        return File(stream, "text/plain", fileName);
    }

    /// <summary>
    /// Webhook endpoint — Python Workers gọi để cập nhật trạng thái
    /// POST /api/jobs/{jobId}/callback
    /// </summary>
    [HttpPost("{jobId:guid}/callback")]
    public async Task<IActionResult> WorkerCallback(Guid jobId, [FromBody] WorkerCallbackRequest req, CancellationToken ct)
    {
        var job = await _db.TranslationJobs.FindAsync([jobId], ct);
        if (job is null) return NotFound();

        job.Status = Enum.Parse<Models.JobStatus>(req.Status, ignoreCase: true);

        if (req.Status.Equals("completed", StringComparison.OrdinalIgnoreCase))
        {
            job.CompletedAt    = DateTime.UtcNow;
            job.ProcessingSecs = (float)(DateTime.UtcNow - (job.StartedAt ?? DateTime.UtcNow)).TotalSeconds;
            job.OutputVideoKey    = req.OutputVideoKey;
            job.OutputSubtitleKey = req.OutputSubtitleKey;

            // Push SignalR notification
            if (req.OutputVideoKey != null && req.OutputSubtitleKey != null)
            {
                var videoUrl    = await _storage.GetPresignedUrlAsync(req.OutputVideoKey);
                var subtitleUrl = await _storage.GetPresignedUrlAsync(req.OutputSubtitleKey);
                await _notify.NotifyJobCompletedAsync(jobId, videoUrl, subtitleUrl);
            }
        }
        else if (req.Status.Equals("failed", StringComparison.OrdinalIgnoreCase))
        {
            job.ErrorMessage = req.ErrorMessage;
            await _notify.NotifyJobFailedAsync(jobId, req.ErrorMessage ?? "Lỗi không xác định");
        }
        else
        {
            await _notify.NotifyJobStatusChangedAsync(jobId, req.Status);
        }

        await _db.SaveChangesAsync(ct);
        return Ok(new { message = "Updated" });
    }

    // Hàm helper: chuyển milliseconds → "HH:MM:SS,mmm"
    private static string FormatTimestamp(int ms)
    {
        var ts = TimeSpan.FromMilliseconds(ms);
        return $"{ts.Hours:D2}:{ts.Minutes:D2}:{ts.Seconds:D2},{ts.Milliseconds:D3}";
    }
}

public record WorkerCallbackRequest(
    string Status,
    string? OutputVideoKey,
    string? OutputSubtitleKey,
    string? ErrorMessage
);
