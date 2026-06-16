$conns = Get-NetTCPConnection -LocalPort 8500 -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conns) {
    Write-Output ("Porta 8500 -> PID " + $c.OwningProcess)
}
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ForEach-Object {
    Write-Output ("PID " + $_.ProcessId + " :: " + $_.CommandLine)
}
