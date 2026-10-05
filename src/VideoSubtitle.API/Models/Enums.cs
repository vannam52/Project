namespace VideoSubtitle.API.Models;

/// <summary>
/// Trạng thái của một translation job trong pipeline
/// </summary>
public enum JobStatus
{
    Pending,
    ExtractingAudio,
    Transcribing,
    Translating,
    Rendering,
    Completed,
    Failed
}

public enum SubtitleFormat
{
    Srt,
    Vtt,
    Ass
}

public enum TranslationProvider
{
    Google,
    DeepL,
    Gemini,
    Libre
}
