FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS base
WORKDIR /app
EXPOSE 8080

FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY ["VideoSubtitle.API.csproj", "."]
RUN dotnet restore "./VideoSubtitle.API.csproj"
COPY . .
RUN dotnet build "VideoSubtitle.API.csproj" -c Release -o /app/build

FROM build AS publish
RUN dotnet publish "VideoSubtitle.API.csproj" -c Release -o /app/publish /p:UseAppHost=false

FROM base AS final
WORKDIR /app
COPY --from=publish /app/publish .
ENTRYPOINT ["dotnet", "VideoSubtitle.API.dll"]
