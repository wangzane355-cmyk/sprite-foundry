param(
    [Parameter(Mandatory)]
    [ValidatePattern('^\d+\.\d+\.\d+(-[0-9A-Za-z][0-9A-Za-z.-]*)?$')]
    [string]$Version,
    [Parameter(Mandatory)]
    [string]$OutputDirectory,
    [string]$WorkDirectory = [IO.Path]::GetTempPath(),
    [string]$Python = (Join-Path $PSScriptRoot '.venv\Scripts\python.exe')
)

$ErrorActionPreference = 'Stop'
$platform = & $Python -c "import sysconfig; print(sysconfig.get_platform())"
if ($LASTEXITCODE -ne 0 -or $platform -ne 'win-amd64') {
    throw 'Build with Windows x64 Python and install requirements-windows.txt first.'
}

$output = (New-Item -ItemType Directory -Path $OutputDirectory -Force).FullName
$zipName = "SpriteFoundry-$Version-Windows-x64.zip"
$archive = Join-Path $output $zipName
$checksum = "$archive.sha256"
if ((Test-Path -LiteralPath $archive) -or (Test-Path -LiteralPath $checksum)) {
    throw "Output already exists for version $Version. Choose a new output directory."
}

$work = Join-Path $WorkDirectory ('sprite-foundry-build-' + [guid]::NewGuid().ToString('N'))
$dist = Join-Path $work 'dist'
New-Item -ItemType Directory -Path $work | Out-Null
Push-Location $PSScriptRoot
try {
    & $Python -m PyInstaller --onedir --console --noupx --name SpriteFoundry `
        --specpath $work --workpath (Join-Path $work 'work') --distpath $dist `
        --add-data "${PSScriptRoot}/web:web" --add-data "${PSScriptRoot}/samples:samples" app.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed. Build files are in $work"
    }

    $bundle = Join-Path $dist 'SpriteFoundry'
    $licenseCode = @'
from importlib.metadata import distribution
from pathlib import Path
import json
import sys

notices = {"Python": [str(Path(sys.base_prefix) / "LICENSE.txt")]}
for package in ("Pillow", "PyInstaller"):
    metadata = distribution(package)
    notices[package] = [
        str(metadata.locate_file(path))
        for path in metadata.files
        if "licenses" in path.parts
    ]
print(json.dumps(notices))
'@
    $noticeJson = & $Python -c $licenseCode
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not locate bundled runtime notices.'
    }
    $notices = $noticeJson | ConvertFrom-Json
    foreach ($notice in $notices.PSObject.Properties) {
        if ($notice.Value.Count -eq 0) {
            throw "No runtime notices found for $($notice.Name)."
        }
        $destination = Join-Path $bundle "ThirdPartyNotices/$($notice.Name)"
        New-Item -ItemType Directory -Path $destination -Force | Out-Null
        foreach ($license in $notice.Value) {
            Copy-Item -LiteralPath $license -Destination $destination
        }
    }

    @"
Sprite Foundry $Version | Windows x64

1. Extract the whole ZIP to a folder you can write to.
2. Double-click SpriteFoundry.exe. It opens the local workbench in your browser.
3. Keep the launcher window open while working. Close it when you are done.

No installation or separate Python runtime is needed.
If the browser does not open, use the local URL printed in the launcher window.
The .data folder next to the EXE contains your local library.
Keep _internal next to the EXE, and back up .data before replacing the folder.

Load the sample images to try previews and Unity export without an account.
The in-app Generate button uses the OpenAI Images API and needs an API key with available credit.
"@ | Set-Content -LiteralPath (Join-Path $bundle 'START-HERE.txt') -Encoding utf8

    $stagedZip = Join-Path $work $zipName
    & $Python -m zipfile -c $stagedZip $bundle
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not create the release ZIP.'
    }
    [IO.File]::Copy($stagedZip, $archive, $false)
    $digest = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    "$digest  $zipName" | Set-Content -LiteralPath $checksum -Encoding ascii
    Write-Output $archive
    Write-Output $checksum
}
finally {
    Pop-Location
}
