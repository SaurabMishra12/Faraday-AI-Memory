<# 
    deploy.ps1 — One-command Faraday Cloud deployment.
    
    Usage:
        .\deploy.ps1 push     # Upload data to Supabase only
        .\deploy.ps1 deploy   # Push data + deploy to Cloud Run
        .\deploy.ps1 full     # Push + build + deploy + test
    
    Prerequisites:
        - Python venv activated with supabase installed
        - gcloud CLI authenticated (for Cloud Run deployment)
#>

param(
    [Parameter(Position=0)]
    [ValidateSet("push", "deploy", "full")]
    [string]$Action = "full"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$AiMemoryDir = $PSScriptRoot

# ─────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────
$GCP_PROJECT = "faraday-memory-cloud"
$GCP_REGION = "asia-south1"  # Mumbai — closest to India
$SERVICE_NAME = "faraday-mcp"
$FARADAY_API_KEY = "frdy_" + [System.Guid]::NewGuid().ToString("N").Substring(0, 24)

# ─────────────────────────────────────────────────────
# Step 1: Push data to Supabase
# ─────────────────────────────────────────────────────
function Push-Data {
    Write-Host "`n📦 Pushing data to Supabase Storage..." -ForegroundColor Cyan
    
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        & $venvPython (Join-Path $AiMemoryDir "sync.py") push
    } else {
        python (Join-Path $AiMemoryDir "sync.py") push
    }
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Data push failed!" -ForegroundColor Red
        exit 1
    }
    Write-Host "✅ Data pushed to Supabase." -ForegroundColor Green
}

# ─────────────────────────────────────────────────────
# Step 2: Deploy to Cloud Run
# ─────────────────────────────────────────────────────
function Deploy-CloudRun {
    Write-Host "`n🚀 Deploying to Google Cloud Run..." -ForegroundColor Cyan
    
    # Check gcloud auth
    $account = gcloud auth list --filter="status=ACTIVE" --format="value(account)" 2>$null
    if (-not $account) {
        Write-Host "⚠️ Not authenticated with gcloud. Running 'gcloud auth login'..." -ForegroundColor Yellow
        gcloud auth login
    }
    
    # Set project
    gcloud config set project $GCP_PROJECT 2>$null
    
    # Enable required APIs
    Write-Host "  Enabling Cloud Run API..." -ForegroundColor Gray
    gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com 2>$null
    
    # Deploy from source (Cloud Build handles Dockerfile)
    Write-Host "  Building and deploying container..." -ForegroundColor Gray
    gcloud run deploy $SERVICE_NAME `
        --source $AiMemoryDir `
        --region $GCP_REGION `
        --platform managed `
        --allow-unauthenticated `
        --memory 2Gi `
        --cpu 1 `
        --min-instances 0 `
        --max-instances 2 `
        --timeout 300 `
        --set-env-vars "SUPABASE_URL=https://qwxagrmoryojholseclm.supabase.co" `
        --set-env-vars "SUPABASE_KEY=$env:SUPABASE_KEY" `
        --set-env-vars "FARADAY_API_KEY=$FARADAY_API_KEY" `
        --set-env-vars "SUPABASE_BUCKET=faraday-memory"
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Cloud Run deployment failed!" -ForegroundColor Red
        exit 1
    }
    
    # Get service URL
    $serviceUrl = gcloud run services describe $SERVICE_NAME --region $GCP_REGION --format="value(status.url)"
    
    Write-Host "`n" -NoNewline
    Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Green
    Write-Host "  ✅ DEPLOYMENT COMPLETE!" -ForegroundColor Green
    Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Green
    Write-Host "`n  Service URL:  $serviceUrl" -ForegroundColor White
    Write-Host "  SSE Endpoint: $serviceUrl/sse" -ForegroundColor White
    Write-Host "  API Key:      $FARADAY_API_KEY" -ForegroundColor Yellow
    Write-Host "`n  📱 Claude Phone Config:" -ForegroundColor Cyan
    Write-Host @"
  {
    "mcpServers": {
      "faraday": {
        "command": "npx",
        "args": [
          "-y", "mcp-remote",
          "$serviceUrl/sse"
        ]
      }
    }
  }
"@ -ForegroundColor Gray
    Write-Host ""
}

# ─────────────────────────────────────────────────────
# Execute
# ─────────────────────────────────────────────────────
switch ($Action) {
    "push" {
        Push-Data
    }
    "deploy" {
        Deploy-CloudRun
    }
    "full" {
        Push-Data
        Deploy-CloudRun
    }
}
