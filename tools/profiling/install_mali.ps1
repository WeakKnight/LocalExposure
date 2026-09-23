$ErrorActionPreference = 'Stop'
$toolRoot = Join-Path $PSScriptRoot '../../.tools/mobile'
$toolRoot = [IO.Path]::GetFullPath($toolRoot)
New-Item -ItemType Directory -Force $toolRoot | Out-Null
$package = Join-Path $toolRoot 'Arm_Performance_Studio_2026.5_windows_x86-64.msi'
$url = 'https://artifacts.tools.arm.com/arm-performance-studio/2026.5/Arm_Performance_Studio_2026.5_windows_x86-64.msi'
$expected = 'f47d3c3e2972cb45902ae746cca99d9d0eb3053cb8a993afa68d269a873e9859'
if (!(Test-Path -LiteralPath $package)) {
    & curl.exe -fSL --retry 2 $url -o $package
    if ($LASTEXITCODE -ne 0) { throw 'Arm package download failed' }
}
if ((Get-FileHash -LiteralPath $package -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
    throw 'Arm package SHA256 mismatch; expected the official 2026.5 manifest hash'
}
$destination = Join-Path $toolRoot 'arm-2026.5'
# Administrative extraction: keep tools local without installing the whole suite or changing PATH.
$arguments = '/a "' + $package + '" /qn TARGETDIR="' + $destination + '" /l*v "' + (Join-Path $toolRoot 'arm-extract.log') + '"'
$process = Start-Process msiexec.exe -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "Arm extraction failed: $($process.ExitCode)" }
Get-ChildItem -LiteralPath $destination -Recurse -Filter malioc.exe | Select-Object -ExpandProperty FullName
