' Stardew Valley Mod Manager launcher (ASCII only: safe for any code page)
' Double-clicked by the desktop shortcut. Shows a console only when it has to
' install the PySide6 dependency (first run), otherwise starts with no window.
Option Explicit

Dim sh, fso, base, py, pyw, rc, i, cands
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

base = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = base

Function RunHidden(cmd)
    Dim code
    On Error Resume Next
    code = sh.Run(cmd, 0, True)
    If Err.Number <> 0 Then
        Err.Clear
        code = -1
    End If
    On Error GoTo 0
    RunHidden = code
End Function

' 1) find a real Python (skip the Microsoft Store placeholder)
py = ""
cands = Array("py", "python")
For i = 0 To UBound(cands)
    If py = "" Then
        If RunHidden("cmd /c " & cands(i) & " -c ""import sys""") = 0 Then
            py = cands(i)
        End If
    End If
Next

If py = "" Then
    MsgBox "Python was not found." & vbCrLf & vbCrLf & _
           "Please install Python 3.10 or newer from python.org" & vbCrLf & _
           "and tick ""Add python.exe to PATH"" during setup.", _
           16, "Stardew Mod Manager"
    sh.Run "https://www.python.org/downloads/", 1, False
    WScript.Quit 0
End If

' 2) make sure the GUI dependency exists; install it in a visible window if not
If RunHidden("cmd /c " & py & " -c ""import PySide6""") <> 0 Then
    rc = sh.Run("cmd /c " & py & " -m pip install PySide6 -i https://pypi.tuna.tsinghua.edu.cn/simple", 1, True)
    If RunHidden("cmd /c " & py & " -c ""import PySide6""") <> 0 Then
        MsgBox "Failed to install PySide6." & vbCrLf & vbCrLf & _
               "Please run this command in a terminal:" & vbCrLf & _
               py & " -m pip install PySide6", 16, "Stardew Mod Manager"
        WScript.Quit 1
    End If
End If

' 3) start the GUI without any console window
pyw = "pythonw"
If LCase(py) = "py" Then pyw = "pyw"
sh.Run """" & pyw & """ """ & base & "\main.py""", 0, False
