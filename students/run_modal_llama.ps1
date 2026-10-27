# Detached launcher for the Modal Glimmer job: survives the calling shell; prints the client PID.
$env:MODAL_CONFIG_PATH = 'C:\Users\Admin\.ruicodex-keys\modal.toml'
$env:MODAL_PROFILE = 'ruicodex'
$env:PYTHONIOENCODING = 'utf-8'
$P = 'C:\Users\Admin\Desktop\Software\Hackathons\meta-storefront-steward'
$p = Start-Process -FilePath 'C:\Users\Admin\.venvs\cloudgpu\Scripts\python.exe' `
     -ArgumentList "$P\students\modal_llama.py", '--stage', 'all' -WorkingDirectory $P `
     -RedirectStandardOutput "$P\data\logs\modal_llama.log" -RedirectStandardError "$P\data\logs\modal_llama.err" `
     -WindowStyle Hidden -PassThru
$p.Id
