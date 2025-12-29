Set WshShell = CreateObject("WScript.Shell")
strPath = WshShell.CurrentDirectory
' Construct the command to run the manager using the virtual environment
' 0 hides the window, true waits for it to finish (though it's a server)
strCommand = """" & strPath & "\venv\Scripts\python.exe"" """ & strPath & "\manager.py"""
WshShell.Run strCommand, 0, False
