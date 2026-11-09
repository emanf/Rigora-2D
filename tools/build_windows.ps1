# Bootstrap the native builder without changing the user's development environment or PATH.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$buildArguments = @($args)
try {
    $uvCommand = Get-Command uv -ErrorAction SilentlyContinue
    $localUv = Join-Path $projectRoot '.build-tools\uv\uv.exe'
    if ($uvCommand) {
        $uvPath = $uvCommand.Source
    } elseif (Test-Path -LiteralPath $localUv) {
        $uvPath = $localUv
    } else {
        $bootstrapDirectory = Join-Path $projectRoot '.build-tools'
        New-Item -ItemType Directory -Path $bootstrapDirectory -Force | Out-Null
        $installer = Join-Path $bootstrapDirectory 'install-uv.ps1'
        Write-Host 'Installing uv locally for the Rigora build...'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri 'https://astral.sh/uv/install.ps1' -OutFile $installer
        $env:UV_INSTALL_DIR = Split-Path -Parent $localUv
        $env:UV_NO_MODIFY_PATH = '1'
        & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $installer
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $localUv)) {
            throw 'uv installation failed. See the installer output above.'
        }
        $uvPath = $localUv
    }
    & $uvPath run --no-project --python 3.12 (Join-Path $PSScriptRoot 'build_app.py') --uv $uvPath @buildArguments
    exit $LASTEXITCODE
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
