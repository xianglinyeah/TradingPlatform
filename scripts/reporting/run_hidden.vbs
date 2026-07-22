' Launches import_latency_live.ps1 with zero visible window.
' WScript.Shell.Run's windowStyle=0 (hidden) genuinely suppresses the
' console host, unlike "powershell.exe -WindowStyle Hidden" alone which can
' still flash briefly. No admin rights required (unlike an S4U scheduled
' task principal, which needs "Log on as a batch job" rights to register).
Set objShell = CreateObject("WScript.Shell")
objShell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""D:\TradingPlatform\scripts\reporting\import_latency_live.ps1""", 0, True
