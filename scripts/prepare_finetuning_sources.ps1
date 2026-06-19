param(
    [string]$ExternalRoot = "C:\Users\User\Desktop\pfaEXTRACT",
    [string]$GeneratedZip = "C:\Users\User\Downloads\data genrer.zip"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$FineRoot = Join-Path $ProjectRoot "Data\finetuning"
$RawRoot = Join-Path $FineRoot "raw"
$ManifestDir = Join-Path $FineRoot "manifests"
$ManifestPath = Join-Path $ManifestDir "raw_sources.jsonl"

New-Item -ItemType Directory -Force -Path $ManifestDir | Out-Null
if (Test-Path -LiteralPath $ManifestPath) {
    Clear-Content -LiteralPath $ManifestPath
}
else {
    New-Item -ItemType File -Force -Path $ManifestPath | Out-Null
}

function Add-ManifestRow {
    param(
        [string]$Source,
        [string]$Target,
        [string]$Dataset,
        [string]$DocumentType,
        [string]$Split = ""
    )
    $row = [ordered]@{
        source = $Source
        target = $Target
        dataset = $Dataset
        document_type = $DocumentType
        split = $Split
    }
    Add-Content -Path $ManifestPath -Value ($row | ConvertTo-Json -Compress) -Encoding UTF8
}

function Copy-DirectoryIfExists {
    param(
        [string]$Source,
        [string]$Target,
        [string]$Dataset,
        [string]$DocumentType,
        [string]$Split = ""
    )
    if (-not (Test-Path -LiteralPath $Source)) {
        Write-Host "Source introuvable: $Source" -ForegroundColor Yellow
        return
    }
    New-Item -ItemType Directory -Force -Path $Target | Out-Null
    Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $Target -Recurse -Force
    }
    Add-ManifestRow -Source $Source -Target $Target -Dataset $Dataset -DocumentType $DocumentType -Split $Split
}

function Copy-SupportedFiles {
    param(
        [string]$Source,
        [string]$Target,
        [string]$Dataset,
        [string]$DocumentType,
        [switch]$RenameSequential,
        [string]$Prefix = "doc"
    )
    if (-not (Test-Path -LiteralPath $Source)) {
        Write-Host "Source introuvable: $Source" -ForegroundColor Yellow
        return
    }
    New-Item -ItemType Directory -Force -Path $Target | Out-Null
    $extensions = @(".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp")
    $index = 1
    Get-ChildItem -LiteralPath $Source -File | Where-Object { $extensions -contains $_.Extension.ToLowerInvariant() } | ForEach-Object {
        if ($RenameSequential) {
            $targetName = "{0}_{1:D6}{2}" -f $Prefix, $index, $_.Extension.ToLowerInvariant()
            $index += 1
        }
        else {
            $targetName = $_.Name
        }
        $targetPath = Join-Path $Target $targetName
        Copy-Item -LiteralPath $_.FullName -Destination $targetPath -Force
        Add-ManifestRow -Source $_.FullName -Target $targetPath -Dataset $Dataset -DocumentType $DocumentType
    }
}

Write-Host "Preparation Data/finetuning..." -ForegroundColor Green

$sroieRoot = Join-Path $ExternalRoot "SROIE2019"
foreach ($split in @("train", "test")) {
    foreach ($part in @("img", "box", "entities")) {
        Copy-DirectoryIfExists `
            -Source (Join-Path $sroieRoot "$split\$part") `
            -Target (Join-Path $RawRoot "kaggle\receipt_sroie\$split\$part") `
            -Dataset "sroie2019" `
            -DocumentType "receipt" `
            -Split $split
    }
}

Copy-SupportedFiles `
    -Source (Join-Path $ExternalRoot "lbmaske") `
    -Target (Join-Path $RawRoot "kaggle\medical_lbmaske\images") `
    -Dataset "lbmaske" `
    -DocumentType "medical_lab_report" `
    -RenameSequential `
    -Prefix "medical_lbmaske"

$currentRaw = Join-Path $ProjectRoot "Data\raw_Data"
Copy-SupportedFiles -Source (Join-Path $currentRaw "electricite") -Target (Join-Path $RawRoot "custom\steg\electricite") -Dataset "custom_raw_data" -DocumentType "steg_invoice"
Copy-SupportedFiles -Source (Join-Path $currentRaw "electricite copy") -Target (Join-Path $RawRoot "custom\steg\electricite_copy") -Dataset "custom_raw_data" -DocumentType "steg_invoice"
Copy-SupportedFiles -Source (Join-Path $currentRaw "medical") -Target (Join-Path $RawRoot "custom\medical\medical") -Dataset "custom_raw_data" -DocumentType "medical_lab_report"
Copy-SupportedFiles -Source (Join-Path $currentRaw "analyse_medical") -Target (Join-Path $RawRoot "custom\medical\analyse_medical") -Dataset "custom_raw_data" -DocumentType "medical_lab_report"
Copy-SupportedFiles -Source (Join-Path $currentRaw "ticketsCasse") -Target (Join-Path $RawRoot "custom\receipt\tickets_caisse") -Dataset "custom_raw_data" -DocumentType "receipt"

if (Test-Path -LiteralPath $GeneratedZip) {
    $tmpGenerated = Join-Path $RawRoot "generated\_tmp_extract"
    if (Test-Path -LiteralPath $tmpGenerated) {
        Remove-Item -LiteralPath $tmpGenerated -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $tmpGenerated | Out-Null
    Expand-Archive -LiteralPath $GeneratedZip -DestinationPath $tmpGenerated -Force
    $generatedRoot = Join-Path $tmpGenerated "data genrer"
    Copy-SupportedFiles -Source (Join-Path $generatedRoot "facture steg") -Target (Join-Path $RawRoot "generated\steg") -Dataset "generated_zip" -DocumentType "steg_invoice"
    Copy-SupportedFiles -Source (Join-Path $generatedRoot "medical") -Target (Join-Path $RawRoot "generated\medical") -Dataset "generated_zip" -DocumentType "medical_lab_report"
    Remove-Item -LiteralPath $tmpGenerated -Recurse -Force
}
else {
    Write-Host "Zip genere introuvable: $GeneratedZip" -ForegroundColor Yellow
}

New-Item -ItemType Directory -Force -Path `
    (Join-Path $FineRoot "processed\inputs\receipt"), `
    (Join-Path $FineRoot "processed\inputs\medical"), `
    (Join-Path $FineRoot "processed\inputs\steg"), `
    (Join-Path $FineRoot "processed\inputs\supplier"), `
    (Join-Path $FineRoot "processed\ground_truth\receipt"), `
    (Join-Path $FineRoot "processed\ground_truth\medical"), `
    (Join-Path $FineRoot "processed\ground_truth\steg"), `
    (Join-Path $FineRoot "processed\ground_truth\supplier"), `
    (Join-Path $FineRoot "splits") | Out-Null

Write-Host "Sources fine-tuning preparees dans: $FineRoot" -ForegroundColor Green
Write-Host "Manifest: $ManifestPath" -ForegroundColor Green
