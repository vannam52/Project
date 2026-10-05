namespace VideoSubtitle.API.DTOs;

// ── Request DTOs ──────────────────────────────────────────────

public record UploadVideoRequest(
    string TargetLanguage,                          // 'vi', 'en', 'ja', ...
    string SourceLanguage = "auto",
    string SubtitleFormat = "srt",                  // 'srt' | 'vtt'
    string TranslationProvider = "google"           // 'google' | 'deepl' | 'gemini'
);

// ── Response DTOs ─────────────────────────────────────────────

public record UploadVideoResponse(
    Guid JobId,
    Guid VideoId,
    string Message,
    string StatusCheckUrl
);

public record JobStatusResponse(
    Guid JobId,
    Guid VideoId,
    string Status,
    string TargetLanguage,
    float? ProgressPercent,
    string? OutputVideoUrl,
    string? OutputSubtitleUrl,
    string? ErrorMessage,
    DateTime CreatedAt,
    DateTime? CompletedAt,
    float? ProcessingSecs,
    List<StepInfo> Steps
);

public record StepInfo(
    string StepName,
    string Status,
    string? LogMessage,
    DateTime StartedAt,
    DateTime? FinishedAt
);

public record SubtitleSegmentResponse(
    int Index,
    int StartTimeMs,
    int EndTimeMs,
    string StartTimeFormatted,   // "00:01:23,456"
    string EndTimeFormatted,
    string OriginalText,
    string? TranslatedText,
    float? Confidence
);

public record PagedResponse<T>(
    List<T> Items,
    int TotalCount,
    int Page,
    int PageSize,
    int TotalPages
);
