# 恢复原始环境变量配置脚本
Write-Host "恢复原始环境变量..." -ForegroundColor Green

# 恢复DeepSeek配置
$env:OPENAI_API_KEY = "sk-7a09668a2d544bf9aa2914d16bf494b1"
$env:OPENAI_BASE_URL = "https://api.deepseek.com"

Write-Host "环境变量已恢复为DeepSeek配置" -ForegroundColor Green
Write-Host "OPENAI_API_KEY: $env:OPENAI_API_KEY" -ForegroundColor Cyan  
Write-Host "OPENAI_BASE_URL: $env:OPENAI_BASE_URL" -ForegroundColor Cyan



