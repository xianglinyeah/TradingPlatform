' Launches import_orders_live.ps1 with zero visible window (same technique
' as run_hidden.vbs for the latency import -- see that file for why).
Set objShell = CreateObject("WScript.Shell")
objShell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""D:\TradingPlatform\scripts\reporting\import_orders_live.ps1""", 0, True
