using Microsoft.EntityFrameworkCore;
using VideoSubtitle.API.Models;

namespace VideoSubtitle.API.Data;

public class AppDbContext(DbContextOptions<AppDbContext> options) : DbContext(options)
{
    public DbSet<Video> Videos => Set<Video>();
    public DbSet<TranslationJob> TranslationJobs => Set<TranslationJob>();
    public DbSet<JobStep> JobSteps => Set<JobStep>();
    public DbSet<SubtitleSegment> SubtitleSegments => Set<SubtitleSegment>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        base.OnModelCreating(modelBuilder);

        // ── Video ──────────────────────────────────────────────
        modelBuilder.Entity<Video>(entity =>
        {
            entity.ToTable("videos");
            entity.HasKey(e => e.Id);
            entity.Property(e => e.Id).HasColumnName("id");
            entity.Property(e => e.OriginalName).HasColumnName("original_name").HasMaxLength(500);
            entity.Property(e => e.StorageKey).HasColumnName("storage_key").HasMaxLength(1000);
            entity.Property(e => e.FileSizeBytes).HasColumnName("file_size_bytes");
            entity.Property(e => e.DurationSecs).HasColumnName("duration_secs");
            entity.Property(e => e.MimeType).HasColumnName("mime_type").HasMaxLength(100);
            entity.Property(e => e.SourceLanguage).HasColumnName("source_language").HasMaxLength(10);
            entity.Property(e => e.CreatedAt).HasColumnName("created_at");
            entity.Property(e => e.UpdatedAt).HasColumnName("updated_at");

            entity.HasMany(v => v.TranslationJobs)
                  .WithOne(j => j.Video)
                  .HasForeignKey(j => j.VideoId)
                  .OnDelete(DeleteBehavior.Cascade);
        });

        // ── TranslationJob ─────────────────────────────────────
        modelBuilder.Entity<TranslationJob>(entity =>
        {
            entity.ToTable("translation_jobs");
            entity.HasKey(e => e.Id);
            entity.Property(e => e.Id).HasColumnName("id");
            entity.Property(e => e.VideoId).HasColumnName("video_id");
            entity.Property(e => e.TargetLanguage).HasColumnName("target_language").HasMaxLength(10);
            entity.Property(e => e.SubtitleFormat)
                  .HasColumnName("subtitle_format")
                  .HasConversion<string>()
                  .HasColumnType("subtitle_format");
            entity.Property(e => e.TranslationProvider)
                  .HasColumnName("translation_provider")
                  .HasConversion<string>()
                  .HasColumnType("translation_provider");
            entity.Property(e => e.Status)
                  .HasColumnName("status")
                  .HasConversion<string>()
                  .HasColumnType("job_status");
            entity.Property(e => e.OutputVideoKey).HasColumnName("output_video_key");
            entity.Property(e => e.OutputSubtitleKey).HasColumnName("output_subtitle_key");
            entity.Property(e => e.ErrorMessage).HasColumnName("error_message");
            entity.Property(e => e.RetryCount).HasColumnName("retry_count");
            entity.Property(e => e.StartedAt).HasColumnName("started_at");
            entity.Property(e => e.CompletedAt).HasColumnName("completed_at");
            entity.Property(e => e.ProcessingSecs).HasColumnName("processing_secs");
            entity.Property(e => e.CreatedAt).HasColumnName("created_at");
            entity.Property(e => e.UpdatedAt).HasColumnName("updated_at");

            entity.HasMany(j => j.Steps)
                  .WithOne(s => s.Job)
                  .HasForeignKey(s => s.JobId)
                  .OnDelete(DeleteBehavior.Cascade);

            entity.HasMany(j => j.Segments)
                  .WithOne(s => s.Job)
                  .HasForeignKey(s => s.JobId)
                  .OnDelete(DeleteBehavior.Cascade);
        });

        // ── JobStep ────────────────────────────────────────────
        modelBuilder.Entity<JobStep>(entity =>
        {
            entity.ToTable("job_steps");
            entity.HasKey(e => e.Id);
            entity.Property(e => e.Id).HasColumnName("id");
            entity.Property(e => e.JobId).HasColumnName("job_id");
            entity.Property(e => e.StepName).HasColumnName("step_name").HasMaxLength(100);
            entity.Property(e => e.WorkerName).HasColumnName("worker_name").HasMaxLength(100);
            entity.Property(e => e.Status).HasColumnName("status").HasMaxLength(50);
            entity.Property(e => e.LogMessage).HasColumnName("log_message");
            entity.Property(e => e.StartedAt).HasColumnName("started_at");
            entity.Property(e => e.FinishedAt).HasColumnName("finished_at");
        });

        // ── SubtitleSegment ────────────────────────────────────
        modelBuilder.Entity<SubtitleSegment>(entity =>
        {
            entity.ToTable("subtitle_segments");
            entity.HasKey(e => e.Id);
            entity.Property(e => e.Id).HasColumnName("id");
            entity.Property(e => e.JobId).HasColumnName("job_id");
            entity.Property(e => e.SegmentIndex).HasColumnName("segment_index");
            entity.Property(e => e.StartTimeMs).HasColumnName("start_time_ms");
            entity.Property(e => e.EndTimeMs).HasColumnName("end_time_ms");
            entity.Property(e => e.OriginalText).HasColumnName("original_text");
            entity.Property(e => e.TranslatedText).HasColumnName("translated_text");
            entity.Property(e => e.Confidence).HasColumnName("confidence");
            entity.Property(e => e.CreatedAt).HasColumnName("created_at");
        });
    }
}
