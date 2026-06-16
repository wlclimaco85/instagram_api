$base = 'http://127.0.0.1:8500'

function Testar($nome, $url) {
    Write-Output ("=== " + $nome + " ===")
    try {
        $r = Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 90
        $obj = $r.Content | ConvertFrom-Json
        Write-Output ("count: " + $obj.count)
        $obj | ConvertTo-Json -Depth 2 -Compress | ForEach-Object { $_.Substring(0, [Math]::Min(400, $_.Length)) }
    } catch {
        Write-Output ("ERRO: " + $_.Exception.Message)
    }
    Write-Output ""
}

Testar "FOLLOWERS (5)" ($base + '/followers?username=silvva_bia&amount=5')
Testar "FOLLOWING (5)" ($base + '/following?username=silvva_bia&amount=5')
