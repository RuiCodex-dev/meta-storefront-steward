# Detached launcher for the Modal Glimmer job: survives the calling shell; prints the client PID.
$env:MODAL_CONFIG_PATH = 'C:\Users\Admin\.ruicodex-keys\modal.toml'
$env:MODAL_PROFILE = 'ruicodex'
$env:PYTHONIOENCODING = 'utf-8'
$P = 'C:\Users\Admin\Desktop\Software\Hackathons\meta-storefront-steward'
$p = Start-Process -FilePath 'C:\Users\Admin\.venvs\cloudgpu\Scripts\python.exe' `
     -ArgumentList "$P\students\modal_glimmer.py", '--stage', 'all' -WorkingDirectory $P `
     -RedirectStandardOutput "$P\data\logs\modal_glimmer.log" -RedirectStandardError "$P\data\logs\modal_glimmer.err" `
     -WindowStyle Hidden -PassThru
$p.Id
