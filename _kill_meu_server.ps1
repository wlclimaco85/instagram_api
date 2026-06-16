# Mata apenas o server de teste do agente (iniciado com '-u server.py').
# O server do usuario roda no venv SEM '-u', entao nao e afetado.
$alvos = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
    $_.CommandLine -like "*-u server.py*"
}
foreach ($p in $alvos) {
    Write-Output ("Encerrando PID " + $p.ProcessId + " :: " + $p.CommandLine)
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 1
if (Get-NetTCPConnection -LocalPort 8500 -State Listen -ErrorAction SilentlyContinue) {
    Write-Output "Porta 8500 AINDA OCUPADA"
} else {
    Write-Output "Porta 8500 LIVRE"
}
