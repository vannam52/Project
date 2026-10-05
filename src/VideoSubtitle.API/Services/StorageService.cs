using Minio;
using Minio.DataModel.Args;

namespace VideoSubtitle.API.Services;

public interface IStorageService
{
    Task<string> UploadFileAsync(Stream fileStream, string fileName, string contentType, CancellationToken ct = default);
    Task<Stream> DownloadFileAsync(string storageKey, CancellationToken ct = default);
    Task<string> GetPresignedUrlAsync(string storageKey, int expirySeconds = 3600);
    Task DeleteFileAsync(string storageKey, CancellationToken ct = default);
    Task EnsureBucketExistsAsync(CancellationToken ct = default);
}

public class MinioStorageService : IStorageService
{
    private readonly IMinioClient _minioClient;
    private readonly string _bucketName;
    private readonly ILogger<MinioStorageService> _logger;

    public MinioStorageService(IMinioClient minioClient, IConfiguration config, ILogger<MinioStorageService> logger)
    {
        _minioClient = minioClient;
        _bucketName  = config["MinIO:BucketName"] ?? "videos";
        _logger      = logger;
    }

    public async Task<string> UploadFileAsync(Stream fileStream, string fileName, string contentType, CancellationToken ct = default)
    {
        var storageKey = $"originals/{Guid.NewGuid()}/{fileName}";
        _logger.LogInformation("Uploading {FileName} → MinIO/{Key}", fileName, storageKey);

        // FIX: stream có thể không biết Length (chunked upload) — buffer vào MemoryStream
        Stream uploadStream = fileStream;
        long size;
        if (!fileStream.CanSeek)
        {
            var ms = new MemoryStream();
            await fileStream.CopyToAsync(ms, ct);
            ms.Position = 0;
            uploadStream = ms;
        }
        size = uploadStream.Length;

        var args = new PutObjectArgs()
            .WithBucket(_bucketName)
            .WithObject(storageKey)
            .WithStreamData(uploadStream)
            .WithObjectSize(size)
            .WithContentType(contentType);

        await _minioClient.PutObjectAsync(args, ct);
        return storageKey;
    }

    public async Task<Stream> DownloadFileAsync(string storageKey, CancellationToken ct = default)
    {
        var memStream = new MemoryStream();
        var args = new GetObjectArgs()
            .WithBucket(_bucketName)
            .WithObject(storageKey)
            .WithCallbackStream(async (stream, token) =>
            {
                await stream.CopyToAsync(memStream, token);
            });

        await _minioClient.GetObjectAsync(args, ct);
        memStream.Position = 0;
        return memStream;
    }

    public async Task<string> GetPresignedUrlAsync(string storageKey, int expirySeconds = 3600)
    {
        var args = new PresignedGetObjectArgs()
            .WithBucket(_bucketName)
            .WithObject(storageKey)
            .WithExpiry(expirySeconds);

        return await _minioClient.PresignedGetObjectAsync(args);
    }

    public async Task DeleteFileAsync(string storageKey, CancellationToken ct = default)
    {
        var args = new RemoveObjectArgs()
            .WithBucket(_bucketName)
            .WithObject(storageKey);
        await _minioClient.RemoveObjectAsync(args, ct);
    }

    public async Task EnsureBucketExistsAsync(CancellationToken ct = default)
    {
        var exists = await _minioClient.BucketExistsAsync(
            new BucketExistsArgs().WithBucket(_bucketName), ct);

        if (!exists)
        {
            await _minioClient.MakeBucketAsync(
                new MakeBucketArgs().WithBucket(_bucketName), ct);
            _logger.LogInformation("Created MinIO bucket: {Bucket}", _bucketName);
        }
    }
}
