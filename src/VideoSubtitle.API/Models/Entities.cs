namespace VideoSubtitle.API.Models;

/// <summary>
/// Video gốc được người dùng upload
/// </summary>
public class Video
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public string OriginalName { get; set; } = string.Empty;
    public string StorageKey { get; set; } = string.Empty;      // Key trên MinIO
    public long FileSizeBytes { get; set; }
    public float? DurationSecs { get; set; }
    public string MimeType { get; set; } = "video/mp4";
    public string SourceLanguage { get; set; } = "auto";        // 'auto' = Whisper detect
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public DateTime UpdatedAt { get; set; } = DateTime.UtcNow;

    // Navigation
    public ICollection<TranslationJob> TranslationJobs { get; set; } = [];
}

/// <summary>
/// Một job dịch video sang ngôn ngữ cụ thể
/// </summary>
public class TranslationJob
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid VideoId { get; set; }
    public string TargetLanguage { get; set; } = string.Empty;  // 'vi', 'en', 'ja', ...
    public SubtitleFormat SubtitleFormat { get; set; } = SubtitleFormat.Srt;
    public TranslationProvider TranslationProvider { get; set; } = TranslationProvider.Google;
    public JobStatus Status { get; set; } = JobStatus.Pending;

    // Kết quả sau khi xử lý
    public string? OutputVideoKey { get; set; }
    public string? OutputSubtitleKey { get; set; }
    public string? ErrorMessage { get; set; }
    public int RetryCount { get; set; } = 0;

    // Thời gian
    public DateTime? StartedAt { get; set; }
    public DateTime? CompletedAt { get; set; }
    public float? ProcessingSecs { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public DateTime UpdatedAt { get; set; } = DateTime.UtcNow;

    // Navigation
    public Video Video { get; set; } = null!;
    public ICollection<JobStep> Steps { get; set; } = [];
    public ICollection<SubtitleSegment> Segments { get; set; } = [];
}

/// <summary>
/// Log của từng bước trong pipeline
/// </summary>
public class JobStep
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid JobId { get; set; }
    public string StepName { get; set; } = string.Empty;
    public string? WorkerName { get; set; }
    public string Status { get; set; } = "running";  // running | done | failed
    public string? LogMessage { get; set; }
    public DateTime StartedAt { get; set; } = DateTime.UtcNow;
    public DateTime? FinishedAt { get; set; }

    // Navigation
    public TranslationJob Job { get; set; } = null!;
}

/// <summary>
/// Từng câu phụ đề với timestamp
/// </summary>
public class SubtitleSegment
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid JobId { get; set; }
    public int SegmentIndex { get; set; }
    public int StartTimeMs { get; set; }    // milliseconds
    public int EndTimeMs { get; set; }      // milliseconds
    public string OriginalText { get; set; } = string.Empty;
    public string? TranslatedText { get; set; }
    public float? Confidence { get; set; }  // Whisper confidence 0-1
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

    // Navigation
    public TranslationJob Job { get; set; } = null!;
}
