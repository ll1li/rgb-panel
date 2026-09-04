#Requires -Version 7
# Stage the freshly built OpenRGB into openrgb-custom and test-detect the GPU.
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
$src   = Join-Path $PSScriptRoot 'OpenRGB\release'
$dst   = Join-Path (Split-Path $PSScriptRoot -Parent) 'openrgb-custom'
$stock = 'C:\Program Files\OpenRGB'

if (-not (Test-Path "$src\OpenRGB.exe")) { throw "no OpenRGB.exe in $src" }
if (Test-Path $dst) { & trash $dst; Start-Sleep 1 }
New-Item -ItemType Directory -Path $dst | Out-Null

# Ship only what the stock install ships (exe, Qt runtime, plugins, hidapi/libusb, PawnIO bits).
Copy-Item "$src\OpenRGB.exe" $dst
foreach ($d in 'platforms','styles','imageformats') { Copy-Item "$src\$d" $dst -Recurse }
Get-ChildItem $src -Filter *.dll | Copy-Item -Destination $dst
foreach ($f in Get-ChildItem $stock -File) {
    if (-not (Test-Path "$dst\$($f.Name)")) { Copy-Item $f.FullName $dst; "copied from stock: $($f.Name)" }
}

"== file comparison (custom vs stock) =="
$c = Get-ChildItem $dst -Recurse -File | ForEach-Object { $_.FullName.Substring($dst.Length) }
$s = Get-ChildItem $stock -Recurse -File | ForEach-Object { $_.FullName.Substring($stock.Length) }
"only in custom: " + (($c | Where-Object { $_ -notin $s }) -join ', ')
"only in stock : " + (($s | Where-Object { $_ -notin $c }) -join ', ')
"custom exe: " + (Get-Item "$dst\OpenRGB.exe").Length + " bytes"
& "$dst\OpenRGB.exe" --version | Out-Null

"== test run =="
Get-Process OpenRGB -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 2
$p = Start-Process -FilePath "$dst\OpenRGB.exe" -ArgumentList '--server','--noautoconnect','--loglevel','6' -PassThru
"test pid $($p.Id)"
Start-Sleep 30
$log = Get-ChildItem "$env:APPDATA\OpenRGB\logs" | Sort-Object LastWriteTime | Select-Object -Last 1
"log: $($log.Name)"
Get-Content $log.FullName | Select-Object -First 3
"-- GPU related lines --"
Get-Content $log.FullName | Select-String -Pattern 'GTX 1080|MSI GPU|MSI GeForce|NvAPI|10DE:1B80' | ForEach-Object { $_.Line -replace ' \[[A-Za-z_\\]+\.cpp:\d+\]', '' } | Select-Object -First 40
"-- rgb list --"
rgb.cmd list
