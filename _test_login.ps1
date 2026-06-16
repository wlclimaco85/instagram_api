try {
    $r = Invoke-WebRequest 'http://127.0.0.1:8500/login_status' -UseBasicParsing
    Write-Output $r.Content
} catch {
    Write-Output ("ERRO: " + $_.Exception.Message)
}
