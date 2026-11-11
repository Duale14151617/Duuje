FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY src/Duale.Api/ ./
RUN dotnet publish -c Release -o /out /p:UseAppHost=false
FROM mcr.microsoft.com/dotnet/aspnet:8.0
WORKDIR /app
COPY --from=build /out .
# Run unprivileged; the files volume must be writable by this user.
RUN useradd --system --uid 10001 --no-create-home duale && mkdir -p /data/files && chown -R duale /data/files
USER 10001
ENV ASPNETCORE_URLS=http://+:8080 DOTNET_EnableDiagnostics=0
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 CMD ["dotnet", "Duale.Api.dll", "--healthcheck"]
ENTRYPOINT ["dotnet", "Duale.Api.dll"]
