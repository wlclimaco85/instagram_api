$r = Invoke-WebRequest 'http://127.0.0.1:8500/profile?username=silvva_bia' -UseBasicParsing
$r.Content | Out-File -FilePath 'C:\App_Academia\instagram_api\_resp_bia.json' -Encoding utf8
Get-Content 'C:\App_Academia\instagram_api\_resp_bia.json' -Encoding utf8
