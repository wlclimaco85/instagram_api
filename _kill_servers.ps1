# Mata apenas processos python rodando server.py do instagram_api (confirmado por CommandLine)
$alvos = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
    $_.CommandLine -like "*server.py*"
}
foreach ($p in $alvos) {
    Write-Output ("Encerrando PID " + $p.ProcessId + " :: " + $p.CommandLine)
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 1
$restante = Get-NetTCPConnection -LocalPort 8500 -State Listen -ErrorAction SilentlyContinue
if ($restante) {
    Write-Output ("AINDA OCUPADA por PID " + $restante.OwningProcess)
} else {
    Write-Output "Porta 8500 livre"
}
