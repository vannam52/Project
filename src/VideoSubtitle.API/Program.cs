using Microsoft.EntityFrameworkCore;
using Minio;
using VideoSubtitle.API.Data;
using VideoSubtitle.API.Hubs;
using VideoSubtitle.API.Services;

var builder = WebApplication.CreateBuilder(args);

// ── Services ───────────────────────────────────────────────────
builder.Services.AddControllers();
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(c =>
{
    c.SwaggerDoc("v1", new()
    {
        Title       = "VideoSubtitle API",
        Version     = "v1",
        Description = "API quản lý pipeline dịch thuật và ghép phụ đề video tự động"
    });
});

// PostgreSQL + EF Core
builder.Services.AddDbContext<AppDbContext>(options =>
    options.UseNpgsql(builder.Configuration.GetConnectionString("DefaultConnection")));

// MinIO Client — FIX: dùng AddMinio đúng cách với ServiceCollection extension
builder.Services.AddMinio(minioClient =>
{
    minioClient
        .WithEndpoint(builder.Configuration["MinIO:Endpoint"] ?? "localhost:9000")
        .WithCredentials(
            builder.Configuration["MinIO:AccessKey"] ?? "minioadmin",
            builder.Configuration["MinIO:SecretKey"] ?? "minioadmin")
        .WithSSL(false);
});

// Custom Services — FIX: RabbitMqService là IAsyncDisposable, đăng ký Singleton đúng
builder.Services.AddSingleton<IMessageQueueService, RabbitMqService>();
builder.Services.AddScoped<IStorageService, MinioStorageService>();
builder.Services.AddScoped<IJobNotificationService, JobNotificationService>();

// SignalR
builder.Services.AddSignalR();

// CORS — cho phép frontend dev kết nối
builder.Services.AddCors(options =>
{
    options.AddPolicy("AllowDev", policy =>
        policy.WithOrigins("http://localhost:3000", "http://localhost:5173")
              .AllowAnyHeader()
              .AllowAnyMethod()
              .AllowCredentials()); // Required cho SignalR
});

// ── App Pipeline ───────────────────────────────────────────────
var app = builder.Build();

app.UseSwagger();
app.UseSwaggerUI(c =>
{
    c.SwaggerEndpoint("/swagger/v1/swagger.json", "VideoSubtitle API v1");
    c.RoutePrefix = string.Empty; // Swagger tại root "/"
});

app.UseCors("AllowDev");
app.UseAuthorization();
app.MapControllers();

// SignalR Hub endpoint
app.MapHub<JobHub>("/hubs/job");

// Health check đơn giản
app.MapGet("/health", () => Results.Ok(new { status = "healthy", timestamp = DateTime.UtcNow }));

// Auto-migrate DB khi khởi động (chỉ dev — trong prod dùng EF migrations)
try
{
    using var scope = app.Services.CreateScope();
    var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
    await db.Database.EnsureCreatedAsync();
    app.Logger.LogInformation("Database schema verified.");
}
catch (Exception ex)
{
    app.Logger.LogWarning("DB not available at startup (will retry on first request): {Msg}", ex.Message);
}

await app.RunAsync();
