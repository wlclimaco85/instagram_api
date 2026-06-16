try {
    $r = Invoke-WebRequest 'http://127.0.0.1:8500/comments?media_id=3918726773265025717' -UseBasicParsing -TimeoutSec 90
    Write-Output $r.Content
} catch {
    $resp = $_.Exception.Response
    if ($resp) {
        $sr = New-Object System.IO.StreamReader($resp.GetResponseStream())
        Write-Output ("BODY: " + $sr.ReadToEnd())
    } else {
        Write-Output ("ERRO: " + $_.Exception.Message)
    }
}
