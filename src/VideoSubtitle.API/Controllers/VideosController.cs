using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using VideoSubtitle.API.Data;
using VideoSubtitle.API.DTOs;
using VideoSubtitle.API.Models;
using VideoSubtitle.API.Services;

namespace VideoSubtitle.API.Controllers;

[ApiController]
[Route("api/[controller]")]
[Produces("application/json")]
public class VideosController : ControllerBase
{
    private readonly AppDbContext _db;
    private readonly IStorageService _storage;
    private readonly IMessageQueueService _mq;
    private readonly ILogger<VideosController> _logger;

    // Giới hạn file upload: 500MB
    private const long MaxFileSizeBytes = 500 * 1024 * 1024;
    private static readonly string[] AllowedMimeTypes = ["video/mp4", "video/quicktime", "video/x-msvideo", "video/webm"];

    public VideosController(AppDbContext db, IStorageService storage, IMessageQueueService mq, ILogger<VideosController> logger)
    {
        _db = db;
        _storage = storage;
        _mq = mq;
        _logger = logger;
    }

    /// <summary>
    /// Upload video và bắt đầu pipeline dịch thuật
    /// POST /api/videos/upload
    /// </summary>
    [HttpPost("upload")]
    [RequestSizeLimit(524288000)] // 500MB
    public async Task<IActionResult> UploadVideo(
        [FromForm] IFormFile file,
        [FromForm] UploadVideoRequest request,
        CancellationToken ct)
    {
        // Validation
        if (file.Length == 0)
            return BadRequest(new { error = "File trống." });

        if (file.Length > MaxFileSizeBytes)
            return BadRequest(new { error = $"File quá lớn. Tối đa {MaxFileSizeBytes / 1024 / 1024}MB." });

        if (!AllowedMimeTypes.Contains(file.ContentType))
            return BadRequest(new { error = "Chỉ chấp nhận file video (mp4, mov, avi, webm)." });

        _logger.LogInformation("Uploading video: {FileName} ({Size} bytes)", file.FileName, file.Length);

        // 1. Upload lên MinIO
        await _storage.EnsureBucketExistsAsync(ct);
        var storageKey = await _storage.UploadFileAsync(file.OpenReadStream(), file.FileName, file.ContentType, ct);

        // 2. Lưu metadata vào PostgreSQL
        var video = new Video
        {
            OriginalName    = file.FileName,
            StorageKey      = storageKey,
            FileSizeBytes   = file.Length,
            SourceLanguage  = request.SourceLanguage,
            MimeType        = file.ContentType
        };
        _db.Videos.Add(video);

        var job = new TranslationJob
        {
            VideoId             = video.Id,
            TargetLanguage      = request.TargetLanguage,
            SubtitleFormat      = Enum.Parse<SubtitleFormat>(request.SubtitleFormat, ignoreCase: true),
            TranslationProvider = Enum.Parse<TranslationProvider>(request.TranslationProvider, ignoreCase: true),
            Status              = JobStatus.Pending,
            StartedAt           = DateTime.UtcNow
        };
        _db.TranslationJobs.Add(job);
        await _db.SaveChangesAsync(ct);

        // 3. Đẩy message vào RabbitMQ → kích hoạt Worker 1
        await _mq.PublishVideoJobAsync(new VideoJobMessage(
            JobId: job.Id,
            VideoId: video.Id,
            StorageKey: storageKey,
            TargetLanguage: request.TargetLanguage,
            SourceLanguage: request.SourceLanguage,
            SubtitleFormat: request.SubtitleFormat,
            TranslationProvider: request.TranslationProvider,
            CreatedAt: job.CreatedAt
        ));

        // 4. Trả về ngay lập tức
        return Accepted(new UploadVideoResponse(
            JobId: job.Id,
            VideoId: video.Id,
            Message: "Video đang được xử lý. Vui lòng theo dõi trạng thái.",
            StatusCheckUrl: $"/api/jobs/{job.Id}/status"
        ));
    }

    /// <summary>
    /// Lấy danh sách video đã upload (phân trang)
    /// GET /api/videos?page=1&pageSize=10
    /// </summary>
    [HttpGet]
    public async Task<IActionResult> GetVideos([FromQuery] int page = 1, [FromQuery] int pageSize = 10)
    {
        var query = _db.Videos.OrderByDescending(v => v.CreatedAt);
        var total = await query.CountAsync();
        var items = await query
            .Skip((page - 1) * pageSize)
            .Take(pageSize)
            .Select(v => new
            {
                v.Id,
                v.OriginalName,
                v.FileSizeBytes,
                v.DurationSecs,
                v.SourceLanguage,
                v.CreatedAt,
                JobCount = v.TranslationJobs.Count
            })
            .ToListAsync();

        return Ok(new { items, totalCount = total, page, pageSize, totalPages = (int)Math.Ceiling(total / (double)pageSize) });
    }

    /// <summary>
    /// Lấy chi tiết một video
    /// GET /api/videos/{id}
    /// </summary>
    [HttpGet("{id:guid}")]
    public async Task<IActionResult> GetVideo(Guid id)
    {
        var video = await _db.Videos
            .Include(v => v.TranslationJobs)
            .FirstOrDefaultAsync(v => v.Id == id);

        if (video is null) return NotFound();
        return Ok(video);
    }

    /// <summary>
    /// Xóa video và tất cả job liên quan
    /// DELETE /api/videos/{id}
    /// </summary>
    [HttpDelete("{id:guid}")]
    public async Task<IActionResult> DeleteVideo(Guid id, CancellationToken ct)
    {
        var video = await _db.Videos.FindAsync([id], ct);
        if (video is null) return NotFound();

        await _storage.DeleteFileAsync(video.StorageKey, ct);
        _db.Videos.Remove(video);
        await _db.SaveChangesAsync(ct);

        return NoContent();
    }
}
