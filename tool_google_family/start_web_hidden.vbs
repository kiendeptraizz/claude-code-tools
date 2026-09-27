' Chay web server NGAM (khong hien cua so console).
' Tu chay khi dang nhap Windows (qua shortcut trong Startup).
Set fso = CreateObject("Scripting.FileSystemObject")
projDir = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = projDir
cmd = """" & projDir & "\venv\Scripts\pythonw.exe"" -m uvicorn web:app --app-dir """ & projDir & """ --host 0.0.0.0 --port 8500"
sh.Run cmd, 0, False
