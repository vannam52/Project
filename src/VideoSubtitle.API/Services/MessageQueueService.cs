using System.Text;
using System.Text.Json;
using RabbitMQ.Client;

namespace VideoSubtitle.API.Services;

/// <summary>
/// Message gửi vào RabbitMQ để kích hoạt worker pipeline
/// </summary>
public record VideoJobMessage(
    Guid JobId,
    Guid VideoId,
    string StorageKey,
    string TargetLanguage,
    string SourceLanguage,
    string SubtitleFormat,
    string TranslationProvider,
    DateTime CreatedAt
);

public interface IMessageQueueService
{
    Task PublishVideoJobAsync(VideoJobMessage message);
}

/// <summary>
/// RabbitMQ Service dùng API v7 (async channel)
/// </summary>
public class RabbitMqService : IMessageQueueService, IAsyncDisposable
{
    private IConnection? _connection;
    private IChannel? _channel;
    private readonly IConfiguration _config;
    private readonly ILogger<RabbitMqService> _logger;

    // Queue names — phải khớp với Python workers
    public const string QueueVideoUploaded   = "video.uploaded";
    public const string QueueAudioExtracted  = "audio.extracted";
    public const string QueueTranscriptReady = "transcript.ready";
    public const string QueueTranslationDone = "translation.ready";
    public const string QueueDeadLetter      = "dead.letter";

    public RabbitMqService(IConfiguration config, ILogger<RabbitMqService> logger)
    {
        _config = config;
        _logger = logger;
    }

    private async Task EnsureConnectedAsync()
    {
        if (_connection is { IsOpen: true } && _channel is { IsOpen: true })
            return;

        var factory = new ConnectionFactory
        {
            HostName = _config["RabbitMQ:Host"] ?? "localhost",
            UserName = _config["RabbitMQ:Username"] ?? "guest",
            Password = _config["RabbitMQ:Password"] ?? "guest",
        };

        // Retry logic: RabbitMQ có thể chưa ready khi API start
        for (int attempt = 1; attempt <= 10; attempt++)
        {
            try
            {
                _connection = await factory.CreateConnectionAsync("VideoSubtitle.API");
                _channel    = await _connection.CreateChannelAsync();
                await DeclareQueuesAsync();
                _logger.LogInformation("Connected to RabbitMQ at {Host}", factory.HostName);
                return;
            }
            catch (Exception ex)
            {
                _logger.LogWarning("RabbitMQ not ready (attempt {Attempt}/10): {Msg}", attempt, ex.Message);
                if (attempt == 10) throw;
                await Task.Delay(TimeSpan.FromSeconds(5));
            }
        }
    }

    private async Task DeclareQueuesAsync()
    {
        if (_channel is null) return;

        // Dead Letter Exchange
        await _channel.ExchangeDeclareAsync("dlx", ExchangeType.Direct, durable: true);
        await _channel.QueueDeclareAsync(QueueDeadLetter, durable: true, exclusive: false, autoDelete: false);
        await _channel.QueueBindAsync(QueueDeadLetter, "dlx", QueueDeadLetter);

        var deadLetterArgs = new Dictionary<string, object?>
        {
            { "x-dead-letter-exchange", "dlx" },
            { "x-dead-letter-routing-key", QueueDeadLetter },
            { "x-message-ttl", 86400000 }
        };

        foreach (var queue in new[] { QueueVideoUploaded, QueueAudioExtracted, QueueTranscriptReady, QueueTranslationDone })
        {
            await _channel.QueueDeclareAsync(
                queue, durable: true, exclusive: false,
                autoDelete: false, arguments: deadLetterArgs);
        }

        _logger.LogInformation("RabbitMQ queues declared");
    }

    public async Task PublishVideoJobAsync(VideoJobMessage message)
    {
        await EnsureConnectedAsync();

        var body  = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(message));
        var props = new BasicProperties
        {
            Persistent  = true,
            ContentType = "application/json",
            MessageId   = message.JobId.ToString()
        };

        await _channel!.BasicPublishAsync(
            exchange: "",
            routingKey: QueueVideoUploaded,
            mandatory: false,
            basicProperties: props,
            body: body
        );

        _logger.LogInformation("Published job {JobId} to queue {Queue}", message.JobId, QueueVideoUploaded);
    }

    public async ValueTask DisposeAsync()
    {
        if (_channel is not null) await _channel.CloseAsync();
        if (_connection is not null) await _connection.CloseAsync();
    }
}
