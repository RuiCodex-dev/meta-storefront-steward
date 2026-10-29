# Muse Glimmer 30B (official Q4_K_M GGUF) on this PC with llama.cpp. CPU-only by default so the shared GPU
# stays free; pass -Gpu <layers> to offload layers during a reserved GPU slot.
#
# Prints the server PID and, with -PidFile, also writes it there. Callers must NOT read the PID through a pipe
# (`PID=$(powershell ... | tail -1)`): Start-Process with redirection creates the server with inherited handles,
# so the server holds the caller's pipe open and the reader waits for ever. That is exactly how the 27 Oct GPU slot
# hung for 4 h 20 min. Run this with stdout to NUL and read -PidFile instead.
param([int]$Gpu = 0, [int]$Port = 8088, [string]$Lora = "", [int]$Budget = 256, [string]$PidFile = "")
$env:LLAMA_ARG_CHAT_TEMPLATE_KWARGS = '{"reasoning_strength":"low"}'
if ($Gpu -eq 0) { $env:CUDA_VISIBLE_DEVICES = "" }
$log = "C:\Users\Admin\Desktop\Software\Hackathons\meta-storefront-steward\data\logs"
$srvArgs = @('-m', 'D:\models\Muse-Glimmer-30B-GGUF\Muse-Glimmer-30B-KQuant-17GB-Q4_K_M.gguf',
          '--host', '127.0.0.1', '--port', "$Port", '--jinja', '-c', '4096', '-np', '1', '-t', '8',
          '-ngl', "$Gpu", '--temp', '0', '--reasoning-budget', "$Budget")
if ($Lora) { $srvArgs += @('--lora', $Lora) }
$p = Start-Process -FilePath 'D:\models\llama-cpp-b11909\llama-server.exe' -ArgumentList $srvArgs `
     -RedirectStandardError "$log\glimmer_server.err" -RedirectStandardOutput "$log\glimmer_server.out" `
     -WindowStyle Hidden -PassThru
if ($PidFile) { Set-Content -Path $PidFile -Value $p.Id -Encoding ascii }
Start-Sleep 3
if (-not $p.HasExited) { $p.PriorityClass = 'BelowNormal' }
$p.Id
